# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 5 · agent-aprendizado
Simulador de operação: gera o que o app do motorista mandaria de volta.

O ciclo de aprendizado precisa de dados de operação — GPS, horário real de
embarque, faltas. Enquanto o app do motorista não existe (Sprint 6), este
módulo produz essas observações a partir do plano, aplicando uma VERDADE
OCULTA que o sistema não conhece:

- fatores de trânsito diferentes dos que o planejamento assumiu (é justamente
  o que o aprendizado tem que descobrir);
- tempo de embarque por ponto diferente do estimado (ponto com cadeirante
  demora mais do que o modelo supõe);
- faltas de alunos com padrão por dia da semana (sexta-feira falta mais).

Nada aqui é apresentado como medição real. O relatório sai marcado como
`origem: "simulacao"`, e o painel mostra o selo correspondente. O que é real
é o CAMINHO: coleta → estimativa → versão → rollback. Quando os pings vierem
do app, troca-se este módulo pela ingestão de verdade e nada mais muda.
"""
from __future__ import annotations

import random

# --------------------------------------------------------- verdade oculta ---
# O planejamento assume 1,35 no pico urbano e 1,10 no pico rural (ver
# dados/tempos.py). A rua, nesta simulação, é pior — e é isso que o sistema
# tem que aprender sozinho.
FATORES_REAIS = {
    "pico_manha": {"urbano": 1.52, "rural": 1.18},
    "entre_picos": {"urbano": 1.05, "rural": 0.98},
    "pico_tarde": {"urbano": 1.41, "rural": 1.12},
    "fora_pico": {"urbano": 0.95, "rural": 0.93},
}

# Embarque real por ponto: o modelo usa 1 min + 0,08/aluno + 3/cadeirante.
# Na rua, cadeirante demora mais e ponto de estrada tem portão para abrir.
EXTRA_CADEIRANTE_MIN = 1.8
EXTRA_RURAL_MIN = 0.6

# Faltas por dia da semana (0 = segunda). Sexta falta mais, segunda também.
FALTAS_POR_DIA = [0.09, 0.06, 0.06, 0.07, 0.13, 0.0, 0.0]

# Dias de chuva penalizam o percurso — o aprendizado enxerga como variância.
PROB_CHUVA = 0.18
FATOR_CHUVA = 1.22


class OperacaoSimulada:
    """Gera observações de uma semana de operação a partir do plano."""

    def __init__(self, semente: int = 7):
        self.rng = random.Random(semente)

    def _fator_real(self, faixa: str, zona: str, chuva: bool) -> float:
        base = FATORES_REAIS.get(faixa, {}).get(zona, 1.0)
        ruido = self.rng.gauss(1.0, 0.07)          # variação dia a dia
        return max(0.5, base * ruido * (FATOR_CHUVA if chuva else 1.0))

    def semana(self, viagens: list, faixa_por_turno: dict,
               zona_por_viagem: dict, dias_letivos: int = 5,
               fator_planejado=None) -> dict:
        """Uma semana de operação: pings de trecho, paradas e faltas.

        `viagens` são as viagens do plano (com km, minutos estimados e
        paradas). Devolve observações agregadas — nunca dados pessoais: o que
        volta é tempo, não quem estava dentro do veículo.

        `fator_planejado(faixa, zona)` é o fator que o PLANEJAMENTO usou: o
        tempo estimado da viagem já vem multiplicado por ele. Para aplicar a
        verdade oculta é preciso desfazer isso primeiro — sem esse cuidado, a
        simulação empilha um fator sobre o outro e o aprendizado "descobre"
        um trânsito que não existe (foi exatamente o que aconteceu na primeira
        versão: ×2,17 onde a verdade era ×1,52).
        """
        if fator_planejado is None:
            from aprendizado.aprender import FATORES_INICIAIS

            def fator_planejado(faixa, zona):
                return FATORES_INICIAIS.get(faixa, {}).get(zona, 1.0)
        trechos, paradas, faltas = [], [], []
        for dia in range(dias_letivos):
            chuva = self.rng.random() < PROB_CHUVA
            for v in viagens:
                faixa = faixa_por_turno.get(v["turno"], "pico_manha")
                zona = zona_por_viagem.get(v["id"], "rural")
                fator = self._fator_real(faixa, zona, chuva)
                estimado = v["min_viagem"]
                sem_transito = estimado / max(1e-6, fator_planejado(faixa, zona))
                realizado = max(1, round(sem_transito * fator))
                trechos.append({
                    "viagem": v["id"], "dia": dia, "faixa": faixa, "zona": zona,
                    "chuva": chuva, "min_estimado": estimado,
                    # o fator que o PLANO usou viaja junto com a observação:
                    # sem ele, quem for estimar teria que adivinhar qual
                    # trânsito já está embutido no tempo estimado
                    "fator_plano": round(fator_planejado(faixa, zona), 4),
                    "min_realizado": realizado,
                })
                for pid in v.get("paradas", []):
                    extra = (EXTRA_CADEIRANTE_MIN if v.get("cadeirantes") else 0)
                    extra += EXTRA_RURAL_MIN if zona == "rural" else 0
                    paradas.append({
                        "ponto": pid, "dia": dia,
                        "min_extra_realizado": round(
                            max(0.0, self.rng.gauss(extra, 0.4)), 2),
                    })
                previstas = v.get("alunos", 0)
                taxa = FALTAS_POR_DIA[dia % len(FALTAS_POR_DIA)]
                ausentes = sum(1 for _ in range(previstas)
                               if self.rng.random() < taxa)
                faltas.append({"viagem": v["id"], "dia": dia,
                               "previstos": previstas, "ausentes": ausentes})
        return {"trechos": trechos, "paradas": paradas, "faltas": faltas}
