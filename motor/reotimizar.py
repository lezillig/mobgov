# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 4 · agent-reotimizacao
Reotimização do dia: falta informada, cancelamento e reinserção da fila.

O planejamento noturno é só metade do trabalho. O que separa um sistema
moderno (RideCo reotimiza a cada 20 s; Spare, a cada minuto) de uma planilha é
o que acontece **depois que o dia começa**:

- o responsável avisa que o aluno não vai hoje → a parada sai da rota e o
  veículo economiza km e minutos;
- o usuário do porta a porta cancela → a capacidade liberada volta na hora
  para o pool e absorve alguém da fila de espera;
- tudo isso com um DIFF LEGÍVEL: "Rota 7: parada P014 removida, −4,2 km e
  −6 min; a rota agora cabe num micro-ônibus".

Este módulo roda em Python puro — sem OR-Tools. Reotimizar uma rota isolada é
um problema pequeno (dezenas de paradas), e resolver por vizinho mais próximo
+ 2-opt responde em milissegundos, o que é o requisito real: o despachante
está no telefone com a mãe do aluno. A reotimização global continua com o
OR-Tools, à noite.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import tempos as tempos_mod
from dados.demanda_pcd import limite_tempo_bordo_min


# ------------------------------------------------------------- utilidades ---
def _matriz(coords, provedor, partida_min, zonas=None):
    return provedor.matriz(coords, partida_min=partida_min, zonas=zonas)


def avaliar_sequencia(coords, ordem, dist, tempo, servicos=None) -> tuple:
    """km e minutos de um circuito depósito → paradas → depósito."""
    servicos = servicos or [0] * len(coords)
    km, minutos = 0.0, 0
    caminho = [0] + list(ordem) + [0]
    for a, b in zip(caminho, caminho[1:]):
        km += dist[a][b]
        minutos += tempo[a][b] + servicos[a]
    return round(km, 1), minutos


def vizinho_mais_proximo(ordem, dist) -> list:
    restantes, atual, saida = list(ordem), 0, []
    while restantes:
        prox = min(restantes, key=lambda n: dist[atual][n])
        saida.append(prox)
        restantes.remove(prox)
        atual = prox
    return saida


def duas_opt(ordem, dist, limite_iteracoes: int = 60) -> list:
    """2-opt clássico: desfaz cruzamentos até não melhorar mais.

    Determinístico e barato — para 20 paradas roda em microssegundos.
    """
    melhor = list(ordem)

    def custo(seq):
        caminho = [0] + seq + [0]
        return sum(dist[a][b] for a, b in zip(caminho, caminho[1:]))

    melhor_custo = custo(melhor)
    for _ in range(limite_iteracoes):
        melhorou = False
        for i in range(len(melhor) - 1):
            for j in range(i + 1, len(melhor)):
                candidato = melhor[:i] + melhor[i:j + 1][::-1] + melhor[j + 1:]
                c = custo(candidato)
                if c < melhor_custo - 1e-9:
                    melhor, melhor_custo, melhorou = candidato, c, True
        if not melhorou:
            break
    return melhor


