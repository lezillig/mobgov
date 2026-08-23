# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 14 · agent-saude
TFD — Tratamento Fora do Domicílio: a van que sai de madrugada para a capital.

Todo município brasileiro tem esta operação e quase nenhum a mede. O
desenho é sempre o mesmo: um veículo sai às 4h da manhã levando de 8 a 40
pessoas, cada uma para um hospital diferente da cidade-polo, e volta quando o
último for liberado. A Portaria SAS/MS nº 55/1999 é o marco: autorização
prévia, acompanhante por direito em casos definidos e ajuda de custo.

Três coisas que este módulo mede e que hoje ninguém mede:

1. **Quanto tempo cada paciente espera no destino.** Quem tem consulta às 8h
   e volta às 17h porque outro tem consulta às 15h passou nove horas num
   saguão — em jejum, muitas vezes idoso, às vezes com dor. Esse número não
   aparece em relatório nenhum, e é o que faz a família desistir do
   tratamento. Aqui ele é o primeiro indicador da viagem.

2. **Quem ficou de fora e por quê.** Vaga é finita e a fila precisa ser
   justa: a ordem de corte é a data da autorização, com a prioridade clínica
   à frente. Quem não coube sai com posição na fila e a próxima data — nunca
   some.

3. **O direito ao acompanhante como regra do sistema, não favor.** Menor de
   18, maior de 60 ou incapacidade declarada têm direito, e o acompanhante
   ocupa vaga de verdade. Sistema que "esquece" o acompanhante lota a van no
   papel e deixa gente na calçada às 4h da manhã.

Como no resto do vertical de saúde: nada de diagnóstico. A especialidade
("oncologia", "cardiologia") é o serviço contratado, aparece no processo do
TFD e é o que decide para qual hospital a pessoa vai — não é laudo.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.tempos import haversine_km  # noqa: E402

# Idades que dão direito a acompanhante pela norma do TFD. Estão aqui, à
# vista, porque secretaria estadual às vezes amplia — e quem confere precisa
# poder comparar com o regulamento que assinou.
IDADE_MENOR = 18
IDADE_IDOSO = 60

# Velocidade média de rodovia para estimar a viagem intermunicipal. É
# estimativa declarada: quando o OSRM estiver ligado, ela some.
VELOCIDADE_RODOVIA_KMH = 65.0

# Folga de chegada antes do primeiro compromisso. Hospital não atende quem
# chega em cima da hora, e a fila de recepção é real.
FOLGA_CHEGADA_MIN = 60

# Acima disto a espera no destino deixa de ser inconveniente e vira problema
# de saúde — idoso em jejum, criança, pessoa com dor.
ESPERA_ACEITAVEL_MIN = 240

# Ajuda de custo por pessoa por dia de viagem. Valor de referência: cada
# município fixa o seu em decreto, e é por isso que é parâmetro.
AJUDA_DE_CUSTO_PADRAO = 60.0


def direito_a_acompanhante(idade: int, incapacidade: bool = False) -> tuple:
    """Devolve (tem_direito, motivo) — a regra escrita, não a interpretação."""
    if incapacidade:
        return True, "incapacidade declarada no laudo de encaminhamento"
    if idade < IDADE_MENOR:
        return True, f"menor de {IDADE_MENOR} anos"
    if idade >= IDADE_IDOSO:
        return True, f"{IDADE_IDOSO} anos ou mais"
    return False, ""


