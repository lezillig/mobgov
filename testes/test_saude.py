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


class TestAcompanhamento(unittest.TestCase):
    """O que o paciente vê e o que ele consegue fazer."""

    def setUp(self):
        from saude import acompanhamento
        self.ac = acompanhamento
        self.tratamentos = [tratamento("consulta", dias_da_semana=(0,),
                                       hora_chegada_min=10 * 60),
                            tratamento("hemodialise", id="T2",
                                       paciente_id="PA2",
                                       dias_da_semana=(0, 2, 4),
                                       hora_chegada_min=6 * 60)]

    def situacao(self, paciente, eventos=None, agora=5 * 60):
        return self.ac.situacao(paciente, dia_da_semana=0, dia="2026-08-24",
                                tratamentos=self.tratamentos,
                                eventos=eventos or [], agora_min=agora)

    def test_previsao_nunca_e_medida_por_otimismo(self):
        """Errar uma vez custa a confiança do ano."""
        s = self.situacao("PA1")
        self.assertEqual(s["ida"]["selo"]["rotulo"], "planejado")
        medido = self.situacao("PA1", eventos=[
            {"tipo": "ping", "paciente": "PA1", "em": "2026-08-24T09:00:00"}])
        self.assertEqual(medido["ida"]["selo"]["rotulo"], "medido")

    def test_volta_sem_hora_e_dita_como_sem_hora(self):
        s = self.situacao("PA1")
        self.assertEqual(s["volta"]["tipo"], "por_chamada")
        self.assertIsNone(s["volta"]["hora"])
        self.assertIn("liberar", s["volta"]["explicacao"])

    def test_volta_com_hora_aparece_com_hora(self):
        s = self.situacao("PA2")
        self.assertEqual(s["volta"]["tipo"], "com_hora")
        self.assertNotEqual(s["volta"]["hora"], "—")

    def test_botao_de_liberado_so_existe_quando_faz_sentido(self):
        """Botão que não faz efeito engana quem está esperando."""
        com_chamada = [a["id"] for a in self.situacao("PA1")["acoes"]]
        self.assertIn("liberado", com_chamada)
        com_hora = [a["id"] for a in self.situacao("PA2")["acoes"]]
        self.assertNotIn("liberado", com_hora)

    def test_liberado_some_depois_de_avisar(self):
        eventos = [{"tipo": "liberado", "paciente": "PA1",
                    "em": "2026-08-24T11:30:00"}]
        s = self.situacao("PA1", eventos=eventos)
        self.assertTrue(s["volta"]["liberado"])
        self.assertNotIn("liberado", [a["id"] for a in s["acoes"]])

    def test_avisar_cedo_libera_vaga_e_em_cima_da_hora_nao_promete(self):
        cedo = self.situacao("PA1", agora=6 * 60)
        self.assertTrue(cedo["aviso_ainda_libera_vaga"])
        self.assertIn("fila", cedo["acoes"][0]["explicacao"])
        emcima = self.situacao("PA1", agora=9 * 60 + 40)
        self.assertFalse(emcima["aviso_ainda_libera_vaga"])
        self.assertNotIn("fila", emcima["acoes"][0]["explicacao"])

    def test_aviso_e_desfazivel_enquanto_o_veiculo_nao_passou(self):
        eventos = [{"tipo": "nao_vou", "paciente": "PA1",
                    "em": "2026-08-24T06:00:00"}]
        antes = self.situacao("PA1", eventos=eventos, agora=7 * 60)
        self.assertTrue(antes["avisou_que_nao_vai"])
        self.assertTrue(antes["pode_desfazer"])
        self.assertEqual([a["id"] for a in antes["acoes"]], ["desfazer"])

        depois = self.situacao("PA1", eventos=eventos, agora=11 * 60)
        self.assertFalse(depois["pode_desfazer"])

    def test_dia_sem_viagem_responde_quando_e_a_proxima(self):
        """Tela vazia faz a pessoa ligar para a secretaria."""
        s = self.ac.situacao("PA2", dia_da_semana=1, dia="2026-08-25",
                             tratamentos=self.tratamentos, eventos=[])
        self.assertFalse(s["tem_viagem"])
        self.assertIn("próximo", s["mensagem"])

    def test_codigo_desconhecido_nao_vaza_nada(self):
        s = self.ac.situacao("PA999", dia_da_semana=0, dia="2026-08-24",
                             tratamentos=self.tratamentos, eventos=[])
        self.assertFalse(s["tem_viagem"])
        self.assertNotIn("tratamento", s)

    def test_fila_de_retorno_ordena_por_quem_espera_ha_mais_tempo(self):
        eventos = [{"tipo": "liberado", "paciente": "PA2",
                    "em": "2026-08-24T10:00:00"},
                   {"tipo": "liberado", "paciente": "PA1",
                    "em": "2026-08-24T13:00:00"}]
        fila = self.ac.fila_de_retorno("2026-08-24", eventos,
                                       self.tratamentos)
        self.assertEqual(fila["resumo"]["pessoas"], 2)
        esperas = [x["esperando_ha_min"] for x in fila["esperando"]]
        self.assertEqual(esperas, sorted(esperas, reverse=True))

    def test_fila_so_conta_o_dia_pedido(self):
        eventos = [{"tipo": "liberado", "paciente": "PA1",
                    "em": "2026-08-20T10:00:00"}]
        fila = self.ac.fila_de_retorno("2026-08-24", eventos,
                                       self.tratamentos)
        self.assertEqual(fila["resumo"]["pessoas"], 0)


class TestTokenDoPaciente(unittest.TestCase):
    def test_token_do_paciente_nao_vale_para_outro(self):
        from operacao import registro
        bom = registro.token_do_paciente("PA1")
        self.assertTrue(registro.token_de_paciente_valido("PA1", bom))
        self.assertFalse(registro.token_de_paciente_valido("PA2", bom))

    def test_token_de_familia_nao_vira_token_de_paciente(self):
        """Prefixo próprio: identificador coincidir não pode dar acesso."""
        from operacao import registro
        familia = registro.token_do_responsavel("PA1")
        self.assertFalse(registro.token_de_paciente_valido("PA1", familia))

    def test_evento_do_paciente_exige_o_paciente(self):
        import tempfile
        from operacao import registro
        arquivo = os.path.join(tempfile.mkdtemp(), "e.jsonl")
        with self.assertRaises(registro.ErroDeRegistro):
            registro.registrar({"tipo": "liberado"}, arquivo)
        gravado = registro.registrar({"tipo": "liberado", "paciente": "PA1"},
                                     arquivo)
        self.assertEqual(gravado["paciente"], "PA1")


if __name__ == "__main__":
    unittest.main()
