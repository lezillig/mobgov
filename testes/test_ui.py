# -*- coding: utf-8 -*-
"""
Testes do protótipo do sistema remodelado (ui/).

O que protegem:

1. **o HTML sai autocontido** — a tela é aberta com duplo clique, muitas vezes
   sem internet; qualquer `src=` ou `href=` para fora quebra a demonstração;
2. **o dado da importação é do plano que está na tela** — mostrar o erro de
   uma planilha em cima dos números de outra é o pior tipo de bug: parece
   certo;
3. **a ordem das pendências** — quem pode ficar sem transporte vem antes de
   dinheiro;
4. **o selo acompanha todo bloco de número** — a regra do projeto virou
   componente, e componente sem teste volta a ser rodapé.
"""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import gerar as ui  # noqa: E402


class TestPendencias(unittest.TestCase):
    """A ordem é a mensagem: primeiro quem espera, depois quanto custa."""

    def test_gente_antes_de_dinheiro(self):
        plano = {
            "coerencia": ["a frota declarada não bate com a demanda"],
            "demanda_nao_atendida": {
                "alunos": 9,
                "pontos": [{"ponto": "P1", "escola": "E1",
                            "minutos_minimos": 88, "limite_min": 75}],
            },
        }
        elegibilidade = {"resumo": {"atrasados": 5, "prazo_dias": 15,
                                    "dias_em_aberto_media": 11.3}}
        itens = ui._pendencias(plano, elegibilidade, None, None)
        self.assertEqual([i["urgencia"] for i in itens][:2], ["alta", "alta"])
        self.assertEqual(itens[-1]["urgencia"], "media")
        self.assertIn("porta a porta", itens[0]["titulo"])

    def test_toda_pendencia_tem_dono_e_acao(self):
        plano = {"coerencia": ["aviso"], "demanda_nao_atendida": {}}
        equipe = {"resumo": {"escalas_com_problema": 2, "com_hora_extra": 1,
                             "hora_extra_total_min": 16}}
        itens = ui._pendencias(plano, None, None, equipe)
        self.assertTrue(itens)
        for item in itens:
            self.assertTrue(item["quem_decide"])
            self.assertTrue(item["acao"])
            self.assertTrue(item["detalhe"])
            self.assertIn(item["destino"], ("planejar", "operar", "vender"))

    def test_sem_problema_nao_inventa_pendencia(self):
        self.assertEqual(
            ui._pendencias({"coerencia": [], "demanda_nao_atendida": {}},
                           {"resumo": {}}, {"resumo": {}}, {"resumo": {}}),
            [])

    def test_hora_extra_no_singular(self):
        equipe = {"resumo": {"com_hora_extra": 1, "hora_extra_total_min": 16}}
        titulo = ui._pendencias({}, None, None, equipe)[0]["titulo"]
        self.assertEqual(titulo, "1 escala fecha com hora extra")


class TestSelo(unittest.TestCase):
    def test_todo_selo_explica_de_onde_veio(self):
        for origem in ("medido", "planejado", "informado", "simulado"):
            selo = ui._selo(origem)
            self.assertEqual(selo["rotulo"], origem)
            self.assertTrue(selo["explicacao"], origem)


class TestMontagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = ui.montar(chave_atual="prefeitura")

    def test_tem_os_quatro_destinos(self):
        for chave in ("pendencias", "resumo", "planejar", "operar", "mapa"):
            self.assertIn(chave, self.dados)

    def test_mapa_tem_o_que_desenhar(self):
        mapa = self.dados["mapa"]
        self.assertTrue(mapa["pontos"])
        self.assertTrue(mapa["viagens"])
        primeira = mapa["viagens"][0]
        self.assertTrue(primeira["paradas"])
        # toda parada desenhada precisa existir no dicionário de pontos
        for parada in primeira["paradas"]:
            self.assertIn(parada, mapa["pontos"])

    def test_importacao_so_entra_se_for_do_mesmo_arquivo(self):
        """O relatório de importação é de uma planilha; o plano, de outra."""
        arquivo = self.dados["planejar"]["arquivo"]
        origem = (self.dados["planejar"]["origem"] or {}).get("arquivo")
        self.assertEqual(arquivo, origem)

    def test_operacao_atual_marcada_no_seletor(self):
        atuais = [o for o in self.dados["operacoes"] if o["atual"]]
        self.assertEqual(len(atuais), 1)
        self.assertEqual(len(self.dados["operacoes"]), len(ui.OPERACOES))

    def test_frota_e_o_pior_turno_nao_a_soma(self):
        """A armadilha do projeto: somar os turnos infla a frota."""
        por_turno = self.dados["planejar"]["por_turno"]
        if por_turno:
            soma = sum(t["veiculos"] for t in por_turno)
            self.assertLessEqual(self.dados["resumo"]["veiculos"], soma)


class TestFretamento(unittest.TestCase):
    """A operação de empresa não empresta números do transporte escolar."""

    @classmethod
    def setUpClass(cls):
        caminho = os.path.join(ui.DIR_RELATORIOS, "plano-fretamento.json")
        if not os.path.exists(caminho):
            raise unittest.SkipTest("sem plano de fretamento gerado")
        cls.dados = ui.montar(caminho, chave_atual="empresa")

    def test_sem_fila_de_porta_a_porta(self):
        self.assertIsNone(self.dados["operar"]["elegibilidade"])

    def test_fala_a_lingua_de_quem_usa(self):
        self.assertEqual(self.dados["operacao"]["passageiros"], "colaboradores")
        self.assertEqual(self.dados["operacao"]["destinos"], "plantas")

    def test_problema_da_planilha_fala_de_colaborador(self):
        """O importador é escolar por dentro; a tela, não."""
        textos = " ".join(p["problema"] + " " + p["sugestao"]
                          for p in self.dados["planejar"]["problemas"])
        self.assertNotIn("aluno", textos.lower())
        self.assertIn("colaborador", textos.lower())

    def test_vender_tem_preco_e_diagnostico(self):
        vender = self.dados["vender"]
        self.assertIsNotNone(vender)
        preco = vender["preco"]["preco"]
        custo = vender["preco"]["custo"]
        self.assertGreater(preco["mes"], custo["total_mes"])
        # o preço sai por divisão: sobra margem DEPOIS do imposto
        sobra = preco["mes"] - custo["total_mes"] - preco["impostos_mes"]
        self.assertAlmostEqual(sobra, preco["lucro_mes"], places=0)
        self.assertTrue(vender["cenarios"])
        self.assertTrue((vender["diagnostico"] or {}).get("achados"))


