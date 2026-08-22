# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 9 · agent-dados
Perfil de operação: o que muda entre transporte escolar e fretamento.

O motor é o mesmo. O que muda é a moldura, e ela estava presa no código do
Município Modelo: dois turnos fixos, destino chamado "escola", custo do
motorista embutido no custo do veículo. Nenhuma dessas três coisas serve para
uma empresa de fretamento.

    Escolar (prefeitura)            Fretamento (empresa)
    ----------------------------    ------------------------------------
    2 turnos, sinal fixo            3 ou 4 turnos, virada quebrada
    destino = escola                destino = planta, unidade, obra
    "antes" = frota do PNATE        "antes" = contrato vigente
    custo do motorista no veículo   MOTORISTA É O CUSTO, e tem lei própria

A última linha é a que muda o resultado. No escolar, um veículo faz manhã e
tarde e ninguém pergunta quem dirige. No fretamento com três turnos, o mesmo
veículo roda o dia inteiro e o motorista não pode: quantos motoristas a
operação exige é uma conta separada da frota — e é a que decide o preço da
proposta. Ver `motor/jornada.py`.

Os perfis são dados, não código: `carregar()` lê um JSON e devolve o mesmo
objeto que os perfis embutidos, para o cliente configurar os turnos dele sem
mexer no sistema.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.municipio_modelo import (  # noqa: E402
    ESCOLAS, TIPOS_VEICULO, TURNOS, Escola, TipoVeiculo, Turno,
)


