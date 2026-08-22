# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 6 · agent-apps
Servidor de operação: serve o app do motorista e recebe o que ele manda.

    GET  /                      app do motorista (PWA offline-first)
    GET  /responsavel           app do responsável ("onde está o ônibus")
    GET  /api/motoristas        lista de motoristas do plano (modo demonstração)
    GET  /api/responsaveis      vínculos de exemplo (modo demonstração)
    GET  /api/rota-do-dia       rota do motorista (motorista + token)
    GET  /api/situacao          situação do aluno (aluno + ponto + token)
    POST /api/eventos           lote de eventos guardados no aparelho
    POST /api/falta             a família avisa que hoje não vai
    POST /api/desfazer-falta    a família desdiz o aviso
    GET  /api/faltas-do-dia     quem avisou falta hoje, por viagem
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

from operacao import onde_esta, registro, rota_do_dia as rotas

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "app_motorista.html")
APP_RESPONSAVEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "app_responsavel.html")
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

    def _vinculo(self, q) -> dict:
        """Devolve {aluno, ponto, turno} quando o token da família confere.

        O token assina os três juntos: trocar o ?ponto= na URL não vale, senão
        qualquer responsável veria a rota inteira do município.
        """
        aluno = (q.get("aluno") or [""])[0]
        ponto = (q.get("ponto") or [""])[0]
        turno = (q.get("turno") or [""])[0]
        token = (q.get("token") or [""])[0]
        if aluno and registro.token_de_responsavel_valido(aluno, token, ponto,
                                                          turno):
            return {"aluno": aluno, "ponto": ponto, "turno": turno}
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

        if rota.path in ("/responsavel", "/responsavel.html"):
            with open(APP_RESPONSAVEL, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8")

        if rota.path == "/api/responsaveis":
            if not self.modo_demonstracao:
                return self._json({"erro": "Disponível apenas em modo "
                                            "demonstração."}, 403)
            return self._json(vinculos_de_demonstracao(self.plano))

        if rota.path == "/api/situacao":
            vinculo = self._vinculo(q)
            if not vinculo:
                return self._json({"erro": "Aluno ou token inválido."}, 401)
            return self._json(onde_esta.situacao(
                vinculo, self.plano,
                registro.ler_eventos(self.arquivo_eventos)))

        if rota.path == "/api/faltas-do-dia":
            return self._json(onde_esta.faltas_do_dia(
                registro.ler_eventos(self.arquivo_eventos)))

        if rota.path == "/api/resumo":
            return self._json(registro.resumo(self.arquivo_eventos))

        self._json({"erro": "Rota não encontrada.",
                    "rotas": ["/", "/responsavel", "/api/motoristas",
                              "/api/rota-do-dia", "/api/situacao",
                              "/api/eventos", "/api/falta",
                              "/api/desfazer-falta", "/api/faltas-do-dia",
                              "/api/resumo"]}, 404)

    do_HEAD = do_GET

    def do_POST(self):
        rota = urlparse(self.path)
        q = parse_qs(rota.query)

        if rota.path in ("/api/falta", "/api/desfazer-falta"):
            vinculo = self._vinculo(q)
            if not vinculo:
                return self._json({"erro": "Aluno ou token inválido."}, 401)
            situacao = onde_esta.situacao(
                vinculo, self.plano, registro.ler_eventos(self.arquivo_eventos))
            viagem = situacao.get("viagem", "")
            if rota.path == "/api/falta":
                evento = onde_esta.avisar_falta(
                    vinculo["aluno"], vinculo["ponto"], viagem,
                    arquivo=self.arquivo_eventos)
            else:
                evento = onde_esta.desfazer_aviso(
                    vinculo["aluno"], vinculo["ponto"], viagem,
                    arquivo=self.arquivo_eventos)
            return self._json({"registrado": evento["tipo"],
                               "em": evento["em"], "viagem": viagem})

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


def vinculos_de_demonstracao(plano: dict, quantos: int = 5) -> list:
    """Links de exemplo para abrir o app do responsável na demonstração.

    Em produção o vínculo sai do cadastro (aluno ↔ ponto) e o link vai por
    SMS. Aqui ele é montado a partir do próprio plano, sem inventar aluno: o
    identificador é derivado do ponto, e não há nome nenhum envolvido.
    """
    frota = (plano or {}).get("frota_otimizada") or {}
    vinculos = []
    for viagem in frota.get("viagens", []):
        paradas = viagem.get("paradas") or []
        # primeira e uma do meio: na demonstração, a do meio é a que mostra a
        # previsão MEDIDA (já há embarque antes dela), e a primeira mostra o
        # horário de plano. As duas telas precisam aparecer.
        escolhidas = [p for p in (paradas[:1] + paradas[len(paradas) // 2:
                                                        len(paradas) // 2 + 1])]
        for ponto in dict.fromkeys(escolhidas):
            aluno = f"A{ponto}"
            vinculos.append({
                "aluno": aluno, "ponto": ponto, "turno": viagem["turno"],
                "escola": viagem["escola"],
                "token": registro.token_do_responsavel(aluno, ponto,
                                                       viagem["turno"]),
            })
        if len(vinculos) >= quantos:
            break
    return vinculos


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

    familias = vinculos_de_demonstracao(Operacao.plano)
    if familias and Operacao.modo_demonstracao:
        v = familias[0]
        print(f"App do responsável em http://{a.host}:{a.porta}/responsavel")
        print(f"  http://{a.host}:{a.porta}/responsavel?aluno={v['aluno']}"
              f"&ponto={v['ponto']}&turno={v['turno']}&token={v['token']}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.server_close()


if __name__ == "__main__":
    main()
