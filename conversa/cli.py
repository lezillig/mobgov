# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-conversa
Conversa pelo terminal: `python conversa/cli.py "quanto eu economizo?"`

Sem argumento, abre o modo pergunta-e-resposta. É o que roda na demonstração
ao vivo: o gestor dita a pergunta, quem apresenta digita, e o número que sai é
o mesmo do painel projetado ao lado.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversa import ferramentas as ferramentas_mod  # noqa: E402
from conversa.assistente import Assistente  # noqa: E402

SUGESTOES = [
    "Quanto eu economizo por mês?",
    "Por que preciso de tantos ônibus?",
    "E se o diesel for a R$ 8,20?",
    "A planilha da secretaria entrou direito?",
    "Como está a operação hoje?",
    "O que o sistema aprendeu até agora?",
    "Gere o relatório para a prestação de contas.",
]


def _cabecalho(assistente: Assistente):
    modo = "offline (sem LLM)" if (assistente.offline or
                                   not assistente.cliente.configurado()) \
        else "com modelo de linguagem"
    print("MOBGOV — assistente de transporte escolar")
    print(f"Modo: {modo}. Todo número sai das ferramentas do sistema.")
    print("Pergunte à vontade. 'sair' encerra, 'temas' lista o que eu sei.\n")
    print("Exemplos:")
    for s in SUGESTOES:
        print(f"  - {s}")
    print()


def _mostrar(resposta: dict, detalhado: bool):
    print()
    print(resposta["resposta"])
    if detalhado:
        print()
        for chamada in resposta["ferramentas"]:
            print(f"[ferramenta] {chamada['nome']}({chamada['argumentos']})")
            print(json.dumps(chamada["resultado"], ensure_ascii=False,
                             indent=2)[:1200])
    if resposta.get("motivo_offline"):
        print(f"\n(respondido offline: {resposta['motivo_offline']})")
    if resposta.get("numeros_suspeitos"):
        print(f"\n(auditoria: {resposta['numeros_suspeitos']})")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pergunte ao MOBGOV em português")
    ap.add_argument("pergunta", nargs="*", help="pergunta; vazio abre o chat")
    ap.add_argument("--offline", action="store_true",
                    help="não usa LLM nem internet")
    ap.add_argument("--detalhado", action="store_true",
                    help="mostra a ferramenta chamada e o resultado bruto")
    args = ap.parse_args(argv)

    assistente = Assistente(offline=args.offline)

    if args.pergunta:
        _mostrar(assistente.responder(" ".join(args.pergunta)), args.detalhado)
        return 0

    _cabecalho(assistente)
    while True:
        try:
            pergunta = input("você > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not pergunta:
            continue
        if pergunta.lower() in ("sair", "quit", "exit"):
            return 0
        if pergunta.lower() == "temas":
            print("\n" + ferramentas_mod.catalogo_em_texto() + "\n")
            continue
        _mostrar(assistente.responder(pergunta), args.detalhado)


if __name__ == "__main__":
    sys.exit(main())
