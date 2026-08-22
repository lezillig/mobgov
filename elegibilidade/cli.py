# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
A mesa de trabalho do analista, no terminal.

    python elegibilidade/cli.py fila
    python elegibilidade/cli.py ver P1A49AA07
    python elegibilidade/cli.py ler-documento P1A49AA07 --arquivo laudo.txt
    python elegibilidade/cli.py aprovar P1A49AA07 --analista "Ana (SME)" \
        --fontes laudo --campos cadeira_de_rodas acompanhante --permanente
    python elegibilidade/cli.py negar P1A49AA07 --analista "Ana (SME)" \
        --justificativa "..."
    python elegibilidade/cli.py relatorio

`ler-documento` mostra o que a leitura assistida propôs, com o trecho que
sustenta cada proposta — e não altera nada. Quem altera é `aprovar --campos`,
que exige o nome de quem está aprovando.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elegibilidade import extracao, fila, formulario, relatorio  # noqa: E402
from elegibilidade.perfil import Perfil  # noqa: E402


def _pedido_de(protocolo: str, arquivo: str) -> dict:
    eventos = fila.ler_eventos(arquivo, protocolo)
    if not eventos:
        raise SystemExit(f"Protocolo {protocolo} não encontrado.")
    return eventos[0].get("pedido", {})


def cmd_fila(args):
    lista = fila.listar(args.arquivo, args.estado, args.hoje)
    if not lista:
        print("Fila vazia.")
        return
    print(f"{'PROTOCOLO':<11} {'ESTADO':<24} {'ABERTO':<11} {'DIAS':>4}  PERFIL")
    for s in lista:
        marca = "!" if s["atrasado"] else " "
        print(f"{s['protocolo']:<11} {s['estado']:<24} {s['aberto_em']:<11} "
              f"{s['dias_em_aberto']:>4}{marca} {s['resumo_do_perfil'][:44]}")
    resumo = fila.resumo(args.arquivo, args.hoje)
    print(f"\n{resumo['pedidos']} pedidos · {resumo['em_aberto']} em aberto · "
          f"{resumo['atrasados']} passaram do prazo de {resumo['prazo_dias']} "
          f"dias · média de {resumo['dias_em_aberto_media']} dias em aberto")


def cmd_ver(args):
    situacao = fila.situacao(args.protocolo, args.arquivo, args.hoje)
    if not situacao:
        raise SystemExit(f"Protocolo {args.protocolo} não encontrado.")
    print(f"Protocolo {situacao['protocolo']} — {situacao['estado_em_portugues']}")
    print(f"  aberto em {situacao['aberto_em']} · prazo até "
          f"{situacao['prazo_ate']}" + ("  [ATRASADO]" if situacao["atrasado"]
                                        else ""))
    print(f"  {situacao['bairro']} → {situacao['destino']}")
    print(f"  perfil: {situacao['resumo_do_perfil']}")
    if situacao["pendencia"]:
        print(f"  esperando da família: {situacao['pendencia']}")
    if situacao["analista"]:
        print(f"  decidido por {situacao['analista']}"
              + (" · concessão permanente" if situacao["permanente"]
                 else f" · vence em {situacao['vence_em']}"))
    if situacao["justificativa"]:
        print(f"  justificativa: {situacao['justificativa']}")
    print("  histórico:")
    for passo in situacao["historico"]:
        detalhe = f" — {passo['detalhe']}" if passo["detalhe"] else ""
        print(f"    {passo['em'][:16]}  {passo['tipo']}"
              f"{' (' + passo['analista'] + ')' if passo['analista'] else ''}"
              f"{detalhe}")


def cmd_ler_documento(args):
    with open(args.arquivo_documento, "r", encoding="utf-8") as f:
        texto = f.read()
    cliente = None
    if args.com_ia:
        from conversa.assistente import ClienteAnthropic
        cliente = ClienteAnthropic()
    resultado = (extracao.analisar_com_modelo(texto, cliente) if cliente
                 else extracao.analisar(texto))
    print(f"Leitura assistida ({resultado.origem}) — NADA foi alterado.\n")
    for item in resultado.para_aprovacao():
        print(f"  [{item['confianca']:.2f}] {item['campo']} = {item['valor']}")
        print(f"         porque {item['porque']}")
        print(f"         trecho: “{item['trecho'][:120]}”")
    for alerta in resultado.alertas:
        print(f"\n  ⚠ {alerta}")
    if resultado.codigos_sensiveis:
        print(f"\n  códigos no documento (dado sensível, fica no processo): "
              f"{', '.join(resultado.codigos_sensiveis)}")
    print("\nPara aplicar, use: aprovar <protocolo> --analista <nome> "
          "--campos <campo> [<campo> ...]")


