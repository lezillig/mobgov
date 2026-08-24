# -*- coding: utf-8 -*-
"""
Testes do diagnóstico de formato da demanda (Sprint 16).

O que está protegido aqui: rodar uma demanda multidestino no motor de coleta
produz um número de veículos alto e com toda a aparência de rigor. O primeiro
arquivo real levava 207 alunos a 83 escolas no mesmo minuto — uma viagem por
escola seriam 83 viagens simultâneas, contra as 46 equipes que rodam de fato.
Errar isso em silêncio é pior do que não responder.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor import forma  # noqa: E402


def aluno(escola, turno="manha", hora="07:00"):
    return {"escola": escola, "turno": turno, "hora": hora}


class TestDiagnostico(unittest.TestCase):
    def test_muitos_alunos_em_poucas_escolas_e_coleta(self):
        alunos = [aluno("EMEF Centro") for _ in range(40)] + \
                 [aluno("EMEF Rural") for _ in range(30)]
        d = forma.diagnosticar(alunos)
        self.assertEqual(d["motor"], "coleta")
        self.assertEqual(d["bloco_que_manda"]["destinos"], 2)
        self.assertEqual(d["bloco_que_manda"]["alunos_por_destino"], 35.0)

    def test_poucos_alunos_em_muitas_escolas_e_porta_a_porta(self):
        """O caso do arquivo real, em miniatura."""
        alunos = [aluno(f"EE {i}") for i in range(40)]
        d = forma.diagnosticar(alunos)
        self.assertEqual(d["motor"], "porta_a_porta")
        self.assertEqual(d["bloco_que_manda"]["alunos_por_destino"], 1.0)
        self.assertIn("porta a porta", d["por_que"])

    def test_o_bloco_que_manda_e_o_mais_cheio(self):
        alunos = ([aluno("EMEF A", "manha") for _ in range(30)]
                  + [aluno(f"EE {i}", "tarde") for i in range(5)])
        d = forma.diagnosticar(alunos)
        self.assertEqual(d["bloco_que_manda"]["horario"], "manha")
        self.assertEqual(d["motor"], "coleta")
        self.assertEqual(len(d["blocos"]), 2)

    def test_o_horario_separa_o_que_o_turno_junta(self):
        """Alunos do mesmo turno em horários diferentes não disputam veículo.

        Com a chave de turno, 30 alunos e 10 escolas parecem concentrados;
        com a hora de entrada, vê-se que às 07:00 são 5 alunos em 5 escolas.
        """
        alunos = ([aluno(f"EE {i}", hora="07:00") for i in range(5)]
                  + [aluno("EMEF Central", hora="08:00") for _ in range(25)])
        por_turno = forma.diagnosticar(alunos)
        por_hora = forma.diagnosticar(alunos, chave_horario=lambda a: a["hora"])
        self.assertEqual(por_turno["bloco_que_manda"]["destinos"], 6)
        self.assertEqual(por_hora["bloco_que_manda"]["horario"], "08:00")
        self.assertEqual(len(por_hora["blocos"]), 2)

    def test_demanda_vazia_nao_quebra(self):
        d = forma.diagnosticar([])
        self.assertEqual(d["motor"], "indefinido")
        self.assertEqual(d["blocos"], [])

    def test_escola_com_grafias_diferentes_e_a_mesma_escola(self):
        """128 grafias para 117 escolas: sem normalizar, o diagnóstico erra."""
        alunos = [aluno(" emef centro "), aluno("EMEF CENTRO"),
                  aluno("EMEF Centro")]
        d = forma.diagnosticar(alunos)
        self.assertEqual(d["bloco_que_manda"]["destinos"], 1)


class TestAviso(unittest.TestCase):
    def test_avisa_quando_o_motor_usado_nao_e_o_indicado(self):
        d = forma.diagnosticar([aluno(f"EE {i}") for i in range(40)])
        texto = forma.aviso(d, "coleta")
        self.assertIn("teto", texto)
        self.assertIn("porta a porta", texto)

    def test_nao_avisa_quando_esta_certo(self):
        d = forma.diagnosticar([aluno("EMEF A") for _ in range(40)])
        self.assertEqual(forma.aviso(d, "coleta"), "")

    def test_nao_avisa_sem_demanda(self):
        self.assertEqual(forma.aviso(forma.diagnosticar([]), "coleta"), "")


if __name__ == "__main__":
    unittest.main()
