# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 1 (revisado na Sprint 3) · agent-dados
Esquema de dados + gerador do Município Modelo sintético.

Município fictício: "Ribeirão Modelo" (~30 mil hab), sede urbana + 4 distritos
rurais, 3 escolas-polo e ~3.000 alunos transportados por dia, divididos entre
os turnos da manhã e da tarde. Frota atual declarada pela prefeitura: 25
veículos — o cenário típico de roteiro histórico, montado por bairro e nunca
recalculado.

O que mudou na Sprint 3: a demanda subiu de 466 para ~3.000 alunos, os alunos
passaram a ser distribuídos por turno e cada parada ganhou TEMPO DE EMBARQUE.
Isso só faz sentido junto com a roteirização multiviagem do motor — um mesmo
veículo faz duas ou três viagens por turno, que é como a prefeitura opera de
verdade.
"""
import math
import random
from dataclasses import dataclass, field

from dados import tempos

random.seed(42)  # reprodutível para a demo


# ---------------------------------------------------------------- esquema ---
@dataclass
class Turno:
    id: str
    nome: str
    janela_chegada: tuple    # (min_inicio, min_fim) minutos desde 00:00
    jornada_max_min: int     # tempo disponível para coletar antes do sinal
    # Quanto dura o turno de quem foi transportado. Serve para saber QUANDO é
    # a dispersão — no escolar dá para viver sem (o mesmo veículo leva e traz
    # e ninguém pergunta quem dirige); no fretamento é o que separa a conta de
    # veículos da conta de motoristas. 0 = não modelada.
    duracao_min: int = 0


@dataclass
class Escola:
    id: str
    nome: str
    lat: float
    lon: float


@dataclass
class PontoEmbarque:
    id: str
    lat: float
    lon: float
    alunos: dict             # turno_id -> alunos que embarcam neste ponto
    alunos_cadeirantes: dict  # turno_id -> subset que precisa de cadeira
    escola_id: str
    distrito: str

    def total_alunos(self) -> int:
        return sum(self.alunos.values())


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
    viagens_por_veiculo_turno: float = 2.0  # o que a operação atual consegue


# ------------------------------------------------------ município modelo ---
# Coordenadas fictícias em torno de um centro (-21.15, -47.80)
CENTRO = (-21.15, -47.80)

# Dois turnos: o mesmo veículo atende os dois, em jornadas separadas.
TURNOS = [
    Turno("manha", "Manhã", (6 * 60 + 40, 7 * 60), 100),
    Turno("tarde", "Tarde", (12 * 60 + 40, 13 * 60), 100),
]

ESCOLAS = [
    Escola("E1", "EMEF Centro",         -21.150, -47.800),
    Escola("E2", "EMEF Distrito Norte", -21.095, -47.775),
    Escola("E3", "EMEF Vila Rural Sul", -21.210, -47.830),
]

TIPOS_VEICULO = [
    TipoVeiculo("ONIBUS31", "Ônibus escolar 31 lugares", 31, 0, 3.10, 14500.0, 3.2),
    TipoVeiculo("MICRO20",  "Micro-ônibus 20 lugares",   20, 0, 2.40, 11800.0, 4.5),
    TipoVeiculo("VAN15A",   "Van acessível 15 lugares",  15, 2, 1.95, 10200.0, 6.0),
]

# ------------------------------------------------------------- frota atual ---
# Num município real a frota atual é DADO DE ENTRADA: vem do cadastro da
# secretaria e dos contratos de terceirização. Aqui o município é fictício,
# então ela é gerada — e por isso vem de uma conta explícita, com as três
# premissas abaixo declaradas no painel, em vez de um número escolhido a dedo.
OCUPACAO_ATUAL = 0.85              # roteiro histórico por bairro, sem agrupamento
VIAGENS_VEICULO_TURNO_ATUAL = 2.5  # o que a operação de hoje consegue encadear
FATOR_KM_ROTEIRO_ATUAL = 1.25      # rotas atuais 25% mais longas que as otimizadas
MIX_ATUAL = {"ONIBUS31": 0.56, "MICRO20": 0.32, "VAN15A": 0.12}


def _distribuir(total: int, mix: dict) -> dict:
    """Distribui `total` veículos na proporção do mix, pelo maior resto."""
    brutos = {t: total * p for t, p in mix.items()}
    comp = {t: int(v) for t, v in brutos.items()}
    sobra = total - sum(comp.values())
    for t, _ in sorted(brutos.items(), key=lambda kv: -(kv[1] - int(kv[1]))):
        if sobra <= 0:
            break
        comp[t] += 1
        sobra -= 1
    return {t: q for t, q in comp.items() if q > 0}


def frota_atual_sintetica(alunos_por_turno: dict, km_medio_viagem: float,
                          viagens_por_rota: int, tipos=None):
    """Reconstrói a frota que a prefeitura fictícia precisaria hoje.

    A conta, passo a passo:
    1. o turno mais cheio manda no tamanho da frota;
    2. com ocupação média de 85%, ele exige alunos ÷ 0,85 lugares-viagem;
    3. cada veículo entrega capacidade × 2,5 viagens por turno;
    4. o km/dia sai do número de viagens necessárias, do km médio de uma
       viagem otimizada e do fator de roteiro 1,25.
    """
    tipos = tipos or TIPOS_VEICULO
    capacidades = {t.id: t.capacidade for t in tipos}
    cap_media = sum(capacidades[t] * p for t, p in MIX_ATUAL.items())

    turno_critico = max(alunos_por_turno.values())
    lugares_viagem = turno_critico / OCUPACAO_ATUAL
    veiculos = math.ceil(lugares_viagem / (cap_media * VIAGENS_VEICULO_TURNO_ATUAL))
    composicao = _distribuir(veiculos, MIX_ATUAL)

    viagens_dia = sum(alunos_por_turno.values()) / (cap_media * OCUPACAO_ATUAL)
    km_dia = viagens_dia * km_medio_viagem * FATOR_KM_ROTEIRO_ATUAL * viagens_por_rota

    frota = FrotaAtual(
        composicao=composicao,
        km_dia_declarado=round(km_dia, 1),
        viagens_por_veiculo_turno=VIAGENS_VEICULO_TURNO_ATUAL,
    )
    premissas = {
        "origem": "cenário sintético — num município real este dado vem do "
                  "cadastro da secretaria, não de estimativa",
        "ocupacao_media": OCUPACAO_ATUAL,
        "viagens_por_veiculo_turno": VIAGENS_VEICULO_TURNO_ATUAL,
        "fator_km_roteiro": FATOR_KM_ROTEIRO_ATUAL,
        "mix_de_tipos": MIX_ATUAL,
        "turno_critico_alunos": turno_critico,
        "viagens_dia_estimadas": round(viagens_dia),
    }
    return frota, premissas

# Proporção de alunos por turno (manhã concentra mais, como no ensino público)
PROPORCAO_MANHA = 0.55

DISTRITOS = {
    # nome: (lat_centro, lon_centro, raio_graus, n_pontos, alunos_min, alunos_max)
    "Sede Urbana":     (-21.150, -47.800, 0.018, 95, 6, 16),
    "Distrito Norte":  (-21.090, -47.770, 0.030, 58, 5, 14),
    "Distrito Leste":  (-21.140, -47.720, 0.034, 52, 5, 13),
    "Vila Rural Sul":  (-21.215, -47.835, 0.038, 52, 4, 13),
    "Assent. Oeste":   (-21.170, -47.885, 0.040, 43, 4, 12),
}

# Tempo de embarque na parada: um tempo fixo de abertura de porta, mais o
# embarque aluno a aluno, mais o tempo extra de acomodar cadeira de rodas.
# O agent-aprendizado corrige esses valores por ponto com dados reais.
PARADA_FIXA_MIN = 1.0
PARADA_POR_ALUNO_MIN = 0.08
PARADA_POR_CADEIRANTE_MIN = 3.0


def tempo_parada_min(ponto: PontoEmbarque, turno_id: str) -> int:
    alunos = ponto.alunos.get(turno_id, 0)
    if alunos == 0:
        return 0
    cadeirantes = ponto.alunos_cadeirantes.get(turno_id, 0)
    return max(1, round(PARADA_FIXA_MIN
                        + PARADA_POR_ALUNO_MIN * alunos
                        + PARADA_POR_CADEIRANTE_MIN * cadeirantes))


def gerar_pontos() -> list:
    pontos, pid = [], 0
    for distrito, (clat, clon, raio, n, amin, amax) in DISTRITOS.items():
        for _ in range(n):
            ang = random.uniform(0, 2 * math.pi)
            r = raio * math.sqrt(random.uniform(0.05, 1.0))
            lat = clat + r * math.cos(ang)
            lon = clon + r * math.sin(ang) / math.cos(math.radians(clat))

            total = random.randint(amin, amax)
            manha = max(1, round(total * PROPORCAO_MANHA
                                 + random.uniform(-1.5, 1.5)))
            manha = min(manha, total - 1) if total > 1 else total
            alunos = {"manha": manha, "tarde": total - manha}

            cadeirantes = {"manha": 0, "tarde": 0}
            if random.random() < 0.06:
                turno = "manha" if random.random() < PROPORCAO_MANHA else "tarde"
                if alunos[turno] > 0:
                    cadeirantes[turno] = 1

            # escola-polo mais próxima do distrito
            escola = min(ESCOLAS,
                         key=lambda e: (e.lat - clat) ** 2 + (e.lon - clon) ** 2)
            pid += 1
            pontos.append(
                PontoEmbarque(f"P{pid:03d}", lat, lon, alunos, cadeirantes,
                              escola.id, distrito)
            )
    return pontos


# Geometria e matrizes vivem em dados/tempos.py desde a Sprint 4, junto com o
# perfil de trânsito. Estes dois nomes continuam aqui porque meio código já os
# importa daqui — e porque a matriz sem trânsito ainda é o piso do sistema.
haversine_km = tempos.haversine_km


def matriz_tempo_dist(locais, fator_rural=1.35, vel_kmh=42.0):
    """Matriz de distância (km) e tempo (min) SEM trânsito.

    Para tempos com trânsito variável por horário, use
    `dados.tempos.provedor_padrao().matriz(locais, partida_min=...)`.
    """
    return tempos.ProvedorHaversine(fator_rural, vel_kmh).matriz(locais)


if __name__ == "__main__":
    pts = gerar_pontos()
    total = sum(p.total_alunos() for p in pts)
    print(f"Pontos de embarque: {len(pts)} | Alunos/dia: {total}")
    for t in TURNOS:
        alunos = sum(p.alunos[t.id] for p in pts)
        cad = sum(p.alunos_cadeirantes[t.id] for p in pts)
        print(f"  Turno {t.nome:6s} {alunos:5d} alunos ({cad} cadeirantes)")
    for d in DISTRITOS:
        dp = [p for p in pts if p.distrito == d]
        print(f"  {d:15s} {len(dp):3d} pontos, "
              f"{sum(p.total_alunos() for p in dp):5d} alunos")
    for e in ESCOLAS:
        ep = [p for p in pts if p.escola_id == e.id]
        print(f"  {e.nome:22s} {len(ep):3d} pontos, "
              f"{sum(p.total_alunos() for p in ep):5d} alunos")
