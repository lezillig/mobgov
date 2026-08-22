# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-apps
Monta a rota do dia de um motorista a partir do plano.

O app do motorista não conversa com o otimizador: ele recebe uma lista de
viagens e paradas, na ordem, com horário previsto e o que fazer em cada
ponto. Traduzir o plano para essa forma é trabalho do servidor — o aparelho
tem que fazer o mínimo possível, porque vai rodar em Android velho, com
tela rachada e sem sinal.
"""
from __future__ import annotations

import json
import os

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")
PLANO = os.path.join(DIR_RELATORIOS, "dimensionamento.json")


def carregar_plano(caminho: str = None) -> dict:
    caminho = caminho or PLANO
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def motoristas(plano: dict = None) -> list:
    """Um motorista por veículo por turno — que é como a escala é feita."""
    plano = plano or carregar_plano()
    veiculos = (plano.get("frota_otimizada") or {}).get("veiculos") or []
    return [{"motorista": v["id"], "turno": v["turno_nome"],
             "veiculo": v["tipo_nome"], "viagens": len(v["viagens"])}
            for v in veiculos]


def rota_do_dia(motorista: str, plano: dict = None) -> dict:
    """Viagens, paradas e horários previstos do motorista."""
    plano = plano or carregar_plano()
    frota = plano.get("frota_otimizada") or {}
    veiculo = next((v for v in frota.get("veiculos", [])
                    if v["id"] == motorista), None)
    if not veiculo:
        return {}

    pontos = (plano.get("geografia") or {}).get("pontos") or {}
    por_id = {v["id"]: v for v in frota.get("viagens", [])}
    turnos = {t["id"]: t for t in (plano.get("demanda") or {}).get("turnos", [])}
    turno = turnos.get(veiculo["turno"], {})
    chegada = turno.get("jornada_max_min", 100)

    # o relógio corre de trás para frente: a última viagem tem que chegar na
    # escola na hora do sinal, então a primeira começa bem antes
    minuto = _minuto_do_sinal(veiculo["turno"]) - veiculo["min_turno"]
    viagens = []
    for viagem_id in veiculo["viagens"]:
        v = por_id.get(viagem_id)
        if not v:
            continue
        paradas = []
        for pid in v["paradas"]:
            coord = pontos.get(pid) or [None, None]
            paradas.append({"ponto": pid, "lat": coord[0], "lon": coord[1],
                            "hora_prevista": _hora(minuto)})
            minuto += max(1, round(v["min_viagem"] / max(1, len(v["paradas"]))))
        viagens.append({
            "viagem": v["id"], "escola": v["escola"], "turno": v["turno_nome"],
            "alunos": v["alunos"], "cadeirantes": v["cadeirantes"],
            "km": v["km_viagem"], "minutos": v["min_viagem"],
            "chegada_prevista": _hora(minuto),
            "paradas": paradas,
        })
        minuto += 5     # virada entre viagens

    return {
        "motorista": motorista,
        "veiculo": veiculo["tipo_nome"],
        "capacidade": veiculo["capacidade"],
        "turno": veiculo["turno_nome"],
        "jornada_prevista_min": veiculo["min_turno"],
        "jornada_limite_min": chegada,
        "viagens": viagens,
        "total_alunos": veiculo["alunos"],
    }


def _minuto_do_sinal(turno_id: str) -> int:
    return {"manha": 6 * 60 + 40, "tarde": 12 * 60 + 40}.get(turno_id, 7 * 60)


def _hora(minuto: int) -> str:
    minuto = max(0, int(minuto)) % (24 * 60)
    return f"{minuto // 60:02d}h{minuto % 60:02d}"
