# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-comercial
As duas etapas comerciais, no terminal.

    # 1. precificar uma demanda nova (ganhar contrato)
    python comercial/cli.py precificar --plano relatorios/plano-fretamento.json \\
        --margem 12 --regime presumido

    # 2. otimizar a operação que já roda (dar dinheiro no contrato atual)
    python comercial/cli.py diagnosticar --plano relatorios/plano-fretamento.json \\
        --linhas linhas-atuais.csv

    # e os dois de uma vez, com proposta em HTML
    python comercial/cli.py proposta --plano ... --linhas ... --saida p.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comercial import diagnostico as diagnostico_mod  # noqa: E402
from comercial import operacao_atual as operacao_mod  # noqa: E402
from comercial import precificacao as precificacao_mod  # noqa: E402
from comercial.precificacao import Premissas  # noqa: E402

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")


def _carregar(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _premissas(args) -> Premissas:
    campos = {}
    if args.margem is not None:
        campos["margem_alvo"] = args.margem / 100.0
    if args.regime:
        campos["regime"] = args.regime
    if args.diesel is not None:
        campos["preco_diesel_l"] = args.diesel
    if args.monitores is not None:
        campos["monitores"] = args.monitores
    if args.dias is not None:
        campos["dias_operacao_mes"] = args.dias
    return Premissas(**campos)


def _reais(valor) -> str:
    texto = f"{valor:,.2f}"
    return "R$ " + texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def cmd_precificar(args):
    plano = _carregar(args.plano)
    resultado = precificacao_mod.precificar(plano, _premissas(args))
    custo, preco = resultado["custo"], resultado["preco"]

    print(f"\nPRECIFICAÇÃO — {plano.get('municipio', 'operação')}")
    print("=" * 72)
    for grupo, valor in custo["por_grupo"].items():
        print(f"  {grupo:<12} {_reais(valor):>18}")
    print(f"  {'CUSTO TOTAL':<12} {_reais(custo['total_mes']):>18}")
    print("-" * 72)
    print(f"  Impostos ({preco['carga_tributaria_pct']}% — "
          f"{preco['regime']}): {_reais(preco['impostos_mes'])}")
    print(f"  Margem ({preco['margem_alvo_pct']}%): {_reais(preco['lucro_mes'])}")
    print(f"  PREÇO: {_reais(preco['mes'])}/mês · {_reais(preco['ano'])}/ano")
    print(f"         {_reais(preco['por_veiculo_mes'])} por veículo/mês · "
          f"{_reais(preco['por_passageiro_mes'])} por passageiro/mês · "
          f"{_reais(preco['por_km'])}/km")
    print("-" * 72)
    for linha in resultado["memoria"]:
        print(f"  {linha}")

    if args.detalhado:
        print("\n  Planilha de custo:")
        for linha in custo["linhas"]:
            print(f"    [{linha['grupo']}] {linha['item']}: "
                  f"{_reais(linha['valor_mes'])}")
            print(f"        {linha['memoria']}")

    print("\n  E se mudar:")
    for cenario in precificacao_mod.sensibilidade(plano, _premissas(args)):
        print(f"    {cenario['cenario']:<38} {_reais(cenario['preco_mes']):>16} "
              f"({cenario['diferenca_pct']:+.1f}%)")

    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"\n  Detalhamento em {args.saida}")
    return 0


def cmd_diagnosticar(args):
    plano = _carregar(args.plano)
    tipos = plano["premissas"]["custos_por_tipo"]
    lido = operacao_mod.importar(args.linhas, tipos)
    if not lido["linhas"]:
        print("Não consegui ler a planilha de linhas:")
        for problema in lido["problemas"]:
            print(f"  - {problema}")
        return 1

    resultado = diagnostico_mod.diagnosticar(lido["linhas"], plano)
    print(f"\nDIAGNÓSTICO DA OPERAÇÃO ATUAL — {plano.get('municipio', '')}")
    print("=" * 72)
    for linha in diagnostico_mod.em_texto(resultado):
        print(linha)
    for problema in lido["problemas"][:5]:
        print(f"\n  ⚠ {problema}")

    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"\n  Detalhamento em {args.saida}")
    return 0


def cmd_proposta(args):
    from comercial import proposta as proposta_mod

    plano = _carregar(args.plano)
    preco = precificacao_mod.precificar(plano, _premissas(args))
    cenarios = precificacao_mod.sensibilidade(plano, _premissas(args))
    diagnostico = None
    if args.linhas:
        tipos = plano["premissas"]["custos_por_tipo"]
        lido = operacao_mod.importar(args.linhas, tipos)
        if lido["linhas"]:
            diagnostico = diagnostico_mod.diagnosticar(lido["linhas"], plano)

    caminho = proposta_mod.gerar(
        plano, preco, cenarios, diagnostico,
        cliente=args.cliente, saida=args.saida)
    print(f"Proposta em {caminho}")
    print(f"  Preço: {_reais(preco['preco']['mes'])}/mês · "
          f"{plano['frota_otimizada']['total_veiculos']} veículos · "
          f"{(plano.get('equipe') or {}).get('resumo', {}).get('motoristas', 0)}"
          f" motoristas")
    if diagnostico:
        print(f"  Diagnóstico: "
              f"{_reais(diagnostico['resumo']['economia_acoes_imediatas_mes'])}"
              f"/mês em ações imediatas")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Precificação e diagnóstico")
    sub = ap.add_subparsers(dest="comando", required=True)

    def comuns(p):
        p.add_argument("--plano", required=True, help="plano do motor (JSON)")
        p.add_argument("--margem", type=float, default=None,
                       help="margem alvo em %% (padrão 12)")
        p.add_argument("--regime", default=None,
                       choices=sorted(precificacao_mod.REGIMES))
        p.add_argument("--diesel", type=float, default=None)
        p.add_argument("--monitores", type=int, default=None)
        p.add_argument("--dias", type=int, default=None)
        p.add_argument("--saida", default=None)

    p = sub.add_parser("precificar", help="quanto custa e por quanto vender")
    comuns(p)
    p.add_argument("--detalhado", action="store_true")
    p.set_defaults(func=cmd_precificar)

    p = sub.add_parser("diagnosticar", help="o que dá para cortar no que já roda")
    comuns(p)
    p.add_argument("--linhas", required=True,
                   help="planilha das linhas operadas hoje")
    p.set_defaults(func=cmd_diagnosticar)

    p = sub.add_parser("proposta", help="proposta em HTML com as duas etapas")
    comuns(p)
    p.add_argument("--linhas", default=None)
    p.add_argument("--cliente", default=None)
    p.set_defaults(func=cmd_proposta)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
