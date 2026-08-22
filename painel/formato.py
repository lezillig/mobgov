# -*- coding: utf-8 -*-
"""Formatação numérica em português do Brasil, sem depender de locale
instalado no servidor (prefeitura/VPS costuma vir com locale mínimo)."""
from __future__ import annotations

import html


def numero(valor: float, casas: int = 0) -> str:
    """1234567.8 -> '1.234.567,8'"""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def reais(valor: float, casas: int = 0) -> str:
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {numero(abs(valor), casas)}"


def reais_curto(valor: float) -> str:
    """Para os cartões grandes do projetor: R$ 1,5 mi / R$ 125 mil."""
    a = abs(valor)
    sinal = "-" if valor < 0 else ""
    if a >= 1_000_000:
        return f"{sinal}R$ {numero(a / 1_000_000, 2)} mi"
    if a >= 1_000:
        return f"{sinal}R$ {numero(a / 1_000, 0)} mil"
    return f"{sinal}R$ {numero(a, 0)}"


def pct(valor: float, casas: int = 1) -> str:
    return f"{numero(valor, casas)}%"


def esc(texto) -> str:
    return html.escape(str(texto), quote=True)
