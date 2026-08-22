# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 2 · agent-painel
Camada de cálculo do PAINEL DE ECONOMIA (a tela da demo).

Princípio inegociável nº 1 do projeto: "economia comprovável — nada de números
mágicos". Por isso este módulo NÃO copia os totais já gravados pelo motor de
dimensionamento: ele recalcula tudo a partir da composição de frota, do km
rodado e das premissas, e devolve junto a MEMÓRIA DE CÁLCULO (fórmula, valores
de entrada e resultado de cada passo) que vai impressa no PDF de prestação de
contas.

Diferença em relação à Sprint 1: o custo por km deixa de ser uma constante e
passa a ser decomposto em combustível + manutenção,

    custo_km(tipo, diesel) = manutencao_km(tipo) + diesel / consumo_km_l(tipo)
    manutencao_km(tipo)    = custo_km_base(tipo) - diesel_base / consumo_km_l(tipo)

de modo que simular o preço do diesel muda o resultado de verdade. Com
diesel = diesel_base a decomposição reproduz exatamente o custo_km da Sprint 1
(ver testes/test_economia.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

RELATORIO_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "dimensionamento.json",
)

MESES_POR_ANO = 12


# --------------------------------------------------------------- premissas ---
@dataclass(frozen=True)
class Premissas:
    """Premissas auditáveis do cálculo. Todas aparecem no relatório em PDF."""
    preco_diesel_l: float
    dias_letivos_mes: int
    viagens_por_rota: int        # coleta de manhã + dispersão no fim do turno
    fator_co2_kg_l: float
    tempo_max_trajeto_min: int
    tempo_virada_min: int        # manobra entre duas viagens do mesmo veículo
    preco_diesel_base_l: float   # preço usado quando o motor calibrou custo_km
    fonte_tempos: str

    def substituir(self, **campos) -> "Premissas":
        base = asdict(self)
        base.update({k: v for k, v in campos.items() if v is not None})
        return Premissas(**base)


RELATORIO_PCD = os.path.join(
    os.path.dirname(RELATORIO_PADRAO), "porta_a_porta.json")
RELATORIO_REOTIMIZACAO = os.path.join(
    os.path.dirname(RELATORIO_PADRAO), "reotimizacao.json")
RELATORIO_IMPORTACAO = os.path.join(
    os.path.dirname(RELATORIO_PADRAO), "importacao.json")
RELATORIO_ELEGIBILIDADE = os.path.join(
    os.path.dirname(RELATORIO_PADRAO), "elegibilidade.json")
RELATORIO_RODADAS = os.path.join(
    os.path.dirname(RELATORIO_PADRAO), "rodadas.json")


def carregar_relatorio(caminho: str = RELATORIO_PADRAO) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_opcional(caminho: str) -> dict:
    """Relatórios que podem não existir ainda (porta a porta, reotimização).

    O painel do escolar tem que abrir mesmo sem eles — o município que só
    contratou o vertical escolar não vê seções vazias.
    """
    if not os.path.exists(caminho):
        return {}
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def premissas_do_relatorio(rel: dict) -> Premissas:
    p = rel["premissas"]
    return Premissas(
        preco_diesel_l=float(p["preco_diesel_l"]),
        dias_letivos_mes=int(p["dias_letivos_mes"]),
        viagens_por_rota=int(p["viagens_por_rota"]),
        fator_co2_kg_l=float(p.get("fator_co2_kg_l", 2.68)),
        tempo_max_trajeto_min=int(p["tempo_max_trajeto_min"]),
        tempo_virada_min=int(p.get("tempo_virada_min", 0)),
        preco_diesel_base_l=float(p["preco_diesel_l"]),
        fonte_tempos=p.get("fonte_tempos", "não informada"),
    )


# ------------------------------------------------------------ custo por km ---
def manutencao_km(tipo: dict, preco_diesel_base: float) -> float:
    """Parcela de manutenção/pneus/lubrificantes embutida no custo_km original."""
    combustivel = preco_diesel_base / float(tipo["consumo_km_l"])
    return max(0.0, float(tipo["custo_km"]) - combustivel)