class TestContrato(unittest.TestCase):
    """Filtro por cliente (empresa) e por fornecedor (governo).

    É a mesma relação vista dos dois lados; o que muda é o rótulo e quem
    está do outro lado do contrato.
    """

    @classmethod
    def setUpClass(cls):
        cls.escolar = ui.montar()
        caminho = os.path.join(ui.DIR_RELATORIOS, "plano-fretamento.json")
        cls.empresa = ui.montar(caminho) if os.path.exists(caminho) else None

    def test_prefeitura_filtra_por_fornecedor(self):
        self.assertEqual(self.escolar["operar"]["contratos"]["rotulo"],
                         "fornecedor")

    def test_empresa_filtra_por_cliente(self):
        if not self.empresa:
            self.skipTest("sem plano de fretamento gerado")
        self.assertEqual(self.empresa["operar"]["contratos"]["rotulo"],
                         "cliente")

    def test_toda_rota_tem_dono(self):
        """Rota sem contraparte cai fora do filtro e some da tela."""
        for dados in filter(None, (self.escolar, self.empresa)):
            for viagem in dados["mapa"]["viagens"]:
                self.assertTrue(viagem["contraparte_id"], viagem["id"])

    def test_as_rotas_do_contrato_somam_o_total(self):
        for dados in filter(None, (self.escolar, self.empresa)):
            contratos = dados["operar"]["contratos"]
            soma = sum(i["rotas"] for i in contratos["itens"])
            self.assertEqual(soma, len(dados["mapa"]["viagens"]))

    def test_casa_pelo_nome_quando_a_planilha_renumerou_o_destino(self):
        """Plano importado numera E1, E2, E3 — o id do perfil não sobrevive.

        Sem o casamento por nome, a operação de fretamento ficaria sem
        cliente nenhum e o filtro sumiria da tela.
        """
        if not self.empresa:
            self.skipTest("sem plano de fretamento gerado")
        ids = {d["id"] for d in self.empresa["mapa"]["destinos"]}
        self.assertTrue(ids and not ids & {"PL1", "PL2", "PL3"})
        self.assertTrue(all(d["contraparte"]
                            for d in self.empresa["mapa"]["destinos"]))

    def test_escala_de_veiculo_nao_soma_para_a_frota(self):
        """A armadilha do projeto, agora numa coluna nova."""
        contratos = self.escolar["operar"]["contratos"]
        soma = sum(i["escalas_de_veiculo"] for i in contratos["itens"])
        if soma > contratos["escalas_de_veiculo"]:
            self.assertTrue(contratos["veiculo_em_mais_de_um"])
        self.assertGreaterEqual(contratos["escalas_de_veiculo"],
                                self.escolar["resumo"]["veiculos"])

    def test_operacao_sem_contrato_declarado_nao_ganha_nome_inventado(self):
        perfil = {"id": "cliente-x", "vertical": "fretamento",
                  "contrapartes": []}
        self.assertEqual(ui._contrato(perfil), {})


class TestAjustes(unittest.TestCase):
    """Parâmetro que decide rota, frota ou preço mora numa tela, não numa
    constante de módulo."""

    @classmethod
    def setUpClass(cls):
        cls.dados = ui.montar()
        cls.ajustes = cls.dados["ajustes"]

    def test_tempo_a_bordo_e_parametro_visivel(self):
        tempo = self.ajustes["tempo"]
        self.assertTrue(tempo["max_trajeto_min"])
        self.assertTrue(tempo["fator_porta_a_porta"])
        self.assertIsNotNone(tempo["folga_porta_a_porta_min"])

    def test_o_tempo_mostrado_e_o_que_o_motor_usou(self):
        """Mostrar o padrão do perfil quando a rodada usou outro seria
        mentir sobre a rota que está na rua."""
        self.assertEqual(
            self.ajustes["tempo"]["max_trajeto_min"],
            self.dados["planejar"]["premissas"]["tempo_max_trajeto_min"])

    def test_catalogo_de_tipos_tem_o_que_o_motor_precisa(self):
        tipos = self.ajustes["tipos_veiculo"]
        self.assertTrue(tipos)
        for t in tipos:
            for campo in ("id", "nome", "capacidade", "custo_km",
                          "custo_fixo_mes", "consumo_km_l"):
                self.assertIn(campo, t)
                self.assertIsNotNone(t[campo], f"{t['id']}.{campo}")

    def test_todo_tipo_usado_no_plano_esta_no_catalogo(self):
        catalogo = {t["id"] for t in self.ajustes["tipos_veiculo"]}
        usados = {l["id"] for l in self.dados["planejar"]["frota_por_tipo"]
                  if l["quantos"]}
        self.assertTrue(usados)
        self.assertTrue(usados <= catalogo, usados - catalogo)

    def test_turno_aparece_com_a_janela_inteira(self):
        for turno in self.ajustes["turnos"]:
            self.assertTrue(turno["nome"])
            self.assertEqual(len(turno["janela_chegada"]), 2)
            self.assertTrue(turno["jornada_max_min"])


