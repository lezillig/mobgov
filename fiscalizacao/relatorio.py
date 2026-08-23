# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 12 · agent-fiscalizacao
O boletim de medição do mês — a peça que vai para o processo.

Junta as três partes numa coisa só, na ordem em que a prefeitura precisa
ler:

    1. quanto do mês tem evidência        (sem isso, o resto não vale)
    2. o que aconteceu, por fornecedor    (medição)
    3. quanto pagar, quanto glosar,       (contrato)
       e o que ficou esperando decisão

A ordem não é estética. Um boletim que abre com "R$ 4.696 de glosa" e só no
rodapé conta que 8% das viagens não tinham evidência já perdeu a discussão
com o fornecedor. Cobertura primeiro.

    python -m fiscalizacao.relatorio
    python -m fiscalizacao.relatorio --dias 22 --valor-km 4.85
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import perfis as perfis_mod  # noqa: E402
from fiscalizacao import contrato as contrato_mod  # noqa: E402
from fiscalizacao import medicao as medicao_mod  # noqa: E402
from fiscalizacao import simulador as simulador_mod  # noqa: E402
from operacao import registro  # noqa: E402
from painel import economia as economia_mod  # noqa: E402

DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA_PADRAO = os.path.join(DIR_BASE, "relatorios", "fiscalizacao.json")

# Cobertura abaixo disto: o boletim sai, mas dizendo que não sustenta glosa.
# É a diferença entre um relatório que resolve e um que vira recurso.
COBERTURA_MINIMA_PCT = 70


def _reais(valor: float) -> str:
    """R$ 10.766,09 — a tela é lida por brasileiro, não por parser."""
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return "R$ " + inteiro.replace(",", ".") + "," + centavos


def montar(plano: dict, eventos: list, dias: list,
           regras: contrato_mod.RegrasDoContrato = None,
           origem: str = "medido", explicacao_selo: str = "",
           veiculos_contratados: int = 0) -> dict:
    """O boletim inteiro: cobertura, medição por fornecedor e pagamento."""
    regras = regras or contrato_mod.RegrasDoContrato()
    perfil = plano.get("perfil") or {}
    contrato = perfis_mod.contrato_por_destino(perfil)

    # a medição casa fornecedor por id OU por nome do destino, como o resto
    # do sistema — plano importado renumera os destinos
    por_destino = {}
    for destino in (plano.get("geografia") or {}).get("escolas", []):
        parte = (contrato.get("por_destino", {}).get(
            perfis_mod.chave_de_destino(destino.get("id")))
            or contrato.get("por_destino", {}).get(
                perfis_mod.chave_de_destino(destino.get("nome"))))
        if parte:
            por_destino[destino.get("id")] = parte
            por_destino[destino.get("nome")] = parte

    medicao = medicao_mod.medir_periodo(plano, eventos, dias, por_destino)
    pagamento = contrato_mod.avaliar(
        medicao, regras,
        veiculos_contratados or (plano.get("frota_otimizada") or {})
        .get("total_veiculos", 0))

    resumo = medicao["resumo"]
    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "municipio": plano.get("municipio"),
        "periodo": {"de": dias[0], "ate": dias[-1], "dias": len(dias)},
        "origem": origem,
        "explicacao_selo": explicacao_selo,
        "rotulo_contraparte": contrato.get("rotulo", "fornecedor"),
        "confiabilidade": _confiabilidade(resumo),
        "resumo": resumo,
        "por_fornecedor": _com_pagamento(medicao, regras),
        "por_dia": medicao["dias"],
        "pagamento": pagamento,
        "pendencias": _pendencias(pagamento, resumo,
                                  contrato.get("rotulo", "fornecedor")),
    }


def _confiabilidade(resumo: dict) -> dict:
    """O primeiro número do boletim: quanto do mês dá para afirmar."""
    cobertura = resumo.get("cobertura_pct") or 0
    return {
        "cobertura_pct": cobertura,
        "sustenta_glosa": cobertura >= COBERTURA_MINIMA_PCT,
        "minimo_pct": COBERTURA_MINIMA_PCT,
        "frase": (f"{cobertura:.0f}% das viagens do período têm evidência de "
                  f"execução."
                  + ("" if cobertura >= COBERTURA_MINIMA_PCT else
                     f" Abaixo de {COBERTURA_MINIMA_PCT}% a medição não "
                     f"sustenta glosa: o problema a resolver primeiro é o "
                     f"envio dos aparelhos, não o desconto.")),
        "km_medido_e_piso": resumo.get("km_medido_e_piso", False),
    }


def _com_pagamento(medicao: dict, regras) -> list:
    """Cada fornecedor com a própria medição e o próprio valor."""
    saida = []
    for grupo in medicao.get("por_fornecedor", []):
        do_grupo = [m for m in medicao["viagens"]
                    if (m.get("fornecedor_id") or "—") == grupo["id"]]
        pagamento = contrato_mod.avaliar(
            {"viagens": do_grupo, "resumo": grupo["resumo"]}, regras)
        saida.append({
            "id": grupo["id"], "nome": grupo["nome"] or "sem contrato",
            "resumo": grupo["resumo"],
            "a_pagar": pagamento["a_pagar"],
            "glosa": pagamento["glosa"],
            "em_suspenso": pagamento["em_suspenso"],
            "maiores_glosas": pagamento["glosas"][:5],
        })
    return saida


