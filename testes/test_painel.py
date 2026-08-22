# -*- coding: utf-8 -*-
"""Testes da página do painel: autonomia offline, conteúdo da demo e API."""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import aprendizado, economia as ec, formato, render  # noqa: E402


class TestFormato(unittest.TestCase):
    def test_numero_em_padrao_brasileiro(self):
        self.assertEqual(formato.numero(1234567.8, 1), "1.234.567,8")
        self.assertEqual(formato.numero(0), "0")

    def test_reais(self):
        self.assertEqual(formato.reais(1234), "R$ 1.234")
        self.assertEqual(formato.reais(-1234), "-R$ 1.234")
        self.assertEqual(formato.reais(6.1, 2), "R$ 6,10")

    def test_reais_curto(self):
        self.assertEqual(formato.reais_curto(1_501_188), "R$ 1,50 mi")
        self.assertEqual(formato.reais_curto(125_099), "R$ 125 mil")
        self.assertEqual(formato.reais_curto(880), "R$ 880")


class TestAprendizado(unittest.TestCase):
    def test_sem_arquivo_usa_serie_de_demonstracao_e_avisa(self):
        serie = aprendizado.carregar_serie("/caminho/que/nao/existe.json")
        self.assertTrue(serie["e_demonstracao"])
        self.assertEqual(serie["selo"], "SÉRIE DE DEMONSTRAÇÃO")
        self.assertGreater(serie["queda_erro_pct"], 0)

    def test_com_arquivo_real_muda_o_selo(self):
        dados = {"origem": "operacao_real", "semanas": [
            {"semana": "2026-03-02", "mae_min": 5.0, "acuracia_ausencia_pct": 60.0,
             "viagens": 100},
            {"semana": "2026-03-09", "mae_min": 4.0, "acuracia_ausencia_pct": 70.0,
             "viagens": 120}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(dados, f)
            caminho = f.name
        try:
            serie = aprendizado.carregar_serie(caminho)
            self.assertFalse(serie["e_demonstracao"])
            self.assertEqual(serie["selo"], "MEDIDO NA OPERAÇÃO")
            self.assertEqual(serie["queda_erro_pct"], 20.0)
            self.assertEqual(serie["ganho_ausencia_pp"], 10.0)
            self.assertEqual(serie["viagens_observadas"], 220)
        finally:
            os.unlink(caminho)


class TestPaginaDoPainel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html, cls.painel = render.montar_html()

    def test_pagina_e_autocontida(self):
        """Requisito de demo: abre sem internet, em notebook de prefeitura."""
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        for atributo in ("src=", "href="):
            self.assertNotIn(atributo, self.html)

    def test_em_portugues_e_com_titulo(self):
        self.assertIn('<html lang="pt-BR">', self.html)
        self.assertIn("<title>MOBGOV", self.html)
        self.assertIn("Dimensionamento de frota", self.html)

    def test_traz_as_seis_manchetes_da_demo(self):
        for rotulo in ("Veículos a menos", "Economia por mês", "Economia por ano",
                       "Quilômetros por dia", "Diesel por dia", "Emissões evitadas"):
            self.assertIn(rotulo, self.html)

    def test_mostra_a_frase_obrigatoria_de_dimensionamento(self):
        atual = self.painel["atual"]["total_veiculos"]
        otim = self.painel["otimizada"]["total_veiculos"]
        self.assertIn(f"Sua frota atual: <b>{atual} veículos</b>", self.html)
        self.assertIn(f"<b>{otim} veículos</b>", self.html)

    def test_explica_a_multiviagem(self):
        self.assertIn("multiviagem", self.html)
        self.assertIn("Viagens por veículo", self.html)
        self.assertIn("Jornada média / máx", self.html)

    def test_declara_como_a_frota_atual_foi_estimada(self):
        """O 'antes' é gerado no município fictício — a página tem que dizer."""
        self.assertIn("não é um número escolhido a dedo", self.html)
        self.assertIn("vem do cadastro da secretaria", self.html)

    def test_bloco_de_elegibilidade_diz_a_origem_do_dado(self):
        if "Elegibilidade ao porta a porta" not in self.html:
            self.skipTest("relatorios/elegibilidade.json ainda não foi gerado")
        self.assertIn("Decisões com analista identificado", self.html)
        # fila simulada tem que aparecer como simulada, com selo na tela
        if (self.painel.get("elegibilidade") or {}).get("origem") != "operacao_real":
            self.assertIn("FILA SIMULADA", self.html)

    def test_bloco_de_elegibilidade_some_quando_nao_ha_relatorio(self):
        self.assertEqual(render.bloco_elegibilidade({}), "")
        self.assertEqual(render.bloco_elegibilidade(None), "")

    def test_traz_premissas_e_memoria_de_calculo(self):
        self.assertIn("Premissas e memória de cálculo", self.html)
        self.assertIn("Limitações declaradas desta versão", self.html)
        for passo in self.painel["memoria_calculo"]:
            self.assertIn(passo["passo"], self.html)

    def test_serie_de_aprendizado_declara_a_origem(self):
        """A regra que não pode quebrar: simulação nunca aparece como medição."""
        serie = aprendizado.carregar_serie()
        self.assertIn(serie["selo"], self.html)
        self.assertIn("Leia com atenção", self.html)
        if serie["origem"] != "operacao_real":
            self.assertNotIn("MEDIDO NA OPERAÇÃO", self.html)
        if serie["origem"] == "simulacao":
            self.assertIn("operação SIMULADA", self.html)

    def test_mostra_versao_do_modelo_e_rollbacks(self):
        serie = aprendizado.carregar_serie()
        if serie.get("versao_modelo"):
            self.assertIn("rollback", self.html.lower())

    def test_cenarios_embutidos_sao_json_valido(self):
        bruto = re.search(
            r'<script type="application/json" id="dados-cenarios">(.*?)</script>',
            self.html, re.S).group(1)
        cenarios = json.loads(bruto.replace("<\\/", "</"))
        self.assertGreater(len(cenarios), 10)
        self.assertEqual(len([c for c in cenarios if c["padrao"]]), 1)

    def test_funciona_sem_javascript(self):
        """Sem JS a página ainda mostra o cenário base e avisa disso."""
        self.assertIn("Simulação interativa indisponível sem JavaScript", self.html)
        self.assertIn(formato.reais(self.painel["economia"]["custo_mes"]), self.html)

    def test_tem_regras_de_impressao_para_o_pdf(self):
        self.assertIn("@media print", self.html)
        self.assertIn("size:A4 portrait", self.html)
        self.assertIn("Responsável pela conferência", self.html)

    def test_grafico_svg_sem_dimensao_fixa(self):
        """Precisa escalar em projetor 1024x768 e na impressão."""
        self.assertIn('<svg viewBox="0 0 720', self.html)
        self.assertNotIn("<svg width=", self.html)

    def test_gerar_grava_arquivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = render.gerar(saida=os.path.join(pasta, "p.html"))
            self.assertTrue(os.path.exists(destino))
            self.assertGreater(os.path.getsize(destino), 20_000)


class TestPainelComPremissasAlteradas(unittest.TestCase):
    def test_diesel_da_linha_de_comando_chega_na_pagina(self):
        html, painel = render.montar_html(diesel=9.0, dias=20)
        self.assertEqual(painel["premissas"]["preco_diesel_l"], 9.0)
        self.assertEqual(painel["premissas"]["dias_letivos_mes"], 20)
        self.assertIn("R$ 9,00/litro", html)
        base = ec.montar_painel(ec.carregar_relatorio(), com_cenarios=False)
        self.assertNotEqual(painel["economia"]["custo_mes"],
                            base["economia"]["custo_mes"])


if __name__ == "__main__":
    unittest.main()