@dataclass
class AutorizacaoTFD:
    """Um encaminhamento aprovado — a fila do TFD é feita destes."""
    id: str
    paciente_id: str
    origem: tuple                       # casa do paciente
    cidade_destino: str
    unidade_destino: str
    coordenada_destino: tuple
    data_do_atendimento: str            # AAAA-MM-DD
    hora_atendimento_min: int
    duracao_prevista_min: int = 120
    especialidade: str = ""             # serviço contratado, nunca diagnóstico
    idade: int = 40
    incapacidade: bool = False
    cadeirante: bool = False
    prioridade: str = "eletivo"         # mesma escala de saude/tratamento.py
    autorizada_em: str = ""             # AAAA-MM-DD — define a ordem da fila
    distrito: str = ""

    @property
    def acompanhante(self) -> bool:
        return direito_a_acompanhante(self.idade, self.incapacidade)[0]

    @property
    def motivo_do_acompanhante(self) -> str:
        return direito_a_acompanhante(self.idade, self.incapacidade)[1]

    @property
    def vagas(self) -> int:
        return 1 + (1 if self.acompanhante else 0)


@dataclass
class VeiculoTFD:
    id: str
    nome: str
    lugares: int
    posicoes_cadeirante: int = 0
    custo_km: float = 2.4
    ajuda_de_custo: float = AJUDA_DE_CUSTO_PADRAO


ORDEM_DA_PRIORIDADE = {"vital": 0, "continuado": 1, "eletivo": 2}


def _ordem_da_fila(a: AutorizacaoTFD) -> tuple:
    """Quem entra primeiro quando falta vaga.

    Prioridade clínica na frente; empatou, quem autorizou antes vai antes.
    A data da autorização é o que torna a fila defensável: não é o telefonema
    de quem conhece alguém na secretaria.
    """
    return (ORDEM_DA_PRIORIDADE.get(a.prioridade, 3),
            a.autorizada_em or "9999-99-99", a.id)


def _minutos_de_viagem(origem: tuple, destino: tuple) -> int:
    km = haversine_km(origem, destino)
    return int(round(km / VELOCIDADE_RODOVIA_KMH * 60))


