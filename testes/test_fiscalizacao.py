# -*- coding: utf-8 -*-
"""
Testes da fiscalização de contrato.

O que protegem é o que faz este módulo servir num processo administrativo:

1. **falta de evidência nunca vira glosa** — é a regra que decide se o
   sistema sobrevive ao primeiro recurso do fornecedor;
2. **toda glosa cita a evidência** — número sem lastro não vai para peça de
   processo;
3. **km medido nunca se passa por medida quando o rastro é esparso** — somar
   retas entre pings distantes corta as curvas e sempre dá menos;
4. **o veredicto de cada viagem corresponde ao que os eventos dizem** — nem
   mais severo, nem mais leniente.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiscalizacao import contrato, medicao, relatorio, simulador  # noqa: E402

PONTOS = {"P1": [-21.150, -47.800], "P2": [-21.155, -47.805],
          "P3": [-21.160, -47.810]}

PLANO = {
    "municipio": "Teste",
    "premissas": {"tempo_virada_min": 5},
    "geografia": {"pontos": PONTOS,
                  "escolas": [{"id": "E1", "nome": "EMEF Centro",
                               "lat": -21.15, "lon": -47.80}]},
    "frota_otimizada": {
        "total_veiculos": 1,
        "viagens": [{"id": "V1", "veiculo": "VM01", "turno": "manha",
                     "turno_nome": "Manhã", "escola_id": "E1",
                     "escola": "EMEF Centro",
                     "paradas": ["P1", "P2", "P3"], "alunos": 20,
                     "km_viagem": 10.0, "min_viagem": 30}],
        "veiculos": [{"id": "VM01", "turno": "manha", "viagens": ["V1"]}],
    },
}

DIA = "2026-08-03"


def _plano_com_varias_viagens(quantas: int) -> dict:
    """Plano maior, para o mês simulado ter amostra de cada imperfeição."""
    viagens = [{"id": f"V{i}", "veiculo": f"VM{i:02d}", "turno": "manha",
                "turno_nome": "Manhã", "escola_id": "E1",
                "escola": "EMEF Centro", "paradas": ["P1", "P2", "P3"],
                "alunos": 20, "km_viagem": 10.0, "min_viagem": 30}
               for i in range(quantas)]
    return dict(PLANO, frota_otimizada={
        "total_veiculos": quantas, "viagens": viagens,
        "veiculos": [{"id": v["veiculo"], "turno": "manha",
                      "viagens": [v["id"]]} for v in viagens]})


def evento(tipo, minuto, **extra):
    return dict({"tipo": tipo, "motorista": "VM01", "viagem": "V1",
                 "em": f"{DIA}T{minuto // 60:02d}:{minuto % 60:02d}:00"},
                **extra)


def ping(minuto, ponto):
    lat, lon = PONTOS[ponto]
    return {"tipo": "ping", "motorista": "VM01", "lat": lat, "lon": lon,
            "em": f"{DIA}T{minuto // 60:02d}:{minuto % 60:02d}:00"}


def viagem_completa(minuto_inicial=360):
    eventos = [evento("inicio", minuto_inicial)]
    for i, p in enumerate(["P1", "P2", "P3"]):
        eventos.append(evento("embarque", minuto_inicial + i + 1, ponto=p))
        # rastro denso: um ping por minuto, que é o que torna o km utilizável
        for j in range(3):
            eventos.append(ping(minuto_inicial + i * 3 + j + 1, p))
    eventos.append(evento("fim", minuto_inicial + 30))
    return eventos


class TestVeredicto(unittest.TestCase):
    def medir(self, eventos):
        return medicao.medir_dia(PLANO, eventos, DIA)["viagens"][0]

    def test_sem_evento_nenhum_nao_e_falta(self):
        """A regra que sustenta o sistema: ausência de prova não é prova."""
        medida = self.medir([])
        self.assertEqual(medida["situacao"], "sem_evidencia")
        self.assertNotEqual(medida["situacao"], "nao_realizada")
        self.assertIn("sem sinal", medida["motivo"])

    def test_viagem_completa_e_realizada(self):
        medida = self.medir(viagem_completa())
        self.assertEqual(medida["situacao"], "realizada")
        self.assertEqual(medida["paradas_com_evidencia"], 3)

    def test_cancelamento_declarado_e_nao_realizada(self):
        medida = self.medir([evento("imprevisto", 360, cancelou_viagem=True,
                                    motivo="veículo quebrou")])
        self.assertEqual(medida["situacao"], "nao_realizada")
        self.assertIn("veículo quebrou", medida["motivo"])

    def test_metade_das_paradas_e_parcial(self):
        eventos = [evento("inicio", 360), evento("embarque", 361, ponto="P1")]
        eventos += [ping(361 + j, "P1") for j in range(5)]
        eventos.append(evento("fim", 380))
        medida = self.medir(eventos)
        self.assertEqual(medida["situacao"], "parcial")
        self.assertLess(medida["paradas_com_evidencia"],
                        medida["paradas_planejadas"])


class TestAtraso(unittest.TestCase):
    def test_agenda_sai_do_plano_e_da_janela_do_turno(self):
        """Sem horário planejado não existe 'atrasado', só 'chegou'."""
        agenda = medicao.horarios_planejados(PLANO)
        self.assertIn("V1", agenda)
        # a última viagem do veículo encosta no fim da janela da manhã (7h)
        self.assertEqual(agenda["V1"]["chegada_min"], 7 * 60)
        self.assertEqual(agenda["V1"]["saida_min"], 7 * 60 - 30)

    def test_chegada_depois_do_horario_conta_atraso(self):
        agenda = medicao.horarios_planejados(PLANO)
        saida = agenda["V1"]["saida_min"]
        eventos = viagem_completa(saida)
        eventos[-1] = evento("fim", saida + 30 + 25)      # 25 min atrasada
        medida = medicao.medir_dia(PLANO, eventos, DIA)["viagens"][0]
        self.assertEqual(medida["atraso_min"], 25)
        self.assertTrue(medida["atrasada"])

    def test_chegada_no_horario_nao_conta_atraso(self):
        agenda = medicao.horarios_planejados(PLANO)
        eventos = viagem_completa(agenda["V1"]["saida_min"])
        medida = medicao.medir_dia(PLANO, eventos, DIA)["viagens"][0]
        self.assertEqual(medida["atraso_min"], 0)
        self.assertFalse(medida["atrasada"])


class TestQuilometragem(unittest.TestCase):
    def test_rastro_esparso_e_piso_nao_medida(self):
        """Somar retas entre pings distantes corta curva — e paga a menos."""
        eventos = [evento("inicio", 360)]
        eventos += [ping(360 + i * 10, p)          # um ping a cada 10 min
                    for i, p in enumerate(["P1", "P2", "P3", "P1", "P2"])]
        eventos.append(evento("fim", 400))
        medida = medicao.medir_dia(PLANO, eventos, DIA)["viagens"][0]
        self.assertIsNotNone(medida["km_medido"])
        self.assertFalse(medida["km_medido_confiavel"])

    def test_rastro_denso_vale_como_medida(self):
        medida = medicao.medir_dia(PLANO, viagem_completa(),
                                   DIA)["viagens"][0]
        self.assertTrue(medida["km_medido_confiavel"])

    def test_dois_pings_nao_viram_quilometragem(self):
        eventos = [evento("inicio", 360), ping(361, "P1"), ping(362, "P2"),
                   evento("fim", 380)]
        medida = medicao.medir_dia(PLANO, eventos, DIA)["viagens"][0]
        self.assertIsNone(medida["km_medido"])


class TestPagamento(unittest.TestCase):
    def medicao_de(self, eventos):
        return {"viagens": medicao.medir_dia(PLANO, eventos, DIA)["viagens"],
                "resumo": medicao.medir_dia(PLANO, eventos, DIA)["resumo"]}

    def test_viagem_sem_evidencia_vira_suspenso_e_nunca_glosa(self):
        regras = contrato.RegrasDoContrato(modelo="km_rodado", valor_km=5.0)
        avaliacao = contrato.avaliar(self.medicao_de([]), regras)
        self.assertEqual(avaliacao["glosa"], 0.0)
        self.assertEqual(avaliacao["em_suspenso"], 50.0)   # 10 km × R$ 5
        self.assertEqual(len(avaliacao["suspensos"]), 1)
        self.assertTrue(avaliacao["suspensos"][0]["quem_decide"])

    def test_viagem_nao_realizada_nao_e_paga(self):
        regras = contrato.RegrasDoContrato(modelo="km_rodado", valor_km=5.0)
        avaliacao = contrato.avaliar(
            self.medicao_de([evento("imprevisto", 360, cancelou_viagem=True,
                                    motivo="quebrou")]), regras)
        self.assertEqual(avaliacao["a_pagar"], 0.0)
        self.assertEqual(avaliacao["glosa"], 50.0)

    def test_toda_glosa_cita_a_evidencia(self):
        regras = contrato.RegrasDoContrato(modelo="km_rodado", valor_km=5.0)
        eventos = [evento("inicio", 360), evento("embarque", 361, ponto="P1")]
        eventos += [ping(361 + j, "P1") for j in range(5)]
        avaliacao = contrato.avaliar(self.medicao_de(eventos), regras)
        self.assertTrue(avaliacao["glosas"])
        for glosa in avaliacao["glosas"]:
            self.assertTrue(glosa["motivo"])
            self.assertIn("evidencia", glosa)
            self.assertTrue(glosa["viagem"])

    def test_memoria_de_calculo_fecha_com_o_total(self):
        regras = contrato.RegrasDoContrato(modelo="km_rodado", valor_km=5.0)
        avaliacao = contrato.avaliar(self.medicao_de(viagem_completa()), regras)
        self.assertEqual(avaliacao["a_pagar"], 50.0)
        self.assertTrue(any("50.00" in linha for linha in avaliacao["memoria"]))

    def test_modelo_desconhecido_levanta_erro(self):
        with self.assertRaises(ValueError):
            contrato.avaliar({"viagens": [], "resumo": {}},
                             contrato.RegrasDoContrato(modelo="marciano"))

    def test_contrato_por_viagem_paga_a_realizada(self):
        regras = contrato.RegrasDoContrato(modelo="viagem", valor_viagem=180.0)
        avaliacao = contrato.avaliar(self.medicao_de(viagem_completa()), regras)
        self.assertEqual(avaliacao["a_pagar"], 180.0)


class TestBoletim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        simulacao = simulador.simular_mes(PLANO, dias=5)
        cls.boletim = relatorio.montar(
            PLANO, simulacao["eventos"], simulacao["dias"],
            contrato.RegrasDoContrato(modelo="km_rodado", valor_km=4.85),
            origem="simulacao", explicacao_selo=simulacao["explicacao_selo"])

    def test_cobertura_vem_antes_do_dinheiro(self):
        """Boletim que abre com glosa e esconde a cobertura perde a discussão."""
        self.assertIn("confiabilidade", self.boletim)
        chaves = list(self.boletim.keys())
        self.assertLess(chaves.index("confiabilidade"),
                        chaves.index("pagamento"))
        self.assertIn("cobertura_pct", self.boletim["confiabilidade"])

    def test_cobertura_baixa_nao_sustenta_glosa(self):
        baixa = relatorio._confiabilidade({"cobertura_pct": 40.0})
        self.assertFalse(baixa["sustenta_glosa"])
        self.assertIn("não sustenta glosa", baixa["frase"])

    def test_periodo_e_declarado(self):
        self.assertEqual(self.boletim["periodo"]["dias"], 5)
        self.assertEqual(self.boletim["origem"], "simulacao")
        self.assertTrue(self.boletim["explicacao_selo"])

    def test_pendencia_tem_dono_e_acao(self):
        for item in self.boletim["pendencias"]:
            self.assertTrue(item["quem_decide"])
            self.assertTrue(item["acao"])
            self.assertTrue(item["detalhe"])


class TestSimulador(unittest.TestCase):
    def test_mesmo_mes_sai_igual(self):
        """Demonstração não pode mudar de número entre duas reuniões."""
        a = simulador.simular_mes(PLANO, dias=3)
        b = simulador.simular_mes(PLANO, dias=3)
        self.assertEqual(a["eventos"], b["eventos"])

    def test_marcado_como_simulacao(self):
        simulacao = simulador.simular_mes(PLANO, dias=2)
        self.assertEqual(simulacao["origem"], "simulacao")
        self.assertIn("nenhuma pessoa real", simulacao["explicacao_selo"])

    def test_so_dias_uteis(self):
        from datetime import date
        simulacao = simulador.simular_mes(PLANO, inicio="2026-08-03", dias=10)
        for dia in simulacao["dias"]:
            self.assertLess(date.fromisoformat(dia).weekday(), 5, dia)

    def test_mes_gerado_exercita_os_quatro_veredictos(self):
        """Um mês perfeito não testaria a fiscalização."""
        plano = _plano_com_varias_viagens(6)
        simulacao = simulador.simular_mes(plano, dias=22)
        medido = medicao.medir_periodo(plano, simulacao["eventos"],
                                       simulacao["dias"])
        resumo = medido["resumo"]
        self.assertTrue(resumo["realizadas"])
        self.assertTrue(resumo["sem_evidencia"],
                        "sem aparelho mudo o mês não exercita a fila de "
                        "decisão humana")
        self.assertTrue(resumo["nao_realizadas"] or resumo["parciais"])
        self.assertLess(resumo["cobertura_pct"], 100)


if __name__ == "__main__":
    unittest.main()
