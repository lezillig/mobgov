# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-apps
"Onde está o ônibus?" — respondido sem inventar.

Esta é a pergunta que a mãe faz às 6h10 na chuva, com a criança no portão. A
resposta errada custa caro dos dois lados: se o app promete "chega em 3
minutos" sem saber, a família perde a confiança na primeira vez; se não
responde nada, a família liga para a secretaria, e a secretaria vira central
telefônica.

Por isso a previsão aqui tem SEMPRE uma origem declarada:

    planejado  não chegou nenhum sinal do veículo hoje — é o horário do plano;
    medido     o veículo reportou posição ou embarque, e a conta parte dali.

O app mostra essa diferença na tela, com todas as letras. Prever com dado que
não existe é o tipo de mentira que derruba um piloto em duas semanas.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from operacao import registro, rota_do_dia as rotas

RAIO_TERRA_KM = 6371.0
VELOCIDADE_PADRAO_KMH = 28.0     # rural com paradas; só para a distância crua

# Divergência a partir da qual o sinal deixa de ser tratado como medição.
# Apareceu numa demonstração: um embarque com horário de outro turno virou
# "878 min atrasado" na tela da família, escrito com toda a confiança. Sinal
# assim é relógio errado no aparelho ou evento de outra viagem — e o certo é
# voltar para o horário do plano dizendo por quê, não fingir precisão.
DIVERGENCIA_MAXIMA_MIN = 120


