# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 4 · orquestrador do dia
Roda o porta a porta (PCD) e os eventos de reotimização do dia.

Produz dois relatórios que o painel lê se existirem:

    relatorios/porta_a_porta.json   rotas n:n, tempo a bordo, frota
    relatorios/reotimizacao.json    faltas, cancelamentos e pedidos novos

Separado do `dimensionar.py` de propósito: o dimensionamento de frota escolar
é planejamento (roda à noite, demora minutos); isto aqui é operação do dia
(roda em segundos, muitas vezes por dia).

Uso:
    python motor/rodar_dia.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import tempos as tempos_mod
from dados.demanda_pcd import (
    DESTINOS, FATOR_TEMPO_BORDO, FOLGA_TEMPO_BORDO_MIN, JANELA_EMBARQUE_MIN,
    PEDIDOS_POR_DIA, gerar_pedidos,
)
from dados.municipio_modelo import (
    ESCOLAS, TIPOS_VEICULO, gerar_pontos, tempo_parada_min,
)
from motor import porta_a_porta as pp
from motor import reotimizar as reo

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")

FILA_DE_ESPERA = 15          # pedidos que não entraram no planejamento da véspera
LIMITE_KM_POR_ENCAIXE = 15   # política: acima disso, viagem dedicada sai mais barato


