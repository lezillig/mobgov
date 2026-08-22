# -*- coding: utf-8 -*-
"""
Testes do app do responsável.

O que estes testes protegem:
1. previsão sem sinal do veículo aparece como PLANEJADO, nunca como medição;
2. o aviso de falta é da família, é desfazível e vale o último;
3. o token de uma família não abre a rota de outra;
4. a taxa de ausência do aprendizado sai do aviso — e some quando não há aviso.
"""
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
from operacao import onde_esta, registro  # noqa: E402
from operacao.servidor import Operacao, vinculos_de_demonstracao  # noqa: E402

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
                     "veiculo": "VM01", "tipo_nome": "Ônibus 31",
                     "paradas": ["P01", "P02", "P03"], "alunos": 28,
                     "cadeirantes": 0, "km_viagem": 12.0, "min_viagem": 30}],
    },
}

DIA = "2026-08-24"
VINCULO = {"aluno": "AP03", "ponto": "P03", "turno": "manha"}


def evento(tipo, **campos):
    return dict({"tipo": tipo}, **campos)


class TestSituacao(unittest.TestCase):
    def test_sem_sinal_do_veiculo_a_previsao_e_o_plano(self):
        s = onde_esta.situacao(VINCULO, PLANO, [], dia=DIA)
        self.assertEqual(s["origem_da_previsao"], "planejado")
        self.assertEqual(s["estado"], "aguardando")
        self.assertIn("não uma medição", s["mensagem"])
        self.assertEqual(s["previsao"], s["hora_planejada"])

    def test_embarque_anterior_vira_previsao_medida(self):
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto="P01", em=f"{DIA}T06:00:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertEqual(s["origem_da_previsao"], "medido")
        self.assertEqual(s["estado"], "a_caminho")

    def test_atraso_do_veiculo_aparece_na_previsao(self):
        no_horario = onde_esta.situacao(
            VINCULO, PLANO,
            [evento("embarque", motorista="VM01", viagem="V1", ponto="P01",
                    em=f"{DIA}T05:50:00")], dia=DIA)
        atrasado = onde_esta.situacao(
            VINCULO, PLANO,
            [evento("embarque", motorista="VM01", viagem="V1", ponto="P01",
                    em=f"{DIA}T06:20:00")], dia=DIA)
        self.assertGreater(atrasado["atraso_min"], no_horario["atraso_min"])

    def test_sinal_com_horario_absurdo_volta_para_o_plano(self):
        """Achado numa demonstração: um embarque com horário de outro turno
        virava '878 min atrasado' escrito com toda a confiança na tela."""
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto="P01", em=f"{DIA}T20:11:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertTrue(s["sinal_inconsistente"])
        self.assertEqual(s["origem_da_previsao"], "planejado")
        self.assertEqual(s["previsao"], s["hora_planejada"])
        self.assertEqual(s["atraso_min"], 0)
        self.assertIn("prefiro não chutar", s["mensagem"])

    def test_atraso_grande_mas_plausivel_continua_medido(self):
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto="P01", em=f"{DIA}T06:40:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertFalse(s["sinal_inconsistente"])
        self.assertEqual(s["origem_da_previsao"], "medido")

    def test_ping_do_veiculo_tambem_serve_de_medicao(self):
        eventos = [evento("ping", motorista="VM01", lat=-21.168, lon=-47.818,
                          em=f"{DIA}T06:05:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertEqual(s["origem_da_previsao"], "medido")
        self.assertIsNotNone(s["posicao_do_veiculo"])

    def test_evento_de_ontem_nao_conta_para_hoje(self):
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto="P01", em="2026-08-23T06:00:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertEqual(s["origem_da_previsao"], "planejado")

    def test_embarque_do_proprio_aluno_encerra_o_acompanhamento(self):
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto="P03", em=f"{DIA}T06:10:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertEqual(s["estado"], "embarcou")
        self.assertFalse(s["pode_avisar_falta"])

    def test_ponto_sem_rota_diz_o_que_fazer(self):
        s = onde_esta.situacao({"aluno": "AX", "ponto": "P99"}, PLANO, [],
                               dia=DIA)
        self.assertEqual(s["estado"], "sem_rota")
        self.assertIn("secretaria", s["mensagem"])

    def test_a_lista_de_paradas_marca_a_sua(self):
        s = onde_esta.situacao(VINCULO, PLANO, [], dia=DIA)
        suas = [p for p in s["paradas"] if p["e_o_seu"]]
        self.assertEqual([p["ponto"] for p in suas], ["P03"])


class TestAvisoDeFalta(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-resp-")
        self.arquivo = os.path.join(self.pasta, "eventos.jsonl")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_aviso_da_familia_e_gravado_sem_motorista(self):
        e = onde_esta.avisar_falta("AP03", "P03", "V1", arquivo=self.arquivo)
        self.assertEqual(e["tipo"], "falta")
        self.assertEqual(len(registro.ler_eventos(self.arquivo, aluno="AP03")), 1)

    def test_aviso_sem_aluno_e_recusado(self):
        with self.assertRaises(registro.ErroDeRegistro):
            registro.registrar({"tipo": "falta", "ponto": "P03"}, self.arquivo)

    def test_falta_avisada_aparece_para_a_familia(self):
        eventos = [evento("falta", aluno="AP03", ponto="P03", viagem="V1",
                          em=f"{DIA}T05:40:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertEqual(s["estado"], "falta_avisada")
        self.assertTrue(s["aviso_de_falta"])

    def test_familia_pode_desdizer_o_aviso(self):
        eventos = [evento("falta", aluno="AP03", ponto="P03", viagem="V1",
                          em=f"{DIA}T05:40:00"),
                   evento("volta_atras", aluno="AP03", ponto="P03",
                          viagem="V1", em=f"{DIA}T05:55:00")]
        s = onde_esta.situacao(VINCULO, PLANO, eventos, dia=DIA)
        self.assertFalse(s["aviso_de_falta"])
        self.assertEqual(s["estado"], "aguardando")

    def test_aviso_desfeito_nao_conta_como_falta_para_o_motorista(self):
        eventos = [evento("falta", aluno="AP01", ponto="P01", viagem="V1",
                          em=f"{DIA}T05:30:00"),
                   evento("falta", aluno="AP02", ponto="P02", viagem="V1",
                          em=f"{DIA}T05:35:00"),
                   evento("volta_atras", aluno="AP01", ponto="P01",
                          viagem="V1", em=f"{DIA}T05:50:00")]
        resumo = onde_esta.faltas_do_dia(eventos, dia=DIA)
        self.assertEqual(resumo["faltas"], 1)
        self.assertEqual(resumo["avisos_desfeitos"], 1)
        self.assertEqual([f["aluno"] for f in resumo["por_viagem"]["V1"]],
                         ["AP02"])


class TestTokenDaFamilia(unittest.TestCase):
    def test_token_da_familia_nao_e_o_do_motorista(self):
        familia = registro.token_do_responsavel("VM01", "P01", "manha")
        self.assertFalse(registro.token_valido("VM01", familia))

    def test_token_amarra_o_ponto(self):
        token = registro.token_do_responsavel("AP03", "P03", "manha")
        self.assertTrue(registro.token_de_responsavel_valido(
            "AP03", token, "P03", "manha"))
        self.assertFalse(registro.token_de_responsavel_valido(
            "AP03", token, "P01", "manha"))

    def test_token_de_outra_chave_nao_vale(self):
        token = registro.token_do_responsavel("AP03", "P03", "manha",
                                              chave="uma")
        self.assertFalse(registro.token_de_responsavel_valido(
            "AP03", token, "P03", "manha", chave="outra"))


class TestApiDoResponsavel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.mkdtemp(prefix="mobgov-api-resp-")
        Operacao.arquivo_eventos = os.path.join(cls.pasta, "eventos.jsonl")
        Operacao.plano = PLANO
        Operacao.modo_demonstracao = True
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Operacao)
        cls.url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        cls.token = registro.token_do_responsavel("AP03", "P03", "manha")

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def consulta(self, aluno="AP03", ponto="P03", token=None):
        return (f"?aluno={aluno}&ponto={ponto}&turno=manha"
                f"&token={token or self.token}")

    def get(self, caminho):
        with urllib.request.urlopen(self.url + caminho) as r:
            return json.loads(r.read())

    def post(self, caminho):
        req = urllib.request.Request(self.url + caminho, data=b"{}",
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_app_do_responsavel_e_servido_e_autocontido(self):
        with urllib.request.urlopen(self.url + "/responsavel") as r:
            html = r.read().decode("utf-8")
        self.assertIn("MOBGOV", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("src=", html)

    def test_situacao_exige_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/situacao" + self.consulta(token="errado"))
        self.assertEqual(ctx.exception.code, 401)

    def test_token_nao_serve_para_outro_ponto(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/situacao" + self.consulta(ponto="P01"))
        self.assertEqual(ctx.exception.code, 401)

    def test_situacao_com_token(self):
        s = self.get("/api/situacao" + self.consulta())
        self.assertEqual(s["ponto"], "P03")
        self.assertEqual(s["escola"], "EMEF Centro")

    def test_avisar_e_desfazer_pela_api(self):
        self.post("/api/falta" + self.consulta())
        s = self.get("/api/situacao" + self.consulta())
        self.assertTrue(s["aviso_de_falta"])
        faltas = self.get("/api/faltas-do-dia")
        self.assertEqual(faltas["faltas"], 1)

        self.post("/api/desfazer-falta" + self.consulta())
        s = self.get("/api/situacao" + self.consulta())
        self.assertFalse(s["aviso_de_falta"])
        self.assertEqual(self.get("/api/faltas-do-dia")["faltas"], 0)

    def test_vinculos_de_demonstracao_saem_do_plano(self):
        vinculos = self.get("/api/responsaveis")
        self.assertTrue(vinculos)
        v = vinculos[0]
        self.assertTrue(registro.token_de_responsavel_valido(
            v["aluno"], v["token"], v["ponto"], v["turno"]))
        # nenhum nome de criança na lista de demonstração
        self.assertNotIn("nome", v)


class TestAusenciaNoAprendizado(unittest.TestCase):
    def eventos_de(self, dias, por_dia=2):
        eventos = []
        for i, dia in enumerate(dias):
            for j in range(por_dia):
                eventos.append(evento("falta", aluno=f"A{j}", ponto="P01",
                                      viagem="V1", em=f"{dia}T05:4{i}:00"))
        return eventos

    def test_sem_aviso_nenhum_a_lista_de_faltas_fica_vazia(self):
        self.assertEqual(ingestao.faltas_observadas([], PLANO), [])

    def test_aviso_vira_taxa_por_viagem_e_dia(self):
        faltas = ingestao.faltas_observadas(
            self.eventos_de(["2026-08-24"], por_dia=7), PLANO)
        self.assertEqual(len(faltas), 1)
        self.assertEqual(faltas[0]["faltas_avisadas"], 7)
        self.assertEqual(faltas[0]["alunos_previstos"], 28)
        self.assertEqual(faltas[0]["taxa"], 0.25)
        self.assertEqual(faltas[0]["origem"], "aviso_do_responsavel")

    def test_aviso_desfeito_nao_vira_ausencia_aprendida(self):
        eventos = [evento("falta", aluno="A1", ponto="P01", viagem="V1",
                          em="2026-08-24T05:40:00"),
                   evento("volta_atras", aluno="A1", ponto="P01", viagem="V1",
                          em="2026-08-24T05:55:00")]
        self.assertEqual(ingestao.faltas_observadas(eventos, PLANO), [])

    def test_aviso_de_viagem_desconhecida_e_ignorado(self):
        eventos = [evento("falta", aluno="A1", ponto="PX", viagem="V9",
                          em="2026-08-24T05:40:00")]
        self.assertEqual(ingestao.faltas_observadas(eventos, PLANO), [])

    def test_taxa_so_sai_com_dias_suficientes(self):
        poucos = {"faltas": ingestao.faltas_observadas(
            self.eventos_de(["2026-08-24", "2026-08-25"]), PLANO)}
        self.assertIsNone(ingestao.taxa_de_ausencia(poucos))

        dias = [f"2026-08-2{d}" for d in range(1, 7)]
        muitos = {"faltas": ingestao.faltas_observadas(
            self.eventos_de(dias), PLANO)}
        taxa = ingestao.taxa_de_ausencia(muitos)
        self.assertAlmostEqual(taxa, 2 / 28, places=3)

    def test_observacoes_agora_trazem_as_faltas(self):
        eventos = [evento("embarque", motorista="VM01", viagem="V1",
                          ponto=p, em=f"2026-08-24T06:{m:02d}:00")
                   for p, m in (("P01", 0), ("P02", 15), ("P03", 34))]
        eventos += self.eventos_de(["2026-08-24"], por_dia=3)
        obs = ingestao.observacoes(eventos, PLANO, {"manha": "pico_manha"},
                                   {"V1": "rural"})
        self.assertEqual(len(obs["trechos"]), 1)
        self.assertEqual(obs["faltas"][0]["faltas_avisadas"], 3)


if __name__ == "__main__":
    unittest.main()
