# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 13 · agent-saude
O que o transporte de paciente tem que o transporte escolar não tem.

Aluno vai à escola todo dia, no mesmo horário, e volta no mesmo horário.
Paciente não. O transporte sanitário municipal é feito de TRATAMENTOS, e cada
um tem um ritmo próprio:

    hemodiálise      3× por semana, hora marcada, sessão de 4 h, NÃO PODE
                     faltar — faltar é internação
    quimioterapia    ciclo, hora de chegada marcada, hora de saída incerta
    fisioterapia     2 a 3× por semana, sessão curta, remarcável
    consulta/exame   avulso, hora marcada, saída incerta

Quatro diferenças que mudam a roteirização, e que este módulo declara:

1. **Prioridade clínica.** Hemodiálise é `vital`: se não couber na frota, o
   sistema não deixa de fora em silêncio — levanta como decisão de quem
   responde pela saúde. Consulta eletiva pode ser remarcada, e isso é dito.

2. **A volta nem sempre tem hora.** Escolar tem sinal de saída; consulta não.
   O paciente sai quando o médico libera. Tratamento com `retorno_previsivel`
   (hemodiálise, fisioterapia) entra no plano do dia com hora de volta;
   os outros entram como CHAMADA — o paciente avisa, e a volta é encaixada
   pela reotimização. Planejar uma volta que não tem hora é planejar um
   veículo parado três horas no estacionamento do hospital.

3. **Jejum encurta o tempo a bordo.** Quem vai fazer exame em jejum não pode
   rodar 90 minutos coletando outras pessoas. É restrição operacional, e o
   motor a recebe como tempo máximo menor para aquele pedido.

4. **O motorista não vê diagnóstico.** Nada aqui guarda doença, CID ou
   laudo. O que sai para a rota é o que roteiriza: precisa de maca, usa
   cadeira, leva acompanhante, está em jejum. A regra é a mesma de
   `elegibilidade/`: diagnóstico fica no processo, necessidade vai para o
   motor.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prioridade clínica em três níveis, do ponto de vista do TRANSPORTE — não é
# classificação de risco, é o que acontece se a viagem não sair.
PRIORIDADES = {
    "vital": {
        "rotulo": "não pode faltar",
        "explicacao": "sem a sessão o paciente interna — hemodiálise, "
                      "quimioterapia em ciclo, oncologia",
        "remarcavel": False,
    },
    "continuado": {
        "rotulo": "não deveria faltar",
        "explicacao": "interromper atrasa a recuperação — fisioterapia, "
                      "reabilitação, pré-natal",
        "remarcavel": True,
    },
    "eletivo": {
        "rotulo": "remarcável",
        "explicacao": "consulta, exame e retorno de rotina",
        "remarcavel": True,
    },
}

# Tipos de tratamento com o ritmo de cada um. Os valores são os praticados na
# rede pública e ficam aqui, à vista, porque mudam de município para município.
TIPOS_DE_TRATAMENTO = {
    "hemodialise": {"nome": "Hemodiálise", "prioridade": "vital",
                    "duracao_sessao_min": 240, "retorno_previsivel": True,
                    "sessoes_por_semana": 3},
    "quimioterapia": {"nome": "Quimioterapia", "prioridade": "vital",
                      "duracao_sessao_min": 300, "retorno_previsivel": False,
                      "sessoes_por_semana": 1},
    "fisioterapia": {"nome": "Fisioterapia", "prioridade": "continuado",
                     "duracao_sessao_min": 60, "retorno_previsivel": True,
                     "sessoes_por_semana": 2},
    "consulta": {"nome": "Consulta", "prioridade": "eletivo",
                 "duracao_sessao_min": 90, "retorno_previsivel": False,
                 "sessoes_por_semana": 0},
    "exame": {"nome": "Exame", "prioridade": "eletivo",
              "duracao_sessao_min": 60, "retorno_previsivel": False,
              "sessoes_por_semana": 0},
}

# Quem está em jejum não pode rodar o limite normal coletando outras pessoas.
TEMPO_MAX_EM_JEJUM_MIN = 45

# Maca não é "mais um passageiro": é o que decide se o veículo serve ou não.
# Remoção de maca vai em ambulância de transporte, viagem dedicada — três
# assentos numa ambulância de quatro deixam lugar para o acompanhante e
# impedem que duas macas caiam no mesmo veículo, que não existe.
ASSENTOS_DA_MACA = 3

JANELA_CHEGADA_MIN = 20      # padrão dial-a-ride, igual ao porta a porta


@dataclass
class Tratamento:
    """A assinatura de transporte de um paciente — o que se repete."""
    id: str
    paciente_id: str                   # pseudônimo, nunca nome
    unidade_id: str
    tipo: str                          # chave de TIPOS_DE_TRATAMENTO
    origem: tuple                      # (lat, lon) — a casa do paciente
    dias_da_semana: tuple = ()         # 0 = segunda … 6 = domingo
    hora_chegada_min: int = 7 * 60
    cadeirante: bool = False
    maca: bool = False
    acompanhante: bool = False
    jejum: bool = False
    distrito: str = ""
    observacao_operacional: str = ""   # "usa oxigênio", nunca diagnóstico

    @property
    def prioridade(self) -> str:
        return TIPOS_DE_TRATAMENTO.get(self.tipo, {}).get("prioridade",
                                                          "eletivo")

    @property
    def remarcavel(self) -> bool:
        return PRIORIDADES[self.prioridade]["remarcavel"]

    @property
    def retorno_previsivel(self) -> bool:
        return TIPOS_DE_TRATAMENTO.get(self.tipo, {}).get("retorno_previsivel",
                                                          False)

    @property
    def duracao_sessao_min(self) -> int:
        return TIPOS_DE_TRATAMENTO.get(self.tipo, {}).get(
            "duracao_sessao_min", 60)

    def acontece_em(self, dia_da_semana: int) -> bool:
        return dia_da_semana in self.dias_da_semana


