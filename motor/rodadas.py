# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-reotimizacao
Reotimização CONTÍNUA: o dia inteiro em rodadas, não um evento por vez.

O que já existia (`motor/reotimizar.py`) responde a um acontecimento: faltou
um aluno, cancelou um usuário, chegou um pedido. Isso resolve o telefonema.
O que faltava é o que os sistemas modernos de paratransit fazem por baixo — o
plano do dia é revisto de tempos em tempos, e uma corrida pode MUDAR DE
VEÍCULO enquanto ainda dá tempo, porque a combinação ficou melhor depois que
outras três coisas aconteceram.

A rodada faz, nesta ordem:

    1. aplica as faltas e cancelamentos que chegaram desde a rodada anterior;
    2. tenta encaixar os pedidos novos, na rota mais barata de todas;
    3. destrói e reconstrói (ruin & recreate): tira da rota os k pedidos que
       hoje custam mais desvio e reinsere cada um onde ficar mais barato —
       inclusive em outro veículo.

E não faz, de propósito:

    * não toca em quem já embarcou nem em quem embarca dentro do horizonte de
      compromisso. A família foi avisada de um horário; sistema que remarca a
      hora da mãe que já está no portão com a criança perde a confiança da
      operação inteira, e economia nenhuma paga isso;
    * não aceita uma solução que atrase a promessa de alguém além da
      tolerância declarada, mesmo que o total de quilômetros melhore;
    * não aceita melhora insignificante: mudar rota por 200 metros gera
      retrabalho de despacho sem retorno.

Se a reconstrução não melhorar o suficiente ou quebrar uma promessa, a rodada
descarta o resultado e mantém o plano anterior — reotimização que piora é
mais cara que reotimização nenhuma.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import tempos as tempos_mod
from motor import reotimizar as reo


@dataclass
class Politica:
    """Os parâmetros que a secretaria decide — todos aparecem no relatório."""
    intervalo_min: int = 5              # de quanto em quanto tempo roda
    horizonte_compromisso_min: int = 20  # nada dentro disso é remarcado
    janela_de_aviso_min: int = 60        # a partir daqui o horário é firme
    max_atraso_promessa_min: int = 5     # tolerância sobre o horário firme
    remocoes_por_rodada: int = 3         # tamanho da destruição
    ganho_minimo_km: float = 0.3         # abaixo disso não vale mexer
    limite_km_extra: float = 15.0        # desvio máximo para aceitar pedido

    def como_dicionario(self) -> dict:
        return {"intervalo_min": self.intervalo_min,
                "horizonte_compromisso_min": self.horizonte_compromisso_min,
                "janela_de_aviso_min": self.janela_de_aviso_min,
                "max_atraso_promessa_min": self.max_atraso_promessa_min,
                "remocoes_por_rodada": self.remocoes_por_rodada,
                "ganho_minimo_km": self.ganho_minimo_km,
                "limite_km_extra": self.limite_km_extra}


# ------------------------------------------------------------- utilidades ---
def _copiar(rotas: list) -> list:
    return [{"id": r["id"], "eventos": [dict(e) for e in r["eventos"]],
             "capacidade": r["capacidade"],
             "posicoes_cadeirante": r["posicoes_cadeirante"],
             "inicio_min": r.get("inicio_min")} for r in rotas]


def _inicio(rota: dict, padrao: int) -> int:
    """Quando o veículo sai — e ele PODE sair mais cedo.

    O horário do primeiro evento manda, e não o `inicio_min` declarado: quando
    a inserção coloca alguém na frente da rota, a saída da garagem se antecipa
    em vez de empurrar a agenda de quem já estava marcado. Guardar o `minuto`
    simulado em cada evento é o que carrega essa informação de uma rodada para
    a seguinte.
    """
    if rota["eventos"] and rota["eventos"][0].get("minuto") is not None:
        return rota["eventos"][0]["minuto"]
    if rota.get("inicio_min") is not None:
        return rota["inicio_min"]
    return padrao


def _agenda(rota, dist, tempo, pedidos_por_id, padrao):
    if not rota["eventos"]:
        return []
    return reo._simular_rota(rota["eventos"], dist, tempo,
                             _inicio(rota, padrao), pedidos_por_id)


def _km_da_agenda(agenda, dist) -> float:
    return sum(dist[a["no"]][b["no"]] for a, b in zip(agenda, agenda[1:]))


def km_total(rotas, dist, tempo, pedidos_por_id, padrao) -> float:
    return round(sum(_km_da_agenda(_agenda(r, dist, tempo, pedidos_por_id,
                                           padrao), dist)
                     for r in rotas), 2)