def cmd_aprovar(args):
    pedido = _pedido_de(args.protocolo, args.arquivo)
    perfil = Perfil.de_dicionario(pedido.get("perfil", {}))
    aplicadas = []
    if args.campos:
        if not args.arquivo_documento:
            raise SystemExit("--campos precisa de --arquivo-documento: o "
                             "trecho que sustenta cada campo vai para o "
                             "registro da decisão.")
        with open(args.arquivo_documento, "r", encoding="utf-8") as f:
            resultado = extracao.analisar(f.read())
        perfil, aplicadas = extracao.aplicar(perfil, resultado, args.campos)

    problemas = perfil.coerente()
    if problemas and not args.mesmo_assim:
        print("Confira antes de aprovar:")
        for p in problemas:
            print(f"  - {p}")
        raise SystemExit("Use --mesmo-assim se estiver certo.")

    evento = fila.aprovar(args.protocolo, args.analista, perfil, args.fontes,
                          permanente=args.permanente,
                          justificativa=args.justificativa,
                          sugestoes_aplicadas=aplicadas,
                          validade_meses=args.validade_meses,
                          arquivo=args.arquivo)
    print(f"Aprovado por {evento['analista']}: {evento['resumo']}")
    print("Concessão permanente — a família não precisa renovar."
          if evento["permanente"] else f"Vence em {evento['vence_em']}.")


def cmd_negar(args):
    fila.negar(args.protocolo, args.analista, args.justificativa,
               arquivo=args.arquivo)
    print("Negado. A família recebe a justificativa e o caminho do recurso.")


def cmd_informacao(args):
    fila.pedir_informacao(args.protocolo, args.analista, args.o_que,
                          args.arquivo)
    print(f"Pedido enviado à família: {args.o_que}")


def cmd_novo(args):
    with open(args.respostas, "r", encoding="utf-8") as f:
        respostas = json.load(f)
    pedido = formulario.montar_pedido(respostas)
    fila.receber(pedido, args.arquivo)
    print(f"Protocolo {pedido['protocolo']} criado. "
          f"Perfil: {pedido['resumo_do_perfil']}")


def cmd_demanda(args):
    demanda = fila.demanda_para_roteirizacao(args.arquivo, args.hoje)
    print(json.dumps(demanda, ensure_ascii=False, indent=1))


def cmd_relatorio(args):
    print(f"Relatório escrito em "
          f"{relatorio.gerar(args.arquivo, hoje=args.hoje)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Elegibilidade ao porta a porta")
    ap.add_argument("--arquivo", default=None,
                    help="diário de eventos (padrão: relatorios/operacao/)")
    ap.add_argument("--hoje", default=None, help="data de referência aaaa-mm-dd")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("fila", help="lista os pedidos")
    p.add_argument("--estado", default=None)
    p.set_defaults(func=cmd_fila)

    p = sub.add_parser("ver", help="mostra um protocolo")
    p.add_argument("protocolo")
    p.set_defaults(func=cmd_ver)

    p = sub.add_parser("ler-documento", help="leitura assistida do documento")
    p.add_argument("protocolo")
    p.add_argument("--arquivo-documento", dest="arquivo_documento",
                   required=True)
    p.add_argument("--com-ia", action="store_true")
    p.set_defaults(func=cmd_ler_documento)

    p = sub.add_parser("aprovar")
    p.add_argument("protocolo")
    p.add_argument("--analista", required=True)
    p.add_argument("--fontes", nargs="+", required=True)
    p.add_argument("--campos", nargs="*", default=[])
    p.add_argument("--arquivo-documento", dest="arquivo_documento")
    p.add_argument("--justificativa", default="")
    p.add_argument("--permanente", action="store_true")
    p.add_argument("--validade-meses", dest="validade_meses", type=int,
                   default=None)
    p.add_argument("--mesmo-assim", dest="mesmo_assim", action="store_true")
    p.set_defaults(func=cmd_aprovar)

    p = sub.add_parser("negar")
    p.add_argument("protocolo")
    p.add_argument("--analista", required=True)
    p.add_argument("--justificativa", required=True)
    p.set_defaults(func=cmd_negar)

    p = sub.add_parser("informacao", help="pede uma informação à família")
    p.add_argument("protocolo")
    p.add_argument("--analista", required=True)
    p.add_argument("--o-que", dest="o_que", required=True)
    p.set_defaults(func=cmd_informacao)

    p = sub.add_parser("novo", help="entra com um pedido a partir de um JSON")
    p.add_argument("respostas")
    p.set_defaults(func=cmd_novo)

    p = sub.add_parser("demanda", help="o que vai para a roteirização")
    p.set_defaults(func=cmd_demanda)

    p = sub.add_parser("relatorio", help="gera relatorios/elegibilidade.json")
    p.set_defaults(func=cmd_relatorio)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
