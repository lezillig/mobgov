# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-apps
Leitor de `multipart/form-data` — o envio de arquivo do navegador.

Por que escrito à mão: o módulo `cgi` da biblioteca padrão, que fazia isso,
foi removido do Python 3.13, e o projeto não instala dependência para o
servidor (a regra é a demo subir em máquina de prefeitura). São cinquenta
linhas, e o formato é estável desde 1998.

O que ele protege, além de separar os campos:

* **limite de tamanho** — planilha de município grande tem alguns MB; um POST
  de 2 GB não pode derrubar o servidor da secretaria;
* **nome de arquivo saneado** — o navegador manda o nome que o usuário tem no
  disco, e ele pode conter `../`. O que sai daqui já vem sem caminho.
"""
from __future__ import annotations

import os
import re

TAMANHO_MAXIMO = 25 * 1024 * 1024      # 25 MB: planilha de município grande


class ErroDeEnvio(ValueError):
    pass


def _fronteira(tipo_conteudo: str) -> bytes:
    achado = re.search(r'boundary="?([^";]+)"?', tipo_conteudo or "")
    if not achado:
        raise ErroDeEnvio("Envio sem fronteira (boundary) no cabeçalho.")
    return achado.group(1).encode("utf-8")


def nome_seguro(nome: str) -> str:
    """Tira caminho e caracteres estranhos — o nome vem do disco de alguém."""
    nome = os.path.basename((nome or "").replace("\\", "/")).strip()
    nome = re.sub(r"[^A-Za-z0-9._ ()-]", "_", nome)
    return nome[:120] or "planilha"


def analisar(corpo: bytes, tipo_conteudo: str) -> dict:
    """{campo: str} para texto e {campo: {"nome", "conteudo"}} para arquivo."""
    if len(corpo) > TAMANHO_MAXIMO:
        raise ErroDeEnvio(
            f"Arquivo grande demais ({len(corpo) // (1024 * 1024)} MB). "
            f"O limite é {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
    fronteira = _fronteira(tipo_conteudo)
    partes = corpo.split(b"--" + fronteira)
    campos = {}
    for parte in partes:
        parte = parte.strip(b"\r\n")
        if not parte or parte == b"--":
            continue
        cabecalho, _, conteudo = parte.partition(b"\r\n\r\n")
        texto_cabecalho = cabecalho.decode("utf-8", "replace")
        nome = re.search(r'name="([^"]*)"', texto_cabecalho)
        if not nome:
            continue
        arquivo = re.search(r'filename="([^"]*)"', texto_cabecalho)
        conteudo = conteudo.rstrip(b"\r\n")
        if arquivo and arquivo.group(1):
            campos[nome.group(1)] = {"nome": nome_seguro(arquivo.group(1)),
                                     "conteudo": conteudo}
        else:
            campos[nome.group(1)] = conteudo.decode("utf-8", "replace")
    return campos
