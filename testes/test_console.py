# -*- coding: utf-8 -*-
"""
Testes do console de operação.

O console é a tela que fica aberta na secretaria o dia inteiro, então as
garantias são as mesmas do painel: abre sem internet, todo número vem do
motor, e o que é simulação aparece como simulação.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import console  # noqa: E402


class TestConsole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html, cls.dados = console.montar_html()

    def test_pagina_e_autocontida(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        for atributo in ("src=", "href="):
            self.assertNotIn(atributo, self.html)

    def test_em_portugues_com_as_quatro_abas(self):
        self.assertIn('<html lang="pt-BR">', self.html)
        for aba in ("Hoje", "Elegibilidade", "Perguntar ao sistema", "Economia"):
            self.assertIn(f">{aba}<", self.html)

    def test_frota_do_dia_e_o_pior_turno_nao_a_soma(self):
        """A armadilha do projeto: somar os turnos daria 41 numa frota de 23."""
        frota = self.dados["painel"]["otimizada"]["total_veiculos"]
        escalas = len(self.dados["plano"]["frota_otimizada"]["veiculos"])
        self.assertLess(frota, escalas)
        self.assertIn(f"{frota} veículos", self.html)
        self.assertIn(f"{escalas} escalas", self.html)

    def test_respostas_do_assistente_sao_calculadas_no_servidor(self):
        self.assertEqual(len(self.dados["respostas"]), len(console.PERGUNTAS))
        for resposta in self.dados["respostas"]:
            self.assertTrue(resposta["resposta"].strip())
            self.assertNotIn("erro", resposta["resposta"][:30].lower())

    def test_numero_da_manchete_bate_com_o_motor(self):
        economia = self.dados["painel"]["economia"]["custo_mes"]
        from painel.formato import reais_curto
        self.assertIn(reais_curto(economia), self.html)

    def test_fila_simulada_aparece_como_simulada(self):
        el = self.dados["elegibilidade"]
        if el.get("origem") != "operacao_real":
            self.assertIn("FILA SIMULADA", self.html)

    def test_aba_de_elegibilidade_some_sem_relatorio(self):
        vazio = dict(self.dados, elegibilidade={})
        self.assertIn("Nenhum pedido ainda", console.aba_elegibilidade(vazio))

    def test_console_abre_sem_operacao_nenhuma(self):
        """Município que ainda não ligou o app do motorista também usa a tela."""
        sem_eventos = dict(self.dados, eventos=[],
                           resumo_eventos={"eventos": 0, "por_tipo": {},
                                           "motoristas": 0},
                           faltas={"dia": "2026-08-22", "faltas": 0,
                                   "avisos_desfeitos": 0, "por_viagem": {}},
                           rodadas={})
        html = console.aba_hoje(sem_eventos)
        self.assertIn("Nenhum evento recebido", html)
        self.assertIn("Nenhuma família avisou falta", html)


if __name__ == "__main__":
    unittest.main()
