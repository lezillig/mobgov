# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-comercial
Importa a planilha das linhas que a empresa opera HOJE.

É a fonte do "antes" do diagnóstico, e precisa ser dado, não estimativa. A
planilha existe em toda operadora, com nomes diferentes: "quadro de linhas",
"escala de rotas", "programação". As colunas essenciais são cinco:

    linha        o código que a operação usa para chamar a rota
    turno        a que turno ela atende
    destino      planta, unidade, escola
    veículo      o tipo (ou o prefixo, de onde se deduz o tipo)
    km/dia       quilometragem rodada por dia
    passageiros  quantos embarcam de fato — não quantos estão cadastrados

O último é o que costuma faltar, e é o mais importante: sem passageiros
transportados não há como falar em ocupação, e sem ocupação não há
diagnóstico. Quando a coluna não vem, o importador avisa em vez de supor.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.planilha import ler, numero_br  # noqa: E402

SINONIMOS = {
    "linha": ["linha", "rota", "codigo", "codigo da linha", "id", "roteiro",
              "itinerario", "servico"],
    "turno": ["turno", "periodo", "horario", "turno de trabalho", "escala"],
    "destino": ["destino", "planta", "unidade", "escola", "fabrica", "filial",
                "local de trabalho", "cliente"],
    "tipo": ["tipo", "tipo de veiculo", "veiculo", "modelo", "categoria",
             "frota"],
    "km_dia": ["km dia", "km/dia", "km por dia", "quilometragem",
               "quilometragem diaria", "km diario", "km"],
    "passageiros": ["passageiros", "passageiros transportados", "embarques",
                    "colaboradores", "alunos", "usuarios", "media de embarques",
                    "transportados"],
    "cadeirantes": ["cadeirantes", "pcd", "cadeira de rodas", "acessibilidade"],
}


def _normalizar(texto) -> str:
    sem = unicodedata.normalize("NFKD", str(texto or ""))
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9/ ]", " ", sem.lower())


def _limpo(texto) -> str:
    return re.sub(r"\s+", " ", _normalizar(texto)).strip()


def detectar_colunas(cabecalho: list) -> dict:
    titulos = [_limpo(c) for c in cabecalho]
    colunas = {}
    for campo, opcoes in SINONIMOS.items():
        for i, titulo in enumerate(titulos):
            if not titulo or i in colunas.values():
                continue
            if titulo in opcoes or any(titulo.startswith(o + " ")
                                       for o in opcoes):
                colunas[campo] = i
                break
    return colunas


def _achar_cabecalho(linhas: list, limite: int = 10) -> int:
    melhor, pontos = 0, -1
    for i, linha in enumerate(linhas[:limite]):
        atual = len(detectar_colunas(linha))
        if atual > pontos:
            melhor, pontos = i, atual
    return melhor


def _numero(texto):
    return numero_br(texto)


def _tipo_do_veiculo(texto: str, tipos: dict):
    """Casa o que está escrito na planilha com um tipo do perfil.

    Aceita o id ("RODO46"), o nome ("Ônibus rodoviário 46 lugares") e o jeito
    que a operação escreve ("onibus 46", "van"). Sem casar, a linha é
    devolvida como ignorada — melhor perder uma linha do diagnóstico do que
    diagnosticar a linha errada.
    """
    alvo = _limpo(texto)
    if not alvo:
        return None
    for tipo_id, tipo in tipos.items():
        if alvo == _limpo(tipo_id) or alvo == _limpo(tipo["nome"]):
            return tipo_id
    for tipo_id, tipo in tipos.items():
        capacidade = str(tipo["capacidade"])
        primeira = _limpo(tipo["nome"]).split()[0]
        if capacidade in alvo and primeira in alvo:
            return tipo_id
    for tipo_id, tipo in tipos.items():
        if _limpo(tipo["nome"]).split()[0] in alvo:
            return tipo_id
    return None


def importar(caminho: str, tipos: dict) -> dict:
    """Lê a planilha de linhas e devolve o que o diagnóstico consome."""
    linhas_planilha = ler(caminho)
    if not linhas_planilha:
        return {"linhas": [], "problemas": ["A planilha está vazia."],
                "colunas": {}}

    inicio = _achar_cabecalho(linhas_planilha)
    colunas = detectar_colunas(linhas_planilha[inicio])
    problemas = []
    if "linha" not in colunas or "tipo" not in colunas:
        return {"linhas": [], "colunas": colunas, "problemas": [
            "Não reconheci as colunas da planilha de linhas. O mínimo é uma "
            "coluna com o código da linha e outra com o tipo de veículo; "
            "km/dia e passageiros transportados são o que permite calcular "
            "ocupação e economia."]}
    if "passageiros" not in colunas:
        problemas.append(
            "A planilha não traz quantos passageiros cada linha transporta. "
            "Sem isso não dá para falar em ocupação — e é justamente aí que "
            "mora a economia de uma operação existente.")

    def campo(linha, nome):
        indice = colunas.get(nome)
        if indice is None or indice >= len(linha):
            return ""
        return str(linha[indice] or "").strip()

    resultado = []
    for numero_linha, bruta in enumerate(linhas_planilha[inicio + 1:],
                                         start=inicio + 2):
        if not any((c or "").strip() for c in bruta):
            continue
        codigo = campo(bruta, "linha")
        if not codigo:
            continue
        tipo_id = _tipo_do_veiculo(campo(bruta, "tipo"), tipos)
        if tipo_id is None:
            problemas.append(
                f"Linha {numero_linha}: não reconheci o veículo "
                f"“{campo(bruta, 'tipo')}”. Ela ficou fora do diagnóstico.")
            continue
        resultado.append({
            "linha": codigo,
            "turno": campo(bruta, "turno") or "único",
            "destino": campo(bruta, "destino") or "não informado",
            "tipo": tipo_id,
            "km_dia": _numero(campo(bruta, "km_dia")) or 0.0,
            "passageiros": _numero(campo(bruta, "passageiros")) or 0.0,
            "cadeirantes": _numero(campo(bruta, "cadeirantes")) or 0.0,
            "linha_planilha": numero_linha,
        })
    return {"linhas": resultado, "colunas": colunas, "problemas": problemas}
