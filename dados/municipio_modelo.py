# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 1 · agent-dados
Esquema de dados + gerador do Município Modelo sintético.

Município fictício: "Ribeirão Modelo" (~30 mil hab), sede urbana + 4 distritos
rurais. 3.000 alunos transportados no turno da manhã, 3 escolas-polo.
Frota atual declarada pela prefeitura: 25 veículos (típico: sobredimensionada
e envelhecida).
"""
import math
import random
from dataclasses import dataclass, field

random.seed(42)  # reprodutível para a demo


# ---------------------------------------------------------------- esquema ---
@dataclass
class Escola:
    id: str
    nome: str
    lat: float
    lon: float
    janela_chegada: tuple  # (min_inicio, min_fim) minutos desde 00:00


@dataclass
class PontoEmbarque:
    id: str
    lat: float
    lon: float
    alunos: int              # alunos que embarcam neste ponto
    alunos_cadeirantes: int  # subset que precisa de posição de cadeira
    escola_id: str
    distrito: str


@dataclass
class TipoVeiculo:
    id: str
    nome: str
    capacidade: int
    posicoes_cadeirante: int
    custo_km: float          # R$/km (combustível+manutenção)
    custo_fixo_mes: float    # R$/mês (motorista+depreciação+seguro)
    consumo_km_l: float


@dataclass
class FrotaAtual:
    """O que a prefeitura declara ter/contratar hoje."""
    composicao: dict = field(default_factory=dict)  # tipo_id -> qtd
    km_dia_declarado: float = 0.0


# ------------------------------------------------------ município modelo ---
# Coordenadas fictícias em torno de um centro (-21.15, -47.80)
CENTRO = (-21.15, -47.80)

ESCOLAS = [
    Escola("E1", "EMEF Centro",            -21.150, -47.800, (6 * 60 + 40, 7 * 60)),
    Escola("E2", "EMEF Distrito Norte",    -21.095, -47.775, (6 * 60 + 40, 7 * 60)),
    Escola("E3", "EMEF Vila Rural Sul",    -21.210, -47.830, (6 * 60 + 40, 7 * 60)),
]

TIPOS_VEICULO = [
    TipoVeiculo("ONIBUS31", "Ônibus escolar 31 lugares", 31, 0, 3.10, 14500.0, 3.2),
    TipoVeiculo("MICRO20",  "Micro-ônibus 20 lugares",   20, 0, 2.40, 11800.0, 4.5),
    TipoVeiculo("VAN15A",   "Van acessível 15 lugares",  15, 2, 1.95, 10200.0, 6.0),
]

# Frota atual declarada (cenário típico: mistura antiga, mal distribuída)
FROTA_ATUAL = FrotaAtual(
    composicao={"ONIBUS31": 14, "MICRO20": 8, "VAN15A": 3},  # 25 veículos
    km_dia_declarado=1180.0,
)

DISTRITOS = {
    # nome: (lat_centro, lon_centro, raio_graus, n_pontos, alunos_min, alunos_max)
    "Sede Urbana":     (-21.150, -47.800, 0.018, 26, 3, 11),
    "Distrito Norte":  (-21.090, -47.770, 0.030, 16, 2, 10),
    "Distrito Leste":  (-21.140, -47.720, 0.034, 14, 2, 9),
    "Vila Rural Sul":  (-21.215, -47.835, 0.038, 15, 2, 9),
    "Assent. Oeste":   (-21.170, -47.885, 0.040, 12, 1, 8),
}


def gerar_pontos() -> list:
    pontos, pid = [], 0
    for distrito, (clat, clon, raio, n, amin, amax) in DISTRITOS.items():
        for _ in range(n):
            ang = random.uniform(0, 2 * math.pi)
            r = raio * math.sqrt(random.uniform(0.05, 1.0))
            lat = clat + r * math.cos(ang)
            lon = clon + r * math.sin(ang) / math.cos(math.radians(clat))
            alunos = random.randint(amin, amax)
            cadeirantes = 1 if random.random() < 0.06 else 0
            # escola mais próxima do distrito
            escola = min(
                ESCOLAS,
                key=lambda e: (e.lat - clat) ** 2 + (e.lon - clon) ** 2,
            )
            pid += 1
            pontos.append(
                PontoEmbarque(
                    f"P{pid:03d}", lat, lon, alunos, cadeirantes,
                    escola.id, distrito,
                )
            )
    return pontos


def haversine_km(a, b) -> float:
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def matriz_tempo_dist(locais, fator_rural=1.35, vel_kmh=42.0):
    """Matriz de distância (km) e tempo (min) aproximada por haversine * fator
    de sinuosidade. No produto real, substituída por OSRM sobre OSM — o
    agent-aprendizado depois corrige esses tempos com GPS real."""
    n = len(locais)
    dist = [[0.0] * n for _ in range(n)]
    tempo = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d = haversine_km(locais[i], locais[j]) * fator_rural
                dist[i][j] = d
                tempo[i][j] = max(1, round(d / vel_kmh * 60))
    return dist, tempo


if __name__ == "__main__":
    pts = gerar_pontos()
    total = sum(p.alunos for p in pts)
    cad = sum(p.alunos_cadeirantes for p in pts)
    print(f"Pontos de embarque: {len(pts)} | Alunos: {total} | Cadeirantes: {cad}")
    for d in DISTRITOS:
        dp = [p for p in pts if p.distrito == d]
        print(f"  {d:15s} {len(dp):3d} pontos, {sum(p.alunos for p in dp):4d} alunos")
