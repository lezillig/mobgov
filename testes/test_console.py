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

    def test_em_portugues_com_as_abas_do_dia(self):
        self.assertIn('<html lang="pt-BR">', self.html)
        for aba in ("Hoje", "Elegibilidade", "Perguntar ao sistema", "Economia"):
            self.assertIn(f">{aba}<", self.html)

    def test_aba_de_equipe_so_existe_quando_o_plano_separa_esse_custo(self):
        """No escolar a prefeitura contrata veículo COM motorista."""
        self.assertNotIn('data-aba="equipe"', self.html)
        self.assertEqual(console.aba_equipe({"equipe": None}), "")

    def test_aba_de_equipe_mostra_a_escala_e_as_regras_usadas(self):
        dados = dict(self.dados, equipe={
            "resumo": {"motoristas": 3, "blocos": 6, "jornada_media_min": 250,
                       "com_dupla_pegada": 2, "escalas_com_problema": 0,
                       "ocupacao_da_jornada_pct": 52.1,
                       "por_turno": {"t1": 2, "t2": 1}},
            "regras": {"jornada_normal_min": 480, "hora_extra_max_min": 120,
                       "direcao_continua_max_min": 330,
                       "parada_obrigatoria_min": 30,
                       "intervalo_refeicao_min": 60, "interjornada_min": 660,
                       "amplitude_max_min": 840, "permite_dupla_pegada": True},
            "custo_motorista_mes": 7800.0, "custo_equipe_mes": 23400.0,
            "motoristas": [{"id": "M01", "inicio": "04h30", "fim": "14h20",
                            "jornada_min": 370, "amplitude_min": 590,
                            "turnos": ["t1", "t2"], "veiculos": ["V1", "V2"],
                            "dupla_pegada": True, "hora_extra_min": 0,
                            "problemas": []}]})
        html = console.aba_equipe(dados)
        self.assertIn("M01", html)
        self.assertIn("dupla pegada", html)
        self.assertIn("Interjornada", html)     # a regra aparece na tela
        self.assertIn("11h00", html)            # 660 min
        self.assertIn("6h10", html)             # jornada de 370 min

    def test_escala_com_problema_e_destacada(self):
        dados = dict(self.dados, equipe={
            "resumo": {"motoristas": 1, "blocos": 1, "jornada_media_min": 700,
                       "com_dupla_pegada": 0, "escalas_com_problema": 1,
                       "ocupacao_da_jornada_pct": 145.8, "por_turno": {}},
            "regras": {}, "custo_motorista_mes": 0, "custo_equipe_mes": 0,
            "motoristas": [{"id": "M01", "inicio": "04h00", "fim": "18h00",
                            "jornada_min": 700, "amplitude_min": 840,
                            "turnos": ["t1"], "veiculos": ["V1"],
                            "dupla_pegada": False, "hora_extra_min": 220,
                            "problemas": ["Jornada de 11h40, acima de 10h."]}]})
        html = console.aba_equipe(dados)
        self.assertIn("atrasada", html)          # a linha fica marcada
        self.assertIn("acima de 10h", html)
        self.assertIn("kpi piora", html)

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