def _minutos(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _hora(minuto) -> str:
    minuto = max(0, int(round(minuto))) % (24 * 60)
    return f"{minuto // 60:02d}h{minuto % 60:02d}"


def _minuto_do_evento(evento: dict):
    try:
        d = datetime.strptime(evento.get("em", ""), "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return d.hour * 60 + d.minute + d.second / 60.0


def _dia_do_evento(evento: dict):
    try:
        return datetime.strptime(evento.get("em", ""),
                                 "%Y-%m-%dT%H:%M:%S").date().isoformat()
    except (TypeError, ValueError):
        return None


def distancia_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(h))


def achar_viagem(plano: dict, ponto: str, turno: str = None) -> tuple:
    """(viagem, motorista) que atende aquele ponto — ou (None, None)."""
    frota = (plano or {}).get("frota_otimizada") or {}
    for viagem in frota.get("viagens", []):
        if ponto not in (viagem.get("paradas") or []):
            continue
        if turno and viagem.get("turno") != turno and \
                viagem.get("turno_nome") != turno:
            continue
        return viagem, viagem.get("veiculo")
    return None, None


def _paradas_da_viagem(plano: dict, motorista: str, viagem_id: str) -> list:
    rota = rotas.rota_do_dia(motorista, plano)
    for viagem in rota.get("viagens", []):
        if viagem["viagem"] == viagem_id:
            return viagem["paradas"], viagem
    return [], {}


def situacao(vinculo: dict, plano: dict, eventos: list = None,
             dia: str = None) -> dict:
    """O que a família vê: horário, previsão, posição e o estado do aviso.

    `vinculo`: {"aluno", "ponto", "turno"} — o que a secretaria entregou à
    família. Sem nome, sem endereço: o app mostra o que a família já sabe.
    """
    aluno, ponto = vinculo.get("aluno"), vinculo.get("ponto")
    eventos = eventos if eventos is not None else registro.ler_eventos()
    dia = dia or datetime.now().date().isoformat()
    do_dia = [e for e in eventos if _dia_do_evento(e) == dia]

    viagem, motorista = achar_viagem(plano, ponto, vinculo.get("turno"))
    if not viagem:
        return {"aluno": aluno, "ponto": ponto,
                "estado": "sem_rota",
                "mensagem": "Não encontrei rota para este ponto hoje. "
                            "Fale com a secretaria."}

    paradas, dados_viagem = _paradas_da_viagem(plano, motorista, viagem["id"])
    minha = next((p for p in paradas if p["ponto"] == ponto), None)
    indice = paradas.index(minha) if minha else 0
    prevista = _minutos(minha["hora_prevista"]) if minha else None
    por_parada = max(1, round(viagem["min_viagem"] / max(1, len(paradas))))

    # --- o que já aconteceu com este aluno hoje ------------------------------
    aviso = _ultimo_aviso(do_dia, aluno)
    embarcou = any(e.get("tipo") == "embarque" and e.get("ponto") == ponto
                   and e.get("viagem") == viagem["id"] for e in do_dia)

    # --- de onde vem a previsão ---------------------------------------------
    embarques = sorted(
        [e for e in do_dia if e.get("tipo") == "embarque"
         and e.get("viagem") == viagem["id"] and e.get("ponto") in
         [p["ponto"] for p in paradas]],
        key=lambda e: _minuto_do_evento(e) or 0)
    ping = _ultimo_ping(do_dia, motorista)

    origem, previsao, atraso = "planejado", prevista, 0
    if embarques:
        ultimo = embarques[-1]
        posicao_ultimo = [p["ponto"] for p in paradas].index(ultimo["ponto"])
        minuto_ultimo = _minuto_do_evento(ultimo)
        if posicao_ultimo < indice and minuto_ultimo is not None:
            origem = "medido"
            previsao = minuto_ultimo + por_parada * (indice - posicao_ultimo)
            atraso = round(previsao - prevista) if prevista is not None else 0
    elif ping and minha and minha.get("lat") is not None:
        minuto_ping = _minuto_do_evento(ping)
        if minuto_ping is not None:
            km = distancia_km((ping["lat"], ping["lon"]),
                              (minha["lat"], minha["lon"]))
            origem = "medido"
            previsao = minuto_ping + (km / VELOCIDADE_PADRAO_KMH) * 60
            atraso = round(previsao - prevista) if prevista is not None else 0

    sinal_inconsistente = (origem == "medido"
                           and abs(atraso) > DIVERGENCIA_MAXIMA_MIN)
    if sinal_inconsistente:
        origem, previsao, atraso = "planejado", prevista, 0

    if embarcou:
        estado, mensagem = "embarcou", "Embarcou. Boa aula!"
    elif aviso == "falta":
        estado = "falta_avisada"
        mensagem = ("Você avisou que hoje ele(a) não vai. O motorista já "
                    "recebeu — o veículo não vai parar no seu ponto.")
    elif origem == "medido":
        estado = "a_caminho"
        mensagem = (f"O veículo está a caminho. Previsão de passar no seu "
                    f"ponto: {_hora(previsao)}"
                    + (f" ({abs(atraso)} min "
                       f"{'atrasado' if atraso > 0 else 'adiantado'})"
                       if abs(atraso) >= 2 else " (no horário)") + ".")
    elif sinal_inconsistente:
        estado = "aguardando"
        mensagem = (f"Horário planejado no seu ponto: "
                    f"{minha['hora_prevista'] if minha else '—'}. O sinal que "
                    f"chegou do veículo tem horário muito diferente do plano, "
                    f"então prefiro não chutar uma previsão — a central já "
                    f"consegue ver isso.")
    else:
        estado = "aguardando"
        mensagem = (f"Horário planejado no seu ponto: "
                    f"{minha['hora_prevista'] if minha else '—'}. O veículo "
                    f"ainda não deu sinal hoje, então esta é a hora do plano, "
                    f"não uma medição.")

    return {
        "aluno": aluno,
        "ponto": ponto,
        "viagem": viagem["id"],
        "escola": viagem.get("escola"),
        "turno": viagem.get("turno_nome"),
        "motorista": motorista,
        "veiculo": viagem.get("tipo_nome"),
        "chegada_na_escola": dados_viagem.get("chegada_prevista"),
        "hora_planejada": minha["hora_prevista"] if minha else None,
        "previsao": _hora(previsao) if previsao is not None else None,
        "origem_da_previsao": origem,
        "atraso_min": atraso,
        "sinal_inconsistente": sinal_inconsistente,
        "estado": estado,
        "mensagem": mensagem,
        "paradas_antes_de_voce": indice,
        "posicao_do_veiculo": ({"lat": ping["lat"], "lon": ping["lon"],
                                "em": ping.get("em")}
                               if ping and ping.get("lat") is not None else None),
        "aviso_de_falta": aviso == "falta",
        "pode_avisar_falta": estado in ("aguardando", "a_caminho"),
        "paradas": [{"ponto": p["ponto"], "hora_prevista": p["hora_prevista"],
                     "lat": p["lat"], "lon": p["lon"],
                     "e_o_seu": p["ponto"] == ponto} for p in paradas],
    }


def _ultimo_aviso(eventos: list, aluno: str):
    """'falta', 'volta_atras' ou None — vale o último aviso do dia."""
    aviso = None
    for evento in sorted(eventos, key=lambda e: _minuto_do_evento(e) or 0):
        if evento.get("aluno") != aluno:
            continue
        if evento.get("tipo") in registro.TIPOS_DO_RESPONSAVEL:
            aviso = evento["tipo"]
    return aviso


def _ultimo_ping(eventos: list, motorista: str):
    pings = [e for e in eventos
             if e.get("tipo") == "ping" and e.get("motorista") == motorista
             and e.get("lat") is not None]
    return max(pings, key=lambda e: _minuto_do_evento(e) or 0) if pings else None


def avisar_falta(aluno: str, ponto: str, viagem: str = "", motivo: str = "",
                 arquivo: str = None) -> dict:
    return registro.registrar({"tipo": "falta", "aluno": aluno, "ponto": ponto,
                               "viagem": viagem, "motivo": motivo}, arquivo)


def desfazer_aviso(aluno: str, ponto: str, viagem: str = "",
                   arquivo: str = None) -> dict:
    return registro.registrar({"tipo": "volta_atras", "aluno": aluno,
                               "ponto": ponto, "viagem": viagem}, arquivo)


def faltas_do_dia(eventos: list = None, dia: str = None) -> dict:
    """Quem avisou falta hoje, por viagem — o que o motorista precisa saber.

    Conta o ÚLTIMO aviso de cada aluno: quem avisou e depois desdisse não é
    falta, e tratar como falta faria o veículo passar direto pela criança.
    """
    eventos = eventos if eventos is not None else registro.ler_eventos()
    dia = dia or datetime.now().date().isoformat()
    ultimo = {}
    for evento in sorted([e for e in eventos if _dia_do_evento(e) == dia],
                         key=lambda e: _minuto_do_evento(e) or 0):
        if evento.get("tipo") in registro.TIPOS_DO_RESPONSAVEL:
            ultimo[evento.get("aluno")] = evento
    por_viagem, desdiseram = {}, 0
    for aluno, evento in ultimo.items():
        if evento["tipo"] == "volta_atras":
            desdiseram += 1
            continue
        por_viagem.setdefault(evento.get("viagem") or "", []).append(
            {"aluno": aluno, "ponto": evento.get("ponto"),
             "avisado_em": evento.get("em")})
    return {"dia": dia, "faltas": sum(len(v) for v in por_viagem.values()),
            "avisos_desfeitos": desdiseram, "por_viagem": por_viagem}
