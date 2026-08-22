# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-reotimizacao
Roda o dia inteiro em rodadas e grava relatorios/rodadas.json.

O exercício é honesto no ponto que costuma ser maquiado: cada informação
entra na rodada em que ela CHEGARIA — a mãe avisa a falta às 6h20, o pedido
novo entra às 7h05 — e o sistema só decide com o que já sabe naquele minuto.
Reotimizar sabendo o dia inteiro de antemão é fácil e não é a realidade.

Uso:
    python motor/rodar_rodadas.py
    python motor/rodar_rodadas.py --intervalo 10 --horizonte 30
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import tempos as tempos_mod
from dados.demanda_pcd import PEDIDOS_POR_DIA, gerar_pedidos
from motor import porta_a_porta as pp
from motor import rodadas as rod

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")

INICIO_MIN = 6 * 60
FIM_MIN = 9 * 60
FILA = 8


def montar_dia(quantidade=PEDIDOS_POR_DIA, fila=FILA, tempo_limite_s=20,
               semente=2026):
    """Planeja a véspera e monta a agenda de acontecimentos do dia."""
    todos = gerar_pedidos(quantidade + fila)
    planejados, novos = todos[:quantidade], todos[quantidade:]
    plano = pp.resolver(planejados, tempo_limite_s=tempo_limite_s)
    contexto = pp.contexto_reotimizacao(planejados, novos)

    rotas = [{"id": r["id"], "eventos": pp.eventos_com_nos(r, contexto),
              "capacidade": r["capacidade"],
              "posicoes_cadeirante": r["posicoes_cadeirante"],
              "inicio_min": None}
             for r in plano["rotas"]]

    rng = random.Random(semente)
    agenda = []
    # faltas informadas ao longo da manhã, sempre antes do embarque
    usuarios = [ev["usuario"] for r in rotas for ev in r["eventos"]
                if ev["tipo"] == "embarque"]
    for usuario in rng.sample(usuarios, min(6, len(usuarios))):
        agenda.append((INICIO_MIN + rng.randrange(0, 90),
                       {"tipo": "falta", "usuario": usuario}))
    # pedidos novos chegando durante a manhã
    for p in novos:
        agenda.append((INICIO_MIN + rng.randrange(5, 100),
                       {"tipo": "pedido",
                        "candidato": dict({"usuario": p.id},
                                          **contexto["indices"][p.id])}))
    return plano, rotas, contexto, sorted(agenda, key=lambda par: par[0])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reotimização contínua em rodadas")
    ap.add_argument("--intervalo", type=int, default=5)
    ap.add_argument("--horizonte", type=int, default=20)
    ap.add_argument("--remocoes", type=int, default=3)
    ap.add_argument("--tempo-limite", dest="tempo_limite", type=int, default=20)
    args = ap.parse_args(argv)

    politica = rod.Politica(intervalo_min=args.intervalo,
                            horizonte_compromisso_min=args.horizonte,
                            remocoes_por_rodada=args.remocoes)

    print("Planejando a véspera (PDPTW)…", flush=True)
    plano, rotas, contexto, agenda = montar_dia(tempo_limite_s=args.tempo_limite)
    print(f"  {len(rotas)} rotas · {plano['km_dia']} km planejados · "
          f"{len(agenda)} acontecimentos ao longo da manhã")

    print("Rodando o dia em rodadas…", flush=True)
    resultado = rod.rodar_dia(rotas, contexto["coords"],
                              contexto["pedidos_por_id"], agenda,
                              INICIO_MIN, FIM_MIN, politica)
    r = resultado["resumo"]
    print(f"  {r['rodadas']} rodadas ({r['rodadas_com_acao']} com ação) · "
          f"{r['km_economizados']} km economizados "
          f"({r['km_do_remanejamento']} deles por remanejamento) · "
          f"{r['faltas_absorvidas']} faltas · "
          f"{r['pedidos_aceitos']}/{r['pedidos_aceitos'] + r['pedidos_recusados']}"
          f" pedidos novos aceitos · {r['corridas_remanejadas']} corridas "
          f"trocaram de veículo")
    print(f"  resposta máxima {r['tempo_max_s']}s · "
          f"{r['melhorias_descartadas']} melhorias descartadas por não "
          f"compensar ou por mexer em horário combinado · "
          f"{r['promessas_quebradas']} promessas quebradas")

    saida = dict(resultado)
    saida.pop("rotas_finais")
    saida["gerado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    saida["km_planejados"] = plano["km_dia"]
    saida["origem"] = "simulacao"
    saida["perfil_transito"] = getattr(
        tempos_mod.provedor_padrao(), "perfil", None) and "com trânsito" or "sem trânsito"
    # o histórico completo pesa; o painel usa o resumo e as rodadas com ação
    saida["rodadas"] = [r_ for r_ in saida["rodadas"]
                        if r_["saidas"] or r_["pedidos_aceitos"]
                        or r_["movimentos"] or r_["pedidos_recusados"]]
    os.makedirs(DIR_RELATORIOS, exist_ok=True)
    caminho = os.path.join(DIR_RELATORIOS, "rodadas.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    print(f"Relatório: {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
