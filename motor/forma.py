# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 16 · agent-rotas
Que formato tem esta demanda — e, portanto, qual motor resolve.

O sistema tem dois motores, e a escolha entre eles não é preferência de
implementação: é o formato do problema.

* **Coleta com destino único** (`motor/dimensionar.py`, CVRP). Muitos alunos,
  poucas escolas, todo mundo da viagem desce no mesmo portão. É o transporte
  escolar rural clássico: 40 alunos, 3 escolas.
* **Porta a porta multidestino** (`motor/porta_a_porta.py`, PDPTW). Cada aluno
  tem origem e destino próprios, e a mesma viagem passa por várias escolas.

O primeiro arquivo de cliente real mostrou por que isso precisa ser detectado
e não presumido: às 07:00 a operação leva **207 alunos a 83 escolas**, e cada
carro passa por 2,2 escolas em média — um deles, por sete. Rodar isso no motor
de destino único obrigaria uma viagem por escola e inventaria dezenas de
veículos que a operação não usa. O número sairia errado para cima, com toda a
aparência de rigor.

A regra é a razão entre passageiros e destinos no mesmo horário. Escola com
dois alunos não enche viagem nenhuma; ou o carro passa em várias escolas, ou
não existe operação possível.
"""
from __future__ import annotations

# Abaixo disto, uma viagem por destino desperdiça o veículo inteiro: com 3
# alunos por escola, um carro de 12 lugares sai com 75% de ar.
ALUNOS_POR_DESTINO_MINIMO = 4.0


def diagnosticar(alunos: list, chave_horario=None) -> dict:
    """Olha a demanda e diz qual motor ela pede.

    `alunos`: dicionários com pelo menos "escola" e "turno".
    `chave_horario`: função que devolve o horário de chegada do aluno, quando
    a planilha o tiver. Sem ela, o turno faz as vezes de horário — o que é
    conservador, porque agrupa demais e esconde a simultaneidade.
    """
    if not alunos:
        return {"motor": "indefinido", "blocos": [], "por_que": "sem demanda"}

    chave = chave_horario or (lambda a: a.get("turno") or "")
    blocos = {}
    for a in alunos:
        item = blocos.setdefault(chave(a), {"alunos": 0, "destinos": set()})
        item["alunos"] += 1
        if a.get("escola"):
            item["destinos"].add(str(a["escola"]).strip().upper())

    saida = []
    for nome, item in blocos.items():
        destinos = len(item["destinos"]) or 1
        saida.append({
            "horario": nome, "alunos": item["alunos"], "destinos": destinos,
            "alunos_por_destino": round(item["alunos"] / destinos, 1),
        })
    saida.sort(key=lambda b: -b["alunos"])

    # decide pelo bloco que manda na frota: o mais cheio
    maior = saida[0]
    multidestino = maior["alunos_por_destino"] < ALUNOS_POR_DESTINO_MINIMO
    return {
        "motor": "porta_a_porta" if multidestino else "coleta",
        "blocos": saida,
        "bloco_que_manda": maior,
        "por_que": _explicar(maior, multidestino),
    }


def _explicar(bloco, multidestino) -> str:
    if multidestino:
        return (
            f"No horário mais cheio ({bloco['horario']}) são {bloco['alunos']} "
            f"alunos para {bloco['destinos']} destinos — {bloco['alunos_por_destino']} "
            f"por destino. Uma viagem por escola sairia quase vazia, então o "
            f"carro precisa passar em mais de uma escola na mesma viagem. Isso "
            f"é porta a porta multidestino (PDPTW), não coleta.")
    return (
        f"No horário mais cheio ({bloco['horario']}) são {bloco['alunos']} "
        f"alunos para {bloco['destinos']} destinos — {bloco['alunos_por_destino']} "
        f"por destino. Dá para encher viagem com destino único, que é mais "
        f"rápido de resolver e mais simples de operar.")


def aviso(diagnostico: dict, motor_em_uso: str) -> str:
    """Frase para o relatório quando o motor escolhido não é o indicado.

    Vazia quando está tudo certo: aviso que aparece sempre ninguém lê.
    """
    if diagnostico.get("motor") in ("indefinido", motor_em_uso):
        return ""
    if diagnostico["motor"] == "porta_a_porta":
        return ("Esta demanda foi roteirizada como coleta (uma escola por "
                "viagem), mas tem cara de porta a porta: "
                + diagnostico["por_que"]
                + " O número de veículos deste plano é, portanto, um teto — a "
                  "operação real consegue menos.")
    return ("Esta demanda foi roteirizada como porta a porta, mas tem "
            "concentração suficiente para coleta com destino único: "
            + diagnostico["por_que"])
