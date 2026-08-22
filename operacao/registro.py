# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-apps
Registro de operação: o que o app do motorista manda de volta.

Três tipos de evento, todos gravados em um arquivo append-only
(`relatorios/operacao/eventos.jsonl`):

    ping        posição do veículo (GPS), com o horário do aparelho
    embarque    aluno embarcou ou desembarcou numa parada
    imprevisto  veículo quebrou, estrada fechada, aluno faltou

Append-only não é preguiça: é trilha de auditoria. Um evento que chega
atrasado (o app estava sem sinal e sincronizou depois) entra no fim do
arquivo com o horário em que ACONTECEU, e nada é reescrito. Para o tribunal
de contas, poder reconstruir o dia na ordem certa vale mais do que ter a
tabela bonitinha.

LGPD: o aluno aparece pelo pseudônimo que o importador gerou. O app do
motorista mostra nome (ele precisa saber quem está subindo), mas o que sai do
aparelho e entra no histórico é o pseudônimo.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime

DIR_OPERACAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "operacao")
ARQUIVO_EVENTOS = os.path.join(DIR_OPERACAO, "eventos.jsonl")

TIPOS_DO_MOTORISTA = ("ping", "embarque", "desembarque", "imprevisto",
                      "inicio", "fim")
# O app do responsável é a origem da taxa de ausência — a única coisa do
# aprendizado que continuava estimada. "falta" é o aviso de que a criança não
# vai hoje; "volta_atras" é o responsável desdizendo o aviso, o que acontece
# bastante e precisa chegar antes de o veículo passar.
TIPOS_DO_RESPONSAVEL = ("falta", "volta_atras")
TIPOS = TIPOS_DO_MOTORISTA + TIPOS_DO_RESPONSAVEL
_trava = threading.Lock()


class ErroDeRegistro(ValueError):
    pass


# ------------------------------------------------------------------ token ---
def token_do_motorista(motorista: str, chave: str = None) -> str:
    """Token estável por motorista, derivado de uma chave do servidor.

    Não é autenticação forte — é o mínimo para o app não aceitar qualquer um
    postando ping no lugar do motorista. Autenticação de verdade entra com o
    backend definitivo; o que não podia era ficar sem nada e alguém achar que
    estava protegido.
    """
    chave = chave or os.environ.get("MOBGOV_CHAVE", "demonstracao")
    return hmac.new(chave.encode("utf-8"), motorista.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def token_valido(motorista: str, token: str, chave: str = None) -> bool:
    return hmac.compare_digest(token_do_motorista(motorista, chave), token or "")


def token_do_responsavel(aluno: str, ponto: str = "", turno: str = "",
                         chave: str = None) -> str:
    """Token da família, ligado ao aluno E ao ponto onde ele embarca.

    O prefixo "responsavel:" é o que impede um token de motorista de valer
    como token de família (e vice-versa) só porque o identificador coincidiu.
    Amarrar o ponto no token evita a outra brincadeira: trocar o ?ponto= da
    URL e sair vendo onde está o veículo de outra rota.
    """
    chave = chave or os.environ.get("MOBGOV_CHAVE", "demonstracao")
    semente = f"responsavel:{aluno}|{ponto}|{turno}"
    return hmac.new(chave.encode("utf-8"), semente.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def token_de_responsavel_valido(aluno: str, token: str, ponto: str = "",
                                turno: str = "", chave: str = None) -> bool:
    return hmac.compare_digest(
        token_do_responsavel(aluno, ponto, turno, chave), token or "")


# ---------------------------------------------------------------- eventos ---
def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def registrar(evento: dict, arquivo: str = None) -> dict:
    """Grava um evento. Devolve o evento como ficou gravado."""
    arquivo = arquivo or ARQUIVO_EVENTOS
    tipo = evento.get("tipo")
    if tipo not in TIPOS:
        raise ErroDeRegistro(
            f"Tipo de evento desconhecido: {tipo!r}. Esperado um de: "
            f"{', '.join(TIPOS)}.")
    if tipo in TIPOS_DO_RESPONSAVEL:
        if not evento.get("aluno"):
            raise ErroDeRegistro("Aviso da família sem identificação do aluno.")
    elif not evento.get("motorista"):
        raise ErroDeRegistro("Evento sem motorista.")

    gravado = dict(evento)
    # o horário do APARELHO é o que vale para reconstruir o dia; o do servidor
    # serve para saber quanto tempo o app ficou sem sinal
    gravado.setdefault("em", _agora())
    gravado["recebido_em"] = _agora()

    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    with _trava:
        with open(arquivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(gravado, ensure_ascii=False) + "\n")
    return gravado


def registrar_lote(eventos: list, arquivo: str = None) -> dict:
    """Sincronização do app: um lote de eventos guardados offline.

    Um evento inválido no meio não pode derrubar o lote inteiro — o motorista
    perderia o dia de trabalho. Os bons entram, os ruins voltam descritos.
    """
    aceitos, recusados = [], []
    for i, evento in enumerate(eventos):
        try:
            aceitos.append(registrar(evento, arquivo))
        except ErroDeRegistro as erro:
            recusados.append({"indice": i, "motivo": str(erro),
                              "evento": evento})
    return {"aceitos": len(aceitos), "recusados": recusados}


def ler_eventos(arquivo: str = None, motorista: str = None,
                tipo: str = None, aluno: str = None) -> list:
    arquivo = arquivo or ARQUIVO_EVENTOS
    if not os.path.exists(arquivo):
        return []
    eventos = []
    with open(arquivo, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue        # linha corrompida não invalida o histórico
            if motorista and evento.get("motorista") != motorista:
                continue
            if aluno and evento.get("aluno") != aluno:
                continue
            if tipo and evento.get("tipo") != tipo:
                continue
            eventos.append(evento)
    return eventos


def resumo(arquivo: str = None) -> dict:
    eventos = ler_eventos(arquivo)
    por_tipo, motoristas = {}, set()
    atrasos = []
    for e in eventos:
        por_tipo[e["tipo"]] = por_tipo.get(e["tipo"], 0) + 1
        motoristas.add(e.get("motorista"))
        try:
            em = datetime.strptime(e["em"], "%Y-%m-%dT%H:%M:%S")
            recebido = datetime.strptime(e["recebido_em"], "%Y-%m-%dT%H:%M:%S")
            atrasos.append((recebido - em).total_seconds())
        except (KeyError, ValueError):
            continue
    return {
        "eventos": len(eventos),
        "por_tipo": por_tipo,
        "motoristas": len([m for m in motoristas if m]),
        "atraso_medio_s": round(sum(atrasos) / len(atrasos), 1) if atrasos else 0,
        "atraso_maximo_s": round(max(atrasos), 1) if atrasos else 0,
    }