@dataclass
class RegrasDeJornada:
    """Parâmetros da jornada do motorista — declarados, não escondidos.

    Os valores padrão seguem a Lei 13.103/2015 e a CLT no que ela remete, mas
    acordo coletivo muda quase todos eles. Por isso são parâmetros do perfil e
    aparecem no relatório: quem assina a escala precisa poder conferir com o
    jurídico da empresa, e não descobrir depois que o sistema supôs outra
    coisa.
    """
    jornada_normal_min: int = 480          # 8 h
    hora_extra_max_min: int = 120          # + 2 h (4 h só com acordo)
    direcao_continua_max_min: int = 330    # 5 h30 ao volante
    parada_obrigatoria_min: int = 30       # depois das 5 h30
    intervalo_refeicao_min: int = 60       # jornada acima de 6 h
    interjornada_min: int = 660            # 11 h entre uma jornada e outra
    amplitude_max_min: int = 840           # 14 h entre a 1ª e a última hora
    permite_dupla_pegada: bool = True      # pega de manhã, larga, volta à tarde
    tempo_troca_veiculo_min: int = 15      # trocar de carro entre blocos

    def como_dicionario(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Contraparte:
    """Quem está do outro lado do contrato daquele destino.

    É a mesma relação vista dos dois lados, por isso é um campo só:

        escolar      quem usa é a PREFEITURA, que contrata — a contraparte é o
                     FORNECEDOR que opera o lote (a viação vencedora);
        fretamento   quem usa é a TRANSPORTADORA, que é contratada — a
                     contraparte é o CLIENTE dono da planta.

    O vínculo é pelo destino porque é assim que os dois contratos são
    escritos: lote de escolas no edital da prefeitura, planta (ou conjunto de
    plantas) no contrato de fretamento. Um veículo pode servir contrapartes
    diferentes ao longo do dia — por isso a atribuição é da viagem, nunca do
    veículo.
    """
    id: str
    nome: str
    destinos: list                         # ids de destino sob este contrato


@dataclass
class Perfil:
    """Uma operação inteira descrita como dado."""
    id: str
    nome: str
    vertical: str                          # "escolar" | "fretamento"
    turnos: list
    destinos: list                         # escolas, plantas, unidades
    tipos_veiculo: list
    rotulo_passageiro: str = "aluno"
    rotulo_passageiro_plural: str = "alunos"
    rotulo_destino: str = "escola"
    rotulo_destino_plural: str = "escolas"
    rotulo_contraparte: str = "fornecedor"
    rotulo_contraparte_plural: str = "fornecedores"
    contrapartes: list = field(default_factory=list)
    # Tempo máximo do passageiro dentro do veículo. São dois números porque
    # são duas promessas diferentes: na rota coletiva a secretaria fixa um
    # teto igual para todo mundo; no porta a porta o teto é relativo ao
    # trajeto direto de cada um — 20 min de casa até a escola não pode virar
    # 75 min só porque o limite geral permite.
    tempo_max_trajeto_min: int = 75
    fator_tempo_bordo: float = 1.6          # porta a porta: × o trajeto direto
    folga_tempo_bordo_min: int = 15         # porta a porta: + folga fixa
    embarque_comum_min: int = 2
    embarque_cadeirante_min: int = 5
    dias_operacao_mes: int = 22
    custo_motorista_mes: float = 0.0       # 0 = já embutido no custo do veículo
    regras_jornada: RegrasDeJornada = field(default_factory=RegrasDeJornada)

    @property
    def separa_custo_do_motorista(self) -> bool:
        return self.custo_motorista_mes > 0

    def turno_por_id(self, ident: str):
        return next((t for t in self.turnos if t.id == ident), None)

    def contraparte_do_destino(self, destino_id: str):
        """Quem responde pelo destino — None quando o contrato não foi
        declarado, e aí a tela simplesmente não oferece o filtro."""
        return next((c for c in self.contrapartes
                     if destino_id in c.destinos), None)

    def como_dicionario(self) -> dict:
        return {
            "id": self.id, "nome": self.nome, "vertical": self.vertical,
            "rotulo_passageiro": self.rotulo_passageiro,
            "rotulo_passageiro_plural": self.rotulo_passageiro_plural,
            "rotulo_destino": self.rotulo_destino,
            "rotulo_destino_plural": self.rotulo_destino_plural,
            "rotulo_contraparte": self.rotulo_contraparte,
            "rotulo_contraparte_plural": self.rotulo_contraparte_plural,
            "contrapartes": [{"id": c.id, "nome": c.nome,
                              "destinos": list(c.destinos)}
                             for c in self.contrapartes],
            "tempo_max_trajeto_min": self.tempo_max_trajeto_min,
            "fator_tempo_bordo": self.fator_tempo_bordo,
            "folga_tempo_bordo_min": self.folga_tempo_bordo_min,
            "embarque_comum_min": self.embarque_comum_min,
            "embarque_cadeirante_min": self.embarque_cadeirante_min,
            "dias_operacao_mes": self.dias_operacao_mes,
            "custo_motorista_mes": self.custo_motorista_mes,
            "turnos": [{"id": t.id, "nome": t.nome,
                        "janela_chegada": list(t.janela_chegada),
                        "jornada_max_min": t.jornada_max_min,
                        "duracao_min": t.duracao_min}
                       for t in self.turnos],
            "destinos": [{"id": d.id, "nome": d.nome, "lat": d.lat,
                          "lon": d.lon} for d in self.destinos],
            "tipos_veiculo": [{"id": t.id, "nome": t.nome,
                               "capacidade": t.capacidade,
                               "posicoes_cadeirante": t.posicoes_cadeirante,
                               "custo_km": t.custo_km,
                               "custo_fixo_mes": t.custo_fixo_mes,
                               "consumo_km_l": t.consumo_km_l}
                              for t in self.tipos_veiculo],
            "regras_jornada": self.regras_jornada.como_dicionario(),
        }


# ------------------------------------------------------------------ escolar ---
# Lotes do edital: é assim que a prefeitura divide o contrato — por região,
# cada lote com uma empresa vencedora. Nomes fictícios, como todo o Município
# Modelo. Numa prefeitura real isso vem do resultado da licitação.
FORNECEDORES = [
    Contraparte("F1", "Viação São Cristóvão", ["E1", "EMEF Centro"]),
    Contraparte("F2", "Trans Norte Transportes", ["E2", "EMEF Distrito Norte"]),
    Contraparte("F3", "Rota Rural Ltda.", ["E3", "EMEF Vila Rural Sul"]),
]

PERFIL_ESCOLAR = Perfil(
    id="escolar", nome="Transporte escolar municipal", vertical="escolar",
    turnos=TURNOS, destinos=ESCOLAS, tipos_veiculo=TIPOS_VEICULO,
    rotulo_passageiro="aluno", rotulo_passageiro_plural="alunos",
    rotulo_destino="escola", rotulo_destino_plural="escolas",
    # a prefeitura contrata: do outro lado está o fornecedor do lote
    rotulo_contraparte="fornecedor", rotulo_contraparte_plural="fornecedores",
    contrapartes=FORNECEDORES,
    tempo_max_trajeto_min=75, dias_operacao_mes=22,
    # no escolar o custo do motorista já vem dentro do custo fixo do veículo,
    # que é como a prefeitura contrata (veículo com motorista)
    custo_motorista_mes=0.0,
)


# --------------------------------------------------------------- fretamento ---
# Turnos de indústria: a virada quebrada é o normal, não a exceção. T1 entra às
# 6h, T2 às 14h20, T3 às 22h, e o administrativo às 8h — quatro janelas de
# chegada diferentes, contra as duas fixas do escolar.
TURNOS_FRETAMENTO = [
    Turno("t1", "1º turno (06h)", (6 * 60, 6 * 60 + 10), 120, 8 * 60),
    Turno("adm", "Administrativo (08h)", (8 * 60, 8 * 60 + 10), 120, 9 * 60),
    Turno("t2", "2º turno (14h20)", (14 * 60 + 20, 14 * 60 + 30), 120, 8 * 60),
    Turno("t3", "3º turno (22h)", (22 * 60, 22 * 60 + 10), 120, 8 * 60),
]

# Frota de fretamento: ônibus rodoviário, micro executivo e van. O custo fixo
# aqui é SÓ do veículo (depreciação, seguro, licenciamento, manutenção
# programada) — o motorista é contado à parte, por cabeça.
TIPOS_FRETAMENTO = [
    TipoVeiculo("RODO46", "Ônibus rodoviário 46 lugares", 46, 0, 3.40, 9800.0, 2.9),
    TipoVeiculo("EXEC28", "Micro-ônibus executivo 28 lugares", 28, 0, 2.60, 7200.0, 4.2),
    TipoVeiculo("VAN16", "Van executiva 16 lugares", 16, 0, 1.80, 4900.0, 8.5),
    TipoVeiculo("VANPCD", "Van acessível 12 lugares", 12, 2, 1.95, 5600.0, 7.8),
]

# Plantas atendidas pela transportadora — o equivalente às escolas.
PLANTAS = [
    Escola("PL1", "Planta 1 — Fábrica", -21.140, -47.790),
    Escola("PL2", "Planta 2 — Centro de distribuição", -21.205, -47.845),
    Escola("PL3", "Escritório administrativo", -21.158, -47.802),
]

# Quem usa o sistema aqui é a transportadora, e ela atende mais de um
# contratante — por isso a planta pertence a um cliente, e não o contrário.
# Nomes fictícios; numa operação real vêm do cadastro de clientes.
# O destino é listado por id E por nome de propósito: plano vindo de planilha
# renumera os destinos na ordem em que aparecem e só preserva o nome da
# coluna — o id do perfil não sobrevive à importação.
CLIENTES = [
    Contraparte("C1", "Indústria Modelo S.A.",
                ["PL1", "PL2", "Planta 1 — Fábrica",
                 "Planta 2 — Centro de distribuição"]),
    Contraparte("C2", "Modelo Serviços Ltda.",
                ["PL3", "Escritório administrativo"]),
]

PERFIL_FRETAMENTO = Perfil(
    id="fretamento", nome="Fretamento corporativo", vertical="fretamento",
    turnos=TURNOS_FRETAMENTO, destinos=PLANTAS, tipos_veiculo=TIPOS_FRETAMENTO,
    rotulo_passageiro="colaborador", rotulo_passageiro_plural="colaboradores",
    rotulo_destino="planta", rotulo_destino_plural="plantas",
    # a transportadora é contratada: do outro lado está o cliente
    rotulo_contraparte="cliente", rotulo_contraparte_plural="clientes",
    contrapartes=CLIENTES,
    # colaborador aceita trajeto maior que criança, e o contrato costuma
    # fixar 90 min como teto de porta a porta
    tempo_max_trajeto_min=90, dias_operacao_mes=22,
    custo_motorista_mes=7800.0,     # salário + encargos + benefícios
)

EMBUTIDOS = {p.id: p for p in (PERFIL_ESCOLAR, PERFIL_FRETAMENTO)}


# ----------------------------------------------------------------- arquivo ---
def de_dicionario(dados: dict) -> Perfil:
    """Perfil vindo de JSON — é assim que o cliente configura os turnos dele."""
    base = EMBUTIDOS.get(dados.get("base") or dados.get("vertical") or "escolar",
                         PERFIL_ESCOLAR)
    turnos = [Turno(t["id"], t["nome"], tuple(t["janela_chegada"]),
                    t.get("jornada_max_min", 120), t.get("duracao_min", 0))
              for t in dados.get("turnos", [])] or base.turnos
    destinos = [Escola(d["id"], d["nome"], d["lat"], d["lon"])
                for d in dados.get("destinos", [])] or base.destinos
    tipos = [TipoVeiculo(t["id"], t["nome"], t["capacidade"],
                         t.get("posicoes_cadeirante", 0), t["custo_km"],
                         t["custo_fixo_mes"], t["consumo_km_l"])
             for t in dados.get("tipos_veiculo", [])] or base.tipos_veiculo
    regras = RegrasDeJornada(**{k: v for k, v in
                                (dados.get("regras_jornada") or {}).items()
                                if k in RegrasDeJornada.__dataclass_fields__})
    # Contrato é dado do cliente: se ele declarar os lotes (ou a carteira de
    # clientes), vale o dele; senão fica sem, e a tela não oferece o filtro —
    # em vez de herdar contraparte de demonstração, que seria nome inventado
    # em cima de operação real.
    contrapartes = [Contraparte(c["id"], c["nome"], list(c.get("destinos", [])))
                    for c in dados.get("contrapartes", [])]
    if "contrapartes" not in dados and destinos is base.destinos:
        contrapartes = base.contrapartes
    return Perfil(
        id=dados.get("id", base.id), nome=dados.get("nome", base.nome),
        vertical=dados.get("vertical", base.vertical),
        turnos=turnos, destinos=destinos, tipos_veiculo=tipos,
        rotulo_passageiro=dados.get("rotulo_passageiro",
                                    base.rotulo_passageiro),
        rotulo_passageiro_plural=dados.get("rotulo_passageiro_plural",
                                           base.rotulo_passageiro_plural),
        rotulo_destino=dados.get("rotulo_destino", base.rotulo_destino),
        rotulo_destino_plural=dados.get("rotulo_destino_plural",
                                        base.rotulo_destino_plural),
        rotulo_contraparte=dados.get("rotulo_contraparte",
                                     base.rotulo_contraparte),
        rotulo_contraparte_plural=dados.get("rotulo_contraparte_plural",
                                            base.rotulo_contraparte_plural),
        contrapartes=contrapartes,
        tempo_max_trajeto_min=dados.get("tempo_max_trajeto_min",
                                        base.tempo_max_trajeto_min),
        fator_tempo_bordo=dados.get("fator_tempo_bordo",
                                    base.fator_tempo_bordo),
        folga_tempo_bordo_min=dados.get("folga_tempo_bordo_min",
                                        base.folga_tempo_bordo_min),
        embarque_comum_min=dados.get("embarque_comum_min",
                                     base.embarque_comum_min),
        embarque_cadeirante_min=dados.get("embarque_cadeirante_min",
                                          base.embarque_cadeirante_min),
        dias_operacao_mes=dados.get("dias_operacao_mes",
                                    base.dias_operacao_mes),
        custo_motorista_mes=dados.get("custo_motorista_mes",
                                      base.custo_motorista_mes),
        regras_jornada=regras if dados.get("regras_jornada")
        else base.regras_jornada)


def carregar(caminho_ou_id: str) -> Perfil:
    """Aceita 'escolar', 'fretamento' ou o caminho de um JSON de perfil."""
    if caminho_ou_id in EMBUTIDOS:
        return EMBUTIDOS[caminho_ou_id]
    if os.path.exists(caminho_ou_id):
        with open(caminho_ou_id, encoding="utf-8") as f:
            return de_dicionario(json.load(f))
    raise ValueError(
        f"Perfil desconhecido: {caminho_ou_id}. Use um de "
        f"{', '.join(sorted(EMBUTIDOS))} ou o caminho de um arquivo .json.")


def gravar_modelo(caminho: str, base: str = "fretamento") -> str:
    """Escreve um JSON de exemplo para o cliente editar os turnos dele."""
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(EMBUTIDOS[base].como_dicionario(), f, ensure_ascii=False,
                  indent=2)
    return caminho


if __name__ == "__main__":
    for perfil in EMBUTIDOS.values():
        print(f"{perfil.id}: {perfil.nome} — {len(perfil.turnos)} turnos, "
              f"{len(perfil.destinos)} {perfil.rotulo_destino}s, "
              f"{len(perfil.tipos_veiculo)} tipos de veículo, "
              f"motorista a R$ {perfil.custo_motorista_mes:,.0f}/mês")
