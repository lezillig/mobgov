# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-dados
Leitura de planilha: CSV, TSV e XLSX, sem instalar nada.

Prefeitura manda `.xlsx`. Pedir "salve como CSV" é transferir para o servidor
público um trabalho que o sistema pode fazer sozinho — e é onde a importação
costuma morrer. Por isso o XLSX é lido aqui direto: um `.xlsx` é um ZIP com
XML dentro, e a biblioteca padrão abre os dois.

O que este módulo resolve, e que um `csv.reader` não resolveria:

- **codificação**: planilha brasileira vem em UTF-8, UTF-8 com BOM ou
  Latin-1, e cada uma quebra os acentos de um jeito;
- **separador**: `;` no Excel em português, `,` no exportado de sistema, tab
  no colado do Word;
- **XLSX**: strings compartilhadas, células vazias que somem do XML e
  colunas puladas (A, B, D…) — se ignorados, os dados entram na coluna
  errada e ninguém percebe até a rota sair torta.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from xml.etree import ElementTree

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CODIFICACOES = ("utf-8-sig", "utf-8", "latin-1")


class ErroDePlanilha(RuntimeError):
    pass


# ------------------------------------------------------------------- texto ---
def _decodificar(bruto: bytes) -> str:
    for codificacao in CODIFICACOES:
        try:
            return bruto.decode(codificacao)
        except UnicodeDecodeError:
            continue
    # último recurso: não perder a linha inteira por causa de um byte
    return bruto.decode("utf-8", errors="replace")


def _separador(texto: str, amostra: int = 12) -> str:
    """Descobre o separador olhando VÁRIAS linhas, não só a primeira.

    A primeira linha de uma planilha de verdade costuma ser título — "RELAÇÃO
    DE COLABORADORES 2026" — sem separador nenhum. Decidindo por ela, o
    arquivo inteiro virava uma coluna só e o importador respondia "não
    reconheci as colunas", que é a mensagem mais frustrante possível para
    quem mandou o arquivo certo.
    """
    linhas = [l for l in texto.splitlines()[:amostra] if l.strip()]
    candidatos = {}
    for separador in (";", ",", "\t"):
        # conta em quantas linhas ele aparece e quantas vezes ao todo: o
        # separador de verdade se repete em quase todas as linhas
        contagens = [l.count(separador) for l in linhas]
        presente = sum(1 for c in contagens if c)
        candidatos[separador] = (presente, sum(contagens))
    melhor = max(candidatos, key=lambda s: candidatos[s])
    return melhor if candidatos[melhor][0] else ","


def numero_br(texto, padrao=None):
    """Número escrito como brasileiro escreve — para QUANTIDADE, não para
    coordenada.

    A ambiguidade é real: "4.386" é quatro mil e trezentos e oitenta e seis, e
    "100.3" é cem vírgula três. A regra que resolve os dois é a do uso: ponto
    seguido de exatamente três dígitos, sem vírgula na frase, é separador de
    milhar; qualquer outro ponto é decimal.

    NÃO use isto em latitude/longitude: "-21.150" é vinte e um e cento e
    cinquenta milésimos, e cairia na regra do milhar. Coordenada tem parser
    próprio no importador, e é assim de propósito.
    """
    bruto = str(texto or "").strip()
    achado = re.search(r"-?[\d.,]+", bruto)
    if not achado:
        return padrao
    numero = achado.group(0)
    if "," in numero:                       # vírgula manda: é a decimal
        numero = numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", numero):
        numero = numero.replace(".", "")    # 4.386 e 1.234.567
    try:
        return float(numero)
    except ValueError:
        return padrao


def ler_csv(caminho: str) -> list:
    with open(caminho, "rb") as f:
        texto = _decodificar(f.read())
    leitor = csv.reader(io.StringIO(texto), delimiter=_separador(texto))
    return [[(c or "").strip() for c in linha] for linha in leitor]


