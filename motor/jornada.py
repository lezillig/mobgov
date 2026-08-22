# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 9 · agent-rotas (fase 3)
Escala de MOTORISTAS: quantos a operação exige, e quem faz o quê.

No escolar dá para viver sem isto: dois turnos, o mesmo motorista de manhã e
de tarde, e a prefeitura contrata "veículo com motorista". No fretamento, não:
o veículo roda os três turnos, o motorista não pode, e é o número de
motoristas que decide o preço da proposta. Dimensionar frota sem dimensionar
equipe é entregar meia conta — e a metade que falta é a mais cara.

O que este módulo faz: pega os blocos de trabalho que a fase 2 produziu (um
veículo, num turno, do minuto X ao minuto Y) e encaixa em motoristas
respeitando as regras declaradas no perfil (`RegrasDeJornada`):

    jornada normal + extra    quanto tempo à disposição no dia
    direção contínua          5h30 ao volante pedem 30 min de parada
    intervalo de refeição     jornada acima de 6h
    interjornada              11h entre a última hora de um dia e a primeira
                              do seguinte — é o que impede o mesmo motorista
                              de fechar o 3º turno e abrir o 1º
    amplitude                 da primeira à última hora do dia
    dupla pegada              pega cedo, larga, volta à tarde (comum e legal
                              sob acordo; desligável no perfil)

Os valores vêm do perfil, com padrão na Lei 13.103/2015, e vão para o
relatório. Acordo coletivo muda quase todos — o sistema não decide isso, ele
escancara o que usou.

A heurística é a mesma família da fase 2 (maior primeiro, no motorista com
menos folga), determinística e explicável escala por escala.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados.perfis import RegrasDeJornada  # noqa: E402

MINUTOS_DO_DIA = 24 * 60


def _hora(minuto) -> str:
    minuto = int(round(minuto))
    return f"{(minuto // 60) % 24:02d}h{minuto % 60:02d}"


def blocos_de_trabalho(veiculos_por_turno: dict, turnos, viagens=None,
                       tempo_antes_min: int = 30) -> list:
    """Converte a escala de veículos em blocos com hora de início e fim.

    A fase 2 devolve "este veículo trabalha 96 minutos neste turno". Para
    escalar gente é preciso saber QUANDO: o bloco termina na janela de chegada
    do turno (é para isso que a viagem existe) e começa a jornada antes dela.

    E não é só a coleta. Quem foi levado às 6h volta às 14h, e alguém dirige
    essa dispersão — contar só a ida daria uma equipe menor do que a operação
    exige, que é justamente o erro que encarece a proposta depois. Quando o
    turno declara `duracao_min`, cada bloco de coleta ganha o par dele na
    dispersão.

    A dispersão do 3º turno cai na madrugada do dia seguinte; como a operação
    se repete todo dia, ela é tratada no mesmo relógio cíclico de 24 h — é o
    que acontece na prática: todo dia, às 6h, alguém dirige aquela volta.
    """
    por_turno = {t.id: t for t in turnos}
    blocos = []
    for turno_id, veiculos in veiculos_por_turno.items():
        turno = por_turno.get(turno_id)
        if turno is None:
            continue
        chegada = turno.janela_chegada[0]
        for veiculo in veiculos:
            duracao = int(veiculo.get("min_turno") or 0)
            if duracao <= 0:
                continue
            fim = chegada
            inicio = fim - duracao - tempo_antes_min
            blocos.append({
                "id": f"{veiculo['id']}@{turno_id}",
                "veiculo": veiculo["id"], "tipo": veiculo.get("tipo"),
                "turno": turno_id, "turno_nome": turno.nome,
                "sentido": "coleta",
                "inicio": inicio, "fim": fim, "duracao": fim - inicio,
                "km": veiculo.get("km_turno", 0.0),
                "viagens": list(veiculo.get("viagens") or []),
            })
            duracao_turno = getattr(turno, "duracao_min", 0)
            if duracao_turno:
                saida = (chegada + duracao_turno) % MINUTOS_DO_DIA
                # a volta dura o mesmo que a ida: é o mesmo percurso ao
                # contrário. Na ida o tempo extra é sair da garagem antes; na
                # volta é voltar para ela depois do último desembarque
                volta_duracao = fim - inicio
                blocos.append({
                    "id": f"{veiculo['id']}@{turno_id}-volta",
                    "veiculo": veiculo["id"], "tipo": veiculo.get("tipo"),
                    "turno": turno_id, "turno_nome": f"{turno.nome} (volta)",
                    "sentido": "dispersao",
                    "inicio": saida, "fim": saida + volta_duracao,
                    "duracao": volta_duracao,
                    "km": veiculo.get("km_turno", 0.0),
                    "viagens": list(veiculo.get("viagens") or []),
                })
    return sorted(blocos, key=lambda b: (b["inicio"], b["id"]))


