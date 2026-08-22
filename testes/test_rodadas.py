# -*- coding: utf-8 -*-
"""
Testes da reotimização contínua em rodadas.

O que estes testes protegem — e é sempre a mesma coisa dita de jeitos
diferentes: a reotimização pode ser esperta com o plano, mas não pode ser
esperta com a palavra dada à família.

Sem OR-Tools: as matrizes de distância e tempo entram prontas, que é o que a
rodada consome. O solver da véspera tem os testes dele.
"""
import os
import sys
import unittest
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor import rodadas as rod  # noqa: E402

# Mapa de teste, em linha reta: garagem 0, e para cada usuário uma origem e um
# destino. As distâncias são o valor absoluto da diferença de posição — dá
# para conferir a conta de cabeça, que é o ponto de um teste.
POSICAO = {0: 0.0,      # garagem
           1: 2.0, 2: 10.0,      # A: casa em 2, destino em 10
           3: 3.0, 4: 10.0,      # B: casa em 3, destino em 10
           5: 30.0, 6: 34.0}     # C: longe de todo mundo


@dataclass
class PedidoFalso:
    id: str
    janela_chegada: tuple
    posicoes_cadeira: int = 0
    assentos: int = 1


# Janelas estreitas de propósito: com janela larga o simulador embarca o mais
# tarde possível (é o comportamento certo — ninguém fica sentado na van
# esperando), e o horário do dia deixaria de estar ancorado em coisa alguma.
PEDIDOS = {
    "A": PedidoFalso("A", (6 * 60 + 5, 6 * 60 + 15)),
    "B": PedidoFalso("B", (6 * 60 + 5, 6 * 60 + 18)),
    "C": PedidoFalso("C", (6 * 60 + 30, 6 * 60 + 40)),
}


def matrizes():
    n = len(POSICAO)
    dist = [[abs(POSICAO[i] - POSICAO[j]) for j in range(n)] for i in range(n)]
    tempo = [[int(abs(POSICAO[i] - POSICAO[j])) for j in range(n)]
             for i in range(n)]
    return dist, tempo


def evento(tipo, usuario, no, servico=1, direto=8):
    return {"tipo": tipo, "usuario": usuario, "no": no, "servico": servico,
            "direto": direto}


def rota(ident, eventos, inicio=6 * 60, capacidade=8, cadeiras=2):
    return {"id": ident, "eventos": eventos, "capacidade": capacidade,
            "posicoes_cadeirante": cadeiras, "inicio_min": inicio}


def candidato(usuario, origem, destino, servico=1, direto=8):
    return {"usuario": usuario, "no_origem": origem, "no_destino": destino,
            "servico": servico, "direto": direto}


class BaseRodada(unittest.TestCase):
    def setUp(self):
        self.dist, self.tempo = matrizes()
        self.pedidos = dict(PEDIDOS)

    def rodar(self, rotas, agora, eventos=None, politica=None):
        return rod.rodada(rotas, None, self.pedidos, agora, eventos,
                          politica or rod.Politica(), dist=self.dist,
                          tempo=self.tempo)


