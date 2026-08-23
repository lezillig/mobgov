# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 12 · agent-fiscalizacao
Do que foi medido para o que se paga.

`medicao.py` responde "o que aconteceu". Aqui responde "quanto vale", que é
outra pergunta e tem outro dono: a medição é técnica, o pagamento é jurídico.
Separar os dois é o que permite o fornecedor contestar o valor sem discutir o
fato, e a prefeitura corrigir a regra sem refazer a medição.

Os três modelos que aparecem em edital de transporte escolar no Brasil:

    km_rodado     R$ por quilômetro efetivamente rodado (o mais comum)
    viagem        R$ por viagem realizada
    veiculo_mes   R$ por veículo por mês (locação), com glosa proporcional

Regras que este módulo não abre mão:

* **nada é glosado sem evidência.** Viagem `sem_evidencia` não vira desconto:
  vira valor EM SUSPENSO, com nome de quem precisa decidir. É a diferença
  entre um sistema que a prefeitura usa e um que o fornecedor derruba no
  primeiro recurso;
* **toda glosa cita a viagem, o motivo e a evidência.** O relatório é peça de
  processo administrativo, não um número no fim da página;
* **o total é conferível na mão.** A memória de cálculo sai junto, linha a
  linha, como no painel de economia.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODELOS = ("km_rodado", "viagem", "veiculo_mes")


@dataclass
class RegrasDoContrato:
    """O que o edital diz — declarado, nunca embutido no código.

    `paga_por` é a pergunta que decide o valor do mês inteiro: o contrato
    paga a quilometragem PLANEJADA (o roteiro homologado) ou a MEDIDA (o que
    o GPS registrou)? Editais brasileiros usam os dois, e a diferença entre
    eles é justamente o que ninguém consegue auditar hoje.
    """
    modelo: str = "km_rodado"
    valor_km: float = 0.0
    valor_viagem: float = 0.0
    valor_veiculo_mes: float = 0.0
    paga_por: str = "planejado"          # "planejado" | "medido"
    tolerancia_atraso_min: int = 20
    glosa_atraso_pct: float = 10.0       # sobre o valor daquela viagem
    glosa_viagem_parcial_pct: float = 50.0
    dias_no_mes: int = 22
    observacoes: list = field(default_factory=list)

    def como_dicionario(self) -> dict:
        return dict(self.__dict__)


def _valor_da_viagem(medida: dict, regras: RegrasDoContrato) -> float:
    if regras.modelo == "viagem":
        return regras.valor_viagem
    if regras.modelo == "km_rodado":
        km = medida.get("km_medido") if regras.paga_por == "medido" \
            else medida.get("km_planejado")
        # sem medida, o contrato que paga por medição não paga no escuro:
        # o valor fica zero e a viagem inteira vai para suspenso mais abaixo
        return (km or 0) * regras.valor_km
    return 0.0          # veiculo_mes não é por viagem; ver abaixo


def avaliar(medicao: dict, regras: RegrasDoContrato,
            veiculos_contratados: int = 0) -> dict:
    """Pagamento, glosa e suspenso a partir de uma medição de período."""
    if regras.modelo not in MODELOS:
        raise ValueError(f"Modelo de contrato desconhecido: {regras.modelo!r}. "
                         f"Esperado um de: {', '.join(MODELOS)}.")

    itens, glosas, suspensos = [], [], []
    devido = 0.0

    for medida in medicao.get("viagens", []):
        valor = _valor_da_viagem(medida, regras)
        situacao = medida["situacao"]

        if situacao == "sem_evidencia":
            suspensos.append({
                "viagem": medida["viagem"], "valor": round(valor, 2),
                "motivo": medida["motivo"],
                "quem_decide": "fiscal do contrato",
                "acao": "Confirmar com o fornecedor se a viagem rodou",
            })
            continue

        if situacao == "nao_realizada":
            glosas.append({
                "viagem": medida["viagem"], "valor": round(valor, 2),
                "tipo": "viagem não realizada", "motivo": medida["motivo"],
                "evidencia": medida["evidencia"],
            })
            continue

        pagar = valor
        if situacao == "parcial":
            corte = valor * regras.glosa_viagem_parcial_pct / 100
            pagar -= corte
            glosas.append({
                "viagem": medida["viagem"], "valor": round(corte, 2),
                "tipo": f"viagem parcial ({regras.glosa_viagem_parcial_pct:g}%)",
                "motivo": medida["motivo"],
                "evidencia": medida["evidencia"],
            })
        elif (medida.get("atraso_min") is not None
              and medida["atraso_min"] > regras.tolerancia_atraso_min):
            corte = valor * regras.glosa_atraso_pct / 100
            pagar -= corte
            glosas.append({
                "viagem": medida["viagem"], "valor": round(corte, 2),
                "tipo": f"atraso ({regras.glosa_atraso_pct:g}%)",
                "motivo": f"Chegou {medida['atraso_min']} min depois do "
                          f"horário, acima da tolerância de "
                          f"{regras.tolerancia_atraso_min} min.",
                "evidencia": medida["evidencia"],
            })

        devido += pagar
        itens.append({"viagem": medida["viagem"], "valor": round(pagar, 2)})

    if regras.modelo == "veiculo_mes":
        devido, glosas = _por_veiculo_mes(medicao, regras, veiculos_contratados,
                                          glosas)

    total_glosa = round(sum(g["valor"] for g in glosas), 2)
    total_suspenso = round(sum(s["valor"] for s in suspensos), 2)
    resumo = medicao.get("resumo", {})

    return {
        "modelo": regras.modelo,
        "regras": regras.como_dicionario(),
        "a_pagar": round(devido, 2),
        "glosa": total_glosa,
        "em_suspenso": total_suspenso,
        "glosas": sorted(glosas, key=lambda g: -g["valor"]),
        "suspensos": suspensos,
        "itens": itens,
        "cobertura_pct": resumo.get("cobertura_pct"),
        "memoria": _memoria(resumo, regras, devido, total_glosa,
                            total_suspenso, veiculos_contratados),
        "alertas": _alertas(resumo, regras),
    }


