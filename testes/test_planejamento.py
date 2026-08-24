# -*- coding: utf-8 -*-
"""
Testes do caminho planilha → rotas: agrupamento, envio e tela de planejamento.

O motor em si (OR-Tools) tem os testes dele e não roda aqui: a suíte precisa
passar em máquina sem dependência. O que se testa é a ponte — que é onde os
erros de verdade apareceram.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import agrupar  # noqa: E402
from planejamento import multipart  # noqa: E402


def aluno(ident, lat, lon, escola="EMEF Centro", turno="manha",
          bairro="Sede Urbana", cadeirante=False):
    return {"id": ident, "lat": lat, "lon": lon, "escola": escola,
            "turno": turno, "bairro": bairro, "cadeirante": cadeirante,
            "acompanhante": False}


class TestAgrupamento(unittest.TestCase):
    def test_alunos_vizinhos_viram_um_ponto_so(self):
        # ~100 m de distância: a criança caminha
        r = agrupar.agrupar([aluno("A1", -21.150, -47.800),
                             aluno("A2", -21.1509, -47.800)])
        self.assertEqual(r["resumo"]["pontos"], 1)
        self.assertEqual(r["resumo"]["alunos"], 2)

    def test_alunos_distantes_viram_pontos_diferentes(self):
        r = agrupar.agrupar([aluno("A1", -21.150, -47.800),
                             aluno("A2", -21.170, -47.830)])
        self.assertEqual(r["resumo"]["pontos"], 2)

    def test_cadeirante_nunca_e_agrupado(self):
        """Quem usa cadeira de rodas não atravessa 300 m de estrada de terra."""
        r = agrupar.agrupar([aluno("A1", -21.150, -47.800),
                             aluno("A2", -21.1501, -47.800, cadeirante=True)])
        self.assertEqual(r["resumo"]["pontos"], 2)
        self.assertEqual(r["resumo"]["pontos_exclusivos_de_cadeirante"], 1)

    def test_escolas_diferentes_nao_compartilham_ponto(self):
        r = agrupar.agrupar([aluno("A1", -21.150, -47.800),
                             aluno("A2", -21.150, -47.800,
                                   escola="EMEF Vila Rural Sul")])
        self.assertEqual(r["resumo"]["pontos"], 2)

    def test_zona_rural_usa_raio_maior(self):
        distantes = [aluno("A1", -21.150, -47.800, bairro="Assentamento Oeste"),
                     aluno("A2", -21.1545, -47.800, bairro="Assentamento Oeste")]
        self.assertEqual(agrupar.agrupar(distantes)["resumo"]["pontos"], 1)
        urbanos = [dict(a, bairro="Centro") for a in distantes]
        self.assertEqual(agrupar.agrupar(urbanos)["resumo"]["pontos"], 2)

    def test_ponto_fica_no_meio_de_quem_ele_atende(self):
        r = agrupar.agrupar([aluno("A1", -21.1500, -47.800),
                             aluno("A2", -21.1520, -47.800)])
        ponto = r["pontos"][0]
        self.assertAlmostEqual(ponto.lat, -21.151, places=3)

    def test_mesma_planilha_gera_os_mesmos_pontos(self):
        alunos = [aluno(f"A{i}", -21.15 - i * 0.001, -47.80) for i in range(8)]
        a = agrupar.agrupar(list(alunos))["resumo"]
        b = agrupar.agrupar(list(reversed(alunos)))["resumo"]
        self.assertEqual(a["pontos"], b["pontos"])

    def test_escola_sem_cadastro_e_estimada_com_aviso(self):
        r = agrupar.agrupar([aluno("A1", -21.15, -47.80, escola="Escola Nova")])
        self.assertEqual(r["escolas"][0]["origem_da_coordenada"],
                         "estimada pelo centro dos alunos")
        self.assertTrue(any("marque a escola no mapa" in a for a in r["avisos"]))

    def test_coordenada_informada_pelo_municipio_manda(self):
        r = agrupar.agrupar([aluno("A1", -21.15, -47.80, escola="Escola Nova")],
                            coordenadas_escolas={"Escola Nova": (-21.1, -47.7)})
        self.assertEqual(r["escolas"][0]["lat"], -21.1)
        self.assertIn("informada", r["escolas"][0]["origem_da_coordenada"])

    def test_aluno_sem_coordenada_fica_de_fora_com_aviso(self):
        r = agrupar.agrupar([aluno("A1", -21.15, -47.80),
                             aluno("A2", None, None)])
        self.assertEqual(r["resumo"]["alunos"], 1)
        self.assertTrue(any("ficaram de fora" in a for a in r["avisos"]))

    def test_escola_sem_nenhum_aluno_localizado_nao_e_inventada(self):
        """Sem coordenada e sem aluno localizado, não há centro que calcular."""
        r = agrupar.agrupar([aluno("A1", None, None, escola="Escola Nova")])
        self.assertEqual(r["escolas"], [])
        self.assertTrue(any("Marque a escola no mapa" in a for a in r["avisos"]))

    def test_turnos_sao_contados_separados(self):
        r = agrupar.agrupar([aluno("A1", -21.150, -47.800, turno="manha"),
                             aluno("A2", -21.1502, -47.800, turno="tarde")])
        ponto = r["pontos"][0]
        self.assertEqual(ponto.alunos["manha"], 1)
        self.assertEqual(ponto.alunos["tarde"], 1)


class TestJanelaDeChegada(unittest.TestCase):
    """A janela de chegada como parâmetro declarado.

    É o parâmetro de maior efeito sobre a frota: na operação real de 456
    alunos, abrir de 20 para 45 minutos derrubou a manhã de 52 para 32
    veículos — enquanto trocar o modelo do veículo valeu um carro. Estava
    enterrado na definição de cada turno, onde ninguém mexe.
    """

    def perfil(self, **kw):
        from dados import perfis as perfis_mod
        from dataclasses import replace
        return replace(perfis_mod.PERFIL_ESCOLAR, **kw)

    def test_sem_o_parametro_os_turnos_ficam_como_estao(self):
        p = self.perfil()
        self.assertEqual([t.janela_chegada for t in p.turnos_com_janela()],
                         [t.janela_chegada for t in p.turnos])

    def test_a_janela_move_o_inicio_e_nao_o_sinal(self):
        """A hora da aula não se negocia; o que se negocia é chegar antes."""
        p = self.perfil(janela_chegada_min=45)
        for antes, depois in zip(p.turnos, p.turnos_com_janela()):
            self.assertEqual(depois.janela_chegada[1], antes.janela_chegada[1])
            self.assertEqual(depois.janela_chegada[0],
                             antes.janela_chegada[1] - 45)

    def test_janela_maior_que_o_dia_nao_vira_horario_negativo(self):
        p = self.perfil(janela_chegada_min=10_000)
        for t in p.turnos_com_janela():
            self.assertGreaterEqual(t.janela_chegada[0], 0)

    def test_o_parametro_atravessa_o_json_do_perfil(self):
        from dados import perfis as perfis_mod
        dados = self.perfil(janela_chegada_min=30).como_dicionario()
        self.assertEqual(dados["janela_chegada_min"], 30)
        voltou = perfis_mod.de_dicionario(dados)
        self.assertEqual(voltou.janela_chegada_min, 30)

    def test_perfil_antigo_sem_o_campo_continua_carregando(self):
        """JSON gravado antes deste parâmetro existir não pode quebrar."""
        from dados import perfis as perfis_mod
        dados = self.perfil().como_dicionario()
        dados.pop("janela_chegada_min")
        self.assertEqual(perfis_mod.de_dicionario(dados).janela_chegada_min, 0)


class TestFrotaDeclaradaNaPlanilha(unittest.TestCase):
    """De qual aba sai a frota de hoje.

    "É a segunda aba" funcionava no arquivo de demonstração e falhava no
    arquivo real, onde a segunda aba é a segunda metade dos alunos.
    """

    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-frota-")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def arquivo(self, abas):
        from dados.planilha_exemplo import escrever_xlsx
        return escrever_xlsx(os.path.join(self.pasta, "p.xlsx"), abas)

    ALUNOS = [["Aluno", "Endereço do Aluno", "CEP", "Escola"],
              ["Ana", "Rua A, 10", "04416-200", "Escola X"]]

    def test_acha_a_aba_de_frota_pelo_nome(self):
        from motor.planejar import ler_frota_declarada
        caminho = self.arquivo({
            "Sul -1": self.ALUNOS, "Sul-2": self.ALUNOS,
            "Frota atual": [["Tipo", "Capacidade", "Quantidade"],
                            ["Van 15 lugares acessível", "15", "4"]]})
        frota = ler_frota_declarada(caminho)
        self.assertEqual(sum(frota["composicao"].values()), 4)
        self.assertIn("Frota atual", frota["origem"])

    def test_lista_de_alunos_na_segunda_aba_nao_vira_frota(self):
        """O arquivo real: a aba 2 é mais 273 alunos, não é veículo nenhum."""
        from motor.planejar import ler_frota_declarada
        caminho = self.arquivo({"Sul -1": self.ALUNOS, "Sul-2": self.ALUNOS})
        self.assertEqual(ler_frota_declarada(caminho), {})


class TestEnvioDeArquivo(unittest.TestCase):
    def corpo(self, nome="planilha.csv", conteudo=b"nome;bairro\nAna;Centro\n",
              extra=None):
        f = "----limite123"
        partes = [f"--{f}\r\nContent-Disposition: form-data; name=\"planilha\"; "
                  f"filename=\"{nome}\"\r\nContent-Type: text/csv\r\n\r\n"
                  .encode("utf-8") + conteudo + b"\r\n"]
        for chave, valor in (extra or {}).items():
            partes.append(f"--{f}\r\nContent-Disposition: form-data; "
                          f"name=\"{chave}\"\r\n\r\n{valor}\r\n".encode("utf-8"))
        partes.append(f"--{f}--\r\n".encode("utf-8"))
        return b"".join(partes), f'multipart/form-data; boundary={f}'

    def test_le_arquivo_e_campos(self):
        corpo, tipo = self.corpo(extra={"municipio": "Ribeirão"})
        campos = multipart.analisar(corpo, tipo)
        self.assertEqual(campos["planilha"]["nome"], "planilha.csv")
        self.assertIn(b"Ana", campos["planilha"]["conteudo"])
        self.assertEqual(campos["municipio"], "Ribeirão")

    def test_nome_de_arquivo_com_caminho_e_saneado(self):
        corpo, tipo = self.corpo(nome="../../etc/passwd")
        campos = multipart.analisar(corpo, tipo)
        self.assertEqual(campos["planilha"]["nome"], "passwd")

    def test_envio_sem_fronteira_e_recusado(self):
        with self.assertRaises(multipart.ErroDeEnvio):
            multipart.analisar(b"qualquer coisa", "multipart/form-data")

    def test_arquivo_grande_demais_e_recusado(self):
        grande = b"x" * (multipart.TAMANHO_MAXIMO + 1)
        with self.assertRaises(multipart.ErroDeEnvio):
            multipart.analisar(grande, "multipart/form-data; boundary=abc")

    def test_conteudo_binario_sobrevive(self):
        """xlsx é zip: um byte trocado corrompe o arquivo inteiro."""
        binario = bytes(range(256)) * 4
        corpo, tipo = self.corpo(nome="p.xlsx", conteudo=binario)
        campos = multipart.analisar(corpo, tipo)
        self.assertEqual(campos["planilha"]["conteudo"], binario)


class TestTelaDePlanejamento(unittest.TestCase):
    """Sobe o servidor de verdade, mas sem chamar o solver."""

    @classmethod
    def setUpClass(cls):
        from planejamento import servidor as servidor_mod
        cls.mod = servidor_mod
        cls.pasta = tempfile.mkdtemp(prefix="mobgov-plan-")
        servidor_mod.DIR_TRABALHO = os.path.join(cls.pasta, "planejamento")
        servidor_mod.DIR_RELATORIOS = cls.pasta
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0),
                                           servidor_mod.Planejamento)
        cls.url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def setUp(self):
        self.mod.ESTADO.importacao = None
        self.mod.ESTADO.plano = None
        self.mod.ESTADO.progresso = []
        self.mod.ESTADO.rodando = False

    def get(self, caminho):
        with urllib.request.urlopen(self.url + caminho) as r:
            return json.loads(r.read())

    def post(self, caminho, corpo=None, tipo="application/json"):
        dados = (json.dumps(corpo).encode("utf-8") if isinstance(corpo, dict)
                 else (corpo or b""))
        req = urllib.request.Request(self.url + caminho, data=dados,
                                     headers={"Content-Type": tipo},
                                     method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def enviar_planilha(self):
        linhas = ["nome;endereco;bairro;escola;turno;cadeirante;lat;lon"]
        for i in range(6):
            linhas.append(f"Aluno {i};Rua A {i};Sede Urbana;EMEF Centro;"
                          f"Manhã;nao;{-21.15 - i * 0.002};-47.80")
        linhas.append("Sem Coordenada;Estrada X;Sede Urbana;EMEF Centro;"
                      "Manhã;nao;;")
        csv = ("\n".join(linhas) + "\n").encode("utf-8")
        f = "----limite999"
        corpo = (f"--{f}\r\nContent-Disposition: form-data; name=\"planilha\"; "
                 f"filename=\"turma.csv\"\r\n\r\n".encode("utf-8") + csv
                 + f"\r\n--{f}--\r\n".encode("utf-8"))
        return self.post("/api/enviar-planilha", corpo,
                         f"multipart/form-data; boundary={f}")

    def test_tela_e_servida_e_autocontida(self):
        with urllib.request.urlopen(self.url + "/") as r:
            html = r.read().decode("utf-8")
        self.assertIn("Planejamento", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("src=", html)

    def test_envio_devolve_resumo_e_pontos(self):
        d = self.enviar_planilha()
        self.assertEqual(d["resumo"]["alunos_importados"], 7)
        self.assertEqual(len(d["pontos"]), 7)
        self.assertTrue(any(p["ajustar"] for p in d["pontos"]))

    def test_envio_sem_arquivo_explica(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/enviar-planilha", b"--x--\r\n",
                      "multipart/form-data; boundary=x")
        self.assertEqual(ctx.exception.code, 400)

    def test_ajuste_no_mapa_corrige_a_coordenada(self):
        d = self.enviar_planilha()
        alvo = next(p for p in d["pontos"] if p["ajustar"])
        antes = d["resumo"]["precisam_ajuste_no_mapa"]
        resposta = self.post("/api/ajustar", {"aluno": alvo["id"],
                                              "lat": -21.1611, "lon": -47.8122})
        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["faltam"], antes - 1)
        estado = self.get("/api/estado")["importacao"]
        ajustado = next(p for p in estado["pontos"] if p["id"] == alvo["id"])
        self.assertFalse(ajustado["ajustar"])
        self.assertAlmostEqual(ajustado["lat"], -21.1611)

    def test_ajuste_de_aluno_inexistente(self):
        self.enviar_planilha()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/ajustar", {"aluno": "NAO-EXISTE", "lat": 1, "lon": 2})
        self.assertEqual(ctx.exception.code, 404)

    def test_roteirizar_sem_planilha_e_recusado(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/roteirizar", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_publicar_sem_plano_e_recusado(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/publicar", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_roteirizacao_roda_em_segundo_plano_e_relata_erro(self):
        """Se o motor falhar, o gestor vê o motivo — não uma tela parada."""
        self.enviar_planilha()
        original = self.mod.planejar_mod.planejar
        self.mod.planejar_mod.planejar = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("solver não fechou"))
        try:
            self.post("/api/roteirizar", {"tempo_limite": 1})
            for _ in range(50):
                estado = self.get("/api/estado")
                if not estado["rodando"]:
                    break
            self.assertIn("solver não fechou", estado["erro"])
        finally:
            self.mod.planejar_mod.planejar = original

    def test_perfil_escolhido_no_envio_manda_nos_turnos(self):
        """T1 numa operação escolar não é turno: o perfil valida isso."""
        linhas = ["Colaborador;Endereço;Bairro;Planta;Turno;Lat;Lon"]
        linhas.append("Ana;Rua A 1;Sede Urbana;Planta 1;T1;-21.15;-47.80")
        csv = ("\n".join(linhas) + "\n").encode("utf-8")
        f = "----limite777"
        corpo = (f"--{f}\r\nContent-Disposition: form-data; name=\"planilha\"; "
                 f"filename=\"rh.csv\"\r\n\r\n".encode("utf-8") + csv
                 + f"\r\n--{f}\r\nContent-Disposition: form-data; "
                   f"name=\"perfil\"\r\n\r\nfretamento\r\n"
                   f"--{f}--\r\n".encode("utf-8"))
        d = self.post("/api/enviar-planilha", corpo,
                      f"multipart/form-data; boundary={f}")
        self.assertEqual(d["perfil"]["id"], "fretamento")
        self.assertIn("t1", d["resumo"]["por_turno"])

    def test_perfil_desconhecido_e_recusado(self):
        f = "----limite888"
        corpo = (f"--{f}\r\nContent-Disposition: form-data; name=\"planilha\"; "
                 f"filename=\"x.csv\"\r\n\r\nnome;endereco\nA;B\n"
                 f"\r\n--{f}\r\nContent-Disposition: form-data; "
                 f"name=\"perfil\"\r\n\r\nmarciano\r\n"
                 f"--{f}--\r\n").encode("utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/enviar-planilha", corpo,
                      f"multipart/form-data; boundary={f}")
        self.assertEqual(ctx.exception.code, 400)

    def test_precificar_sem_plano_e_recusado(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/precificar", {"margem": 12})
        self.assertEqual(ctx.exception.code, 400)

    def test_diagnostico_sem_plano_e_recusado(self):
        f = "----limite999"
        corpo = (f"--{f}\r\nContent-Disposition: form-data; name=\"linhas\"; "
                 f"filename=\"l.csv\"\r\n\r\nLinha;Tipo\nL1;VAN16\n"
                 f"\r\n--{f}--\r\n").encode("utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/enviar-linhas", corpo,
                      f"multipart/form-data; boundary={f}")
        self.assertEqual(ctx.exception.code, 400)

    def test_proposta_so_existe_depois_de_precificar(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/proposta")
        self.assertEqual(ctx.exception.code, 404)

    def test_publicar_grava_o_plano_e_guarda_o_anterior(self):
        self.enviar_planilha()
        self.mod.ESTADO.plano = {
            "frota_otimizada": {"total_veiculos": 3, "viagens": [1, 2],
                                "composicao": {"VAN15A": 3}, "km_dia": 10.0,
                                "custo_mes": 100},
        }
        anterior = os.path.join(self.mod.DIR_RELATORIOS, "dimensionamento.json")
        os.makedirs(self.mod.DIR_RELATORIOS, exist_ok=True)
        with open(anterior, "w", encoding="utf-8") as f:
            json.dump({"plano": "antigo"}, f)

        resposta = self.post("/api/publicar", {})
        self.assertTrue(resposta["publicado"])
        with open(anterior, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["frota_otimizada"]["total_veiculos"], 3)
        historico = os.path.join(self.mod.DIR_TRABALHO, "historico")
        self.assertTrue(os.listdir(historico))   # o antigo não foi apagado

    # ------------------------------------------------- cadastro de parâmetros
    def test_cadastro_de_tipo_de_veiculo_e_gravado_e_sobrevive(self):
        """A frota disponível é cadastro, não constante do código."""
        from dados import perfis as perfis_mod
        base = perfis_mod.PERFIL_ESCOLAR.como_dicionario()
        base["tipos_veiculo"] = base["tipos_veiculo"] + [{
            "id": "ONIBUS44", "nome": "Ônibus 44 lugares", "capacidade": 44,
            "posicoes_cadeirante": 0, "custo_km": 3.9,
            "custo_fixo_mes": 16800.0, "consumo_km_l": 2.7}]
        base["tempo_max_trajeto_min"] = 60

        resposta = self.post("/api/perfil", base)
        self.assertTrue(resposta["ok"])
        ids = [t["id"] for t in resposta["perfil"]["tipos_veiculo"]]
        self.assertIn("ONIBUS44", ids)
        self.assertEqual(resposta["perfil"]["tempo_max_trajeto_min"], 60)

        # gravado em disco: quem cadastrou na sexta não recadastra na segunda
        caminho = os.path.join(self.mod.DIR_TRABALHO, "perfil.json")
        self.assertTrue(os.path.exists(caminho))
        self.mod.ESTADO.perfil = perfis_mod.PERFIL_ESCOLAR
        self.mod.ESTADO.recuperar_perfil()
        self.assertEqual(self.mod.ESTADO.perfil.tempo_max_trajeto_min, 60)
        self.assertIn("ONIBUS44",
                      [t.id for t in self.mod.ESTADO.perfil.tipos_veiculo])
        self.mod.ESTADO.perfil = perfis_mod.PERFIL_ESCOLAR
        os.remove(caminho)

    def test_operacao_sem_nenhum_tipo_de_veiculo_e_recusada(self):
        """Sem tipo cadastrado o solver não tem o que usar — recusar aqui é
        melhor do que descobrir no meio da roteirização."""
        from dados import perfis as perfis_mod
        base = perfis_mod.PERFIL_ESCOLAR.como_dicionario()
        base["tipos_veiculo"] = []
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/perfil", base)
        self.assertEqual(ctx.exception.code, 400)

    def test_tempo_maximo_a_bordo_invalido_e_recusado(self):
        from dados import perfis as perfis_mod
        base = perfis_mod.PERFIL_ESCOLAR.como_dicionario()
        base["tempo_max_trajeto_min"] = 0
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/perfil", base)
        self.assertEqual(ctx.exception.code, 400)

    def test_tempo_a_bordo_da_rodada_chega_no_motor(self):
        """A secretaria aperta o tempo numa rodada sem reconfigurar tudo."""
        self.enviar_planilha()
        recebido = {}
        original = self.mod.planejar_mod.planejar

        def espiao(*a, **kw):
            recebido.update(kw)
            return {"frota_otimizada": {"total_veiculos": 1, "viagens": [],
                                        "composicao": {}, "km_dia": 0.0,
                                        "custo_mes": 0}}

        self.mod.planejar_mod.planejar = espiao
        try:
            self.post("/api/roteirizar", {"tempo_limite": 1,
                                          "tempo_max_trajeto": 55})
            for _ in range(50):
                if not self.get("/api/estado")["rodando"]:
                    break
            self.assertEqual(recebido.get("tempo_max_trajeto_min"), 55)
        finally:
            self.mod.planejar_mod.planejar = original

    # ------------------------------------------- a tela nova, servida ao vivo
    def test_sistema_e_servido_e_autocontido(self):
        with urllib.request.urlopen(self.url + "/sistema") as r:
            html = r.read().decode("utf-8")
        self.assertIn("MOBGOV", html)
        self.assertNotIn("__DADOS__", html)
        self.assertNotIn("src=\"http", html)

    def test_sistema_sem_planilha_pede_a_planilha(self):
        """Vazio é estado previsto: a operação acabou de começar."""
        from ui import gerar as ui_mod
        dados = ui_mod.montar_ao_vivo()
        self.assertTrue(dados["ao_vivo"])
        self.assertEqual(len(dados["pendencias"]), 1)
        self.assertIn("planilha", dados["pendencias"][0]["titulo"].lower())
        self.assertTrue(dados["pendencias"][0]["acao"])
        # nada inventado para "não deixar a tela feia"
        self.assertIsNone(dados["resumo"]["veiculos"])
        self.assertIsNone(dados["resumo"]["economia_mes"])

    def test_sistema_depois_do_envio_mostra_o_arquivo(self):
        from ui import gerar as ui_mod
        self.enviar_planilha()
        dados = ui_mod.montar_ao_vivo(
            importacao=self.mod.ESTADO.resumo_da_importacao(),
            perfil=self.mod.ESTADO.perfil_em_dicionario())
        self.assertEqual(dados["planejar"]["arquivo"], "turma.csv")
        self.assertTrue(dados["planejar"]["importacao"]["alunos_importados"])
        # os endereços já geocodificados vão para o mapa
        self.assertTrue(dados["mapa"]["pontos"])

    def test_plano_sem_frota_atual_informada_nao_quebra_o_painel(self):
        """O caso comum: o município não informou a frota de hoje.

        O motor se recusa a estimar, então não há 'antes'. Isso é estado
        previsto — economia vazia e a explicação do que falta, nunca erro.
        """
        from ui import gerar as ui_mod
        plano = {
            "municipio": "Teste", "gerado_em": "hoje",
            "demanda": {"alunos": 10, "escolas": 1, "pontos_embarque": 3,
                        "cadeirantes": 0,
                        "alunos_por_turno": {"manha": 10},
                        "turnos": [{"id": "manha", "nome": "Manhã",
                                    "jornada_max_min": 100}]},
            "premissas": {"custos_por_tipo": {
                "VAN15A": {"nome": "Van", "capacidade": 15,
                           "posicoes_cadeirante": 2, "fixo_mes": 10200.0,
                           "custo_km": 1.95, "consumo_km_l": 6.0}},
                "dias_letivos_mes": 22, "preco_diesel_l": 6.1,
                "fator_co2_kg_l": 2.68, "tempo_max_trajeto_min": 75,
                "tempo_virada_min": 5, "viagens_por_rota": 2},
            "frota_atual": None,
            "comparacao_indisponivel": "a frota atual não foi informada",
            "frota_otimizada": {
                "composicao": {"VAN15A": 1}, "total_veiculos": 1,
                "km_dia": 30.0, "custo_mes": 12000.0, "litros_dia": 5.0,
                "viagens": [{"id": "V1", "veiculo": "V1", "turno": "manha",
                             "turno_nome": "Manhã", "escola_id": "E1",
                             "escola": "E", "paradas": [], "alunos": 10,
                             "km_viagem": 30.0, "min_viagem": 40,
                             "ocupacao_pct": 66, "tipo": "VAN15A",
                             "tipo_nome": "Van", "cadeirantes": 0}],
                "veiculos": [{"id": "V1", "turno": "manha",
                              "turno_nome": "Manhã", "tipo": "VAN15A",
                              "tipo_nome": "Van", "capacidade": 15,
                              "min_turno": 40, "km_turno": 30.0, "alunos": 10,
                              "ocupacao_media_pct": 66, "viagens": ["V1"]}],
                "por_turno": [{"turno": "Manhã", "alunos": 10, "viagens": 1,
                               "veiculos": 1, "lugares_ofertados": 15}]},
        }
        dados = ui_mod.montar_ao_vivo(plano=plano)
        self.assertEqual(dados["resumo"]["veiculos"], 1)
        self.assertIsNone(dados["resumo"]["economia_mes"])
        self.assertTrue(dados["planejar"]["frota_por_tipo"])


if __name__ == "__main__":
    unittest.main()
