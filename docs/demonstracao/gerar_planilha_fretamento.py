# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 9 · agent-qa-demo
Planilha de DEMONSTRAÇÃO de um cliente de fretamento.

O arquivo que uma empresa manda para cotar fretamento não é a planilha da
secretaria: vem do RH, tem matrícula e centro de custo, o destino é planta e o
turno é T1/T2/T3. A bagunça é outra, e igualmente real — turno escrito de seis
jeitos, endereço sem número, colaborador que mudou de planta e ficou nas duas
listas, e a coluna de PCD preenchida com "-".

Gera CSV (é como o RH exporta) com a lista de colaboradores e um bloco final
com a frota do contrato vigente — o "antes" da comparação.

Uso:
    python docs/demonstracao/gerar_planilha_fretamento.py
"""
from __future__ import annotations

import csv
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from dados.perfis import PERFIL_FRETAMENTO  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(DIR, "planilha-fretamento-demo.csv")
SAIDA_FROTA = os.path.join(DIR, "planilha-fretamento-frota.csv")
COLABORADORES = 420
rng = random.Random(2026)

CABECALHO = ["Matrícula", "Colaborador", "Endereço", "Nº", "Bairro",
             "Planta", "Turno de trabalho", "Mobilidade reduzida",
             "Latitude", "Longitude", "Centro de custo"]

NOMES = ["Adriana", "Bruno", "Cláudia", "Douglas", "Edna", "Fernando",
         "Gisele", "Hélio", "Iara", "Jonas", "Kátia", "Leandro", "Márcia",
         "Nilton", "Odete", "Paulo", "Renata", "Sérgio", "Tânia", "Vagner"]
SOBRENOMES = ["Almeida", "Barbosa", "Cardoso", "Duarte", "Esteves", "Farias",
              "Gonçalves", "Henriques", "Lima", "Moreira", "Nunes", "Pires",
              "Queiroz", "Ramos", "Santos", "Teixeira"]
RUAS = ["Rua das Palmeiras", "Av. Industrial", "Rua Dom Pedro",
        "Estrada do Contorno", "Rua 7 de Setembro", "Av. dos Trabalhadores",
        "Rua Projetada B", "Travessa da Fábrica", "Rodovia SP-330 km 12"]
BAIRROS = [("Jardim Operário", -21.170, -47.815, 0.020),
           ("Vila Industrial", -21.150, -47.790, 0.016),
           ("Centro", -21.158, -47.803, 0.012),
           ("Distrito de Bonfim", -21.205, -47.860, 0.030),
           ("Zona Rural Norte", -21.100, -47.760, 0.045)]

# O mesmo turno escrito como cada área da empresa escreve.
TURNOS_ESCRITOS = {
    "t1": ["T1", "1º turno", "1 TURNO", "turno 1", "A"],
    "t2": ["T2", "2º turno", "2 TURNO", "turno 2", "B"],
    "t3": ["T3", "3º turno", "3 TURNO", "turno 3", "C"],
    "adm": ["ADM", "Administrativo", "COMERCIAL", "Escritório", "Geral"],
}
# Proporção realista de uma fábrica com três turnos + administrativo.
PESO_TURNO = [("t1", 34), ("t2", 28), ("t3", 16), ("adm", 22)]
PCD = ["", "", "", "", "-", "não", "NÃO", "N", "sim", "?"]
PESOS_PCD = [40, 24, 14, 8, 5, 3, 2, 2, 1, 1]
CENTROS = ["CC-1010 Produção", "CC-2040 Logística", "CC-3070 Qualidade",
           "CC-4090 Administrativo", "CC-5020 Manutenção"]


def _linhas() -> list:
    plantas = [d.nome for d in PERFIL_FRETAMENTO.destinos]
    turnos = [t for t, _ in PESO_TURNO]
    pesos = [p for _, p in PESO_TURNO]
    linhas = []
    for i in range(COLABORADORES):
        bairro, clat, clon, raio = BAIRROS[i % len(BAIRROS)]
        nome = f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}"
        if i % 19 == 0:
            nome = nome.upper()

        turno = rng.choices(turnos, weights=pesos)[0]
        # o administrativo trabalha no escritório; produção, nas plantas
        planta = (plantas[2] if turno == "adm"
                  else plantas[i % 2])

        tem_coordenada = rng.random() < 0.82
        angulo = rng.uniform(0, 2 * math.pi)
        distancia = raio * math.sqrt(rng.uniform(0.05, 1.0))
        lat = round(clat + distancia * math.cos(angulo), 6) if tem_coordenada else ""
        lon = round(clon + distancia * math.sin(angulo), 6) if tem_coordenada else ""
        if tem_coordenada and i % 73 == 0:          # colunas trocadas
            lat, lon = lon, lat

        linhas.append([
            f"{50000 + i}", nome, rng.choice(RUAS),
            str(rng.randint(1, 1200)) if tem_coordenada else "s/n", bairro,
            planta, rng.choice(TURNOS_ESCRITOS[turno]),
            rng.choices(PCD, weights=PESOS_PCD)[0], lat, lon,
            rng.choice(CENTROS),
        ])
        if i and i % 97 == 0:                        # mudou de planta e ficou
            repetido = list(linhas[-1])              # nas duas listas
            repetido[5] = plantas[(i + 1) % 2]
            linhas.append(repetido)
    return linhas


def gerar(saida: str = SAIDA, saida_frota: str = SAIDA_FROTA) -> tuple:
    linhas = _linhas()
    with open(saida, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["RELAÇÃO DE COLABORADORES — FRETAMENTO 2026"])
        escritor.writerow(["Empresa Modelo S.A. · exportado do RH"])
        escritor.writerow([])
        escritor.writerow(CABECALHO)
        escritor.writerows(linhas)

    # o contrato vigente, que é o "antes" da comparação
    with open(saida_frota, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CONTRATO DE FRETAMENTO VIGENTE"])
        escritor.writerow([])
        escritor.writerow(["Tipo de veículo", "Lugares", "Quantidade"])
        for tipo, quantidade in (("RODO46", 9), ("EXEC28", 6), ("VAN16", 4),
                                 ("VANPCD", 2)):
            veiculo = next(t for t in PERFIL_FRETAMENTO.tipos_veiculo
                           if t.id == tipo)
            escritor.writerow([veiculo.nome, veiculo.capacidade, quantidade])
        escritor.writerow([])
        escritor.writerow(["Quilometragem contratada: 1.980 km/dia"])
    return saida, saida_frota


if __name__ == "__main__":
    a, b = gerar()
    print(f"Colaboradores: {a}")
    print(f"Contrato vigente: {b}")
