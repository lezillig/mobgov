# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-comercial (etapa 2)
Otimizar o que já roda: diagnóstico da operação atual, linha por linha.

Precificar serve para ganhar contrato novo. Esta etapa é a outra metade, e a
que dá dinheiro mais rápido: a empresa já opera 25 linhas, com 25 veículos e
25 motoristas, e ninguém sabe dizer quais delas poderiam ser duas em vez de
três.

A diferença para o "antes e depois" que já existia no painel é a fonte do
"antes". Lá, quando o município não declarava a frota, ela era estimada — e
estimativa não serve para mexer numa operação real. Aqui o antes é a planilha
de linhas que a empresa opera hoje: veículo, turno, quilometragem, passageiros
transportados. Cada achado aponta para uma linha com nome.

Os achados são de quatro tipos, em ordem do que dá menos trabalho para fazer:

    veículo grande demais   linha de 12 passageiros num ônibus de 46:
                            trocar o carro não mexe em itinerário nenhum
    linhas que se fundem    duas linhas do mesmo turno e destino, cada uma
                            com meia lotação, e sobra jornada para as duas
    km excedente            o mesmo serviço com percurso menor
    veículo ocioso          o que sobra quando as três coisas acima acontecem

O sistema não "aplica" nada: cada achado sai com o número, a linha afetada e
o que precisa ser conferido antes. Mexer em linha de fretamento é mexer no
horário de gente que bate ponto.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import economia as economia_mod  # noqa: E402
from painel.formato import numero, reais  # noqa: E402

# Ocupação abaixo disso é veículo rodando com ar: o primeiro lugar onde se
# procura economia numa operação existente.
OCUPACAO_BAIXA = 0.55
# Diferença mínima de lugares para valer a troca de veículo. Trocar um 46 por
# um 28 vale; trocar um 16 por um 15 é retrabalho de contrato por nada.
GANHO_MINIMO_DE_LUGARES = 8


@dataclass
class Achado:
    tipo: str
    titulo: str
    linhas: list
    economia_mes: float
    detalhe: str
    o_que_conferir: str

    def como_dicionario(self) -> dict:
        return {"tipo": self.tipo, "titulo": self.titulo,
                "linhas": self.linhas,
                "economia_mes": round(self.economia_mes, 2),
                "detalhe": self.detalhe,
                "o_que_conferir": self.o_que_conferir}


def _custo_mensal_do_veiculo(tipo: dict, km_dia: float, dias: int,
                             diesel: float, diesel_base: float,
                             custo_motorista: float = 0.0) -> float:
    """Custo cheio de um veículo: posse + rodagem + (motorista, se separado)."""
    km_mes = km_dia * dias
    combustivel = km_mes / float(tipo["consumo_km_l"]) * diesel
    manutencao = km_mes * economia_mod.manutencao_km(tipo, diesel_base)
    return float(tipo["fixo_mes"]) + combustivel + manutencao + custo_motorista


