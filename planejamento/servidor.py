# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-apps
A TELA DA ROTEIRIZAÇÃO: sobe a planilha, confere, ajusta e publica.

Este é o caminho que a secretaria percorre para tirar o transporte do papel:

    1. enviar a planilha        (o arquivo que ela já tem, do jeito que está)
    2. conferir o que entrou    (erro e aviso linha a linha, com o que fazer)
    3. ajustar no mapa          (endereço sem coordenada vira ponto arrastável)
    4. roteirizar               (o motor roda de verdade, com progresso na tela)
    5. publicar                 (o plano vira a rota que o motorista vê no app)

Regras que valem aqui como valem no resto do sistema:

* nada é publicado por acidente — roteirizar e publicar são dois botões, e o
  segundo diz em quantos veículos e quantas viagens ele vai mexer;
* o "antes" não é inventado: sem a frota atual informada, o plano sai sem
  comparação e a tela explica o que falta;
* aluno que não cabe em rota nenhuma dentro do limite aparece na tela como
  decisão da secretaria, não some.

    python -m planejamento.servidor
    python -m planejamento.servidor --porta 8090
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comercial import diagnostico as diagnostico_mod  # noqa: E402
from comercial import operacao_atual as operacao_mod  # noqa: E402
from comercial import precificacao as precificacao_mod  # noqa: E402
from comercial import proposta as proposta_mod  # noqa: E402
from dados import perfis as perfis_mod  # noqa: E402
from dados.planilha import ErroDePlanilha  # noqa: E402
from motor import planejar as planejar_mod  # noqa: E402
from planejamento import multipart  # noqa: E402

TELA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tela.html")
DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_RELATORIOS = os.path.join(DIR_BASE, "relatorios")
DIR_TRABALHO = os.path.join(DIR_RELATORIOS, "planejamento")


