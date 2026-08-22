# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-aprendizado
Converte o que o app do motorista mandou em observações de aprendizado.

É a peça que troca o simulador por dado real. O formato de saída é o mesmo
que `aprendizado/simulador.py` produz — de propósito: o ciclo de aprendizado
não muda uma linha quando a origem passa a ser GPS.

O que dá para medir com os eventos que o app manda hoje:

- **duração real da coleta**: do primeiro ao último embarque de uma viagem,
  comparada com o previsto para o mesmo trecho;
- **tempo de parada por ponto**: o intervalo entre dois embarques menos o
  deslocamento previsto entre eles.

O que NÃO dá, e por isso não é inventado aqui: a taxa de ausência. Ela vem do
app do responsável ("meu filho não vai hoje"), que ainda não existe. Enquanto
não existir, o modelo mantém a estimativa anterior — melhor do que fabricar
uma medição.
"""
from __future__ import annotations

from datetime import datetime

MINIMO_DE_EMBARQUES = 3   # com menos de 3 paradas, a conta não diz nada


def _minuto(texto: str):
    try:
        d = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return d.hour * 60 + d.minute + d.second / 60.0


def _dia(texto: str):
    try:
        return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S").date().isoformat()
    except (TypeError, ValueError):
        return None


def observacoes(eventos: list, plano: dict, faixa_por_turno: dict,
                zona_por_viagem: dict, fator_plano=None) -> dict:
    """Traduz eventos de operação em trechos e paradas observados."""
    viagens = {v["id"]: v for v in
               (plano.get("frota_otimizada") or {}).get("viagens", [])}
    if fator_plano is None:
        from aprendizado.aprender import FATORES_INICIAIS

        def fator_plano(faixa, zona):
            return FATORES_INICIAIS.get(faixa, {}).get(zona, 1.0)

    # agrupa embarques por (viagem, dia), na ordem em que aconteceram
    por_viagem_dia = {}
    for e in eventos:
        if e.get("tipo") != "embarque" or not e.get("viagem"):
            continue
        minuto, dia = _minuto(e.get("em")), _dia(e.get("em"))
        if minuto is None:
            continue
        por_viagem_dia.setdefault((e["viagem"], dia), []).append(
            (minuto, e.get("ponto")))

    trechos, paradas = [], []
    for (viagem_id, dia), marcas in por_viagem_dia.items():
        viagem = viagens.get(viagem_id)
        if not viagem or len(marcas) < MINIMO_DE_EMBARQUES:
            continue
        marcas.sort()
        faixa = faixa_por_turno.get(viagem["turno"], "pico_manha")
        zona = zona_por_viagem.get(viagem_id, "rural")

        # o previsto para o mesmo pedaço: do primeiro ao último embarque, ou
        # seja, (n-1)/n do tempo total da viagem
        n = max(1, len(viagem.get("paradas") or [1]))
        previsto = viagem["min_viagem"] * (len(marcas) - 1) / n
        realizado = marcas[-1][0] - marcas[0][0]
        if previsto <= 0 or realizado <= 0:
            continue

        trechos.append({
            "viagem": viagem_id, "dia": dia, "faixa": faixa, "zona": zona,
            "chuva": False,             # clima entra quando houver API ligada
            "min_estimado": round(previsto, 1),
            "fator_plano": round(fator_plano(faixa, zona), 4),
            "min_realizado": round(realizado, 1),
        })

        # tempo de parada: intervalo real menos o deslocamento previsto
        deslocamento_previsto = viagem["min_viagem"] / n
        for (minuto_a, _), (minuto_b, ponto_b) in zip(marcas, marcas[1:]):
            extra = (minuto_b - minuto_a) - deslocamento_previsto
            if ponto_b:
                paradas.append({"ponto": ponto_b, "dia": dia,
                                "min_extra_realizado": round(max(0.0, extra), 2)})

    return {"trechos": trechos, "paradas": paradas, "faltas": []}


def suficiente(observadas: dict, minimo_de_trechos: int = 30) -> bool:
    """Tem dado que baste para trocar uma premissa por uma medição?

    Abaixo disso, o ciclo continua com o simulador e o painel segue dizendo
    "simulação" — porque quatro viagens observadas não viram evidência.
    """
    return len(observadas.get("trechos") or []) >= minimo_de_trechos
