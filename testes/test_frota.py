# -*- coding: utf-8 -*-
"""
Testes do cadastro de frota por veículo (Sprint 16).

O que está sendo protegido aqui é uma descoberta do primeiro arquivo real: o
tamanho da frota que o motor calcula depende inteiramente da configuração do
veículo que se supõe. Van de 15 lugares e carro de "2 cadeirantes + 4 alunos"
dão respostas que diferem em 15 carros para a MESMA demanda. Por isso a
configuração precisa entrar como dado — e precisa entrar certa.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import frota as frota_mod  # noqa: E402
from dados.planilha_exemplo import escrever_xlsx  # noqa: E402

CABECALHO = ["Placa", "Tipo", "Capacidade total", "Capacidade PCD",
             "Capacidade alunos", "Monitora", "Contrato", "Turnos", "Ativo"]


def linha(placa="ABC1D23", tipo="Van acessível", total=12, pcd=2, alunos=6,
          monitora="sim", contrato="01/2025", turnos="manhã e tarde",
          ativo="sim"):
    return [placa, tipo, str(total), str(pcd), str(alunos), monitora,
            contrato, turnos, ativo]


class BaseFrota(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="mobgov-frota-")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def importar(self, linhas, **kw):
        caminho = escrever_xlsx(os.path.join(self.pasta, "frota.xlsx"), linhas)
        return frota_mod.importar(caminho, **kw)


class TestLeitura(BaseFrota):
    def test_le_um_veiculo_com_placa(self):
        r = self.importar([CABECALHO, linha()])
        self.assertEqual(len(r.veiculos), 1)
        v = r.veiculos[0]
        self.assertEqual(v.placa, "ABC1D23")
        self.assertEqual(v.capacidade_alunos, 6)
        self.assertEqual(v.capacidade_pcd, 2)
        self.assertEqual(v.contrato, "01/2025")
        self.assertEqual(v.turnos, ("manha", "tarde"))
        self.assertTrue(v.ativo)

    def test_placa_normaliza_formato(self):
        for escrito in ("abc-1d23", "ABC 1D23", "abc1d23"):
            self.assertEqual(frota_mod.normalizar_placa(escrito), "ABC1D23")
        self.assertEqual(frota_mod.normalizar_placa("carro do João"), "")

    def test_placa_torta_vira_aviso_e_o_carro_entra(self):
        r = self.importar([CABECALHO, linha(placa="carro 7")])
        self.assertEqual(len(r.veiculos), 1)
        self.assertEqual(r.veiculos[0].placa, "")
        self.assertTrue(any(p["campo"] == "placa" for p in r.problemas))

    def test_placa_repetida_entra_uma_vez_so(self):
        r = self.importar([CABECALHO, linha(), linha()])
        self.assertEqual(len(r.veiculos), 1)
        self.assertTrue(any("repetida" in p["problema"] for p in r.problemas))

    def test_carro_parado_nao_conta_como_frota(self):
        r = self.importar([CABECALHO, linha(), linha(placa="XYZ2E45",
                                                     ativo="manutenção")])
        self.assertEqual(len(r.veiculos), 2)
        self.assertEqual(len(r.ativos), 1)
        self.assertEqual(r.resumo()["parados"], 1)

    def test_lista_de_alunos_nao_e_lida_como_frota(self):
        """A aba "Sul-2" do arquivo real não pode virar veículo."""
        alunos = [["Aluno", "Endereço do Aluno", "CEP", "Escola"],
                  ["Ana", "Rua A, 10", "04416-200", "Escola X"]]
        caminho = escrever_xlsx(os.path.join(self.pasta, "mista.xlsx"),
                                {"Sul-2": alunos, "Frota": [CABECALHO, linha()]})
        r = frota_mod.importar(caminho)
        self.assertEqual(r.aba, "Frota")
        self.assertEqual(len(r.veiculos), 1)


class TestContaDeLugares(BaseFrota):
    def test_deduz_alunos_quando_a_planilha_nao_diz(self):
        """8 lugares − motorista − monitora − 2×3 da cadeira + 2 posições."""
        cabecalho = ["Placa", "Tipo", "Capacidade total", "Capacidade PCD",
                     "Monitora"]
        r = self.importar([cabecalho, ["ABC1D23", "Van", "8", "2", "sim"]])
        self.assertEqual(r.veiculos[0].capacidade_alunos, 2)
        self.assertTrue(any(p["campo"] == "capacidade_alunos"
                            for p in r.problemas))

    def test_sem_cadeirante_a_deducao_e_a_conta_simples(self):
        cabecalho = ["Placa", "Tipo", "Capacidade total", "Monitora"]
        r = self.importar([cabecalho, ["ABC1D23", "Van", "16", "sim"]])
        self.assertEqual(r.veiculos[0].capacidade_alunos, 14)

    def test_sem_monitora_sobra_um_lugar_a_mais(self):
        cabecalho = ["Placa", "Tipo", "Capacidade total", "Monitora"]
        r = self.importar([cabecalho, ["ABC1D23", "Van", "16", "não"]])
        self.assertEqual(r.veiculos[0].capacidade_alunos, 15)

    def test_conta_que_nao_fecha_vira_aviso_mas_vale_o_declarado(self):
        r = self.importar([CABECALHO, linha(total=8, pcd=2, alunos=9)])
        self.assertEqual(r.veiculos[0].capacidade_alunos, 9)
        aviso = [p for p in r.problemas if "não fecha" in p["problema"]]
        self.assertTrue(aviso)
        self.assertIn("9", aviso[0]["sugestao"])

    def test_avisa_quando_o_cadeirante_ficou_fora_da_capacidade(self):
        """A confusão cara: contar só os sentados.

        Num carro de 2 cadeiras + 4 assentos, declarar 4 em vez de 6 tira dois
        alunos de cada carro e inventa frota que não está faltando.
        """
        r = self.importar([CABECALHO, linha(total=12, pcd=2, alunos=4)])
        aviso = [p for p in r.problemas if "cadeirantes" in p["problema"]]
        self.assertTrue(aviso)
        self.assertIn("6", aviso[0]["sugestao"])
        self.assertEqual(r.veiculos[0].capacidade_alunos, 4)   # vale o declarado

    def test_veiculo_sem_lugar_para_aluno_e_recusado(self):
        r = self.importar([CABECALHO, linha(total=2, pcd=0, alunos=0)])
        self.assertEqual(r.veiculos, [])
        self.assertTrue(any(p["gravidade"] == "erro" for p in r.problemas))


class TestPonteComOMotor(BaseFrota):
    def test_veiculos_iguais_viram_um_tipo_so_e_guardam_as_placas(self):
        r = self.importar([CABECALHO, linha(), linha(placa="XYZ2E45"),
                           linha(placa="QRS3F67", total=16, pcd=0, alunos=14)])
        tipos, composicao, placas = frota_mod.tipos_e_composicao(r.veiculos)
        self.assertEqual(len(tipos), 2)
        self.assertEqual(sorted(composicao.values()), [1, 2])
        # o caminho de volta existe: o plano precisa dizer qual carro faz o quê
        do_par = [i for i, q in composicao.items() if q == 2][0]
        self.assertEqual(sorted(placas[do_par]), ["ABC1D23", "XYZ2E45"])

    def test_o_tipo_leva_a_capacidade_de_alunos_e_as_posicoes(self):
        r = self.importar([CABECALHO, linha()])
        tipos, _, _ = frota_mod.tipos_e_composicao(r.veiculos)
        self.assertEqual(tipos[0].capacidade, 6)
        self.assertEqual(tipos[0].posicoes_cadeirante, 2)

    def test_carro_parado_fica_fora_da_composicao(self):
        r = self.importar([CABECALHO, linha(),
                           linha(placa="XYZ2E45", ativo="parado")])
        _, composicao, _ = frota_mod.tipos_e_composicao(r.veiculos)
        self.assertEqual(sum(composicao.values()), 1)


class TestModeloDePlanilha(BaseFrota):
    def test_o_modelo_que_geramos_e_lido_pelo_importador(self):
        """Um modelo que o próprio sistema não lê de volta é uma armadilha."""
        caminho = frota_mod.modelo_de_planilha(
            os.path.join(self.pasta, "modelo.xlsx"))
        r = frota_mod.importar(caminho)
        self.assertEqual(r.aba, "Frota")
        self.assertEqual(len(r.veiculos), 2)
        self.assertEqual(r.veiculos[0].capacidade_alunos, 6)
        self.assertEqual(r.veiculos[0].capacidade_pcd, 2)
        self.assertEqual(r.veiculos[0].custo_km, 1.95)
        self.assertEqual(r.veiculos[1].turnos, ("manha",))
        # as linhas de exemplo não podem sair com aviso: elas são o formato
        self.assertEqual([p for p in r.problemas
                          if p["gravidade"] == "erro"], [])

    def test_o_modelo_explica_coluna_por_coluna(self):
        from dados.planilha import abas, ler
        caminho = frota_mod.modelo_de_planilha(
            os.path.join(self.pasta, "modelo.xlsx"))
        self.assertIn("Como preencher", abas(caminho))
        texto = " ".join(" ".join(l) for l in ler(caminho, "Como preencher"))
        self.assertIn("CADEIRANTE INCLUÍDO", texto)


class TestCabeADemanda(BaseFrota):
    def frota_de(self, quantos, **kw):
        placas = [f"AAA{i}A{i:02d}" for i in range(1, quantos + 1)]
        r = self.importar([CABECALHO] + [linha(placa=p, **kw) for p in placas])
        return r.veiculos

    def test_diz_quantos_lugares_faltam(self):
        """10 carros de 6 alunos não levam 268 alunos numa viagem."""
        conta = frota_mod.cabe_a_demanda(
            self.frota_de(10), {"manha": 268}, {"manha": 42})
        self.assertFalse(conta["manha"]["cabe"])
        self.assertEqual(conta["manha"]["lugares_ofertados"], 60)
        self.assertEqual(conta["manha"]["faltam_lugares"], 208)

    def test_separa_falta_de_assento_de_falta_de_posicao_de_cadeira(self):
        """São veículos diferentes; confundir os dois é o erro clássico."""
        conta = frota_mod.cabe_a_demanda(
            self.frota_de(20, pcd=0, total=6, alunos=4),
            {"manha": 60}, {"manha": 10})
        self.assertEqual(conta["manha"]["limita"],
                         "posição de cadeira de rodas")
        self.assertEqual(conta["manha"]["faltam_lugares"], 0)
        self.assertEqual(conta["manha"]["faltam_posicoes_cadeirante"], 10)

    def test_duas_viagens_por_veiculo_dobram_a_oferta(self):
        uma = frota_mod.cabe_a_demanda(
            self.frota_de(10), {"manha": 80}, {"manha": 0})
        duas = frota_mod.cabe_a_demanda(
            self.frota_de(10), {"manha": 80}, {"manha": 0},
            viagens_por_veiculo=2)
        self.assertFalse(uma["manha"]["cabe"])
        self.assertEqual(duas["manha"]["lugares_ofertados"], 120)
        self.assertTrue(duas["manha"]["cabe"])

    def test_carro_so_da_manha_nao_conta_na_tarde(self):
        veiculos = self.frota_de(4, turnos="manhã")
        conta = frota_mod.cabe_a_demanda(
            veiculos, {"manha": 10, "tarde": 10}, {"manha": 0, "tarde": 0})
        self.assertEqual(conta["manha"]["veiculos_no_turno"], 4)
        self.assertEqual(conta["tarde"]["veiculos_no_turno"], 0)


if __name__ == "__main__":
    unittest.main()
