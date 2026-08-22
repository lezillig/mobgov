# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 5 · agent-aprendizado
O ciclo que faz o sistema melhorar sozinho.

Entra observação de operação (trechos percorridos, tempo de parada, faltas),
sai um MODELO versionado com três coisas que o motor de rotas usa no dia
seguinte:

1. **fatores de trânsito** por faixa horária e zona — corrigem a matriz de
   tempos (o mapa "aprende" o trânsito do município);
2. **tempo extra de parada** por ponto — o embarque de cadeirante demora mais
   do que o modelo supõe, e quanto mais é medido, não chutado;
3. **taxa de ausência** por dia da semana — permite superlotação controlada
   sem deixar aluno em pé.

Regras que vêm do prompt-mestre e não são negociáveis:

- **Versionamento com rollback**: o modelo novo só entra se o erro cair. Se
  piorar, volta o anterior e o motivo fica registrado. Um sistema que aprende
  também precisa saber desaprender.
- **Métrica honesta**: o erro é medido na SEMANA SEGUINTE, dados que o modelo
  não viu. Medir no que já se conhece é auto-elogio.
- **Sem dado pessoal**: as observações são tempos e contagens. Nenhum nome,
  nenhum CPF, nenhuma condição de saúde entra no modelo.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

FATORES_INICIAIS = {
    "pico_manha": {"urbano": 1.35, "rural": 1.10},
    "entre_picos": {"urbano": 1.00, "rural": 1.00},
    "pico_tarde": {"urbano": 1.30, "rural": 1.08},
    "fora_pico": {"urbano": 0.92, "rural": 0.95},
}

MINIMO_DE_AMOSTRAS = 12   # abaixo disso, não se troca uma premissa por ruído


@dataclass
class Modelo:
    """Uma versão do que o sistema acredita sobre a rua."""
    versao: int
    fatores: dict
    parada_extra_por_ponto: dict = field(default_factory=dict)
    ausencia_por_dia: dict = field(default_factory=dict)
    amostras: int = 0

    def fator(self, faixa: str, zona: str) -> float:
        return self.fatores.get(faixa, {}).get(
            zona, FATORES_INICIAIS.get(faixa, {}).get(zona, 1.0))


def modelo_inicial() -> Modelo:
    return Modelo(versao=0,
                  fatores={f: dict(z) for f, z in FATORES_INICIAIS.items()})


# ------------------------------------------------------------- estimativas ---
def estimar_fatores(trechos: list, base: Modelo) -> dict:
    """Fator = mediana de (tempo realizado ÷ tempo estimado sem trânsito).

    Mediana, e não média, porque um dia de chuva forte não pode redefinir o
    trânsito da semana inteira. Faixa com poucas amostras mantém a premissa
    anterior — é melhor uma estimativa declarada do que um número tirado de
    três viagens.
    """
    razoes = {}
    for t in trechos:
        # desfaz o fator QUE O PLANO USOU, não o do modelo atual: o tempo
        # estimado da observação foi calculado uma vez, na véspera, e não muda
        # porque o modelo evoluiu. Usar o fator corrente aqui faz o fator
        # crescer a cada rodada (bug real: 1,35 → 1,55 → 1,83 → …).
        fator_plano = t.get("fator_plano") or FATORES_INICIAIS.get(
            t["faixa"], {}).get(t["zona"], 1.0)
        estimado_sem_transito = t["min_estimado"] / fator_plano
        if estimado_sem_transito <= 0:
            continue
        razoes.setdefault((t["faixa"], t["zona"]), []).append(
            t["min_realizado"] / estimado_sem_transito)

    fatores = {f: dict(z) for f, z in base.fatores.items()}
    for (faixa, zona), valores in razoes.items():
        if len(valores) >= MINIMO_DE_AMOSTRAS:
            fatores.setdefault(faixa, {})[zona] = round(
                statistics.median(valores), 3)
    return fatores


def estimar_paradas(paradas: list) -> dict:
    por_ponto = {}
    for p in paradas:
        por_ponto.setdefault(p["ponto"], []).append(p["min_extra_realizado"])
    return {ponto: round(statistics.median(v), 2)
            for ponto, v in por_ponto.items() if len(v) >= 3}


def estimar_ausencias(faltas: list) -> dict:
    por_dia = {}
    for f in faltas:
        if f["previstos"]:
            por_dia.setdefault(f["dia"], []).append(f["ausentes"] / f["previstos"])
    return {str(dia): round(statistics.mean(v), 4)
            for dia, v in por_dia.items() if len(v) >= 3}


