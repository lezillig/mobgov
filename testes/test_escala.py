# -*- coding: utf-8 -*-
"""Testes da escala multiviagem (Sprint 3).

Cobrem a fase 2 do motor — o encaixe das viagens em veículos físicos. Rodam
sem OR-Tools: a heurística é código puro, de propósito.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.municipio_modelo import TipoVeiculo, Turno  # noqa: E402
from motor.escala import montar_jornadas, compor_frota  # noqa: E402

TURNO = Turno("manha", "Manhã", (6 * 60 + 40, 7 * 60), 100)

TIPOS = {
    "ONIBUS31": TipoVeiculo("ONIBUS31", "Ônibus 31", 31, 0, 3.10, 14500.0, 3.2),
    "MICRO20": TipoVeiculo("MICRO20", "Micro 20", 20, 0, 2.40, 11800.0, 4.5),
    "VAN15A": TipoVeiculo("VAN15A", "Van acessível 15", 15, 2, 1.95, 10200.0, 6.0),
}


def viagem(id_, alunos, minutos, km=10.0, cadeirantes=0, escola="E1"):
    return {"id": id_, "escola_id": escola, "alunos": alunos,
            "cadeirantes": cadeirantes, "km_viagem": km, "min_viagem": minutos}


class TestMontarJornadas(unittest.TestCase):
    def test_toda_viagem_entra_em_exatamente_um_veiculo(self):
        viagens = [viagem(f"T{i}", 25, 25) for i in range(9)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS)
        alocadas = [v for veic in veiculos for v in veic["viagens"]]
        self.assertEqual(sorted(alocadas), sorted(v["id"] for v in viagens))
        self.assertEqual(len(alocadas), len(set(alocadas)))

    def test_jornada_nunca_estoura_o_limite(self):
        viagens = [viagem(f"T{i}", 20, 40) for i in range(12)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS, jornada_max=100)
        for v in veiculos:
            self.assertLessEqual(v["min_turno"], 100)
            self.assertGreaterEqual(v["folga_jornada_min"], 0)

    def test_encadeia_varias_viagens_por_veiculo(self):
        """O ponto da Sprint 3: 3 viagens de 30 min cabem em 100 min."""
        viagens = [viagem(f"T{i}", 30, 30) for i in range(3)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS, jornada_max=100)
        self.assertEqual(len(veiculos), 1)
        self.assertEqual(len(veiculos[0]["viagens"]), 3)

    def test_viagem_longa_demais_abre_veiculo_proprio(self):
        viagens = [viagem("A", 30, 60), viagem("B", 30, 60)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS, jornada_max=100)
        self.assertEqual(len(veiculos), 2)

    def test_cadeirante_so_entra_em_veiculo_acessivel(self):
        viagens = [viagem("A", 12, 30, cadeirantes=1),
                   viagem("B", 28, 30),
                   viagem("C", 10, 25, cadeirantes=2)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS)
        por_id = {v["id"]: v for v in veiculos}
        for vg in viagens:
            if vg["cadeirantes"]:
                tipo = TIPOS[por_id[vg["veiculo"]]["tipo"]]
                self.assertGreaterEqual(tipo.posicoes_cadeirante, vg["cadeirantes"])

    def test_capacidade_do_veiculo_cobre_cada_viagem(self):
        viagens = [viagem("A", 31, 20), viagem("B", 14, 20), viagem("C", 19, 20)]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS)
        por_id = {v["id"]: v for v in veiculos}
        for vg in viagens:
            capacidade = TIPOS[por_id[vg["veiculo"]]["tipo"]].capacidade
            self.assertGreaterEqual(capacidade, vg["alunos"])
            self.assertLessEqual(vg["ocupacao_pct"], 100)

    def test_escolhe_o_tipo_mais_barato_que_atende(self):
        veiculos = montar_jornadas([viagem("A", 8, 20)], TURNO, TIPOS)
        self.assertEqual(veiculos[0]["tipo"], "VAN15A")

    def test_km_do_veiculo_inclui_as_viagens_e_o_deslocamento(self):
        viagens = [viagem("A", 20, 30, km=12.0, escola="E1"),
                   viagem("B", 20, 30, km=8.0, escola="E2")]
        veiculos = montar_jornadas(viagens, TURNO, TIPOS, jornada_max=100)
        km_total = sum(v["km_turno"] for v in veiculos)
        self.assertGreaterEqual(km_total, 20.0)  # 12 + 8 + deslocamento entre escolas

    def test_e_deterministica(self):
        viagens = [viagem(f"T{i}", 10 + i, 20 + i) for i in range(15)]
        primeira = montar_jornadas(copy.deepcopy(viagens), TURNO, TIPOS)
        segunda = montar_jornadas(copy.deepcopy(viagens), TURNO, TIPOS)
        self.assertEqual([(v["id"], v["tipo"], v["viagens"]) for v in primeira],
                         [(v["id"], v["tipo"], v["viagens"]) for v in segunda])

    def test_sem_tipo_compativel_falha_explicitamente(self):
        with self.assertRaises(RuntimeError):
            montar_jornadas([viagem("A", 40, 20)], TURNO, TIPOS)


class TestComporFrota(unittest.TestCase):
    def test_toma_o_maior_de_cada_tipo_entre_os_turnos(self):
        composicao = compor_frota({
            "manha": [{"tipo": "ONIBUS31"}, {"tipo": "ONIBUS31"}, {"tipo": "VAN15A"}],
            "tarde": [{"tipo": "ONIBUS31"}, {"tipo": "VAN15A"}, {"tipo": "VAN15A"}],
        })
        self.assertEqual(composicao, {"ONIBUS31": 2, "VAN15A": 2})

    def test_nao_soma_os_turnos(self):
        """O mesmo veículo atende manhã e tarde — somar seria comprar em dobro."""
        composicao = compor_frota({
            "manha": [{"tipo": "ONIBUS31"} for _ in range(10)],
            "tarde": [{"tipo": "ONIBUS31"} for _ in range(8)],
        })
        self.assertEqual(composicao["ONIBUS31"], 10)


if __name__ == "__main__":
    unittest.main()