def promessas(rotas, dist, tempo, pedidos_por_id, padrao) -> dict:
    """O horário que cada usuário recebeu — a régua de tudo o que vem depois."""
    prometido = {}
    for rota in rotas:
        for ev in _agenda(rota, dist, tempo, pedidos_por_id, padrao):
            registro = prometido.setdefault(ev["usuario"], {"rota": rota["id"]})
            registro[ev["tipo"]] = ev["minuto"]
            registro["rota"] = rota["id"]
    return prometido


def _travados(rota, dist, tempo, pedidos_por_id, agora, horizonte, padrao):
    """(quantos eventos do começo estão comprometidos, usuários intocáveis).

    Um usuário é intocável quando o embarque dele já aconteceu ou acontece
    dentro do horizonte. Passageiro a bordo não muda de veículo — e quem está
    esperando no portão na hora combinada, também não.
    """
    agenda = _agenda(rota, dist, tempo, pedidos_por_id, padrao)
    limite = agora + horizonte
    presos, prefixo = set(), 0
    for i, ev in enumerate(agenda):
        if ev["minuto"] <= limite:
            prefixo = i + 1
            presos.add(ev["usuario"])
    # o desembarque de quem já embarcou também não pode sair da rota
    for ev in agenda:
        if ev["tipo"] == "embarque" and ev["minuto"] <= limite:
            presos.add(ev["usuario"])
    return prefixo, presos


def _remover(rota, usuario) -> list:
    retirados = [e for e in rota["eventos"] if e["usuario"] == usuario]
    rota["eventos"] = [e for e in rota["eventos"] if e["usuario"] != usuario]
    return retirados


def _candidato_de(eventos: list) -> dict:
    """Reconstrói o pedido no formato de inserção a partir dos eventos."""
    emb = next(e for e in eventos if e["tipo"] == "embarque")
    des = next(e for e in eventos if e["tipo"] == "desembarque")
    return {"usuario": emb["usuario"], "no_origem": emb["no"],
            "no_destino": des["no"], "servico": emb["servico"],
            "direto": emb.get("direto", 0)}


def _melhor_destino(rotas, candidato, dist, tempo, pedidos_por_id, agora,
                    politica, padrao):
    """Rota mais barata para (re)inserir um pedido, respeitando o congelado."""
    melhor = None
    for rota in rotas:
        prefixo, _ = _travados(rota, dist, tempo, pedidos_por_id, agora,
                               politica.horizonte_compromisso_min, padrao)
        agenda = _agenda(rota, dist, tempo, pedidos_por_id, padrao)
        km_atual = _km_da_agenda(agenda, dist)
        tentativa = reo.melhor_insercao_em_rota(
            agenda, candidato, dist, tempo, pedidos_por_id, rota["capacidade"],
            rota["posicoes_cadeirante"], _inicio(rota, padrao),
            posicao_minima=prefixo)
        if not tentativa:
            continue
        extra = tentativa["km"] - km_atual
        if melhor is None or extra < melhor["km_extra"]:
            melhor = {"rota": rota, "km_extra": round(extra, 2),
                      "eventos": [dict(e) for e in tentativa["agenda"]]}
    return melhor


def _promessas_respeitadas(antes: dict, depois: dict, tolerancia: int,
                           agora: int = None, janela_aviso: int = None) -> list:
    """Quem teria o horário mexido além do combinado.

    O horário só é firme perto da hora. Um sistema de transporte sob demanda
    confirma a janela quando ela se aproxima (`janela_de_aviso_min`); antes
    disso, o plano é plano, e mexer nele não quebra promessa nenhuma. É essa
    distinção que deixa a reotimização respirar: ela remaneja a tarde inteira
    à vontade e não encosta na próxima meia hora.
    """
    quebras = []
    for usuario, promessa in antes.items():
        nova = depois.get(usuario)
        if not nova:
            continue                     # saiu do dia (falta/cancelamento)
        if (agora is not None and janela_aviso is not None
                and promessa.get("embarque", 0) > agora + janela_aviso):
            continue                     # ainda não foi avisado: pode mudar
        if ("embarque" in promessa and "embarque" in nova
                and abs(nova["embarque"] - promessa["embarque"]) > tolerancia):
            quebras.append(
                f"{usuario}: embarque combinado às "
                f"{_hora(promessa['embarque'])} iria para {_hora(nova['embarque'])}")
        if ("desembarque" in promessa and "desembarque" in nova
                and nova["desembarque"] - promessa["desembarque"] > tolerancia):
            quebras.append(
                f"{usuario}: chegada combinada às "
                f"{_hora(promessa['desembarque'])} atrasaria para "
                f"{_hora(nova['desembarque'])}")
    return quebras