# ---------------------------------------------------------------- métricas ---
def erro_medio(modelo: Modelo, trechos: list) -> float:
    """MAE em minutos entre o tempo que o modelo preveria e o realizado."""
    if not trechos:
        return 0.0
    erros = []
    for t in trechos:
        fator_plano = t.get("fator_plano") or FATORES_INICIAIS.get(
            t["faixa"], {}).get(t["zona"], 1.0)
        sem_transito = t["min_estimado"] / fator_plano
        previsto = sem_transito * modelo.fator(t["faixa"], t["zona"])
        erros.append(abs(previsto - t["min_realizado"]))
    return round(sum(erros) / len(erros), 2)


def acuracia_ausencia(modelo: Modelo, faltas: list) -> float:
    """Acerto da previsão de ausência, medido POR DIA, não por viagem.

    Prever quantos faltam numa viagem de 28 alunos é adivinhar moeda: a
    variação binomial domina e nenhum modelo honesto acerta. O que interessa
    para dimensionar frota é o agregado do dia — quantos lugares sobram na
    rede inteira. É assim que se mede aqui.
    """
    if not faltas or not modelo.ausencia_por_dia:
        return 0.0
    por_dia = {}
    for f in faltas:
        if not f["previstos"]:
            continue
        acumulado = por_dia.setdefault(f["dia"], {"previstos": 0, "ausentes": 0})
        acumulado["previstos"] += f["previstos"]
        acumulado["ausentes"] += f["ausentes"]

    acertos = []
    for dia, valores in por_dia.items():
        taxa = modelo.ausencia_por_dia.get(str(dia))
        if taxa is None:
            continue
        previsto = taxa * valores["previstos"]
        real = valores["ausentes"]
        pior = max(previsto, real, 1)
        acertos.append(max(0.0, 1 - abs(previsto - real) / pior))
    return round(100 * sum(acertos) / len(acertos), 1) if acertos else 0.0


# ------------------------------------------------------------- ciclo ---
def treinar_semana(modelo: Modelo, observadas: dict, validacao: dict) -> dict:
    """Uma rodada de aprendizado: estima, valida e decide se promove.

    Devolve o modelo vigente depois da rodada (novo ou o anterior, em caso de
    rollback) junto com as métricas — que vão inteiras para o painel.
    """
    candidato = Modelo(
        versao=modelo.versao + 1,
        fatores=estimar_fatores(observadas["trechos"], modelo),
        parada_extra_por_ponto=estimar_paradas(observadas["paradas"]),
        ausencia_por_dia=estimar_ausencias(observadas["faltas"]),
        amostras=modelo.amostras + len(observadas["trechos"]),
    )

    erro_antes = erro_medio(modelo, validacao["trechos"])
    erro_depois = erro_medio(candidato, validacao["trechos"])
    promovido = erro_depois <= erro_antes or modelo.versao == 0

    vigente = candidato if promovido else modelo
    return {
        "modelo": vigente,
        "versao": vigente.versao,
        "promovido": promovido,
        "mae_antes_min": erro_antes,
        "mae_min": erro_depois if promovido else erro_antes,
        "acuracia_ausencia_pct": acuracia_ausencia(vigente, validacao["faltas"]),
        "amostras": len(observadas["trechos"]),
        "motivo_rollback": (None if promovido else
                            f"erro subiria de {erro_antes} para {erro_depois} min"),
    }


def exemplos_do_aprendizado(modelo: Modelo, inicial: Modelo,
                            paradas: dict, ausencias: dict) -> list:
    """Frases concretas para o painel — o que mudou e por quê."""
    exemplos = []
    for faixa, zonas in modelo.fatores.items():
        for zona, valor in zonas.items():
            antes = inicial.fator(faixa, zona)
            if abs(valor - antes) >= 0.05:
                direcao = "mais lento" if valor > antes else "mais rápido"
                exemplos.append(
                    f"Faixa “{faixa.replace('_', ' ')}” na zona {zona}: o "
                    f"planejamento supunha ×{antes:.2f} e a rua mostrou "
                    f"×{valor:.2f} — {direcao} do que o mapa dizia.")
    if paradas:
        pior = max(paradas.items(), key=lambda kv: kv[1])
        exemplos.append(
            f"Ponto {pior[0]}: o embarque leva {pior[1]:.1f} min a mais que o "
            f"previsto — a rota que passa por ele ganhou folga.")
    if ausencias:
        pior_dia = max(ausencias.items(), key=lambda kv: kv[1])
        dias = ["segunda", "terça", "quarta", "quinta", "sexta"]
        nome = dias[int(pior_dia[0]) % len(dias)]
        exemplos.append(
            f"{nome.capitalize()} tem {100 * pior_dia[1]:.1f}% de ausência: dá "
            f"para usar veículo menor sem deixar aluno em pé.")
    return exemplos[:5]
