# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 15 · agent-saude
O que o paciente vê, e o que ele consegue fazer.

O transporte sanitário tem dois públicos que não escolheram usá-lo: o
paciente e a família dele. Para eles a régua não é eficiência, é confiança —
e confiança se ganha com três coisas, nesta ordem:

1. **não prometer o que não se sabe.** A previsão vem com selo: `medido`
   quando houve ping ou embarque hoje, `planejado` quando é só o horário do
   plano. Errar uma vez custa a confiança do ano;

2. **dar controle onde ele existe.** "Hoje eu não vou" é desfazível enquanto o
   veículo não passou. No escolar isso poupa km; aqui vale mais: a poltrona
   devolvida com antecedência pode ir para quem está na fila do TFD, e a fila
   do TFD é gente esperando meses por uma consulta;

3. **fechar o laço da volta.** Consulta e quimioterapia acabam quando o médico
   libera — o plano da manhã não tem essa hora, e por isso não a inventa. O
   botão "já fui liberado" é o que transforma essa volta em pedido de verdade
   para a reotimização. Sem ele, a alternativa real é o paciente ligar para a
   secretaria, ou esperar sentado até alguém lembrar dele.

Nada clínico entra aqui. O app mostra hora, veículo e destino; não mostra —
nem guarda — por que a pessoa está indo.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from operacao import registro  # noqa: E402
from saude import demanda as demanda_mod  # noqa: E402
from saude.tratamento import (  # noqa: E402
    PRIORIDADES, TIPOS_DE_TRATAMENTO, pedidos_do_dia,
)

# Depois disto o aviso de ausência não adianta mais: o veículo já saiu para
# buscar. Continua sendo registrado — vira falta, e a falta alimenta o
# aprendizado — mas a tela para de dizer que "libera a vaga", porque não
# libera.
ANTECEDENCIA_UTIL_MIN = 60


def _hhmm(minutos) -> str:
    if minutos is None:
        return "—"
    minutos = int(minutos) % (24 * 60)
    return f"{minutos // 60:02d}h{minutos % 60:02d}"


def _agora_min(agora: str = None) -> int:
    d = (datetime.strptime(agora, "%Y-%m-%dT%H:%M:%S") if agora
         else datetime.now())
    return d.hour * 60 + d.minute


def _eventos_de_hoje(paciente: str, dia: str, eventos: list) -> list:
    return [e for e in eventos
            if e.get("paciente") == paciente and (e.get("em") or "")[:10] == dia]


