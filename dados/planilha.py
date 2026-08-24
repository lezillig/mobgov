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
from datetime import datetime, timedelta
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


def ler_xlsx(caminho: str, aba=0) -> list:
    try:
        with zipfile.ZipFile(caminho) as z:
            compartilhadas = _strings_compartilhadas(z)
            formatos = _formatos_de_data(z)
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
            valores.append(_valor_da_celula(celula, compartilhadas, formatos))
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


def _abas_do_arquivo(z: zipfile.ZipFile) -> list:
    """As abas na ORDEM em que o Excel as mostra, com nome e caminho.

    Ordenar `sheet1.xml, sheet2.xml, ...` por nome de arquivo erra de duas
    formas: `sheet10` vem antes de `sheet2`, e a ordem dos arquivos não é a
    ordem das abas na tela. Quem manda é `xl/workbook.xml` mais o mapa de
    relacionamentos — é o que a planilha da secretaria de verdade exige,
    porque lá a segunda aba é metade da operação.
    """
    try:
        with z.open("xl/_rels/workbook.xml.rels") as f:
            rels = ElementTree.parse(f).getroot()
        alvo = {}
        for r in rels:
            ident = r.get("Id")
            caminho = r.get("Target", "")
            if ident and "worksheets/" in caminho:
                alvo[ident] = "xl/" + caminho.lstrip("/").replace("../", "")
        with z.open("xl/workbook.xml") as f:
            wb = ElementTree.parse(f).getroot()
        abas = []
        for folha in wb.iter(f"{{{NS['x']}}}sheet"):
            ident = folha.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships}id")
            caminho = alvo.get(ident)
            if caminho:
                abas.append({"nome": folha.get("name", ""), "caminho": caminho})
        if abas:
            return abas
    except (KeyError, ElementTree.ParseError):
        pass
    # workbook.xml ilegível: cai para os arquivos, agora em ordem numérica
    def numero(n):
        achado = re.search(r"sheet(\d+)\.xml$", n)
        return int(achado.group(1)) if achado else 0
    planilhas = sorted((n for n in z.namelist()
                        if n.startswith("xl/worksheets/sheet")
                        and n.endswith(".xml")), key=numero)
    return [{"nome": f"aba {i + 1}", "caminho": n}
            for i, n in enumerate(planilhas)]


def _nome_da_aba(z: zipfile.ZipFile, aba) -> str:
    """`aba` pode ser o índice (0, 1, …) ou o nome que aparece no Excel."""
    abas = _abas_do_arquivo(z)
    if not abas:
        raise ErroDePlanilha("A planilha não tem nenhuma aba com dados.")
    if isinstance(aba, str):
        alvo = " ".join(aba.split()).casefold()
        for a in abas:
            if " ".join(a["nome"].split()).casefold() == alvo:
                return a["caminho"]
        raise ErroDePlanilha(
            f"A planilha não tem a aba {aba!r}. Ela tem: "
            f"{', '.join(a['nome'] for a in abas)}.")
    return abas[min(int(aba), len(abas) - 1)]["caminho"]


def abas(caminho: str) -> list:
    """Os nomes das abas, na ordem da planilha.

    Existe para ninguém perder metade da operação em silêncio: planilha de
    secretaria costuma ter uma aba por região, e ler só a primeira é o tipo
    de erro que só aparece quando faltar veículo na rua.
    """
    if os.path.splitext(caminho)[1].lower() not in (".xlsx", ".xlsm"):
        return []
    try:
        with zipfile.ZipFile(caminho) as z:
            return [a["nome"] for a in _abas_do_arquivo(z)]
    except (zipfile.BadZipFile, KeyError):
        return []


# Formatos de data e hora que o Excel numera de fábrica. O resto (id >= 164)
# é formato que o usuário criou, e vem escrito em xl/styles.xml.
FORMATOS_DE_FABRICA = {
    14: "data", 15: "data", 16: "data", 17: "data",
    18: "hora", 19: "hora", 20: "hora", 21: "hora",
    22: "data_hora", 45: "hora", 46: "hora", 47: "hora",
}