@dataclass
class PedidoDeSaude:
    """Uma perna de viagem — ida ou volta. Compatível com o motor PDPTW.

    Os nomes dos campos seguem `dados.demanda_pcd.PedidoPCD` de propósito: o
    porta a porta já resolve embarque e desembarque com janela e tempo máximo
    a bordo, e o transporte sanitário é o mesmo problema com outra origem de
    demanda. Duplicar o solver por causa do vocabulário seria caro e pior.
    """
    id: str
    origem: tuple
    destino_id: str
    destino: tuple
    janela_chegada: tuple
    cadeirante: bool = False
    acompanhante: bool = False
    distrito: str = ""
    # o que é de saúde e o motor precisa saber
    sentido: str = "ida"               # "ida" | "volta"
    tratamento_id: str = ""
    paciente_id: str = ""
    tipo_tratamento: str = "consulta"
    prioridade: str = "eletivo"
    maca: bool = False
    jejum: bool = False
    tempo_max_bordo_min: int = None
    observacao_operacional: str = ""

    @property
    def assentos(self) -> int:
        """Maca ocupa o espaço de três assentos, e vai em veículo próprio."""
        if self.maca:
            return ASSENTOS_DA_MACA + (1 if self.acompanhante else 0)
        return (0 if self.cadeirante else 1) + (1 if self.acompanhante else 0)

    @property
    def posicoes_cadeira(self) -> int:
        return 1 if self.cadeirante else 0


def _janela(hora_chegada_min: int) -> tuple:
    return (hora_chegada_min - JANELA_CHEGADA_MIN, hora_chegada_min)


def pedidos_do_dia(tratamentos: list, dia_da_semana: int,
                   unidades: dict, avulsos: list = None) -> dict:
    """Os pedidos de transporte de um dia, separados pelo que dá para planejar.

    Devolve três listas, e a separação é a informação:

        `ida`              tudo que tem hora de chegada — planejável hoje
        `volta_planejada`  tratamento com hora de saída conhecida
        `volta_por_chamada` tratamento cuja saída depende do médico liberar

    A terceira lista NÃO entra no plano da manhã. Ela existe para o
    despachante saber quantas voltas vão pipocar durante o dia e reservar
    folga de frota — planejar hora que ninguém sabe é como o transporte
    sanitário perde veículo parado no estacionamento do hospital.
    """
    ida, volta_planejada, volta_por_chamada = [], [], []

    for t in list(tratamentos) + list(avulsos or []):
        if t.dias_da_semana and not t.acontece_em(dia_da_semana):
            continue
        destino = unidades.get(t.unidade_id)
        if not destino:
            continue

        tempo_max = TEMPO_MAX_EM_JEJUM_MIN if t.jejum else None
        ida.append(PedidoDeSaude(
            id=f"{t.id}-ida", origem=t.origem, destino_id=t.unidade_id,
            destino=destino, janela_chegada=_janela(t.hora_chegada_min),
            cadeirante=t.cadeirante, acompanhante=t.acompanhante,
            distrito=t.distrito, sentido="ida", tratamento_id=t.id,
            paciente_id=t.paciente_id, tipo_tratamento=t.tipo,
            prioridade=t.prioridade, maca=t.maca, jejum=t.jejum,
            tempo_max_bordo_min=tempo_max,
            observacao_operacional=t.observacao_operacional))

        saida = t.hora_chegada_min + t.duracao_sessao_min
        volta = PedidoDeSaude(
            id=f"{t.id}-volta", origem=destino, destino_id="casa",
            destino=t.origem, janela_chegada=(saida, saida + JANELA_CHEGADA_MIN),
            cadeirante=t.cadeirante, acompanhante=t.acompanhante,
            distrito=t.distrito, sentido="volta", tratamento_id=t.id,
            paciente_id=t.paciente_id, tipo_tratamento=t.tipo,
            prioridade=t.prioridade, maca=t.maca,
            observacao_operacional=t.observacao_operacional)
        if t.retorno_previsivel:
            volta_planejada.append(volta)
        else:
            volta_por_chamada.append(volta)

    return {
        "ida": ida,
        "volta_planejada": volta_planejada,
        "volta_por_chamada": volta_por_chamada,
        "resumo": _resumo(ida, volta_planejada, volta_por_chamada),
    }


def _resumo(ida, volta_planejada, volta_por_chamada) -> dict:
    todos = ida + volta_planejada
    return {
        "pedidos_planejaveis": len(todos),
        "idas": len(ida),
        "voltas_planejadas": len(volta_planejada),
        "voltas_por_chamada": len(volta_por_chamada),
        "por_prioridade": _contar(ida, "prioridade"),
        "por_tipo": _contar(ida, "tipo_tratamento"),
        "com_maca": sum(1 for p in todos if p.maca),
        "cadeirantes": sum(1 for p in todos if p.cadeirante),
        "com_acompanhante": sum(1 for p in todos if p.acompanhante),
        "em_jejum": sum(1 for p in ida if p.jejum),
        "assentos_necessarios_no_pico": None,   # calculado pelo motor
    }


def _contar(pedidos, campo) -> dict:
    contagem = {}
    for p in pedidos:
        chave = getattr(p, campo)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def explicar_prioridade(prioridade: str) -> dict:
    return dict(PRIORIDADES.get(prioridade, PRIORIDADES["eletivo"]),
                id=prioridade)