class Estado:
    """O rascunho do planejamento — vive enquanto o servidor está de pé.

    Guardado também em disco: se a secretaria fechar o navegador no meio da
    conferência, o trabalho de ajustar cem endereços no mapa não pode sumir.
    """

    def __init__(self):
        self.importacao = None
        self.plano = None
        self.progresso = []
        self.rodando = False
        self.erro = ""
        self.perfil = perfis_mod.PERFIL_ESCOLAR
        self.linhas_atuais = None       # o quadro de linhas que já roda hoje
        self.preco = None
        self.diagnostico = None
        self.trava = threading.Lock()

    # ------------------------------------------------------------ persistência
    def salvar(self):
        os.makedirs(DIR_TRABALHO, exist_ok=True)
        if self.importacao:
            with open(os.path.join(DIR_TRABALHO, "rascunho.json"), "w",
                      encoding="utf-8") as f:
                json.dump(self.importacao, f, ensure_ascii=False)

    def recuperar(self):
        caminho = os.path.join(DIR_TRABALHO, "rascunho.json")
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                self.importacao = json.load(f)

    # ------------------------------------------------------------------ etapas
    def anotar(self, etapa: str, detalhe: str = ""):
        with self.trava:
            self.progresso.append({
                "etapa": etapa, "detalhe": detalhe,
                "em": datetime.now().strftime("%H:%M:%S")})

    def perfil_em_dicionario(self) -> dict:
        perfil = self.perfil
        return {
            "id": perfil.id, "nome": perfil.nome, "vertical": perfil.vertical,
            "rotulo_passageiro_plural": perfil.rotulo_passageiro_plural,
            "rotulo_destino_plural": perfil.rotulo_destino_plural,
            "separa_custo_do_motorista": perfil.separa_custo_do_motorista,
            "tempo_max_trajeto_min": perfil.tempo_max_trajeto_min,
            "fator_tempo_bordo": perfil.fator_tempo_bordo,
            "folga_tempo_bordo_min": perfil.folga_tempo_bordo_min,
            "turnos": [{"id": t.id, "nome": t.nome} for t in perfil.turnos],
            # a frota disponível, inteira: é aqui que se cadastra o tipo de
            # veículo que a operação pode usar, e o solver não usa nenhum tipo
            # que não esteja nesta lista
            "tipos_veiculo": [{"id": t.id, "nome": t.nome,
                               "capacidade": t.capacidade,
                               "posicoes_cadeirante": t.posicoes_cadeirante,
                               "custo_km": t.custo_km,
                               "custo_fixo_mes": t.custo_fixo_mes,
                               "consumo_km_l": t.consumo_km_l}
                              for t in perfil.tipos_veiculo],
        }

    # ------------------------------------------------------------- parâmetros
    def gravar_perfil(self, dados: dict) -> dict:
        """Salva o perfil editado na tela e passa a usá-lo.

        Vai para arquivo porque parâmetro de operação sobrevive ao processo:
        quem cadastrou a frota na sexta não recadastra na segunda.
        """
        # `de_dicionario` trata lista vazia como "não configurado" e devolve o
        # catálogo padrão — o que é certo para um JSON parcial e errado aqui:
        # apagar todos os tipos na tela é uma decisão, não uma omissão.
        if "tipos_veiculo" in dados and not dados["tipos_veiculo"]:
            raise ValueError("A operação precisa de pelo menos um tipo de "
                             "veículo cadastrado.")
        perfil = perfis_mod.de_dicionario(dados)
        if not perfil.tipos_veiculo:
            raise ValueError("A operação precisa de pelo menos um tipo de "
                             "veículo cadastrado.")
        if perfil.tempo_max_trajeto_min <= 0:
            raise ValueError("O tempo máximo a bordo precisa ser maior que "
                             "zero.")
        os.makedirs(DIR_TRABALHO, exist_ok=True)
        with open(os.path.join(DIR_TRABALHO, "perfil.json"), "w",
                  encoding="utf-8") as f:
            json.dump(perfil.como_dicionario(), f, ensure_ascii=False, indent=2)
        self.perfil = perfil
        return self.perfil_em_dicionario()

    def recuperar_perfil(self):
        caminho = os.path.join(DIR_TRABALHO, "perfil.json")
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                self.perfil = perfis_mod.de_dicionario(json.load(f))

    def resumo_da_importacao(self) -> dict:
        if not self.importacao:
            return {}
        imp = self.importacao
        alunos = imp.get("alunos", [])
        return {
            "arquivo": imp.get("arquivo"),
            "importado_em": imp.get("gerado_em"),
            "resumo": imp.get("resumo", {}),
            "problemas": imp.get("problemas", [])[:400],
            "frota_declarada": imp.get("frota_declarada") or {},
            # o mapa só precisa do que é ponto: id, coordenada e se pede ajuste
            "pontos": [{"id": a["id"], "lat": a["lat"], "lon": a["lon"],
                        "bairro": a.get("bairro"), "escola": a.get("escola"),
                        "turno": a.get("turno"),
                        "endereco": a.get("endereco_original"),
                        "ajustar": bool(a.get("precisa_ajuste_no_mapa")),
                        "cadeirante": bool(a.get("cadeirante"))}
                       for a in alunos],
        }


ESTADO = Estado()


def _plano_resumido(plano: dict) -> dict:
    if not plano:
        return {}
    fo = plano["frota_otimizada"]
    return {
        "municipio": plano.get("municipio"),
        "frota": {"total": fo["total_veiculos"], "composicao": fo["composicao"],
                  "km_dia": fo["km_dia"], "custo_mes": fo["custo_mes"]},
        "viagens": len(fo["viagens"]),
        "economia": plano.get("economia"),
        "comparacao_indisponivel": plano.get("comparacao_indisponivel", ""),
        "coerencia": plano.get("coerencia", []),
        "demanda_nao_atendida": plano.get("demanda_nao_atendida", {}),
        "agrupamento": plano.get("agrupamento", {}),
        "demanda": plano.get("demanda", {}),
        "por_turno": fo.get("por_turno", {}),
    }