# ------------------------------------------------- escolar: falta informada ---
def reotimizar_por_falta(viagem: dict, paradas: list, faltas: dict,
                         deposito: tuple, tipos_por_id: dict,
                         provedor=None, partida_min: int = 6 * 60 + 20) -> dict:
    """Recalcula uma viagem escolar depois de faltas informadas.

    `paradas`: [{"id", "lat", "lon", "alunos", "tempo_parada"}] na ordem atual.
    `faltas`: {"P014": 3} — quantos alunos daquele ponto não vão hoje.

    Devolve o antes, o depois, o diff em português e o tempo de resposta.
    """
    inicio = time.perf_counter()
    provedor = provedor or tempos_mod.provedor_padrao()

    coords = [deposito] + [(p["lat"], p["lon"]) for p in paradas]
    servicos = [0] + [p.get("tempo_parada", 1) for p in paradas]
    dist, tempo = _matriz(coords, provedor, partida_min)

    ordem_atual = list(range(1, len(paradas) + 1))
    km_antes, min_antes = avaliar_sequencia(coords, ordem_atual, dist, tempo, servicos)
    alunos_antes = sum(p["alunos"] for p in paradas)

    # aplica as faltas
    restantes, removidas, aliviadas = [], [], []
    for i, p in enumerate(paradas, start=1):
        faltantes = int(faltas.get(p["id"], 0))
        se_restam = p["alunos"] - faltantes
        if faltantes and se_restam <= 0:
            removidas.append(p["id"])
        else:
            if faltantes:
                aliviadas.append((p["id"], faltantes))
            restantes.append(i)

    if removidas or aliviadas:
        # Partir da ordem que o solver já achou (tirando as paradas removidas)
        # e melhorá-la com 2-opt. Reconstruir do zero por vizinho mais próximo
        # jogaria fora uma sequência boa e podia sair pior que o plano
        # original — o que numa demonstração seria constrangedor. Testamos as
        # duas e ficamos com a melhor.
        def custo(seq):
            caminho = [0] + list(seq) + [0]
            return sum(dist[a][b] for a, b in zip(caminho, caminho[1:]))

        herdada = duas_opt(restantes, dist)
        do_zero = duas_opt(vizinho_mais_proximo(restantes, dist), dist)
        ordem_nova = min(herdada, do_zero, key=custo)
    else:
        ordem_nova = ordem_atual
    km_depois, min_depois = avaliar_sequencia(
        coords, ordem_nova, dist, tempo, servicos)
    alunos_depois = alunos_antes - sum(faltas.values())

    # a rota menor ainda precisa do mesmo veículo?
    tipo_atual = tipos_por_id.get(viagem.get("tipo"))
    cadeirantes = viagem.get("cadeirantes", 0)
    candidatos = [t for t in tipos_por_id.values()
                  if t.capacidade >= alunos_depois
                  and t.posicoes_cadeirante >= cadeirantes]
    tipo_sugerido = (min(candidatos, key=lambda t: t.custo_fixo_mes)
                     if candidatos else tipo_atual)

    diff = []
    for pid in removidas:
        diff.append(f"Parada {pid} removida hoje — nenhum aluno embarca nela.")
    for pid, qtd in aliviadas:
        diff.append(f"Parada {pid} mantida com {qtd} aluno(s) a menos.")
    if ordem_nova != [i for i in ordem_atual if i in ordem_nova]:
        diff.append("Ordem das paradas refeita para encurtar o percurso.")
    if km_antes - km_depois > 0.05:
        diff.append(f"Percurso: {km_antes:.1f} km → {km_depois:.1f} km "
                    f"(−{km_antes - km_depois:.1f} km) e "
                    f"{min_antes} min → {min_depois} min "
                    f"(−{min_antes - min_depois} min).")
    if (tipo_atual and tipo_sugerido and tipo_sugerido.id != tipo_atual.id
            and tipo_sugerido.custo_fixo_mes < tipo_atual.custo_fixo_mes):
        diff.append(f"Com {alunos_depois} alunos, a viagem cabe hoje num "
                    f"{tipo_sugerido.nome} no lugar do {tipo_atual.nome}.")
    if not diff:
        diff.append("Nenhuma mudança: as faltas não alteram a rota.")

    return {
        "viagem": viagem.get("id"),
        "antes": {"paradas": [p["id"] for p in paradas], "alunos": alunos_antes,
                  "km": km_antes, "minutos": min_antes},
        "depois": {"paradas": [paradas[i - 1]["id"] for i in ordem_nova],
                   "alunos": alunos_depois, "km": km_depois,
                   "minutos": min_depois},
        "economia": {"km": round(km_antes - km_depois, 1),
                     "minutos": min_antes - min_depois},
        "tipo_sugerido": tipo_sugerido.id if tipo_sugerido else None,
        "diff": diff,
        "segundos": round(time.perf_counter() - inicio, 3),
    }


# ------------------------------- porta a porta: cancelamento e reinserção ---
_INFINITO = 10 ** 6


