# -*- coding: utf-8 -*-
"""
Testes do vertical de saúde (transporte sanitário).

O que protegem é o que diferencia transporte de paciente de transporte de
aluno:

1. **prioridade clínica não some** — hemodiálise que não coube é internação
   na quinta, e não pode sair na mesma linha que uma consulta remarcável;
2. **volta sem hora não entra no plano da manhã** — planejar hora que
   ninguém sabe é deixar veículo parado no estacionamento do hospital;
3. **maca não compartilha veículo** — remoção é viagem dedicada, e a conta
   de assentos sozinha deixaria duas macas numa van;
4. **nada clínico atravessa para a rota** — o motorista sabe que vai de
   maca, nunca por quê.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from saude import demanda as demanda_mod  # noqa: E402
from saude.tratamento import (  # noqa: E402
    ASSENTOS_DA_MACA, PRIORIDADES, TEMPO_MAX_EM_JEJUM_MIN, Tratamento,
    pedidos_do_dia,
)

UNIDADES = {"U1": (-21.128, -47.772), "U2": (-21.146, -47.792)}


def tratamento(tipo, **extra):
    base = dict(id="T1", paciente_id="PA1", unidade_id="U1", tipo=tipo,
                origem=(-21.15, -47.80), dias_da_semana=(0, 2, 4),
                hora_chegada_min=6 * 60)
    base.update(extra)
    return Tratamento(**base)


class TestPrioridade(unittest.TestCase):
    def test_hemodialise_nao_e_remarcavel(self):
        """Faltar hemodiálise é internação — o sistema precisa saber disso."""
        t = tratamento("hemodialise")
        self.assertEqual(t.prioridade, "vital")
        self.assertFalse(t.remarcavel)

    def test_consulta_e_remarcavel(self):
        t = tratamento("consulta")
        self.assertEqual(t.prioridade, "eletivo")
        self.assertTrue(t.remarcavel)

    def test_toda_prioridade_explica_o_que_acontece_se_faltar(self):
        for chave, regra in PRIORIDADES.items():
            self.assertTrue(regra["rotulo"], chave)
            self.assertTrue(regra["explicacao"], chave)
            self.assertIn("remarcavel", regra)

    def test_prioridade_chega_no_pedido(self):
        agenda = pedidos_do_dia([tratamento("hemodialise")], 0, UNIDADES)
        self.assertEqual(agenda["ida"][0].prioridade, "vital")


class TestVolta(unittest.TestCase):
    def test_hemodialise_tem_volta_planejada(self):
        agenda = pedidos_do_dia([tratamento("hemodialise")], 0, UNIDADES)
        self.assertEqual(len(agenda["volta_planejada"]), 1)
        self.assertEqual(len(agenda["volta_por_chamada"]), 0)

    def test_consulta_tem_volta_por_chamada(self):
        """Consulta acaba quando o médico libera — planejar a hora é inventar."""
        agenda = pedidos_do_dia([tratamento("consulta", dias_da_semana=(0,))],
                                0, UNIDADES)
        self.assertEqual(len(agenda["volta_planejada"]), 0)
        self.assertEqual(len(agenda["volta_por_chamada"]), 1)

    def test_volta_por_chamada_fica_fora_do_planejavel(self):
        agenda = pedidos_do_dia([tratamento("consulta", dias_da_semana=(0,))],
                                0, UNIDADES)
        self.assertEqual(agenda["resumo"]["pedidos_planejaveis"], 1)
        self.assertEqual(agenda["resumo"]["voltas_por_chamada"], 1)

    def test_volta_sai_depois_da_sessao(self):
        t = tratamento("hemodialise", hora_chegada_min=6 * 60)
        agenda = pedidos_do_dia([t], 0, UNIDADES)
        volta = agenda["volta_planejada"][0]
        self.assertEqual(volta.janela_chegada[0],
                         6 * 60 + t.duracao_sessao_min)
        # a volta é do hospital para a casa, não o contrário
        self.assertEqual(volta.origem, UNIDADES["U1"])
        self.assertEqual(volta.destino, t.origem)


class TestRestricoesOperacionais(unittest.TestCase):
    def test_maca_ocupa_mais_de_um_assento(self):
        agenda = pedidos_do_dia([tratamento("consulta", maca=True,
                                            dias_da_semana=(0,))], 0, UNIDADES)
        self.assertEqual(agenda["ida"][0].assentos, ASSENTOS_DA_MACA)

    def test_maca_com_acompanhante_nao_cabe_duas_vezes_na_ambulancia(self):
        """Duas macas na mesma ambulância não existe na rua."""
        capacidade = 4          # AMBTRANS
        com_acompanhante = ASSENTOS_DA_MACA + 1
        self.assertLessEqual(com_acompanhante, capacidade)
        self.assertGreater(2 * ASSENTOS_DA_MACA, capacidade)

    def test_cadeirante_ocupa_posicao_de_cadeira_nao_assento(self):
        agenda = pedidos_do_dia([tratamento("consulta", cadeirante=True,
                                            dias_da_semana=(0,))], 0, UNIDADES)
        pedido = agenda["ida"][0]
        self.assertEqual(pedido.posicoes_cadeira, 1)
        self.assertEqual(pedido.assentos, 0)

    def test_jejum_aperta_o_tempo_a_bordo(self):
        agenda = pedidos_do_dia([tratamento("exame", jejum=True,
                                            dias_da_semana=(0,))], 0, UNIDADES)
        self.assertEqual(agenda["ida"][0].tempo_max_bordo_min,
                         TEMPO_MAX_EM_JEJUM_MIN)

    def test_sem_jejum_usa_o_limite_geral(self):
        agenda = pedidos_do_dia([tratamento("exame", dias_da_semana=(0,))],
                                0, UNIDADES)
        self.assertIsNone(agenda["ida"][0].tempo_max_bordo_min)


class TestSigilo(unittest.TestCase):
    def test_nada_clinico_no_pedido(self):
        """Diagnóstico fica no processo; para a rota vai a necessidade."""
        agenda = pedidos_do_dia([tratamento("quimioterapia",
                                            dias_da_semana=(0,))], 0, UNIDADES)
        campos = vars(agenda["ida"][0]).keys()
        for proibido in ("diagnostico", "cid", "laudo", "doenca", "nome"):
            self.assertNotIn(proibido, campos)

    def test_paciente_e_pseudonimo(self):
        tratamentos = demanda_mod.gerar_tratamentos()
        for t in tratamentos[:20]:
            self.assertTrue(t.paciente_id.startswith("PA"))
            self.assertNotIn(" ", t.paciente_id)

    def test_observacao_e_operacional(self):
        for observacao in demanda_mod.OBSERVACOES:
            texto = observacao.lower()
            for clinico in ("câncer", "diabet", "renal", "cid"):
                self.assertNotIn(clinico, texto)


class TestAgendaDaSemana(unittest.TestCase):
    def test_hemodialise_acontece_tres_vezes_na_semana(self):
        t = tratamento("hemodialise", dias_da_semana=(0, 2, 4))
        dias = [d for d in range(7) if t.acontece_em(d)]
        self.assertEqual(dias, [0, 2, 4])

    def test_dia_sem_tratamento_nao_gera_pedido(self):
        agenda = pedidos_do_dia([tratamento("hemodialise",
                                            dias_da_semana=(0, 2, 4))],
                                1, UNIDADES)
        self.assertEqual(agenda["ida"], [])

    def test_unidade_desconhecida_nao_vira_viagem_para_lugar_nenhum(self):
        agenda = pedidos_do_dia([tratamento("consulta", unidade_id="U9",
                                            dias_da_semana=(0,))], 0, UNIDADES)
        self.assertEqual(agenda["ida"], [])

    def test_demanda_sintetica_e_estavel(self):
        a = demanda_mod.gerar_tratamentos()
        b = demanda_mod.gerar_tratamentos()
        self.assertEqual([t.id for t in a], [t.id for t in b])
        self.assertEqual([t.origem for t in a], [t.origem for t in b])

    def test_quem_vai_de_maca_nao_e_tambem_cadeirante(self):
        for t in demanda_mod.gerar_tratamentos():
            self.assertFalse(t.maca and t.cadeirante, t.id)


if __name__ == "__main__":
    unittest.main()
