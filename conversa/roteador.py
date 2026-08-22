# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-conversa
Roteador offline: escolhe a ferramenta por palavra-chave, sem LLM.

Por que existe, se o assistente tem um modelo de linguagem? Porque a
demonstração acontece numa sala de prefeitura com wi-fi de visitante, e porque
nenhum piloto pode depender de crédito de API para responder "quanto eu
economizo". O roteador é o piso: entende as perguntas que o gestor realmente
faz, chama a mesma ferramenta que o LLM chamaria e devolve o mesmo número.

O LLM entra por cima disso, para entender pergunta torta e escrever melhor —
nunca para calcular.
"""
from __future__ import annotations

import re
import unicodedata

# Cada regra é (ferramenta, pesos por palavra). O peso separa o termo que
# decide (ex.: "importação") do termo que só ajuda (ex.: "planilha").
REGRAS = [
    ("simular_cenario", {
        "e se": 6, "simul": 5, "cenario": 5, "diesel a": 5, "subir": 3,
        "hipotese": 4, "supondo": 4, "caso o diesel": 5, "com quantos dias": 4,
    }),
    ("qualidade_da_importacao", {
        "importa": 6, "planilha": 4, "erro": 3, "aviso": 3, "cadastro": 3,
        "endereco": 3, "geocod": 4, "coordenada": 3,
    }),
    ("o_que_o_sistema_aprendeu", {
        "aprend": 6, "erro de previsao": 5, "melhorou": 3, "historico": 3,
        "modelo": 3, "rollback": 5, "acuracia": 4,
    }),
    ("estado_da_operacao", {
        "hoje": 4, "agora": 3, "operacao": 4, "falta": 4, "ausencia": 4,
        "motorista": 3, "reotimiz": 5, "atraso": 3, "imprevisto": 4,
        "em tempo real": 4,
    }),
    ("explicar_rota", {
        "rota": 4, "viagem": 4, "por que a rota": 6, "linha": 2, "parada": 3,
        "ponto de embarque": 4, "explica": 3, "escola": 2,
    }),
    ("dimensionar_frota", {
        "frota": 4, "quantos veiculos": 6, "quantos onibus": 6, "van": 3,
        "micro": 3, "composicao": 4, "dimensiona": 5, "por que preciso": 5,
        "tipo de veiculo": 4, "quantas viagens": 4,
    }),
    ("gerar_relatorio", {
        "relatorio": 5, "pdf": 5, "prestacao de contas": 6, "tribunal": 5,
        "gerar": 3, "imprimir": 4, "painel": 3, "documento": 3,
    }),
    ("consultar_indicadores", {
        "economia": 5, "economiz": 5, "quanto": 3, "custo": 4, "gasto": 4,
        "reais": 3, "por mes": 3, "por ano": 3, "co2": 4, "emissao": 4,
        "combustivel": 3, "litros": 4, "quilometr": 3, "km": 3, "numeros": 3,
        "resumo": 3,
    }),
]

# Ferramenta usada quando nada casa: é a manchete, e é a pergunta que o gestor
# faz em 8 de cada 10 demonstrações.
PADRAO = "consultar_indicadores"

_NUMERO = re.compile(r"(\d+(?:[.,]\d+)?)")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento — 'Ônibus' e 'onibus' têm que casar igual."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _argumentos_de_cenario(pergunta: str) -> dict:
    """Tira do texto o preço do diesel e os dias letivos, quando ditos.

    'e se o diesel for a 8,20?' -> {'preco_diesel': 8.2}
    'com 20 dias letivos'       -> {'dias_letivos': 20}
    """
    argumentos = {}
    diesel = re.search(r"diesel[^\d]{0,20}(\d+(?:[.,]\d+)?)", pergunta)
    if not diesel:
        diesel = re.search(r"r\$ ?(\d+(?:[.,]\d+)?)", pergunta)
    if diesel:
        argumentos["preco_diesel"] = float(diesel.group(1).replace(",", "."))
    dias = re.search(r"(\d{1,2}) ?dias", pergunta)
    if dias:
        argumentos["dias_letivos"] = int(dias.group(1))
    return argumentos


def _argumentos_de_rota(pergunta: str, original: str) -> dict:
    """Pega o id da viagem se ele estiver escrito (ex.: E1-manha-03)."""
    achado = re.search(r"\b([eE]\d+-[a-zA-Z]+-\d+)\b", original)
    return {"viagem": achado.group(1)} if achado else {}


def pontuar(pergunta: str) -> list:
    """Devolve [(ferramenta, pontos)] ordenado — útil para depurar e testar."""
    texto = normalizar(pergunta)
    placar = []
    for ferramenta, pesos in REGRAS:
        pontos = sum(peso for termo, peso in pesos.items() if termo in texto)
        if pontos:
            placar.append((ferramenta, pontos))
    placar.sort(key=lambda par: (-par[1], par[0]))
    return placar


def escolher(pergunta: str) -> tuple:
    """(nome_da_ferramenta, argumentos, confianca 0..1).

    A confiança serve para o assistente saber quando avisar que talvez tenha
    entendido errado — melhor dizer "achei que você quis dizer X" do que
    responder com cara de certeza sobre a pergunta errada.
    """
    texto = normalizar(pergunta)
    placar = pontuar(pergunta)
    if not placar:
        return PADRAO, {}, 0.0

    ferramenta, pontos = placar[0]
    segundo = placar[1][1] if len(placar) > 1 else 0
    # confiança cresce com a pontuação e com a distância para o segundo lugar
    confianca = min(1.0, round(pontos / 12.0 + (pontos - segundo) / 20.0, 2))

    argumentos = {}
    if ferramenta == "simular_cenario":
        argumentos = _argumentos_de_cenario(texto)
        if not argumentos:
            # "e se..." sem número nenhum não é cenário: é conversa
            ferramenta, confianca = PADRAO, 0.3
    elif ferramenta == "explicar_rota":
        argumentos = _argumentos_de_rota(texto, pergunta)
    return ferramenta, argumentos, max(0.0, confianca)
