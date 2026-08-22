# -*- coding: utf-8 -*-
"""
Testes do protótipo do sistema remodelado (ui/).

O que protegem:

1. **o HTML sai autocontido** — a tela é aberta com duplo clique, muitas vezes
   sem internet; qualquer `src=` ou `href=` para fora quebra a demonstração;
2. **o dado da importação é do plano que está na tela** — mostrar o erro de
   uma planilha em cima dos números de outra é o pior tipo de bug: parece
   certo;
3. **a ordem das pendências** — quem pode ficar sem transporte vem antes de
   dinheiro;
4. **o selo acompanha todo bloco de número** — a regra do projeto virou
   componente, e componente sem teste volta a ser rodapé.
"""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import gerar as ui  # noqa: E402


class TestPendencias(unittest.TestCase):
    """A ordem é a mensagem: primeiro quem espera, depois quanto custa."""

    def test_gente_antes_de_dinheiro(self):
        plano = {
            "coerencia": ["a frota declarada não bate com a demanda"],
            "demanda_nao_atendida": {
                "alunos": 9,
                "pontos": [{"ponto": "P1", "escola": "E1",
                            "minutos_minimos": 88, "limite_min": 75}],
            },
        }
        elegibilidade = {"resumo": {"atrasados": 5, "prazo_dias": 15,
                                    "dias_em_aberto_media": 11.3}}
        itens = ui._pendencias(plano, elegibilidade, None, None)
        self.assertEqual([i["urgencia"] for i in itens][:2], ["alta", "alta"])
        self.assertEqual(itens[-1]["urgencia"], "media")
        self.assertIn("porta a porta", itens[0]["titulo"])

    def test_toda_pendencia_tem_dono_e_acao(self):
        plano = {"coerencia": ["aviso"], "demanda_nao_atendida": {}}
        equipe = {"resumo": {"escalas_com_problema": 2, "com_hora_extra": 1,
                             "hora_extra_total_min": 16}}
        itens = ui._pendencias(plano, None, None, equipe)
        self.assertTrue(itens)
        for item in itens:
            self.assertTrue(item["quem_decide"])
            self.assertTrue(item["acao"])
            self.assertTrue(item["detalhe"])
            self.assertIn(item["destino"], ("planejar", "operar", "vender"))

    def test_sem_problema_nao_inventa_pendencia(self):
        self.assertEqual(
            ui._pendencias({"coerencia": [], "demanda_nao_atendida": {}},
                           {"resumo": {}}, {"resumo": {}}, {"resumo": {}}),
            [])

    def test_hora_extra_no_singular(self):
        equipe = {"resumo": {"com_hora_extra": 1, "hora_extra_total_min": 16}}
        titulo = ui._pendencias({}, None, None, equipe)[0]["titulo"]
        self.assertEqual(titulo, "1 escala fecha com hora extra")


class TestSelo(unittest.TestCase):
    def test_todo_selo_explica_de_onde_veio(self):
        for origem in ("medido", "planejado", "informado", "simulado"):
            selo = ui._selo(origem)
            self.assertEqual(selo["rotulo"], origem)
            self.assertTrue(selo["explicacao"], origem)


class TestMontagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = ui.montar(chave_atual="prefeitura")

    def test_tem_os_quatro_destinos(self):
        for chave in ("pendencias", "resumo", "planejar", "operar", "mapa"):
            self.assertIn(chave, self.dados)

    def test_mapa_tem_o_que_desenhar(self):
        mapa = self.dados["mapa"]
        self.assertTrue(mapa["pontos"])
        self.assertTrue(mapa["viagens"])
        primeira = mapa["viagens"][0]
        self.assertTrue(primeira["paradas"])
        # toda parada desenhada precisa existir no dicionário de pontos
        for parada in primeira["paradas"]:
            self.assertIn(parada, mapa["pontos"])

    def test_importacao_so_entra_se_for_do_mesmo_arquivo(self):
        """O relatório de importação é de uma planilha; o plano, de outra."""
        arquivo = self.dados["planejar"]["arquivo"]
        origem = (self.dados["planejar"]["origem"] or {}).get("arquivo")
        self.assertEqual(arquivo, origem)

    def test_operacao_atual_marcada_no_seletor(self):
        atuais = [o for o in self.dados["operacoes"] if o["atual"]]
        self.assertEqual(len(atuais), 1)
        self.assertEqual(len(self.dados["operacoes"]), len(ui.OPERACOES))

    def test_frota_e_o_pior_turno_nao_a_soma(self):
        """A armadilha do projeto: somar os turnos infla a frota."""
        por_turno = self.dados["planejar"]["por_turno"]
        if por_turno:
            soma = sum(t["veiculos"] for t in por_turno)
            self.assertLessEqual(self.dados["resumo"]["veiculos"], soma)