def _horarios_limite(eventos, tempo, pedidos_por_id) -> list:
    """Mais tarde que cada evento pode acontecer sem atrasar os seguintes."""
    n = len(eventos)
    limite = [_INFINITO] * n
    for i in range(n - 1, -1, -1):
        teto = _INFINITO
        if pedidos_por_id and eventos[i]["tipo"] == "desembarque":
            teto = pedidos_por_id[eventos[i]["usuario"]].janela_chegada[1]
        if i < n - 1:
            teto = min(teto, limite[i + 1] - eventos[i]["servico"]
                       - tempo[eventos[i]["no"]][eventos[i + 1]["no"]])
        limite[i] = teto
    return limite


def _simular_rota(eventos, dist, tempo, inicio_min, pedidos_por_id=None) -> list:
    """Monta a agenda da rota — e o veículo espera FORA, não com gente dentro.

    A primeira versão fazia o veículo esperar a janela abrir no destino, com o
    passageiro a bordo. Isso é errado por dois motivos: ninguém fica sentado na
    van vendo o relógio, e o tempo a bordo calculado assim estourava o limite,
    fazendo a reotimização recusar encaixes que na prática cabem.

    O certo é o que o despachante faz: EMBARCAR O MAIS TARDE POSSÍVEL. Uma
    passada de trás para frente calcula o horário-limite de cada evento; a
    passada da frente para trás então atrasa cada embarque até esse limite.
    O usuário sai de casa mais tarde e anda menos tempo dentro do veículo.
    """
    limite = (_horarios_limite(eventos, tempo, pedidos_por_id)
              if pedidos_por_id else [_INFINITO] * len(eventos))
    agenda, minuto = [], inicio_min
    for i, ev in enumerate(eventos):
        if i > 0:
            minuto += tempo[eventos[i - 1]["no"]][ev["no"]]
        if pedidos_por_id:
            if ev["tipo"] == "embarque":
                minuto = max(minuto, min(limite[i], _INFINITO - 1))
            else:
                janela_ini = pedidos_por_id[ev["usuario"]].janela_chegada[0]
                minuto = max(minuto, janela_ini)
        agenda.append(dict(ev, minuto=minuto))
        minuto += ev["servico"]
    return agenda


def _viavel(agenda, pedidos_por_id) -> bool:
    """Confere janela de chegada e tempo máximo a bordo de cada usuário.

    A borda inferior da janela não é checada aqui porque a simulação já faz o
    veículo esperar; o que não se pode é chegar DEPOIS do fim da janela nem
    passar do tempo máximo a bordo.
    """
    embarque = {}
    for ev in agenda:
        if ev["tipo"] == "embarque":
            embarque[ev["usuario"]] = ev["minuto"]
        else:
            p = pedidos_por_id[ev["usuario"]]
            if ev["minuto"] > p.janela_chegada[1]:
                return False
            if ev["usuario"] not in embarque:
                return False   # desembarque antes do embarque: inválido
            direto = ev.get("direto", 0)
            if ev["minuto"] - embarque[ev["usuario"]] > limite_tempo_bordo_min(direto):
                return False
    return True


def melhor_insercao_em_rota(agenda, candidato, dist, tempo, pedidos_por_id,
                            capacidade, posicoes_cadeira, inicio_min):
    """Melhor posição para encaixar um pedido numa rota — ou None se não cabe.

    Testa todas as combinações de posição de embarque e desembarque
    (mantendo a precedência) e devolve a de menor quilometragem que respeita
    janela, tempo a bordo e capacidade. É a "inserção mais barata" clássica,
    a mesma mecânica que RideCo e Spare usam para aceitar pedido do dia.
    """
    p = pedidos_por_id[candidato["usuario"]]
    if p.posicoes_cadeira > posicoes_cadeira:
        return None
    emb = {"tipo": "embarque", "usuario": p.id, "no": candidato["no_origem"],
           "servico": candidato["servico"], "direto": candidato["direto"]}
    des = {"tipo": "desembarque", "usuario": p.id, "no": candidato["no_destino"],
           "servico": candidato["servico"], "direto": candidato["direto"]}

    melhor = None
    for i in range(len(agenda) + 1):
        for j in range(i + 1, len(agenda) + 2):
            tentativa = list(agenda)
            tentativa.insert(i, emb)
            tentativa.insert(j, des)
            # Inserção na frente: o veículo pode SAIR MAIS CEDO da garagem em
            # vez de empurrar a agenda de quem já está na rota.
            inicio_tentativa = inicio_min
            if i == 0 and agenda:
                inicio_tentativa = inicio_min - (
                    tempo[emb["no"]][agenda[0]["no"]] + emb["servico"])
            simulada = _simular_rota(tentativa, dist, tempo, inicio_tentativa,
                                     pedidos_por_id)
            if not _viavel(simulada, pedidos_por_id):
                continue
            if _ocupacao_maxima(simulada, pedidos_por_id) > capacidade:
                continue
            km = sum(dist[a["no"]][b["no"]]
                     for a, b in zip(simulada, simulada[1:]))
            if melhor is None or km < melhor["km"]:
                melhor = {"km": km, "agenda": simulada, "posicoes": (i, j)}
    return melhor


