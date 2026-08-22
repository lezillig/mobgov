# -*- coding: utf-8 -*-
"""
Testes da camada conversacional.

O que estes testes protegem, em ordem de importância:
1. o assistente nunca escreve número que não veio de ferramenta;
2. sem internet e sem chave de API, ele continua respondendo;
3. a pergunta do gestor cai na ferramenta certa.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversa import ferramentas, redator, roteador  # noqa: E402
from conversa.assistente import (Assistente, ClienteAnthropic, ErroDeAPI,  # noqa: E402
                                 auditar_numeros)

INDICADORES = {
    "municipio": "Ribeirão Modelo (sintético)", "frota_atual": 30,
    "frota_necessaria": 23, "reducao_frota_pct": 23.3,
    "custo_atual_mes": 660613.82, "custo_necessario_mes": 519491.5,
    "economia_mes": 141122.32, "economia_ano": 1693467.84,
    "km_dia_economizados": 1287.2, "litros_dia_economizados": 262.7,
    "tco2_ano_evitadas": 185.8, "alunos": 2915, "viagens": 107,
    "ocupacao_media_pct": 93.6, "gerado_em": "2026-08-22 15:39",
}


class ClienteFalso(ClienteAnthropic):
    """Finge a API: devolve as respostas que a gente combinar, em ordem."""

    def __init__(self, respostas, erro=None):
        super().__init__(chave="x", modelo="modelo-de-teste")
        self.respostas = list(respostas)
        self.erro = erro
        self.pedidos = []

    def mensagem(self, mensagens, ferramentas_, sistema=None):
        # cópia: o assistente continua acrescentando na mesma lista, e sem
        # copiar o teste veria o estado do fim, não o do momento da chamada
        self.pedidos.append(list(mensagens))
        if self.erro:
            raise ErroDeAPI(self.erro)
        return self.respostas.pop(0)


def texto(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn"}


def usa_ferramenta(nome, entrada=None, ident="tu_1"):
    return {"content": [{"type": "tool_use", "id": ident, "name": nome,
                         "input": entrada or {}}],
            "stop_reason": "tool_use"}


class TestRoteador(unittest.TestCase):
    def test_perguntas_reais_caem_na_ferramenta_certa(self):
        casos = [
            ("Quanto eu economizo por mês?", "consultar_indicadores"),
            ("Qual a economia anual do município?", "consultar_indicadores"),
            ("Por que preciso de tantos ônibus?", "dimensionar_frota"),
            ("Qual a composição da frota?", "dimensionar_frota"),
            ("E se o diesel for a R$ 8,20?", "simular_cenario"),
            ("A planilha da secretaria entrou direito?",
             "qualidade_da_importacao"),
            ("Quantos erros teve na importação?", "qualidade_da_importacao"),
            ("O que o sistema aprendeu?", "o_que_o_sistema_aprendeu"),
            ("Como está a operação hoje?", "estado_da_operacao"),
            ("Me explica a viagem E1-manha-03", "explicar_rota"),
            ("Gere o relatório para o tribunal de contas",
             "gerar_relatorio"),
        ]
        for pergunta, esperada in casos:
            with self.subTest(pergunta=pergunta):
                self.assertEqual(roteador.escolher(pergunta)[0], esperada)

    def test_acento_e_caixa_nao_importam(self):
        a = roteador.escolher("QUANTO EU ECONOMIZO?")[0]
        b = roteador.escolher("quanto eu economizo?")[0]
        self.assertEqual(a, b)

    def test_tira_o_preco_do_diesel_da_pergunta(self):
        _, argumentos, _ = roteador.escolher("e se o diesel subir para 8,20?")
        self.assertAlmostEqual(argumentos["preco_diesel"], 8.20)

    def test_tira_os_dias_letivos_da_pergunta(self):
        _, argumentos, _ = roteador.escolher("simula com 18 dias letivos")
        self.assertEqual(argumentos["dias_letivos"], 18)

    def test_cenario_sem_numero_nao_vira_cenario(self):
        """'e se a gente mudar tudo?' não tem o que simular."""
        nome, argumentos, _ = roteador.escolher("e se a gente mudar tudo?")
        self.assertEqual(nome, "consultar_indicadores")
        self.assertEqual(argumentos, {})

    def test_pega_o_id_da_viagem(self):
        _, argumentos, _ = roteador.escolher("por que a rota E1-manha-03 "
                                             "usa uma van?")
        self.assertEqual(argumentos["viagem"], "E1-manha-03")

    def test_pergunta_sem_relacao_tem_confianca_baixa(self):
        _, _, confianca = roteador.escolher("bom dia, tudo bem?")
        self.assertLess(confianca, 0.4)

    def test_pergunta_clara_tem_confianca_alta(self):
        _, _, confianca = roteador.escolher("quanto eu economizo por mês "
                                            "com essa frota?")
        self.assertGreaterEqual(confianca, 0.4)


class TestFerramentas(unittest.TestCase):
    def test_catalogo_no_formato_da_api(self):
        for esquema in ferramentas.esquemas():
            self.assertIn("name", esquema)
            self.assertIn("description", esquema)
            self.assertEqual(esquema["input_schema"]["type"], "object")

    def test_ferramenta_desconhecida_nao_derruba(self):
        resposta = ferramentas.executar("apagar_tudo")
        self.assertIn("erro", resposta)
        self.assertIn("disponiveis", resposta)

    def test_ferramenta_que_falha_devolve_erro_explicado(self):
        quebrada = ferramentas.Ferramenta(
            "quebrada", "", {"type": "object", "properties": {}},
            lambda **_: 1 / 0)
        ferramentas.POR_NOME["quebrada"] = quebrada
        try:
            resposta = ferramentas.executar("quebrada")
        finally:
            del ferramentas.POR_NOME["quebrada"]
        self.assertIn("erro", resposta)

    def test_indicadores_trazem_os_numeros_da_manchete(self):
        d = ferramentas.executar("consultar_indicadores")
        for chave in ("frota_atual", "frota_necessaria", "economia_mes",
                      "economia_ano", "tco2_ano_evitadas"):
            self.assertIn(chave, d)

    def test_cenario_muda_a_conta(self):
        d = ferramentas.executar("simular_cenario", {"preco_diesel": 9.0})
        self.assertNotEqual(d["economia_mes_base"], d["economia_mes_cenario"])


class TestRedator(unittest.TestCase):
    def test_escreve_em_portugues_com_reais(self):
        resposta = redator.escrever("consultar_indicadores", INDICADORES)
        self.assertIn("R$ 141.122,32", resposta)
        self.assertIn("23,3%", resposta)
        self.assertNotIn("141122.32", resposta)

    def test_erro_da_ferramenta_vira_a_resposta(self):
        self.assertEqual(
            redator.escrever("consultar_indicadores", {"erro": "sem plano"}),
            "sem plano")

    def test_dado_faltando_nao_vira_numero_inventado(self):
        incompleto = dict(INDICADORES)
        del incompleto["economia_ano"]
        resposta = redator.escrever("consultar_indicadores", incompleto)
        self.assertIn("economia_ano", resposta)


class TestAuditoria(unittest.TestCase):
    def test_numero_da_ferramenta_passa(self):
        self.assertEqual(
            auditar_numeros("A economia é de R$ 141.122,32 por mês.",
                            [INDICADORES]), [])

    def test_numero_reescalado_passa(self):
        """R$ 1,69 mi é 1693467.84 dito de outro jeito."""
        self.assertEqual(
            auditar_numeros("Dá R$ 1,69 mi por ano.", [INDICADORES]), [])

    def test_numero_inventado_e_pego(self):
        suspeitos = auditar_numeros("A economia é de R$ 250.000,00 por mês.",
                                    [INDICADORES])
        self.assertTrue(suspeitos)

    def test_numero_pequeno_nao_e_acusado(self):
        self.assertEqual(auditar_numeros("Três pontos: 1. 2. 3.",
                                         [INDICADORES]), [])

    def test_ano_nao_e_acusado(self):
        self.assertEqual(auditar_numeros("No ano de 2026 o plano vale.",
                                         [INDICADORES]), [])


class TestAssistenteOffline(unittest.TestCase):
    def test_responde_sem_chave_de_api(self):
        assistente = Assistente(offline=True)
        resposta = assistente.responder("quanto eu economizo por mês?")
        self.assertEqual(resposta["modo"], "offline")
        self.assertIn("R$", resposta["resposta"])
        self.assertEqual(resposta["ferramentas"][0]["nome"],
                         "consultar_indicadores")

    def test_pergunta_vaga_avisa_que_pode_ter_entendido_errado(self):
        resposta = Assistente(offline=True).responder("oi")
        self.assertIn("Não tenho certeza", resposta["resposta"])

    def test_todo_numero_da_resposta_offline_vem_de_ferramenta(self):
        resposta = Assistente(offline=True).responder("quanto eu economizo?")
        resultados = [f["resultado"] for f in resposta["ferramentas"]]
        self.assertEqual(auditar_numeros(resposta["resposta"], resultados), [])


class TestAssistenteComLlm(unittest.TestCase):
    def test_chama_ferramenta_e_escreve_a_resposta(self):
        cliente = ClienteFalso([
            usa_ferramenta("consultar_indicadores"),
            texto("A economia é de R$ 141.122,32 por mês."),
        ])
        resposta = Assistente(cliente=cliente).responder("quanto economizo?")
        self.assertEqual(resposta["modo"], "llm")
        self.assertTrue(resposta["numeros_conferidos"])
        self.assertEqual(resposta["ferramentas"][0]["nome"],
                         "consultar_indicadores")

    def test_resultado_da_ferramenta_volta_para_o_modelo(self):
        cliente = ClienteFalso([usa_ferramenta("consultar_indicadores"),
                                texto("pronto")])
        Assistente(cliente=cliente).responder("quanto economizo?")
        ultima = cliente.pedidos[-1][-1]
        self.assertEqual(ultima["role"], "user")
        self.assertEqual(ultima["content"][0]["type"], "tool_result")
        json.loads(ultima["content"][0]["content"])     # é JSON válido

    def test_numero_inventado_pelo_modelo_e_substituido(self):
        cliente = ClienteFalso([
            usa_ferramenta("consultar_indicadores"),
            texto("A economia chega a R$ 900.000,00 por mês."),
        ])
        resposta = Assistente(cliente=cliente).responder("quanto economizo?")
        self.assertFalse(resposta["numeros_conferidos"])
        self.assertNotIn("900.000,00", resposta["resposta"])
        self.assertIn("R$ 141.122,32", resposta["resposta"])

    def test_resposta_sem_consultar_nada_nao_vale(self):
        cliente = ClienteFalso([texto("Economiza bastante, pode confiar.")])
        resposta = Assistente(cliente=cliente).responder("quanto economizo?")
        self.assertEqual(resposta["modo"], "offline")

    def test_api_fora_do_ar_cai_para_offline(self):
        cliente = ClienteFalso([], erro="sem rede")
        resposta = Assistente(cliente=cliente).responder("quanto economizo?")
        self.assertEqual(resposta["modo"], "offline")
        self.assertIn("sem rede", resposta["motivo_offline"])
        self.assertIn("R$", resposta["resposta"])

    def test_modelo_em_loop_de_ferramenta_nao_trava(self):
        cliente = ClienteFalso([usa_ferramenta("consultar_indicadores",
                                               ident=f"tu_{i}")
                                for i in range(9)])
        resposta = Assistente(cliente=cliente, max_rodadas=3).responder("?")
        self.assertEqual(resposta["modo"], "offline")

    def test_cliente_sem_chave_nao_e_considerado_configurado(self):
        self.assertFalse(ClienteAnthropic(chave="", modelo="x").configurado())
        self.assertFalse(ClienteAnthropic(chave="k", modelo="").configurado())


if __name__ == "__main__":
    unittest.main()
