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
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from motor.escala import montar_jornadas, compor_frota, TEMPO_VIRADA_MIN
from dados import tempos as tempos_mod
from dados.municipio_modelo import (
    ESCOLAS, TIPOS_VEICULO, TURNOS, gerar_pontos, frota_atual_sintetica,
    tempo_parada_min,
)

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
def resolver_viagens(escola, turno, pontos, tipos,
                     tempo_limite_s=TEMPO_LIMITE_SOLVER_S, provedor=None):
    """Resolve as viagens de coleta de uma escola em um turno."""
    pontos = [p for p in pontos if p.alunos.get(turno.id, 0) > 0]
    if not pontos:
        return []

    locais = [(escola.lat, escola.lon)] + [(p.lat, p.lon) for p in pontos]
    provedor = provedor or tempos_mod.provedor_padrao()
    partida = turno.janela_chegada[0] - MINUTOS_ANTES_DA_JANELA
    zonas = [tempos_mod.zona_de(l) for l in locais]
    dist, tempo = provedor.matriz(locais, partida_min=partida, zonas=zonas)

    demandas = [0] + [p.alunos[turno.id] for p in pontos]
    cadeirantes = [0] + [p.alunos_cadeirantes.get(turno.id, 0) for p in pontos]
    paradas_min = [0] + [tempo_parada_min(p, turno.id) for p in pontos]

    # Frota oferecida ao solver = viagens possíveis. Dimensionada com folga
    # sobre o mínimo teórico de assentos, para não amarrar a solução.
    maior_capacidade = max(t.capacidade for t in tipos)
    minimo = math.ceil(sum(demandas) / maior_capacidade)
    oferta = {
        "ONIBUS31": minimo + 4,
        "MICRO20": max(3, minimo // 4),
        "VAN15A": max(2, math.ceil(sum(cadeirantes) / 2) + 1),
    }
    frota = []
    for t in tipos:
        frota += [t] * oferta.get(t.id, 2)
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
        raise RuntimeError(
            f"Sem solução para {escola.nome} / {turno.nome} — verifique a "
            f"oferta de veículos e o tempo máximo de trajeto")

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


def main():
    pontos = gerar_pontos()
    tipos_por_id = {t.id: t for t in TIPOS_VEICULO}

    todas_viagens, veiculos_por_turno = [], {}
    for turno in TURNOS:
        viagens_turno = []
        for e in ESCOLAS:
            pts_e = [p for p in pontos if p.escola_id == e.id]
            viagens_turno += resolver_viagens(e, turno, pts_e, TIPOS_VEICULO)
        veiculos_por_turno[turno.id] = montar_jornadas(
            viagens_turno, turno, tipos_por_id,
            partida_min=turno.janela_chegada[0] - MINUTOS_ANTES_DA_JANELA)
        todas_viagens += viagens_turno
        print(f"  {turno.nome}: {len(viagens_turno)} viagens em "
              f"{len(veiculos_por_turno[turno.id])} veículos", flush=True)

    comp_otim = compor_frota(veiculos_por_turno)
    todos_veiculos = [v for lista in veiculos_por_turno.values() for v in lista]
    km_dia_otim = sum(v["km_turno"] for v in todos_veiculos) * VIAGENS_POR_ROTA

    alunos_por_turno = {t.id: sum(p.alunos[t.id] for p in pontos) for t in TURNOS}
    km_medio_viagem = (sum(v["km_viagem"] for v in todas_viagens)
                       / max(1, len(todas_viagens)))
    frota_atual, premissas_frota_atual = frota_atual_sintetica(
        alunos_por_turno, km_medio_viagem, VIAGENS_POR_ROTA, TIPOS_VEICULO)

    custo_otim, litros_otim, n_otim = custos_frota(
        comp_otim, km_dia_otim, tipos_por_id)
    custo_atual, litros_atual, n_atual = custos_frota(
        frota_atual.composicao, frota_atual.km_dia_declarado, tipos_por_id)

    resultado = {
        "municipio": "Ribeirão Modelo (sintético)",
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "premissas": {
            "dias_letivos_mes": DIAS_LETIVOS_MES,
            "preco_diesel_l": PRECO_DIESEL,
            "fator_co2_kg_l": FATOR_CO2_KG_L,
            "tempo_max_trajeto_min": TEMPO_MAX_TRAJETO_MIN,
            "tempo_virada_min": TEMPO_VIRADA_MIN,
            "jornada_max_turno_min": {t.id: t.jornada_max_min for t in TURNOS},
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
                for t in TIPOS_VEICULO
            },
        },
        "demanda": {
            "alunos": sum(p.total_alunos() for p in pontos),
            "alunos_por_turno": {
                t.id: sum(p.alunos[t.id] for p in pontos) for t in TURNOS},
            "cadeirantes": sum(sum(p.alunos_cadeirantes.values()) for p in pontos),
            "cadeirantes_por_turno": {
                t.id: sum(p.alunos_cadeirantes.get(t.id, 0) for p in pontos)
                for t in TURNOS},
            "pontos_embarque": len(pontos),
            "escolas": len(ESCOLAS),
            "turnos": [{"id": t.id, "nome": t.nome,
                        "jornada_max_min": t.jornada_max_min} for t in TURNOS],
        },
        "frota_atual": {
            "composicao": frota_atual.composicao,
            "total_veiculos": n_atual,
            "km_dia": frota_atual.km_dia_declarado,
            "custo_mes": round(custo_atual),
            "litros_dia": round(litros_atual, 1),
            "viagens_por_veiculo_turno": frota_atual.viagens_por_veiculo_turno,
            "como_foi_estimada": premissas_frota_atual,
        },
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
                for t in TURNOS
            },
        },
    }
    eco_mes = custo_atual - custo_otim
    resultado["economia"] = {
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
    print("MOBGOV · Dimensionamento de Frota — Ribeirão Modelo")
    print("=" * 68)
    print(f"Demanda: {d['alunos']} alunos/dia ({d['cadeirantes']} cadeirantes) em "
          f"{d['pontos_embarque']} pontos, {d['escolas']} escolas, "
          f"{len(d['turnos'])} turnos")
    for t in TURNOS:
        print(f"   - {t.nome}: {d['alunos_por_turno'][t.id]} alunos, "
              f"{fo['por_turno'][t.id]['viagens']} viagens, "
              f"{fo['por_turno'][t.id]['veiculos']} veículos")
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