# -------------------------------------------------------------------- xlsx ---
def _coluna_para_indice(referencia: str) -> int:
    """'A' -> 0, 'B' -> 1, 'AA' -> 26. Célula pulada não pode deslocar a linha."""
    letras = re.match(r"([A-Z]+)", referencia or "")
    if not letras:
        return 0
    indice = 0
    for letra in letras.group(1):
        indice = indice * 26 + (ord(letra) - ord("A") + 1)
    return indice - 1


def ler_xlsx(caminho: str, aba: int = 0) -> list:
    try:
        with zipfile.ZipFile(caminho) as z:
            compartilhadas = _strings_compartilhadas(z)
            nome_aba = _nome_da_aba(z, aba)
            with z.open(nome_aba) as f:
                arvore = ElementTree.parse(f)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as erro:
        raise ErroDePlanilha(
            f"Não consegui abrir '{os.path.basename(caminho)}' como planilha "
            f"do Excel ({erro}). Se o arquivo for .xls antigo, salve como "
            f".xlsx ou .csv e tente de novo.")

    linhas = []
    for linha in arvore.getroot().iter(f"{{{NS['x']}}}row"):
        valores = []
        for celula in linha:
            indice = _coluna_para_indice(celula.get("r", ""))
            while len(valores) < indice:       # célula vazia some do XML
                valores.append("")
            valores.append(_valor_da_celula(celula, compartilhadas))
        # Linha totalmente vazia também some do XML: o Excel pula do <row r=2>
        # para o <row r=4>. Se a gente ignorasse o 'r', tudo depois da linha em
        # branco andaria uma casa — e o "conserte a linha 88" do relatório de
        # importação mandaria o servidor para a linha errada da planilha dele.
        try:
            numero = int(linha.get("r", "0"))
        except ValueError:
            numero = 0
        while numero and len(linhas) < numero - 1:
            linhas.append([])
        linhas.append(valores)
    return linhas


def _strings_compartilhadas(z: zipfile.ZipFile) -> list:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    with z.open("xl/sharedStrings.xml") as f:
        arvore = ElementTree.parse(f)
    textos = []
    for item in arvore.getroot().iter(f"{{{NS['x']}}}si"):
        textos.append("".join(t.text or "" for t in item.iter(f"{{{NS['x']}}}t")))
    return textos


def _nome_da_aba(z: zipfile.ZipFile, aba: int) -> str:
    planilhas = sorted(n for n in z.namelist()
                       if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    if not planilhas:
        raise ErroDePlanilha("A planilha não tem nenhuma aba com dados.")
    return planilhas[min(aba, len(planilhas) - 1)]


def _valor_da_celula(celula, compartilhadas: list) -> str:
    tipo = celula.get("t")
    if tipo == "inlineStr":
        return "".join(t.text or "" for t in celula.iter(f"{{{NS['x']}}}t")).strip()
    valor = celula.find(f"{{{NS['x']}}}v")
    if valor is None or valor.text is None:
        return ""
    if tipo == "s":
        try:
            return compartilhadas[int(valor.text)].strip()
        except (ValueError, IndexError):
            return ""
    texto = valor.text.strip()
    # número inteiro que veio como 12.0 volta a ser 12 — CPF e matrícula
    # quebram feio quando viram float
    if re.fullmatch(r"-?\d+\.0+", texto):
        return texto.split(".")[0]
    return texto


# ------------------------------------------------------------------ único ---
def ler(caminho: str, aba: int = 0) -> list:
    """Lê a planilha e devolve uma lista de linhas (listas de texto)."""
    if not os.path.exists(caminho):
        raise ErroDePlanilha(f"Arquivo não encontrado: {caminho}")
    extensao = os.path.splitext(caminho)[1].lower()
    if extensao in (".xlsx", ".xlsm"):
        return ler_xlsx(caminho, aba)
    if extensao in (".csv", ".txt", ".tsv"):
        return ler_csv(caminho)
    # sem extensão confiável: tenta ZIP (xlsx) e cai para texto
    try:
        return ler_xlsx(caminho, aba)
    except ErroDePlanilha:
        return ler_csv(caminho)
