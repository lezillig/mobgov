# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 5 · agent-aprendizado
Roda o ciclo de aprendizado sobre semanas de operação.

Produz dois arquivos que o resto do sistema consome sozinho:

    relatorios/aprendizado.json       série semanal para o painel
    relatorios/fatores_transito.json  fatores que o motor de rotas passa a usar

O segundo é o que fecha o ciclo: na próxima vez que o motor rodar, a matriz de
tempos já sai corrigida pelo que a operação mostrou. É o "IA que aprende" do
prompt-mestre deixando de ser slide e virando arquivo.

Uso:
    python motor/rodar_aprendizado.py            # 8 semanas simuladas
    python motor/rodar_aprendizado.py --semanas 12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aprendizado.aprender import (
    Modelo, acuracia_ausencia, erro_medio, exemplos_do_aprendizado,
    modelo_inicial, treinar_semana,
)
from aprendizado.simulador import OperacaoSimulada
from dados import tempos as tempos_mod

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")

# Origem dos dados. Enquanto o app do motorista não existe, é simulação — e o
# painel diz isso na cara. Quando os pings forem reais, troca para "gps_real".
ORIGEM = "simulacao"


def _faixa_por_turno(rel: dict) -> dict:
    """Em que faixa horária cada turno cai, segundo o perfil de trânsito."""
    perfil = tempos_mod.PerfilDeTransito()
    faixas = {}
    for t in rel["demanda"]["turnos"]:
        # o mesmo horário que o motor usa: meia hora antes da janela
        minuto = {"manha": 6 * 60 + 10, "tarde": 12 * 60 + 10}.get(t["id"],
                                                                  7 * 60)
        faixas[t["id"]] = perfil.faixa(minuto).id
    return faixas


def _zona_por_viagem(rel: dict) -> dict:
    """Viagem é urbana se a maioria das paradas está na malha urbana."""
    pontos = (rel.get("geografia") or {}).get("pontos") or {}
    zonas = {}
    for v in rel["frota_otimizada"]["viagens"]:
        marcas = [tempos_mod.zona_de(pontos[pid])
                  for pid in v.get("paradas", []) if pid in pontos]
        urbanas = sum(1 for m in marcas if m == "urbano")
        zonas[v["id"]] = ("urbano" if marcas and urbanas > len(marcas) / 2
                          else "rural")
    return zonas


def rodar(semanas: int = 8, caminho_relatorio: str = None) -> dict:
    caminho_relatorio = caminho_relatorio or os.path.join(
        DIR_RELATORIOS, "dimensionamento.json")
    with open(caminho_relatorio, encoding="utf-8") as f:
        rel = json.load(f)

    viagens = rel["frota_otimizada"]["viagens"]
    faixas, zonas = _faixa_por_turno(rel), _zona_por_viagem(rel)
    simulador = OperacaoSimulada()

    modelo = modelo_inicial()
    inicial = modelo
    historico, rollbacks = [], 0

    # Dois conjuntos fixos, gerados uma vez e nunca usados para treinar:
    # - VALIDAÇÃO decide se o modelo novo entra ou volta atrás;
    # - TESTE é o que vai para o painel.
    # Separar os dois evita o vício clássico de reportar erro no mesmo
    # conjunto que escolheu o modelo. E fixá-los evita o que apareceu na
    # primeira rodada: a curva do erro subindo e descendo porque a semana de
    # validação sorteava mais dias de chuva, não porque o modelo piorou.
    validacao = simulador.semana(viagens, faixas, zonas)
    teste = simulador.semana(viagens, faixas, zonas)
    observadas = simulador.semana(viagens, faixas, zonas)
    # O modelo aprende com TODO o histórico, não só com a última semana:
    # estimar em cima de cinco dias faz o fator oscilar e o rollback disparar
    # à toa. Memória curta não é aprendizado, é sobressalto.
    acumulado = {"trechos": [], "paradas": [], "faltas": []}

    for semana in range(1, semanas + 1):
        for chave in acumulado:
            acumulado[chave] = acumulado[chave] + observadas[chave]
        rodada = treinar_semana(modelo, acumulado, validacao)
        modelo = rodada["modelo"]
        if not rodada["promovido"]:
            rollbacks += 1
        historico.append({
            "semana": f"Semana {semana}",
            "mae_min": erro_medio(modelo, teste["trechos"]),
            "acuracia_ausencia_pct": acuracia_ausencia(modelo, teste["faltas"]),
            "viagens": rodada["amostras"],
            "versao_modelo": rodada["versao"],
            "promovido": rodada["promovido"],
            "motivo_rollback": rodada["motivo_rollback"],
        })
        observadas = simulador.semana(viagens, faixas, zonas)

    serie = {
        "origem": ORIGEM,
        "unidade_erro": "min",
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "semanas": historico,
        "exemplos": exemplos_do_aprendizado(
            modelo, inicial, modelo.parada_extra_por_ponto,
            modelo.ausencia_por_dia),
        "versao_modelo": modelo.versao,
        "rollbacks": rollbacks,
        "amostras": modelo.amostras,
    }

    fatores = {
        "origem": ORIGEM,
        "gerado_em": serie["gerado_em"],
        "fatores": modelo.fatores,
        "amostras": modelo.amostras,
        "observacao": "Fatores estimados a partir de operação simulada. "
                      "Quando o app do motorista entrar, a mesma rotina roda "
                      "sobre os pings reais e a origem passa a 'gps_real'.",
    }

    os.makedirs(DIR_RELATORIOS, exist_ok=True)
    for nome, dados in (("aprendizado.json", serie),
                        ("fatores_transito.json", fatores)):
        with open(os.path.join(DIR_RELATORIOS, nome), "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    return serie


def main():
    ap = argparse.ArgumentParser(description="Ciclo de aprendizado do MOBGOV")
    ap.add_argument("--semanas", type=int, default=8)
    a = ap.parse_args()
    serie = rodar(a.semanas)
    primeira, ultima = serie["semanas"][0], serie["semanas"][-1]
    print(f"Aprendizado sobre {a.semanas} semanas ({serie['amostras']} viagens "
          f"observadas, origem: {serie['origem']})")
    print(f"  erro médio do tempo estimado: {primeira['mae_min']} min → "
          f"{ultima['mae_min']} min")
    print(f"  acurácia de ausência: {primeira['acuracia_ausencia_pct']}% → "
          f"{ultima['acuracia_ausencia_pct']}%")
    print(f"  versão do modelo: {serie['versao_modelo']} · "
          f"rollbacks: {serie['rollbacks']}")
    for e in serie["exemplos"]:
        print(f"  - {e}")
    print("Relatórios: relatorios/aprendizado.json e "
          "relatorios/fatores_transito.json")


if __name__ == "__main__":
    main()
