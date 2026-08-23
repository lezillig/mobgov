# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 12 · agent-fiscalizacao
Um mês de operação como ele é: imperfeito, com sinal ruim e dia atípico.

A fiscalização precisa de execução para medir, e o Município Modelo é
sintético. Este módulo produz os eventos que o app do motorista mandaria
durante um mês, a partir do plano publicado — e o relatório sai marcado como
`origem: "simulacao"`, com selo, em toda tela que o mostrar.

O que a simulação NÃO faz é gerar um mês perfeito. Um mês perfeito não testa
nada: a fiscalização existe justamente para o dia em que o ônibus não saiu, o
motorista esqueceu o celular e a viagem chegou 40 minutos atrasada. Por isso
a imperfeição é declarada aqui, com número, e é ela que exercita cada
caminho da medição:

    aparelho sem envio      viagem inteira sem evento  -> sem_evidencia
    veículo quebrado        imprevisto cancelando       -> nao_realizada
    rota encurtada          parte das paradas           -> parcial
    trânsito                chegada depois do horário   -> atrasada

A semente é fixa: o mesmo mês sai igual toda vez, e a demonstração não muda
de número entre uma reunião e outra.
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiscalizacao import medicao  # noqa: E402

SEMENTE = 42

# Como a operação real erra, em fração das viagens do dia. Os valores são
# plausíveis para transporte escolar municipal e estão aqui, à vista, porque
# quem apresenta a demonstração precisa poder dizer de onde saíram.
SEM_ENVIO = 0.08            # aparelho descarregado, sem sinal, app fechado
CANCELADA = 0.015           # veículo quebrado, estrada interditada
ENCURTADA = 0.03            # não passou em parte das paradas
ATRASO_MEDIO_MIN = 6
ATRASO_DESVIO_MIN = 9

MOTIVOS_CANCELAMENTO = [
    "veículo quebrou a caminho da primeira parada",
    "estrada interditada por causa da chuva",
    "motorista faltou e não houve substituto",
]


def _dias_uteis(inicio: date, quantidade: int) -> list:
    dias, atual = [], inicio
    while len(dias) < quantidade:
        if atual.weekday() < 5:
            dias.append(atual.isoformat())
        atual += timedelta(days=1)
    return dias


def _pings(coords: list, veiculo: str, dia: str, minuto_inicial: int,
           passo_min: int = 2) -> list:
    eventos = []
    for i, (lat, lon) in enumerate(coords):
        minuto = minuto_inicial + i * passo_min
        eventos.append({
            "tipo": "ping", "motorista": veiculo,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "em": f"{dia}T{minuto // 60:02d}:{minuto % 60:02d}:00",
        })
    return eventos


def simular_mes(plano: dict, inicio: str = None, dias: int = 22,
                semente: int = SEMENTE) -> dict:
    """Gera os eventos de um mês e devolve também a lista de dias medidos."""
    rng = random.Random(semente)
    viagens = (plano.get("frota_otimizada") or {}).get("viagens") or []
    pontos = (plano.get("geografia") or {}).get("pontos") or {}
    escolas = {e["id"]: (e["lat"], e["lon"])
               for e in (plano.get("geografia") or {}).get("escolas", [])}

    primeiro = date.fromisoformat(inicio) if inicio else date(2026, 8, 3)
    calendario = _dias_uteis(primeiro, dias)

    # O relógio das viagens sai da MESMA agenda que a fiscalização usa para
    # medir atraso. Se o simulador inventasse horários próprios, a medição
    # estaria conferindo a si mesma.
    agenda = medicao.horarios_planejados(plano)

    eventos = []
    for dia in calendario:
        for viagem in viagens:
            eventos.extend(_simular_viagem(viagem, dia, pontos, escolas, rng,
                                           agenda.get(viagem["id"])))
    eventos.sort(key=lambda e: e["em"])
    return {
        "origem": "simulacao",
        "explicacao_selo": "mês de operação gerado a partir do plano — "
                           "nenhum veículo real, nenhuma pessoa real",
        "dias": calendario,
        "eventos": eventos,
        "premissas": {
            "sem_envio_pct": round(SEM_ENVIO * 100, 1),
            "cancelada_pct": round(CANCELADA * 100, 1),
            "encurtada_pct": round(ENCURTADA * 100, 1),
            "atraso_medio_min": ATRASO_MEDIO_MIN,
            "semente": semente,
        },
    }


def _simular_viagem(viagem, dia, pontos, escolas, rng, horario=None) -> list:
    veiculo = viagem.get("veiculo")
    paradas = [p for p in (viagem.get("paradas") or []) if p in pontos]
    if not veiculo or not paradas:
        return []

    # aparelho que não enviou nada: é o caso que a fiscalização precisa tratar
    # como decisão humana, e não como falta comprovada
    if rng.random() < SEM_ENVIO:
        return []

    saida = _minuto_de_saida(viagem, horario)

    if rng.random() < CANCELADA:
        return [{
            "tipo": "imprevisto", "motorista": veiculo, "viagem": viagem["id"],
            "cancelou_viagem": True,
            "motivo": rng.choice(MOTIVOS_CANCELAMENTO),
            "em": f"{dia}T{saida // 60:02d}:{saida % 60:02d}:00",
        }]

    atendidas = paradas
    if rng.random() < ENCURTADA and len(paradas) > 2:
        atendidas = paradas[:max(1, len(paradas) // 2)]

    eventos = [{
        "tipo": "inicio", "motorista": veiculo, "viagem": viagem["id"],
        "em": f"{dia}T{saida // 60:02d}:{saida % 60:02d}:00",
    }]
    for i, parada in enumerate(atendidas):
        minuto = saida + int((i + 1) * _passo(viagem, len(atendidas)))
        eventos.append({
            "tipo": "embarque", "motorista": veiculo, "viagem": viagem["id"],
            "ponto": parada,
            "em": f"{dia}T{minuto // 60:02d}:{minuto % 60:02d}:00",
        })
    eventos.extend(_pings([tuple(pontos[p]) for p in atendidas],
                          veiculo, dia, saida + 1))

    atraso = max(0, int(rng.gauss(ATRASO_MEDIO_MIN, ATRASO_DESVIO_MIN)))
    chegada = saida + (viagem.get("min_viagem") or 30) + atraso
    destino = escolas.get(viagem.get("escola_id"))
    if destino:
        eventos.extend(_pings([destino], veiculo, dia, chegada))
    eventos.append({
        "tipo": "fim", "motorista": veiculo, "viagem": viagem["id"],
        "em": f"{dia}T{chegada // 60:02d}:{chegada % 60:02d}:00",
    })
    # atendidas < paradas é o que a medição vai enxergar como viagem parcial
    return eventos


def _passo(viagem, quantas) -> float:
    return max(1.0, (viagem.get("min_viagem") or 30) / max(quantas, 1))


def _minuto_de_saida(viagem, horario=None) -> int:
    if horario and horario.get("saida_min") is not None:
        return max(0, horario["saida_min"])
    # sem agenda, usa o turno: manhã sai às 6h, tarde às 12h
    return 6 * 60 if str(viagem.get("turno", "")).startswith("manha") else 12 * 60
