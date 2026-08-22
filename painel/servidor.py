# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 2 · agent-painel
Servidor mínimo do painel, só com a biblioteca padrão do Python.

O contrato de API já é o que o front definitivo (React) e o agent-conversa vão
consumir; quando o backend virar FastAPI, estas mesmas funções de `economia.py`
são reaproveitadas sem alteração.

    GET /                       painel HTML (aceita ?diesel=7.20&dias=20)
    GET /api/economia           indicadores antes/depois + memória de cálculo
    GET /api/cenarios           grade de cenários pré-calculados
    GET /api/aprendizado        série "o que o sistema aprendeu"
    GET /api/relatorio          relatório bruto do motor de dimensionamento

Uso:
    python -m painel.servidor --porta 8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from . import economia as economia_mod
    from . import aprendizado as aprendizado_mod
    from . import render as render_mod
except ImportError:  # execução direta: python painel/servidor.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from painel import economia as economia_mod
    from painel import aprendizado as aprendizado_mod
    from painel import render as render_mod


class Painel(BaseHTTPRequestHandler):
    relatorio = economia_mod.RELATORIO_PADRAO
    server_version = "MOBGOV-Painel/0.2"

    # ------------------------------------------------------------ utilidades
    def _responder(self, corpo: bytes, tipo: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, dados, status: int = 200):
        corpo = json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8")
        self._responder(corpo, "application/json; charset=utf-8", status)

    def _parametros(self, q: dict):
        def numero(nome, conv):
            if nome in q and q[nome] and q[nome][0].strip():
                try:
                    return conv(q[nome][0].replace(",", "."))
                except ValueError:
                    raise ValueError(f"Parâmetro '{nome}' inválido: {q[nome][0]}")
            return None
        return numero("diesel", float), numero("dias", int)

    def _painel(self, diesel, dias, com_cenarios=True):
        rel = economia_mod.carregar_relatorio(self.relatorio)
        premissas = economia_mod.premissas_do_relatorio(rel).substituir(
            preco_diesel_l=diesel, dias_letivos_mes=dias)
        return economia_mod.montar_painel(rel, premissas, com_cenarios=com_cenarios)

    # ----------------------------------------------------------------- rotas
    def do_GET(self):
        rota = urlparse(self.path)
        q = parse_qs(rota.query)
        try:
            diesel, dias = self._parametros(q)
        except ValueError as erro:
            return self._json({"erro": str(erro)}, 400)

        try:
            if rota.path in ("/", "/painel", "/index.html"):
                html, _ = render_mod.montar_html(self.relatorio, diesel, dias)
                return self._responder(html.encode("utf-8"),
                                       "text/html; charset=utf-8")
            if rota.path == "/api/economia":
                return self._json(self._painel(diesel, dias, com_cenarios=False))
            if rota.path == "/api/cenarios":
                return self._json(self._painel(diesel, dias)["cenarios"])
            if rota.path == "/api/aprendizado":
                return self._json(aprendizado_mod.carregar_serie())
            if rota.path == "/api/relatorio":
                return self._json(economia_mod.carregar_relatorio(self.relatorio))
        except FileNotFoundError:
            return self._json(
                {"erro": "Relatório de dimensionamento não encontrado. "
                         "Rode antes: python motor/dimensionar.py"}, 503)

        self._json({"erro": "Rota não encontrada",
                    "rotas": ["/", "/api/economia", "/api/cenarios",
                              "/api/aprendizado", "/api/relatorio"]}, 404)

    do_HEAD = do_GET

    def log_message(self, formato, *args):  # log enxuto em pt-BR
        sys.stderr.write("[painel] %s\n" % (formato % args))


def main():
    ap = argparse.ArgumentParser(description="Servidor do painel de economia")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 para apresentar em outra máquina da sala")
    ap.add_argument("--relatorio", default=economia_mod.RELATORIO_PADRAO)
    a = ap.parse_args()
    Painel.relatorio = a.relatorio
    servidor = ThreadingHTTPServer((a.host, a.porta), Painel)
    print(f"Painel de economia em http://{a.host}:{a.porta}/  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.server_close()


if __name__ == "__main__":
    main()