def roteirizar_em_segundo_plano(opcoes: dict):
    """O solver leva minutos: roda em thread e a tela pergunta o progresso."""
    ESTADO.rodando = True
    ESTADO.erro = ""
    ESTADO.progresso = []
    ESTADO.plano = None

    def trabalho():
        try:
            frota = opcoes.get("frota_declarada") or None
            if frota and not frota.get("composicao"):
                frota = None
            plano = planejar_mod.planejar(
                ESTADO.importacao,
                frota_declarada=frota,
                perfil=ESTADO.perfil,
                municipio=opcoes.get("municipio") or None,
                tempo_limite_s=int(opcoes.get("tempo_limite") or 20),
                raio_urbano=float(opcoes.get("raio_urbano") or 300),
                raio_rural=float(opcoes.get("raio_rural") or 800),
                tempo_max_trajeto_min=int(
                    opcoes.get("tempo_max_trajeto") or 0) or None,
                progresso=ESTADO.anotar)
            ESTADO.plano = plano
            ESTADO.anotar("concluido",
                          f"{plano['frota_otimizada']['total_veiculos']} veículos")
        except Exception as erro:                 # o gestor precisa do motivo
            ESTADO.erro = f"{type(erro).__name__}: {erro}"
            ESTADO.anotar("erro", ESTADO.erro)
            traceback.print_exc()
        finally:
            ESTADO.rodando = False

    threading.Thread(target=trabalho, daemon=True).start()