def _hora(minuto: int) -> str:
    return f"{int(minuto) // 60:02d}h{int(minuto) % 60:02d}"


# ---------------------------------------------------------------- rodada ----
def rodada(rotas: list, coords: list, pedidos_por_id: dict, agora_min: int,
           eventos: list = None, politica: Politica = None, provedor=None,
           dist=None, tempo=None) -> dict:
    """Uma rodada de reotimização. Devolve o novo plano e o diff legível."""
    politica = politica or Politica()
    inicio_relogio = time.perf_counter()
    if dist is None or tempo is None:
        provedor = provedor or tempos_mod.provedor_padrao()
        dist, tempo = provedor.matriz(coords, partida_min=agora_min)

    estado = _copiar(rotas)
    prometido = promessas(estado, dist, tempo, pedidos_por_id, agora_min)
    km_inicial = km_total(estado, dist, tempo, pedidos_por_id, agora_min)
    diff, movimentos = [], []
    saidas, aceitos, recusados = [], [], []

    # 1) faltas e cancelamentos ------------------------------------------------
    presos = set()
    for rota in estado:
        _, presos_da_rota = _travados(rota, dist, tempo, pedidos_por_id,
                                      agora_min,
                                      politica.horizonte_compromisso_min,
                                      agora_min)
        presos |= presos_da_rota

    for evento in eventos or []:
        if evento["tipo"] not in ("falta", "cancelamento"):
            continue
        usuario = evento["usuario"]
        alvo = next((r for r in estado
                     if any(e["usuario"] == usuario for e in r["eventos"])), None)
        if alvo is None:
            diff.append(f"{usuario} não estava em nenhuma rota de hoje.")
            continue
        if usuario in presos:
            # já embarcou (ou está embarcando): a viagem acontece de qualquer
            # jeito; só faz sentido registrar
            diff.append(f"{usuario} avisou falta, mas o veículo já estava na "
                        f"porta — nada a reprogramar.")
            continue
        _remover(alvo, usuario)
        saidas.append(usuario)
        diff.append(f"{usuario} saiu da rota {alvo['id']} (falta informada).")

    # 2) pedidos novos ---------------------------------------------------------
    for evento in eventos or []:
        if evento["tipo"] != "pedido":
            continue
        candidato = evento["candidato"]
        melhor = _melhor_destino(estado, candidato, dist, tempo, pedidos_por_id,
                                 agora_min, politica, agora_min)
        if not melhor:
            recusados.append({"usuario": candidato["usuario"],
                              "motivo": "não cabe em nenhuma rota sem estourar "
                                        "janela, capacidade ou tempo a bordo"})
            diff.append(f"Pedido de {candidato['usuario']} recusado: não cabe "
                        f"em nenhuma rota de hoje.")
            continue
        if melhor["km_extra"] > politica.limite_km_extra:
            recusados.append({"usuario": candidato["usuario"],
                              "motivo": f"desvio de {melhor['km_extra']} km "
                                        f"acima do limite"})
            diff.append(f"Pedido de {candidato['usuario']} recusado: caberia na "
                        f"rota {melhor['rota']['id']}, mas custaria "
                        f"{melhor['km_extra']} km — acima do limite de "
                        f"{politica.limite_km_extra} km por encaixe.")
            continue

        # Encaixar o pedido novo não pode atrasar quem já tem horário firme.
        # Sem esta conferência, aceitar uma corrida às 7h05 empurraria a
        # criança das 7h20 para as 7h35 — e ninguém avisou a mãe dela.
        guardado = list(melhor["rota"]["eventos"])
        melhor["rota"]["eventos"] = melhor["eventos"]
        atropelados = _promessas_respeitadas(
            prometido, promessas(estado, dist, tempo, pedidos_por_id, agora_min),
            politica.max_atraso_promessa_min, agora_min,
            politica.janela_de_aviso_min)
        if atropelados:
            melhor["rota"]["eventos"] = guardado
            recusados.append({"usuario": candidato["usuario"],
                              "motivo": "atrasaria horário já combinado de "
                                        f"{len(atropelados)} usuário(s)"})
            diff.append(f"Pedido de {candidato['usuario']} recusado: caberia na "
                        f"rota {melhor['rota']['id']}, mas atrasaria horário "
                        f"já combinado. {atropelados[0]}.")
            continue

        aceitos.append({"usuario": candidato["usuario"],
                        "rota": melhor["rota"]["id"],
                        "km_extra": melhor["km_extra"]})
        diff.append(f"Pedido de {candidato['usuario']} aceito na rota "
                    f"{melhor['rota']['id']} com {melhor['km_extra']} km a mais.")

    km_apos_eventos = km_total(estado, dist, tempo, pedidos_por_id, agora_min)
    km_extra_dos_pedidos = round(sum(a["km_extra"] for a in aceitos), 2)

    # 3) destruir e reconstruir ------------------------------------------------
    # A régua da melhoria é o plano DEPOIS dos acontecimentos: o remanejamento
    # responde por si, não pelo que a falta e o pedido novo já mexeram.
    prometido_agora = promessas(estado, dist, tempo, pedidos_por_id, agora_min)
    antes_da_melhoria = _copiar(estado)
    candidatos = _mais_caros(estado, dist, tempo, pedidos_por_id, agora_min,
                             politica, politica.remocoes_por_rodada)
    retirados = []
    for usuario, rota_origem in candidatos:
        alvo = next(r for r in estado if r["id"] == rota_origem)
        eventos_do_usuario = _remover(alvo, usuario)
        retirados.append((usuario, rota_origem, _candidato_de(eventos_do_usuario)))

    reinseridos = True
    for usuario, rota_origem, candidato in retirados:
        melhor = _melhor_destino(estado, candidato, dist, tempo, pedidos_por_id,
                                 agora_min, politica, agora_min)
        if not melhor:
            reinseridos = False
            break
        melhor["rota"]["eventos"] = melhor["eventos"]
        if melhor["rota"]["id"] != rota_origem:
            movimentos.append({"usuario": usuario, "de": rota_origem,
                               "para": melhor["rota"]["id"]})

    km_final = km_total(estado, dist, tempo, pedidos_por_id, agora_min)
    ganho = round(km_apos_eventos - km_final, 2)
    quebras = _promessas_respeitadas(
        prometido_agora,
        promessas(estado, dist, tempo, pedidos_por_id, agora_min),
        politica.max_atraso_promessa_min, agora_min,
        politica.janela_de_aviso_min)

    descartada = ""
    if not reinseridos:
        descartada = ("a reconstrução não achou lugar para todo mundo — plano "
                      "anterior mantido")
    elif quebras:
        descartada = (f"a melhoria quebraria {len(quebras)} horário já "
                      f"combinado — plano anterior mantido")
    elif ganho < politica.ganho_minimo_km:
        descartada = (f"ganho de {ganho} km abaixo do mínimo de "
                      f"{politica.ganho_minimo_km} km — não vale remanejar")

    if descartada:
        estado = antes_da_melhoria
        movimentos = []
        km_final = km_apos_eventos
        ganho = 0.0
        if quebras:
            diff.append(f"Melhoria descartada: {descartada}. "
                        f"Exemplo: {quebras[0]}.")
        else:
            diff.append(f"Melhoria descartada: {descartada}.")
    elif movimentos:
        for m in movimentos:
            diff.append(f"{m['usuario']} passou da rota {m['de']} para a "
                        f"{m['para']}.")
        diff.append(f"Remanejamento economizou {ganho} km sem mexer em nenhum "
                    f"horário já combinado.")

    # Separar as três parcelas é o que impede a conta mentirosa dos dois
    # lados: somar o km do pedido novo como "economia negativa" esconderia o
    # ganho real; ignorá-lo esconderia o custo de atender mais gente.
    return {
        "minuto": agora_min,
        "hora": _hora(agora_min),
        "km_antes": round(km_inicial, 2),
        "km_depois": round(km_final, 2),
        "km_liberados_por_falta": round(
            km_inicial - (km_apos_eventos - km_extra_dos_pedidos), 2),
        "km_de_demanda_nova": km_extra_dos_pedidos,
        # km_final = km_inicial − liberados − ganho + demanda nova; a economia
        # é o que sobra quando se devolve à conta o km da demanda nova.
        "km_economizados": round(
            km_inicial - km_final + km_extra_dos_pedidos, 2),
        "ganho_do_remanejamento_km": ganho,
        "saidas": saidas,
        "pedidos_aceitos": aceitos,
        "pedidos_recusados": recusados,
        "movimentos": movimentos,
        "promessas_preservadas": not quebras or bool(descartada),
        "melhoria_descartada": descartada,
        "segundos": round(time.perf_counter() - inicio_relogio, 3),
        "diff": diff,
        "rotas": estado,
    }


