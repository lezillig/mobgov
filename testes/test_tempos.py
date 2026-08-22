# -*- coding: utf-8 -*-
"""Testes da camada de tempos com trânsito variável (Sprint 4)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import tempos  # noqa: E402

PONTOS = [(-21.150, -47.800), (-21.100, -47.770), (-21.210, -47.830)]


class TestFaixaHoraria(unittest.TestCase):
    def test_faixa_normal(self):
        f = tempos.FaixaHoraria("t", "Teste", 6 * 60, 8 * 60, 1.2, 1.1)
        self.assertTrue(f.contem(7 * 60))
        self.assertFalse(f.contem(9 * 60))

    def test_faixa_que_vira_o_dia(self):
        f = tempos.FaixaHoraria("n", "Noite", 19 * 60, 6 * 60, 0.9, 0.9)
        self.assertTrue(f.contem(23 * 60))
        self.assertTrue(f.contem(3 * 60))
        self.assertFalse(f.contem(12 * 60))

    def test_todo_minuto_do_dia_cai_em_alguma_faixa(self):
        perfil = tempos.PerfilDeTransito()
        for minuto in range(0, 1440, 7):
            self.assertIsNotNone(perfil.faixa(minuto))


class TestPerfilDeTransito(unittest.TestCase):
    def setUp(self):
        self.perfil = tempos.PerfilDeTransito()

    def test_pico_da_manha_e_pior_que_o_meio_do_dia(self):
        self.assertGreater(self.perfil.fator(7 * 60, "urbano"),
                           self.perfil.fator(14 * 60, "urbano"))

    def test_zona_urbana_sofre_mais_que_a_rural_no_pico(self):
        self.assertGreater(self.perfil.fator(7 * 60, "urbano"),
                           self.perfil.fator(7 * 60, "rural"))

    def test_sem_arquivo_os_fatores_sao_estimados(self):
        self.assertTrue(self.perfil.e_estimado)
        self.assertIn("estimado", self.perfil.explicar(7 * 60, "urbano"))

    def test_fatores_medidos_substituem_os_estimados(self):
        medidos = {"origem": "gps_real",
                   "fatores": {"pico_manha": {"urbano": 1.9, "rural": 1.4}},
                   "amostras": 5000}
        perfil = tempos.PerfilDeTransito(aprendidos=medidos)
        self.assertFalse(perfil.e_estimado)
        self.assertEqual(perfil.fator(7 * 60, "urbano"), 1.9)
        self.assertIn("GPS real", perfil.explicar(7 * 60, "urbano"))
        # faixa sem medição continua com o valor estimado
        self.assertEqual(perfil.fator(14 * 60, "urbano"),
                         tempos.PerfilDeTransito().fator(14 * 60, "urbano"))

    def test_carregar_fatores_de_arquivo(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump({"fatores": {"pico_manha": {"urbano": 1.5}}}, f)
            caminho = f.name
        try:
            dados = tempos.carregar_fatores_aprendidos(caminho)
            self.assertEqual(dados["origem"], "gps_real")
        finally:
            os.unlink(caminho)

    def test_sem_arquivo_devolve_estimado(self):
        dados = tempos.carregar_fatores_aprendidos("/nao/existe.json")
        self.assertEqual(dados["origem"], "estimado")


class TestProvedores(unittest.TestCase):
    def test_haversine_e_simetrico_e_positivo(self):
        dist, tempo = tempos.ProvedorHaversine().matriz(PONTOS)
        for i in range(len(PONTOS)):
            self.assertEqual(dist[i][i], 0.0)
            for j in range(len(PONTOS)):
                if i != j:
                    self.assertGreater(dist[i][j], 0)
                    self.assertAlmostEqual(dist[i][j], dist[j][i], places=6)
                    self.assertGreaterEqual(tempo[i][j], 1)

    def test_sem_horario_o_transito_nao_muda_nada(self):
        base = tempos.ProvedorHaversine()
        com = tempos.ComTransito(base)
        _, t1 = base.matriz(PONTOS)
        _, t2 = com.matriz(PONTOS, partida_min=None)
        self.assertEqual(t1, t2)

    def test_no_pico_da_manha_a_viagem_demora_mais(self):
        com = tempos.ComTransito(tempos.ProvedorHaversine())
        zonas = ["urbano", "rural", "rural"]
        _, pico = com.matriz(PONTOS, partida_min=7 * 60, zonas=zonas)
        _, calmo = com.matriz(PONTOS, partida_min=14 * 60, zonas=zonas)
        self.assertGreater(pico[0][1], calmo[0][1])

    def test_transito_nao_altera_distancia(self):
        com = tempos.ComTransito(tempos.ProvedorHaversine())
        d1, _ = com.matriz(PONTOS, partida_min=7 * 60)
        d2, _ = com.matriz(PONTOS, partida_min=14 * 60)
        self.assertEqual(d1, d2)

    def test_trecho_que_toca_o_urbano_sofre_o_fator_urbano(self):
        com = tempos.ComTransito(tempos.ProvedorHaversine())
        _, misto = com.matriz(PONTOS, partida_min=7 * 60,
                              zonas=["urbano", "rural", "rural"])
        _, so_rural = com.matriz(PONTOS, partida_min=7 * 60,
                                 zonas=["rural", "rural", "rural"])
        self.assertGreater(misto[0][1], so_rural[0][1])

    def test_zona_de(self):
        self.assertEqual(tempos.zona_de((-21.150, -47.800)), "urbano")
        self.assertEqual(tempos.zona_de((-21.300, -47.900)), "rural")

    def test_provedor_externo_avisa_que_nao_esta_ligado(self):
        with self.assertRaises(NotImplementedError):
            tempos.ProvedorExterno("osrm").matriz(PONTOS)

    def test_provedor_externo_com_chamador(self):
        def falso(locais, partida_min):
            n = len(locais)
            return [[1.0] * n] * n, [[2] * n] * n
        d, t = tempos.ProvedorExterno("teste", falso).matriz(PONTOS, 7 * 60)
        self.assertEqual(t[0][1], 2)

    def test_provedor_padrao_traz_transito(self):
        self.assertIsInstance(tempos.provedor_padrao(), tempos.ComTransito)
        self.assertIsInstance(tempos.provedor_padrao(com_transito=False),
                              tempos.ProvedorHaversine)


if __name__ == "__main__":
    unittest.main()
