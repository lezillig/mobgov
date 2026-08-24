# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 4 · agent-porta-a-porta
Roteirização PORTA A PORTA para usuários com deficiência (PDPTW).

O escolar é um problema de coleta: todo mundo desce no mesmo lugar. O porta a
porta não — cada usuário tem a própria origem e o próprio destino, e a rota
intercala **n embarques e n desembarques**. É o *pickup and delivery problem
with time windows* que RideCo, Spare e Via resolvem continuamente.

O que este motor garante, e que um roteirizador de entrega não garantiria:

1. **Par indissociável**: quem embarca com um veículo desembarca com o mesmo,
   e o embarque vem antes do desembarque (restrição de precedência).
2. **Janela de chegada** por usuário — a consulta é às 9h, não "de manhã".
3. **Tempo máximo a bordo** por usuário: tempo direto × fator + folga. Sem
   isso, a otimização "empilha" gente no veículo e o usuário roda a cidade
   inteira — a queixa clássica do paratransit.
4. **Posição de cadeira de rodas** como capacidade separada do assento, e
   acompanhante ocupando assento.
5. **Tempo de embarque na porta**, maior para quem usa rampa ou elevador.

Saída: rotas com a sequência de eventos, tempo a bordo de cada usuário e a
frota mínima necessária — no mesmo formato auditável do resto do sistema.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from dados import tempos as tempos_mod
from dados.demanda_pcd import (
    GARAGEM, TIPOS_PCD, PedidoPCD, limite_tempo_bordo_min, tempo_embarque_min,
)

TEMPO_LIMITE_SOLVER_S = 30
# O horizonte é RELÓGIO ABSOLUTO: as janelas vêm em minutos desde 00:00, e a
# dimensão de tempo não zera na saída da garagem. 16 h cobre o dia do porta a
# porta escolar; o transporte sanitário vai além (hemodiálise do turno das
# 16 h volta às 20 h), e por isso os dois são parâmetro, não constante.
HORIZONTE_MIN = 16 * 60          # o dia de operação cabe em 16 h
ESPERA_MAXIMA_MIN = 30           # veículo parado esperando janela abrir
# Quantos passageiros uma rota porta a porta costuma juntar, medido na
# operação real: ~5. É o divisor da oferta de veículos ao solver — ver o
# comentário longo em `resolver`. Deliberadamente conservador (oferta maior
# custa tempo de solver; oferta menor devolve "sem solução" enganoso).
PASSAGEIROS_POR_ROTA = 4


_zona = tempos_mod.zona_de


def oferta_de_veiculos(quantos_pedidos: int) -> int:
    """Quantos veículos de cada tipo oferecer ao solver.

    NÃO depende da capacidade do veículo — ver o comentário em `resolver`.
    """
    return max(3, math.ceil(quantos_pedidos / PASSAGEIROS_POR_ROTA))