def situacao(paciente: str, dia_da_semana: int = None, dia: str = None,
             tratamentos: list = None, eventos: list = None,
             agora_min: int = None) -> dict:
    """O que o paciente precisa saber agora — e o que ele pode fazer.

    Devolve sempre a mesma forma, inclusive quando não há viagem hoje: "hoje
    você não tem transporte" é resposta, e é melhor do que uma tela vazia que
    faz a pessoa ligar para a secretaria para ter certeza.
    """
    dia = dia or datetime.now().strftime("%Y-%m-%d")
    if dia_da_semana is None:
        dia_da_semana = datetime.strptime(dia, "%Y-%m-%d").weekday()
    tratamentos = (tratamentos if tratamentos is not None
                   else demanda_mod.gerar_tratamentos())
    eventos = eventos if eventos is not None else registro.ler_eventos()
    agora = agora_min if agora_min is not None else _agora_min()

    meus = [t for t in tratamentos if t.paciente_id == paciente]
    if not meus:
        return {"paciente": paciente, "dia": dia, "tem_viagem": False,
                "mensagem": "Não encontramos transporte cadastrado para este "
                            "código. Procure a secretaria de saúde."}

    agenda = pedidos_do_dia(meus, dia_da_semana,
                            demanda_mod.unidades_por_id())
    nomes = demanda_mod.nomes_das_unidades()
    ida = agenda["ida"][0] if agenda["ida"] else None
    if not ida:
        return {"paciente": paciente, "dia": dia, "tem_viagem": False,
                "mensagem": _proxima_viagem(meus, dia_da_semana),
                "tratamentos": [_resumo_do_tratamento(t, nomes) for t in meus]}

    do_dia = _eventos_de_hoje(paciente, dia, eventos)
    tipos = [e.get("tipo") for e in do_dia]
    avisou_falta = "nao_vou" in tipos and tipos[::-1].index("nao_vou") < (
        tipos[::-1].index("confirmado") if "confirmado" in tipos else len(tipos))
    liberado = "liberado" in tipos

    tratamento = next(t for t in meus if t.id == ida.tratamento_id)
    saida_prevista = ida.janela_chegada[0]
    volta = (agenda["volta_planejada"] + agenda["volta_por_chamada"])
    volta = volta[0] if volta else None

    return {
        "paciente": paciente,
        "dia": dia,
        "tem_viagem": True,
        "tratamento": _resumo_do_tratamento(tratamento, nomes),
        "ida": {
            "unidade": nomes.get(ida.destino_id, ida.destino_id),
            "chegada_prevista": _hhmm(ida.janela_chegada[1]),
            "passa_por_voce": _hhmm(saida_prevista - 15),
            "selo": _selo(do_dia),
        },
        "volta": _volta(tratamento, volta, liberado),
        "avisou_que_nao_vai": avisou_falta,
        "pode_desfazer": avisou_falta and agora < saida_prevista,
        "aviso_ainda_libera_vaga": (saida_prevista - agora) >= ANTECEDENCIA_UTIL_MIN,
        "acoes": _acoes(tratamento, avisou_falta, liberado, agora,
                        saida_prevista),
        "prioridade": dict(PRIORIDADES[tratamento.prioridade],
                           id=tratamento.prioridade),
        "observacao_operacional": tratamento.observacao_operacional,
    }


def _resumo_do_tratamento(t, nomes) -> dict:
    regra = TIPOS_DE_TRATAMENTO.get(t.tipo, {})
    return {
        "id": t.id, "tipo": t.tipo, "nome": regra.get("nome", t.tipo),
        "unidade": nomes.get(t.unidade_id, t.unidade_id),
        "hora": _hhmm(t.hora_chegada_min),
        "dias": sorted(t.dias_da_semana),
        "cadeirante": t.cadeirante, "maca": t.maca,
        "acompanhante": t.acompanhante,
        "jejum": t.jejum,
    }


def _selo(eventos_de_hoje: list) -> dict:
    """Medido só quando houve sinal do veículo hoje. Nunca por otimismo."""
    if any(e.get("tipo") in ("ping", "embarque", "inicio")
           for e in eventos_de_hoje):
        return {"rotulo": "medido",
                "explicacao": "o veículo já mandou posição hoje"}
    return {"rotulo": "planejado",
            "explicacao": "é o horário do plano; o veículo ainda não "
                          "reportou posição hoje"}


def _volta(tratamento, pedido, liberado: bool) -> dict:
    if tratamento.retorno_previsivel:
        return {
            "tipo": "com_hora",
            "hora": _hhmm(pedido.janela_chegada[0]) if pedido else "—",
            "explicacao": "A sessão tem duração conhecida, então a volta já "
                          "está no plano do dia.",
        }
    return {
        "tipo": "por_chamada",
        "hora": None,
        "liberado": liberado,
        "explicacao": ("Avisamos o motorista. Aguarde no local combinado."
                       if liberado else
                       "A volta não tem hora marcada porque a consulta acaba "
                       "quando o médico liberar. Toque em “já fui liberado” "
                       "quando terminar — é isso que chama o carro."),
    }


