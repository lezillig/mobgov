# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 15 · agent-saude
API do app do paciente e da fila de retorno.

    GET  /                    o app do paciente
    GET  /api/minha-viagem    a viagem de hoje (paciente + token; ?dia= vê outro)
    POST /api/nao-vou         "hoje eu não vou" — libera a vaga
    POST /api/desfazer        "na verdade eu vou"
    POST /api/liberado        "o médico me liberou" — chama o carro da volta
    GET  /api/fila-de-retorno quem está esperando o carro (despachante)

Três decisões que valem a pena registrar:

* **o token amarra o paciente.** Não é autenticação forte — é o mínimo para
  o vizinho não ver o transporte do outro trocando o `?paciente=` da URL. No
  vertical de saúde isso importa mais: o dado do outro lado é mais sensível;

* **tudo vira evento no mesmo registro append-only** de `operacao/`. A trilha
  do transporte é uma só, e é ela que o tribunal de contas lê;

* **"não vou" é sempre aceito**, mesmo em cima da hora. O que muda é o que a
  tela promete: perto da saída ele não libera mais vaga, mas continua
  poupando a parada do motorista — e continua alimentando a taxa de ausência
  que o aprendizado usa.

    python -m saude.servidor
    python -m saude.servidor --porta 8070
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from operacao import registro  # noqa: E402
from saude import acompanhamento as ac  # noqa: E402
from saude import demanda as demanda_mod  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "app_paciente.html")


class Paciente(BaseHTTPRequestHandler):
    server_version = "MOBGOV-Saude/0.1"

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

    def _consulta(self) -> dict:
        bruto = parse_qs(urlparse(self.path).query)
        return {k: v[0] for k, v in bruto.items()}

    def _autorizado(self, campos: dict):
        """Devolve o paciente autorizado, ou None (e já respondeu 401)."""
        paciente = campos.get("paciente", "")
        if not paciente:
            self._json({"erro": "Informe o código do paciente."}, 400)
            return None
        if not registro.token_de_paciente_valido(paciente,
                                                 campos.get("token", "")):
            self._json({"erro": "Este link não é válido para este paciente."},
                       401)
            return None
        return paciente

    # --------------------------------------------------------------- rotas
    def do_GET(self):
        rota = urlparse(self.path)
        if rota.path in ("/", "/index.html", "/paciente"):
            with open(APP, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8")

        if rota.path == "/api/minha-viagem":
            campos = self._consulta()
            paciente = self._autorizado(campos)
            if paciente is None:
                return None
            # `dia` é opcional e serve para o paciente ver o próximo
            # atendimento sem esperar chegar o dia — pergunta que a
            # secretaria recebe por telefone toda semana
            dados = ac.situacao(paciente, dia=campos.get("dia") or None)
            dados["demonstracao"] = True
            return self._json(dados)

        if rota.path == "/api/fila-de-retorno":
            return self._json(ac.fila_de_retorno())

        if rota.path == "/api/pacientes":
            # modo demonstração: os links prontos, para abrir no celular
            tratamentos = demanda_mod.gerar_tratamentos()[:12]
            return self._json({"pacientes": [
                {"paciente": t.paciente_id, "tratamento": t.tipo,
                 "token": registro.token_do_paciente(t.paciente_id)}
                for t in tratamentos]})

        self._json({"erro": "Rota não encontrada.",
                    "rotas": ["/", "/api/minha-viagem", "/api/nao-vou",
                              "/api/desfazer", "/api/liberado",
                              "/api/fila-de-retorno"]}, 404)

    do_HEAD = do_GET

    def do_POST(self):
        rota = urlparse(self.path)
        acoes = {"/api/nao-vou": "nao_vou", "/api/desfazer": "confirmado",
                 "/api/liberado": "liberado"}
        if rota.path not in acoes:
            return self._json({"erro": "Rota não encontrada."}, 404)

        campos = self._consulta()
        paciente = self._autorizado(campos)
        if paciente is None:
            return None
        try:
            evento = registro.registrar({"tipo": acoes[rota.path],
                                         "paciente": paciente,
                                         "origem": "app do paciente"})
        except registro.ErroDeRegistro as erro:
            return self._json({"erro": str(erro)}, 400)
        return self._json({"ok": True, "evento": evento})

    def log_message(self, formato, *args):
        sys.stderr.write("[saude] %s\n" % (formato % args))


def main(argv=None):
    ap = argparse.ArgumentParser(description="App do paciente")
    ap.add_argument("--porta", type=int, default=8070)
    a = ap.parse_args(argv)
    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Paciente)
    exemplo = demanda_mod.gerar_tratamentos()[0]
    print(f"App do paciente em http://127.0.0.1:{a.porta}/"
          f"?paciente={exemplo.paciente_id}"
          f"&token={registro.token_do_paciente(exemplo.paciente_id)}")
    print(f"Fila de retorno em  http://127.0.0.1:{a.porta}/api/fila-de-retorno")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
