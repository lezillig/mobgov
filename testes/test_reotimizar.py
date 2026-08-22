# -*- coding: utf-8 -*-
"""Testes da reotimização do dia (Sprint 4).

Rodam sem OR-Tools: reotimizar uma rota isolada é heurística pura — e precisa
responder em milissegundos, porque o despachante está no telefone.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import tempos  # noqa: E402
from dados.demanda_pcd import PedidoPCD  # noqa: E402
from dados.municipio_modelo import TipoVeiculo  # noqa: E402
from motor import reotimizar as reo  # noqa: E402

TIPOS = {
    "ONIBUS31": TipoVeiculo("ONIBUS31", "Ônibus 31", 31, 0, 3.10, 14500.0, 3.2),
    "MICRO20": TipoVeiculo("MICRO20", "Micro 20", 20, 0, 2.40, 11800.0, 4.5),
    "VAN15A": TipoVeiculo("VAN15A", "Van acessível 15", 15, 2, 1.95, 10200.0, 6.0),
}
ESCOLA = (-21.150, -47.800)


def parada(pid, dlat, dlon, alunos=6):
    return {"id": pid, "lat": ESCOLA[0] + dlat, "lon": ESCOLA[1] + dlon,
            "alunos": alunos, "tempo_parada": 2}


PARADAS = [parada("P01", 0.010, 0.000), parada("P02", 0.020, 0.005),
           parada("P03", 0.030, 0.010), parada("P04", 0.040, 0.000),
           parada("P05", 0.050, -0.010)]
VIAGEM = {"id": "E1-manha-01", "tipo": "ONIBUS31", "cadeirantes": 0}


class TestFaltaEscolar(unittest.TestCase):
    def test_sem_faltas_nao_muda_nada(self):
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, {}, ESCOLA, TIPOS)
        self.assertEqual(r["antes"]["paradas"], r["depois"]["paradas"])
        self.assertEqual(r["economia"]["km"], 0)
        self.assertIn("Nenhuma mudança", r["diff"][0])

    def test_ponto_esvaziado_sai_da_rota(self):
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, {"P03": 6}, ESCOLA, TIPOS)
        self.assertNotIn("P03", r["depois"]["paradas"])
        self.assertEqual(len(r["depois"]["paradas"]), len(PARADAS) - 1)
        self.assertGreater(r["economia"]["km"], 0)

    def test_falta_parcial_mantem_a_parada(self):
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, {"P03": 2}, ESCOLA, TIPOS)
        self.assertIn("P03", r["depois"]["paradas"])
        self.assertEqual(r["depois"]["alunos"], r["antes"]["alunos"] - 2)

    def test_nunca_piora_o_percurso(self):
        """Reotimizar não pode devolver rota pior que a original."""
        for faltas in ({"P01": 6}, {"P05": 6}, {"P02": 6, "P04": 6}):
            r = reo.reotimizar_por_falta(VIAGEM, PARADAS, faltas, ESCOLA, TIPOS)
            self.assertLessEqual(r["depois"]["km"], r["antes"]["km"] + 1e-9,
                                 f"piorou com {faltas}")

    def test_sugere_veiculo_menor_quando_sobra_lugar(self):
        faltas = {"P01": 6, "P02": 6, "P03": 6}
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, faltas, ESCOLA, TIPOS)
        self.assertEqual(r["tipo_sugerido"], "VAN15A")
        self.assertTrue(any("cabe hoje" in d for d in r["diff"]))

    def test_responde_em_menos_de_um_segundo(self):
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, {"P02": 6}, ESCOLA, TIPOS)
        self.assertLess(r["segundos"], 1.0)

    def test_todas_as_paradas_faltando(self):
        faltas = {p["id"]: p["alunos"] for p in PARADAS}
        r = reo.reotimizar_por_falta(VIAGEM, PARADAS, faltas, ESCOLA, TIPOS)
        self.assertEqual(r["depois"]["paradas"], [])
        self.assertEqual(r["depois"]["alunos"], 0)


class TestDuasOpt(unittest.TestCase):
    def test_desfaz_cruzamento(self):
        coords = [ESCOLA, (-21.150, -47.790), (-21.150, -47.780),
                  (-21.150, -47.770)]
        dist, _ = tempos.ProvedorHaversine().matriz(coords)
        ordem_ruim = [3, 1, 2]
        melhor = reo.duas_opt(ordem_ruim, dist)

        def custo(seq):
            caminho = [0] + list(seq) + [0]
            return sum(dist[a][b] for a, b in zip(caminho, caminho[1:]))
        self.assertLess(custo(melhor), custo(ordem_ruim))

    def test_nao_perde_nem_duplica_parada(self):
        coords = [ESCOLA] + [(-21.15 + 0.01 * i, -47.80 + 0.005 * i)
                             for i in range(1, 7)]
        dist, _ = tempos.ProvedorHaversine().matriz(coords)
        ordem = [4, 2, 6, 1, 5, 3]
        melhor = reo.duas_opt(ordem, dist)
        self.assertEqual(sorted(melhor), sorted(ordem))


def pedido(uid, minuto_chegada, cadeirante=False, acompanhante=False):
    return PedidoPCD(id=uid, origem=(-21.16, -47.81), destino_id="D1",
                     destino=(-21.152, -47.805),
                     janela_chegada=(minuto_chegada - 20, minuto_chegada),
                     cadeirante=cadeirante, acompanhante=acompanhante,
                     distrito="Sede Urbana")


class TestPortaAPortaReotimizacao(unittest.TestCase):
    def setUp(self):
        # 3 usuários: coords = garagem + (origem, destino) de cada um
        self.pedidos = {
            "U1": pedido("U1", 8 * 60),
            "U2": pedido("U2", 8 * 60 + 30),
            "U3": pedido("U3", 9 * 60, cadeirante=True),
        }
        self.coords = [(-21.155, -47.795)]
        self.indices = {}
        for i, (uid, p) in enumerate(self.pedidos.items()):
            self.indices[uid] = {"no_origem": 1 + 2 * i, "no_destino": 2 + 2 * i,
                                 "servico": 2, "direto": 8}
            self.coords += [p.origem, p.destino]
        self.eventos = []
        for uid in ("U1", "U2"):
            ix = self.indices[uid]
            self.eventos.append({"tipo": "embarque", "usuario": uid,
                                 "no": ix["no_origem"], "servico": 2,
                                 "direto": 8, "minuto": 7 * 60 + 20})
        for uid in ("U1", "U2"):
            ix = self.indices[uid]
            self.eventos.append({"tipo": "desembarque", "usuario": uid,
                                 "no": ix["no_destino"], "servico": 2,
                                 "direto": 8})

    def test_cancelamento_remove_os_dois_eventos(self):
        r = reo.cancelar_e_reinserir(
            self.eventos, self.coords, "U1", [], self.pedidos, 8, 2)
        usuarios = {e["usuario"] for e in r["agenda"]}
        self.assertNotIn("U1", usuarios)
        self.assertIn("U2", usuarios)

    def test_cancelar_quem_nao_esta_na_rota_falha(self):
        with self.assertRaises(ValueError):
            reo.cancelar_e_reinserir(self.eventos, self.coords, "U3", [],
                                     self.pedidos, 8, 2)

    def test_reinsercao_aproveita_a_vaga(self):
        candidato = dict({"usuario": "U3"}, **self.indices["U3"])
        r = reo.cancelar_e_reinserir(self.eventos, self.coords, "U1",
                                     [candidato], self.pedidos, 8, 2)
        self.assertEqual(r["encaixado"], "U3")
        self.assertIn("U3", {e["usuario"] for e in r["agenda"]})

    def test_cadeirante_nao_entra_em_veiculo_sem_posicao(self):
        candidato = dict({"usuario": "U3"}, **self.indices["U3"])
        r = reo.cancelar_e_reinserir(self.eventos, self.coords, "U1",
                                     [candidato], self.pedidos, 8, 0)
        self.assertIsNone(r["encaixado"])

    def test_insercao_respeita_a_janela_de_chegada(self):
        """Quem só pode chegar às 8h não entra numa rota que termina às 9h."""
        apertado = pedido("U4", 6 * 60 + 30)
        self.pedidos["U4"] = apertado
        self.indices["U4"] = {"no_origem": 7, "no_destino": 8,
                              "servico": 2, "direto": 8}
        self.coords += [apertado.origem, apertado.destino]
        candidato = dict({"usuario": "U4"}, **self.indices["U4"])
        r = reo.cancelar_e_reinserir(self.eventos, self.coords, "U1",
                                     [candidato], self.pedidos, 8, 2)
        self.assertIsNone(r["encaixado"])

    def test_escolhe_a_rota_mais_barata(self):
        rota_perto = {"id": "PP01", "eventos": self.eventos, "capacidade": 8,
                      "posicoes_cadeirante": 2}
        rota_longe = {"id": "PP02", "eventos": [
            dict(e, no=e["no"]) for e in self.eventos], "capacidade": 8,
            "posicoes_cadeirante": 2}
        candidato = dict({"usuario": "U3"}, **self.indices["U3"])
        r = reo.inserir_na_melhor_rota([rota_perto, rota_longe], self.coords,
                                       candidato, self.pedidos)
        self.assertTrue(r["aceito"])
        self.assertIn(r["rota"], ("PP01", "PP02"))
        self.assertLess(r["segundos"], 1.0)

    def test_limite_de_km_recusa_encaixe_caro(self):
        rota = {"id": "PP01", "eventos": self.eventos, "capacidade": 8,
                "posicoes_cadeirante": 2}
        candidato = dict({"usuario": "U3"}, **self.indices["U3"])
        r = reo.inserir_na_melhor_rota([rota], self.coords, candidato,
                                       self.pedidos, limite_km_extra=0.0)
        self.assertFalse(r["aceito"])
        self.assertIn("acima do limite", r["diff"][0])


if __name__ == "__main__":
    unittest.main()