# --------------------------------------------------------------- validação ---
def conferir(blocos: list, regras: RegrasDeJornada) -> list:
    """Problemas de uma escala de um motorista. Lista vazia = escala legal."""
    if not blocos:
        return []
    ordenados = sorted(blocos, key=lambda b: b["inicio"])
    problemas = []

    amplitude = ordenados[-1]["fim"] - ordenados[0]["inicio"]
    if amplitude > regras.amplitude_max_min:
        problemas.append(
            f"Amplitude de {amplitude // 60}h{amplitude % 60:02d} entre a "
            f"primeira e a última hora, acima do limite de "
            f"{regras.amplitude_max_min // 60}h.")

    trabalho = sum(b["duracao"] for b in ordenados)
    # intervalo curto entre dois blocos continua sendo tempo à disposição
    for anterior, seguinte in zip(ordenados, ordenados[1:]):
        vao = seguinte["inicio"] - anterior["fim"]
        if vao < 0:
            problemas.append(
                f"Os blocos {anterior['id']} e {seguinte['id']} se sobrepõem.")
        elif vao < regras.tempo_troca_veiculo_min:
            problemas.append(
                f"Só {vao} min entre {anterior['id']} e {seguinte['id']}: o "
                f"motorista precisa de {regras.tempo_troca_veiculo_min} min "
                f"para trocar de veículo.")
        elif vao < regras.intervalo_refeicao_min:
            trabalho += vao

    limite = regras.jornada_normal_min + regras.hora_extra_max_min
    if trabalho > limite:
        problemas.append(
            f"Jornada de {trabalho // 60}h{trabalho % 60:02d}, acima de "
            f"{limite // 60}h (normal + extra).")

    if trabalho > 360 and len(ordenados) == 1:
        problemas.append(
            f"Jornada de {trabalho // 60}h{trabalho % 60:02d} em bloco único, "
            f"sem intervalo de refeição de {regras.intervalo_refeicao_min} min.")

    # direção contínua: um vão de 30 min ou mais zera o relógio do volante
    ao_volante = 0
    for i, bloco in enumerate(ordenados):
        if i > 0:
            vao = bloco["inicio"] - ordenados[i - 1]["fim"]
            if vao >= regras.parada_obrigatoria_min:
                ao_volante = 0
        ao_volante += bloco["duracao"]
        if ao_volante > regras.direcao_continua_max_min:
            problemas.append(
                f"{ao_volante // 60}h{ao_volante % 60:02d} de direção sem a "
                f"parada de {regras.parada_obrigatoria_min} min exigida a cada "
                f"{regras.direcao_continua_max_min // 60}h"
                f"{regras.direcao_continua_max_min % 60:02d}.")
            break

    if not regras.permite_dupla_pegada and len(ordenados) > 1:
        for anterior, seguinte in zip(ordenados, ordenados[1:]):
            if seguinte["inicio"] - anterior["fim"] >= regras.intervalo_refeicao_min:
                problemas.append(
                    "Escala em dois períodos (dupla pegada), que este perfil "
                    "não permite.")
                break
    return problemas


def _cabe(motorista: dict, bloco: dict, regras: RegrasDeJornada) -> bool:
    return not conferir(motorista["blocos"] + [bloco], regras)


def _interjornada_ok(motorista: dict, bloco: dict, regras: RegrasDeJornada) -> bool:
    """O mesmo motorista não fecha o 3º turno e abre o 1º do dia seguinte.

    A operação é cíclica: o que termina às 23h volta amanhã às 4h30, e entre
    as duas pontas precisa haver 11 horas. Comparar dentro de um dia só
    esconderia justamente o pior caso do fretamento industrial.
    """
    if not motorista["blocos"]:
        return True
    inicio_do_dia = min(b["inicio"] for b in motorista["blocos"] + [bloco])
    fim_do_dia = max(b["fim"] for b in motorista["blocos"] + [bloco])
    descanso = MINUTOS_DO_DIA - (fim_do_dia - inicio_do_dia)
    return descanso >= regras.interjornada_min