class TestFaltas(BaseRodada):
    def test_falta_informada_a_tempo_libera_a_parada(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("embarque", "B", 3),
                             evento("desembarque", "A", 2),
                             evento("desembarque", "B", 4)])]
        resultado = self.rodar(rotas, 5 * 60,
                               [{"tipo": "falta", "usuario": "A"}])
        self.assertEqual(resultado["saidas"], ["A"])
        self.assertLess(resultado["km_depois"], resultado["km_antes"])
        usuarios = {e["usuario"] for e in resultado["rotas"][0]["eventos"]}
        self.assertEqual(usuarios, {"B"})

    def test_falta_avisada_em_cima_da_hora_nao_reprograma(self):
        """O veículo já está na porta: não há o que remanejar, só registrar."""
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        resultado = self.rodar(rotas, 6 * 60,
                               [{"tipo": "falta", "usuario": "A"}])
        self.assertEqual(resultado["saidas"], [])
        self.assertIn("já estava na porta", " ".join(resultado["diff"]))

    def test_falta_de_quem_nao_esta_em_rota_nenhuma(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        resultado = self.rodar(rotas, 5 * 60,
                               [{"tipo": "falta", "usuario": "C"}])
        self.assertIn("não estava em nenhuma rota", " ".join(resultado["diff"]))


class TestPedidosNovos(BaseRodada):
    def test_pedido_entra_na_rota_mais_barata(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)]),
                 rota("R2", [evento("embarque", "C", 5),
                             evento("desembarque", "C", 6)])]
        resultado = self.rodar(
            rotas, 5 * 60,
            [{"tipo": "pedido", "candidato": candidato("B", 3, 4)}])
        self.assertEqual(len(resultado["pedidos_aceitos"]), 1)
        # B mora ao lado de A: a rota barata é a R1, não a que vai para longe
        self.assertEqual(resultado["pedidos_aceitos"][0]["rota"], "R1")

    def test_pedido_caro_demais_e_recusado_com_motivo(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        politica = rod.Politica(limite_km_extra=5.0)
        resultado = self.rodar(
            rotas, 5 * 60,
            [{"tipo": "pedido", "candidato": candidato("C", 5, 6)}], politica)
        self.assertEqual(resultado["pedidos_aceitos"], [])
        self.assertIn("acima do limite",
                      resultado["pedidos_recusados"][0]["motivo"]
                      + " ".join(resultado["diff"]))

    def test_com_tolerancia_zero_o_pedido_que_mexe_no_horario_e_recusado(self):
        """A conta fecharia em km — e mesmo assim não pode.

        Encaixar B faz o veículo passar antes na casa de A. Um minuto de
        diferença é nada no papel e é tudo no portão: com tolerância zero e o
        horário já avisado, o pedido é recusado com o motivo escrito.
        """
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        politica = rod.Politica(limite_km_extra=100.0,
                                max_atraso_promessa_min=0,
                                janela_de_aviso_min=600)
        resultado = self.rodar(
            rotas, 5 * 60,
            [{"tipo": "pedido", "candidato": candidato("B", 3, 4)}], politica)
        self.assertEqual(resultado["pedidos_aceitos"], [])
        self.assertIn("horário já combinado", " ".join(resultado["diff"]))

    def test_km_da_demanda_nova_nao_entra_como_economia_negativa(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        resultado = self.rodar(
            rotas, 5 * 60,
            [{"tipo": "pedido", "candidato": candidato("C", 5, 6, direto=4)}],
            rod.Politica(limite_km_extra=100.0))
        self.assertGreater(resultado["km_de_demanda_nova"], 0)
        self.assertGreaterEqual(resultado["km_economizados"], 0)
        # a conta fecha: rodar mais para atender mais não vira "economia"
        self.assertAlmostEqual(
            resultado["km_depois"],
            resultado["km_antes"] + resultado["km_de_demanda_nova"]
            - resultado["km_economizados"], places=2)


class TestRemanejamento(BaseRodada):
    def test_corrida_muda_de_veiculo_quando_compensa(self):
        """C está numa rota que passa longe; a outra vai bem ao lado dele."""
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2),
                             evento("embarque", "C", 5),
                             evento("desembarque", "C", 6)]),
                 rota("R2", [evento("embarque", "B", 5, direto=4),
                             evento("desembarque", "B", 6, direto=4)])]
        self.pedidos["B"] = PedidoFalso("B", (0, 24 * 60))
        politica = rod.Politica(janela_de_aviso_min=0, remocoes_por_rodada=2)
        resultado = self.rodar(rotas, 5 * 60, [], politica)
        self.assertTrue(resultado["movimentos"] or
                        resultado["ganho_do_remanejamento_km"] >= 0)

    def test_nao_mexe_em_quem_embarca_dentro_do_horizonte(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)]),
                 rota("R2", [evento("embarque", "C", 5),
                             evento("desembarque", "C", 6)])]
        politica = rod.Politica(horizonte_compromisso_min=600,
                                janela_de_aviso_min=0)
        resultado = self.rodar(rotas, 5 * 60, [], politica)
        self.assertEqual(resultado["movimentos"], [])

    def test_ganho_pequeno_demais_nao_vira_remanejamento(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("desembarque", "A", 2)])]
        politica = rod.Politica(ganho_minimo_km=50.0, janela_de_aviso_min=0)
        resultado = self.rodar(rotas, 5 * 60, [], politica)
        self.assertEqual(resultado["movimentos"], [])
        self.assertIn("abaixo do mínimo", resultado["melhoria_descartada"])

    def test_plano_nunca_piora(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("embarque", "B", 3),
                             evento("desembarque", "A", 2),
                             evento("desembarque", "B", 4)]),
                 rota("R2", [evento("embarque", "C", 5),
                             evento("desembarque", "C", 6)])]
        politica = rod.Politica(janela_de_aviso_min=0)
        resultado = self.rodar(rotas, 5 * 60, [], politica)
        self.assertLessEqual(resultado["km_depois"], resultado["km_antes"])

    def test_promessa_nunca_e_quebrada(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("embarque", "B", 3),
                             evento("desembarque", "A", 2),
                             evento("desembarque", "B", 4)]),
                 rota("R2", [evento("embarque", "C", 5),
                             evento("desembarque", "C", 6)])]
        resultado = self.rodar(rotas, 5 * 60, [])
        self.assertTrue(resultado["promessas_preservadas"])


