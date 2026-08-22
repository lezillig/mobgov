# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 4 · agent-dados / agent-porta-a-porta
Demanda do transporte PORTA A PORTA (usuários com deficiência).

Diferença essencial para o escolar:

    Escolar (ponto de encontro)      PCD (porta a porta)
    --------------------------      -------------------------------------
    o aluno caminha até o ponto     o veículo encosta na casa do usuário
    destino único por rota          n embarques e n desembarques por rota
    janela = sinal da escola        janela por usuário (consulta, terapia)
    tempo máximo por aluno          tempo máximo A BORDO por usuário

A relação é n:n: numa mesma rota o veículo pode pegar o usuário A, pegar o B,
deixar o A, pegar o C e deixar B e C — desde que ninguém fique a bordo além do
limite e cada um chegue na sua janela. Isso é um PDPTW (pickup and delivery
with time windows), resolvido em motor/porta_a_porta.py.

LGPD: nenhum nome, CPF ou diagnóstico. O usuário é um identificador
pseudonimizado e um conjunto de restrições operacionais (cadeira de rodas,
acompanhante) — que é tudo o que a roteirização precisa saber.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from dados.municipio_modelo import DISTRITOS, TipoVeiculo

_rng = random.Random(2026)   # gerador próprio: não interfere no seed do escolar


# ---------------------------------------------------------------- esquema ---
@dataclass
class Destino:
    id: str
    nome: str
    lat: float
    lon: float


@dataclass
class PedidoPCD:
    """Uma viagem solicitada. Sem dado pessoal — só o que roteiriza."""
    id: str
    origem: tuple             # (lat, lon) — a casa do usuário
    destino_id: str
    destino: tuple
    janela_chegada: tuple     # (min_inicio, min_fim) desde 00:00
    cadeirante: bool
    acompanhante: bool
    distrito: str

    @property
    def assentos(self) -> int:
        """Cadeirante ocupa posição de cadeira; acompanhante ocupa assento."""
        return (0 if self.cadeirante else 1) + (1 if self.acompanhante else 0)

    @property
    def posicoes_cadeira(self) -> int:
        return 1 if self.cadeirante else 0


# Veículos do porta a porta: van pequena adaptada, o padrão do paratransit.
TIPOS_PCD = [
    TipoVeiculo("VANPCD8", "Van porta a porta 8 lugares", 8, 2, 1.70, 9200.0, 8.0),
    TipoVeiculo("VAN15A", "Van acessível 15 lugares", 15, 2, 1.95, 10200.0, 6.0),
]

DESTINOS = [
    Destino("D1", "CER — Centro de Reabilitação", -21.152, -47.805),
    Destino("D2", "Hospital Municipal",           -21.146, -47.792),
    Destino("D3", "APAE / escola especial",       -21.160, -47.812),
]

GARAGEM = (-21.155, -47.795)

# Janelas de chegada praticadas: consultas e terapias começam de hora em hora.
# A janela de 20 minutos é o padrão do dial-a-ride (ver benchmarking).
HORARIOS_CHEGADA = [7 * 60 + 30, 8 * 60, 8 * 60 + 30, 9 * 60,
                    9 * 60 + 30, 10 * 60, 10 * 60 + 30, 11 * 60]
JANELA_EMBARQUE_MIN = 20

# Tempo de embarque/desembarque na porta — o cadeirante usa rampa ou elevador.
EMBARQUE_COMUM_MIN = 2
EMBARQUE_CADEIRANTE_MIN = 5

# Limite de tempo a bordo: tempo direto × fator + folga. Espelha a regra
# americana ("não mais que ~1 hora além do tempo direto") num parâmetro que a
# secretaria pode apertar ou afrouxar — e que aparece no painel.
FATOR_TEMPO_BORDO = 1.6
FOLGA_TEMPO_BORDO_MIN = 15

PROPORCAO_CADEIRANTE = 0.35
PROPORCAO_ACOMPANHANTE = 0.30
PEDIDOS_POR_DIA = 80


def gerar_pedidos(quantidade: int = PEDIDOS_POR_DIA) -> list:
    """Gera a demanda diária sintética do porta a porta."""
    distritos = list(DISTRITOS.items())
    pedidos = []
    for i in range(quantidade):
        nome, (clat, clon, raio, *_) = distritos[i % len(distritos)]
        ang = _rng.uniform(0, 2 * math.pi)
        r = raio * math.sqrt(_rng.uniform(0.05, 1.0))
        lat = clat + r * math.cos(ang)
        lon = clon + r * math.sin(ang) / math.cos(math.radians(clat))

        destino = _rng.choice(DESTINOS)
        chegada = _rng.choice(HORARIOS_CHEGADA)
        pedidos.append(PedidoPCD(
            id=f"U{i + 1:03d}",
            origem=(lat, lon),
            destino_id=destino.id,
            destino=(destino.lat, destino.lon),
            janela_chegada=(chegada - JANELA_EMBARQUE_MIN, chegada),
            cadeirante=_rng.random() < PROPORCAO_CADEIRANTE,
            acompanhante=_rng.random() < PROPORCAO_ACOMPANHANTE,
            distrito=nome,
        ))
    return pedidos


def tempo_embarque_min(pedido: PedidoPCD, perfil=None) -> int:
    if pedido.cadeirante:
        return (getattr(perfil, "embarque_cadeirante_min", None)
                or EMBARQUE_CADEIRANTE_MIN)
    return getattr(perfil, "embarque_comum_min", None) or EMBARQUE_COMUM_MIN


def limite_tempo_bordo_min(tempo_direto_min: int, perfil=None) -> int:
    """Quanto tempo o usuário pode ficar dentro do veículo, no máximo.

    Os dois números saem do perfil da operação quando ele é passado; as
    constantes acima são só o padrão de quem não configurou nada. Regra que
    decide quanto tempo uma criança fica dentro do ônibus não pode morar
    escondida numa constante de módulo.
    """
    fator = getattr(perfil, "fator_tempo_bordo", None) or FATOR_TEMPO_BORDO
    folga = getattr(perfil, "folga_tempo_bordo_min", None)
    if folga is None:
        folga = FOLGA_TEMPO_BORDO_MIN
    return math.ceil(tempo_direto_min * fator) + folga


if __name__ == "__main__":
    pedidos = gerar_pedidos()
    cad = sum(1 for p in pedidos if p.cadeirante)
    aco = sum(1 for p in pedidos if p.acompanhante)
    print(f"Pedidos porta a porta: {len(pedidos)} | cadeirantes: {cad} "
          f"({100 * cad // len(pedidos)}%) | com acompanhante: {aco}")
    for d in DESTINOS:
        n = sum(1 for p in pedidos if p.destino_id == d.id)
        print(f"  {d.nome:34s} {n:3d} viagens")
    for h in sorted({p.janela_chegada[1] for p in pedidos}):
        n = sum(1 for p in pedidos if p.janela_chegada[1] == h)
        print(f"  chegada até {h // 60:02d}h{h % 60:02d}: {n} pedidos")
