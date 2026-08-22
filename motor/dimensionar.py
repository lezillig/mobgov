# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 1 · agent-rotas
Motor de dimensionamento de frota: CVRP escolar com frota heterogênea,
restrição de cadeirantes e tempo máximo de trajeto por aluno.

Estratégia MVP:
- Resolve por escola (cada escola é um depósito de chegada).
- Oferece ao solver uma frota "generosa" de cada tipo com custo fixo por
  veículo usado -> o próprio solver minimiza o número de veículos.
- Compara o resultado com a frota atual declarada e gera o relatório
  antes vs depois com premissas explícitas.
"""
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from dados.municipio_modelo import (
    ESCOLAS, TIPOS_VEICULO, FROTA_ATUAL, gerar_pontos, matriz_tempo_dist,
)

TEMPO_MAX_TRAJETO_MIN = 75   # parâmetro da secretaria: aluno no veículo <= 75 min
DIAS_LETIVOS_MES = 22
PRECO_DIESEL = 6.10          # R$/l — premissa declarada no relatório
FATOR_CO2_KG_L = 2.68        # kg CO2 por litro de diesel
VIAGENS_DIA = 2              # ida (manhã) + volta (tarde) espelhada


def resolver_escola(escola, pontos, tipos, tempo_limite_s=20):
    """Resolve o roteamento dos pontos de uma escola; retorna rotas usadas."""
    locais = [(escola.lat, escola.lon)] + [(p.lat, p.lon) for p in pontos]
    dist, tempo = matriz_tempo_dist(locais)

    demandas = [0] + [p.alunos for p in pontos]
    cadeirantes = [0] + [p.alunos_cadeirantes for p in pontos]

    # frota oferecida ao solver: generosa; custo fixo faz minimizar uso
    frota = []
    for t in tipos:
        frota += [t] * 14
    n_veic = len(frota)

    manager = pywrapcp.RoutingIndexManager(len(locais), n_veic, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cb_dist(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return int(dist[a][b] * 1000)  # metros

    def cb_tempo(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return tempo[a][b]

    di = routing.RegisterTransitCallback(cb_dist)
    ti = routing.RegisterTransitCallback(cb_tempo)
    routing.SetArcCostEvaluatorOfAllVehicles(di)

    # custo fixo por veículo usado (escala p/ solver: R$ fixo mensal /100)
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

    # tempo máximo de rota (proxy do tempo máximo do 1º aluno embarcado)
    routing.AddDimension(ti, 0, TEMPO_MAX_TRAJETO_MIN, True, "Tempo")

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    params.time_limit.FromSeconds(tempo_limite_s)

    sol = routing.SolveWithParameters(params)
    if not sol:
        raise RuntimeError(f"Sem solução para {escola.nome}")

    rotas = []
    for v in range(n_veic):
        idx = routing.Start(v)
        if routing.IsEnd(sol.Value(routing.NextVar(idx))):
            continue
        paradas, km, minutos, alunos, cad = [], 0.0, 0, 0, 0
        while not routing.IsEnd(idx):
            nxt = sol.Value(routing.NextVar(idx))
            a, b = manager.IndexToNode(idx), manager.IndexToNode(nxt)
            km += dist[a][b]
            minutos += tempo[a][b]
            if a != 0:
                p = pontos[a - 1]
                paradas.append(p.id)
                alunos += p.alunos
                cad += p.alunos_cadeirantes
            idx = nxt
        rotas.append({
            "tipo": frota[v].id, "tipo_nome": frota[v].nome,
            "escola": escola.nome, "paradas": paradas,
            "alunos": alunos, "cadeirantes": cad,
            "km_viagem": round(km, 1), "min_viagem": minutos,
            "ocupacao_pct": round(100 * alunos / frota[v].capacidade),
        })
    return rotas


def custos_frota(composicao, km_dia, tipos_por_id):
    """Custo mensal estimado de uma composição de frota + km diário."""
    fixo = sum(tipos_por_id[t].custo_fixo_mes * q for t, q in composicao.items())
    # custo variável: usa custo_km médio ponderado da composição
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

    todas_rotas = []
    for e in ESCOLAS:
        pts_e = [p for p in pontos if p.escola_id == e.id]
        todas_rotas += resolver_escola(e, pts_e, TIPOS_VEICULO)

    # composição otimizada
    comp_otim = {}
    for r in todas_rotas:
        comp_otim[r["tipo"]] = comp_otim.get(r["tipo"], 0) + 1
    km_dia_otim = sum(r["km_viagem"] for r in todas_rotas) * VIAGENS_DIA

    custo_otim, litros_otim, n_otim = custos_frota(
        comp_otim, km_dia_otim, tipos_por_id)
    custo_atual, litros_atual, n_atual = custos_frota(
        FROTA_ATUAL.composicao, FROTA_ATUAL.km_dia_declarado, tipos_por_id)

    resultado = {
        "municipio": "Ribeirão Modelo (sintético)",
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "premissas": {
            "dias_letivos_mes": DIAS_LETIVOS_MES,
            "preco_diesel_l": PRECO_DIESEL,
            "fator_co2_kg_l": FATOR_CO2_KG_L,
            "tempo_max_trajeto_min": TEMPO_MAX_TRAJETO_MIN,
            "viagens_por_dia": VIAGENS_DIA,
            "fonte_tempos": "OSRM/haversine com fator rural 1.35 "
                            "(corrigido depois pelo aprendizado com GPS real)",
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
            "alunos": sum(p.alunos for p in pontos),
            "cadeirantes": sum(p.alunos_cadeirantes for p in pontos),
            "pontos_embarque": len(pontos),
            "escolas": len(ESCOLAS),
        },
        "frota_atual": {
            "composicao": FROTA_ATUAL.composicao,
            "total_veiculos": n_atual,
            "km_dia": FROTA_ATUAL.km_dia_declarado,
            "custo_mes": round(custo_atual),
            "litros_dia": round(litros_atual, 1),
        },
        "frota_otimizada": {
            "composicao": comp_otim,
            "total_veiculos": n_otim,
            "km_dia": round(km_dia_otim, 1),
            "custo_mes": round(custo_otim),
            "litros_dia": round(litros_otim, 1),
            "rotas": todas_rotas,
        },
    }
    eco_mes = custo_atual - custo_otim
    resultado["economia"] = {
        "veiculos": n_atual - n_otim,
        "reducao_frota_pct": round(100 * (n_atual - n_otim) / n_atual, 1),
        "custo_mes": round(eco_mes),
        "custo_ano": round(eco_mes * 12),
        "km_dia": round(FROTA_ATUAL.km_dia_declarado - km_dia_otim, 1),
        "litros_dia": round(litros_atual - litros_otim, 1),
        "tco2_ano": round(
            (litros_atual - litros_otim) * DIAS_LETIVOS_MES * 12
            * FATOR_CO2_KG_L / 1000, 1),
    }

    os.makedirs("relatorios", exist_ok=True)
    with open("relatorios/dimensionamento.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------ resumo executivo ----
    e = resultado["economia"]
    fa, fo = resultado["frota_atual"], resultado["frota_otimizada"]
    nome = {t.id: t.nome for t in TIPOS_VEICULO}
    print("=" * 64)
    print("MOBGOV · Dimensionamento de Frota — Ribeirão Modelo")
    print("=" * 64)
    print(f"Demanda: {resultado['demanda']['alunos']} alunos "
          f"({resultado['demanda']['cadeirantes']} cadeirantes) em "
          f"{resultado['demanda']['pontos_embarque']} pontos, "
          f"{resultado['demanda']['escolas']} escolas")
    print(f"\nFROTA ATUAL:     {fa['total_veiculos']} veículos | "
          f"{fa['km_dia']:.0f} km/dia | R$ {fa['custo_mes']:,} /mês")
    for t, q in fa["composicao"].items():
        print(f"   - {q:2d}x {nome[t]}")
    print(f"\nFROTA NECESSÁRIA: {fo['total_veiculos']} veículos | "
          f"{fo['km_dia']:.0f} km/dia | R$ {fo['custo_mes']:,} /mês")
    for t, q in sorted(fo["composicao"].items()):
        print(f"   - {q:2d}x {nome[t]}")
    print("\n" + "-" * 64)
    print(f"ECONOMIA: {e['veiculos']} veículos a menos "
          f"(-{e['reducao_frota_pct']}%) | R$ {e['custo_mes']:,}/mês | "
          f"R$ {e['custo_ano']:,}/ano")
    print(f"          {e['km_dia']:.0f} km/dia | {e['litros_dia']:.0f} "
          f"litros/dia | {e['tco2_ano']} tCO2/ano evitadas")
    print("-" * 64)
    oc = sorted(todas_rotas, key=lambda r: -r["ocupacao_pct"])
    print(f"Ocupação média das rotas otimizadas: "
          f"{sum(r['ocupacao_pct'] for r in todas_rotas)//len(todas_rotas)}% "
          f"(máx {oc[0]['ocupacao_pct']}%, mín {oc[-1]['ocupacao_pct']}%)")
    print(f"Relatório completo: relatorios/dimensionamento.json")


if __name__ == "__main__":
    main()
