# -*- coding: utf-8 -*-
"""
Testes da escala de motoristas (Lei 13.103 como restrição declarada).

O que protegem: que o sistema não produza uma escala que a empresa não pode
cumprir — e que o número de motoristas seja calculado, não chutado a partir
do número de veículos.

Sem OR-Tools: a fase 3 é heurística pura, como a fase 2.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.perfis import PERFIL_FRETAMENTO, RegrasDeJornada, carregar  # noqa: E402
from motor import jornada  # noqa: E402


def bloco(ident, inicio, fim, veiculo="V1", turno="t1", km=40.0):
    return {"id": ident, "veiculo": veiculo, "tipo": "RODO46", "turno": turno,
            "turno_nome": turno, "inicio": inicio, "fim": fim,
            "duracao": fim - inicio, "km": km, "viagens": []}


class TestConferir(unittest.TestCase):
    def setUp(self):
        self.regras = RegrasDeJornada()

    def test_escala_normal_nao_tem_problema(self):
        blocos = [bloco("A", 4 * 60, 7 * 60), bloco("B", 13 * 60, 16 * 60)]
        self.assertEqual(jornada.conferir(blocos, self.regras), [])

    def test_jornada_acima_do_limite_e_apontada(self):
        blocos = [bloco("A", 4 * 60, 10 * 60), bloco("B", 11 * 60, 17 * 60)]
        problemas = jornada.conferir(blocos, self.regras)
        self.assertTrue(any("Jornada de" in p for p in problemas))

    def test_direcao_continua_sem_parada_e_apontada(self):
        """6h ao volante sem os 30 min de parada."""
        problemas = jornada.conferir([bloco("A", 4 * 60, 10 * 60)], self.regras)
        self.assertTrue(any("direção sem a parada" in p for p in problemas))

    def test_parada_de_30_min_zera_o_relogio_do_volante(self):
        blocos = [bloco("A", 4 * 60, 9 * 60), bloco("B", 9 * 60 + 40, 13 * 60)]
        self.assertEqual(
            [p for p in jornada.conferir(blocos, self.regras)
             if "volante" in p or "direção" in p], [])

    def test_blocos_sobrepostos_sao_apontados(self):
        blocos = [bloco("A", 4 * 60, 8 * 60), bloco("B", 7 * 60, 9 * 60)]
        self.assertTrue(any("se sobrepõem" in p
                            for p in jornada.conferir(blocos, self.regras)))

    def test_tempo_de_troca_de_veiculo_e_respeitado(self):
        blocos = [bloco("A", 4 * 60, 7 * 60),
                  bloco("B", 7 * 60 + 5, 9 * 60, veiculo="V2")]
        self.assertTrue(any("trocar de veículo" in p
                            for p in jornada.conferir(blocos, self.regras)))

    def test_amplitude_excessiva_e_apontada(self):
        blocos = [bloco("A", 4 * 60, 7 * 60), bloco("B", 20 * 60, 22 * 60)]
        self.assertTrue(any("Amplitude" in p
                            for p in jornada.conferir(blocos, self.regras)))

    def test_dupla_pegada_pode_ser_proibida_pelo_acordo(self):
        blocos = [bloco("A", 4 * 60, 7 * 60), bloco("B", 13 * 60, 16 * 60)]
        sem_pegada = RegrasDeJornada(permite_dupla_pegada=False)
        self.assertTrue(any("dupla pegada" in p
                            for p in jornada.conferir(blocos, sem_pegada)))
        self.assertEqual(jornada.conferir(blocos, self.regras), [])


class TestEscalar(unittest.TestCase):
    def setUp(self):
        self.regras = RegrasDeJornada()

    def test_um_motorista_absorve_dois_blocos_que_cabem(self):
        escala = jornada.escalar([bloco("A", 4 * 60, 7 * 60),
                                  bloco("B", 13 * 60, 16 * 60)], self.regras)
        self.assertEqual(escala["resumo"]["motoristas"], 1)
        self.assertTrue(escala["motoristas"][0]["dupla_pegada"])

    def test_blocos_simultaneos_exigem_motoristas_diferentes(self):
        escala = jornada.escalar([bloco("A", 4 * 60, 7 * 60, veiculo="V1"),
                                  bloco("B", 4 * 60, 7 * 60, veiculo="V2")],
                                 self.regras)
        self.assertEqual(escala["resumo"]["motoristas"], 2)

    def test_interjornada_impede_fechar_a_noite_e_abrir_a_madrugada(self):
        """O que termina às 23h não volta às 4h30: faltam as 11 horas."""
        escala = jornada.escalar([bloco("noite", 20 * 60, 23 * 60, turno="t3"),
                                  bloco("madrugada", 4 * 60, 6 * 60, turno="t1")],
                                 self.regras)
        self.assertEqual(escala["resumo"]["motoristas"], 2)

    def test_nenhuma_escala_gerada_tem_problema(self):
        blocos = [bloco(f"B{i}", 4 * 60 + i * 30, 6 * 60 + i * 30,
                        veiculo=f"V{i}") for i in range(6)]
        blocos += [bloco(f"T{i}", 13 * 60 + i * 20, 15 * 60 + i * 20,
                         veiculo=f"V{i}", turno="t2") for i in range(6)]
        escala = jornada.escalar(blocos, self.regras)
        self.assertEqual(escala["resumo"]["escalas_com_problema"], 0)
        for motorista in escala["motoristas"]:
            self.assertEqual(motorista["problemas"], [])

    def test_todo_bloco_e_atribuido_a_alguem(self):
        blocos = [bloco(f"B{i}", 4 * 60, 7 * 60, veiculo=f"V{i}")
                  for i in range(5)]
        escala = jornada.escalar(blocos, self.regras)
        atribuidos = [b["id"] for m in escala["motoristas"] for b in m["blocos"]]
        self.assertEqual(sorted(atribuidos), sorted(b["id"] for b in blocos))

    def test_hora_extra_e_contada_e_declarada(self):
        blocos = [bloco("A", 4 * 60, 9 * 60), bloco("B", 10 * 60, 14 * 60)]
        escala = jornada.escalar(blocos, self.regras)
        self.assertGreater(escala["resumo"]["hora_extra_total_min"], 0)

    def test_escala_vazia_nao_quebra(self):
        escala = jornada.escalar([], self.regras)
        self.assertEqual(escala["resumo"]["motoristas"], 0)
        self.assertEqual(escala["resumo"]["ocupacao_da_jornada_pct"], 0.0)


class TestBlocosDaOperacao(unittest.TestCase):
    def test_coleta_termina_na_janela_do_turno(self):
        veiculos = {"t1": [{"id": "VT101", "tipo": "RODO46", "min_turno": 90,
                            "km_turno": 40.0, "viagens": ["A", "B"]}]}
        blocos = jornada.blocos_de_trabalho(veiculos,
                                            PERFIL_FRETAMENTO.turnos)
        coleta = next(b for b in blocos if b["sentido"] == "coleta")
        self.assertEqual(coleta["fim"], 6 * 60)             # 1º turno às 06h
        self.assertEqual(coleta["duracao"], 120)            # 90 + 30 antes

    def test_a_volta_do_turno_tambem_e_um_bloco(self):
        """Quem foi levado às 6h volta às 14h, e alguém dirige essa volta."""
        veiculos = {"t1": [{"id": "VT101", "tipo": "RODO46", "min_turno": 90,
                            "km_turno": 40.0, "viagens": ["A"]}]}
        blocos = jornada.blocos_de_trabalho(veiculos, PERFIL_FRETAMENTO.turnos)
        self.assertEqual(len(blocos), 2)
        volta = next(b for b in blocos if b["sentido"] == "dispersao")
        self.assertEqual(volta["inicio"], 14 * 60)          # 06h + 8h de turno
        self.assertEqual(volta["duracao"], 120)

    def test_volta_do_terceiro_turno_cai_na_madrugada_do_dia_seguinte(self):
        veiculos = {"t3": [{"id": "VT301", "tipo": "RODO46", "min_turno": 60,
                            "km_turno": 30.0, "viagens": []}]}
        blocos = jornada.blocos_de_trabalho(veiculos, PERFIL_FRETAMENTO.turnos)
        volta = next(b for b in blocos if b["sentido"] == "dispersao")
        self.assertEqual(volta["inicio"], 6 * 60)   # 22h + 8h, relógio cíclico

    def test_turno_sem_duracao_declarada_gera_so_a_coleta(self):
        """No escolar a volta não é modelada — e a conta não inventa uma."""
        from dados.perfis import PERFIL_ESCOLAR
        veiculos = {"manha": [{"id": "VM01", "tipo": "ONIBUS31",
                               "min_turno": 60, "km_turno": 20.0,
                               "viagens": []}]}
        blocos = jornada.blocos_de_trabalho(veiculos, PERFIL_ESCOLAR.turnos)
        self.assertEqual(len(blocos), 1)

    def test_quatro_turnos_geram_ida_e_volta_de_cada_um(self):
        veiculos = {t.id: [{"id": f"V{t.id}", "tipo": "RODO46",
                            "min_turno": 60, "km_turno": 20.0, "viagens": []}]
                    for t in PERFIL_FRETAMENTO.turnos}
        blocos = jornada.blocos_de_trabalho(veiculos, PERFIL_FRETAMENTO.turnos)
        self.assertEqual(len(blocos), 8)
        self.assertEqual(sum(1 for b in blocos if b["sentido"] == "dispersao"), 4)

    def test_operacao_de_tres_turnos_precisa_de_mais_motorista_que_veiculo(self):
        """A conta que o fretamento exige e o escolar esconde."""
        veiculos = {t.id: [{"id": "V01", "tipo": "RODO46", "min_turno": 180,
                            "km_turno": 90.0, "viagens": []}]
                    for t in PERFIL_FRETAMENTO.turnos}
        escala = jornada.escalar_operacao(veiculos, PERFIL_FRETAMENTO.turnos,
                                          PERFIL_FRETAMENTO.regras_jornada)
        # um único veículo cobre os quatro turnos; um motorista não cobre
        self.assertGreater(escala["resumo"]["motoristas"], 1)
        self.assertEqual(escala["resumo"]["escalas_com_problema"], 0)


class TestPerfis(unittest.TestCase):
    def test_perfil_de_fretamento_tem_turnos_e_custo_de_motorista(self):
        self.assertEqual(len(PERFIL_FRETAMENTO.turnos), 4)
        self.assertTrue(PERFIL_FRETAMENTO.separa_custo_do_motorista)
        self.assertEqual(PERFIL_FRETAMENTO.rotulo_passageiro, "colaborador")

    def test_perfil_escolar_mantem_o_custo_do_motorista_no_veiculo(self):
        escolar = carregar("escolar")
        self.assertFalse(escolar.separa_custo_do_motorista)
        self.assertEqual(len(escolar.turnos), 2)

    def test_perfil_pode_vir_de_json_com_os_turnos_do_cliente(self):
        import json
        import tempfile
        from dados.perfis import de_dicionario

        dados = {
            "base": "fretamento", "id": "cliente-x", "nome": "Cliente X",
            "turnos": [{"id": "a", "nome": "Turno A", "janela_chegada": [300, 310],
                        "jornada_max_min": 100},
                       {"id": "b", "nome": "Turno B", "janela_chegada": [900, 910],
                        "jornada_max_min": 100}],
            "regras_jornada": {"jornada_normal_min": 440,
                               "permite_dupla_pegada": False},
        }
        perfil = de_dicionario(dados)
        self.assertEqual([t.id for t in perfil.turnos], ["a", "b"])
        self.assertEqual(perfil.regras_jornada.jornada_normal_min, 440)
        self.assertFalse(perfil.regras_jornada.permite_dupla_pegada)
        # e o que não foi dito vem do perfil base
        self.assertEqual(perfil.custo_motorista_mes,
                         PERFIL_FRETAMENTO.custo_motorista_mes)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(dados, f)
            caminho = f.name
        try:
            self.assertEqual(carregar(caminho).id, "cliente-x")
        finally:
            os.remove(caminho)

    def test_perfil_desconhecido_explica(self):
        with self.assertRaises(ValueError) as ctx:
            carregar("nao-existe")
        self.assertIn("fretamento", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
