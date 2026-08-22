# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 4 · agent-transito
Camada de tempos de percurso, com TRÂNSITO VARIÁVEL.

Até a Sprint 3 o tempo entre dois pontos era uma constante: distância em linha
reta × fator rural ÷ velocidade média. Isso ignora o fato mais óbvio da
operação — a mesma rota leva 18 minutos às 6h40 e 11 minutos às 14h.

Aqui o tempo passa a depender de QUANDO se viaja e de ONDE se viaja, através
de um provedor plugável:

    ProvedorHaversine        linha reta × fator de sinuosidade (offline, sempre disponível)
    ComTransito(provedor)    aplica o perfil de trânsito por faixa horária e zona
    ProvedorExterno          contrato pronto para OSRM/Valhalla/Google/Mapbox/HERE

Os fatores do perfil são PREMISSAS DECLARADAS enquanto não houver GPS real.
Assim que o app do motorista começar a mandar pings, o agent-aprendizado grava
`relatorios/fatores_transito.json` e os fatores medidos substituem os
estimados — sem trocar uma linha do motor de rotas.

Referências de mercado (ver docs/benchmarking-mercado.md): Google Routes API
com TRAFFIC_AWARE_OPTIMAL, Mapbox Matrix com tráfego histórico e ao vivo, OSRM
com atualização de velocidades por CSV, Valhalla com custo por segmento em
tempo de execução.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FATORES_APRENDIDOS = os.path.join(DIR_BASE, "relatorios", "fatores_transito.json")


# ------------------------------------------------------- perfil de trânsito ---
@dataclass(frozen=True)
class FaixaHoraria:
    id: str
    nome: str
    inicio_min: int          # minutos desde 00:00
    fim_min: int
    fator_urbano: float      # multiplicador do tempo base na malha urbana
    fator_rural: float       # multiplicador do tempo base na zona rural

    def contem(self, minuto: int) -> bool:
        minuto %= 1440
        if self.inicio_min <= self.fim_min:
            return self.inicio_min <= minuto < self.fim_min
        return minuto >= self.inicio_min or minuto < self.fim_min  # vira o dia


# Perfil padrão de um município médio do interior: o pico da manhã é o pior
# momento — e é exatamente quando o transporte escolar roda.
PERFIL_PADRAO = (
    FaixaHoraria("pico_manha",  "Pico da manhã",  6 * 60,  8 * 60 + 30, 1.35, 1.10),
    FaixaHoraria("entre_picos", "Entre picos",    8 * 60 + 30, 16 * 60, 1.00, 1.00),
    FaixaHoraria("pico_tarde",  "Pico da tarde",  16 * 60, 19 * 60,     1.30, 1.08),
    FaixaHoraria("fora_pico",   "Fora de pico",   19 * 60, 6 * 60,      0.92, 0.95),
)


def carregar_fatores_aprendidos(caminho: str = FATORES_APRENDIDOS) -> dict:
    """Fatores medidos com GPS real, quando existirem (agent-aprendizado).

    Formato: {"origem": "gps_real", "fatores": {"pico_manha": {"urbano": 1.42,
    "rural": 1.13}, ...}, "amostras": 12345}
    """
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
            dados.setdefault("origem", "gps_real")
            return dados
    return {"origem": "estimado", "fatores": {}, "amostras": 0}


class PerfilDeTransito:
    """Traduz (horário, zona) em um multiplicador de tempo."""

    def __init__(self, faixas=PERFIL_PADRAO, aprendidos: dict = None):
        self.faixas = tuple(faixas)
        self.aprendidos = aprendidos or {"origem": "estimado", "fatores": {}}

    @property
    def origem(self) -> str:
        return self.aprendidos.get("origem", "estimado")

    @property
    def e_estimado(self) -> bool:
        return self.origem != "gps_real"

    def faixa(self, minuto: int) -> FaixaHoraria:
        for f in self.faixas:
            if f.contem(minuto):
                return f
        return self.faixas[0]

    def fator(self, minuto: int, zona: str = "rural") -> float:
        faixa = self.faixa(minuto)
        medido = self.aprendidos.get("fatores", {}).get(faixa.id)
        if medido and zona in medido:
            return float(medido[zona])
        return faixa.fator_urbano if zona == "urbano" else faixa.fator_rural

    def explicar(self, minuto: int, zona: str = "rural") -> str:
        faixa = self.faixa(minuto)
        fonte = ("medido com GPS real" if not self.e_estimado
                 else "estimado, ainda sem GPS real")
        hora = f"{minuto // 60:02d}h{minuto % 60:02d}"
        return (f"{hora} cai em “{faixa.nome}”: tempo multiplicado por "
                f"{self.fator(minuto, zona):.2f} na zona {zona} ({fonte})")

    def resumo(self) -> list:
        return [
            {"faixa": f.nome, "id": f.id,
             "inicio": f"{f.inicio_min // 60:02d}h{f.inicio_min % 60:02d}",
             "fim": f"{f.fim_min // 60:02d}h{f.fim_min % 60:02d}",
             "fator_urbano": self.fator(
                 (f.inicio_min + 1) % 1440, "urbano"),
             "fator_rural": self.fator((f.inicio_min + 1) % 1440, "rural")}
            for f in self.faixas
        ]