class TestFretamento(unittest.TestCase):
    """A operação de empresa não empresta números do transporte escolar."""

    @classmethod
    def setUpClass(cls):
        caminho = os.path.join(ui.DIR_RELATORIOS, "plano-fretamento.json")
        if not os.path.exists(caminho):
            raise unittest.SkipTest("sem plano de fretamento gerado")
        cls.dados = ui.montar(caminho, chave_atual="empresa")

    def test_sem_fila_de_porta_a_porta(self):
        self.assertIsNone(self.dados["operar"]["elegibilidade"])

    def test_fala_a_lingua_de_quem_usa(self):
        self.assertEqual(self.dados["operacao"]["passageiros"], "colaboradores")
        self.assertEqual(self.dados["operacao"]["destinos"], "plantas")

    def test_problema_da_planilha_fala_de_colaborador(self):
        """O importador é escolar por dentro; a tela, não."""
        textos = " ".join(p["problema"] + " " + p["sugestao"]
                          for p in self.dados["planejar"]["problemas"])
        self.assertNotIn("aluno", textos.lower())
        self.assertIn("colaborador", textos.lower())

    def test_vender_tem_preco_e_diagnostico(self):
        vender = self.dados["vender"]
        self.assertIsNotNone(vender)
        preco = vender["preco"]["preco"]
        custo = vender["preco"]["custo"]
        self.assertGreater(preco["mes"], custo["total_mes"])
        # o preço sai por divisão: sobra margem DEPOIS do imposto
        sobra = preco["mes"] - custo["total_mes"] - preco["impostos_mes"]
        self.assertAlmostEqual(sobra, preco["lucro_mes"], places=0)
        self.assertTrue(vender["cenarios"])
        self.assertTrue((vender["diagnostico"] or {}).get("achados"))


class TestHtmlGerado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.mkdtemp()
        cls.caminho = ui.gerar(os.path.join(cls.pasta, "sistema.html"))
        with open(cls.caminho, encoding="utf-8") as f:
            cls.html = f.read()

    def test_autocontido(self):
        """Sem internet a tela tem que abrir igual."""
        fora = re.findall(r'(?:src|href)="(?!#)(https?:|//)', self.html)
        self.assertEqual(fora, [], "a tela busca coisa fora do arquivo")

    def test_dados_embutidos_e_validos(self):
        self.assertNotIn("__DADOS__", self.html)
        bruto = re.search(r"var DADOS = (\{.*?\});\n", self.html, re.S)
        self.assertIsNotNone(bruto, "não achei o bloco de dados embutido")
        dados = json.loads(bruto.group(1))
        self.assertIn("pendencias", dados)

    def test_diz_que_e_demonstracao(self):
        self.assertIn("demonstração", self.html)

    def test_as_duas_operacoes_apontam_para_arquivos_que_existem(self):
        caminhos = ui.gerar_todas(self.pasta)
        self.assertEqual(len(caminhos), len(ui.OPERACOES))
        for caminho in caminhos:
            self.assertTrue(os.path.exists(caminho))
        nomes = {os.path.basename(c) for c in caminhos}
        for operacao in ui.OPERACOES:
            self.assertIn(operacao["arquivo"], nomes)


if __name__ == "__main__":
    unittest.main()
