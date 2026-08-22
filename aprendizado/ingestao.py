# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-aprendizado
Converte o que o app do motorista mandou em observações de aprendizado.

É a peça que troca o simulador por dado real. O formato de saída é o mesmo
que `aprendizado/simulador.py` produz — de propósito: o ciclo de aprendizado
não muda uma linha quando a origem passa a ser GPS.

O que dá para medir com os eventos que os apps mandam:

- **duração real da coleta**: do primeiro ao último embarque de uma viagem,
  comparada com o previsto para o mesmo trecho;
- **tempo de parada por ponto**: o intervalo entre dois embarques menos o
  deslocamento previsto entre eles;
- **taxa de ausência**: dos avisos do app do responsável ("hoje ele(a) não
  vai"), por viagem e por dia. Era a última coisa do aprendizado que
  continuava estimada; agora tem origem, e quem informa é a própria família.

Vale o ÚLTIMO aviso de cada aluno no dia: quem avisou e depois desdisse não
faltou. Contar aviso desfeito como falta ensinaria ao modelo uma ausência que
não houve — e, no dia, faria o veículo passar direto pela criança que estava
no ponto.

Sem aviso nenhum a lista sai vazia: dia sem aviso não é dia sem falta, é dia
sem informação, e as duas coisas não podem virar o mesmo número.
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

    return {"trechos": trechos, "paradas": paradas,
            "faltas": faltas_observadas(eventos, plano)}


def faltas_observadas(eventos: list, plano: dict) -> list:
    """Taxa de ausência por viagem e por dia, a partir dos avisos da família."""
    viagens = {v["id"]: v for v in
               (plano.get("frota_otimizada") or {}).get("viagens", [])}

    # último aviso de cada aluno em cada dia — desdizer apaga o aviso anterior
    ultimo = {}
    for evento in sorted(eventos, key=lambda e: (e.get("em") or "")):
        if evento.get("tipo") not in ("falta", "volta_atras"):
            continue
        dia = _dia(evento.get("em"))
        if dia is None or not evento.get("aluno"):
            continue
        ultimo[(dia, evento["aluno"])] = evento

    por_viagem_dia = {}
    for (dia, _aluno), evento in ultimo.items():
        if evento["tipo"] != "falta":
            continue
        viagem_id = evento.get("viagem")
        if viagem_id not in viagens:
            continue
        por_viagem_dia[(viagem_id, dia)] = por_viagem_dia.get(
            (viagem_id, dia), 0) + 1

    faltas = []
    for (viagem_id, dia), quantas in sorted(por_viagem_dia.items()):
        previstos = viagens[viagem_id].get("alunos") or 0
        if previstos <= 0:
            continue
        faltas.append({
            "viagem": viagem_id, "dia": dia,
            "turno": viagens[viagem_id].get("turno"),
            "alunos_previstos": previstos,
            "faltas_avisadas": quantas,
            "taxa": round(quantas / previstos, 4),
            "origem": "aviso_do_responsavel",
        })
    return faltas


def taxa_de_ausencia(observadas: dict, minimo_de_dias: int = 5):
    """Taxa média — ou None enquanto não houver dias suficientes.

    Devolver None é o ponto: com dois dias de aviso, qualquer número seria
    ruído com cara de medição, e o modelo continua com a estimativa anterior.
    """
    faltas = observadas.get("faltas") or []
    dias = {f["dia"] for f in faltas}
    if len(dias) < minimo_de_dias:
        return None
    previstos = sum(f["alunos_previstos"] for f in faltas)
    avisadas = sum(f["faltas_avisadas"] for f in faltas)
    return round(avisadas / previstos, 4) if previstos else None


def suficiente(observadas: dict, minimo_de_trechos: int = 30) -> bool:
    """Tem dado que baste para trocar uma premissa por uma medição?

    Abaixo disso, o ciclo continua com o simulador e o painel segue dizendo
    "simulação" — porque quatro viagens observadas não viram evidência.
    """
    return len(observadas.get("trechos") or []) >= minimo_de_trechos
