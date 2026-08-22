# -*- coding: utf-8 -*-
"""
Testes das duas etapas comerciais: precificar e diagnosticar.

O que protegem, em ordem do que dói mais caro se quebrar:
1. o preço entrega a margem DEPOIS do imposto (a divisão, não a soma);
2. o diagnóstico não soma economias que já se contêm;
3. número de planilha brasileira não vira outro número.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comercial import diagnostico as diagnostico_mod  # noqa: E402
from comercial import operacao_atual as operacao_mod  # noqa: E402
from comercial import precificacao as precificacao_mod  # noqa: E402
from comercial.precificacao import Premissas  # noqa: E402
from dados.planilha import numero_br  # noqa: E402

TIPOS = {
    "RODO46": {"nome": "Ônibus rodoviário 46 lugares", "capacidade": 46,
               "posicoes_cadeirante": 0, "fixo_mes": 9800.0, "custo_km": 3.40,
               "consumo_km_l": 2.9},
    "VAN16": {"nome": "Van executiva 16 lugares", "capacidade": 16,
              "posicoes_cadeirante": 0, "fixo_mes": 4900.0, "custo_km": 1.80,
              "consumo_km_l": 8.5},
}

PLANO = {
    "municipio": "Empresa Teste",
    "premissas": {"dias_letivos_mes": 22, "preco_diesel_l": 6.10,
                  "preco_diesel_base_l": 6.10, "viagens_por_rota": 2,
                  "custos_por_tipo": TIPOS},
    "demanda": {"alunos": 200, "turnos": [{"id": "t1"}, {"id": "t2"}]},
    "frota_otimizada": {
        "composicao": {"RODO46": 2, "VAN16": 1}, "total_veiculos": 3,
        "km_dia": 400.0, "litros_dia": 100.0, "custo_mes": 0,
        "viagens": [1, 2, 3],
        "veiculos": [
            {"id": "V1", "tipo": "RODO46", "km_turno": 80.0,
             "ocupacao_media_pct": 78},
            {"id": "V2", "tipo": "RODO46", "km_turno": 70.0,
             "ocupacao_media_pct": 65},
            {"id": "V3", "tipo": "VAN16", "km_turno": 50.0,
             "ocupacao_media_pct": 80}],
    },
    "perfil": {"custo_motorista_mes": 7800.0, "rotulo_passageiro": "colaborador",
               "rotulo_passageiro_plural": "colaboradores"},
    "equipe": {"resumo": {"motoristas": 5, "jornada_media_min": 300,
                          "com_dupla_pegada": 2, "escalas_com_problema": 0},
               "custo_motorista_mes": 7800.0},
}


class TestPrecificacao(unittest.TestCase):
    def test_preco_entrega_a_margem_depois_do_imposto(self):
        """A conta que separa proposta de prejuízo."""
        resultado = precificacao_mod.precificar(
            PLANO, Premissas(margem_alvo=0.12, regime="presumido"))
        preco = resultado["preco"]["mes"]
        custo = resultado["custo"]["total_mes"]
        impostos = resultado["preco"]["impostos_mes"]
        lucro_real = preco - custo - impostos
        self.assertAlmostEqual(lucro_real / preco, 0.12, places=4)

    def test_somar_a_margem_ao_custo_daria_margem_menor(self):
        resultado = precificacao_mod.precificar(PLANO, Premissas())
        custo = resultado["custo"]["total_mes"]
        errado = custo * 1.12
        carga = resultado["preco"]["carga_tributaria_pct"] / 100
        margem_errada = (errado - custo - errado * carga) / errado
        self.assertLess(margem_errada, 0.12)
        self.assertLess(resultado["preco"]["mes"] * 0 + margem_errada, 0.12)

    def test_sem_imposto_o_preco_e_menor(self):
        com = precificacao_mod.precificar(PLANO, Premissas(regime="presumido"))
        sem = precificacao_mod.precificar(PLANO, Premissas(regime="sem_imposto"))
        self.assertLess(sem["preco"]["mes"], com["preco"]["mes"])

    def test_margem_mais_imposto_acima_de_100_e_recusado(self):
        with self.assertRaises(ValueError) as ctx:
            precificacao_mod.precificar(PLANO, Premissas(margem_alvo=0.95))
        self.assertIn("100%", str(ctx.exception))

    def test_equipe_entra_no_custo_com_encargos_e_beneficios(self):
        resultado = precificacao_mod.precificar(PLANO, Premissas())
        equipe = resultado["custo"]["por_grupo"]["Equipe"]
        folha = 5 * 7800.0
        self.assertGreater(equipe, folha)      # encargos + benefícios
        self.assertAlmostEqual(equipe, folha * 1.68 + 5 * 900.0, places=2)

    def test_cada_linha_de_custo_tem_memoria_de_calculo(self):
        resultado = precificacao_mod.precificar(PLANO, Premissas())
        for linha in resultado["custo"]["linhas"]:
            self.assertTrue(linha["memoria"].strip(), linha["item"])

    def test_diesel_mais_caro_sobe_o_preco(self):
        base = precificacao_mod.precificar(PLANO, Premissas())
        caro = precificacao_mod.precificar(PLANO,
                                           Premissas(preco_diesel_l=9.0))
        self.assertGreater(caro["preco"]["mes"], base["preco"]["mes"])

    def test_indicadores_explicam_de_onde_vem_o_preco(self):
        resultado = precificacao_mod.precificar(PLANO, Premissas())
        ind = resultado["indicadores"]
        self.assertAlmostEqual(
            sum(ind["participacao_no_custo_pct"].values()), 100.0, places=0)
        self.assertEqual(ind["passageiros_por_motorista"], 40.0)

    def test_sensibilidade_recalcula_de_verdade(self):
        cenarios = precificacao_mod.sensibilidade(PLANO, Premissas())
        base = next(c for c in cenarios if c["cenario"] == "Proposta base")
        outro = next(c for c in cenarios if "Margem de 18%" in c["cenario"])
        self.assertEqual(base["diferenca_pct"], 0.0)
        self.assertGreater(outro["preco_mes"], base["preco_mes"])
        # custo não muda quando só a margem muda
        self.assertAlmostEqual(outro["custo_mes"], base["custo_mes"], places=2)


class TestDiagnostico(unittest.TestCase):
    def linhas(self):
        return [
            {"linha": "L01", "turno": "t1", "destino": "Planta 1",
             "tipo": "RODO46", "km_dia": 100.0, "passageiros": 10},
            {"linha": "L02", "turno": "t1", "destino": "Planta 1",
             "tipo": "RODO46", "km_dia": 90.0, "passageiros": 12},
            {"linha": "L03", "turno": "t2", "destino": "Planta 1",
             "tipo": "VAN16", "km_dia": 60.0, "passageiros": 15},
        ]

    def test_veiculo_grande_demais_vira_achado_com_a_linha_nomeada(self):
        resultado = diagnostico_mod.diagnosticar(self.linhas(), PLANO)
        trocas = [a for a in resultado["achados"]
                  if a["tipo"] == "veiculo_grande_demais"]
        self.assertTrue(trocas)
        self.assertIn("L01", trocas[0]["linhas"])
        self.assertGreater(trocas[0]["economia_mes"], 0)

    def test_linha_cheia_nao_vira_achado_de_troca(self):
        resultado = diagnostico_mod.diagnosticar(self.linhas(), PLANO)
        for achado in resultado["achados"]:
            self.assertNotIn("L03", achado.get("linhas", []))

    def test_duas_linhas_magras_do_mesmo_turno_se_fundem(self):
        resultado = diagnostico_mod.diagnosticar(self.linhas(), PLANO)
        fusoes = [a for a in resultado["achados"]
                  if a["tipo"] == "linhas_que_se_fundem"]
        self.assertTrue(fusoes)
        self.assertEqual(sorted(fusoes[0]["linhas"]), ["L01", "L02"])

    def test_todo_achado_diz_o_que_conferir_antes(self):
        resultado = diagnostico_mod.diagnosticar(self.linhas(), PLANO)
        for achado in resultado["achados"]:
            self.assertTrue(achado["o_que_conferir"].strip())

    def test_o_teto_nao_e_a_soma_dos_achados(self):
        """Somar troca + fusão + frota ociosa venderia economia que não existe."""
        resultado = diagnostico_mod.diagnosticar(self.linhas(), PLANO)
        soma_de_tudo = sum(a["economia_mes"] for a in resultado["achados"])
        self.assertLess(resultado["resumo"]["economia_teto_mes"], soma_de_tudo)

    def test_linha_com_veiculo_desconhecido_fica_de_fora(self):
        linhas = self.linhas() + [{"linha": "L99", "tipo": "FOGUETE",
                                   "km_dia": 10, "passageiros": 1}]
        resultado = diagnostico_mod.diagnosticar(linhas, PLANO)
        self.assertEqual(resultado["resumo"]["linhas_analisadas"], 3)
        self.assertEqual(resultado["resumo"]["linhas_ignoradas"], 1)

    def test_operacao_ja_enxuta_nao_gera_achado_falso(self):
        enxuta = [{"linha": "L01", "turno": "t1", "destino": "P1",
                   "tipo": "VAN16", "km_dia": 50.0, "passageiros": 15}]
        resultado = diagnostico_mod.diagnosticar(enxuta, PLANO)
        trocas = [a for a in resultado["achados"]
                  if a["tipo"] == "veiculo_grande_demais"]
        self.assertEqual(trocas, [])


class TestPlanilhaDeLinhas(unittest.TestCase):
    def escrever(self, texto):
        arquivo = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                              encoding="utf-8")
        arquivo.write(texto)
        arquivo.close()
        return arquivo.name

    def test_le_quadro_de_linhas_com_titulo_antes_do_cabecalho(self):
        caminho = self.escrever(
            "QUADRO DE LINHAS 2026\n\n"
            "Linha;Turno;Destino;Tipo de veículo;Km/dia;Passageiros\n"
            "L01;1º turno;Planta 1;Ônibus rodoviário 46 lugares;100,5;12\n"
            "L02;2º turno;Planta 1;Van executiva 16 lugares;60;14\n")
        try:
            lido = operacao_mod.importar(caminho, TIPOS)
        finally:
            os.remove(caminho)
        self.assertEqual(len(lido["linhas"]), 2)
        self.assertEqual(lido["linhas"][0]["tipo"], "RODO46")
        self.assertEqual(lido["linhas"][0]["km_dia"], 100.5)

    def test_km_com_ponto_decimal_nao_vira_milhar(self):
        """100.3 km/dia virando 1003 inflava a economia em quatro vezes."""
        self.assertEqual(numero_br("100.3"), 100.3)
        self.assertEqual(numero_br("4.386"), 4386.0)
        self.assertEqual(numero_br("1.234.567"), 1234567.0)
        self.assertEqual(numero_br("12,5"), 12.5)
        self.assertIsNone(numero_br("sem número"))

    def test_veiculo_escrito_do_jeito_da_operacao_e_reconhecido(self):
        caminho = self.escrever(
            "Linha;Tipo;Km/dia;Passageiros\n"
            "L01;onibus 46;100;12\nL02;VAN16;40;9\nL03;van;30;8\n")
        try:
            lido = operacao_mod.importar(caminho, TIPOS)
        finally:
            os.remove(caminho)
        self.assertEqual([l["tipo"] for l in lido["linhas"]],
                         ["RODO46", "VAN16", "VAN16"])

    def test_sem_coluna_de_passageiros_o_importador_avisa(self):
        caminho = self.escrever("Linha;Tipo;Km/dia\nL01;VAN16;40\n")
        try:
            lido = operacao_mod.importar(caminho, TIPOS)
        finally:
            os.remove(caminho)
        self.assertTrue(any("passageiros" in p for p in lido["problemas"]))

    def test_planilha_irreconhecivel_explica_o_que_falta(self):
        caminho = self.escrever("a;b;c\n1;2;3\n")
        try:
            lido = operacao_mod.importar(caminho, TIPOS)
        finally:
            os.remove(caminho)
        self.assertEqual(lido["linhas"], [])
        self.assertTrue(lido["problemas"])


class TestProposta(unittest.TestCase):
    def test_proposta_e_autocontida_e_traz_as_duas_etapas(self):
        from comercial import proposta as proposta_mod

        preco = precificacao_mod.precificar(PLANO, Premissas())
        cenarios = precificacao_mod.sensibilidade(PLANO, Premissas())
        linhas = [{"linha": "L01", "turno": "t1", "destino": "P1",
                   "tipo": "RODO46", "km_dia": 100.0, "passageiros": 10}]
        diagnostico = diagnostico_mod.diagnosticar(linhas, PLANO)
        html = proposta_mod.renderizar(PLANO, preco, cenarios, diagnostico,
                                       cliente="Cliente Teste")
        self.assertNotIn("http://", html)
        self.assertNotIn("src=", html)
        self.assertIn("Cliente Teste", html)
        self.assertIn("Como o preço foi formado", html)
        self.assertIn("O que dá para melhorar no que já roda hoje", html)
        self.assertIn("Premissas", html)

    def test_proposta_sem_diagnostico_omite_a_secao(self):
        from comercial import proposta as proposta_mod

        preco = precificacao_mod.precificar(PLANO, Premissas())
        html = proposta_mod.renderizar(PLANO, preco, [], None)
        self.assertNotIn("O que dá para melhorar no que já roda hoje", html)


if __name__ == "__main__":
    unittest.main()
