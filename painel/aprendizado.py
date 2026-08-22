# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 2 · agent-painel
Série "o que o sistema aprendeu" exibida no painel de economia.

O módulo de aprendizado contínuo (agent-aprendizado) só é construído na
Sprint 5, quando o app do motorista começar a mandar GPS real. Até lá o painel
mostra uma SÉRIE DE DEMONSTRAÇÃO — e diz isso na tela, com selo visível, para
não vender como resultado medido o que ainda é ilustração. Assim que existir
`relatorios/aprendizado.json` gerado pela operação, o painel passa a ler o
arquivo real e o selo muda sozinho.

Formato esperado do arquivo real:
{
  "origem": "operacao_real",
  "unidade_erro": "min",
  "semanas": [{"semana": "2026-03-02", "mae_min": 6.4,
               "acuracia_ausencia_pct": 71.0, "viagens": 812}, ...],
  "exemplos": ["..."]
}
"""
from __future__ import annotations

import json
import os

SERIE_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "aprendizado.json",
)

# Curva de demonstração: erro médio do tempo estimado por trecho caindo à
# medida que o histórico de GPS cresce, e previsão de ausência ficando melhor.
_DEMONSTRACAO = {
    "origem": "demonstracao",
    "unidade_erro": "min",
    "semanas": [
        {"semana": "Semana 1", "mae_min": 7.8, "acuracia_ausencia_pct": 58.0, "viagens": 704},
        {"semana": "Semana 2", "mae_min": 6.9, "acuracia_ausencia_pct": 63.0, "viagens": 726},
        {"semana": "Semana 3", "mae_min": 5.6, "acuracia_ausencia_pct": 68.0, "viagens": 748},
        {"semana": "Semana 4", "mae_min": 4.7, "acuracia_ausencia_pct": 72.0, "viagens": 733},
        {"semana": "Semana 5", "mae_min": 4.1, "acuracia_ausencia_pct": 76.0, "viagens": 759},
        {"semana": "Semana 6", "mae_min": 3.4, "acuracia_ausencia_pct": 79.0, "viagens": 771},
        {"semana": "Semana 7", "mae_min": 3.0, "acuracia_ausencia_pct": 81.0, "viagens": 766},
        {"semana": "Semana 8", "mae_min": 2.6, "acuracia_ausencia_pct": 83.0, "viagens": 780},
    ],
    "exemplos": [
        "Estrada do Assentamento Oeste (P061→P067): o mapa dizia 8 min, "
        "na prática são 14 em dia de chuva — tempo corrigido na Semana 3.",
        "Ponto P014 (Sede Urbana): embarque com cadeirante leva 3,5 min, "
        "e não os 1,5 min padrão — a rota 4 ganhou folga e parou de atrasar.",
        "Sextas-feiras têm 11% mais ausências: a Rota 12 passou de ônibus "
        "de 31 lugares para micro-ônibus de 20 sem deixar aluno em pé.",
    ],
}

_ROTULOS_ORIGEM = {
    "demonstracao": ("SÉRIE DE DEMONSTRAÇÃO",
                     "Dados ilustrativos, escritos à mão para a apresentação."),
    "simulacao": ("APRENDIDO EM SIMULAÇÃO",
                  "O ciclo de aprendizado rodou de verdade — coleta, "
                  "estimativa, versão e rollback —, mas sobre uma operação "
                  "simulada. Os pings reais entram quando o app do motorista "
                  "for ao ar."),
    "operacao_real": ("MEDIDO NA OPERAÇÃO",
                      "Série calculada com GPS e horários reais de embarque "
                      "coletados pelo app do motorista."),
}


def carregar_serie(caminho: str = SERIE_PADRAO) -> dict:
    """Lê a série real se existir; senão devolve a de demonstração."""
    serie = _DEMONSTRACAO
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            serie = json.load(f)
            serie.setdefault("origem", "operacao_real")
    return resumir(serie)


def resumir(serie: dict) -> dict:
    """Acrescenta à série os números que o painel exibe como manchete."""
    semanas = serie.get("semanas", [])
    serie = dict(serie)
    selo, explicacao = _ROTULOS_ORIGEM.get(
        serie.get("origem"), _ROTULOS_ORIGEM["demonstracao"])
    serie["selo"] = selo
    serie["explicacao_selo"] = explicacao
    serie["e_demonstracao"] = serie.get("origem") != "operacao_real"
    serie["e_simulacao"] = serie.get("origem") == "simulacao"
    if semanas:
        primeiro, ultimo = semanas[0], semanas[-1]
        queda = primeiro["mae_min"] - ultimo["mae_min"]
        serie["erro_inicial_min"] = primeiro["mae_min"]
        serie["erro_atual_min"] = ultimo["mae_min"]
        serie["queda_erro_pct"] = (
            round(100 * queda / primeiro["mae_min"], 1) if primeiro["mae_min"] else 0.0)
        serie["ganho_ausencia_pp"] = round(
            ultimo.get("acuracia_ausencia_pct", 0)
            - primeiro.get("acuracia_ausencia_pct", 0), 1)
        serie["viagens_observadas"] = sum(s.get("viagens", 0) for s in semanas)
        serie["rollbacks"] = serie.get("rollbacks", 0)
        serie["versao_modelo"] = serie.get("versao_modelo", 0)
    return serie