def diagnosticar(operacao_atual: list, plano: dict,
                 custo_motorista_mes: float = None) -> dict:
    """Compara a operação declarada com o que o plano mostra ser possível.

    `operacao_atual`: uma linha por rota que a empresa opera hoje —
    {"linha", "turno", "destino", "tipo", "km_dia", "passageiros"}.
    """
    p = plano["premissas"]
    tipos = p["custos_por_tipo"]
    dias = p["dias_letivos_mes"]
    diesel = p["preco_diesel_l"]
    diesel_base = p.get("preco_diesel_base_l", diesel)
    if custo_motorista_mes is None:
        custo_motorista_mes = (plano.get("perfil") or {}).get(
            "custo_motorista_mes", 0.0) or 0.0

    achados = []
    linhas = [dict(l) for l in operacao_atual if l.get("tipo") in tipos]
    desconhecidos = [l for l in operacao_atual if l.get("tipo") not in tipos]

    for linha in linhas:
        tipo = tipos[linha["tipo"]]
        linha["lugares"] = tipo["capacidade"]
        linha["ocupacao"] = (float(linha.get("passageiros") or 0)
                             / max(1, tipo["capacidade"]))
        linha["custo_mes"] = _custo_mensal_do_veiculo(
            tipo, float(linha.get("km_dia") or 0), dias, diesel, diesel_base,
            custo_motorista_mes)

    # 1) veículo grande demais para a linha ------------------------------------
    for linha in linhas:
        passageiros = float(linha.get("passageiros") or 0)
        atual = tipos[linha["tipo"]]
        candidatos = [(k, t) for k, t in tipos.items()
                      if t["capacidade"] >= passageiros
                      and t["capacidade"] <= atual["capacidade"]
                      - GANHO_MINIMO_DE_LUGARES
                      and t["posicoes_cadeirante"] >= atual["posicoes_cadeirante"]
                      * (1 if linha.get("cadeirantes") else 0)]
        if not candidatos:
            continue
        menor_id, menor = min(candidatos, key=lambda kv: kv[1]["fixo_mes"])
        novo_custo = _custo_mensal_do_veiculo(
            menor, float(linha.get("km_dia") or 0), dias, diesel, diesel_base,
            custo_motorista_mes)
        economia = linha["custo_mes"] - novo_custo
        if economia <= 0:
            continue
        achados.append(Achado(
            "veiculo_grande_demais",
            f"{linha['linha']}: trocar {atual['nome']} por {menor['nome']}",
            [linha["linha"]], economia,
            f"A linha transporta {passageiros:.0f} passageiros num veículo de "
            f"{atual['capacidade']} lugares ({linha['ocupacao']:.0%} de "
            f"ocupação). Um {menor['nome']} atende a mesma gente.",
            "Confira se o itinerário tem trecho que exige o veículo maior "
            "(rampa, bagageiro, acesso) e se o contrato especifica o tipo."))

    # 2) linhas do mesmo turno e destino que se fundem --------------------------
    por_grupo = {}
    for linha in linhas:
        por_grupo.setdefault((linha.get("turno"), linha.get("destino")),
                             []).append(linha)
    for (turno, destino), grupo in sorted(por_grupo.items(),
                                          key=lambda kv: str(kv[0])):
        magras = sorted([l for l in grupo if l["ocupacao"] < OCUPACAO_BAIXA],
                        key=lambda l: -l["custo_mes"])
        if len(magras) < 2:
            continue
        maior = max(t["capacidade"] for t in tipos.values())
        for i in range(0, len(magras) - 1, 2):
            a, b = magras[i], magras[i + 1]
            juntos = float(a.get("passageiros") or 0) + float(b.get("passageiros") or 0)
            if juntos > maior:
                continue
            candidatos = [(k, t) for k, t in tipos.items()
                          if t["capacidade"] >= juntos]
            if not candidatos:
                continue
            _, escolhido = min(candidatos, key=lambda kv: kv[1]["fixo_mes"])
            # o percurso somado encolhe, mas não some: o veículo ainda passa
            # nos dois lados. Estimativa conservadora: 80% da soma
            km_junto = (float(a.get("km_dia") or 0)
                        + float(b.get("km_dia") or 0)) * 0.8
            novo_custo = _custo_mensal_do_veiculo(
                escolhido, km_junto, dias, diesel, diesel_base,
                custo_motorista_mes)
            economia = a["custo_mes"] + b["custo_mes"] - novo_custo
            if economia <= 0:
                continue
            achados.append(Achado(
                "linhas_que_se_fundem",
                f"{a['linha']} + {b['linha']}: uma linha em vez de duas",
                [a["linha"], b["linha"]], economia,
                f"As duas atendem {destino} no {turno} com "
                f"{a['ocupacao']:.0%} e {b['ocupacao']:.0%} de ocupação. "
                f"Juntas são {juntos:.0f} passageiros, que cabem num "
                f"{escolhido['nome']}.",
                "A fusão alonga o trajeto de quem embarca primeiro: confira "
                "se o tempo a bordo continua dentro do combinado com o "
                "cliente antes de propor."))

    # 3) quilometragem excedente ------------------------------------------------
    km_atual = sum(float(l.get("km_dia") or 0) for l in linhas)
    km_plano = float(plano["frota_otimizada"]["km_dia"])
    if km_atual and km_plano and km_atual > km_plano * 1.05:
        excedente = km_atual - km_plano
        custo_km_medio = sum(
            economia_mod.manutencao_km(tipos[l["tipo"]], diesel_base)
            + diesel / float(tipos[l["tipo"]]["consumo_km_l"])
            for l in linhas) / max(1, len(linhas))
        achados.append(Achado(
            "km_excedente",
            f"{excedente:,.0f} km/dia a mais que o percurso otimizado",
            [l["linha"] for l in linhas], excedente * dias * custo_km_medio,
            f"A operação de hoje roda {km_atual:,.0f} km/dia; o mesmo "
            f"atendimento, roteirizado, fecha em {km_plano:,.0f} km/dia "
            f"({100 * excedente / km_atual:.0f}% a menos).",
            "O percurso otimizado pressupõe os mesmos pontos de embarque. Se "
            "algum ponto for imposto pelo cliente, refaça com ele fixo."))

    # 4) o que sobra de frota ---------------------------------------------------
    veiculos_hoje = len({l["linha"] for l in linhas})
    veiculos_plano = plano["frota_otimizada"]["total_veiculos"]
    if veiculos_hoje > veiculos_plano:
        sobra = veiculos_hoje - veiculos_plano
        custo_medio = (sum(l["custo_mes"] for l in linhas)
                       / max(1, len(linhas)))
        achados.append(Achado(
            "frota_ociosa",
            f"{sobra} veículo(s) a menos para o mesmo atendimento",
            [], sobra * custo_medio,
            f"A operação usa {veiculos_hoje} veículos; o plano fecha com "
            f"{veiculos_plano}. A diferença é o efeito somado das trocas, "
            f"fusões e do percurso menor — não é um corte à parte.",
            "Não some esta economia com as anteriores: ela já as contém. "
            "Use-a como teto do que dá para capturar."))

    equipe = (plano.get("equipe") or {}).get("resumo") or {}
    return {
        "achados": [a.como_dicionario() for a in achados],
        "resumo": {
            "linhas_analisadas": len(linhas),
            "linhas_ignoradas": len(desconhecidos),
            "veiculos_hoje": veiculos_hoje,
            "veiculos_no_plano": veiculos_plano,
            "motoristas_no_plano": equipe.get("motoristas"),
            "km_dia_hoje": round(km_atual, 1),
            "km_dia_no_plano": round(km_plano, 1),
            "custo_mes_hoje": round(sum(l["custo_mes"] for l in linhas), 2),
            "ocupacao_media_hoje_pct": round(
                100 * sum(l["ocupacao"] for l in linhas) / max(1, len(linhas)), 1),
            # o teto é o achado de frota ociosa quando existe; os demais são
            # parcelas dele. Somar tudo daria uma economia que não existe.
            "economia_teto_mes": round(max(
                [a.economia_mes for a in achados
                 if a.tipo == "frota_ociosa"] or [0.0]), 2),
            "economia_acoes_imediatas_mes": round(sum(
                a.economia_mes for a in achados
                if a.tipo in ("veiculo_grande_demais", "linhas_que_se_fundem")), 2),
        },
        "linhas_ignoradas": [l.get("linha") for l in desconhecidos],
    }


def em_texto(diagnostico: dict, quantos: int = 8) -> list:
    """As linhas que a tela e o terminal mostram."""
    r = diagnostico["resumo"]
    saida = [
        f"{r['linhas_analisadas']} linhas analisadas · "
        f"{r['veiculos_hoje']} veículos hoje contra {r['veiculos_no_plano']} "
        f"no plano · ocupação média de {numero(r['ocupacao_media_hoje_pct'], 1)}%",
        f"Ações imediatas (troca de veículo e fusão de linha): "
        f"{reais(r['economia_acoes_imediatas_mes'], 2)}/mês",
        f"Teto do que dá para capturar: "
        f"{reais(r['economia_teto_mes'], 2)}/mês",
        "",
    ]
    for achado in diagnostico["achados"][:quantos]:
        saida.append(f"• {achado['titulo']} "
                     f"({reais(achado['economia_mes'], 2)}/mês)")
        saida.append(f"    {achado['detalhe']}")
        saida.append(f"    conferir: {achado['o_que_conferir']}")
    return saida
