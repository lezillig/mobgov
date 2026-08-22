# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
O que o painel mostra sobre a elegibilidade — com selo de origem.

Mesma regra do resto do sistema: se o dado é real, diz que é real; se é
simulação, diz que é simulação, na tela, sem letra miúda. O painel de um
município não pode exibir número de demonstração com cara de medição.

Os indicadores foram escolhidos para responder às três perguntas que
aparecem na reunião:

  "quanto tempo demora?"        -> dias em aberto, atrasados, prazo assumido
  "quem decide?"                -> % de decisões com analista identificado
  "e o papel, acabou mesmo?"    -> % de aprovações que não exigiram laudo
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elegibilidade import fila  # noqa: E402
from elegibilidade.demonstracao import ARQUIVO_DEMO  # noqa: E402
from elegibilidade.formulario import FONTES_ACEITAS  # noqa: E402

SAIDA_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "elegibilidade.json")

SELOS = {
    "operacao_real": ("DADO DA OPERAÇÃO",
                      "Pedidos recebidos pelo formulário do município."),
    "simulacao": ("FILA SIMULADA",
                  "Casos gerados para a demonstração — nenhuma pessoa real."),
}

# Fontes que dispensam o laudo em papel: é este o número que responde à
# pergunta "acabou o papel?".
SEM_LAUDO = ("cadastro_municipal", "declaracao_escolar",
             "avaliacao_presencial", "renovacao")


def _origem(arquivo: str) -> tuple:
    if arquivo and os.path.exists(arquivo) and arquivo != ARQUIVO_DEMO:
        return arquivo, "operacao_real"
    return ARQUIVO_DEMO, "simulacao"


def montar(arquivo: str = None, hoje: str = None) -> dict:
    arquivo, origem = _origem(arquivo or fila.ARQUIVO_PADRAO)
    selo, explicacao = SELOS[origem]
    lista = fila.listar(arquivo, hoje=hoje)
    resumo = fila.resumo(arquivo, hoje=hoje)

    decisoes, com_analista, sem_laudo, com_sugestao = 0, 0, 0, 0
    fontes = {}
    for protocolo in fila.protocolos(arquivo):
        for evento in fila.ler_eventos(arquivo, protocolo):
            if evento["tipo"] not in ("aprovado", "negado", "revalidado"):
                continue
            decisoes += 1
            if evento.get("analista"):
                com_analista += 1
            if evento.get("sugestoes_aplicadas"):
                com_sugestao += 1
            for fonte in evento.get("fontes", []):
                fontes[fonte] = fontes.get(fonte, 0) + 1
                if fonte in SEM_LAUDO:
                    sem_laudo += 1

    aprovacoes = max(1, resumo["aprovados"])
    return {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "origem": origem,
        "selo": selo,
        "explicacao_selo": explicacao,
        "resumo": resumo,
        "decisoes": decisoes,
        "decisoes_com_analista_pct": round(100 * com_analista / max(1, decisoes), 1),
        "aprovacoes_sem_laudo_pct": round(100 * sem_laudo / aprovacoes, 1),
        "aprovacoes_com_leitura_assistida_pct": round(
            100 * com_sugestao / aprovacoes, 1),
        "fontes": [{"fonte": f, "rotulo": FONTES_ACEITAS.get(f, f),
                    "decisoes": q}
                   for f, q in sorted(fontes.items(), key=lambda p: -p[1])],
        "a_vencer_30_dias": fila.a_vencer(30, arquivo, hoje),
        "fila": [{k: s[k] for k in ("protocolo", "estado",
                                    "estado_em_portugues", "aberto_em",
                                    "prazo_ate", "atrasado", "dias_em_aberto",
                                    "bairro", "destino", "resumo_do_perfil",
                                    "analista", "permanente", "vence_em")}
                 for s in lista],
        "usuarios_para_roteirizacao": len(
            fila.demanda_para_roteirizacao(arquivo, hoje)),
    }


def gerar(arquivo: str = None, saida: str = SAIDA_PADRAO,
          hoje: str = None) -> str:
    relatorio = montar(arquivo, hoje)
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=1)
    return saida


if __name__ == "__main__":
    print(f"Relatório de elegibilidade em {gerar()}")
