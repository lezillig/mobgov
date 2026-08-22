# -*- coding: utf-8 -*-
"""Testes da operação do dia: registro, rota do motorista, API e ingestão."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aprendizado import ingestao  # noqa: E402
from operacao import registro, rota_do_dia as rotas  # noqa: E402
from operacao.servidor import Operacao  # noqa: E402

PLANO = {
    "demanda": {"turnos": [{"id": "manha", "nome": "Manhã",
                            "jornada_max_min": 100}]},
    "geografia": {"pontos": {"P01": [-21.15, -47.80], "P02": [-21.16, -47.81],
                             "P03": [-21.17, -47.82]}},
    "frota_otimizada": {
        "veiculos": [{"id": "VM01", "turno": "manha", "turno_nome": "Manhã",
                      "tipo": "ONIBUS31", "tipo_nome": "Ônibus 31",
                      "capacidade": 31, "viagens": ["V1"], "min_turno": 60,
                      "alunos": 28}],
        "viagens": [{"id": "V1", "turno": "manha", "turno_nome": "Manhã",
                     "escola": "EMEF Centro", "escola_id": "E1",
                     "paradas": ["P01", "P02", "P03"], "alunos": 28,
                     "cadeirantes": 0, "km_viagem": 12.0, "min_viagem": 30}],
    },
}


class TestRegistro(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-op-")
        self.arquivo = os.path.join(self.pasta, "eventos.jsonl")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_grava_e_le(self):
        registro.registrar({"tipo": "ping", "motorista": "VM01",
                            "lat": -21.15, "lon": -47.8}, self.arquivo)
        eventos = registro.ler_eventos(self.arquivo)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["tipo"], "ping")

    def test_guarda_o_horario_do_aparelho_e_o_do_servidor(self):
        """O que vale para reconstruir o dia é quando ACONTECEU."""
        e = registro.registrar({"tipo": "embarque", "motorista": "VM01",
                                "em": "2026-08-22T06:12:00"}, self.arquivo)
        self.assertEqual(e["em"], "2026-08-22T06:12:00")
        self.assertIn("recebido_em", e)
        self.assertNotEqual(e["em"], e["recebido_em"])

    def test_tipo_desconhecido_e_recusado_com_motivo(self):
        with self.assertRaises(registro.ErroDeRegistro) as ctx:
            registro.registrar({"tipo": "voar", "motorista": "VM01"},
                               self.arquivo)
        self.assertIn("voar", str(ctx.exception))

    def test_evento_sem_motorista_e_recusado(self):
        with self.assertRaises(registro.ErroDeRegistro):
            registro.registrar({"tipo": "ping"}, self.arquivo)

    def test_lote_ruim_no_meio_nao_derruba_o_resto(self):
        """O motorista não pode perder o dia por causa de um evento torto."""
        resultado = registro.registrar_lote([
            {"tipo": "embarque", "motorista": "VM01", "ponto": "P01"},
            {"tipo": "voar", "motorista": "VM01"},
            {"tipo": "ping", "motorista": "VM01"},
        ], self.arquivo)
        self.assertEqual(resultado["aceitos"], 2)
        self.assertEqual(len(resultado["recusados"]), 1)
        self.assertEqual(resultado["recusados"][0]["indice"], 1)

    def test_arquivo_com_linha_corrompida_ainda_e_lido(self):
        registro.registrar({"tipo": "ping", "motorista": "VM01"}, self.arquivo)
        with open(self.arquivo, "a", encoding="utf-8") as f:
            f.write("{lixo\n")
        registro.registrar({"tipo": "ping", "motorista": "VM01"}, self.arquivo)
        self.assertEqual(len(registro.ler_eventos(self.arquivo)), 2)

    def test_token_por_motorista(self):
        a = registro.token_do_motorista("VM01", chave="abc")
        self.assertTrue(registro.token_valido("VM01", a, chave="abc"))
        self.assertFalse(registro.token_valido("VM02", a, chave="abc"))
        self.assertFalse(registro.token_valido("VM01", a, chave="outra"))
        self.assertFalse(registro.token_valido("VM01", ""))


class TestRotaDoDia(unittest.TestCase):
    def test_monta_a_rota_do_motorista(self):
        rota = rotas.rota_do_dia("VM01", PLANO)
        self.assertEqual(rota["veiculo"], "Ônibus 31")
        self.assertEqual(len(rota["viagens"]), 1)
        self.assertEqual(len(rota["viagens"][0]["paradas"]), 3)

    def test_paradas_trazem_coordenada_e_horario(self):
        parada = rotas.rota_do_dia("VM01", PLANO)["viagens"][0]["paradas"][0]
        self.assertIsNotNone(parada["lat"])
        self.assertRegex(parada["hora_prevista"], r"^\d{2}h\d{2}$")

    def test_horarios_avancam_ao_longo_da_viagem(self):
        paradas = rotas.rota_do_dia("VM01", PLANO)["viagens"][0]["paradas"]
        horas = [p["hora_prevista"] for p in paradas]
        self.assertEqual(horas, sorted(horas))

    def test_motorista_desconhecido_devolve_vazio(self):
        self.assertEqual(rotas.rota_do_dia("NAO-EXISTE", PLANO), {})

    def test_lista_de_motoristas(self):
        lista = rotas.motoristas(PLANO)
        self.assertEqual(lista[0]["motorista"], "VM01")


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.mkdtemp(prefix="mobgov-api-")
        Operacao.arquivo_eventos = os.path.join(cls.pasta, "eventos.jsonl")
        Operacao.plano = PLANO
        Operacao.modo_demonstracao = True
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Operacao)
        cls.url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        cls.token = registro.token_do_motorista("VM01")

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def get(self, caminho):
        with urllib.request.urlopen(self.url + caminho) as r:
            return json.loads(r.read())

    def post(self, caminho, corpo):
        req = urllib.request.Request(
            self.url + caminho, data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_app_do_motorista_e_servido(self):
        with urllib.request.urlopen(self.url + "/") as r:
            html = r.read().decode("utf-8")
        self.assertIn("MOBGOV", html)
        self.assertIn("localStorage", html)      # offline-first de verdade
        self.assertNotIn("http://", html)        # sem CDN

    def test_rota_do_dia_exige_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/rota-do-dia?motorista=VM01&token=errado")
        self.assertEqual(ctx.exception.code, 401)

    def test_rota_do_dia_com_token(self):
        rota = self.get(f"/api/rota-do-dia?motorista=VM01&token={self.token}")
        self.assertEqual(rota["motorista"], "VM01")

    def test_eventos_precisam_de_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/eventos?motorista=VM01&token=errado",
                      {"eventos": []})
        self.assertEqual(ctx.exception.code, 401)

    def test_lote_de_eventos(self):
        resultado = self.post(
            f"/api/eventos?motorista=VM01&token={self.token}",
            {"eventos": [{"tipo": "embarque", "viagem": "V1", "ponto": "P01"},
                         {"tipo": "voar"}]})
        self.assertEqual(resultado["aceitos"], 1)
        self.assertEqual(len(resultado["recusados"]), 1)

    def test_evento_nao_pode_assinar_por_outro_motorista(self):
        self.post(f"/api/eventos?motorista=VM01&token={self.token}",
                  {"eventos": [{"tipo": "ping", "motorista": "VM99"}]})
        gravados = registro.ler_eventos(Operacao.arquivo_eventos,
                                        motorista="VM99")
        self.assertEqual(gravados, [])

    def test_corpo_invalido(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(f"/api/eventos?motorista=VM01&token={self.token}",
                      {"nao_e_eventos": 1})
        self.assertEqual(ctx.exception.code, 400)

    def test_resumo(self):
        resumo = self.get("/api/resumo")
        self.assertIn("por_tipo", resumo)


class TestIngestao(unittest.TestCase):
    def eventos_de_um_dia(self, minutos):
        return [{"tipo": "embarque", "motorista": "VM01", "viagem": "V1",
                 "ponto": ponto, "em": f"2026-08-24T{6:02d}:{m:02d}:00"}
                for ponto, m in zip(("P01", "P02", "P03"), minutos)]

    def test_converte_embarques_em_trechos(self):
        obs = ingestao.observacoes(
            self.eventos_de_um_dia([0, 15, 34]), PLANO,
            {"manha": "pico_manha"}, {"V1": "rural"})
        self.assertEqual(len(obs["trechos"]), 1)
        trecho = obs["trechos"][0]
        self.assertEqual(trecho["min_realizado"], 34)
        self.assertIn("fator_plano", trecho)      # o ciclo precisa disso

    def test_ignora_viagem_com_poucos_embarques(self):
        obs = ingestao.observacoes(
            self.eventos_de_um_dia([0, 10])[:2], PLANO,
            {"manha": "pico_manha"}, {"V1": "rural"})
        self.assertEqual(obs["trechos"], [])

    def test_mede_tempo_de_parada_por_ponto(self):
        obs = ingestao.observacoes(
            self.eventos_de_um_dia([0, 15, 34]), PLANO,
            {"manha": "pico_manha"}, {"V1": "rural"})
        pontos = {p["ponto"] for p in obs["paradas"]}
        self.assertEqual(pontos, {"P02", "P03"})
        self.assertTrue(all(p["min_extra_realizado"] >= 0
                            for p in obs["paradas"]))

    def test_nao_inventa_falta(self):
        """Ausência vem do app do responsável, que ainda não existe."""
        obs = ingestao.observacoes(
            self.eventos_de_um_dia([0, 15, 34]), PLANO,
            {"manha": "pico_manha"}, {"V1": "rural"})
        self.assertEqual(obs["faltas"], [])

    def test_suficiente_exige_massa_critica(self):
        self.assertFalse(ingestao.suficiente({"trechos": [1] * 5}))
        self.assertTrue(ingestao.suficiente({"trechos": [1] * 40}))

    def test_evento_sem_horario_valido_e_ignorado(self):
        eventos = self.eventos_de_um_dia([0, 15, 34])
        eventos.append({"tipo": "embarque", "motorista": "VM01",
                        "viagem": "V1", "ponto": "P03", "em": "ontem"})
        obs = ingestao.observacoes(eventos, PLANO, {"manha": "pico_manha"},
                                   {"V1": "rural"})
        self.assertEqual(len(obs["trechos"]), 1)


if __name__ == "__main__":
    unittest.main()