class Planejamento(BaseHTTPRequestHandler):
    server_version = "MOBGOV-Planejamento/0.8"

    # ------------------------------------------------------------- resposta
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

    def _corpo(self) -> bytes:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > multipart.TAMANHO_MAXIMO:
            raise multipart.ErroDeEnvio("Envio grande demais.")
        return self.rfile.read(tamanho)

    # ---------------------------------------------------------------- rotas
    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho in ("/", "/index.html", "/planejamento"):
            with open(TELA, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8")
        if caminho == "/api/estado":
            return self._json({
                "importacao": ESTADO.resumo_da_importacao(),
                "rodando": ESTADO.rodando,
                "erro": ESTADO.erro,
                "progresso": ESTADO.progresso[-40:],
                "plano": _plano_resumido(ESTADO.plano),
                "perfil": ESTADO.perfil_em_dicionario(),
                "perfis": [{"id": p.id, "nome": p.nome}
                           for p in perfis_mod.EMBUTIDOS.values()],
                "equipe": (ESTADO.plano or {}).get("equipe"),
                "preco": ESTADO.preco,
                "diagnostico": ESTADO.diagnostico,
                "linhas_atuais": len(ESTADO.linhas_atuais or []),
                "publicado": os.path.exists(
                    os.path.join(DIR_RELATORIOS, "dimensionamento.json")),
            })

        if caminho == "/api/proposta":
            arquivo = os.path.join(DIR_TRABALHO, "proposta.html")
            if not os.path.exists(arquivo):
                return self._json({"erro": "Gere a proposta primeiro."}, 404)
            with open(arquivo, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8")
        self._json({"erro": "Rota não encontrada.",
                    "rotas": ["/", "/api/estado", "/api/enviar-planilha",
                              "/api/ajustar", "/api/roteirizar",
                              "/api/publicar"]}, 404)

    do_HEAD = do_GET

    def do_POST(self):
        caminho = urlparse(self.path).path
        try:
            if caminho == "/api/enviar-planilha":
                return self._enviar_planilha()
            if caminho == "/api/ajustar":
                return self._ajustar()
            if caminho == "/api/roteirizar":
                return self._roteirizar()
            if caminho == "/api/publicar":
                return self._publicar()
            if caminho == "/api/enviar-linhas":
                return self._enviar_linhas()
            if caminho == "/api/precificar":
                return self._precificar()
            if caminho == "/api/perfil":
                return self._gravar_perfil()
        except (multipart.ErroDeEnvio, ErroDePlanilha) as erro:
            return self._json({"erro": str(erro)}, 400)
        except Exception as erro:
            traceback.print_exc()
            return self._json({"erro": f"{type(erro).__name__}: {erro}"}, 500)
        self._json({"erro": "Rota não encontrada."}, 404)

    # -------------------------------------------------------------- ações
    def _enviar_planilha(self):
        campos = multipart.analisar(self._corpo(),
                                    self.headers.get("Content-Type", ""))
        arquivo = campos.get("planilha")
        if not isinstance(arquivo, dict) or not arquivo["conteudo"]:
            return self._json({"erro": "Nenhum arquivo foi enviado."}, 400)

        # O perfil muda o que a planilha significa: quais turnos existem, o
        # que é o destino e se o motorista é custo à parte. Escolher isso
        # depois da importação seria reimportar tudo.
        try:
            ESTADO.perfil = perfis_mod.carregar(campos.get("perfil")
                                                or "escolar")
        except ValueError as erro:
            return self._json({"erro": str(erro)}, 400)

        os.makedirs(DIR_TRABALHO, exist_ok=True)
        destino = os.path.join(DIR_TRABALHO, arquivo["nome"])
        with open(destino, "wb") as f:
            f.write(arquivo["conteudo"])

        importacao = planejar_mod.importar_planilha(destino,
                                                    perfil=ESTADO.perfil)
        importacao["frota_declarada"] = planejar_mod.ler_frota_declarada(
            destino, perfil=ESTADO.perfil)
        importacao["caminho"] = destino
        ESTADO.importacao = importacao
        ESTADO.plano = None
        ESTADO.progresso = []
        ESTADO.preco = None
        ESTADO.diagnostico = None
        ESTADO.salvar()
        resposta = ESTADO.resumo_da_importacao()
        resposta["perfil"] = ESTADO.perfil_em_dicionario()
        return self._json(resposta)

    def _enviar_linhas(self):
        """A planilha da operação que a empresa JÁ roda — o 'antes' real."""
        if not ESTADO.plano:
            return self._json({"erro": "Roteirize antes: o diagnóstico compara "
                                       "a operação de hoje com o plano."}, 400)
        campos = multipart.analisar(self._corpo(),
                                    self.headers.get("Content-Type", ""))
        arquivo = campos.get("linhas")
        if not isinstance(arquivo, dict) or not arquivo["conteudo"]:
            return self._json({"erro": "Nenhum arquivo foi enviado."}, 400)

        os.makedirs(DIR_TRABALHO, exist_ok=True)
        destino = os.path.join(DIR_TRABALHO, f"linhas-{arquivo['nome']}")
        with open(destino, "wb") as f:
            f.write(arquivo["conteudo"])

        tipos = ESTADO.plano["premissas"]["custos_por_tipo"]
        lido = operacao_mod.importar(destino, tipos)
        if not lido["linhas"]:
            return self._json({"erro": " ".join(lido["problemas"])
                                       or "Planilha sem linhas."}, 400)
        ESTADO.linhas_atuais = lido["linhas"]
        ESTADO.diagnostico = diagnostico_mod.diagnosticar(lido["linhas"],
                                                          ESTADO.plano)
        ESTADO.diagnostico["problemas_da_planilha"] = lido["problemas"][:6]
        return self._json(ESTADO.diagnostico)

    def _precificar(self):
        if not ESTADO.plano:
            return self._json({"erro": "Roteirize antes de precificar."}, 400)
        opcoes = json.loads(self._corpo().decode("utf-8") or "{}")
        campos = {}
        if opcoes.get("margem") is not None:
            campos["margem_alvo"] = float(opcoes["margem"]) / 100.0
        if opcoes.get("regime"):
            campos["regime"] = opcoes["regime"]
        if opcoes.get("monitores") is not None:
            campos["monitores"] = int(opcoes["monitores"])
        try:
            premissas = precificacao_mod.Premissas(**campos)
            ESTADO.preco = precificacao_mod.precificar(ESTADO.plano, premissas)
            cenarios = precificacao_mod.sensibilidade(ESTADO.plano, premissas)
        except ValueError as erro:
            return self._json({"erro": str(erro)}, 400)
        ESTADO.preco["cenarios"] = cenarios

        os.makedirs(DIR_TRABALHO, exist_ok=True)
        proposta_mod.gerar(
            ESTADO.plano, ESTADO.preco, cenarios, ESTADO.diagnostico,
            cliente=opcoes.get("cliente") or None,
            saida=os.path.join(DIR_TRABALHO, "proposta.html"))
        return self._json(ESTADO.preco)

    def _ajustar(self):
        pedido = json.loads(self._corpo().decode("utf-8"))
        if not ESTADO.importacao:
            return self._json({"erro": "Nenhuma planilha enviada ainda."}, 400)
        alvo = pedido.get("aluno")
        lat, lon = float(pedido["lat"]), float(pedido["lon"])
        for aluno in ESTADO.importacao["alunos"]:
            if aluno["id"] != alvo:
                continue
            aluno["lat"], aluno["lon"] = round(lat, 6), round(lon, 6)
            aluno["precisa_ajuste_no_mapa"] = False
            aluno["origem_da_coordenada"] = "ajustada no mapa"
            ESTADO.importacao["resumo"]["precisam_ajuste_no_mapa"] = sum(
                1 for a in ESTADO.importacao["alunos"]
                if a.get("precisa_ajuste_no_mapa"))
            ESTADO.salvar()
            return self._json({"ok": True, "aluno": alvo,
                               "faltam": ESTADO.importacao["resumo"][
                                   "precisam_ajuste_no_mapa"]})
        return self._json({"erro": f"Aluno {alvo} não está nesta importação."},
                          404)

    def _gravar_perfil(self):
        """Cadastro dos parâmetros da operação — a frota disponível inclusive."""
        pedido = json.loads(self._corpo().decode("utf-8") or "{}")
        try:
            return self._json({"ok": True, "perfil": ESTADO.gravar_perfil(pedido)})
        except (ValueError, KeyError, TypeError) as erro:
            return self._json({"erro": str(erro)}, 400)

    def _roteirizar(self):
        if not ESTADO.importacao:
            return self._json({"erro": "Envie a planilha primeiro."}, 400)
        if ESTADO.rodando:
            return self._json({"erro": "Já existe uma roteirização em "
                                       "andamento."}, 409)
        opcoes = json.loads(self._corpo().decode("utf-8") or "{}")
        roteirizar_em_segundo_plano(opcoes)
        return self._json({"iniciado": True})

    def _publicar(self):
        if not ESTADO.plano:
            return self._json({"erro": "Não há plano roteirizado para "
                                       "publicar."}, 400)
        os.makedirs(DIR_RELATORIOS, exist_ok=True)
        anterior = os.path.join(DIR_RELATORIOS, "dimensionamento.json")
        if os.path.exists(anterior):
            # o plano que estava no ar não é apagado: vira histórico datado
            carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
            os.makedirs(os.path.join(DIR_TRABALHO, "historico"), exist_ok=True)
            os.replace(anterior, os.path.join(DIR_TRABALHO, "historico",
                                              f"dimensionamento-{carimbo}.json"))
        planejar_mod.gravar(ESTADO.plano, anterior)
        with open(os.path.join(DIR_RELATORIOS, "importacao.json"), "w",
                  encoding="utf-8") as f:
            json.dump({k: v for k, v in ESTADO.importacao.items()
                       if k != "cofre"}, f, ensure_ascii=False, indent=2)
        fo = ESTADO.plano["frota_otimizada"]
        return self._json({
            "publicado": True,
            "veiculos": fo["total_veiculos"], "viagens": len(fo["viagens"]),
            "mensagem": (f"Plano publicado: {fo['total_veiculos']} veículos e "
                         f"{len(fo['viagens'])} viagens. Os motoristas passam "
                         f"a ver esta rota no app; o plano anterior foi para o "
                         f"histórico."),
        })

    def log_message(self, formato, *args):
        sys.stderr.write("[planejamento] %s\n" % (formato % args))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tela de planejamento do MOBGOV")
    ap.add_argument("--porta", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)

    ESTADO.recuperar_perfil()
    ESTADO.recuperar()
    servidor = ThreadingHTTPServer((a.host, a.porta), Planejamento)
    print(f"Planejamento em http://{a.host}:{a.porta}/")
    print("  1) envie a planilha  2) confira  3) ajuste no mapa  "
          "4) roteirize  5) publique")
    print("  6) precifique  7) compare com a operação de hoje")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