def _por_veiculo_mes(medicao, regras, veiculos_contratados, glosas):
    """Locação: paga por veículo-mês, com desconto proporcional ao que faltou.

    A conta é a única honesta aqui: o contrato paga disponibilidade, então a
    glosa é a fração de viagens não realizadas sobre as planejadas — sem
    contar as sem evidência, que não entram nem como falta nem como serviço.
    """
    resumo = medicao.get("resumo", {})
    bruto = veiculos_contratados * regras.valor_veiculo_mes
    apuraveis = (resumo.get("viagens_planejadas", 0)
                 - resumo.get("sem_evidencia", 0))
    faltaram = resumo.get("nao_realizadas", 0)
    if apuraveis > 0 and faltaram:
        corte = bruto * faltaram / apuraveis
        glosas = glosas + [{
            "viagem": "—", "valor": round(corte, 2),
            "tipo": "indisponibilidade",
            "motivo": f"{faltaram} de {apuraveis} viagens apuráveis não foram "
                      f"realizadas ({100 * faltaram / apuraveis:.1f}% do mês).",
            "evidencia": {"eventos": None, "por_tipo": {}},
        }]
        return bruto - corte, glosas
    return bruto, glosas


def _memoria(resumo, regras, devido, glosa, suspenso, veiculos) -> list:
    linhas = [f"Modelo do contrato: {regras.modelo}."]
    if regras.modelo == "km_rodado":
        km = (resumo.get("km_medido") if regras.paga_por == "medido"
              else resumo.get("km_planejado"))
        linhas.append(
            f"Paga por quilometragem {regras.paga_por}: {km or 0} km × "
            f"R$ {regras.valor_km:.2f}/km.")
        if (resumo.get("km_medido") is not None
                and resumo.get("km_planejado")):
            dif = resumo["km_medido"] - resumo["km_planejado"]
            linhas.append(
                f"Planejado {resumo['km_planejado']} km, medido "
                f"{resumo['km_medido']} km ({dif:+.1f} km) — a diferença é "
                f"informação, não erro: rua fechada, desvio e ponto novo "
                f"mudam o percurso.")
    elif regras.modelo == "viagem":
        linhas.append(
            f"{resumo.get('realizadas', 0)} viagens realizadas × "
            f"R$ {regras.valor_viagem:.2f}.")
    else:
        linhas.append(
            f"{veiculos} veículos × R$ {regras.valor_veiculo_mes:.2f}/mês.")
    linhas.append(f"Glosa apurada: R$ {glosa:.2f}.")
    if suspenso:
        linhas.append(
            f"Em suspenso: R$ {suspenso:.2f} — viagens sem evidência, que NÃO "
            f"são glosa. Alguém precisa confirmar antes de descontar.")
    linhas.append(f"Valor a pagar: R$ {devido:.2f}.")
    return linhas


def _alertas(resumo, regras) -> list:
    """O que compromete a própria medição, dito antes do número."""
    alertas = []
    cobertura = resumo.get("cobertura_pct") or 0
    if cobertura < 70:
        alertas.append(
            f"Só {cobertura:.0f}% das viagens têm evidência. Com essa "
            f"cobertura a medição não sustenta glosa: primeiro resolva o "
            f"envio dos aparelhos, depois discuta desconto.")
    if (regras.paga_por == "medido"
            and resumo.get("viagens_com_km_medido", 0)
            < resumo.get("viagens_planejadas", 0)):
        alertas.append(
            "O contrato paga por quilometragem medida, mas parte das viagens "
            "não tem rastro suficiente para medir. Essas ficam em suspenso — "
            "pagar por medição que não existe seria pagar no escuro.")
    if resumo.get("km_medido_e_piso") and regras.paga_por == "medido":
        alertas.append(
            "O rastro de GPS chega esparso demais em parte das viagens. A "
            "quilometragem medida aí é PISO, não medida: somar retas entre "
            "pings distantes corta as curvas e sempre dá menos do que o "
            "veículo rodou. Pagar por ela é pagar a menos por defeito de "
            "aparelho — aumente a frequência do envio antes de usar este "
            "número para pagamento.")
    if resumo.get("sem_evidencia"):
        alertas.append(
            f"{resumo['sem_evidencia']} viagens sem nenhum evento. Isso é "
            f"fila de decisão humana, não falta comprovada.")
    return alertas
