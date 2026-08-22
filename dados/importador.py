# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-dados
Importa a planilha real da prefeitura e devolve demanda estruturada.

O primeiro passo do roteiro de demonstração é "importar planilha real
bagunçada". Bagunçada de verdade quer dizer: cabeçalho com nome diferente a
cada município ("aluno", "nome do aluno", "ALUNO(A)"), turno escrito de seis
jeitos, endereço sem número, aluno repetido em duas linhas, célula de
cadeirante com "x", e uma linha em branco no meio.

O importador não recusa a planilha por causa disso. Ele:

1. **acha as colunas** por sinônimo, ignorando acento, caixa e espaço;
2. **normaliza** turno, sim/não e coordenadas;
3. **deduplica** aluno repetido, mantendo a primeira ocorrência;
4. **geocodifica com plano B**: sem lat/lon, usa o ponto de referência do
   bairro e marca a linha como "precisa de ajuste no mapa" — endereço rural
   quase nunca tem número, e travar a importação por isso inviabiliza o
   piloto;
5. **anonimiza**: o que segue para a roteirização é um pseudônimo. O nome do
   aluno só é guardado se o município pedir explicitamente, em arquivo
   separado. Dado de menor de idade não passeia pelo sistema.
6. **relata em português**, linha a linha, o que não deu para resolver
   sozinho — com a sugestão do que fazer.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from dados.planilha import ler

# --------------------------------------------------------------- sinônimos ---
SINONIMOS = {
    "nome": ["nome", "nome do aluno", "aluno", "aluna", "estudante",
             "nome completo", "nome aluno", "nome do estudante", "aluno a",
             # fretamento: a planilha vem do RH, não da secretaria
             "colaborador", "colaboradora", "funcionario", "funcionaria",
             "empregado", "nome do colaborador", "nome do funcionario"],
    "endereco": ["endereco", "logradouro", "rua", "endereco completo",
                 "residencia", "endereco residencial", "local de embarque"],
    "numero": ["numero", "n", "no", "num", "numero casa"],
    "bairro": ["bairro", "distrito", "localidade", "comunidade", "zona",
               "povoado", "assentamento", "regiao"],
    "escola": ["escola", "unidade", "unidade escolar", "destino",
               "escola de destino", "estabelecimento",
               # fretamento: o destino é a planta onde a pessoa trabalha
               "planta", "fabrica", "filial", "local de trabalho", "obra",
               "centro de custo", "unidade de destino", "site"],
    "turno": ["turno", "periodo", "horario", "turno escolar",
              "turno de trabalho", "escala", "jornada"],
    "cadeirante": ["cadeirante", "cadeira de rodas", "usa cadeira de rodas",
                   "pcd", "deficiencia", "necessidade especial",
                   "mobilidade reduzida", "acessibilidade"],
    "acompanhante": ["acompanhante", "monitor", "necessita acompanhante",
                     "responsavel acompanha"],
    "latitude": ["latitude", "lat", "coord lat"],
    "longitude": ["longitude", "long", "lon", "coord long"],
}

# Turnos reconhecidos. Os quatro primeiros são do escolar; os de fretamento
# vêm da indústria, onde "T1" e "1o turno" são o jeito de todo mundo escrever.
TURNOS = {
    "manha": ["manha", "matutino", "m", "manha 1", "1", "mat"],
    "tarde": ["tarde", "vespertino", "t", "2", "vesp"],
    "noite": ["noite", "noturno", "n", "3", "not"],
    "t1": ["t1", "1o turno", "1 turno", "primeiro turno", "turno 1", "a"],
    "t2": ["t2", "2o turno", "2 turno", "segundo turno", "turno 2", "b"],
    "t3": ["t3", "3o turno", "3 turno", "terceiro turno", "turno 3", "c"],
    "adm": ["adm", "administrativo", "comercial", "horario administrativo",
            "escritorio", "geral"],
}

AFIRMATIVOS = {"sim", "s", "x", "1", "true", "verdadeiro", "v", "sim ",
               "possui", "tem"}
NEGATIVOS = {"nao", "n", "0", "false", "falso", "", "-", "nenhum"}


# ------------------------------------------------------------------ texto ---
def normalizar(texto: str) -> str:
    """minúsculas, sem acento, sem pontuação, espaço colapsado."""
    if texto is None:
        return ""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn")
    limpo = re.sub(r"[^\w\s]", " ", sem_acento.lower())
    return re.sub(r"\s+", " ", limpo).strip()