def custo_km(tipo: dict, premissas: Premissas) -> float:
    return (manutencao_km(tipo, premissas.preco_diesel_base_l)
            + premissas.preco_diesel_l / float(tipo["consumo_km_l"]))


# ------------------------------------------------------- avaliação de frota ---
def _km_por_tipo_dos_veiculos(veiculos: list, viagens_por_rota: int) -> dict:
    """Frota otimizada: cada veículo tem a jornada dele (as viagens do turno
    mais o deslocamento entre elas), então cada tipo carrega exatamente o km
    que roda — mais fiel que ratear pela quantidade de veículos.

    Um mesmo veículo físico aparece uma vez por turno; somar os turnos dá o
    km do dia. O fator viagens_por_rota cobre a dispersão no fim do turno,
    espelhada da coleta.
    """
    km = {}
    for v in veiculos:
        km[v["tipo"]] = km.get(v["tipo"], 0.0) + float(v["km_turno"]) * viagens_por_rota
    return km


def _km_rateado(composicao: dict, km_dia_total: float) -> dict:
    """Frota atual: a prefeitura só declara o km/dia global, então rateamos
    proporcionalmente à quantidade de veículos de cada tipo."""
    total = sum(composicao.values())
    if total == 0:
        return {}
    return {t: km_dia_total * q / total for t, q in composicao.items()}


def avaliar_frota(rotulo: str, composicao: dict, km_dia_por_tipo: dict,
                  tipos: dict, premissas: Premissas) -> dict:
    """Custo, consumo e emissões de uma composição de frota, tipo a tipo."""
    linhas = []
    for tipo_id, qtd in sorted(composicao.items(), key=lambda kv: -kv[1]):
        t = tipos[tipo_id]
        km_dia = float(km_dia_por_tipo.get(tipo_id, 0.0))
        ckm = custo_km(t, premissas)
        fixo = float(t["fixo_mes"]) * qtd
        variavel = km_dia * premissas.dias_letivos_mes * ckm
        litros = km_dia / float(t["consumo_km_l"])
        linhas.append({
            "tipo": tipo_id,
            "nome": t.get("nome", tipo_id),
            "qtd": qtd,
            "capacidade": int(t.get("capacidade", 0)),
            "assentos": int(t.get("capacidade", 0)) * qtd,
            "posicoes_cadeirante": int(t.get("posicoes_cadeirante", 0)) * qtd,
            "km_dia": round(km_dia, 1),
            "custo_km": round(ckm, 3),
            "custo_fixo_mes": round(fixo, 2),
            "custo_variavel_mes": round(variavel, 2),
            "custo_mes": round(fixo + variavel, 2),
            "litros_dia": round(litros, 1),
        })

    fixo = sum(l["custo_fixo_mes"] for l in linhas)
    variavel = sum(l["custo_variavel_mes"] for l in linhas)
    litros_dia = sum(l["litros_dia"] for l in linhas)
    km_dia = sum(l["km_dia"] for l in linhas)
    return {
        "rotulo": rotulo,
        "composicao": linhas,
        "total_veiculos": sum(composicao.values()),
        "assentos": sum(l["assentos"] for l in linhas),
        "posicoes_cadeirante": sum(l["posicoes_cadeirante"] for l in linhas),
        "km_dia": round(km_dia, 1),
        "km_mes": round(km_dia * premissas.dias_letivos_mes, 1),
        "custo_fixo_mes": round(fixo, 2),
        "custo_variavel_mes": round(variavel, 2),
        "custo_mes": round(fixo + variavel, 2),
        "custo_ano": round((fixo + variavel) * MESES_POR_ANO, 2),
        "litros_dia": round(litros_dia, 1),
        "litros_ano": round(
            litros_dia * premissas.dias_letivos_mes * MESES_POR_ANO, 1),
        "tco2_ano": round(
            litros_dia * premissas.dias_letivos_mes * MESES_POR_ANO
            * premissas.fator_co2_kg_l / 1000, 1),
    }