def _gravar(nome: str, dados: dict):
    os.makedirs(DIR_RELATORIOS, exist_ok=True)
    caminho = os.path.join(DIR_RELATORIOS, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    return caminho


# ------------------------------------------------------------ porta a porta ---
def rodar_porta_a_porta(quantidade=PEDIDOS_POR_DIA, fila=FILA_DE_ESPERA,
                        tempo_limite_s=30):
    todos = gerar_pedidos(quantidade + fila)
    atendidos, espera = todos[:quantidade], todos[quantidade:]
    resultado = pp.resolver(atendidos, tempo_limite_s=tempo_limite_s)
    contexto = pp.contexto_reotimizacao(atendidos, espera)

    perfil = tempos_mod.provedor_padrao()
    resultado["gerado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    resultado["premissas"] = {
        "janela_embarque_min": JANELA_EMBARQUE_MIN,
        "fator_tempo_bordo": FATOR_TEMPO_BORDO,
        "folga_tempo_bordo_min": FOLGA_TEMPO_BORDO_MIN,
        "limite_km_por_encaixe": LIMITE_KM_POR_ENCAIXE,
        "destinos": [{"id": d.id, "nome": d.nome} for d in DESTINOS],
        "perfil_transito": getattr(perfil, "perfil", None).resumo()
        if hasattr(perfil, "perfil") else [],
        "transito_origem": getattr(perfil, "perfil", None).origem
        if hasattr(perfil, "perfil") else "sem trânsito",
    }
    resultado["fila_espera"] = [p.id for p in espera]
    return resultado, atendidos, espera, contexto


# --------------------------------------------------------- eventos do dia ---
def eventos_de_reotimizacao(pcd, atendidos, espera, contexto) -> dict:
    eventos = {"gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "escolar": [], "porta_a_porta": [], "pedidos_novos": []}

    # 1) falta informada no escolar — o caso mais comum do dia a dia
    caminho_escolar = os.path.join(DIR_RELATORIOS, "dimensionamento.json")
    if os.path.exists(caminho_escolar):
        with open(caminho_escolar, encoding="utf-8") as f:
            rel = json.load(f)
        pontos = {p.id: p for p in gerar_pontos()}
        tipos = {t.id: t for t in TIPOS_VEICULO}
        # duas viagens: uma com faltas pontuais, outra com um ponto inteiro vazio
        candidatas = sorted(rel["frota_otimizada"]["viagens"],
                            key=lambda v: -len(v["paradas"]))[:2]
        for i, viagem in enumerate(candidatas):
            escola = next(e for e in ESCOLAS if e.id == viagem["escola_id"])
            paradas = [{"id": pid, "lat": pontos[pid].lat, "lon": pontos[pid].lon,
                        "alunos": pontos[pid].alunos[viagem["turno"]],
                        "tempo_parada": tempo_parada_min(pontos[pid],
                                                         viagem["turno"])}
                       for pid in viagem["paradas"]]
            if i == 0:
                faltas = {paradas[0]["id"]: paradas[0]["alunos"],
                          paradas[2]["id"]: 2} if len(paradas) > 2 else {}
            else:
                faltas = {p["id"]: p["alunos"] for p in paradas[:3]}
            eventos["escolar"].append(reo.reotimizar_por_falta(
                viagem, paradas, faltas, (escola.lat, escola.lon), tipos,
                partida_min=6 * 60 + 10))

    # 2) cancelamento no porta a porta, com reinserção da fila
    fila_fmt = [dict({"usuario": p.id}, **contexto["indices"][p.id])
                for p in espera]
    for rota in pcd["rotas"][:2]:
        eventos_rota = pp.eventos_com_nos(rota, contexto)
        eventos["porta_a_porta"].append(reo.cancelar_e_reinserir(
            eventos_rota, contexto["coords"], eventos_rota[0]["usuario"],
            fila_fmt, contexto["pedidos_por_id"], rota["capacidade"],
            rota["posicoes_cadeirante"]))

    # 3) pedidos novos chegando durante o dia (inserção dinâmica)
    rotas_fmt = [{"id": r["id"], "eventos": pp.eventos_com_nos(r, contexto),
                  "capacidade": r["capacidade"],
                  "posicoes_cadeirante": r["posicoes_cadeirante"]}
                 for r in pcd["rotas"]]
    for p in espera[:6]:
        candidato = dict({"usuario": p.id}, **contexto["indices"][p.id])
        eventos["pedidos_novos"].append(reo.inserir_na_melhor_rota(
            rotas_fmt, contexto["coords"], candidato,
            contexto["pedidos_por_id"],
            limite_km_extra=LIMITE_KM_POR_ENCAIXE))

    tempos_resposta = [e["segundos"] for grupo in
                       (eventos["escolar"], eventos["porta_a_porta"],
                        eventos["pedidos_novos"]) for e in grupo]
    eventos["resumo"] = {
        "eventos": len(tempos_resposta),
        "tempo_max_s": max(tempos_resposta) if tempos_resposta else 0,
        "tempo_medio_s": round(sum(tempos_resposta) / len(tempos_resposta), 3)
        if tempos_resposta else 0,
        "km_economizados": round(
            sum(e["economia"]["km"] for e in eventos["escolar"])
            + sum(e["economia_km"] for e in eventos["porta_a_porta"]), 1),
        "pedidos_aceitos": sum(1 for e in eventos["pedidos_novos"] if e["aceito"]),
        "pedidos_avaliados": len(eventos["pedidos_novos"]),
    }
    return eventos


def main():
    print("Porta a porta (PDPTW)…", flush=True)
    pcd, atendidos, espera, contexto = rodar_porta_a_porta()
    ind = pcd["indicadores"]
    print(f"  {pcd['pedidos']} pedidos · {pcd['total_veiculos']} veículos · "
          f"{pcd['km_dia']} km/dia · {ind['usuarios_por_veiculo']} usuários por "
          f"veículo · tempo a bordo médio {ind['tempo_bordo_medio_min']} min "
          f"(máx {ind['tempo_bordo_max_min']}) · "
          f"{ind['dentro_do_limite_pct']}% dentro do limite")
    _gravar("porta_a_porta.json", pcd)

    print("Eventos do dia (faltas, cancelamentos, pedidos novos)…", flush=True)
    eventos = eventos_de_reotimizacao(pcd, atendidos, espera, contexto)
    r = eventos["resumo"]
    print(f"  {r['eventos']} eventos · resposta máxima {r['tempo_max_s']}s · "
          f"{r['km_economizados']} km economizados · "
          f"{r['pedidos_aceitos']}/{r['pedidos_avaliados']} pedidos novos aceitos")
    _gravar("reotimizacao.json", eventos)
    print("Relatórios: relatorios/porta_a_porta.json e relatorios/reotimizacao.json")


if __name__ == "__main__":
    main()