def inserir_na_melhor_rota(rotas: list, coords: list, candidato: dict,
                           pedidos_por_id: dict, provedor=None,
                           partida_min: int = 7 * 60,
                           limite_km_extra: float = None) -> dict:
    """Escolhe, entre TODAS as rotas do dia, a que absorve o pedido mais barato.

    `rotas`: [{"id", "eventos", "capacidade", "posicoes_cadeirante"}].
    Aceitar o pedido na primeira rota que couber seria fácil e caro: numa
    rodada de teste isso encaixou um usuário com 21 km de desvio quando outra
    rota o absorveria com muito menos.
    """
    inicio = time.perf_counter()
    provedor = provedor or tempos_mod.provedor_padrao()
    dist, tempo = _matriz(coords, provedor, partida_min)

    melhor = None
    for rota in rotas:
        eventos = rota["eventos"]
        if not eventos:
            continue
        inicio_min = eventos[0].get("minuto", partida_min)
        agenda = _simular_rota(eventos, dist, tempo, inicio_min, pedidos_por_id)
        km_atual = sum(dist[a["no"]][b["no"]] for a, b in zip(agenda, agenda[1:]))
        tentativa = melhor_insercao_em_rota(
            agenda, candidato, dist, tempo, pedidos_por_id, rota["capacidade"],
            rota["posicoes_cadeirante"], inicio_min)
        if not tentativa:
            continue
        extra = tentativa["km"] - km_atual
        if melhor is None or extra < melhor["km_extra"]:
            melhor = {"rota": rota["id"], "km_extra": round(extra, 1),
                      "km_rota": round(tentativa["km"], 1),
                      "agenda": tentativa["agenda"]}

    segundos = round(time.perf_counter() - inicio, 3)
    if not melhor:
        return {"usuario": candidato["usuario"], "aceito": False,
                "segundos": segundos,
                "diff": [f"Pedido de {candidato['usuario']} não cabe em "
                         f"nenhuma rota de hoje sem estourar a janela ou o "
                         f"tempo a bordo de quem já está agendado."]}
    if limite_km_extra is not None and melhor["km_extra"] > limite_km_extra:
        # Encaixar a qualquer custo não é economia: um desvio de 30 km para
        # atender uma pessoa pode sair mais caro que uma viagem dedicada. O
        # limite é política da secretaria, e fica declarado.
        return {"usuario": candidato["usuario"], "aceito": False,
                "rota_candidata": melhor["rota"],
                "km_extra": melhor["km_extra"], "segundos": segundos,
                "diff": [f"Pedido de {candidato['usuario']} caberia na rota "
                         f"{melhor['rota']}, mas custaria {melhor['km_extra']} km "
                         f"a mais — acima do limite de {limite_km_extra} km por "
                         f"encaixe. Vale mais programar uma viagem dedicada."]}
    return {
        "usuario": candidato["usuario"], "aceito": True,
        "rota": melhor["rota"], "km_extra": melhor["km_extra"],
        "segundos": segundos,
        "agenda": [{"tipo": e["tipo"], "usuario": e["usuario"],
                    "hora": f"{e['minuto'] // 60:02d}h{e['minuto'] % 60:02d}"}
                   for e in melhor["agenda"]],
        "diff": [f"Pedido de {candidato['usuario']} aceito na rota "
                 f"{melhor['rota']} com {melhor['km_extra']} km a mais — a "
                 f"rota mais barata entre as {len(rotas)} do dia."],
    }


