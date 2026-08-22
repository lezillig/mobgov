# -*- coding: utf-8 -*-
"""Testes do motor porta a porta (PDPTW, Sprint 4).

Precisam do OR-Tools; sem ele, são pulados — a suíte inteira continua rodando
com a biblioteca padrão.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.demanda_pcd import (  # noqa: E402
    PedidoPCD, gerar_pedidos, limite_tempo_bordo_min,
)

try:
    from motor import porta_a_porta as pp
    TEM_ORTOOLS = True
except ImportError:  # pragma: no cover
    TEM_ORTOOLS = False


class TestDemandaPCD(unittest.TestCase):
    def test_gerador_e_reprodutivel(self):
        a = [p.id for p in gerar_pedidos(20)]
        b = [p.id for p in gerar_pedidos(20)]
        self.assertEqual(a, b)

    def test_cadeirante_ocupa_posicao_e_nao_assento(self):
        p = PedidoPCD("U1", (0, 0), "D1", (1, 1), (480, 500), True, False, "x")
        self.assertEqual(p.posicoes_cadeira, 1)
        self.assertEqual(p.assentos, 0)

    def test_acompanhante_ocupa_assento(self):
        p = PedidoPCD("U2", (0, 0), "D1", (1, 1), (480, 500), False, True, "x")
        self.assertEqual(p.assentos, 2)
        p3 = PedidoPCD("U3", (0, 0), "D1", (1, 1), (480, 500), True, True, "x")
        self.assertEqual(p3.assentos, 1)
        self.assertEqual(p3.posicoes_cadeira, 1)

    def test_janela_de_embarque_de_vinte_minutos(self):
        for p in gerar_pedidos(10):
            self.assertEqual(p.janela_chegada[1] - p.janela_chegada[0], 20)

    def test_limite_de_tempo_a_bordo_cresce_com_a_viagem(self):
        self.assertLess(limite_tempo_bordo_min(10), limite_tempo_bordo_min(40))
        self.assertGreater(limite_tempo_bordo_min(10), 10)


@unittest.skipUnless(TEM_ORTOOLS, "OR-Tools não instalado")
class TestSolverPortaAPorta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pedidos = gerar_pedidos(10)
        cls.resultado = pp.resolver(cls.pedidos, tempo_limite_s=8)
        cls.por_id = {p.id: p for p in cls.pedidos}

    def test_todo_pedido_e_atendido_uma_vez(self):
        embarques = [e["usuario"] for r in self.resultado["rotas"]
                     for e in r["eventos"] if e["tipo"] == "embarque"]
        self.assertEqual(sorted(embarques), sorted(self.por_id))

    def test_embarque_e_desembarque_no_mesmo_veiculo_e_na_ordem_certa(self):
        for rota in self.resultado["rotas"]:
            vistos = {}
            for i, ev in enumerate(rota["eventos"]):
                if ev["tipo"] == "embarque":
                    vistos[ev["usuario"]] = i
                else:
                    self.assertIn(ev["usuario"], vistos,
                                  f"{ev['usuario']} desembarca sem ter embarcado "
                                  f"nesta rota")
                    self.assertLess(vistos[ev["usuario"]], i)

    def test_ocupacao_nunca_negativa_nem_acima_da_capacidade(self):
        for rota in self.resultado["rotas"]:
            for ev in rota["eventos"]:
                self.assertGreaterEqual(ev["ocupacao_apos"], 0)
                self.assertLessEqual(ev["ocupacao_apos"], rota["capacidade"])

    def test_relacao_n_para_n_acontece(self):
        """Alguma rota tem que intercalar embarque e desembarque — senão isto
        aqui é só um roteirizador de coleta com outro nome."""
        intercalou = False
        for rota in self.resultado["rotas"]:
            tipos = [e["tipo"] for e in rota["eventos"]]
            for i in range(len(tipos) - 2):
                if tipos[i] == "embarque" and "desembarque" in tipos[i + 1:i + 2]:
                    if "embarque" in tipos[i + 2:]:
                        intercalou = True
        self.assertTrue(intercalou or len(self.resultado["rotas"]) == 1)

    def test_janela_de_chegada_respeitada(self):
        for rota in self.resultado["rotas"]:
            for ev in rota["eventos"]:
                if ev["tipo"] == "desembarque":
                    ini, fim = self.por_id[ev["usuario"]].janela_chegada
                    self.assertLessEqual(ev["minuto"], fim, ev["usuario"])

    def test_tempo_a_bordo_dentro_do_limite(self):
        for b in self.resultado["tempo_bordo"]:
            self.assertLessEqual(b["min_a_bordo"], b["limite"], b["usuario"])
        self.assertEqual(self.resultado["indicadores"]["dentro_do_limite_pct"],
                         100.0)

    def test_cadeirante_sempre_em_veiculo_acessivel(self):
        for rota in self.resultado["rotas"]:
            if rota["cadeirantes"]:
                self.assertGreaterEqual(rota["posicoes_cadeirante"], 1)

    def test_indicadores_coerentes(self):
        ind = self.resultado["indicadores"]
        self.assertGreater(ind["usuarios_por_veiculo"], 0)
        self.assertGreater(ind["km_por_usuario"], 0)
        self.assertGreaterEqual(ind["tempo_bordo_max_min"],
                                ind["tempo_bordo_medio_min"])

    def test_contexto_de_reotimizacao_mapeia_todos_os_nos(self):
        ctx = pp.contexto_reotimizacao(self.pedidos)
        self.assertEqual(len(ctx["coords"]), 1 + 2 * len(self.pedidos))
        for p in self.pedidos:
            self.assertIn(p.id, ctx["indices"])
            self.assertGreater(ctx["indices"][p.id]["direto"], 0)

    def test_sem_pedidos_devolve_vazio(self):
        vazio = pp.resolver([])
        self.assertEqual(vazio["total_veiculos"], 0)


if __name__ == "__main__":
    unittest.main()