def _numero(valor: str):
    if valor in (None, ""):
        return None
    texto = str(valor).strip().replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def pseudonimo(*partes) -> str:
    """Identificador estável e irreversível para o aluno.

    Estável porque a mesma pessoa na importação do mês seguinte precisa cair
    no mesmo id (senão o histórico se perde). Irreversível porque o que roda
    no motor, nos logs e em qualquer prompt de IA não pode voltar a ser o
    nome de uma criança.
    """
    semente = "|".join(normalizar(p) for p in partes if p)
    return "A" + hashlib.sha256(semente.encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------- cabeçalho ---
def detectar_colunas(cabecalho: list) -> dict:
    """Mapeia campo -> índice da coluna, por sinônimo."""
    normalizado = [normalizar(c) for c in cabecalho]
    colunas = {}
    for campo, opcoes in SINONIMOS.items():
        for i, titulo in enumerate(normalizado):
            if not titulo or i in colunas.values():
                continue
            if titulo in opcoes or any(
                    titulo.startswith(o + " ") or titulo == o for o in opcoes):
                colunas[campo] = i
                break
    return colunas


def _achar_cabecalho(linhas: list, limite: int = 10) -> int:
    """A planilha da secretaria costuma ter título e logo antes do cabeçalho."""
    melhor, melhor_pontuacao = 0, -1
    for i, linha in enumerate(linhas[:limite]):
        pontuacao = len(detectar_colunas(linha))
        if pontuacao > melhor_pontuacao:
            melhor, melhor_pontuacao = i, pontuacao
    return melhor


# ------------------------------------------------------------- conversões ---
def converter_turno(valor: str, validos=None):
    """Traduz o que está escrito na célula para um id de turno.

    `validos` é a lista de turnos que a operação tem de fato (do perfil): sem
    ela, uma planilha de fretamento com "T1" entraria como turno inexistente
    numa operação escolar de manhã e tarde — e o aluno cairia num turno que
    ninguém opera.
    """
    alvo = normalizar(valor)
    for turno, opcoes in TURNOS.items():
        if alvo in opcoes and (validos is None or turno in validos):
            return turno
    return None


def converter_sim_nao(valor: str):
    """True, False ou None quando a célula é ambígua.

    Cuidado com o vazio: `normalizar("?")` devolve "" porque a pontuação sai,
    e "" está na lista de negativos. Sem esta checagem, uma célula com "?" no
    campo de cadeirante virava "não" em silêncio — e o aluno perderia o
    veículo acessível sem ninguém ser avisado. Célula que tinha conteúdo e
    virou vazio é ambígua, não é negativa.
    """
    bruto = "" if valor is None else str(valor).strip()
    alvo = normalizar(bruto)
    if alvo in AFIRMATIVOS:
        return True
    if alvo == "" and bruto != "":
        return None
    if alvo in NEGATIVOS:
        return False
    return None


# ------------------------------------------------------------- importação ---
class Importacao:
    """Resultado da importação: alunos, problemas e resumo."""

    def __init__(self):
        self.alunos = []
        self.problemas = []
        self.colunas = {}
        self.cofre = {}

    def problema(self, linha, campo, valor, descricao, sugestao, gravidade="erro"):
        self.problemas.append({
            "linha": linha, "campo": campo, "valor": valor,
            "problema": descricao, "sugestao": sugestao, "gravidade": gravidade,
        })

    def resumo(self) -> dict:
        erros = [p for p in self.problemas if p["gravidade"] == "erro"]
        avisos = [p for p in self.problemas if p["gravidade"] == "aviso"]
        return {
            "alunos_importados": len(self.alunos),
            "erros": len(erros),
            "avisos": len(avisos),
            "precisam_ajuste_no_mapa": sum(
                1 for a in self.alunos if a["precisa_ajuste_no_mapa"]),
            "colunas_detectadas": self.colunas,
            "por_turno": self._contar("turno"),
            "por_escola": self._contar("escola"),
            "cadeirantes": sum(1 for a in self.alunos if a["cadeirante"]),
            "acompanhantes": sum(1 for a in self.alunos if a["acompanhante"]),
        }

    def _contar(self, campo) -> dict:
        contagem = {}
        for a in self.alunos:
            contagem[a[campo]] = contagem.get(a[campo], 0) + 1
        return contagem


def importar(caminho: str, referencias: dict = None, guardar_nomes: bool = False,
             limites=None, turnos_validos=None) -> Importacao:
    """Lê a planilha e devolve a demanda pronta para o motor.

    `referencias`: {bairro_normalizado: (lat, lon)} — o ponto de referência
    usado quando não há coordenada na planilha.
    `guardar_nomes`: só ligue se o município exigir a lista nominal; o padrão
    é descartar o nome depois de gerar o pseudônimo.
    `limites`: (lat_min, lat_max, lon_min, lon_max) para pegar coordenada
    trocada de lugar ou digitada errada.
    `turnos_validos`: os turnos que a operação tem (vêm do perfil). Sem isso,
    "T1" de uma planilha de fábrica viraria turno numa operação escolar.
    """
    referencias = {normalizar(k): v for k, v in (referencias or {}).items()}
    resultado = Importacao()

    linhas = ler(caminho)
    if not linhas:
        resultado.problema(0, "arquivo", "", "A planilha está vazia.",
                           "Confira se a aba certa foi enviada.")
        return resultado

    inicio = _achar_cabecalho(linhas)
    resultado.colunas = detectar_colunas(linhas[inicio])
    if "nome" not in resultado.colunas and "endereco" not in resultado.colunas:
        resultado.problema(
            inicio + 1, "cabecalho", ";".join(linhas[inicio][:6]),
            "Não reconheci as colunas da planilha.",
            "O cabeçalho precisa ter pelo menos uma coluna de nome do aluno e "
            "uma de endereço. Aceito variações como 'aluno', 'estudante', "
            "'logradouro', 'rua'.")
        return resultado

    vistos = {}
    for numero_linha, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        if not any((c or "").strip() for c in linha):
            continue                              # linha em branco no meio
        aluno = _converter_linha(linha, numero_linha, resultado, referencias,
                                 limites, turnos_validos)
        if aluno is None:
            continue
        chave = aluno["id"]
        if chave in vistos:
            resultado.problema(
                numero_linha, "duplicado", aluno["endereco_original"],
                f"Aluno repetido (já aparece na linha {vistos[chave]}).",
                "Mantive só a primeira ocorrência. Se forem pessoas "
                "diferentes com o mesmo nome, acrescente algo que as "
                "distinga (data de nascimento ou matrícula).", "aviso")
            continue
        vistos[chave] = numero_linha
        resultado.alunos.append(aluno)
        nome_do_aluno = aluno.pop("_nome", None)
        if guardar_nomes and nome_do_aluno:
            resultado.cofre[aluno["id"]] = nome_do_aluno
    return resultado


def _converter_linha(linha, numero_linha, resultado, referencias, limites,
                     turnos_validos=None):
    def campo(nome):
        indice = resultado.colunas.get(nome)
        if indice is None or indice >= len(linha):
            return ""
        return (linha[indice] or "").strip()

    nome = campo("nome")
    endereco = " ".join(x for x in (campo("endereco"), campo("numero")) if x)
    bairro = campo("bairro")

    if not nome and not endereco:
        resultado.problema(numero_linha, "linha", "",
                           "Linha sem nome e sem endereço.",
                           "Provavelmente é um rodapé ou total; conferir.",
                           "aviso")
        return None

    turno = converter_turno(campo("turno"), turnos_validos)
    if turno is None:
        padrao = (turnos_validos or ["manha"])[0]
        aceitos = ", ".join(turnos_validos) if turnos_validos else \
            "manhã, tarde ou noite (aceito também matutino, vespertino, M, T, N)"
        resultado.problema(
            numero_linha, "turno", campo("turno"),
            "Turno não reconhecido.",
            f"Turnos desta operação: {aceitos}. Assumi “{padrao}” para não "
            f"perder a pessoa — confira.", "aviso")
        turno = padrao

    cadeirante = converter_sim_nao(campo("cadeirante"))
    if cadeirante is None and campo("cadeirante"):
        resultado.problema(
            numero_linha, "cadeirante", campo("cadeirante"),
            "Não entendi se o aluno usa cadeira de rodas.",
            "Use sim/não, S/N ou X. Assumi que NÃO — confira, porque isso "
            "muda o tipo de veículo da rota.", "erro")
    cadeirante = bool(cadeirante)

    lat, lon = _numero(campo("latitude")), _numero(campo("longitude"))
    origem, ajuste = "planilha", False

    if lat is not None and lon is not None and limites:
        lat_min, lat_max, lon_min, lon_max = limites
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            if (lat_min <= lon <= lat_max and lon_min <= lat <= lon_max):
                lat, lon = lon, lat        # latitude e longitude trocadas
                resultado.problema(
                    numero_linha, "coordenada", f"{lon}, {lat}",
                    "Latitude e longitude estavam trocadas.",
                    "Corrigi automaticamente — confira no mapa.", "aviso")
            else:
                resultado.problema(
                    numero_linha, "coordenada", f"{lat}, {lon}",
                    "Coordenada fora do município.",
                    "Usei o ponto de referência do bairro; ajuste no mapa.",
                    "erro")
                lat = lon = None

    if lat is None or lon is None:
        referencia = referencias.get(normalizar(bairro))
        if referencia:
            lat, lon = referencia
            origem, ajuste = "referencia_do_bairro", True
            resultado.problema(
                numero_linha, "endereco", endereco or bairro,
                "Endereço sem coordenada.",
                f"Usei o ponto de referência de “{bairro}”. Arraste o ponto "
                f"no mapa para a posição certa antes de publicar a rota.",
                "aviso")
        else:
            resultado.problema(
                numero_linha, "endereco", endereco or bairro,
                "Endereço sem coordenada e bairro desconhecido.",
                "Preencha latitude/longitude, ou informe um bairro que já "
                "tenha ponto de referência cadastrado.", "erro")
            return None

    return {
        "id": pseudonimo(nome, endereco, bairro),
        "_nome": nome,
        "turno": turno,
        "escola": campo("escola") or "(não informada)",
        "bairro": bairro,
        "endereco_original": endereco,
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "origem_da_coordenada": origem,
        "precisa_ajuste_no_mapa": ajuste,
        "cadeirante": cadeirante,
        "acompanhante": bool(converter_sim_nao(campo("acompanhante"))),
        "linha_planilha": numero_linha,
    }