def montar_viagem(autorizacoes: list, data_do_atendimento: str,
                  veiculo: VeiculoTFD, garagem: tuple,
                  ajuda_de_custo: float = None) -> dict:
    """A viagem de TFD de um dia: quem vai, a que horas, e quem espera quanto.

    O veículo é um só e volta com todo mundo — é assim que a operação existe.
    Por isso a hora de retorno é a do ÚLTIMO liberado, e a espera de cada um é
    a diferença entre isso e a hora em que ele terminou.
    """
    do_dia = [a for a in autorizacoes
              if a.data_do_atendimento == data_do_atendimento]
    do_dia.sort(key=_ordem_da_fila)

    embarcados, fila, vagas_usadas = [], [], 0
    cadeiras_usadas = 0
    for a in do_dia:
        tem_lugar = vagas_usadas + a.vagas <= veiculo.lugares
        # posição de cadeira é limite próprio: van cheia de assentos livres
        # não resolve para quem vai de cadeira de rodas
        tem_cadeira = (not a.cadeirante
                       or cadeiras_usadas < veiculo.posicoes_cadeirante)
        if tem_lugar and tem_cadeira:
            embarcados.append(a)
            vagas_usadas += a.vagas
            cadeiras_usadas += 1 if a.cadeirante else 0
        else:
            fila.append(a)

    if not embarcados:
        return _viagem_vazia(data_do_atendimento, veiculo, fila)

    # ida: sair cedo o bastante para o primeiro compromisso, com folga
    destino_mais_longe = max(
        (_minutos_de_viagem(garagem, a.coordenada_destino) for a in embarcados),
        default=0)
    primeiro = min(a.hora_atendimento_min for a in embarcados)
    saida = primeiro - destino_mais_longe - FOLGA_CHEGADA_MIN

    # retorno: o veículo espera todo mundo; quem manda é o último liberado
    liberacoes = {a.id: a.hora_atendimento_min + a.duracao_prevista_min
                  for a in embarcados}
    ultimo = max(liberacoes.values())
    retorno = ultimo + destino_mais_longe

    passageiros = []
    for a in embarcados:
        espera = ultimo - liberacoes[a.id]
        passageiros.append({
            "autorizacao": a.id, "paciente": a.paciente_id,
            "unidade": a.unidade_destino, "cidade": a.cidade_destino,
            "especialidade": a.especialidade,
            "hora_atendimento": _hhmm(a.hora_atendimento_min),
            "liberado_previsto": _hhmm(liberacoes[a.id]),
            "espera_no_destino_min": espera,
            "espera_demais": espera > ESPERA_ACEITAVEL_MIN,
            "acompanhante": a.acompanhante,
            "motivo_do_acompanhante": a.motivo_do_acompanhante,
            "cadeirante": a.cadeirante,
            "prioridade": a.prioridade,
            "vagas": a.vagas,
            "distrito": a.distrito,
        })
    passageiros.sort(key=lambda p: -p["espera_no_destino_min"])

    em_fila = _fila(fila, data_do_atendimento)
    esperas = [p["espera_no_destino_min"] for p in passageiros]
    km = 2 * max(haversine_km(garagem, a.coordenada_destino)
                 for a in embarcados)
    pessoas = sum(a.vagas for a in embarcados)
    diaria = ajuda_de_custo if ajuda_de_custo is not None \
        else veiculo.ajuda_de_custo

    return {
        "data": data_do_atendimento,
        "veiculo": {"id": veiculo.id, "nome": veiculo.nome,
                    "lugares": veiculo.lugares},
        "cidade_destino": embarcados[0].cidade_destino,
        "saida": _hhmm(saida), "saida_min": saida,
        "retorno_previsto": _hhmm(retorno), "retorno_min": retorno,
        "duracao_total_min": retorno - saida,
        "ocupacao": {"vagas_usadas": vagas_usadas,
                     "lugares": veiculo.lugares,
                     "ocupacao_pct": round(100 * vagas_usadas / veiculo.lugares, 1),
                     "pacientes": len(embarcados),
                     "acompanhantes": sum(1 for a in embarcados
                                          if a.acompanhante),
                     "cadeirantes": cadeiras_usadas},
        "espera": {
            "media_min": round(sum(esperas) / len(esperas), 1),
            "maxima_min": max(esperas),
            "acima_do_aceitavel": sum(1 for e in esperas
                                      if e > ESPERA_ACEITAVEL_MIN),
            "limite_min": ESPERA_ACEITAVEL_MIN,
        },
        "passageiros": passageiros,
        "fila": em_fila,
        "custos": {
            "km": round(km, 1),
            "custo_rodagem": round(km * veiculo.custo_km, 2),
            "ajuda_de_custo_unitaria": diaria,
            "pessoas_com_ajuda": pessoas,
            "ajuda_de_custo_total": round(pessoas * diaria, 2),
            "total": round(km * veiculo.custo_km + pessoas * diaria, 2),
        },
        "alertas": _alertas(passageiros, em_fila, retorno, saida),
    }


def _viagem_vazia(data, veiculo, fila) -> dict:
    return {
        "data": data,
        "veiculo": {"id": veiculo.id, "nome": veiculo.nome,
                    "lugares": veiculo.lugares},
        "ocupacao": {"vagas_usadas": 0, "lugares": veiculo.lugares,
                     "ocupacao_pct": 0.0, "pacientes": 0,
                     "acompanhantes": 0, "cadeirantes": 0},
        "passageiros": [], "fila": _fila(fila, data),
        "espera": {}, "custos": {},
        "alertas": ["Nenhuma autorização para esta data."],
    }


