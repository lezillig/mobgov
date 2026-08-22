# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 3 · agent-rotas (fase 2)
Escala multiviagem: encaixa as viagens de um turno em veículos físicos.

Fica separado de `dimensionar.py` de propósito. A fase 1 (roteirização)
depende do OR-Tools; esta fase é heurística pura, roda com a biblioteca
padrão e por isso pode ser testada — e explicada — isoladamente.
"""
from __future__ import annotations

from dados.municipio_modelo import ESCOLAS, matriz_tempo_dist

TEMPO_VIRADA_MIN = 5   # manobra/espera entre duas viagens do mesmo veículo


def matriz_entre_escolas(escolas=None):
    escolas = escolas or ESCOLAS
    locais = [(e.lat, e.lon) for e in escolas]
    dist, tempo = matriz_tempo_dist(locais)
    indice = {e.id: i for i, e in enumerate(escolas)}
    return dist, tempo, indice


def montar_jornadas(viagens, turno, tipos_por_id, jornada_max=None,
                    escolas=None, tempo_virada_min=TEMPO_VIRADA_MIN):
    """Encaixa as viagens de um turno em veículos físicos (multiviagem).

    Regras, na ordem em que um gestor as explicaria:
    - a viagem mais longa entra primeiro (as difíceis acham lugar antes);
    - ela vai para o veículo que ficar com MENOS folga, para fechar jornada;
    - o veículo precisa ter assentos e posições de cadeirante para a viagem;
    - entre duas viagens conta o deslocamento até a próxima escola mais o
      tempo de virada (manobra, espera do sinal);
    - se nenhum veículo comporta, abre-se um novo, do tipo mais barato que
      atenda àquela viagem.

    A heurística é determinística: mesma entrada, mesma escala — requisito
    para a demonstração ser reprodutível e auditável.
    """
    jornada_max = jornada_max or turno.jornada_max_min
    dist_e, tempo_e, idx_e = matriz_entre_escolas(escolas)
    veiculos = []

    def deslocamento(de_escola, para_escola):
        if de_escola is None:
            return 0, 0.0
        i, j = idx_e[de_escola], idx_e[para_escola]
        return tempo_e[i][j] + tempo_virada_min, dist_e[i][j]

    def comporta(tipo, viagem):
        return (tipo.capacidade >= viagem["alunos"]
                and tipo.posicoes_cadeirante >= viagem["cadeirantes"])

    for viagem in sorted(viagens, key=lambda v: (-v["min_viagem"], v["id"])):
        escolhido, menor_folga, escolhido_desloc = None, None, None
        for veic in veiculos:
            tipo = tipos_por_id[veic["tipo"]]
            if not comporta(tipo, viagem):
                continue
            min_desloc, km_desloc = deslocamento(veic["ultima_escola"],
                                                 viagem["escola_id"])
            usado = veic["min_turno"] + min_desloc + viagem["min_viagem"]
            if usado > jornada_max:
                continue
            folga = jornada_max - usado
            if menor_folga is None or folga < menor_folga:
                escolhido, menor_folga = veic, folga
                escolhido_desloc = (min_desloc, km_desloc)

        if escolhido is None:
            candidatos = [t for t in tipos_por_id.values() if comporta(t, viagem)]
            if not candidatos:
                raise RuntimeError(
                    f"Nenhum tipo de veículo atende à viagem {viagem['id']} "
                    f"({viagem['alunos']} alunos, "
                    f"{viagem['cadeirantes']} cadeirantes)")
            tipo = min(candidatos, key=lambda t: t.custo_fixo_mes)
            escolhido = {
                "id": f"V{turno.id[:1].upper()}{len(veiculos) + 1:02d}",
                "turno": turno.id, "turno_nome": turno.nome,
                "tipo": tipo.id, "tipo_nome": tipo.nome,
                "capacidade": tipo.capacidade,
                "viagens": [], "min_turno": 0, "km_turno": 0.0,
                "alunos": 0, "ultima_escola": None,
            }
            veiculos.append(escolhido)
            escolhido_desloc = (0, 0.0)

        min_desloc, km_desloc = escolhido_desloc
        escolhido["viagens"].append(viagem["id"])
        escolhido["min_turno"] += min_desloc + viagem["min_viagem"]
        escolhido["km_turno"] = round(
            escolhido["km_turno"] + km_desloc + viagem["km_viagem"], 1)
        escolhido["alunos"] += viagem["alunos"]
        escolhido["ultima_escola"] = viagem["escola_id"]
        viagem["veiculo"] = escolhido["id"]
        viagem["tipo"] = escolhido["tipo"]
        viagem["tipo_nome"] = escolhido["tipo_nome"]
        viagem["ocupacao_pct"] = round(
            100 * viagem["alunos"] / escolhido["capacidade"])

    for v in veiculos:
        v["ocupacao_media_pct"] = round(
            100 * v["alunos"] / (v["capacidade"] * len(v["viagens"])))
        v["folga_jornada_min"] = jornada_max - v["min_turno"]
    return veiculos


def compor_frota(veiculos_por_turno: dict) -> dict:
    """Frota necessária = pior caso de cada tipo entre os turnos.

    O mesmo veículo atende manhã e tarde, então as quantidades não se somam.
    Tomar o máximo por tipo é o lado seguro: garante cobrir os dois turnos.
    """
    composicao = {}
    for veiculos in veiculos_por_turno.values():
        do_turno = {}
        for v in veiculos:
            do_turno[v["tipo"]] = do_turno.get(v["tipo"], 0) + 1
        for tipo, qtd in do_turno.items():
            composicao[tipo] = max(composicao.get(tipo, 0), qtd)
    return composicao