def _classificar_formato(codigo: str):
    """"h:mm" -> hora; "dd/mm/aaaa" -> data; "#,##0.00" -> None."""
    limpo = re.sub(r"\[[^\]]*\]", "", codigo or "")     # [h], [Red], [$-416]
    limpo = re.sub(r"\"[^\"]*\"", "", limpo).lower()    # literais entre aspas
    limpo = limpo.replace("\\", "")
    tem_hora = "h" in limpo or "s" in limpo
    tem_data = "y" in limpo or "a" in limpo or "d" in limpo
    if tem_hora and tem_data:
        return "data_hora"
    return "hora" if tem_hora else ("data" if tem_data else None)


def _formatos_de_data(z: zipfile.ZipFile) -> dict:
    """Índice de estilo -> "data" | "hora" | "data_hora".

    Existe porque, para o Excel, hora é número: 07:00 fica gravado como
    0.2916666. Sem consultar o formato, a coluna de horário da planilha real
    chegava ao importador como uma fração — e o turno de 456 alunos virava
    "não reconhecido". O formato da célula é o único lugar onde está escrito
    que aquele número é um relógio.
    """
    if "xl/styles.xml" not in z.namelist():
        return {}
    try:
        with z.open("xl/styles.xml") as f:
            raiz = ElementTree.parse(f).getroot()
    except ElementTree.ParseError:
        return {}

    por_id = dict(FORMATOS_DE_FABRICA)
    for fmt in raiz.iter(f"{{{NS['x']}}}numFmt"):
        try:
            ident = int(fmt.get("numFmtId", "-1"))
        except ValueError:
            continue
        classe = _classificar_formato(fmt.get("formatCode", ""))
        if classe:
            por_id[ident] = classe
        else:
            por_id.pop(ident, None)     # o usuário redefiniu um id de fábrica

    estilos = {}
    lista = raiz.find(f"{{{NS['x']}}}cellXfs")
    for indice, xf in enumerate(lista if lista is not None else []):
        try:
            ident = int(xf.get("numFmtId", "0"))
        except ValueError:
            continue
        if ident in por_id:
            estilos[indice] = por_id[ident]
    return estilos


# O Excel conta os dias a partir de 30/12/1899 (o dia zero fictício que faz a
# conta bater com o bug do ano bissexto de 1900 que a Lotus 1-2-3 tinha e a
# Microsoft copiou).
_DIA_ZERO = datetime(1899, 12, 30)


def _data_do_serial(texto: str, classe: str):
    try:
        serial = float(texto)
    except ValueError:
        return None
    if serial < 0 or serial > 2958466:          # fora de 1900..9999
        return None
    momento = _DIA_ZERO + timedelta(days=serial)
    if classe == "hora" or (classe == "data_hora" and serial < 1):
        return momento.strftime("%H:%M")
    if classe == "data":
        return momento.strftime("%d/%m/%Y")
    return momento.strftime("%d/%m/%Y %H:%M")


def _valor_da_celula(celula, compartilhadas: list, formatos: dict = None) -> str:
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
    if tipo in (None, "n") and formatos:
        try:
            classe = formatos.get(int(celula.get("s", "-1")))
        except ValueError:
            classe = None
        if classe:
            legivel = _data_do_serial(texto, classe)
            if legivel:
                return legivel
    # número inteiro que veio como 12.0 volta a ser 12 — CPF e matrícula
    # quebram feio quando viram float
    if re.fullmatch(r"-?\d+\.0+", texto):
        return texto.split(".")[0]
    return texto


# ------------------------------------------------------------------ único ---
def ler(caminho: str, aba=0) -> list:
    """Lê a planilha e devolve uma lista de linhas (listas de texto).

    `aba` aceita índice ou o nome que aparece no Excel. Para saber o que
    existe antes de escolher, use `abas(caminho)`.
    """
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
