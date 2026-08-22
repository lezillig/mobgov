# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 1 (revisado na Sprint 3) · agent-rotas
Motor de dimensionamento de frota: CVRP escolar com frota heterogênea,
restrição de cadeirantes, tempo de embarque por parada, tempo máximo de
trajeto por aluno e — a novidade da Sprint 3 — ROTEIRIZAÇÃO MULTIVIAGEM.

Por que multiviagem: prefeitura não usa um veículo por rota. O mesmo ônibus
faz duas ou três viagens no mesmo turno (sai, coleta, entrega na escola, volta
e faz a próxima). Sem modelar isso, uma demanda de 3.000 alunos exigiria uma
frota irreal — e o número da economia perderia o sentido.

Estratégia, em duas fases:
1. ROTEIRIZAR (OR-Tools): para cada escola e cada turno, resolver o CVRP com
   frota heterogênea. Cada "veículo" do solver é uma VIAGEM. O custo fixo por
   veículo usado faz o próprio solver minimizar o número de viagens.
2. ESCALAR (empacotamento): encaixar as viagens de um turno em veículos
   físicos, respeitando a jornada disponível antes do sinal, o deslocamento
   entre o fim de uma viagem e o início da próxima, e a compatibilidade de
   tipo (assentos e posições de cadeirante). Heurística "maior primeiro, no
   veículo com menos folga" — determinística e explicável viagem a viagem.