def _variacao_pct(antes: float, depois: float) -> float:
    if not antes:
        return 0.0
    return round(100 * (antes - depois) / antes, 1)


def comparar(atual: dict, otimizada: dict) -> dict:
    """Bloco 'antes vs depois' — os números da manchete da demo."""
    return {
        "veiculos": atual["total_veiculos"] - otimizada["total_veiculos"],
        "reducao_frota_pct": _variacao_pct(
            atual["total_veiculos"], otimizada["total_veiculos"]),
        "custo_mes": round(atual["custo_mes"] - otimizada["custo_mes"], 2),
        "custo_ano": round(atual["custo_ano"] - otimizada["custo_ano"], 2),
        "reducao_custo_pct": _variacao_pct(
            atual["custo_mes"], otimizada["custo_mes"]),
        "km_dia": round(atual["km_dia"] - otimizada["km_dia"], 1),
        "reducao_km_pct": _variacao_pct(atual["km_dia"], otimizada["km_dia"]),
        "litros_dia": round(atual["litros_dia"] - otimizada["litros_dia"], 1),
        "litros_ano": round(atual["litros_ano"] - otimizada["litros_ano"], 1),
        "tco2_ano": round(atual["tco2_ano"] - otimizada["tco2_ano"], 1),
    }


# --------------------------------------------------------------- qualidade ---
def qualidade_do_servico(rel: dict, otimizada: dict) -> dict:
    """Contrapeso honesto da economia: mostrar que cortar frota não piorou o
    serviço (ocupação, tempo dentro do limite legal, lugares sobrando e
    jornada dos veículos dentro do que cabe antes do sinal).

    Com multiviagem, o que atende o aluno não é o assento do veículo e sim o
    LUGAR-VIAGEM: um ônibus de 31 lugares que faz 3 viagens oferece 93 lugares
    naquele turno.
    """
    viagens = rel["frota_otimizada"]["viagens"]
    veiculos = rel["frota_otimizada"]["veiculos"]
    tipos = rel["premissas"]["custos_por_tipo"]
    ocupacoes = [v["ocupacao_pct"] for v in viagens]
    tempos = [v["min_viagem"] for v in viagens]

    por_turno = []
    for t in rel["demanda"]["turnos"]:
        vgs = [v for v in viagens if v["turno"] == t["id"]]
        vcs = [v for v in veiculos if v["turno"] == t["id"]]
        if not vcs:
            continue
        lugares = sum(v["capacidade"] * len(v["viagens"]) for v in vcs)
        alunos_turno = rel["demanda"]["alunos_por_turno"][t["id"]]
        jornadas = [v["min_turno"] for v in vcs]
        por_turno.append({
            "turno": t["nome"],
            "alunos": alunos_turno,
            "viagens": len(vgs),
            "veiculos": len(vcs),
            "viagens_por_veiculo": round(len(vgs) / len(vcs), 2),
            "lugares_ofertados": lugares,
            "lugares_folga": lugares - alunos_turno,
            "jornada_limite_min": t["jornada_max_min"],
            "jornada_media_min": round(sum(jornadas) / len(jornadas), 1),
            "jornada_max_min": max(jornadas),
        })

    # toda viagem com cadeirante precisa ter caído em veículo acessível
    cadeirantes_ok = all(
        v["cadeirantes"] <= int(tipos[v["tipo"]].get("posicoes_cadeirante", 0))
        for v in viagens
    )
    return {
        "viagens": len(viagens),
        "viagens_por_veiculo_turno": rel["frota_otimizada"].get(
            "viagens_por_veiculo_turno"),
        "viagens_por_veiculo_atual": rel["frota_atual"].get(
            "viagens_por_veiculo_turno"),
        "ocupacao_media_pct": round(sum(ocupacoes) / len(ocupacoes), 1),
        "ocupacao_min_pct": min(ocupacoes),
        "ocupacao_max_pct": max(ocupacoes),
        "tempo_medio_viagem_min": round(sum(tempos) / len(tempos), 1),
        "tempo_max_viagem_min": max(tempos),
        "por_turno": por_turno,
        "cadeirantes": rel["demanda"]["cadeirantes"],
        "posicoes_cadeirante": otimizada["posicoes_cadeirante"],
        "atende_cadeirantes": cadeirantes_ok,
    }