def _mais_caros(rotas, dist, tempo, pedidos_por_id, agora, politica, quantos):
    """Os pedidos que hoje custam mais desvio — e que dá para mexer.

    Custo de um pedido = quanto a rota encolhe se ele sair. Tirar primeiro
    quem custa mais é o que faz o ruin & recreate convergir rápido; tirar ao
    acaso desperdiça rodada.
    """
    placar = []
    for rota in rotas:
        prefixo, presos = _travados(rota, dist, tempo, pedidos_por_id, agora,
                                    politica.horizonte_compromisso_min, agora)
        agenda = _agenda(rota, dist, tempo, pedidos_por_id, agora)
        km_atual = _km_da_agenda(agenda, dist)
        usuarios = []
        for ev in rota["eventos"]:
            if ev["usuario"] not in usuarios and ev["usuario"] not in presos:
                usuarios.append(ev["usuario"])
        for usuario in usuarios:
            restante = [e for e in rota["eventos"] if e["usuario"] != usuario]
            if not restante:
                continue
            simulada = reo._simular_rota(restante, dist, tempo,
                                         _inicio(rota, agora), pedidos_por_id)
            placar.append((round(km_atual - _km_da_agenda(simulada, dist), 2),
                           usuario, rota["id"]))
    placar.sort(key=lambda t: (-t[0], t[1]))
    return [(usuario, rota) for _, usuario, rota in placar[:quantos]]


