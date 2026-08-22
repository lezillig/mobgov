# -*- coding: utf-8 -*-
"""Testes do ciclo de aprendizado contínuo (Sprint 5).

Rodam sem OR-Tools e sem operação real: o simulador entrega observações com
uma VERDADE OCULTA e os testes verificam se o aprendizado a encontra — e, o
que importa tanto quanto, se ele recusa piorar.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aprendizado import aprender  # noqa: E402
from aprendizado.simulador import FATORES_REAIS, OperacaoSimulada  # noqa: E402

VIAGENS = [
    {"id": f"V{i:02d}", "turno": "manha", "paradas": [f"P{i}{k}" for k in range(4)],
     "alunos": 28, "cadeirantes": 1 if i % 5 == 0 else 0, "min_viagem": 30 + i}
    for i in range(12)
]
FAIXAS = {"manha": "pico_manha"}
ZONAS = {v["id"]: ("urbano" if i % 2 else "rural") for i, v in enumerate(VIAGENS)}


def semanas(quantidade=3, semente=7):
    sim = OperacaoSimulada(semente)
    return [sim.semana(VIAGENS, FAIXAS, ZONAS) for _ in range(quantidade)]


class TestSimulador(unittest.TestCase):
    def test_observacao_nao_carrega_dado_pessoal(self):
        obs = semanas(1)[0]
        permitido = {"viagem", "dia", "faixa", "zona", "chuva", "min_estimado",
                     "fator_plano", "min_realizado"}
        for t in obs["trechos"]:
            self.assertTrue(set(t) <= permitido, set(t) - permitido)

    def test_registra_o_fator_que_o_plano_usou(self):
        obs = semanas(1)[0]
        for t in obs["trechos"]:
            self.assertIn("fator_plano", t)
            self.assertGreater(t["fator_plano"], 0)

    def test_e_reprodutivel(self):
        a = semanas(1, semente=3)[0]["trechos"][:5]
        b = semanas(1, semente=3)[0]["trechos"][:5]
        self.assertEqual(a, b)

    def test_realizado_difere_do_estimado(self):
        """Se a simulação devolvesse o próprio plano, não haveria o que aprender."""
        obs = semanas(1)[0]
        diferentes = sum(1 for t in obs["trechos"]
                         if t["min_realizado"] != t["min_estimado"])
        self.assertGreater(diferentes, len(obs["trechos"]) * 0.5)


class TestEstimativas(unittest.TestCase):
    def test_encontra_a_verdade_oculta_do_transito(self):
        obs = semanas(4)
        acumulado = {"trechos": [t for s in obs for t in s["trechos"]]}
        fatores = aprender.estimar_fatores(acumulado["trechos"],
                                           aprender.modelo_inicial())
        for zona in ("urbano", "rural"):
            real = FATORES_REAIS["pico_manha"][zona]
            aprendido = fatores["pico_manha"][zona]
            # a chuva puxa a mediana um pouco para cima; 20% de folga
            self.assertGreater(aprendido, real * 0.85, zona)
            self.assertLess(aprendido, real * 1.20, zona)

    def test_faixa_sem_amostra_mantem_a_premissa(self):
        obs = semanas(1)[0]
        fatores = aprender.estimar_fatores(obs["trechos"],
                                           aprender.modelo_inicial())
        self.assertEqual(fatores["pico_tarde"],
                         aprender.FATORES_INICIAIS["pico_tarde"])

    def test_poucas_amostras_nao_trocam_premissa(self):
        obs = semanas(1)[0]
        poucos = obs["trechos"][:3]
        fatores = aprender.estimar_fatores(poucos, aprender.modelo_inicial())
        self.assertEqual(fatores["pico_manha"],
                         aprender.FATORES_INICIAIS["pico_manha"])

    def test_aprende_tempo_extra_de_parada(self):
        obs = semanas(2)
        paradas = [p for s in obs for p in s["paradas"]]
        extras = aprender.estimar_paradas(paradas)
        self.assertTrue(extras)
        self.assertTrue(all(v >= 0 for v in extras.values()))

    def test_aprende_ausencia_por_dia(self):
        obs = semanas(3)
        faltas = [f for s in obs for f in s["faltas"]]
        taxas = aprender.estimar_ausencias(faltas)
        self.assertEqual(len(taxas), 5)                 # cinco dias letivos
        self.assertGreater(float(taxas["4"]), float(taxas["1"]))  # sexta > terça


class TestCicloDeTreino(unittest.TestCase):
    def setUp(self):
        obs = semanas(6)
        self.treino = {chave: [x for s in obs[:4] for x in s[chave]]
                       for chave in ("trechos", "paradas", "faltas")}
        self.validacao = obs[4]
        self.teste = obs[5]

    def test_o_erro_cai_depois_de_aprender(self):
        inicial = aprender.modelo_inicial()
        antes = aprender.erro_medio(inicial, self.teste["trechos"])
        rodada = aprender.treinar_semana(inicial, self.treino, self.validacao)
        depois = aprender.erro_medio(rodada["modelo"], self.teste["trechos"])
        self.assertLess(depois, antes)

    def test_modelo_promovido_ganha_versao(self):
        rodada = aprender.treinar_semana(aprender.modelo_inicial(),
                                         self.treino, self.validacao)
        self.assertTrue(rodada["promovido"])
        self.assertEqual(rodada["versao"], 1)

    def test_rollback_quando_o_candidato_piora(self):
        """Modelo já bom + observação envenenada = o sistema tem que recusar."""
        bom = aprender.treinar_semana(aprender.modelo_inicial(),
                                      self.treino, self.validacao)["modelo"]
        envenenado = {
            "trechos": [dict(t, min_realizado=t["min_realizado"] * 4)
                        for t in self.treino["trechos"]],
            "paradas": self.treino["paradas"], "faltas": self.treino["faltas"],
        }
        rodada = aprender.treinar_semana(bom, envenenado, self.validacao)
        self.assertFalse(rodada["promovido"])
        self.assertEqual(rodada["modelo"].versao, bom.versao)
        self.assertIn("erro subiria", rodada["motivo_rollback"])

    def test_acuracia_de_ausencia_e_agregada_por_dia(self):
        rodada = aprender.treinar_semana(aprender.modelo_inicial(),
                                         self.treino, self.validacao)
        self.assertGreater(rodada["acuracia_ausencia_pct"], 70)

    def test_exemplos_falam_portugues_e_citam_numeros(self):
        rodada = aprender.treinar_semana(aprender.modelo_inicial(),
                                         self.treino, self.validacao)
        exemplos = aprender.exemplos_do_aprendizado(
            rodada["modelo"], aprender.modelo_inicial(),
            rodada["modelo"].parada_extra_por_ponto,
            rodada["modelo"].ausencia_por_dia)
        self.assertTrue(exemplos)
        self.assertTrue(any("planejamento supunha" in e for e in exemplos))


if __name__ == "__main__":
    unittest.main()
