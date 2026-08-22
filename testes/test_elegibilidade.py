# -*- coding: utf-8 -*-
"""
Testes da elegibilidade ao porta a porta.

O que estes testes protegem:
1. diagnóstico nunca vira dado de rota;
2. nada é aprovado sem nome de gente e sem evidência;
3. a leitura por IA sugere, e sugestão sem trecho literal é descartada;
4. condição permanente não volta para a fila todo ano.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elegibilidade import extracao, fila, formulario  # noqa: E402
from elegibilidade.perfil import Perfil  # noqa: E402

RESPOSTAS = {
    "nome": "Maria da Silva", "nascimento": "10/03/2015",
    "responsavel": "João da Silva", "telefone": "16 99999-0000",
    "endereco": "Rua das Acácias, 120", "bairro": "Sede Urbana",
    "referencia": "portão azul", "destino": "EMEF Centro", "turno": "Manhã",
    "vai_sozinho_ate_o_ponto": "não", "cadeira_de_rodas": "sim",
    "cadeira_motorizada": "não", "precisa_elevador": "sim",
    "acompanhante": "sim", "auxilio_no_embarque": "sim",
    "cinto_especial": "não", "crise_com_lotacao": "não",
    "tempo_max_bordo_min": "40", "condicao_permanente": "sim",
    "fonte": "laudo", "observacoes": "cão solto no quintal",
}

LAUDO = (
    "RELATÓRIO MÉDICO\n"
    "Paciente com paralisia cerebral (CID G80.1), não deambula e faz uso de "
    "cadeira de rodas.\n"
    "Necessita de acompanhante durante todo o deslocamento.\n"
    "Recomenda-se veículo adaptado com plataforma elevatória.\n"
    "O paciente não deve permanecer mais de 40 minutos em posição sentada "
    "durante o transporte.\n"
)


class TestPerfil(unittest.TestCase):
    def test_perfil_nao_tem_campo_de_diagnostico(self):
        proibidos = ("cid", "diagnostico", "doenca", "laudo", "deficiencia")
        for campo in Perfil.__dataclass_fields__:
            self.assertFalse(any(p in campo for p in proibidos), campo)

    def test_dado_de_rota_nao_leva_nada_pessoal(self):
        perfil = formulario.perfil_de(RESPOSTAS)
        rota = perfil.para_roteirizacao("A123")
        texto = str(rota).lower()
        for vazamento in ("maria", "silva", "acácias", "99999", "cão"):
            self.assertNotIn(vazamento, texto)

    def test_cadeirante_ocupa_posicao_e_nao_assento(self):
        perfil = Perfil(cadeira_de_rodas=True, acompanhante=True)
        self.assertEqual(perfil.posicoes_cadeira, 1)
        self.assertEqual(perfil.assentos, 1)          # só o acompanhante

    def test_parada_com_elevador_demora_mais(self):
        rapido = Perfil().min_parada
        cadeira = Perfil(cadeira_de_rodas=True).min_parada
        elevador = Perfil(cadeira_de_rodas=True, elevador_ou_rampa=True).min_parada
        self.assertLess(rapido, cadeira)
        self.assertLess(cadeira, elevador)

    def test_veiculo_precisa_de_plataforma_quando_ha_elevador(self):
        perfil = Perfil(cadeira_de_rodas=True, elevador_ou_rampa=True)
        self.assertIn("plataforma_elevatoria", perfil.veiculo_precisa())
        self.assertIn("posicao_cadeira", perfil.veiculo_precisa())

    def test_combinacao_incoerente_e_apontada(self):
        perfil = Perfil(cadeira_motorizada=True)      # sem cadeira de rodas
        self.assertTrue(perfil.coerente())

    def test_evitar_lotacao_sem_numero_e_apontado(self):
        self.assertTrue(Perfil(evitar_lotacao=True).coerente())

    def test_ida_e_volta_do_dicionario(self):
        perfil = formulario.perfil_de(RESPOSTAS)
        self.assertEqual(Perfil.de_dicionario(perfil.como_dicionario()), perfil)


class TestFormulario(unittest.TestCase):
    def test_pergunta_pelo_que_a_pessoa_consegue(self):
        """Quem não vai sozinho ao ponto é quem precisa de porta a porta."""
        self.assertTrue(formulario.perfil_de(RESPOSTAS).porta_a_porta)
        sozinho = dict(RESPOSTAS, vai_sozinho_ate_o_ponto="sim")
        self.assertFalse(formulario.perfil_de(sozinho).porta_a_porta)

    def test_campo_condicional_some_quando_nao_se_aplica(self):
        sem_cadeira = dict(RESPOSTAS, cadeira_de_rodas="não")
        visiveis = [c.nome for c in formulario.campos_visiveis(sem_cadeira)]
        self.assertNotIn("cadeira_motorizada", visiveis)

    def test_falta_de_campo_obrigatorio_e_explicada(self):
        incompleto = dict(RESPOSTAS)
        del incompleto["telefone"]
        problemas = formulario.validar(incompleto)
        self.assertTrue(any("Telefone" in p for p in problemas))

    def test_crise_com_lotacao_exige_o_numero(self):
        respostas = dict(RESPOSTAS, crise_com_lotacao="sim")
        self.assertTrue(formulario.validar(respostas))
        respostas["max_passageiros_junto"] = "3"
        self.assertEqual(formulario.validar(respostas), [])
        self.assertEqual(formulario.perfil_de(respostas).max_passageiros_junto, 3)

    def test_pedido_separa_pessoal_de_operacional(self):
        pedido = formulario.montar_pedido(RESPOSTAS, em="2026-08-22")
        self.assertIn("nome", pedido["pessoais"])
        self.assertNotIn("nome", pedido["perfil"])
        self.assertTrue(pedido["usuario"].startswith("A"))
        self.assertNotIn("maria", str(pedido["perfil"]).lower())

    def test_pedido_incompleto_nao_entra(self):
        with self.assertRaises(ValueError):
            formulario.montar_pedido({"nome": "Ana"})

    def test_mesmo_usuario_gera_o_mesmo_identificador(self):
        a = formulario.montar_pedido(RESPOSTAS)["usuario"]
        b = formulario.montar_pedido(dict(RESPOSTAS))["usuario"]
        self.assertEqual(a, b)


class TestExtracao(unittest.TestCase):
    def test_sugere_com_trecho_do_documento(self):
        resultado = extracao.analisar(LAUDO)
        campos = resultado.por_campo()
        self.assertIn("cadeira_de_rodas", campos)
        self.assertIn("acompanhante", campos)
        self.assertIn("elevador_ou_rampa", campos)
        for sugestao in resultado.sugestoes:
            self.assertIn(sugestao.trecho.split("\n")[0][:20], LAUDO)

    def test_pega_o_limite_de_tempo(self):
        campos = extracao.analisar(LAUDO).por_campo()
        self.assertEqual(campos["tempo_max_bordo_min"].valor, 40)

    def test_cid_e_marcado_como_sensivel_e_nao_vira_restricao(self):
        resultado = extracao.analisar(LAUDO)
        self.assertIn("G80.1", resultado.codigos_sensiveis)
        self.assertTrue(resultado.alertas)
        self.assertNotIn("cid", [s.campo for s in resultado.sugestoes])

    def test_trecho_comeca_no_comeco_da_frase(self):
        """O ponto de 'CID G80.1' não termina frase — se terminasse, o
        analista receberia uma evidência começando em '1), não deambula…'."""
        campos = extracao.analisar(LAUDO).por_campo()
        self.assertTrue(
            campos["cadeira_de_rodas"].trecho.startswith("Paciente com"))

    def test_documento_sem_necessidade_avisa(self):
        resultado = extracao.analisar("Atestado de comparecimento à consulta.")
        self.assertEqual(resultado.sugestoes, [])
        self.assertTrue(resultado.alertas)

    def test_documento_vazio_nao_quebra(self):
        self.assertEqual(extracao.analisar("").sugestoes, [])

    def test_nada_entra_no_perfil_sem_aprovacao(self):
        resultado = extracao.analisar(LAUDO)
        perfil, aplicados = extracao.aplicar(Perfil(), resultado, [])
        self.assertEqual(perfil, Perfil())
        self.assertEqual(aplicados, [])

    def test_so_o_campo_marcado_entra(self):
        resultado = extracao.analisar(LAUDO)
        perfil, aplicados = extracao.aplicar(Perfil(), resultado,
                                             ["cadeira_de_rodas"])
        self.assertTrue(perfil.cadeira_de_rodas)
        self.assertFalse(perfil.acompanhante)         # não foi marcado
        self.assertEqual(len(aplicados), 1)
        self.assertIn("cadeira de rodas", aplicados[0]["trecho"].lower())

    def test_sugestao_da_ia_sem_trecho_no_documento_e_descartada(self):
        class ClienteQueAlucina:
            def configurado(self):
                return True

            def mensagem(self, mensagens, ferramentas, sistema=None):
                return {"content": [{"type": "text", "text":
                        '{"sugestoes": [{"campo": "acompanhante", '
                        '"valor": true, "confianca": 0.9, '
                        '"trecho": "necessita de dois acompanhantes e maca", '
                        '"porque": "inventado"}]}'}]}

        resultado = extracao.analisar_com_modelo("Usa cadeira de rodas.",
                                                 ClienteQueAlucina())
        self.assertNotIn("acompanhante",
                         [s.campo for s in resultado.sugestoes
                          if s.porque == "inventado"])
        self.assertTrue(any("Descartei" in a for a in resultado.alertas))

    def test_sugestao_da_ia_com_trecho_literal_entra_para_aprovacao(self):
        texto = "O aluno necessita de acompanhante em todo o trajeto."

        class ClienteBom:
            def configurado(self):
                return True

            def mensagem(self, mensagens, ferramentas, sistema=None):
                return {"content": [{"type": "text", "text":
                        '{"sugestoes": [{"campo": "acompanhante", '
                        '"valor": true, "confianca": 0.8, '
                        '"trecho": "necessita de acompanhante em todo o '
                        'trajeto", "porque": "leitura por IA"}]}'}]}

        resultado = extracao.analisar_com_modelo(texto, ClienteBom())
        self.assertIn("acompanhante", resultado.por_campo())
        self.assertEqual(resultado.origem, "regras+ia")

    def test_api_fora_do_ar_cai_para_as_regras(self):
        class ClienteQuebrado:
            def configurado(self):
                return True

            def mensagem(self, *a, **kw):
                raise RuntimeError("sem rede")

        resultado = extracao.analisar_com_modelo(LAUDO, ClienteQuebrado())
        self.assertIn("cadeira_de_rodas", resultado.por_campo())
        self.assertEqual(resultado.origem, "regras")


class TestFila(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-eleg-")
        self.arquivo = os.path.join(self.pasta, "elegibilidade.jsonl")
        self.pedido = formulario.montar_pedido(RESPOSTAS, em="2026-08-01")
        fila.receber(self.pedido, self.arquivo)
        self.protocolo = self.pedido["protocolo"]

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def perfil(self):
        return formulario.perfil_de(RESPOSTAS)

    def test_pedido_recebido_ja_tem_protocolo_para_acompanhar(self):
        situacao = fila.situacao(self.protocolo, self.arquivo)
        self.assertEqual(situacao["estado"], "recebido")
        self.assertIn("aguardando", situacao["estado_em_portugues"].lower())

    def test_aprovar_sem_analista_e_impossivel(self):
        with self.assertRaises(fila.ErroDeFila):
            fila.aprovar(self.protocolo, "", self.perfil(), ["laudo"],
                         arquivo=self.arquivo)

    def test_aprovar_sem_evidencia_e_impossivel(self):
        with self.assertRaises(fila.ErroDeFila):
            fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), [],
                         arquivo=self.arquivo)

    def test_negar_sem_justificativa_e_impossivel(self):
        with self.assertRaises(fila.ErroDeFila):
            fila.negar(self.protocolo, "Ana (SME)", "", arquivo=self.arquivo)

    def test_negativa_diz_como_recorrer(self):
        fila.negar(self.protocolo, "Ana (SME)", "Endereço fora do município.",
                   arquivo=self.arquivo)
        situacao = fila.situacao(self.protocolo, self.arquivo)
        self.assertEqual(situacao["estado"], "negado")
        self.assertTrue(situacao["historico"][-1]["detalhe"])

    def test_pedir_informacao_muda_o_estado_e_diz_o_que_falta(self):
        fila.iniciar_analise(self.protocolo, "Ana (SME)", self.arquivo)
        fila.pedir_informacao(self.protocolo, "Ana (SME)",
                              "Foto do documento com o nome legível.",
                              self.arquivo)
        situacao = fila.situacao(self.protocolo, self.arquivo)
        self.assertEqual(situacao["estado"], "pendente_de_informacao")
        self.assertIn("legível", situacao["pendencia"])
        fila.receber_informacao(self.protocolo, "foto enviada", self.arquivo)
        self.assertEqual(fila.situacao(self.protocolo, self.arquivo)["estado"],
                         "em_analise")

    def test_pedido_de_informacao_vago_e_recusado(self):
        with self.assertRaises(fila.ErroDeFila):
            fila.pedir_informacao(self.protocolo, "Ana", "", self.arquivo)

    def test_aprovacao_registra_quem_decidiu_e_com_base_em_que(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(),
                     ["laudo", "cadastro_municipal"],
                     justificativa="Usa cadeira de rodas; não chega ao ponto.",
                     arquivo=self.arquivo, em="2026-08-05")
        situacao = fila.situacao(self.protocolo, self.arquivo, hoje="2026-08-06")
        self.assertEqual(situacao["estado"], "aprovado")
        self.assertEqual(situacao["analista"], "Ana (SME)")
        self.assertTrue(situacao["justificativa"])

    def test_condicao_permanente_nao_vence(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     permanente=True, arquivo=self.arquivo, em="2026-08-05")
        situacao = fila.situacao(self.protocolo, self.arquivo)
        self.assertTrue(situacao["permanente"])
        self.assertEqual(situacao["vence_em"], "")
        self.assertTrue(fila.demanda_para_roteirizacao(self.arquivo,
                                                       hoje="2030-01-01"))

    def test_concessao_temporaria_vence(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     validade_meses=6, arquivo=self.arquivo, em="2026-08-05")
        self.assertTrue(fila.demanda_para_roteirizacao(self.arquivo,
                                                       hoje="2026-12-01"))
        self.assertEqual(fila.demanda_para_roteirizacao(self.arquivo,
                                                        hoje="2027-03-01"), [])

    def test_avisa_quem_esta_para_vencer(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     validade_meses=1, arquivo=self.arquivo, em="2026-08-05")
        self.assertTrue(fila.a_vencer(30, self.arquivo, hoje="2026-08-20"))
        self.assertEqual(fila.a_vencer(3, self.arquivo, hoje="2026-08-20"), [])

    def test_demanda_para_rota_nao_leva_dado_pessoal(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     arquivo=self.arquivo, em="2026-08-05")
        demanda = fila.demanda_para_roteirizacao(self.arquivo, hoje="2026-08-06")
        self.assertEqual(len(demanda), 1)
        texto = str(demanda).lower()
        for vazamento in ("maria", "silva", "acácias", "99999", "laudo"):
            self.assertNotIn(vazamento, texto)
        self.assertTrue(demanda[0]["cadeirante"])
        self.assertEqual(demanda[0]["tempo_max_bordo_min"], 40)

    def test_prazo_e_atraso(self):
        atrasado = fila.situacao(self.protocolo, self.arquivo, hoje="2026-09-30")
        self.assertTrue(atrasado["atrasado"])
        no_prazo = fila.situacao(self.protocolo, self.arquivo, hoje="2026-08-03")
        self.assertFalse(no_prazo["atrasado"])

    def test_historico_guarda_tudo_em_ordem(self):
        fila.iniciar_analise(self.protocolo, "Ana (SME)", self.arquivo)
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     arquivo=self.arquivo)
        tipos = [h["tipo"] for h in
                 fila.situacao(self.protocolo, self.arquivo)["historico"]]
        self.assertEqual(tipos, ["recebido", "em_analise", "aprovado"])

    def test_linha_corrompida_nao_derruba_a_fila(self):
        with open(self.arquivo, "a", encoding="utf-8") as f:
            f.write("{isso não é json\n")
        self.assertTrue(fila.situacao(self.protocolo, self.arquivo))

    def test_evento_invalido_e_recusado(self):
        with self.assertRaises(fila.ErroDeFila):
            fila.registrar({"tipo": "dar_um_jeitinho",
                            "protocolo": self.protocolo}, self.arquivo)
        with self.assertRaises(fila.ErroDeFila):
            fila.registrar({"tipo": "aprovado"}, self.arquivo)

    def test_resumo_da_fila(self):
        fila.aprovar(self.protocolo, "Ana (SME)", self.perfil(), ["laudo"],
                     arquivo=self.arquivo, em="2026-08-05")
        resumo = fila.resumo(self.arquivo, hoje="2026-08-06")
        self.assertEqual(resumo["pedidos"], 1)
        self.assertEqual(resumo["aprovados"], 1)
        self.assertEqual(resumo["em_aberto"], 0)

    def test_fila_ordena_atrasado_primeiro(self):
        outro = formulario.montar_pedido(
            dict(RESPOSTAS, nome="Bruno Souza"), em="2026-09-20")
        fila.receber(outro, self.arquivo)
        lista = fila.listar(self.arquivo, hoje="2026-09-25")
        self.assertEqual(lista[0]["protocolo"], self.protocolo)
        self.assertTrue(lista[0]["atrasado"])


if __name__ == "__main__":
    unittest.main()
