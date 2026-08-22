# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-apps
Servidor de operação: serve o app do motorista e recebe o que ele manda.

    GET  /                      app do motorista (PWA offline-first)
    GET  /api/motoristas        lista de motoristas do plano (modo demonstração)
    GET  /api/rota-do-dia       rota do motorista (motorista + token)
    POST /api/eventos           lote de eventos guardados no aparelho
    GET  /api/resumo            o que já chegou (para a central)

Biblioteca padrão, como o resto do sistema. O token é um HMAC simples por
motorista: não é autenticação de banco, é o mínimo para o aparelho de um não
postar ping no lugar do outro. Escuta em 127.0.0.1 por padrão — para testar no
celular do motorista, use `--host 0.0.0.0` numa rede em que isso faça sentido.

Uso:
    python -m operacao.servidor
    python -m operacao.servidor --host 0.0.0.0 --porta 8080
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from operacao import registro, rota_do_dia as rotas

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "app_motorista.html")
TAMANHO_MAXIMO = 2 * 1024 * 1024      # 2 MB de lote já é um dia inteiro offline


class Operacao(BaseHTTPRequestHandler):
    server_version = "MOBGOV-Operacao/0.6"
    arquivo_eventos = None
    plano = None
    modo_demonstracao = True

    # ------------------------------------------------------------ resposta
    def _responder(self, corpo: bytes, tipo: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, dados, status: int = 200):
        self._responder(json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", status)

    def _autorizado(self, q) -> str:
        """Devolve o motorista quando o token confere; senão, None."""
        motorista = (q.get("motorista") or [""])[0]
        token = (q.get("token") or [""])[0]
        if motorista and registro.token_valido(motorista, token):
            return motorista
        return None

    # --------------------------------------------------------------- rotas
    def do_GET(self):
        rota = urlparse(self.path)
        q = parse_qs(rota.query)

        if rota.path in ("/", "/app", "/index.html"):
            with open(APP, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8")

        if rota.path == "/api/motoristas":
            if not self.modo_demonstracao:
                return self._json({"erro": "Disponível apenas em modo "
                                            "demonstração."}, 403)
            lista = rotas.motoristas(self.plano)
            for m in lista:
                m["token"] = registro.token_do_motorista(m["motorista"])
            return self._json(lista)

        if rota.path == "/api/rota-do-dia":
            motorista = self._autorizado(q)
            if not motorista:
                return self._json({"erro": "Motorista ou token inválido."}, 401)
            rota_dia = rotas.rota_do_dia(motorista, self.plano)
            if not rota_dia:
                return self._json({"erro": f"Sem rota para {motorista} hoje.",
                                   "viagens": []}, 404)
            return self._json(rota_dia)

        if rota.path == "/api/resumo":
            return self._json(registro.resumo(self.arquivo_eventos))

        self._json({"erro": "Rota não encontrada.",
                    "rotas": ["/", "/api/motoristas", "/api/rota-do-dia",
                              "/api/eventos", "/api/resumo"]}, 404)

    do_HEAD = do_GET

    def do_POST(self):
        rota = urlparse(self.path)
        q = parse_qs(rota.query)
        if rota.path != "/api/eventos":
            return self._json({"erro": "Rota não encontrada."}, 404)

        motorista = self._autorizado(q)
        if not motorista:
            return self._json({"erro": "Motorista ou token inválido."}, 401)

        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > TAMANHO_MAXIMO:
            return self._json({"erro": "Lote grande demais."}, 413)
        try:
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"erro": "Corpo não é JSON válido."}, 400)

        eventos = corpo.get("eventos") if isinstance(corpo, dict) else None
        if not isinstance(eventos, list):
            return self._json({"erro": "Esperado {\"eventos\": [...]}"}, 400)

        # o motorista do token manda: o aparelho não escolhe por quem assina
        for e in eventos:
            if isinstance(e, dict):
                e["motorista"] = motorista
        resultado = registro.registrar_lote(eventos, self.arquivo_eventos)
        return self._json(resultado)

    def log_message(self, formato, *args):
        sys.stderr.write("[operacao] %s\n" % (formato % args))


def main():
    ap = argparse.ArgumentParser(description="Servidor de operação do MOBGOV")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sem-demonstracao", action="store_true",
                    help="esconde a lista de motoristas e seus tokens")
    a = ap.parse_args()

    Operacao.plano = rotas.carregar_plano()
    Operacao.modo_demonstracao = not a.sem_demonstracao
    servidor = ThreadingHTTPServer((a.host, a.porta), Operacao)

    lista = rotas.motoristas(Operacao.plano)
    print(f"App do motorista em http://{a.host}:{a.porta}/")
    if lista and Operacao.modo_demonstracao:
        primeiro = lista[0]
        token = registro.token_do_motorista(primeiro["motorista"])
        print(f"  {len(lista)} motoristas no plano. Para abrir como "
              f"{primeiro['motorista']}:")
        print(f"  http://{a.host}:{a.porta}/?motorista={primeiro['motorista']}"
              f"&token={token}")
    else:
        print("  Nenhum plano encontrado — rode antes: python motor/dimensionar.py")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.server_close()


if __name__ == "__main__":
    main()