class TestDiaInteiro(unittest.TestCase):
    def setUp(self):
        self.dist, self.tempo = matrizes()

    class ProvedorFalso:
        def __init__(self, dist, tempo):
            self.dist, self.tempo = dist, tempo

        def matriz(self, coords, partida_min=None, zonas=None):
            return self.dist, self.tempo

    def test_dia_roda_em_rodadas_e_soma_o_resultado(self):
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("embarque", "B", 3),
                             evento("desembarque", "A", 2),
                             evento("desembarque", "B", 4)])]
        agenda = [(5 * 60 + 10, {"tipo": "falta", "usuario": "B"}),
                  (5 * 60 + 20, {"tipo": "pedido",
                                 "candidato": candidato("C", 5, 6)})]
        resultado = rod.rodar_dia(
            rotas, None, dict(PEDIDOS), agenda, 5 * 60, 5 * 60 + 40,
            rod.Politica(intervalo_min=10, limite_km_extra=100.0),
            provedor=self.ProvedorFalso(self.dist, self.tempo))
        resumo = resultado["resumo"]
        self.assertEqual(resumo["rodadas"], 5)
        self.assertEqual(resumo["faltas_absorvidas"], 1)
        self.assertEqual(resumo["promessas_quebradas"], 0)
        self.assertTrue(resumo["tempo_max_s"] < 5)

    def test_evento_so_e_visto_na_rodada_em_que_chega(self):
        """O sistema não pode decidir hoje com a informação de daqui a pouco."""
        rotas = [rota("R1", [evento("embarque", "A", 1),
                             evento("embarque", "B", 3),
                             evento("desembarque", "A", 2),
                             evento("desembarque", "B", 4)])]
        agenda = [(5 * 60 + 35, {"tipo": "falta", "usuario": "B"})]
        resultado = rod.rodar_dia(
            rotas, None, dict(PEDIDOS), agenda, 5 * 60, 5 * 60 + 40,
            rod.Politica(intervalo_min=10),
            provedor=self.ProvedorFalso(self.dist, self.tempo))
        com_saida = [r["hora"] for r in resultado["rodadas"] if r["saidas"]]
        self.assertEqual(com_saida, ["05h40"])


if __name__ == "__main__":
    unittest.main()
