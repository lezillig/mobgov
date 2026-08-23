# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 13 · agent-saude
O dia do transporte sanitário: da agenda de tratamentos às rotas.

Reaproveita o motor do porta a porta (`motor/porta_a_porta.py`), que é um
PDPTW: n embarques e n desembarques, com janela e tempo máximo a bordo. O
transporte de paciente é exatamente esse problema — o que muda é de onde vem
a demanda e o que acontece quando ela não cabe.

E é aí que este módulo faz o que o escolar não precisa fazer: **separar o que
ficou de fora por prioridade clínica**. Uma consulta de rotina que não coube
é remarcada com um telefonema. Uma hemodiálise que não coube é uma
internação na quinta-feira. Os dois não podem sair na mesma linha de
relatório, e nenhum dos dois pode sumir em silêncio.

    python -m saude.rodar
    python -m saude.rodar --dia 2 --veiculos 6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor import porta_a_porta  # noqa: E402
from saude import demanda as demanda_mod  # noqa: E402
from saude import acompanhamento as acompanhamento_mod  # noqa: E402
from saude import tfd as tfd_mod  # noqa: E402
from saude.tratamento import PRIORIDADES, pedidos_do_dia  # noqa: E402

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")
SAIDA_PADRAO = os.path.join(DIR_RELATORIOS, "saude.json")

DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


def _por_prioridade(pedidos: list) -> dict:
    contagem = {}
    for p in pedidos:
        contagem[p.prioridade] = contagem.get(p.prioridade, 0) + 1
    return contagem


def _nao_atendidos(pedidos: list, rotas: list) -> list:
    """Quem ficou de fora — com o que fazer a respeito de cada um.

    O motor resolve com a frota que recebeu. Se a frota não dá, alguém fica
    sem viagem, e a única resposta errada é não dizer quem.
    """
    atendidos = {e.get("usuario") for r in rotas for e in r.get("eventos", [])}
    fora = [p for p in pedidos if p.id not in atendidos]
    saida = []
    for p in sorted(fora, key=lambda x: (x.prioridade != "vital",
                                         x.prioridade != "continuado")):
        regra = PRIORIDADES[p.prioridade]
        saida.append({
            "pedido": p.id, "paciente": p.paciente_id,
            "tratamento": p.tipo_tratamento, "sentido": p.sentido,
            "prioridade": p.prioridade,
            "rotulo": regra["rotulo"],
            "remarcavel": regra["remarcavel"],
            "o_que_fazer": ("Sem alternativa: precisa de veículo hoje. "
                            "Faltar significa internação."
                            if not regra["remarcavel"] else
                            "Dá para remarcar com aviso ao paciente, ou "
                            "encaixar em outro horário do mesmo dia."),
            "distrito": p.distrito,
        })
    return saida


def rodar(dia_da_semana: int = 0, veiculos_por_tipo: int = None,
          tempo_limite_s: int = 20, semente: int = demanda_mod.SEMENTE) -> dict:
    """Monta e resolve o dia. Devolve o relatório inteiro."""
    tratamentos = demanda_mod.gerar_tratamentos(semente)
    unidades = demanda_mod.unidades_por_id()
    agenda = pedidos_do_dia(tratamentos, dia_da_semana, unidades)

    planejaveis = agenda["ida"] + agenda["volta_planejada"]

    # Maca não compartilha veículo com ninguém: é remoção em ambulância de
    # transporte, viagem dedicada. Jogar as duas demandas no mesmo solver
    # produziria uma van de oito lugares levando duas macas — que não existe
    # na rua, por mais que caiba na conta de assentos.
    comuns = [p for p in planejaveis if not p.maca]
    de_maca = [p for p in planejaveis if p.maca]

    resultado = _resolver(
        comuns, [t for t in demanda_mod.TIPOS_SAUDE if t.id != "AMBTRANS"],
        tempo_limite_s, veiculos_por_tipo)
    remocoes = _resolver(
        de_maca, [t for t in demanda_mod.TIPOS_SAUDE if t.id == "AMBTRANS"],
        tempo_limite_s, veiculos_por_tipo)
    resultado = _juntar(resultado, remocoes)

    fora = _nao_atendidos(planejaveis, resultado.get("rotas", []))
    vitais_fora = [f for f in fora if not f["remarcavel"]]

    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "origem": "simulacao",
        "explicacao_selo": "pacientes sintéticos — nenhum dado clínico, "
                           "nenhuma pessoa real",
        "dia_da_semana": DIAS[dia_da_semana],
        "tratamentos_ativos": len(tratamentos),
        "agenda": agenda["resumo"],
        "frota": {
            "total_veiculos": resultado.get("total_veiculos", 0),
            "composicao": resultado.get("composicao", {}),
            "km_dia": resultado.get("km_dia", 0.0),
        },
        "indicadores": resultado.get("indicadores", {}),
        "remocoes_de_maca": resultado.get("remocoes_de_maca", {}),
        "rotas": [_rota_resumida(r) for r in resultado.get("rotas", [])],
        "nao_atendidos": fora,
        "alertas": _alertas(vitais_fora, agenda),
        "tfd": _tfd(),
        # a contrapartida do botão do paciente: sem esta fila o aviso não
        # vira nada
        "fila_de_retorno": acompanhamento_mod.fila_de_retorno(
            tratamentos=tratamentos),
        "unidades": demanda_mod.nomes_das_unidades(),
        "prioridades": {k: dict(v, id=k) for k, v in PRIORIDADES.items()},
    }


