# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 13 · agent-saude
Demanda sintética do transporte sanitário — sem nenhum dado clínico.

Espelha `dados/demanda_pcd.py`: mesma semente, mesmo compromisso. O que sai
daqui é o que roteiriza — casa, unidade, horário, cadeira, maca,
acompanhante, jejum. Doença, CID e laudo não existem neste módulo e não devem
passar a existir: o motorista precisa saber que o paciente vai de maca, não
por quê.

As proporções são as de uma rede municipal de porte médio e estão declaradas
aqui porque mudam de município para município — quem apresentar a
demonstração precisa poder dizer de onde saíram.
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.municipio_modelo import TipoVeiculo  # noqa: E402
from saude.tratamento import Tratamento  # noqa: E402

SEMENTE = 42

# Unidades de saúde do Município Modelo. A hemodiálise é sempre a mais longe
# — clínica de nefrologia costuma ser uma só, e é ela que puxa o km do mês.
UNIDADES = [
    {"id": "U1", "nome": "Clínica de Hemodiálise", "lat": -21.128, "lon": -47.772,
     "tipos": ["hemodialise"]},
    {"id": "U2", "nome": "Hospital Municipal", "lat": -21.146, "lon": -47.792,
     "tipos": ["quimioterapia", "consulta", "exame"]},
    {"id": "U3", "nome": "Centro de Especialidades", "lat": -21.158, "lon": -47.806,
     "tipos": ["fisioterapia", "consulta", "exame"]},
    {"id": "U4", "nome": "UBS Distrito Norte", "lat": -21.098, "lon": -47.778,
     "tipos": ["consulta"]},
]

GARAGEM = (-21.155, -47.795)

# Frota do transporte sanitário: van adaptada, carro pequeno para quem anda
# sozinho e ambulância de transporte para quem vai de maca (remoção simples,
# sem suporte avançado — que é outro serviço e outro contrato).
TIPOS_SAUDE = [
    TipoVeiculo("CARRO4", "Carro de apoio 4 lugares", 4, 0, 0.95, 4200.0, 11.0),
    TipoVeiculo("VANPCD8", "Van adaptada 8 lugares", 8, 2, 1.70, 9200.0, 8.0),
    TipoVeiculo("VAN15A", "Van acessível 15 lugares", 15, 2, 1.95, 10200.0, 6.0),
    TipoVeiculo("AMBTRANS", "Ambulância de transporte (maca)", 4, 1, 2.30,
                12800.0, 6.5),
]

DISTRITOS = [
    ("Sede Urbana", -21.152, -47.802, 0.030, 0.55),
    ("Distrito Norte", -21.098, -47.775, 0.022, 0.20),
    ("Vila Rural Sul", -21.208, -47.830, 0.040, 0.15),
    ("Zona Rural Leste", -21.160, -47.735, 0.055, 0.10),
]

# Quantos pacientes de cada tratamento, numa rede de ~50 mil habitantes.
# Hemodiálise é o menor número e a maior operação: 3 sessões por semana, sem
# falta possível.
QUANTIDADES = {
    "hemodialise": 34,
    "quimioterapia": 18,
    "fisioterapia": 46,
    "consulta": 62,
    "exame": 25,
}

# Turnos de hemodiálise: as clínicas trabalham em três, e a operação de
# transporte é desenhada em cima deles.
TURNOS_HEMODIALISE = [6 * 60, 11 * 60, 16 * 60]
HORARIOS_COMUNS = [7 * 60, 8 * 60, 9 * 60, 10 * 60, 13 * 60, 14 * 60]

PROPORCAO_CADEIRANTE = 0.22
PROPORCAO_MACA = 0.04
PROPORCAO_ACOMPANHANTE = 0.38    # idoso e menor têm direito por norma
PROPORCAO_JEJUM_EM_EXAME = 0.6

OBSERVACOES = ["usa oxigênio portátil", "não sobe escada",
               "precisa de apoio para caminhar", ""]


def _sorteia_casa(rng) -> tuple:
    nome, lat, lon, raio, _ = rng.choices(
        DISTRITOS, weights=[d[4] for d in DISTRITOS])[0]
    return (round(rng.gauss(lat, raio / 3), 6),
            round(rng.gauss(lon, raio / 3), 6)), nome


def _dias(tipo: str, rng) -> tuple:
    """Segunda a sexta; hemodiálise em dias alternados, como a clínica faz."""
    if tipo == "hemodialise":
        return rng.choice([(0, 2, 4), (1, 3, 5)])[:3]
    if tipo == "fisioterapia":
        return tuple(sorted(rng.sample([0, 1, 2, 3, 4], 2)))
    if tipo == "quimioterapia":
        return (rng.choice([0, 1, 2, 3, 4]),)
    return (rng.choice([0, 1, 2, 3, 4]),)


def gerar_tratamentos(semente: int = SEMENTE) -> list:
    """Os tratamentos ativos do município — a agenda que se repete."""
    rng = random.Random(semente)
    unidades_por_tipo = {}
    for u in UNIDADES:
        for tipo in u["tipos"]:
            unidades_por_tipo.setdefault(tipo, []).append(u["id"])

    tratamentos, sequencia = [], 0
    for tipo, quantos in QUANTIDADES.items():
        for _ in range(quantos):
            sequencia += 1
            casa, distrito = _sorteia_casa(rng)
            maca = rng.random() < PROPORCAO_MACA
            hora = (rng.choice(TURNOS_HEMODIALISE) if tipo == "hemodialise"
                    else rng.choice(HORARIOS_COMUNS))
            tratamentos.append(Tratamento(
                id=f"T{sequencia:04d}",
                paciente_id=f"PA{sequencia:04d}",
                unidade_id=rng.choice(unidades_por_tipo[tipo]),
                tipo=tipo, origem=casa,
                dias_da_semana=_dias(tipo, rng),
                hora_chegada_min=hora,
                # quem vai de maca não "também usa cadeira": é outra coisa
                cadeirante=(not maca) and rng.random() < PROPORCAO_CADEIRANTE,
                maca=maca,
                acompanhante=rng.random() < PROPORCAO_ACOMPANHANTE,
                jejum=(tipo == "exame" and rng.random() < PROPORCAO_JEJUM_EM_EXAME),
                distrito=distrito,
                observacao_operacional=rng.choice(OBSERVACOES)))
    return tratamentos


def unidades_por_id() -> dict:
    return {u["id"]: (u["lat"], u["lon"]) for u in UNIDADES}


def nomes_das_unidades() -> dict:
    return {u["id"]: u["nome"] for u in UNIDADES}


if __name__ == "__main__":
    tratamentos = gerar_tratamentos()
    print(f"Tratamentos ativos: {len(tratamentos)}")
    for tipo in QUANTIDADES:
        do_tipo = [t for t in tratamentos if t.tipo == tipo]
        vitais = sum(1 for t in do_tipo if t.prioridade == "vital")
        print(f"  {tipo:16s} {len(do_tipo):3d} pacientes "
              f"({vitais} sem falta possível)")
    print(f"  de maca: {sum(1 for t in tratamentos if t.maca)} | "
          f"cadeirantes: {sum(1 for t in tratamentos if t.cadeirante)} | "
          f"com acompanhante: "
          f"{sum(1 for t in tratamentos if t.acompanhante)}")
