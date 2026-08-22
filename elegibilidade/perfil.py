# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
O perfil de necessidade: o que a roteirização precisa saber, e só isso.

A regra que organiza este módulo inteiro:

    DIAGNÓSTICO NÃO ROTEIRIZA. NECESSIDADE ROTEIRIZA.

Saber que a pessoa tem paralisia cerebral não diz ao solver nada que ele possa
usar. Saber que ela usa cadeira de rodas motorizada, precisa de plataforma
elevatória, viaja com acompanhante e não pode passar de 40 minutos a bordo
diz tudo. O primeiro é dado sensível de saúde; o segundo é restrição
operacional. O sistema guarda os dois em lugares diferentes, e só o segundo
chega perto de um arquivo de rota.

`Perfil.para_roteirizacao()` é a fronteira: o que sai dali pode ir para o
motor, para o painel e para o app do motorista. O resto fica no processo de
elegibilidade, que tem dono, prazo e registro de quem olhou.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Tempo extra de parada por embarque, em minutos, quando há auxílio. Vem da
# medição do próprio sistema (ver aprendizado/): embarque com cadeirante leva
# ~3,5 min, e não os 1,5 min que o planejamento supunha.
MIN_PARADA_PADRAO = 1.5
MIN_PARADA_CADEIRANTE = 3.5
MIN_PARADA_ELEVADOR = 5.0
MIN_PARADA_AUXILIO = 2.5

TEMPO_MAX_BORDO_PADRAO = 60


@dataclass
class Perfil:
    """Necessidades operacionais de transporte de uma pessoa.

    Nenhum campo aqui é diagnóstico. Se um dia alguém quiser acrescentar
    "CID" a esta classe, a resposta é não: o CID vive no pedido, com controle
    de acesso, e nunca em dado de rota.
    """
    porta_a_porta: bool = False
    cadeira_de_rodas: bool = False
    cadeira_motorizada: bool = False
    elevador_ou_rampa: bool = False
    acompanhante: bool = False
    auxilio_no_embarque: bool = False
    cinto_de_quatro_pontos: bool = False
    evitar_lotacao: bool = False
    tempo_max_bordo_min: int = TEMPO_MAX_BORDO_PADRAO
    max_passageiros_junto: int = 0        # 0 = sem restrição
    observacoes_operacionais: str = ""

    # ------------------------------------------------------------ derivados --
    @property
    def min_parada(self) -> float:
        """Quanto tempo o veículo fica parado para esta pessoa embarcar."""
        if self.elevador_ou_rampa or self.cadeira_motorizada:
            base = MIN_PARADA_ELEVADOR
        elif self.cadeira_de_rodas:
            base = MIN_PARADA_CADEIRANTE
        elif self.auxilio_no_embarque:
            base = MIN_PARADA_AUXILIO
        else:
            base = MIN_PARADA_PADRAO
        return round(base + (0.5 if self.acompanhante else 0.0), 2)

    @property
    def assentos(self) -> int:
        return (0 if self.cadeira_de_rodas else 1) + (1 if self.acompanhante else 0)

    @property
    def posicoes_cadeira(self) -> int:
        return 1 if self.cadeira_de_rodas else 0

    def veiculo_precisa(self) -> list:
        """Requisitos que o veículo tem que ter — o solver filtra por isso."""
        exigencias = []
        if self.posicoes_cadeira:
            exigencias.append("posicao_cadeira")
        if self.elevador_ou_rampa or self.cadeira_motorizada:
            exigencias.append("plataforma_elevatoria")
        if self.cinto_de_quatro_pontos:
            exigencias.append("cinto_quatro_pontos")
        return exigencias

    def coerente(self) -> list:
        """Combinações que não fazem sentido — pega erro de digitação e de
        marcação antes de virar rota impossível."""
        problemas = []
        if self.cadeira_motorizada and not self.cadeira_de_rodas:
            problemas.append("Cadeira motorizada marcada sem cadeira de rodas.")
        if self.cadeira_de_rodas and not self.porta_a_porta:
            problemas.append(
                "Usuário de cadeira de rodas sem atendimento porta a porta — "
                "confirme se ele consegue mesmo chegar ao ponto de encontro.")
        if self.tempo_max_bordo_min < 10:
            problemas.append("Tempo máximo a bordo abaixo de 10 minutos "
                             "inviabiliza qualquer rota compartilhada.")
        if self.max_passageiros_junto and self.max_passageiros_junto < 1:
            problemas.append("Máximo de passageiros junto tem que ser 1 ou mais.")
        if self.evitar_lotacao and not self.max_passageiros_junto:
            problemas.append("‘Evitar lotação’ sem número: quantas pessoas no "
                             "máximo podem viajar junto?")
        return problemas

    # ------------------------------------------------------------ fronteira --
    def para_roteirizacao(self, identificador: str) -> dict:
        """O único formato que sai daqui para o motor de rotas.

        Sem nome, sem diagnóstico, sem endereço textual, sem observação
        clínica: identificador pseudonimizado e restrições operacionais.
        """
        return {
            "id": identificador,
            "porta_a_porta": self.porta_a_porta,
            "cadeirante": self.cadeira_de_rodas,
            "acompanhante": self.acompanhante,
            "assentos": self.assentos,
            "posicoes_cadeira": self.posicoes_cadeira,
            "min_parada": self.min_parada,
            "tempo_max_bordo_min": self.tempo_max_bordo_min,
            "max_passageiros_junto": self.max_passageiros_junto,
            "veiculo_precisa": self.veiculo_precisa(),
        }

    def como_dicionario(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dicionario(cls, dados: dict) -> "Perfil":
        campos = {c: dados[c] for c in cls.__dataclass_fields__ if c in dados}
        return cls(**campos)

    def resumo(self) -> str:
        """Uma linha em português para o analista ler na fila."""
        partes = []
        if self.porta_a_porta:
            partes.append("porta a porta")
        if self.cadeira_de_rodas:
            partes.append("cadeira motorizada" if self.cadeira_motorizada
                          else "cadeira de rodas")
        if self.elevador_ou_rampa:
            partes.append("plataforma elevatória")
        if self.acompanhante:
            partes.append("com acompanhante")
        if self.auxilio_no_embarque:
            partes.append("auxílio no embarque")
        if self.evitar_lotacao:
            partes.append(f"no máximo {self.max_passageiros_junto} junto")
        if self.tempo_max_bordo_min != TEMPO_MAX_BORDO_PADRAO:
            partes.append(f"até {self.tempo_max_bordo_min} min a bordo")
        return "; ".join(partes) if partes else "sem restrição operacional"


@dataclass
class Concessao:
    """A decisão: perfil aprovado, por quem, até quando."""
    pedido: str
    perfil: Perfil
    analista: str
    decidido_em: str
    vence_em: str = ""
    permanente: bool = False
    justificativa: str = ""
    fontes: list = field(default_factory=list)

    def vigente_em(self, data: str) -> bool:
        if self.permanente or not self.vence_em:
            return True
        return data <= self.vence_em