def _tfd(data: str = "2026-08-24") -> dict:
    """A viagem intermunicipal do dia, com a espera de cada um no destino."""
    autorizacoes = demanda_mod.gerar_autorizacoes_tfd(data)
    veiculo = tfd_mod.VeiculoTFD("TFD1", "Van TFD 15 lugares", 15,
                                 posicoes_cadeirante=2)
    viagem = tfd_mod.montar_viagem(autorizacoes, data, veiculo,
                                   demanda_mod.GARAGEM)
    viagem["se_dividir_o_retorno"] = tfd_mod.dividir_retorno(viagem)
    viagem["autorizacoes_no_dia"] = len(autorizacoes)
    return viagem


def _resolver(pedidos, tipos, tempo_limite_s, veiculos_por_tipo) -> dict:
    if not pedidos:
        return {"rotas": [], "composicao": {}, "total_veiculos": 0,
                "km_dia": 0.0, "indicadores": {}}
    return porta_a_porta.resolver(
        pedidos, tipos=tipos,
        partida_min=min(p.janela_chegada[0] for p in pedidos) - 60,
        tempo_limite_s=tempo_limite_s,
        veiculos_por_tipo=veiculos_por_tipo,
        # o dia da saúde é mais longo que o escolar: a hemodiálise do turno
        # das 16 h só volta para casa às 20 h
        horizonte_min=_fim_do_dia(pedidos),
        espera_maxima_min=45)


def _juntar(a: dict, b: dict) -> dict:
    """As duas operações somam frota e km; os indicadores ficam com a maior."""
    composicao = dict(a.get("composicao", {}))
    for tipo, quantos in (b.get("composicao") or {}).items():
        composicao[tipo] = composicao.get(tipo, 0) + quantos
    return {
        "rotas": (a.get("rotas") or []) + (b.get("rotas") or []),
        "composicao": composicao,
        "total_veiculos": a.get("total_veiculos", 0) + b.get("total_veiculos", 0),
        "km_dia": round(a.get("km_dia", 0.0) + b.get("km_dia", 0.0), 1),
        "indicadores": a.get("indicadores") or b.get("indicadores") or {},
        "remocoes_de_maca": {
            "viagens": len(b.get("rotas") or []),
            "veiculos": b.get("total_veiculos", 0),
            "km_dia": b.get("km_dia", 0.0),
        },
    }


def _fim_do_dia(pedidos: list) -> int:
    """Até que horas o relógio precisa ir — com folga para o último retorno."""
    ultimo = max((p.janela_chegada[1] for p in pedidos), default=16 * 60)
    return min(24 * 60, ultimo + 90)


def _rota_resumida(rota: dict) -> dict:
    return {
        "id": rota.get("id"), "tipo": rota.get("tipo_nome"),
        "km": rota.get("km"), "min": rota.get("min"),
        "usuarios": rota.get("usuarios"),
        "ocupacao_maxima": rota.get("ocupacao_maxima"),
        "ocupacao_maxima_pct": rota.get("ocupacao_maxima_pct"),
    }


def _alertas(vitais_fora: list, agenda: dict) -> list:
    alertas = []
    if vitais_fora:
        alertas.append(
            f"{len(vitais_fora)} viagens de tratamento que não pode faltar "
            f"ficaram sem veículo. Não são remarcáveis: ou entra frota, ou "
            f"alguém precisa decidir hoje, com nome e hora.")
    por_chamada = agenda["resumo"]["voltas_por_chamada"]
    if por_chamada:
        alertas.append(
            f"{por_chamada} voltas não têm hora — consulta e quimioterapia "
            f"terminam quando o médico libera. Elas NÃO estão no plano da "
            f"manhã de propósito: entram pela reotimização quando o paciente "
            f"avisa. Reserve folga de frota para a tarde.")
    return alertas


def gravar(relatorio: dict, saida: str = SAIDA_PADRAO) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    return saida


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dia do transporte sanitário")
    ap.add_argument("--dia", type=int, default=0,
                    help="0 = segunda … 4 = sexta")
    ap.add_argument("--veiculos", type=int, default=None,
                    help="veículos por tipo disponíveis")
    ap.add_argument("--tempo-limite", type=int, default=20)
    ap.add_argument("--saida", default=SAIDA_PADRAO)
    a = ap.parse_args(argv)

    relatorio = rodar(a.dia, a.veiculos, a.tempo_limite)
    caminho = gravar(relatorio, a.saida)

    ag, fr = relatorio["agenda"], relatorio["frota"]
    print(f"Transporte sanitário — {relatorio['dia_da_semana']}")
    print(f"  {relatorio['tratamentos_ativos']} tratamentos ativos; "
          f"{ag['pedidos_planejaveis']} viagens planejáveis hoje "
          f"({ag['idas']} idas + {ag['voltas_planejadas']} voltas)")
    print(f"  por prioridade: " + ", ".join(
        f"{v} {k}" for k, v in sorted(ag["por_prioridade"].items())))
    print(f"  maca: {ag['com_maca']} | cadeira: {ag['cadeirantes']} | "
          f"acompanhante: {ag['com_acompanhante']} | jejum: {ag['em_jejum']}")
    print(f"  frota: {fr['total_veiculos']} veículos, {fr['km_dia']} km/dia "
          f"{fr['composicao']}")
    if relatorio["nao_atendidos"]:
        print(f"  não atendidos: {len(relatorio['nao_atendidos'])}")
    for alerta in relatorio["alertas"]:
        print(f"  ! {alerta}")
    print(f"Relatório em {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