def _pendencias(pagamento: dict, resumo: dict, rotulo: str) -> list:
    """O que precisa de gente antes de o boletim virar pagamento."""
    itens = []
    if pagamento["suspensos"]:
        itens.append({
            "urgencia": "alta",
            "titulo": f"{len(pagamento['suspensos'])} viagens sem evidência "
                      f"para confirmar",
            "detalhe": f"São {_reais(pagamento['em_suspenso'])} que não podem "
                       f"ser pagos nem glosados sem alguém confirmar com o "
                       f"{rotulo} se a viagem rodou. Aparelho sem sinal é o "
                       f"motivo mais comum.",
            "quem_decide": "fiscal do contrato",
            "acao": "Abrir a fila de confirmação",
        })
    if pagamento["glosas"]:
        itens.append({
            "urgencia": "media",
            "titulo": f"{_reais(pagamento['glosa'])} de glosa a notificar",
            "detalhe": f"{len(pagamento['glosas'])} ocorrências com evidência "
                       f"registrada. O {rotulo} tem direito a contestar antes "
                       f"do desconto — o boletim é a peça que abre o prazo.",
            "quem_decide": "fiscal do contrato",
            "acao": "Notificar o fornecedor",
        })
    if resumo.get("atrasadas"):
        itens.append({
            "urgencia": "baixa",
            "titulo": f"{resumo['atrasadas']} chegadas fora do horário",
            "detalhe": f"Atraso médio de {resumo.get('atraso_medio_min')} min. "
                       f"Nem todo atraso é glosa, mas atraso que se repete no "
                       f"mesmo itinerário é sinal de que o roteiro está "
                       f"apertado demais — vale replanejar antes de multar.",
            "quem_decide": "quem planeja as rotas",
            "acao": "Ver os itinerários que mais atrasam",
        })
    return itens


def gerar(saida: str = SAIDA_PADRAO, dias: int = 22,
          regras: contrato_mod.RegrasDoContrato = None,
          usar_simulacao: bool = None) -> str:
    """Escreve o boletim. Usa a operação real se houver; senão, simula.

    A escolha é declarada no arquivo, no campo `origem`, e toda tela que
    mostrar esses números mostra o selo correspondente.
    """
    plano = economia_mod.carregar_relatorio(economia_mod.RELATORIO_PADRAO)
    reais = registro.ler_eventos()
    dias_reais = sorted({(e.get("em") or "")[:10] for e in reais if e.get("em")})

    # um punhado de eventos não é um mês de operação: com menos de um dia
    # cheio de execução, medir daria um boletim que só fala de ausência
    if usar_simulacao is None:
        usar_simulacao = len(dias_reais) < 2

    if usar_simulacao:
        simulacao = simulador_mod.simular_mes(plano, dias=dias)
        eventos, calendario = simulacao["eventos"], simulacao["dias"]
        origem, explicacao = "simulacao", simulacao["explicacao_selo"]
    else:
        eventos, calendario = reais, dias_reais
        origem, explicacao = "medido", ("eventos do aplicativo do motorista e "
                                        "do GPS dos veículos")

    boletim = montar(plano, eventos, calendario, regras, origem, explicacao)
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(boletim, f, ensure_ascii=False, indent=2)
    return saida


def main(argv=None):
    ap = argparse.ArgumentParser(description="Boletim de medição do contrato")
    ap.add_argument("--dias", type=int, default=22)
    ap.add_argument("--modelo", default="km_rodado",
                    choices=contrato_mod.MODELOS)
    ap.add_argument("--valor-km", type=float, default=4.85)
    ap.add_argument("--valor-viagem", type=float, default=0.0)
    ap.add_argument("--valor-veiculo-mes", type=float, default=0.0)
    ap.add_argument("--paga-por", default="planejado",
                    choices=("planejado", "medido"))
    ap.add_argument("--saida", default=SAIDA_PADRAO)
    a = ap.parse_args(argv)

    regras = contrato_mod.RegrasDoContrato(
        modelo=a.modelo, valor_km=a.valor_km, valor_viagem=a.valor_viagem,
        valor_veiculo_mes=a.valor_veiculo_mes, paga_por=a.paga_por,
        dias_no_mes=a.dias)
    caminho = gerar(a.saida, a.dias, regras)
    with open(caminho, encoding="utf-8") as f:
        boletim = json.load(f)

    r, p = boletim["resumo"], boletim["pagamento"]
    print(f"Boletim de medição — {boletim['municipio']} "
          f"({boletim['periodo']['de']} a {boletim['periodo']['ate']})")
    print(f"  {boletim['confiabilidade']['frase']}")
    print(f"  {r['viagens_planejadas']} viagens planejadas: "
          f"{r['realizadas']} realizadas, {r['parciais']} parciais, "
          f"{r['nao_realizadas']} não realizadas, "
          f"{r['sem_evidencia']} sem evidência")
    print(f"  A pagar R$ {p['a_pagar']:,.2f} | glosa R$ {p['glosa']:,.2f} | "
          f"em suspenso R$ {p['em_suspenso']:,.2f}")
    for alerta in p["alertas"]:
        print(f"  ! {alerta}")
    print(f"Boletim em {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