def cancelar_e_reinserir(rota_eventos: list, coords: list, cancelado: str,
                         fila_espera: list, pedidos_por_id: dict,
                         capacidade: int, posicoes_cadeira: int,
                         provedor=None, partida_min: int = 7 * 60) -> dict:
    """Tira um cancelamento da rota e tenta encaixar alguém da fila de espera.

    É a mecânica que o mercado chama de inserção dinâmica: a capacidade
    liberada por um cancelamento volta ao pool na hora, em vez de virar
    assento vazio rodando a cidade.

    `rota_eventos`: [{"tipo","usuario","no","servico","direto"}] em ordem.
    `coords`: coordenadas indexadas por "no".
    """
    inicio = time.perf_counter()
    provedor = provedor or tempos_mod.provedor_padrao()
    dist, tempo = _matriz(coords, provedor, partida_min)

    inicio_min = rota_eventos[0].get("minuto", partida_min)
    antes = _simular_rota(rota_eventos, dist, tempo, inicio_min, pedidos_por_id)
    km_antes = sum(dist[a["no"]][b["no"]] for a, b in zip(antes, antes[1:]))

    sem_cancelado = [e for e in rota_eventos if e["usuario"] != cancelado]
    if len(sem_cancelado) == len(rota_eventos):
        raise ValueError(f"Usuário {cancelado} não está nesta rota")

    agenda = _simular_rota(sem_cancelado, dist, tempo, inicio_min, pedidos_por_id)
    km_depois = sum(dist[a["no"]][b["no"]] for a, b in zip(agenda, agenda[1:]))

    diff = [f"Usuário {cancelado} cancelou: embarque e desembarque retirados "
            f"da rota."]
    if km_antes - km_depois > 0.05:
        diff.append(f"Percurso: {km_antes:.1f} km → {km_depois:.1f} km "
                    f"(−{km_antes - km_depois:.1f} km).")

    # ---- tenta encaixar alguém da fila de espera na capacidade liberada
    encaixado, melhor = None, None
    for candidato in fila_espera:
        tentativa = melhor_insercao_em_rota(
            agenda, candidato, dist, tempo, pedidos_por_id, capacidade,
            posicoes_cadeira, inicio_min)
        if tentativa and (melhor is None or tentativa["km"] < melhor[0]):
            melhor = (tentativa["km"], tentativa["agenda"])
            encaixado = candidato["usuario"]
    if encaixado:
        km_final = melhor[0]
        diff.append(f"Usuário {encaixado} entrou da fila de espera no lugar "
                    f"liberado (+{km_final - km_depois:.1f} km, ainda "
                    f"{km_antes - km_final:+.1f} km em relação ao plano "
                    f"original).")
        agenda = melhor[1]
        km_depois = km_final
    elif fila_espera:
        diff.append("Ninguém da fila de espera cabia na janela liberada sem "
                    "estourar o tempo a bordo de quem já está na rota.")

    return {
        "cancelado": cancelado,
        "encaixado": encaixado,
        "km_antes": round(km_antes, 1),
        "km_depois": round(km_depois, 1),
        "economia_km": round(km_antes - km_depois, 1),
        "agenda": [{"tipo": e["tipo"], "usuario": e["usuario"],
                    "hora": f"{e['minuto'] // 60:02d}h{e['minuto'] % 60:02d}"}
                   for e in agenda],
        "diff": diff,
        "segundos": round(time.perf_counter() - inicio, 3),
    }


def _ocupacao_maxima(agenda, pedidos_por_id) -> int:
    ocupacao = pico = 0
    for ev in agenda:
        p = pedidos_por_id[ev["usuario"]]
        carga = p.assentos + p.posicoes_cadeira
        ocupacao += carga if ev["tipo"] == "embarque" else -carga
        pico = max(pico, ocupacao)
    return pico
