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

from dados.planilha import ErroDePlanilha, abas as listar_abas, ler

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
    "cep": ["cep", "codigo postal", "cep residencial"],
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

    A planilha real quase nunca escreve "manhã": escreve o horário da aula.
    Numa lista de 456 alunos de operação em produção, a coluna de turno tinha
    "07:00 às 12:20", "13:00 ás 18:20", "07h", "16:00:00" — vinte grafias, e
    nenhuma delas a palavra turno. Recusar isso jogava fora a planilha
    inteira, então o horário de entrada também vale como turno.
    """
    alvo = normalizar(valor)
    for turno, opcoes in TURNOS.items():
        if alvo in opcoes and (validos is None or turno in validos):
            return turno
    pelo_horario = _turno_do_horario(valor)
    if pelo_horario and (validos is None or pelo_horario in validos):
        return pelo_horario
    return None


def _turno_do_horario(valor: str):
    """Turno deduzido da hora de entrada, quando a célula traz um horário.

    Vale a PRIMEIRA hora da célula: "07:00 às 12:20" é aula de manhã que
    termina ao meio-dia, não aula de tarde. O corte às 11 h e às 17 h é o que
    separa os turnos numa escola brasileira — 12:20 é fim de manhã, 13:00 é
    começo de tarde.
    """
    if valor in (None, ""):
        return None
    texto = str(valor).strip().lower()
    casado = re.search(r"(\d{1,2})\s*(?::|h)", texto)
    if not casado:
        return None
    hora = int(casado.group(1))
    if hora > 23:
        return None
    if hora < 11:
        return "manha"
    return "tarde" if hora < 17 else "noite"


def chaves_de_cep(valor) -> list:
    """CEP em chaves de busca, do mais específico ao mais amplo.

    Duas armadilhas do arquivo real, as duas silenciosas:

    1. **o zero à esquerda some**. A célula é numérica, então o CEP 04416-200
       chega como 4416200. Sem completar com zero, a cidade inteira muda de
       região — a primeira leitura que fiz desses dados agrupou a zona sul de
       São Paulo como se fosse interior.
    2. o CEP vem com hífen, com ponto, com espaço ou com nada.

    Devolve ["04416200", "04416", "044"]: casa com a base de referência que o
    município tiver, seja ela por CEP exato, por logradouro ou por região.
    """
    digitos = re.sub(r"\D", "", str(valor or ""))
    if not digitos or len(digitos) > 8:
        return []
    completo = digitos.zfill(8)
    return [completo, completo[:5], completo[:3]]


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
        self.abas_lidas = []
        self.abas_ignoradas = []
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
            # planilha de secretaria costuma ter uma aba por região; dizer
            # quais entraram é o que impede metade da operação de sumir
            "abas_lidas": list(self.abas_lidas),
            "abas_ignoradas": list(self.abas_ignoradas),
        }

    def _contar(self, campo) -> dict:
        contagem = {}
        for a in self.alunos:
            contagem[a[campo]] = contagem.get(a[campo], 0) + 1
        return contagem


def importar(caminho: str, referencias: dict = None, guardar_nomes: bool = False,
             limites=None, turnos_validos=None, aba=None) -> Importacao:
    """Lê a planilha e devolve a demanda pronta para o motor.

    `referencias`: {bairro_normalizado: (lat, lon)} — o ponto de referência
    usado quando não há coordenada na planilha.
    `guardar_nomes`: só ligue se o município exigir a lista nominal; o padrão
    é descartar o nome depois de gerar o pseudônimo.
    `limites`: (lat_min, lat_max, lon_min, lon_max) para pegar coordenada
    trocada de lugar ou digitada errada.
    `turnos_validos`: os turnos que a operação tem (vêm do perfil). Sem isso,
    "T1" de uma planilha de fábrica viraria turno numa operação escolar.
    `aba`: por padrão lê TODAS as abas que tenham cara de lista de alunos.
    Passe um nome ou índice para restringir a uma só.
    """
    referencias = {normalizar(k): v for k, v in (referencias or {}).items()}
    resultado = Importacao()

    # Uma planilha de secretaria costuma ter UMA ABA POR REGIÃO ("Sul 1",
    # "Sul 2"). Ler só a primeira faz metade da operação sumir sem erro
    # nenhum — o pior tipo de defeito, porque só aparece quando falta veículo
    # na rua. Aqui todas as abas com cara de lista de alunos entram, e as que
    # ficaram de fora saem nomeadas no resumo.
    nomes_das_abas = listar_abas(caminho) or [None]
    if aba is not None:
        nomes_das_abas = [aba]

    vistos = {}
    for indice, nome_da_aba in enumerate(nomes_das_abas):
        alvo = nome_da_aba if nome_da_aba is not None else indice
        try:
            linhas = ler(caminho, alvo) if nome_da_aba is not None else ler(caminho)
        except ErroDePlanilha as erro:
            resultado.abas_ignoradas.append(
                {"aba": str(nome_da_aba), "motivo": str(erro)})
            continue
        _importar_aba(linhas, str(nome_da_aba or "única"), resultado, vistos,
                      referencias, limites, turnos_validos, guardar_nomes)

    if not resultado.alunos:
        # Não basta ignorar as abas em silêncio: quem mandou o arquivo precisa
        # ler numa frase por que nada entrou, e o que fazer a respeito.
        if resultado.abas_ignoradas:
            nomes = ", ".join(f"“{i['aba']}”" for i in resultado.abas_ignoradas)
            resultado.problema(
                0, "arquivo", nomes, "Nenhuma aba virou lista de alunos.",
                f"Olhei {nomes} e não achei cabeçalho com nome e endereço do "
                f"aluno. Confira se o cabeçalho está na planilha (pode estar "
                f"depois de mais de dez linhas de título) e se a aba certa "
                f"foi enviada.")
        elif not resultado.problemas:
            resultado.problema(0, "arquivo", "", "A planilha está vazia.",
                               "Confira se a aba certa foi enviada.")
    return resultado


def _importar_aba(linhas, nome_da_aba, resultado, vistos, referencias,
                  limites, turnos_validos, guardar_nomes):
    """Uma aba. Aba sem cara de lista de alunos é ignorada COM NOME."""
    if not linhas:
        resultado.abas_ignoradas.append(
            {"aba": nome_da_aba, "motivo": "aba vazia"})
        return

    inicio = _achar_cabecalho(linhas)
    colunas = detectar_colunas(linhas[inicio])
    if "nome" not in colunas and "endereco" not in colunas:
        resultado.abas_ignoradas.append({
            "aba": nome_da_aba,
            "motivo": "não tem coluna de nome nem de endereço — pode ser a "
                      "aba de frota, de contrato ou de anotações"})
        return
    resultado.colunas = colunas
    resultado.abas_lidas.append(nome_da_aba)
    antes_desta_aba = len(resultado.alunos)
    for numero_linha, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        if not any((c or "").strip() for c in linha):
            continue                              # linha em branco no meio
        aluno = _converter_linha(linha, numero_linha, resultado, referencias,
                                 limites, turnos_validos)
        if aluno is None:
            continue
        aluno["aba"] = nome_da_aba
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

    if len(resultado.alunos) == antes_desta_aba:
        resultado.abas_lidas.remove(nome_da_aba)
        resultado.abas_ignoradas.append({
            "aba": nome_da_aba,
            "motivo": "tem cabeçalho de lista de alunos, mas nenhuma linha "
                      "virou aluno"})


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
        # bairro primeiro; o CEP é o plano B de quem tem lista de endereço
        # urbano, onde ninguém escreve o bairro mas o CEP está sempre lá
        referencia, apoio = referencias.get(normalizar(bairro)), bairro
        if not referencia:
            for chave in chaves_de_cep(campo("cep")):
                referencia = referencias.get(chave)
                if referencia:
                    apoio = f"CEP {chave}"
                    break
        if referencia:
            lat, lon = referencia
            origem, ajuste = "referencia_do_bairro", True
            resultado.problema(
                numero_linha, "endereco", endereco or bairro,
                "Endereço sem coordenada.",
                f"Usei o ponto de referência de “{apoio}”. Arraste o ponto "
                f"no mapa para a posição certa antes de publicar a rota.",
                "aviso")
        else:
            resultado.problema(
                numero_linha, "endereco", endereco or bairro,
                "Endereço sem coordenada e bairro desconhecido.",
                "Preencha latitude/longitude, ou informe um bairro (ou um "
                "CEP) que já tenha ponto de referência cadastrado.", "erro")
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
