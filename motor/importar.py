# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-dados
Importa a planilha da prefeitura e grava a demanda estruturada.

Uso:
    python motor/importar.py --gerar-exemplo         # cria uma planilha bagunçada
    python motor/importar.py planilha.xlsx
    python motor/importar.py planilha.csv --nomes    # guarda a lista nominal

Saída:
    relatorios/importacao.json   demanda + problemas linha a linha
    relatorios/cofre-nomes.json  só com --nomes, e o painel nunca lê este arquivo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import importador
from dados.planilha import ErroDePlanilha
from dados.planilha_exemplo import (
    gerar, limites_do_municipio, referencias_de_bairro,
)

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")
EXEMPLO = os.path.join(DIR_RELATORIOS, "planilha-prefeitura.xlsx")


def main():
    ap = argparse.ArgumentParser(description="Importador de planilha do MOBGOV")
    ap.add_argument("planilha", nargs="?", help="arquivo .xlsx, .csv ou .tsv")
    ap.add_argument("--gerar-exemplo", action="store_true",
                    help="cria uma planilha bagunçada de demonstração")
    ap.add_argument("--nomes", action="store_true",
                    help="guarda a lista nominal em arquivo separado (LGPD: "
                         "só use se o município exigir)")
    a = ap.parse_args()

    os.makedirs(DIR_RELATORIOS, exist_ok=True)
    caminho = a.planilha
    if a.gerar_exemplo or not caminho:
        caminho = gerar(EXEMPLO)
        print(f"Planilha de demonstração criada: {caminho}")

    try:
        resultado = importador.importar(
            caminho, referencias=referencias_de_bairro(),
            guardar_nomes=a.nomes, limites=limites_do_municipio())
    except ErroDePlanilha as erro:
        print(f"Não deu para ler a planilha: {erro}")
        return 1

    resumo = resultado.resumo()
    saida = {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "arquivo": os.path.basename(caminho),
        "resumo": resumo,
        "alunos": resultado.alunos,
        "problemas": resultado.problemas,
    }
    with open(os.path.join(DIR_RELATORIOS, "importacao.json"), "w",
              encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    if a.nomes and resultado.cofre:
        with open(os.path.join(DIR_RELATORIOS, "cofre-nomes.json"), "w",
                  encoding="utf-8") as f:
            json.dump(resultado.cofre, f, ensure_ascii=False, indent=2)
        print("Lista nominal gravada em relatorios/cofre-nomes.json — trate "
              "esse arquivo como dado pessoal de menor de idade.")

    print(f"\nImportação de {os.path.basename(caminho)}")
    print(f"  {resumo['alunos_importados']} alunos importados · "
          f"{resumo['erros']} erros · {resumo['avisos']} avisos")
    print(f"  {resumo['precisam_ajuste_no_mapa']} precisam de ajuste no mapa "
          f"(endereço sem coordenada)")
    print(f"  cadeirantes: {resumo['cadeirantes']} · com acompanhante: "
          f"{resumo['acompanhantes']}")
    print(f"  por turno: {resumo['por_turno']}")
    print(f"  colunas reconhecidas: {', '.join(sorted(resumo['colunas_detectadas']))}")
    if resultado.problemas:
        print("\n  primeiros problemas:")
        for p in resultado.problemas[:6]:
            print(f"   - linha {p['linha']} ({p['gravidade']}): {p['problema']} "
                  f"→ {p['sugestao']}")
    print("\nRelatório completo: relatorios/importacao.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
