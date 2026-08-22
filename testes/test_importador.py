# -*- coding: utf-8 -*-
"""Testes do importador de planilha da prefeitura (Sprint 6)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import importador, planilha  # noqa: E402
from dados.planilha_exemplo import (  # noqa: E402
    escrever_xlsx, gerar, limites_do_municipio, referencias_de_bairro,
)

CABECALHO = ["ALUNO(A)", "Endereço", "Nº", "Bairro", "Escola", "Turno",
             "Cadeira de Rodas", "Acompanhante", "Latitude", "Longitude"]


class BaseArquivos(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-planilha-")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def csv(self, texto, codificacao="utf-8", nome="planilha.csv"):
        caminho = os.path.join(self.pasta, nome)
        with open(caminho, "wb") as f:
            f.write(texto.encode(codificacao))
        return caminho

    def xlsx(self, linhas, nome="planilha.xlsx"):
        return escrever_xlsx(os.path.join(self.pasta, nome), linhas)


class TestLeituraDePlanilha(BaseArquivos):
    def test_csv_com_ponto_e_virgula(self):
        c = self.csv("nome;bairro\nAna;Centro\n")
        self.assertEqual(planilha.ler(c), [["nome", "bairro"], ["Ana", "Centro"]])

    def test_csv_com_virgula(self):
        c = self.csv("nome,bairro\nAna,Centro\n")
        self.assertEqual(planilha.ler(c)[1], ["Ana", "Centro"])

    def test_csv_em_latin1_nao_quebra_acento(self):
        c = self.csv("nome;bairro\nJoão;Sertão\n", codificacao="latin-1")
        self.assertEqual(planilha.ler(c)[1], ["João", "Sertão"])

    def test_csv_com_bom(self):
        c = self.csv("﻿nome;bairro\nAna;Centro\n")
        self.assertEqual(planilha.ler(c)[0][0], "nome")

    def test_xlsx_basico(self):
        x = self.xlsx([["nome", "bairro"], ["Ana", "Centro"]])
        self.assertEqual(planilha.ler(x), [["nome", "bairro"], ["Ana", "Centro"]])

    def test_xlsx_com_celula_vazia_no_meio(self):
        """Célula vazia some do XML; se não for reposta, a linha desloca."""
        x = self.xlsx([["a", "b", "c"], ["1", "", "3"]])
        self.assertEqual(planilha.ler(x)[1], ["1", "", "3"])

    def test_xlsx_com_linha_em_branco_mantem_a_numeracao(self):
        """Linha vazia some do XML — mas a linha 4 do relatório tem que ser a
        linha 4 que o servidor vê quando abre o arquivo no Excel."""
        x = self.xlsx([["a"], [""], ["b"], ["c"]])
        lido = planilha.ler(x)
        self.assertEqual(len(lido), 4)
        self.assertEqual(lido[0], ["a"])
        self.assertEqual(lido[1], [])
        self.assertEqual(lido[2], ["b"])
        self.assertEqual(lido[3], ["c"])

    def test_arquivo_inexistente(self):
        with self.assertRaises(planilha.ErroDePlanilha):
            planilha.ler(os.path.join(self.pasta, "nao-existe.xlsx"))

    def test_arquivo_que_nao_e_planilha(self):
        c = self.csv("isso aqui não é planilha", nome="lixo.xlsx")
        with self.assertRaises(planilha.ErroDePlanilha):
            planilha.ler_xlsx(c)


class TestDeteccaoDeColunas(unittest.TestCase):
    def test_reconhece_sinonimos(self):
        colunas = importador.detectar_colunas(CABECALHO)
        for campo in ("nome", "endereco", "bairro", "escola", "turno",
                      "cadeirante", "latitude", "longitude"):
            self.assertIn(campo, colunas, campo)

    def test_ignora_acento_e_caixa(self):
        colunas = importador.detectar_colunas(["ESTUDANTE", "LOGRADOURO",
                                               "PERÍODO"])
        self.assertEqual(colunas["nome"], 0)
        self.assertEqual(colunas["endereco"], 1)
        self.assertEqual(colunas["turno"], 2)

    def test_cabecalho_irreconhecivel(self):
        self.assertEqual(importador.detectar_colunas(["x", "y", "z"]), {})


class TestConversoes(unittest.TestCase):
    def test_turnos(self):
        for texto in ("Manhã", "MAT", "matutino", "M", "manha"):
            self.assertEqual(importador.converter_turno(texto), "manha", texto)
        for texto in ("Tarde", "vespertino", "T"):
            self.assertEqual(importador.converter_turno(texto), "tarde", texto)
        self.assertIsNone(importador.converter_turno("integral"))

    def test_sim_nao(self):
        for texto in ("sim", "S", "x", "1", "SIM"):
            self.assertTrue(importador.converter_sim_nao(texto), texto)
        for texto in ("não", "N", "0", "-", ""):
            self.assertFalse(importador.converter_sim_nao(texto), texto)
        self.assertIsNone(importador.converter_sim_nao("?"))

    def test_pseudonimo_e_estavel_e_nao_revela_o_nome(self):
        a = importador.pseudonimo("Ana Maria", "Rua X 10", "Centro")
        b = importador.pseudonimo("ana maria", "rua x 10", "centro")
        self.assertEqual(a, b)                       # estável
        self.assertNotIn("ana", a.lower())           # não revela
        self.assertNotEqual(
            a, importador.pseudonimo("Ana Maria", "Rua Y 10", "Centro"))


class TestImportacao(BaseArquivos):
    def setUp(self):
        super().setUp()
        self.referencias = referencias_de_bairro()
        self.limites = limites_do_municipio()

    def importar(self, linhas, **kw):
        return importador.importar(self.xlsx(linhas),
                                   referencias=self.referencias,
                                   limites=self.limites, **kw)

    def linha(self, nome="Ana Silva", turno="Manhã", cadeira="", lat="-21.15",
              lon="-47.80", bairro="Sede Urbana"):
        return [nome, "Rua A", "10", bairro, "EMEF Centro", turno, cadeira,
                "", lat, lon]

    def test_pula_titulo_antes_do_cabecalho(self):
        r = self.importar([["PREFEITURA DE X", "", ""],
                           ["transporte 2026", "", ""],
                           CABECALHO, self.linha()])
        self.assertEqual(len(r.alunos), 1)

    def test_linha_do_relatorio_e_a_linha_do_excel(self):
        """Com título, linha em branco e cabeçalho na linha 4, o primeiro
        aluno é a linha 5 — é para lá que o servidor tem que ir."""
        r = self.importar([["PREFEITURA DE X"], ["transporte 2026"], [""],
                           CABECALHO, self.linha(), self.linha(nome="Bruno")])
        self.assertEqual([a["linha_planilha"] for a in r.alunos], [5, 6])

    def test_aluno_repetido_entra_uma_vez_so(self):
        r = self.importar([CABECALHO, self.linha(), self.linha()])
        self.assertEqual(len(r.alunos), 1)
        self.assertTrue(any("repetido" in p["problema"] for p in r.problemas))

    def test_linha_em_branco_nao_vira_aluno(self):
        r = self.importar([CABECALHO, self.linha(), [""] * 10])
        self.assertEqual(len(r.alunos), 1)

    def test_endereco_sem_coordenada_usa_referencia_do_bairro(self):
        r = self.importar([CABECALHO,
                           self.linha(lat="", lon="", bairro="Vila Rural Sul")])
        aluno = r.alunos[0]
        self.assertEqual(aluno["origem_da_coordenada"], "referencia_do_bairro")
        self.assertTrue(aluno["precisa_ajuste_no_mapa"])
        self.assertTrue(any("ajuste" in p["sugestao"].lower() or
                            "arraste" in p["sugestao"].lower()
                            for p in r.problemas))

    def test_bairro_desconhecido_sem_coordenada_e_erro(self):
        r = self.importar([CABECALHO,
                           self.linha(lat="", lon="", bairro="Marte")])
        self.assertEqual(len(r.alunos), 0)
        self.assertTrue(any(p["gravidade"] == "erro" for p in r.problemas))

    def test_latitude_e_longitude_trocadas_sao_corrigidas(self):
        r = self.importar([CABECALHO, self.linha(lat="-47.80", lon="-21.15")])
        aluno = r.alunos[0]
        self.assertAlmostEqual(aluno["lat"], -21.15, places=2)
        self.assertAlmostEqual(aluno["lon"], -47.80, places=2)
        self.assertTrue(any("trocadas" in p["problema"] for p in r.problemas))

    def test_coordenada_fora_do_municipio_cai_para_a_referencia(self):
        r = self.importar([CABECALHO, self.linha(lat="-3.10", lon="-60.02")])
        self.assertEqual(r.alunos[0]["origem_da_coordenada"],
                         "referencia_do_bairro")
        self.assertTrue(any("fora do município" in p["problema"]
                            for p in r.problemas))

    def test_turno_desconhecido_vira_aviso_e_assume_manha(self):
        r = self.importar([CABECALHO, self.linha(turno="integral")])
        self.assertEqual(r.alunos[0]["turno"], "manha")
        self.assertTrue(any(p["campo"] == "turno" and p["gravidade"] == "aviso"
                            for p in r.problemas))

    def test_cadeirante_ambiguo_vira_erro_e_assume_nao(self):
        r = self.importar([CABECALHO, self.linha(cadeira="?")])
        self.assertFalse(r.alunos[0]["cadeirante"])
        self.assertTrue(any(p["campo"] == "cadeirante" and
                            p["gravidade"] == "erro" for p in r.problemas))

    def test_nome_nao_vai_para_o_dado_de_roteirizacao(self):
        r = self.importar([CABECALHO, self.linha(nome="Maria de Lourdes")])
        bruto = str(r.alunos[0])
        self.assertNotIn("Maria", bruto)
        self.assertNotIn("Lourdes", bruto)

    def test_lista_nominal_so_sai_quando_pedida(self):
        sem = self.importar([CABECALHO, self.linha()])
        self.assertEqual(sem.cofre, {})
        com = self.importar([CABECALHO, self.linha()], guardar_nomes=True)
        self.assertEqual(list(com.cofre.values()), ["Ana Silva"])

    def test_cabecalho_irreconhecivel_explica_o_que_falta(self):
        r = self.importar([["col1", "col2"], ["a", "b"]])
        self.assertEqual(len(r.alunos), 0)
        self.assertIn("cabeçalho", r.problemas[0]["sugestao"].lower())

    def test_planilha_vazia(self):
        r = importador.importar(self.xlsx([]))
        self.assertEqual(len(r.alunos), 0)
        self.assertTrue(r.problemas)


class TestPlanilhaDeDemonstracao(BaseArquivos):
    def test_importa_a_planilha_bagunçada_inteira(self):
        caminho = gerar(os.path.join(self.pasta, "demo.xlsx"), quantidade=60)
        r = importador.importar(caminho, referencias=referencias_de_bairro(),
                                limites=limites_do_municipio())
        resumo = r.resumo()
        self.assertGreater(resumo["alunos_importados"], 50)
        self.assertGreater(resumo["avisos"], 0)     # a bagunça foi apontada
        self.assertGreater(resumo["precisam_ajuste_no_mapa"], 0)
        self.assertEqual(set(resumo["por_turno"]) - {"manha", "tarde", "noite"},
                         set())
        # nenhum aluno entra sem coordenada utilizável
        for a in r.alunos:
            self.assertIsNotNone(a["lat"])
            self.assertIsNotNone(a["lon"])

    def test_e_reprodutivel(self):
        a = gerar(os.path.join(self.pasta, "a.xlsx"), 30)
        b = gerar(os.path.join(self.pasta, "b.xlsx"), 30)
        self.assertEqual(planilha.ler(a), planilha.ler(b))


if __name__ == "__main__":
    unittest.main()