def resolver(pedidos: list, tipos=None, provedor=None, partida_min: int = 7 * 60,
             tempo_limite_s: int = TEMPO_LIMITE_SOLVER_S,
             veiculos_por_tipo: int = None,
             horizonte_min: int = HORIZONTE_MIN,
             espera_maxima_min: int = ESPERA_MAXIMA_MIN) -> dict:
    """Resolve o dia do porta a porta. Devolve rotas, frota e indicadores."""
    if not pedidos:
        return {"rotas": [], "composicao": {}, "total_veiculos": 0,
                "km_dia": 0.0, "pedidos": 0}

    tipos = tipos or TIPOS_PCD
    provedor = provedor or tempos_mod.provedor_padrao()

    # nós: 0 = garagem; para cada pedido, um de embarque e um de desembarque
    locais = [GARAGEM]
    for p in pedidos:
        locais += [p.origem, p.destino]
    zonas = [_zona(l) for l in locais]
    dist, tempo = provedor.matriz(locais, partida_min=partida_min, zonas=zonas)

    def no_embarque(i):
        return 1 + 2 * i

    def no_desembarque(i):
        return 2 + 2 * i

    # tempo de serviço por nó (embarque na porta, desembarque no destino)
    servico = [0] * len(locais)
    for i, p in enumerate(pedidos):
        servico[no_embarque(i)] = tempo_embarque_min(p)
        servico[no_desembarque(i)] = tempo_embarque_min(p)

    # Frota oferecida: generosa, com custo fixo por veículo usado para que o
    # próprio solver minimize a quantidade.
    #
    # O divisor NÃO é a capacidade do veículo, e isso é contraintuitivo. Numa
    # operação real de 268 alunos para 101 escolas com janela de 20 minutos, o
    # motor fecha ~5 passageiros por veículo — seja ele de 6 ou de 12 lugares.
    # Dimensionar a oferta por assento dava 35 veículos para um carro de 12, e
    # o modelo saía "sem solução": não por falta de assento, por falta de
    # carro. Quem descarta a configuração de veículo por causa disso descarta
    # a certa. O divisor é o que uma rota porta a porta consegue juntar.
    if veiculos_por_tipo is None:
        veiculos_por_tipo = oferta_de_veiculos(len(pedidos))
    frota = []
    for t in tipos:
        frota += [t] * veiculos_por_tipo
    n_veic = len(frota)

    manager = pywrapcp.RoutingIndexManager(len(locais), n_veic, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cb_dist(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return int(dist[a][b] * 1000)

    def cb_tempo(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return tempo[a][b] + servico[a]

    di = routing.RegisterTransitCallback(cb_dist)
    ti = routing.RegisterTransitCallback(cb_tempo)
    routing.SetArcCostEvaluatorOfAllVehicles(di)
    for v, t in enumerate(frota):
        routing.SetFixedCostOfVehicle(int(t.custo_fixo_mes / 100), v)

    # ---- capacidades: assento e posição de cadeira são dimensões separadas
    assentos = [0] * len(locais)
    cadeiras = [0] * len(locais)
    for i, p in enumerate(pedidos):
        assentos[no_embarque(i)] = p.assentos
        assentos[no_desembarque(i)] = -p.assentos
        cadeiras[no_embarque(i)] = p.posicoes_cadeira
        cadeiras[no_desembarque(i)] = -p.posicoes_cadeira

    ca = routing.RegisterUnaryTransitCallback(
        lambda i: assentos[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        ca, 0, [t.capacidade for t in frota], True, "Assentos")
    cc = routing.RegisterUnaryTransitCallback(
        lambda i: cadeiras[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        cc, 0, [t.posicoes_cadeirante for t in frota], True, "Cadeiras")

    # ---- tempo: com folga (o veículo pode esperar a janela abrir)
    routing.AddDimension(ti, espera_maxima_min, horizonte_min, False, "Tempo")
    dim_tempo = routing.GetDimensionOrDie("Tempo")

    solver = routing.solver()
    for i, p in enumerate(pedidos):
        emb = manager.NodeToIndex(no_embarque(i))
        des = manager.NodeToIndex(no_desembarque(i))

        # par indissociável, mesmo veículo, embarque antes do desembarque
        routing.AddPickupAndDelivery(emb, des)
        solver.Add(routing.VehicleVar(emb) == routing.VehicleVar(des))
        solver.Add(dim_tempo.CumulVar(emb) <= dim_tempo.CumulVar(des))

        # janela de chegada do usuário
        ini, fim = p.janela_chegada
        dim_tempo.CumulVar(des).SetRange(int(ini), int(fim))

        # tempo máximo a bordo. O pedido pode apertar o limite geral — quem
        # vai fazer exame em jejum não pode rodar 90 min coletando os outros.
        direto = tempo[no_embarque(i)][no_desembarque(i)]
        limite = limite_tempo_bordo_min(direto)
        aperto = getattr(p, "tempo_max_bordo_min", None)
        if aperto:
            limite = min(limite, int(aperto))
        solver.Add(dim_tempo.CumulVar(des) - dim_tempo.CumulVar(emb) <= limite)

    for v in range(n_veic):
        routing.AddVariableMinimizedByFinalizer(
            dim_tempo.CumulVar(routing.Start(v)))
        routing.AddVariableMinimizedByFinalizer(
            dim_tempo.CumulVar(routing.End(v)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION)
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    params.time_limit.FromSeconds(tempo_limite_s)
    sol = routing.SolveWithParameters(params)
    if not sol:
        raise RuntimeError(
            "Sem solução para o porta a porta — janelas apertadas demais ou "
            "frota insuficiente. Afrouxe a janela de chegada ou aumente a "
            "oferta de veículos.")

    return _extrair(routing, manager, sol, dim_tempo, frota, pedidos, dist,
                    tempo, provedor, partida_min)


def _extrair(routing, manager, sol, dim_tempo, frota, pedidos, dist, tempo,
             provedor, partida_min) -> dict:
    """Traduz a solução do solver para o formato do relatório."""
    por_no = {}
    for i, p in enumerate(pedidos):
        por_no[1 + 2 * i] = ("embarque", p)
        por_no[2 + 2 * i] = ("desembarque", p)

    rotas, composicao = [], {}
    bordo_por_usuario = {}
    for v in range(len(frota)):
        idx = routing.Start(v)
        if routing.IsEnd(sol.Value(routing.NextVar(idx))):
            continue
        eventos, km, ocupacao, pico = [], 0.0, 0, 0
        while not routing.IsEnd(idx):
            no = manager.IndexToNode(idx)
            if no in por_no:
                tipo_evento, pedido = por_no[no]
                minuto = sol.Min(dim_tempo.CumulVar(idx))
                ocupacao += (pedido.assentos + pedido.posicoes_cadeira
                             if tipo_evento == "embarque"
                             else -(pedido.assentos + pedido.posicoes_cadeira))
                pico = max(pico, ocupacao)
                coord = (pedido.origem if tipo_evento == "embarque"
                         else pedido.destino)
                eventos.append({
                    "tipo": tipo_evento,
                    "usuario": pedido.id,
                    "lat": round(coord[0], 6),
                    "lon": round(coord[1], 6),
                    "minuto": minuto,
                    "hora": f"{minuto // 60:02d}h{minuto % 60:02d}",
                    "cadeirante": pedido.cadeirante,
                    "acompanhante": pedido.acompanhante,
                    "ocupacao_apos": ocupacao,
                })
                if tipo_evento == "embarque":
                    bordo_por_usuario[pedido.id] = {"embarque": minuto}
                else:
                    reg = bordo_por_usuario.setdefault(pedido.id, {})
                    reg["desembarque"] = minuto
                    reg["direto"] = tempo[1 + 2 * pedidos.index(pedido)][
                        2 + 2 * pedidos.index(pedido)]
            prox = sol.Value(routing.NextVar(idx))
            a, b = manager.IndexToNode(idx), manager.IndexToNode(prox)
            km += dist[a][b]
            idx = prox

        t = frota[v]
        composicao[t.id] = composicao.get(t.id, 0) + 1
        embarques = [e for e in eventos if e["tipo"] == "embarque"]
        rotas.append({
            "id": f"PP{len(rotas) + 1:02d}",
            "tipo": t.id,
            "tipo_nome": t.nome,
            "capacidade": t.capacidade,
            "posicoes_cadeirante": t.posicoes_cadeirante,
            "usuarios": len(embarques),
            "cadeirantes": sum(1 for e in embarques if e["cadeirante"]),
            "eventos": eventos,
            "km": round(km, 1),
            "inicio": eventos[0]["hora"] if eventos else "—",
            "fim": eventos[-1]["hora"] if eventos else "—",
            "minutos": (eventos[-1]["minuto"] - eventos[0]["minuto"]
                        if eventos else 0),
            "ocupacao_maxima": pico,
            "ocupacao_maxima_pct": round(100 * pico / t.capacidade),
        })

    bordo = []
    for uid, reg in bordo_por_usuario.items():
        if "desembarque" in reg and "embarque" in reg:
            a_bordo = reg["desembarque"] - reg["embarque"]
            direto = reg.get("direto", 0)
            bordo.append({
                "usuario": uid,
                "min_a_bordo": a_bordo,
                "min_direto": direto,
                "limite": limite_tempo_bordo_min(direto),
                "desvio_pct": round(100 * (a_bordo - direto) / direto)
                if direto else 0,
            })

    km_dia = sum(r["km"] for r in rotas)
    return {
        "pedidos": len(pedidos),
        "rotas": rotas,
        "composicao": composicao,
        "total_veiculos": len(rotas),
        "km_dia": round(km_dia, 1),
        "tempo_bordo": bordo,
        "provedor_tempos": provedor.nome,
        "partida_min": partida_min,
        "indicadores": _indicadores(rotas, bordo, pedidos),
    }


def contexto_reotimizacao(pedidos: list, fila_espera: list = None,
                          provedor=None, partida_min: int = 7 * 60) -> dict:
    """Prepara coordenadas e índices para o módulo de reotimização.

    A reotimização do dia precisa dos mesmos nós que o solver usou; em vez de
    cada módulo remontar isso do seu jeito (e divergir), o mapa sai daqui.
    """
    provedor = provedor or tempos_mod.provedor_padrao()
    todos = list(pedidos) + list(fila_espera or [])
    coords = [GARAGEM]
    indices = {}
    for p in todos:
        indices[p.id] = {"no_origem": len(coords), "no_destino": len(coords) + 1,
                         "servico": tempo_embarque_min(p)}
        coords += [p.origem, p.destino]
    zonas = [_zona(l) for l in coords]
    _, tempo = provedor.matriz(coords, partida_min=partida_min, zonas=zonas)
    for p in todos:
        ix = indices[p.id]
        ix["direto"] = tempo[ix["no_origem"]][ix["no_destino"]]
    return {"coords": coords, "indices": indices,
            "pedidos_por_id": {p.id: p for p in todos}}


def eventos_com_nos(rota: dict, contexto: dict) -> list:
    """Converte os eventos de uma rota no formato que a reotimização consome."""
    eventos = []
    for ev in rota["eventos"]:
        ix = contexto["indices"][ev["usuario"]]
        eventos.append({
            "tipo": ev["tipo"],
            "usuario": ev["usuario"],
            "no": ix["no_origem"] if ev["tipo"] == "embarque" else ix["no_destino"],
            "servico": ix["servico"],
            "direto": ix["direto"],
            "minuto": ev["minuto"],
        })
    return eventos


def _indicadores(rotas, bordo, pedidos) -> dict:
    if not rotas:
        return {}
    a_bordo = [b["min_a_bordo"] for b in bordo] or [0]
    dentro = sum(1 for b in bordo if b["min_a_bordo"] <= b["limite"])
    return {
        "usuarios_por_veiculo": round(len(pedidos) / len(rotas), 2),
        "tempo_bordo_medio_min": round(sum(a_bordo) / len(a_bordo), 1),
        "tempo_bordo_max_min": max(a_bordo),
        "dentro_do_limite_pct": round(100 * dentro / len(bordo), 1) if bordo else 0,
        "compartilhamento_max": max(r["ocupacao_maxima"] for r in rotas),
        "ocupacao_media_pct": round(
            sum(r["ocupacao_maxima_pct"] for r in rotas) / len(rotas), 1),
        "km_por_usuario": round(
            sum(r["km"] for r in rotas) / max(1, len(pedidos)), 2),
    }