A frota necessária é o pior caso de cada tipo entre os turnos: o mesmo veículo
serve manhã e tarde, então não se soma, se toma o máximo.
"""
import json
import math
import sys
import os
from dataclasses import dataclass
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from motor.escala import montar_jornadas, compor_frota, TEMPO_VIRADA_MIN
from dados import tempos as tempos_mod
from dados.municipio_modelo import (
    ESCOLAS, TIPOS_VEICULO, TURNOS, gerar_pontos, frota_atual_sintetica,
    tempo_parada_min,
)

@dataclass
class _FrotaDeclarada:
    """Frota que o município informou ter — o "antes" sem estimativa."""
    composicao: dict
    km_dia_declarado: float
    viagens_por_veiculo_turno: float = None


# O trânsito é apanhado no MIOLO DA COLETA, não no horário do sinal: é quando
# os veículos estão de fato na rua. Meia hora antes da janela de chegada.
MINUTOS_ANTES_DA_JANELA = 30

TEMPO_MAX_TRAJETO_MIN = 75   # parâmetro da secretaria: aluno no veículo <= 75 min
DIAS_LETIVOS_MES = 22
PRECO_DIESEL = 6.10          # R$/l — premissa declarada no relatório
FATOR_CO2_KG_L = 2.68        # kg CO2 por litro de diesel
VIAGENS_POR_ROTA = 2         # cada rota acontece duas vezes: coleta e dispersão
TEMPO_LIMITE_SOLVER_S = 30


# ------------------------------------------------------------ fase 1: rotas ---
def viagens_pelo_tempo(tempo, paradas_min, limite=None) -> int:
    """Quantas viagens o TEMPO exige, independentemente dos assentos.

    A conta é a que um despachante faz de cabeça: uma viagem gasta o trecho
    final até a escola, e cada parada custa o pulo até a parada vizinha mais
    o tempo de embarque. Divide-se o que sobra do limite por esse custo e
    sai quantas paradas cabem numa viagem.

    É estimativa, e serve só para dimensionar a OFERTA de veículos que o
    solver recebe — quem decide as viagens continua sendo o solver.
    """
    limite = limite or TEMPO_MAX_TRAJETO_MIN
    n = len(tempo) - 1                       # o nó 0 é a escola
    if n <= 0:
        return 0
    ate_a_escola = sum(tempo[0][i] for i in range(1, n + 1)) / n
    vizinho = [min(tempo[i][j] for j in range(1, n + 1) if j != i)
               for i in range(1, n + 1)] if n > 1 else [0]
    custo_da_parada = (sum(vizinho) / len(vizinho)
                       + sum(paradas_min[1:]) / n)
    disponivel = max(1.0, limite - ate_a_escola)
    paradas_por_viagem = max(1, int(disponivel / max(0.5, custo_da_parada)))
    return math.ceil(n / paradas_por_viagem)


def _separar_inviaveis(escola, turno, pontos, dist, tempo):
    """Tira da conta os pontos que não cabem em rota nenhuma — e diz por quê.

    Um ponto cujo trajeto mínimo (escola → ponto → embarque → escola) já passa
    do tempo máximo por aluno não tem solução: não existe rota que o inclua
    sem violar a regra. Isso aparece com planilha de verdade, e quase sempre
    significa uma destas três coisas, todas decisões de gente:

      * o aluno está matriculado numa escola do outro lado do município;
      * a coordenada dele está errada (endereço mal geocodificado);
      * aquele caso precisa mesmo de atendimento individual.

    O que o sistema NÃO pode fazer é escolher sozinho: nem afrouxar o limite
    (que é regra da secretaria), nem deixar a criança fora da rota em silêncio.
    Então ele roteiriza o resto e devolve estes casos por escrito.
    """
    limite = TEMPO_MAX_TRAJETO_MIN
    dentro, fora = [], []
    for i, p in enumerate(pontos, start=1):
        minimo = tempo[0][i] + tempo_parada_min(p, turno.id) + tempo[i][0]
        if minimo > limite:
            fora.append({
                "ponto": p.id, "escola": escola.nome, "escola_id": escola.id,
                "turno": turno.id, "turno_nome": turno.nome,
                "bairro": p.distrito,
                "alunos": p.alunos.get(turno.id, 0),
                "minutos_minimos": int(round(minimo)),
                "limite_min": limite,
                "motivo": (f"Só a ida e a volta até a escola já levam "
                           f"{int(round(minimo))} min, acima do limite de "
                           f"{limite} min por aluno."),
                "o_que_fazer": ("Confira o endereço e a escola de matrícula. "
                                "Se estiverem certos, este caso precisa de "
                                "decisão da secretaria: elevar o limite para "
                                "ele, atendimento individual ou transferência "
                                "de unidade."),
            })
        else:
            dentro.append((i, p))

    if not fora:
        return pontos, dist, tempo, []

    # remonta as matrizes só com o que sobrou (o nó 0 é a escola)
    indices = [0] + [i for i, _ in dentro]
    dist = [[dist[a][b] for b in indices] for a in indices]
    tempo = [[tempo[a][b] for b in indices] for a in indices]
    return [p for _, p in dentro], dist, tempo, fora


def resolver_viagens(escola, turno, pontos, tipos,
                     tempo_limite_s=TEMPO_LIMITE_SOLVER_S, provedor=None,
                     inviaveis=None):
    """Resolve as viagens de coleta de uma escola em um turno.

    `inviaveis`: lista onde são anotados os pontos que NÃO cabem em rota
    nenhuma — ver `_separar_inviaveis`.
    """
    pontos = [p for p in pontos if p.alunos.get(turno.id, 0) > 0]
    if not pontos:
        return []

    locais = [(escola.lat, escola.lon)] + [(p.lat, p.lon) for p in pontos]
    provedor = provedor or tempos_mod.provedor_padrao()
    partida = turno.janela_chegada[0] - MINUTOS_ANTES_DA_JANELA
    zonas = [tempos_mod.zona_de(l) for l in locais]
    dist, tempo = provedor.matriz(locais, partida_min=partida, zonas=zonas)

    pontos, dist, tempo, fora = _separar_inviaveis(escola, turno, pontos,
                                                   dist, tempo)
    if fora and inviaveis is not None:
        inviaveis.extend(fora)
    if not pontos:
        return []

    demandas = [0] + [p.alunos[turno.id] for p in pontos]
    cadeirantes = [0] + [p.alunos_cadeirantes.get(turno.id, 0) for p in pontos]
    paradas_min = [0] + [tempo_parada_min(p, turno.id) for p in pontos]

    # Frota oferecida ao solver = viagens possíveis. Precisa de folga sobre
    # DOIS mínimos, e não só sobre um:
    #   por assentos — quantas viagens cabem os alunos;
    #   por tempo    — quantas paradas cabem no limite de trajeto.
    # Com a demanda do Município Modelo os dois davam quase o mesmo número.
    # Com a planilha de um município de verdade, não: 196 pontos de 1,5 aluno
    # esgotam o tempo muito antes de esgotar os assentos, e o solver ficava
    # sem solução para a escola do centro.
    maior_capacidade = max(t.capacidade for t in tipos)
    minimo = math.ceil(sum(demandas) / maior_capacidade)
    base = max(minimo, viagens_pelo_tempo(tempo, paradas_min))
    oferta = {
        "ONIBUS31": base + 4,
        "MICRO20": max(3, base // 4),
        "VAN15A": max(2, math.ceil(sum(cadeirantes) / 2) + 1),
    }
    # Reforço: se a estimativa errar para baixo, o solver fica sem solução.
    # Em vez de desistir (que na tela do gestor vira "o sistema não roteirizou
    # o meu município"), oferece-se mais viagem e tenta de novo.
    for reforco in (0, max(2, base // 2), base * 2):
        frota = []
        for t in tipos:
            extra = reforco if t.id == "ONIBUS31" else 0
            frota += [t] * (oferta.get(t.id, 2) + extra)
        viagens = _resolver_com_frota(
            escola, turno, pontos, frota, dist, tempo, demandas, cadeirantes,
            paradas_min, tempo_limite_s)
        if viagens is not None:
            return viagens
    raise RuntimeError(
        f"Sem solução para {escola.nome} / {turno.nome} mesmo com frota "
        f"reforçada — reveja o tempo máximo de trajeto ({TEMPO_MAX_TRAJETO_MIN} "
        f"min) ou o raio de agrupamento dos pontos.")


def _resolver_com_frota(escola, turno, pontos, frota, dist, tempo, demandas,
                        cadeirantes, paradas_min, tempo_limite_s):
    """Resolve o CVRP com uma oferta de viagens dada. None = sem solução."""
    locais = [(escola.lat, escola.lon)] + [(p.lat, p.lon) for p in pontos]
    n_veic = len(frota)

    manager = pywrapcp.RoutingIndexManager(len(locais), n_veic, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cb_dist(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return int(dist[a][b] * 1000)  # metros

    def cb_tempo(i, j):
        """Deslocamento até a próxima parada + embarque na parada de origem."""
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return tempo[a][b] + paradas_min[a]

    di = routing.RegisterTransitCallback(cb_dist)
    ti = routing.RegisterTransitCallback(cb_tempo)
    routing.SetArcCostEvaluatorOfAllVehicles(di)

    # custo fixo por viagem usada (escala p/ solver: R$ fixo mensal /100)
    for v, t in enumerate(frota):
        routing.SetFixedCostOfVehicle(int(t.custo_fixo_mes / 100), v)

    # capacidade de assentos
    dcap = routing.RegisterUnaryTransitCallback(
        lambda i: demandas[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        dcap, 0, [t.capacidade for t in frota], True, "Assentos")

    # capacidade de posições de cadeirante
    ccap = routing.RegisterUnaryTransitCallback(
        lambda i: cadeirantes[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        ccap, 0, [t.posicoes_cadeirante for t in frota], True, "Cadeirantes")

    # tempo máximo da viagem (proxy do tempo do 1º aluno embarcado)
    routing.AddDimension(ti, 0, TEMPO_MAX_TRAJETO_MIN, True, "Tempo")

    # Estratégias de solução inicial em ordem de preferência. Com muitas
    # paradas e tempo máximo por viagem apertado, a construção gulosa clássica
    # (PATH_CHEAPEST_ARC) fecha viagens longas cedo e não consegue encaixar as
    # últimas paradas — ela sozinha não achava solução para a escola do centro.
    # A inserção em paralelo distribui as paradas entre as viagens e resolve.
    estrategias = [
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
        routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_INSERTION,
    ]
    sol = None
    for estrategia in estrategias:
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = estrategia
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        params.time_limit.FromSeconds(tempo_limite_s)
        sol = routing.SolveWithParameters(params)
        if sol:
            break
    if not sol:
        return None

    viagens = []
    for v in range(n_veic):
        idx = routing.Start(v)
        if routing.IsEnd(sol.Value(routing.NextVar(idx))):
            continue
        paradas, km, minutos, alunos, cad = [], 0.0, 0, 0, 0
        while not routing.IsEnd(idx):
            nxt = sol.Value(routing.NextVar(idx))
            a, b = manager.IndexToNode(idx), manager.IndexToNode(nxt)
            km += dist[a][b]
            minutos += tempo[a][b] + paradas_min[a]
            if a != 0:
                p = pontos[a - 1]
                paradas.append(p.id)
                alunos += p.alunos[turno.id]
                cad += p.alunos_cadeirantes.get(turno.id, 0)
            idx = nxt
        viagens.append({
            "id": f"{escola.id}-{turno.id}-{len(viagens) + 1:02d}",
            "turno": turno.id, "turno_nome": turno.nome,
            "escola_id": escola.id, "escola": escola.nome,
            "tipo_sugerido": frota[v].id,
            "paradas": paradas, "alunos": alunos, "cadeirantes": cad,
            "km_viagem": round(km, 1), "min_viagem": minutos,
        })
    return viagens


# --------------------------------------------------------- fase 2: jornadas ---
# A escala multiviagem vive em motor/escala.py: é heurística pura, sem
# OR-Tools, e por isso pode ser testada sozinha.


# ------------------------------------------------------------------ custos ---
def custos_frota(composicao, km_dia, tipos_por_id):
    """Custo mensal estimado de uma composição de frota + km diário."""
    fixo = sum(tipos_por_id[t].custo_fixo_mes * q for t, q in composicao.items())
    tot = sum(composicao.values())
    if tot == 0:
        return 0, 0, 0
    ckm = sum(tipos_por_id[t].custo_km * q for t, q in composicao.items()) / tot
    var = km_dia * DIAS_LETIVOS_MES * ckm
    litros_dia = sum(
        (km_dia * q / tot) / tipos_por_id[t].consumo_km_l
        for t, q in composicao.items()
    )
    return fixo + var, litros_dia, tot


def montar_relatorio(pontos, escolas=None, turnos=None, tipos=None,
                     municipio="Ribeirão Modelo (sintético)",
                     tempo_limite_s=TEMPO_LIMITE_SOLVER_S,
                     frota_declarada=None, permitir_estimativa=True,
                     progresso=None) -> dict:
    """Roda as duas fases e devolve o relatório completo.

    Separado de `main()` na Sprint 8 para que a MESMA conta sirva ao Município
    Modelo e à planilha de um município de verdade — quando a tela de
    planejamento manda roteirizar, é esta função que roda. Se o caminho fosse
    outro, o número da demonstração e o número do piloto poderiam divergir sem
    ninguém perceber.

    `frota_declarada`: {"composicao": {tipo: qtd}, "km_dia": float} quando o
    município informa a frota que tem hoje.

    `permitir_estimativa`: sem frota declarada, a do Município Modelo é
    reconstruída por estimativa. Com a planilha de um município real isso é
    proibido, e por um motivo concreto: a estimativa supõe ocupação de 85% e
    2,5 viagens por veículo, o que só vale para uma demanda adensada. Na
    primeira planilha real que passou por aqui — 297 alunos espalhados em 196
    pontos —, ela projetou 3 veículos contra os 23 que o plano precisa, e a
    "economia" saiu em −666%. Sem o "antes" informado, o relatório sai sem
    comparação e diz o que falta.
    `progresso`: função chamada a cada etapa, para a tela mostrar em que pé
    está (o solver leva minutos).
    """
    escolas = escolas if escolas is not None else ESCOLAS
    turnos = turnos if turnos is not None else TURNOS
    tipos = tipos if tipos is not None else TIPOS_VEICULO
    tipos_por_id = {t.id: t for t in tipos}
    avisar = progresso or (lambda etapa, detalhe="": None)

    todas_viagens, veiculos_por_turno = [], {}
    inviaveis = []
    for turno in turnos:
        viagens_turno = []
        for e in escolas:
            pts_e = [p for p in pontos if p.escola_id == e.id]
            avisar("roteirizando", f"{e.nome} · {turno.nome}")
            viagens_turno += resolver_viagens(e, turno, pts_e, tipos,
                                              tempo_limite_s=tempo_limite_s,
                                              inviaveis=inviaveis)
        veiculos_por_turno[turno.id] = montar_jornadas(
            viagens_turno, turno, tipos_por_id,
            partida_min=turno.janela_chegada[0] - MINUTOS_ANTES_DA_JANELA)
        todas_viagens += viagens_turno
        avisar("escalado", f"{turno.nome}: {len(viagens_turno)} viagens em "
                           f"{len(veiculos_por_turno[turno.id])} veículos")

    comp_otim = compor_frota(veiculos_por_turno)
    todos_veiculos = [v for lista in veiculos_por_turno.values() for v in lista]
    km_dia_otim = sum(v["km_turno"] for v in todos_veiculos) * VIAGENS_POR_ROTA

    alunos_por_turno = {t.id: sum(p.alunos.get(t.id, 0) for p in pontos)
                        for t in turnos}
    km_medio_viagem = (sum(v["km_viagem"] for v in todas_viagens)
                       / max(1, len(todas_viagens)))
    comparacao_indisponivel = ""
    if frota_declarada and frota_declarada.get("composicao"):
        frota_atual = _FrotaDeclarada(
            composicao={k: int(v) for k, v in
                        frota_declarada["composicao"].items() if int(v) > 0},
            km_dia_declarado=float(frota_declarada.get("km_dia") or 0.0),
            viagens_por_veiculo_turno=frota_declarada.get(
                "viagens_por_veiculo_turno"))
        premissas_frota_atual = [
            "A frota atual foi INFORMADA pelo município, não estimada.",
            f"Quilometragem declarada: {frota_atual.km_dia_declarado} km/dia.",
        ]
    elif permitir_estimativa:
        frota_atual, premissas_frota_atual = frota_atual_sintetica(
            alunos_por_turno, km_medio_viagem, VIAGENS_POR_ROTA, tipos)
    else:
        frota_atual, premissas_frota_atual = None, []
        comparacao_indisponivel = (
            "A frota atual do município não foi informada, então este plano "
            "não traz comparação nem economia. Informe quantos veículos de "
            "cada tipo o município opera hoje e a quilometragem diária — os "
            "dois números costumam estar no contrato de transporte ou no "
            "relatório do PNATE.")

    custo_otim, litros_otim, n_otim = custos_frota(
        comp_otim, km_dia_otim, tipos_por_id)
    if frota_atual is not None:
        custo_atual, litros_atual, n_atual = custos_frota(
            frota_atual.composicao, frota_atual.km_dia_declarado, tipos_por_id)
    else:
        custo_atual = litros_atual = n_atual = 0

    resultado = {
        "municipio": municipio,
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "premissas": {
            "dias_letivos_mes": DIAS_LETIVOS_MES,
            "preco_diesel_l": PRECO_DIESEL,
            "fator_co2_kg_l": FATOR_CO2_KG_L,
            "tempo_max_trajeto_min": TEMPO_MAX_TRAJETO_MIN,
            "tempo_virada_min": TEMPO_VIRADA_MIN,
            "jornada_max_turno_min": {t.id: t.jornada_max_min for t in turnos},
            "viagens_por_rota": VIAGENS_POR_ROTA,
            "fonte_tempos": "OSRM/haversine com fator rural 1.35 + tempo de "
                            "embarque por parada (corrigidos depois pelo "
                            "aprendizado com GPS real)",
            "custos_por_tipo": {
                t.id: {"nome": t.nome,
                       "capacidade": t.capacidade,
                       "posicoes_cadeirante": t.posicoes_cadeirante,
                       "fixo_mes": t.custo_fixo_mes, "custo_km": t.custo_km,
                       "consumo_km_l": t.consumo_km_l}
                for t in tipos
            },
        },
        # Coordenadas vão para o relatório porque o painel desenha o mapa a
        # partir DELE, não do gerador: com a planilha real de um município, o
        # mapa tem que sair igual sem o painel conhecer o Município Modelo.
        "geografia": {
            "escolas": [{"id": e.id, "nome": e.nome, "lat": e.lat, "lon": e.lon}
                        for e in escolas],
            "pontos": {p.id: [round(p.lat, 6), round(p.lon, 6)] for p in pontos},
        },
        "demanda": {
            "alunos": sum(p.total_alunos() for p in pontos),
            "alunos_por_turno": alunos_por_turno,
            "cadeirantes": sum(sum(p.alunos_cadeirantes.values()) for p in pontos),
            "cadeirantes_por_turno": {
                t.id: sum(p.alunos_cadeirantes.get(t.id, 0) for p in pontos)
                for t in turnos},
            "pontos_embarque": len(pontos),
            "escolas": len(escolas),
            "turnos": [{"id": t.id, "nome": t.nome,
                        "jornada_max_min": t.jornada_max_min} for t in turnos],
        },
        "frota_atual": {
            "composicao": frota_atual.composicao,
            "total_veiculos": n_atual,
            "km_dia": frota_atual.km_dia_declarado,
            "custo_mes": round(custo_atual),
            "litros_dia": round(litros_atual, 1),
            "viagens_por_veiculo_turno": frota_atual.viagens_por_veiculo_turno,
            "como_foi_estimada": premissas_frota_atual,
        } if frota_atual is not None else None,
        "frota_otimizada": {
            "composicao": comp_otim,
            "total_veiculos": n_otim,
            "km_dia": round(km_dia_otim, 1),
            "custo_mes": round(custo_otim),
            "litros_dia": round(litros_otim, 1),
            "viagens": todas_viagens,
            "veiculos": todos_veiculos,
            "viagens_por_veiculo_turno": round(
                len(todas_viagens) / max(1, len(todos_veiculos)), 2),
            "por_turno": {
                t.id: {"viagens": len([v for v in todas_viagens
                                       if v["turno"] == t.id]),
                       "veiculos": len(veiculos_por_turno[t.id])}
                for t in turnos
            },
        },
    }
    eco_mes = custo_atual - custo_otim
    resultado["economia"] = None if frota_atual is None else {
        "veiculos": n_atual - n_otim,
        "reducao_frota_pct": round(100 * (n_atual - n_otim) / n_atual, 1),
        "custo_mes": round(eco_mes),
        "custo_ano": round(eco_mes * 12),
        "km_dia": round(frota_atual.km_dia_declarado - km_dia_otim, 1),
        "litros_dia": round(litros_atual - litros_otim, 1),
        "tco2_ano": round(
            (litros_atual - litros_otim) * DIAS_LETIVOS_MES * 12
            * FATOR_CO2_KG_L / 1000, 1),
    }
    if comparacao_indisponivel:
        resultado["comparacao_indisponivel"] = comparacao_indisponivel
    resultado["coerencia"] = _conferir_coerencia(resultado, frota_atual,
                                                 tipos_por_id, turnos)
    # Demanda que não coube em rota nenhuma dentro da regra da secretaria.
    # Fica no relatório em campo próprio, porque é decisão de gente — e porque
    # um plano que esconde a criança que ficou de fora não vale nada.
    resultado["demanda_nao_atendida"] = {
        "pontos": inviaveis,
        "alunos": sum(i["alunos"] for i in inviaveis),
        "por_turno": {t.id: sum(i["alunos"] for i in inviaveis
                                if i["turno"] == t.id) for t in turnos},
    }
    if inviaveis:
        avisar("atenção", f"{resultado['demanda_nao_atendida']['alunos']} aluno(s) "
                          f"em {len(inviaveis)} ponto(s) não cabem no limite de "
                          f"{TEMPO_MAX_TRAJETO_MIN} min — decisão da secretaria")
    if resultado["economia"]:
        avisar("pronto", f"{n_otim} veículos · "
                         f"{resultado['economia']['veiculos']} a menos que a "
                         f"frota atual")
    else:
        avisar("pronto", f"{n_otim} veículos — sem comparação: falta a frota "
                         f"atual do município")
    return resultado


def _conferir_coerencia(resultado, frota_atual, tipos_por_id, turnos) -> list:
    """Confere se demanda e frota declarada contam a mesma história.

    Apareceu na primeira planilha real que passou pelo sistema: 297 alunos e
    uma frota declarada de 30 veículos (772 lugares). A conta fechava e a
    "economia" saía enorme — mas o que aquilo dizia de verdade é que a
    planilha de alunos era de uma parte do município e a frota, do município
    inteiro. Comparar os dois é comparar coisas diferentes.

    O sistema não corrige isso sozinho: ele avisa antes de alguém levar o
    número para uma reunião.
    """
    avisos = []
    if frota_atual is None:
        return avisos
    lugares = sum(tipos_por_id[t].capacidade * q
                  for t, q in frota_atual.composicao.items()
                  if t in tipos_por_id)
    maior_turno = max(resultado["demanda"]["alunos_por_turno"].values() or [0])
    if maior_turno and lugares > maior_turno * 2:
        avisos.append(
            f"A frota declarada oferece {lugares} lugares por viagem, para um "
            f"turno de {maior_turno} alunos ({lugares / maior_turno:.1f}× a "
            f"demanda). Confira se a planilha de alunos cobre o município "
            f"inteiro — comparar a frota do município com uma parte dos alunos "
            f"produz uma economia que não existe.")
    if maior_turno and lugares and lugares < maior_turno:
        avisos.append(
            f"A frota declarada tem {lugares} lugares por viagem para "
            f"{maior_turno} alunos no maior turno. Ou faltam veículos na "
            f"declaração, ou a operação de hoje já depende de mais viagens do "
            f"que o contrato prevê.")
    if frota_atual.km_dia_declarado <= 0:
        avisos.append(
            "A quilometragem diária da frota atual não foi informada: sem ela, "
            "o custo variável do 'antes' fica subestimado e a economia sai "
            "menor do que é.")
    return avisos


def main():
    resultado = montar_relatorio(
        gerar_pontos(),
        progresso=lambda etapa, detalhe="": print(f"  {etapa}: {detalhe}",
                                                  flush=True))
    todas_viagens = resultado["frota_otimizada"]["viagens"]

    destino = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")
    os.makedirs(destino, exist_ok=True)
    with open(os.path.join(destino, "dimensionamento.json"), "w",
              encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------ resumo executivo ----
    e = resultado["economia"]
    fa, fo = resultado["frota_atual"], resultado["frota_otimizada"]
    d = resultado["demanda"]
    nome = {t.id: t.nome for t in TIPOS_VEICULO}
    print("=" * 68)
    print(f"MOBGOV · Dimensionamento de Frota — {resultado['municipio']}")
    print("=" * 68)
    print(f"Demanda: {d['alunos']} alunos/dia ({d['cadeirantes']} cadeirantes) em "
          f"{d['pontos_embarque']} pontos, {d['escolas']} escolas, "
          f"{len(d['turnos'])} turnos")
    for t in d["turnos"]:
        print(f"   - {t['nome']}: {d['alunos_por_turno'][t['id']]} alunos, "
              f"{fo['por_turno'][t['id']]['viagens']} viagens, "
              f"{fo['por_turno'][t['id']]['veiculos']} veículos")
    print(f"\nFROTA ATUAL:      {fa['total_veiculos']} veículos | "
          f"{fa['km_dia']:.0f} km/dia | R$ {fa['custo_mes']:,} /mês")
    for t, q in fa["composicao"].items():
        print(f"   - {q:2d}x {nome[t]}")
    print(f"\nFROTA NECESSÁRIA: {fo['total_veiculos']} veículos | "
          f"{fo['km_dia']:.0f} km/dia | R$ {fo['custo_mes']:,} /mês | "
          f"{fo['viagens_por_veiculo_turno']} viagens por veículo/turno")
    for t, q in sorted(fo["composicao"].items()):
        print(f"   - {q:2d}x {nome[t]}")
    print("\n" + "-" * 68)
    print(f"ECONOMIA: {e['veiculos']} veículos a menos "
          f"(-{e['reducao_frota_pct']}%) | R$ {e['custo_mes']:,}/mês | "
          f"R$ {e['custo_ano']:,}/ano")
    print(f"          {e['km_dia']:.0f} km/dia | {e['litros_dia']:.0f} "
          f"litros/dia | {e['tco2_ano']} tCO2/ano evitadas")
    print("-" * 68)
    oc = sorted(todas_viagens, key=lambda v: -v["ocupacao_pct"])
    print(f"Ocupação média das viagens: "
          f"{sum(v['ocupacao_pct'] for v in todas_viagens)//len(todas_viagens)}% "
          f"(máx {oc[0]['ocupacao_pct']}%, mín {oc[-1]['ocupacao_pct']}%)")
    print("Relatório completo: relatorios/dimensionamento.json")


if __name__ == "__main__":
    main()
