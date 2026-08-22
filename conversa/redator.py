# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-conversa
Transforma o resultado de uma ferramenta em resposta escrita em português.

Este módulo é a prova de que a camada conversacional não precisa do LLM para
responder certo. Cada frase aqui é montada a partir do dicionário que a
ferramenta devolveu — não há texto inventado, e todo número aparece formatado
do mesmo jeito que no painel (R$ 141.122, 23,3%, 1.287 km).

Quando existe chave de API, o LLM reescreve a resposta com mais jeito de
conversa — mas recebe exatamente estes números e é proibido de mexer neles.
"""
from __future__ import annotations

from painel.formato import numero, pct, reais, reais_curto


def _linha(rotulo: str, valor: str) -> str:
    return f"• {rotulo}: {valor}"


def indicadores(d: dict) -> str:
    return "\n".join([
        f"Em {d['municipio']}, a rota otimizada precisa de "
        f"{d['frota_necessaria']} veículos no lugar de {d['frota_atual']} — "
        f"{pct(d['reducao_frota_pct'])} a menos.",
        "",
        _linha("Economia por mês", reais(d["economia_mes"], 2)),
        _linha("Economia por ano", f"{reais_curto(d['economia_ano'])} "
                                   f"({reais(d['economia_ano'], 2)})"),
        _linha("Custo hoje", f"{reais(d['custo_atual_mes'], 2)}/mês"),
        _linha("Custo otimizado", f"{reais(d['custo_necessario_mes'], 2)}/mês"),
        _linha("Quilometragem poupada", f"{numero(d['km_dia_economizados'], 1)} km/dia"),
        _linha("Diesel poupado", f"{numero(d['litros_dia_economizados'], 1)} L/dia"),
        _linha("CO₂ evitado", f"{numero(d['tco2_ano_evitadas'], 1)} t/ano"),
        "",
        f"São {numero(d['alunos'])} alunos em {d['viagens']} viagens por dia, "
        f"com ocupação média de {pct(d['ocupacao_media_pct'])}. "
        f"Números do plano gerado em {d['gerado_em']}.",
    ])


def frota(d: dict) -> str:
    def tabela(itens):
        return "\n".join(_linha(i["tipo"], f"{i['quantidade']}") for i in itens)

    partes = ["Frota que o município declara hoje:", tabela(d["frota_atual"]),
              "", "Frota necessária pelo plano otimizado:",
              tabela(d["frota_necessaria"]), "", d["explicacao"]]
    if d.get("por_turno"):
        partes += ["", "Por turno:"]
        for turno in d["por_turno"]:
            partes.append(_linha(
                turno.get("nome", turno.get("turno", "")),
                f"{turno.get('veiculos', '?')} veículos, "
                f"{turno.get('viagens', '?')} viagens"))
    return "\n".join(partes)


def cenario(d: dict) -> str:
    mudou = d["premissas_alteradas"]
    ditas = []
    if mudou.get("preco_diesel_l"):
        ditas.append(f"diesel a {reais(mudou['preco_diesel_l'], 2)}/L")
    if mudou.get("dias_letivos_mes"):
        ditas.append(f"{mudou['dias_letivos_mes']} dias letivos no mês")
    cabecalho = "Cenário: " + (" e ".join(ditas) if ditas else "sem alteração")

    diferenca = d["diferenca_mes"]
    if diferenca > 0:
        veredito = (f"A economia AUMENTA {reais(diferenca, 2)} por mês nesse "
                    f"cenário.")
    elif diferenca < 0:
        veredito = (f"A economia CAI {reais(abs(diferenca), 2)} por mês nesse "
                    f"cenário.")
    else:
        veredito = "A economia não muda nesse cenário."
    return "\n".join([
        cabecalho, "",
        _linha("Economia hoje", f"{reais(d['economia_mes_base'], 2)}/mês"),
        _linha("Economia no cenário", f"{reais(d['economia_mes_cenario'], 2)}/mês"),
        _linha("Custo sem otimizar", f"{reais(d['custo_atual_mes'], 2)}/mês"),
        _linha("Custo otimizado", f"{reais(d['custo_necessario_mes'], 2)}/mês"),
        "", veredito,
    ])


def rota(d: dict) -> str:
    linhas = [
        f"Viagem {d['viagem']} — {d['escola']} ({d['turno']}).", "",
        _linha("Alunos", f"{d['alunos']} ({d['cadeirantes']} em cadeira de rodas)"),
        _linha("Paradas", str(d["paradas"])),
        _linha("Distância", f"{numero(d['km'], 1)} km"),
        _linha("Duração", f"{numero(d['minutos'], 0)} min"),
        _linha("Veículo", f"{d.get('veiculo')} ({d.get('veiculo_id')})"),
    ]
    if d.get("ocupacao_pct") is not None:
        linhas.append(_linha("Ocupação", pct(d["ocupacao_pct"])))
    if d.get("outras_viagens_do_veiculo"):
        linhas.append(_linha("O mesmo veículo ainda faz",
                             ", ".join(d["outras_viagens_do_veiculo"])))
    return "\n".join(linhas + ["", d["explicacao"]])


def operacao(d: dict) -> str:
    eventos = d.get("eventos_recebidos") or {}
    por_tipo = eventos.get("por_tipo") or {}
    if not por_tipo:
        texto = ["Nenhum evento recebido do app do motorista ainda hoje."]
    else:
        texto = ["Eventos recebidos do app do motorista:"]
        texto += [_linha(tipo, numero(qtd)) for tipo, qtd in sorted(por_tipo.items())]
    reot = d.get("reotimizacoes_do_dia") or {}
    if reot:
        texto += ["", "Reotimizações do dia:"]
        for rotulo, chave, casas, sufixo in (
                ("Eventos tratados", "eventos", 0, ""),
                ("Pedidos avaliados", "pedidos_avaliados", 0, ""),
                ("Pedidos aceitos", "pedidos_aceitos", 0, ""),
                ("Km economizados", "km_economizados", 1, " km"),
                ("Pior tempo de resposta", "tempo_max_s", 3, " s")):
            if chave in reot:
                texto.append(_linha(rotulo,
                                    f"{numero(reot[chave], casas)}{sufixo}"))
    return "\n".join(texto)


def importacao(d: dict) -> str:
    if d.get("aviso"):
        return d["aviso"]
    linhas = ["Última importação da planilha da secretaria"]
    if d.get("arquivo"):
        linhas[0] += f" ({d['arquivo']})"
    linhas[0] += ":"
    linhas.append("")
    for rotulo, chave in (("Alunos importados", "alunos_importados"),
                          ("Erros (a linha não entrou)", "erros"),
                          ("Avisos (entrou, mas confira)", "avisos"),
                          ("Precisam de ajuste no mapa", "precisam_ajuste_no_mapa"),
                          ("Cadeirantes", "cadeirantes"),
                          ("Com acompanhante", "acompanhantes")):
        if chave in d:
            linhas.append(_linha(rotulo, numero(d[chave])))
    if d.get("por_turno"):
        linhas.append(_linha("Por turno", ", ".join(
            f"{turno}: {numero(qtd)}" for turno, qtd in sorted(d["por_turno"].items()))))
    if d.get("problemas_mais_comuns"):
        linhas += ["", "O que mais apareceu:"]
        linhas += [f"• [{p['gravidade']}] {p['problema']} ({p['ocorrencias']}x)"
                   for p in d["problemas_mais_comuns"]]
    return "\n".join(linhas)


def elegibilidade(d: dict) -> str:
    if d.get("aviso"):
        return d["aviso"]
    estados = d.get("por_estado") or {}
    linhas = [
        f"[{d.get('selo')}] {numero(d['pedidos'])} pedidos de porta a porta, "
        f"{numero(d['em_aberto'])} em aberto e {numero(d['atrasados'])} fora "
        f"do prazo de {d['prazo_dias']} dias.", "",
        _linha("Média de dias em aberto", numero(d["dias_em_aberto_media"], 1)),
        _linha("Aprovados", numero(d.get("aprovados", 0))),
        _linha("Negados", numero(d.get("negados", 0))),
        _linha("Concessões permanentes (não renovam todo ano)",
               numero(d.get("permanentes", 0))),
        _linha("Vencendo em 30 dias", numero(d.get("a_vencer_30_dias", 0))),
    ]
    if d.get("decisoes_com_analista_pct") is not None:
        linhas.append(_linha("Decisões com analista identificado",
                             pct(d["decisoes_com_analista_pct"])))
    if d.get("aprovacoes_sem_laudo_pct") is not None:
        linhas.append(_linha("Aprovações sem laudo em papel",
                             pct(d["aprovacoes_sem_laudo_pct"])))
    if estados:
        linhas += ["", "Por situação:"]
        linhas += [_linha(estado, numero(qtd))
                   for estado, qtd in sorted(estados.items())]
    return "\n".join(linhas)


def aprendizado(d: dict) -> str:
    if d.get("erro_atual_min") is None:
        return "Ainda não há série de aprendizado para mostrar."
    linhas = [
        f"[{d.get('selo')}] O erro de previsão de tempo caiu de "
        f"{numero(d['erro_inicial_min'], 2)} min para "
        f"{numero(d['erro_atual_min'], 2)} min "
        f"({pct(d['queda_erro_pct'])} de queda).",
    ]
    if d.get("versao_modelo"):
        linhas.append(_linha("Versão do modelo", str(d["versao_modelo"])))
    if d.get("rollbacks"):
        linhas.append(_linha("Rollbacks (versões descartadas por piorarem)",
                             str(d["rollbacks"])))
    if d.get("exemplos"):
        linhas += ["", "Exemplos do que ele aprendeu:"]
        linhas += [f"• {e}" for e in d["exemplos"]]
    return "\n".join(linhas)


def relatorio(d: dict) -> str:
    return f"Relatório gerado em {d['arquivo']}.\n{d['como_usar']}"


ESCRITORES = {
    "consultar_indicadores": indicadores,
    "dimensionar_frota": frota,
    "simular_cenario": cenario,
    "explicar_rota": rota,
    "estado_da_operacao": operacao,
    "qualidade_da_importacao": importacao,
    "elegibilidade_pcd": elegibilidade,
    "o_que_o_sistema_aprendeu": aprendizado,
    "gerar_relatorio": relatorio,
}


def escrever(ferramenta: str, resultado: dict) -> str:
    """Resposta em português a partir do resultado bruto da ferramenta."""
    if not isinstance(resultado, dict):
        return str(resultado)
    if resultado.get("erro"):
        return resultado["erro"]
    escritor = ESCRITORES.get(ferramenta)
    if not escritor:
        return str(resultado)
    try:
        return escritor(resultado)
    except (KeyError, TypeError) as falha:
        # dado incompleto não pode virar resposta inventada — diz o que faltou
        return (f"Consegui rodar {ferramenta}, mas o relatório está sem o "
                f"campo {falha}. Rode de novo o dimensionamento para atualizar.")