def _fila(fila: list, data: str) -> list:
    """Quem não coube — com posição e o motivo, nunca só ausente."""
    saida = []
    for posicao, a in enumerate(fila, start=1):
        saida.append({
            "posicao": posicao, "autorizacao": a.id, "paciente": a.paciente_id,
            "unidade": a.unidade_destino, "especialidade": a.especialidade,
            "prioridade": a.prioridade,
            "autorizada_em": a.autorizada_em,
            "vagas_necessarias": a.vagas,
            "cadeirante": a.cadeirante,
            "motivo": ("Não havia posição de cadeira de rodas livre no veículo."
                       if a.cadeirante else
                       "O veículo do dia lotou antes desta autorização na fila."),
            "o_que_fazer": ("Precisa de veículo acessível: ou entra um segundo "
                            "carro, ou o atendimento é remarcado com o "
                            "hospital." if a.cadeirante else
                            "Remarcar com o hospital ou abrir segunda viagem. "
                            "A posição na fila é pela data da autorização."),
        })
    return saida


def _alertas(passageiros, fila, retorno, saida) -> list:
    alertas = []
    demais = [p for p in passageiros if p["espera_demais"]]
    if demais:
        pior = max(p["espera_no_destino_min"] for p in demais)
        alertas.append(
            f"{len(demais)} pessoas esperam mais de "
            f"{ESPERA_ACEITAVEL_MIN // 60} h no destino — a pior espera é de "
            f"{pior // 60} h{pior % 60:02d}. Ninguém mede isso hoje, e é o que "
            f"faz o paciente desistir do tratamento. Dois retornos, um no meio "
            f"do dia e outro no fim, resolvem a maior parte.")
    if retorno - saida > 14 * 60:
        alertas.append(
            f"A viagem inteira leva {(retorno - saida) // 60} h. Confira a "
            f"jornada do motorista antes de confirmar: acima de 14 h de "
            f"amplitude a escala não fecha na Lei 13.103.")
    if fila:
        vitais = [f for f in fila if f["prioridade"] == "vital"]
        if vitais:
            alertas.append(
                f"{len(vitais)} pessoas de tratamento que não pode faltar "
                f"ficaram fora por falta de vaga. Não são remarcáveis.")
    return alertas


def _hhmm(minutos: int) -> str:
    minutos = int(minutos) % (24 * 60)
    return f"{minutos // 60:02d}h{minutos % 60:02d}"


def dividir_retorno(viagem: dict) -> dict:
    """A conta do segundo retorno: quem volta cedo e quanta espera some.

    Não decide nada — mostra o efeito. Quem decide é quem paga o segundo
    veículo, e precisa ver o tamanho do ganho antes.
    """
    passageiros = viagem.get("passageiros") or []
    if len(passageiros) < 2:
        return {}
    liberacoes = sorted(_minutos(p["liberado_previsto"]) for p in passageiros)
    meio = liberacoes[len(liberacoes) // 2]

    cedo = [p for p in passageiros if _minutos(p["liberado_previsto"]) <= meio]
    tarde = [p for p in passageiros if _minutos(p["liberado_previsto"]) > meio]
    if not cedo or not tarde:
        return {}

    fim_cedo = max(_minutos(p["liberado_previsto"]) for p in cedo)
    fim_tarde = max(_minutos(p["liberado_previsto"]) for p in tarde)
    espera_nova = ([fim_cedo - _minutos(p["liberado_previsto"]) for p in cedo]
                   + [fim_tarde - _minutos(p["liberado_previsto"])
                      for p in tarde])
    antes = viagem["espera"]["media_min"]
    depois = round(sum(espera_nova) / len(espera_nova), 1)

    return {
        "primeiro_retorno": _hhmm(fim_cedo), "pessoas_no_primeiro": len(cedo),
        "segundo_retorno": _hhmm(fim_tarde), "pessoas_no_segundo": len(tarde),
        "espera_media_antes_min": antes,
        "espera_media_depois_min": depois,
        "horas_de_espera_poupadas": round(
            (antes - depois) * len(passageiros) / 60, 1),
        "custo": "uma segunda viagem de ida e volta do veículo, ou um "
                 "segundo carro no mesmo dia",
    }


def _minutos(hhmm: str) -> int:
    horas, minutos = hhmm.split("h")
    return int(horas) * 60 + int(minutos)