def escalar(blocos: list, regras: RegrasDeJornada = None,
            prefixo: str = "M") -> dict:
    """Encaixa os blocos em motoristas. Devolve escala + indicadores.

    Mesma lógica da escala de veículos: o bloco mais longo entra primeiro, no
    motorista que ficar com menos folga — assim as jornadas fecham cheias em
    vez de sobrar meia dúzia de motoristas com duas horas cada.
    """
    regras = regras or RegrasDeJornada()
    motoristas = []
    for bloco in sorted(blocos, key=lambda b: (-b["duracao"], b["inicio"])):
        escolhido, menor_folga = None, None
        for motorista in motoristas:
            if not _interjornada_ok(motorista, bloco, regras):
                continue
            if not _cabe(motorista, bloco, regras):
                continue
            usado = sum(b["duracao"] for b in motorista["blocos"]) + bloco["duracao"]
            folga = regras.jornada_normal_min + regras.hora_extra_max_min - usado
            if menor_folga is None or folga < menor_folga:
                escolhido, menor_folga = motorista, folga
        if escolhido is None:
            escolhido = {"id": f"{prefixo}{len(motoristas) + 1:02d}",
                         "blocos": []}
            motoristas.append(escolhido)
        escolhido["blocos"].append(bloco)

    for motorista in motoristas:
        motorista["blocos"].sort(key=lambda b: b["inicio"])
        primeiro, ultimo = motorista["blocos"][0], motorista["blocos"][-1]
        trabalho = sum(b["duracao"] for b in motorista["blocos"])
        motorista.update({
            "turnos": sorted({b["turno"] for b in motorista["blocos"]}),
            "veiculos": sorted({b["veiculo"] for b in motorista["blocos"]}),
            "inicio": _hora(primeiro["inicio"]), "fim": _hora(ultimo["fim"]),
            "jornada_min": trabalho,
            "amplitude_min": ultimo["fim"] - primeiro["inicio"],
            "dupla_pegada": len(motorista["blocos"]) > 1 and any(
                b2["inicio"] - b1["fim"] >= regras.intervalo_refeicao_min
                for b1, b2 in zip(motorista["blocos"], motorista["blocos"][1:])),
            "hora_extra_min": max(0, trabalho - regras.jornada_normal_min),
            "km": round(sum(b["km"] for b in motorista["blocos"]), 1),
            "problemas": conferir(motorista["blocos"], regras),
        })

    total = len(motoristas)
    jornada_media = (sum(m["jornada_min"] for m in motoristas) / total
                     if total else 0)
    por_turno = {}
    for motorista in motoristas:
        for turno in motorista["turnos"]:
            por_turno[turno] = por_turno.get(turno, 0) + 1
    return {
        "motoristas": motoristas,
        "regras": regras.como_dicionario(),
        "resumo": {
            "motoristas": total,
            "blocos": len(blocos),
            "jornada_media_min": round(jornada_media, 1),
            "jornada_maxima_min": max((m["jornada_min"] for m in motoristas),
                                      default=0),
            "com_hora_extra": sum(1 for m in motoristas
                                  if m["hora_extra_min"] > 0),
            "hora_extra_total_min": sum(m["hora_extra_min"] for m in motoristas),
            "com_dupla_pegada": sum(1 for m in motoristas if m["dupla_pegada"]),
            "escalas_com_problema": sum(1 for m in motoristas
                                        if m["problemas"]),
            "por_turno": por_turno,
            "ocupacao_da_jornada_pct": round(
                100 * jornada_media / regras.jornada_normal_min, 1)
            if total else 0.0,
        },
    }


def escalar_operacao(veiculos_por_turno: dict, turnos, regras=None,
                     tempo_antes_min: int = 30) -> dict:
    """Atalho: da escala de veículos direto para a escala de motoristas."""
    blocos = blocos_de_trabalho(veiculos_por_turno, turnos,
                                tempo_antes_min=tempo_antes_min)
    resultado = escalar(blocos, regras)
    resultado["blocos"] = blocos
    return resultado


def explicar(escala: dict, quantos: int = 5) -> list:
    """Linhas em português para a tela e para o relatório."""
    linhas = []
    for motorista in escala["motoristas"][:quantos]:
        turnos = ", ".join(motorista["turnos"])
        extra = (f" · {motorista['hora_extra_min']} min de hora extra"
                 if motorista["hora_extra_min"] else "")
        pegada = " · dupla pegada" if motorista["dupla_pegada"] else ""
        linhas.append(
            f"{motorista['id']}: {motorista['inicio']}–{motorista['fim']} "
            f"({motorista['jornada_min'] // 60}h"
            f"{motorista['jornada_min'] % 60:02d} de jornada) · turnos "
            f"{turnos} · veículos {', '.join(motorista['veiculos'])}"
            f"{extra}{pegada}")
    return linhas