# --------------------------------------------------------- memória de cálculo ---
def memoria_de_calculo(atual: dict, otimizada: dict, premissas: Premissas,
                       tipos: dict) -> list:
    """Passo a passo em português, para o gestor público e o tribunal de contas."""
    linhas_diesel = ", ".join(
        f"{t.get('nome', tid)}: R$ {custo_km(t, premissas):.2f}/km"
        for tid, t in tipos.items()
    )
    return [
        {
            "passo": "1. Custo por km de cada tipo de veículo",
            "formula": "custo_km = manutenção_km + preço_diesel ÷ consumo (km/l)",
            "valores": f"preço do diesel R$ {premissas.preco_diesel_l:.2f}/l → {linhas_diesel}",
        },
        {
            "passo": "2. Custo fixo mensal",
            "formula": "Σ (custo_fixo_mês do tipo × quantidade de veículos)",
            "valores": (f"frota atual R$ {atual['custo_fixo_mes']:,.0f}/mês · "
                        f"frota necessária R$ {otimizada['custo_fixo_mes']:,.0f}/mês"),
        },
        {
            "passo": "3. Custo variável mensal",
            "formula": "km/dia × dias letivos no mês × custo_km",
            "valores": (f"{atual['km_dia']:,.0f} km/dia × {premissas.dias_letivos_mes} dias "
                        f"→ R$ {atual['custo_variavel_mes']:,.0f}/mês (atual) · "
                        f"{otimizada['km_dia']:,.0f} km/dia × {premissas.dias_letivos_mes} dias "
                        f"→ R$ {otimizada['custo_variavel_mes']:,.0f}/mês (necessária)"),
        },
        {
            "passo": "4. Consumo de combustível",
            "formula": "litros/dia = Σ (km/dia do tipo ÷ consumo km/l do tipo)",
            "valores": (f"{atual['litros_dia']:,.1f} l/dia (atual) · "
                        f"{otimizada['litros_dia']:,.1f} l/dia (necessária)"),
        },
        {
            "passo": "5. Emissões evitadas",
            "formula": (f"tCO₂/ano = litros/dia × dias letivos × 12 meses × "
                        f"{premissas.fator_co2_kg_l} kg CO₂/l ÷ 1.000"),
            "valores": (f"{atual['tco2_ano']:,.1f} t/ano (atual) · "
                        f"{otimizada['tco2_ano']:,.1f} t/ano (necessária)"),
        },
        {
            "passo": "6. Economia",
            "formula": "economia = indicador da frota atual − indicador da frota necessária",
            "valores": ("os valores da faixa superior desta página saem exatamente "
                        "destes passos, sem arredondamento intermediário"),
        },
    ]


# --------------------------------------------------------------- cenários ---
def _economia_com(rel: dict, premissas: Premissas) -> dict:
    tipos = rel["premissas"]["custos_por_tipo"]
    atual = avaliar_frota(
        "Frota atual", rel["frota_atual"]["composicao"],
        _km_rateado(rel["frota_atual"]["composicao"],
                    rel["frota_atual"]["km_dia"]),
        tipos, premissas)
    otim = avaliar_frota(
        "Frota necessária", rel["frota_otimizada"]["composicao"],
        _km_por_tipo_dos_veiculos(rel["frota_otimizada"]["veiculos"],
                                  premissas.viagens_por_rota),
        tipos, premissas)
    return {"atual": atual, "otimizada": otim, "economia": comparar(atual, otim)}