class TestFrotaPorTipo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = ui.montar()
        cls.linhas = cls.dados["planejar"]["frota_por_tipo"]

    def test_a_soma_por_tipo_e_a_frota(self):
        self.assertEqual(sum(l["quantos"] for l in self.linhas),
                         self.dados["resumo"]["veiculos"])

    def test_tipo_que_some_da_frota_continua_na_tabela(self):
        """Cortar 10 micro-ônibus é o resultado; escondê-lo é omissão."""
        atual = ui.economia_mod.carregar_relatorio(
            ui.economia_mod.RELATORIO_PADRAO)["frota_atual"]["composicao"]
        for tipo in atual:
            self.assertIn(tipo, {l["id"] for l in self.linhas})

    def test_lugares_batem_com_capacidade(self):
        for l in self.linhas:
            self.assertEqual(l["lugares"], (l["capacidade"] or 0) * l["quantos"])


class TestTempoABordoParametrizavel(unittest.TestCase):
    """O limite do porta a porta sai do perfil, não de constante fixa."""

    def test_perfil_aperta_e_afrouxa_o_limite(self):
        from dados import perfis as perfis_mod
        from dados.demanda_pcd import limite_tempo_bordo_min
        from dataclasses import replace

        padrao = limite_tempo_bordo_min(20)
        apertado = replace(perfis_mod.PERFIL_ESCOLAR, fator_tempo_bordo=1.2,
                           folga_tempo_bordo_min=5)
        frouxo = replace(perfis_mod.PERFIL_ESCOLAR, fator_tempo_bordo=2.0,
                         folga_tempo_bordo_min=30)
        self.assertLess(limite_tempo_bordo_min(20, apertado), padrao)
        self.assertGreater(limite_tempo_bordo_min(20, frouxo), padrao)

    def test_limite_sempre_maior_que_o_trajeto_direto(self):
        from dados.demanda_pcd import limite_tempo_bordo_min
        for direto in (5, 20, 45):
            self.assertGreater(limite_tempo_bordo_min(direto), direto)

    def test_perfil_de_arquivo_carrega_os_novos_parametros(self):
        from dados import perfis as perfis_mod
        perfil = perfis_mod.de_dicionario({
            "base": "escolar", "tempo_max_trajeto_min": 50,
            "fator_tempo_bordo": 1.3, "folga_tempo_bordo_min": 10})
        self.assertEqual(perfil.tempo_max_trajeto_min, 50)
        self.assertEqual(perfil.fator_tempo_bordo, 1.3)
        self.assertEqual(perfil.folga_tempo_bordo_min, 10)
        # e sobrevive à ida e volta pelo JSON que a tela grava
        volta = perfis_mod.de_dicionario(perfil.como_dicionario())
        self.assertEqual(volta.tempo_max_trajeto_min, 50)
        self.assertEqual(volta.fator_tempo_bordo, 1.3)


class TestHtmlGerado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.mkdtemp()
        cls.caminho = ui.gerar(os.path.join(cls.pasta, "sistema.html"))
        with open(cls.caminho, encoding="utf-8") as f:
            cls.html = f.read()

    def test_autocontido(self):
        """Sem internet a tela tem que abrir igual."""
        fora = re.findall(r'(?:src|href)="(?!#)(https?:|//)', self.html)
        self.assertEqual(fora, [], "a tela busca coisa fora do arquivo")

    def test_dados_embutidos_e_validos(self):
        self.assertNotIn("__DADOS__", self.html)
        bruto = re.search(r"var DADOS = (\{.*?\});\n", self.html, re.S)
        self.assertIsNotNone(bruto, "não achei o bloco de dados embutido")
        dados = json.loads(bruto.group(1))
        self.assertIn("pendencias", dados)

    def test_diz_que_e_demonstracao(self):
        self.assertIn("demonstração", self.html)

    def test_as_duas_operacoes_apontam_para_arquivos_que_existem(self):
        caminhos = ui.gerar_todas(self.pasta)
        self.assertEqual(len(caminhos), len(ui.OPERACOES))
        for caminho in caminhos:
            self.assertTrue(os.path.exists(caminho))
        nomes = {os.path.basename(c) for c in caminhos}
        for operacao in ui.OPERACOES:
            self.assertIn(operacao["arquivo"], nomes)


if __name__ == "__main__":
    unittest.main()