# ------------------------------------------------------------- geometria ---
def haversine_km(a, b) -> float:
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def zona_de(local, centro=(-21.150, -47.800), raio_urbano_graus: float = 0.02) -> str:
    """Classifica um ponto como urbano ou rural para efeito de trânsito.

    Aproximação deliberada: o que muda o tempo de percurso é estar na malha
    congestionada ou na estrada. Com malha viária real (OSRM/Valhalla) essa
    classificação some — a via já traz a velocidade.
    """
    d = math.hypot(local[0] - centro[0], local[1] - centro[1])
    return "urbano" if d <= raio_urbano_graus else "rural"


# -------------------------------------------------------------- provedores ---
class ProvedorDeTempos:
    """Contrato que o motor de rotas enxerga. Trocar o provedor não muda o motor."""

    nome = "abstrato"

    def matriz(self, locais, partida_min: int = None, zonas=None):
        """Devolve (distancias_km, tempos_min) — duas matrizes n×n."""
        raise NotImplementedError


class ProvedorHaversine(ProvedorDeTempos):
    """Linha reta × fator de sinuosidade. Offline, determinístico, sempre roda.

    É o piso do sistema: funciona sem internet, sem chave de API e sem servidor
    de mapas — o que importa numa demonstração em prefeitura.
    """

    nome = "haversine"

    def __init__(self, fator_sinuosidade: float = 1.35, vel_kmh: float = 42.0):
        self.fator_sinuosidade = fator_sinuosidade
        self.vel_kmh = vel_kmh

    def matriz(self, locais, partida_min: int = None, zonas=None):
        n = len(locais)
        dist = [[0.0] * n for _ in range(n)]
        tempo = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                d = haversine_km(locais[i], locais[j]) * self.fator_sinuosidade
                dist[i][j] = d
                tempo[i][j] = max(1, round(d / self.vel_kmh * 60))
        return dist, tempo


class ComTransito(ProvedorDeTempos):
    """Envelopa um provedor e aplica o perfil de trânsito por horário e zona.

    O tempo base continua vindo do provedor de baixo (haversine hoje, OSRM
    amanhã); o que este envelope faz é dizer que atravessar a cidade às 6h40
    custa mais do que às 14h. Quando o provedor de baixo já entregar tempo com
    trânsito (Google, Mapbox), este envelope sai de cena — daí a separação.
    """

    def __init__(self, base: ProvedorDeTempos, perfil: PerfilDeTransito = None):
        self.base = base
        self.perfil = perfil or PerfilDeTransito()
        self.nome = f"{base.nome}+transito"

    def matriz(self, locais, partida_min: int = None, zonas=None):
        dist, tempo = self.base.matriz(locais, partida_min, zonas)
        if partida_min is None:
            return dist, tempo
        n = len(locais)
        zonas = zonas or ["rural"] * n
        ajustado = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                # a zona mais lenta do par manda: um trecho que entra na cidade
                # sofre o congestionamento urbano
                zona = "urbano" if "urbano" in (zonas[i], zonas[j]) else "rural"
                fator = self.perfil.fator(partida_min, zona)
                ajustado[i][j] = max(1, round(tempo[i][j] * fator))
        return dist, ajustado


class ProvedorExterno(ProvedorDeTempos):
    """Contrato para malha viária real com trânsito (OSRM, Valhalla, Google...).

    Deliberadamente não implementado: o MVP roda offline. O que fica pronto é
    a assinatura e o ponto de troca — o motor de rotas já chama `matriz()` e
    não sabe de onde o número vem.

    Como plugar, pela ordem de custo/benefício levantada no benchmarking:
    1. OSRM próprio + tabela de velocidades por CSV (grátis, trânsito
       histórico do próprio município, exige servidor);
    2. Valhalla próprio (custo por segmento em tempo de execução, bom para
       restrições de veículo);
    3. Mapbox Matrix (tráfego histórico e ao vivo, cobrado por elemento);
    4. Google Routes com TRAFFIC_AWARE_OPTIMAL (melhor trânsito ao vivo do
       mercado, SKU Pro — caro em matriz grande, use só para ETA do dia).
    """

    def __init__(self, nome: str, chamador=None):
        self.nome = nome
        self.chamador = chamador

    def matriz(self, locais, partida_min: int = None, zonas=None):
        if self.chamador is None:
            raise NotImplementedError(
                f"Provedor '{self.nome}' ainda não está ligado. "
                f"Passe um chamador(locais, partida_min) que devolva "
                f"(distancias_km, tempos_min).")
        return self.chamador(locais, partida_min)


# ------------------------------------------------------------------ padrão ---
def provedor_padrao(com_transito: bool = True) -> ProvedorDeTempos:
    base = ProvedorHaversine()
    if not com_transito:
        return base
    return ComTransito(base, PerfilDeTransito(
        aprendidos=carregar_fatores_aprendidos()))