def grade_de_cenarios(rel: dict, premissas: Premissas,
                      precos_diesel=None, dias_letivos=None) -> list:
    """Pré-calcula os cenários que os controles do painel podem selecionar.

    Os controles NUNCA recalculam nada no navegador: eles apenas escolhem um
    cenário já calculado aqui, para que todo número exibido na demo tenha
    saído do motor (mesma regra do agent-conversa).
    """
    precos = precos_diesel or [round(4.5 + 0.5 * i, 2) for i in range(10)]
    if premissas.preco_diesel_l not in precos:
        precos = sorted(precos + [premissas.preco_diesel_l])
    dias = dias_letivos or sorted({20, 21, 22, premissas.dias_letivos_mes})

    cenarios = []
    for preco in precos:
        for d in dias:
            p = premissas.substituir(preco_diesel_l=preco, dias_letivos_mes=d)
            r = _economia_com(rel, p)
            cenarios.append({
                "preco_diesel_l": preco,
                "dias_letivos_mes": d,
                "padrao": (preco == premissas.preco_diesel_l
                           and d == premissas.dias_letivos_mes),
                "custo_atual_mes": r["atual"]["custo_mes"],
                "custo_otimizado_mes": r["otimizada"]["custo_mes"],
                "economia_mes": r["economia"]["custo_mes"],
                "economia_ano": r["economia"]["custo_ano"],
                "reducao_custo_pct": r["economia"]["reducao_custo_pct"],
            })
    return cenarios


# ------------------------------------------------------------------ painel ---
def montar_painel(rel: dict, premissas: Premissas = None,
                  com_cenarios: bool = True) -> dict:
    """Estrutura completa consumida pelo renderizador HTML e pela API."""
    premissas = premissas or premissas_do_relatorio(rel)
    r = _economia_com(rel, premissas)
    tipos = rel["premissas"]["custos_por_tipo"]

    painel = {
        "municipio": rel["municipio"],
        "gerado_em": rel.get("gerado_em", "—"),
        "premissas": asdict(premissas),
        "demanda": rel["demanda"],
        "atual": r["atual"],
        "atual_origem": rel["frota_atual"].get("como_foi_estimada"),
        "otimizada": r["otimizada"],
        "economia": r["economia"],
        "qualidade": qualidade_do_servico(rel, r["otimizada"]),
        "memoria_calculo": memoria_de_calculo(
            r["atual"], r["otimizada"], premissas, tipos),
    }
    if rel.get("geografia"):
        painel["geografia"] = rel["geografia"]
        painel["viagens_mapa"] = rel["frota_otimizada"]["viagens"]
    if rel.get("porta_a_porta"):
        painel["porta_a_porta"] = rel["porta_a_porta"]
    if rel.get("reotimizacao"):
        painel["reotimizacao"] = rel["reotimizacao"]
    if rel.get("importacao"):
        painel["importacao"] = rel["importacao"]
    if rel.get("elegibilidade"):
        painel["elegibilidade"] = rel["elegibilidade"]
    if rel.get("rodadas"):
        painel["rodadas"] = rel["rodadas"]
    if com_cenarios:
        painel["cenarios"] = grade_de_cenarios(rel, premissas)
    return painel


if __name__ == "__main__":  # resumo rápido em linha de comando
    p = montar_painel(carregar_relatorio(), com_cenarios=False)
    e = p["economia"]
    print(f"{p['municipio']} — {p['atual']['total_veiculos']} → "
          f"{p['otimizada']['total_veiculos']} veículos "
          f"(-{e['reducao_frota_pct']}%)")
    print(f"Economia: R$ {e['custo_mes']:,.0f}/mês · R$ {e['custo_ano']:,.0f}/ano · "
          f"{e['km_dia']:,.0f} km/dia · {e['litros_dia']:,.0f} l/dia · "
          f"{e['tco2_ano']:,.1f} tCO₂/ano")
