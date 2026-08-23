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


class TestTFD(unittest.TestCase):
    """A van que sai de madrugada para a capital."""

    @classmethod
    def setUpClass(cls):
        from saude import tfd
        cls.tfd = tfd
        cls.autorizacoes = demanda_mod.gerar_autorizacoes_tfd("2026-08-24")
        cls.veiculo = tfd.VeiculoTFD("TFD1", "Van TFD 15", 15,
                                     posicoes_cadeirante=2)
        cls.viagem = tfd.montar_viagem(cls.autorizacoes, "2026-08-24",
                                       cls.veiculo, demanda_mod.GARAGEM)

    def test_acompanhante_e_direito_com_motivo_escrito(self):
        tem, motivo = self.tfd.direito_a_acompanhante(15)
        self.assertTrue(tem)
        self.assertIn("menor", motivo)
        tem, motivo = self.tfd.direito_a_acompanhante(70)
        self.assertTrue(tem)
        self.assertTrue(motivo)
        tem, motivo = self.tfd.direito_a_acompanhante(40)
        self.assertFalse(tem)
        self.assertEqual(motivo, "")

    def test_incapacidade_da_direito_em_qualquer_idade(self):
        tem, motivo = self.tfd.direito_a_acompanhante(35, incapacidade=True)
        self.assertTrue(tem)
        self.assertIn("incapacidade", motivo)

    def test_acompanhante_ocupa_vaga_de_verdade(self):
        """Van que 'esquece' o acompanhante deixa gente na calçada às 4h."""
        ocupacao = self.viagem["ocupacao"]
        self.assertEqual(
            ocupacao["vagas_usadas"],
            ocupacao["pacientes"] + ocupacao["acompanhantes"])
        self.assertLessEqual(ocupacao["vagas_usadas"], self.veiculo.lugares)

    def test_cadeira_e_limite_proprio(self):
        self.assertLessEqual(self.viagem["ocupacao"]["cadeirantes"],
                             self.veiculo.posicoes_cadeirante)

    def test_ninguem_some_da_fila(self):
        total = (self.viagem["ocupacao"]["pacientes"]
                 + len(self.viagem["fila"]))
        self.assertEqual(total, len(self.autorizacoes))
        for item in self.viagem["fila"]:
            self.assertTrue(item["posicao"])
            self.assertTrue(item["motivo"])
            self.assertTrue(item["o_que_fazer"])

    def test_fila_e_por_prioridade_e_data_de_autorizacao(self):
        """A fila precisa ser defensável: não é telefonema, é data."""
        ordenadas = sorted(self.autorizacoes, key=self.tfd._ordem_da_fila)
        prioridades = [a.prioridade for a in ordenadas]

        # nenhum eletivo entra antes de um vital
        vitais = [i for i, p in enumerate(prioridades) if p == "vital"]
        eletivos = [i for i, p in enumerate(prioridades) if p == "eletivo"]
        self.assertTrue(vitais and eletivos, "amostra sem os dois casos")
        self.assertLess(max(vitais), min(eletivos))

        # dentro da mesma prioridade, quem autorizou antes vai antes
        datas = [a.autorizada_em for a in ordenadas
                 if a.prioridade == "vital"]
        self.assertEqual(datas, sorted(datas))

    def test_espera_no_destino_e_medida_por_pessoa(self):
        """O número que ninguém mede: quantas horas no saguão."""
        self.assertIn("espera", self.viagem)
        self.assertGreater(self.viagem["espera"]["maxima_min"], 0)
        for p in self.viagem["passageiros"]:
            self.assertGreaterEqual(p["espera_no_destino_min"], 0)
        # o último liberado espera zero; é ele que define o retorno
        self.assertEqual(min(p["espera_no_destino_min"]
                             for p in self.viagem["passageiros"]), 0)

    def test_retorno_e_do_ultimo_liberado(self):
        liberacoes = [p["liberado_previsto"]
                      for p in self.viagem["passageiros"]]
        self.assertTrue(self.viagem["retorno_previsto"] >= max(liberacoes))

    def test_viagem_longa_avisa_sobre_a_jornada(self):
        """15 h de amplitude não fecham na Lei 13.103 — o sistema diz isso."""
        if self.viagem["duracao_total_min"] > 14 * 60:
            self.assertTrue(any("13.103" in a for a in self.viagem["alertas"]))

    def test_dividir_retorno_mostra_o_ganho_sem_decidir(self):
        divisao = self.tfd.dividir_retorno(self.viagem)
        self.assertLess(divisao["espera_media_depois_min"],
                        divisao["espera_media_antes_min"])
        self.assertGreater(divisao["horas_de_espera_poupadas"], 0)
        self.assertTrue(divisao["custo"])

    def test_custo_separa_rodagem_de_ajuda_de_custo(self):
        custos = self.viagem["custos"]
        self.assertAlmostEqual(
            custos["total"],
            custos["custo_rodagem"] + custos["ajuda_de_custo_total"], places=2)
        self.assertEqual(custos["pessoas_com_ajuda"],
                         self.viagem["ocupacao"]["vagas_usadas"])

    def test_dia_sem_autorizacao_nao_inventa_viagem(self):
        vazia = self.tfd.montar_viagem(self.autorizacoes, "2030-01-01",
                                       self.veiculo, demanda_mod.GARAGEM)
        self.assertEqual(vazia["passageiros"], [])
        self.assertEqual(vazia["ocupacao"]["vagas_usadas"], 0)

    def test_especialidade_nao_e_diagnostico(self):
        for a in self.autorizacoes:
            self.assertIn(a.especialidade, demanda_mod.ESPECIALIDADES)


if __name__ == "__main__":
    unittest.main()
