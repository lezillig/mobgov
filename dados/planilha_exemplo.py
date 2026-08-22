# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-dados
Gera a "planilha da prefeitura" — bagunçada de propósito.

Serve para dois fins: o primeiro passo do roteiro de demonstração ("importar
planilha real bagunçada") e os testes do importador. A bagunça aqui não é
caricatura; é a lista do que aparece de verdade:

- duas linhas de título antes do cabeçalho;
- cabeçalho com "ALUNO(A)", "Endereço", "Nº", "Cadeira de Rodas";
- turno escrito como "MAT", "T", "Vespertino", "manhã";
- cadeirante marcado com "x", "SIM", "-", e uma célula com "?";
- aluno repetido em duas linhas;
- linha em branco no meio e um total no rodapé;
- endereço rural sem coordenada, só com o bairro;
- uma latitude e longitude trocadas de lugar.

Escreve XLSX de verdade (ZIP + XML), sem instalar nada.
"""
from __future__ import annotations

import random
import zipfile
from xml.sax.saxutils import escape

from dados.municipio_modelo import DISTRITOS, ESCOLAS

CABECALHO = ["ALUNO(A)", "Endereço", "Nº", "Bairro", "Escola", "Turno",
             "Cadeira de Rodas", "Acompanhante", "Latitude", "Longitude"]

NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elis", "Fábio", "Gabriela",
         "Heitor", "Ivone", "João", "Karina", "Lucas", "Marina", "Nelson",
         "Olívia", "Paulo", "Queila", "Rafael", "Sônia", "Tiago"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Pereira", "Costa", "Almeida",
              "Rodrigues", "Nascimento", "Araújo", "Ferreira"]
RUAS = ["Rua das Acácias", "Estrada do Assentamento", "Av. Central",
        "Rua Projetada", "Estrada Municipal", "Travessa São José"]
TURNOS_SUJOS = ["Manhã", "MAT", "manha", "Tarde", "T", "Vespertino", "M"]
# pesos realistas: a maioria não usa cadeira de rodas. O "?" aparece pouco,
# mas aparece — e é justamente o que o importador tem que reclamar.
CADEIRA_SUJO = ["", "", "", "", "-", "não", "NÃO", "x", "SIM", "?"]
PESOS_CADEIRA = [30, 25, 15, 10, 6, 5, 4, 2, 2, 1]


def linhas_bagunçadas(quantidade: int = 120, semente: int = 11) -> list:
    rng = random.Random(semente)
    distritos = list(DISTRITOS.items())
    linhas = [
        ["PREFEITURA MUNICIPAL DE RIBEIRÃO MODELO", "", "", "", "", ""],
        ["Secretaria de Educação — transporte escolar 2026", "", "", "", "", ""],
        CABECALHO,
    ]
    for i in range(quantidade):
        bairro, (clat, clon, raio, *_) = distritos[i % len(distritos)]
        nome = f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}"
        escola = rng.choice(ESCOLAS).nome
        tem_coordenada = rng.random() < 0.72       # o resto é endereço rural
        lat = round(clat + rng.uniform(-raio, raio), 6) if tem_coordenada else ""
        lon = round(clon + rng.uniform(-raio, raio), 6) if tem_coordenada else ""

        if tem_coordenada and i % 37 == 0:         # trocaram os dois campos
            lat, lon = lon, lat
        if tem_coordenada and i % 53 == 0:         # digitou o estado vizinho
            lat = round(lat + 8.0, 6) if lat else lat

        linhas.append([
            nome,
            f"{rng.choice(RUAS)}",
            str(rng.randint(1, 900)) if tem_coordenada else "s/n",
            bairro,
            escola,
            rng.choice(TURNOS_SUJOS),
            rng.choices(CADEIRA_SUJO, weights=PESOS_CADEIRA)[0],
            "sim" if rng.random() < 0.08 else "",
            str(lat), str(lon),
        ])
        if i % 45 == 0 and i:                      # aluno repetido
            linhas.append(list(linhas[-1]))
        if i % 60 == 0 and i:                      # linha em branco no meio
            linhas.append(["", "", "", "", "", "", "", "", "", ""])
    linhas.append(["TOTAL", str(quantidade), "", "", "", "", "", "", "", ""])
    return linhas


# --------------------------------------------------------------- escrita ---
def _celula(referencia: str, texto: str) -> str:
    if texto == "":
        return ""
    return (f'<c r="{referencia}" t="inlineStr"><is><t xml:space="preserve">'
            f'{escape(str(texto))}</t></is></c>')


def _referencia(coluna: int, linha: int) -> str:
    letras = ""
    coluna += 1
    while coluna:
        coluna, resto = divmod(coluna - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return f"{letras}{linha}"


def escrever_xlsx(caminho: str, linhas: list):
    corpo = []
    for i, linha in enumerate(linhas, start=1):
        celulas = "".join(_celula(_referencia(j, i), v)
                          for j, v in enumerate(linha))
        if not celulas:
            continue          # o Excel não grava linha vazia: pula o <row r=N>
        corpo.append(f'<row r="{i}">{celulas}</row>')
    planilha = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main"><sheetData>'
                + "".join(corpo) + '</sheetData></worksheet>')

    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/content-types">'
                   '<Default Extension="rels" ContentType="application/'
                   'vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId1" Type='
                   '"http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Alunos" sheetId="1" r:id="rId1"/>'
                   '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId1" Type='
                   '"http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", planilha)
    return caminho


def gerar(caminho: str, quantidade: int = 120) -> str:
    return escrever_xlsx(caminho, linhas_bagunçadas(quantidade))


def referencias_de_bairro() -> dict:
    """Pontos de referência por bairro — o plano B da geocodificação."""
    return {nome: (dados[0], dados[1]) for nome, dados in DISTRITOS.items()}


def limites_do_municipio(folga: float = 0.08) -> tuple:
    lats = [d[0] for d in DISTRITOS.values()]
    lons = [d[1] for d in DISTRITOS.values()]
    return (min(lats) - folga, max(lats) + folga,
            min(lons) - folga, max(lons) + folga)
