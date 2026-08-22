# -*- coding: utf-8 -*-
"""Testes da camada de cálculo do painel de economia (Sprint 2).

Rodar da raiz do repositório:  python -m unittest discover -s testes -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import economia as ec  # noqa: E402


class BaseRelatorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rel = ec.carregar_relatorio()
        cls.premissas = ec.premissas_do_relatorio(cls.rel)
        cls.tipos = cls.rel["premissas"]["custos_por_tipo"]


class TestCustoPorKm(BaseRelatorio):
    def test_decomposicao_reproduz_custo_original(self):
        """Com o diesel do relatório, combustível + manutenção tem que dar
        exatamente o custo_km que o motor de dimensionamento usou."""
        for tipo in self.tipos.values():
            self.assertAlmostEqual(
                ec.custo_km(tipo, self.premissas), float(tipo["custo_km"]), places=6)

    def test_manutencao_nunca_negativa(self):
        for tipo in self.tipos.values():
            self.assertGreaterEqual(
                ec.manutencao_km(tipo, self.premissas.preco_diesel_base_l), 0.0)

    def test_diesel_mais_caro_encarece_o_km(self):
        caro = self.premissas.substituir(preco_diesel_l=9.0)
        for tipo in self.tipos.values():
            self.assertGreater(ec.custo_km(tipo, caro),
                               ec.custo_km(tipo, self.premissas))


class TestAvaliacaoDeFrota(BaseRelatorio):
    def setUp(self):
        self.painel = ec.montar_painel(self.rel, self.premissas, com_cenarios=False)

    def test_custo_total_e_a_soma_das_partes(self):
        for frota in (self.painel["atual"], self.painel["otimizada"]):
            self.assertAlmostEqual(
                frota["custo_mes"],
                frota["custo_fixo_mes"] + frota["custo_variavel_mes"], places=2)
            self.assertAlmostEqual(
                frota["custo_mes"] * ec.MESES_POR_ANO, frota["custo_ano"], places=0)

    def test_km_da_frota_otimizada_vem_das_rotas(self):
        """km/dia = soma do km das rotas × viagens por dia (ida e volta)."""
        esperado = sum(r["km_viagem"] for r in self.rel["frota_otimizada"]["rotas"])
        esperado *= self.premissas.viagens_por_dia
        self.assertAlmostEqual(self.painel["otimizada"]["km_dia"], esperado, places=0)

    def test_km_da_frota_atual_e_o_declarado_pela_prefeitura(self):
        self.assertAlmostEqual(self.painel["atual"]["km_dia"],
                               self.rel["frota_atual"]["km_dia"], places=0)

    def test_formula_de_emissoes(self):
        for frota in (self.painel["atual"], self.painel["otimizada"]):
            esperado = (frota["litros_dia"] * self.premissas.dias_letivos_mes
                        * ec.MESES_POR_ANO * self.premissas.fator_co2_kg_l / 1000)
            self.assertAlmostEqual(frota["tco2_ano"], esperado, places=0)

    def test_assentos_cobrem_a_demanda(self):
        """Frota menor não pode significar aluno sem assento."""
        self.assertGreaterEqual(self.painel["otimizada"]["assentos"],
                                self.rel["demanda"]["alunos"])


class TestEconomia(BaseRelatorio):
    def setUp(self):
        self.painel = ec.montar_painel(self.rel, self.premissas, com_cenarios=False)
        self.economia = self.painel["economia"]

    def test_economia_e_a_diferenca_entre_as_duas_frotas(self):
        self.assertAlmostEqual(
            self.economia["custo_mes"],
            self.painel["atual"]["custo_mes"] - self.painel["otimizada"]["custo_mes"],
            places=2)

    def test_meta_do_mvp_reducao_de_frota(self):
        """Métrica de sucesso declarada no prompt-mestre: ≥ 20% de redução."""
        self.assertGreaterEqual(self.economia["reducao_frota_pct"], 20.0)

    def test_indicadores_da_manchete_sao_positivos(self):
        for chave in ("veiculos", "custo_mes", "custo_ano", "km_dia",
                      "litros_dia", "tco2_ano"):
            self.assertGreater(self.economia[chave], 0, chave)

    def test_diesel_mais_caro_aumenta_a_economia(self):
        """A frota otimizada roda menos km, então diesel caro amplia a economia."""
        caro = ec.montar_painel(
            self.rel, self.premissas.substituir(preco_diesel_l=9.0),
            com_cenarios=False)
        self.assertGreater(caro["economia"]["custo_mes"], self.economia["custo_mes"])

    def test_qualidade_do_servico_dentro_dos_limites(self):
        q = self.painel["qualidade"]
        self.assertLessEqual(q["tempo_max_rota_min"],
                             self.premissas.tempo_max_trajeto_min)
        self.assertLessEqual(q["ocupacao_max_pct"], 100)
        self.assertTrue(q["atende_cadeirantes"])


class TestCenarios(BaseRelatorio):
    def test_cenario_padrao_bate_com_o_relatorio(self):
        cenarios = ec.grade_de_cenarios(self.rel, self.premissas)
        padroes = [c for c in cenarios if c["padrao"]]
        self.assertEqual(len(padroes), 1)
        base = ec.montar_painel(self.rel, self.premissas, com_cenarios=False)
        self.assertAlmostEqual(padroes[0]["economia_mes"],
                               base["economia"]["custo_mes"], places=2)

    def test_grade_cobre_as_combinacoes(self):
        cenarios = ec.grade_de_cenarios(
            self.rel, self.premissas, precos_diesel=[5.0, 6.10, 8.0],
            dias_letivos=[20, 22])
        self.assertEqual(len(cenarios), 6)
        self.assertEqual(len({(c["preco_diesel_l"], c["dias_letivos_mes"])
                              for c in cenarios}), 6)

    def test_mais_dias_letivos_aumenta_o_custo_das_duas_frotas(self):
        curto = ec.montar_painel(
            self.rel, self.premissas.substituir(dias_letivos_mes=18),
            com_cenarios=False)
        longo = ec.montar_painel(
            self.rel, self.premissas.substituir(dias_letivos_mes=22),
            com_cenarios=False)
        self.assertGreater(longo["atual"]["custo_mes"], curto["atual"]["custo_mes"])
        self.assertGreater(longo["otimizada"]["custo_mes"],
                           curto["otimizada"]["custo_mes"])


class TestPremissas(BaseRelatorio):
    def test_substituir_ignora_valores_nulos(self):
        igual = self.premissas.substituir(preco_diesel_l=None, dias_letivos_mes=None)
        self.assertEqual(igual, self.premissas)

    def test_substituir_nao_muda_o_original(self):
        novo = self.premissas.substituir(preco_diesel_l=8.0)
        self.assertEqual(self.premissas.preco_diesel_l, 6.10)
        self.assertEqual(novo.preco_diesel_l, 8.0)
        self.assertEqual(novo.preco_diesel_base_l, self.premissas.preco_diesel_base_l)

    def test_memoria_de_calculo_descreve_todos_os_passos(self):
        painel = ec.montar_painel(self.rel, self.premissas, com_cenarios=False)
        passos = painel["memoria_calculo"]
        self.assertGreaterEqual(len(passos), 6)
        for p in passos:
            self.assertTrue(p["passo"] and p["formula"] and p["valores"])


if __name__ == "__main__":
    unittest.main()