# ------------------------------------------------------------- dia inteiro ---
def rodar_dia(rotas: list, coords: list, pedidos_por_id: dict,
              agenda_de_eventos: list, inicio_min: int, fim_min: int,
              politica: Politica = None, provedor=None) -> dict:
    """Roda uma rodada a cada `intervalo_min` e devolve o histórico do dia.

    `agenda_de_eventos`: [(minuto, evento)] — a hora em que a informação
    CHEGOU, não a hora do serviço. É essa distinção que torna o exercício
    honesto: o sistema só pode usar o que já sabe.
    """
    politica = politica or Politica()
    provedor = provedor or tempos_mod.provedor_padrao()
    dist, tempo = provedor.matriz(coords, partida_min=inicio_min)

    estado = _copiar(rotas)
    pendentes = sorted(agenda_de_eventos, key=lambda par: par[0])
    historico, i = [], 0
    minuto = inicio_min
    while minuto <= fim_min:
        chegaram = []
        while i < len(pendentes) and pendentes[i][0] <= minuto:
            chegaram.append(pendentes[i][1])
            i += 1
        resultado = rodada(estado, coords, pedidos_por_id, minuto, chegaram,
                           politica, dist=dist, tempo=tempo)
        estado = resultado.pop("rotas")
        historico.append(resultado)
        minuto += politica.intervalo_min

    tempos_resposta = [r["segundos"] for r in historico]
    com_acao = [r for r in historico
                if r["saidas"] or r["pedidos_aceitos"] or r["movimentos"]
                or r["pedidos_recusados"]]
    return {
        "politica": politica.como_dicionario(),
        "rodadas": historico,
        "rotas_finais": estado,
        "resumo": {
            "rodadas": len(historico),
            "rodadas_com_acao": len(com_acao),
            "km_economizados": round(
                sum(r["km_economizados"] for r in historico), 2),
            "km_de_demanda_nova": round(
                sum(r["km_de_demanda_nova"] for r in historico), 2),
            "km_liberados_por_falta": round(
                sum(r["km_liberados_por_falta"] for r in historico), 2),
            "km_do_remanejamento": round(
                sum(r["ganho_do_remanejamento_km"] for r in historico), 2),
            "faltas_absorvidas": sum(len(r["saidas"]) for r in historico),
            "pedidos_aceitos": sum(len(r["pedidos_aceitos"]) for r in historico),
            "pedidos_recusados": sum(len(r["pedidos_recusados"])
                                     for r in historico),
            "corridas_remanejadas": sum(len(r["movimentos"]) for r in historico),
            "melhorias_descartadas": sum(1 for r in historico
                                         if r["melhoria_descartada"]),
            "promessas_quebradas": sum(1 for r in historico
                                       if not r["promessas_preservadas"]),
            "tempo_max_s": max(tempos_resposta) if tempos_resposta else 0,
            "tempo_medio_s": round(
                sum(tempos_resposta) / len(tempos_resposta), 3)
            if tempos_resposta else 0,
        },
    }