def _acoes(tratamento, avisou_falta, liberado, agora, saida) -> list:
    """Só o que é verdade agora. Botão que não faz efeito engana."""
    acoes = []
    if avisou_falta:
        if agora < saida:
            acoes.append({"id": "desfazer", "rotulo": "Na verdade eu vou",
                          "estilo": "secundaria",
                          "explicacao": "Dá para voltar atrás enquanto o "
                                        "veículo não passou."})
    else:
        libera = (saida - agora) >= ANTECEDENCIA_UTIL_MIN
        acoes.append({
            "id": "nao_vou", "rotulo": "Hoje eu não vou", "estilo": "perigo",
            "explicacao": ("Avisando agora, a vaga pode ir para quem está na "
                           "fila." if libera else
                           "O veículo já está a caminho — avise mesmo assim, "
                           "para o motorista não esperar por você."),
        })
    # quem avisou que não vai não está no hospital: oferecer "já fui
    # liberado" aqui é oferecer um botão que produz uma corrida para buscar
    # ninguém
    if not avisou_falta and not tratamento.retorno_previsivel and not liberado:
        acoes.append({"id": "liberado", "rotulo": "Já fui liberado",
                      "estilo": "principal",
                      "explicacao": "Use quando o médico liberar. É o que "
                                    "coloca sua volta na fila do carro."})
    return acoes


def _proxima_viagem(tratamentos: list, dia_da_semana: int) -> str:
    nomes = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado",
             "domingo")
    proximos = []
    for t in tratamentos:
        for d in t.dias_da_semana:
            adiante = (d - dia_da_semana) % 7
            if adiante:
                proximos.append((adiante, d, t))
    if not proximos:
        return "Você não tem transporte marcado nos próximos dias."
    adiante, d, t = min(proximos)
    quando = "amanhã" if adiante == 1 else f"na {nomes[d]}"
    return (f"Hoje você não tem transporte. O próximo é {quando}, "
            f"às {_hhmm(t.hora_chegada_min)}.")


# ------------------------------------------------------- fila de retorno ---
def fila_de_retorno(dia: str = None, eventos: list = None,
                    tratamentos: list = None) -> dict:
    """Quem já foi liberado e está esperando o carro — a tela do despachante.

    É a contrapartida do botão do paciente: sem esta fila, o aviso não vira
    nada. Aqui ele vira ordem de serviço, com quanto tempo a pessoa está
    esperando.
    """
    dia = dia or datetime.now().strftime("%Y-%m-%d")
    eventos = eventos if eventos is not None else registro.ler_eventos()
    tratamentos = (tratamentos if tratamentos is not None
                   else demanda_mod.gerar_tratamentos())
    nomes = demanda_mod.nomes_das_unidades()
    por_paciente = {t.paciente_id: t for t in tratamentos}
    agora = _agora_min()

    esperando = []
    for e in eventos:
        if e.get("tipo") != "liberado" or (e.get("em") or "")[:10] != dia:
            continue
        t = por_paciente.get(e.get("paciente"))
        avisou = _minuto_do_evento(e)
        esperando.append({
            "paciente": e.get("paciente"),
            "unidade": nomes.get(t.unidade_id) if t else e.get("unidade"),
            "avisou_as": _hhmm(avisou),
            "esperando_ha_min": max(0, agora - avisou) if avisou is not None
            else None,
            "cadeirante": bool(t.cadeirante) if t else False,
            "maca": bool(t.maca) if t else False,
            "acompanhante": bool(t.acompanhante) if t else False,
            "prioridade": t.prioridade if t else "eletivo",
        })
    esperando.sort(key=lambda x: -(x["esperando_ha_min"] or 0))
    return {
        "dia": dia,
        "esperando": esperando,
        "resumo": {
            "pessoas": len(esperando),
            "espera_maxima_min": max((x["esperando_ha_min"] or 0
                                      for x in esperando), default=0),
            "com_cadeira": sum(1 for x in esperando if x["cadeirante"]),
            "com_maca": sum(1 for x in esperando if x["maca"]),
        },
    }


def _minuto_do_evento(evento: dict):
    try:
        d = datetime.strptime(evento["em"], "%Y-%m-%dT%H:%M:%S")
    except (KeyError, ValueError):
        return None
    return d.hour * 60 + d.minute
