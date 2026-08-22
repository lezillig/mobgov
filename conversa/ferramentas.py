# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-conversa
As ferramentas que o assistente pode chamar — e a única fonte de números.

A regra do projeto é dura e não tem exceção: **o modelo de linguagem nunca
inventa número**. Ele escolhe a ferramenta e escreve a frase; o valor sai
daqui, do mesmo motor que gera o painel e o PDF de prestação de contas. Se o
assistente disser "R$ 141 mil por mês", esse número passou por
`painel/economia.py` — não por uma estimativa plausível.

Duas consequências práticas:

1. **Sem chave de API o assistente continua funcionando.** As ferramentas são
   Python puro; o que o LLM acrescenta é entender a pergunta. Na demonstração
   em prefeitura, sem internet, um roteador por palavras-chave escolhe a
   ferramenta e a resposta sai igual.
2. **Nenhum dado pessoal sai daqui.** As ferramentas devolvem agregados e
   identificadores pseudonimizados. Nome de aluno não entra em prompt.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import economia as economia_mod  # noqa: E402
from painel.formato import numero  # noqa: E402

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict
    funcao: callable
    exemplos: list = field(default_factory=list)

    def esquema(self) -> dict:
        """Formato de tool use da API da Anthropic."""
        return {"name": self.nome, "description": self.descricao,
                "input_schema": self.parametros}


def _painel(diesel=None, dias=None) -> dict:
    rel = economia_mod.carregar_relatorio()
    premissas = economia_mod.premissas_do_relatorio(rel).substituir(
        preco_diesel_l=diesel, dias_letivos_mes=dias)
    return economia_mod.montar_painel(rel, premissas, com_cenarios=False)


def _opcional(nome: str) -> dict:
    return economia_mod.carregar_opcional(os.path.join(DIR_RELATORIOS, nome))


# ------------------------------------------------------------- ferramentas ---
def consultar_indicadores() -> dict:
    """Os números da manchete: frota, custo, km, litros, CO2."""
    p = _painel()
    return {
        "municipio": p["municipio"],
        "frota_atual": p["atual"]["total_veiculos"],
        "frota_necessaria": p["otimizada"]["total_veiculos"],
        "reducao_frota_pct": p["economia"]["reducao_frota_pct"],
        "custo_atual_mes": p["atual"]["custo_mes"],
        "custo_necessario_mes": p["otimizada"]["custo_mes"],
        "economia_mes": p["economia"]["custo_mes"],
        "economia_ano": p["economia"]["custo_ano"],
        "km_dia_economizados": p["economia"]["km_dia"],
        "litros_dia_economizados": p["economia"]["litros_dia"],
        "tco2_ano_evitadas": p["economia"]["tco2_ano"],
        "alunos": p["demanda"]["alunos"],
        "viagens": p["qualidade"]["viagens"],
        "ocupacao_media_pct": p["qualidade"]["ocupacao_media_pct"],
        "gerado_em": p["gerado_em"],
    }


def dimensionar_frota() -> dict:
    """Quantos veículos de cada tipo, e por quê."""
    p = _painel()
    return {
        "frota_atual": [{"tipo": l["nome"], "quantidade": l["qtd"]}
                        for l in p["atual"]["composicao"]],
        "frota_necessaria": [{"tipo": l["nome"], "quantidade": l["qtd"]}
                             for l in p["otimizada"]["composicao"]],
        "viagens_por_veiculo_turno": p["qualidade"]["viagens_por_veiculo_turno"],
        "por_turno": p["qualidade"]["por_turno"],
        "tempo_max_trajeto_min": p["premissas"]["tempo_max_trajeto_min"],
        "explicacao": (
            f"A frota necessária é {p['otimizada']['total_veiculos']} veículos "
            f"porque cada um encadeia "
            f"{numero(p['qualidade']['viagens_por_veiculo_turno'], 2)} "
            f"viagens por turno "
            f"dentro da jornada disponível antes do sinal, respeitando o limite "
            f"de {p['premissas']['tempo_max_trajeto_min']} minutos por aluno. "
            f"O número é o pior caso entre os turnos, não a soma deles."),
    }


def simular_cenario(preco_diesel: float = None, dias_letivos: int = None) -> dict:
    """E se o diesel subir, ou o calendário mudar?"""
    base = _painel()
    novo = _painel(diesel=preco_diesel, dias=dias_letivos)
    return {
        "premissas_alteradas": {"preco_diesel_l": preco_diesel,
                                "dias_letivos_mes": dias_letivos},
        "economia_mes_base": base["economia"]["custo_mes"],
        "economia_mes_cenario": novo["economia"]["custo_mes"],
        "diferenca_mes": round(novo["economia"]["custo_mes"]
                               - base["economia"]["custo_mes"], 2),
        "custo_atual_mes": novo["atual"]["custo_mes"],
        "custo_necessario_mes": novo["otimizada"]["custo_mes"],
    }


def explicar_rota(viagem: str = None) -> dict:
    """Por que esta viagem existe e o que ela faz."""
    rel = economia_mod.carregar_relatorio()
    viagens = rel["frota_otimizada"]["viagens"]
    escolhida = next((v for v in viagens if v["id"] == viagem), None)
    if escolhida is None:
        escolhida = max(viagens, key=lambda v: v["alunos"])
    veiculo = next((v for v in rel["frota_otimizada"]["veiculos"]
                    if escolhida["id"] in v["viagens"]), {})
    return {
        "viagem": escolhida["id"],
        "escola": escolhida["escola"],
        "turno": escolhida["turno_nome"],
        "alunos": escolhida["alunos"],
        "cadeirantes": escolhida["cadeirantes"],
        "paradas": len(escolhida["paradas"]),
        "km": escolhida["km_viagem"],
        "minutos": escolhida["min_viagem"],
        "ocupacao_pct": escolhida["ocupacao_pct"],
        "veiculo": escolhida.get("tipo_nome"),
        "veiculo_id": veiculo.get("id"),
        "outras_viagens_do_veiculo": [v for v in veiculo.get("viagens", [])
                                      if v != escolhida["id"]],
        "explicacao": (
            f"A viagem {escolhida['id']} usa um {escolhida.get('tipo_nome')} "
            f"porque leva {escolhida['alunos']} alunos "
            f"({escolhida['cadeirantes']} em cadeira de rodas) e o veículo "
            f"menor que atenderia essa combinação não comportaria a demanda "
            f"nem as posições de cadeira."),
    }


def estado_da_operacao() -> dict:
    """O que já aconteceu hoje: eventos do app, faltas, reotimizações."""
    from operacao import registro
    resumo = registro.resumo()
    reot = _opcional("reotimizacao.json").get("resumo", {})
    return {"eventos_recebidos": resumo, "reotimizacoes_do_dia": reot}


def qualidade_da_importacao() -> dict:
    """Como está o dado que entrou — erros e avisos da planilha."""
    imp = _opcional("importacao.json")
    if not imp.get("resumo"):
        return {"aviso": "Nenhuma planilha importada ainda. Rode: "
                         "python motor/importar.py <planilha.xlsx>"}
    resposta = dict(imp["resumo"])
    resposta["arquivo"] = imp.get("arquivo")
    resposta["gerado_em"] = imp.get("gerado_em")
    # Os problemas vêm linha a linha; o gestor quer saber o que MAIS apareceu.
    contagem = {}
    for p in imp.get("problemas", []):
        chave = (p.get("gravidade", "aviso"), p.get("problema", ""))
        contagem[chave] = contagem.get(chave, 0) + 1
    resposta["problemas_mais_comuns"] = [
        {"gravidade": gravidade, "problema": texto, "ocorrencias": qtd}
        for (gravidade, texto), qtd in sorted(contagem.items(),
                                              key=lambda par: -par[1])[:6]]
    return resposta


def elegibilidade_pcd() -> dict:
    """Como está a fila de quem pede o porta a porta."""
    el = _opcional("elegibilidade.json")
    if not el.get("resumo"):
        return {"aviso": "Ainda não há fila de elegibilidade. Rode: "
                         "python elegibilidade/relatorio.py"}
    resumo = dict(el["resumo"])
    resumo.update({
        "selo": el.get("selo"),
        "origem": el.get("origem"),
        "decisoes_com_analista_pct": el.get("decisoes_com_analista_pct"),
        "aprovacoes_sem_laudo_pct": el.get("aprovacoes_sem_laudo_pct"),
        "usuarios_para_roteirizacao": el.get("usuarios_para_roteirizacao"),
        "fontes": el.get("fontes", []),
    })
    return resumo


def o_que_o_sistema_aprendeu() -> dict:
    """Evolução do erro de previsão e o que mudou no modelo."""
    from painel import aprendizado as aprendizado_mod
    serie = aprendizado_mod.carregar_serie()
    return {
        "origem": serie.get("origem"),
        "selo": serie.get("selo"),
        "erro_inicial_min": serie.get("erro_inicial_min"),
        "erro_atual_min": serie.get("erro_atual_min"),
        "queda_erro_pct": serie.get("queda_erro_pct"),
        "versao_modelo": serie.get("versao_modelo"),
        "rollbacks": serie.get("rollbacks"),
        "exemplos": serie.get("exemplos", [])[:3],
    }


def gerar_relatorio(saida: str = None) -> dict:
    """Gera o painel em HTML, pronto para virar PDF."""
    from painel import render
    destino = render.gerar(saida=saida) if saida else render.gerar()
    return {"arquivo": destino,
            "como_usar": "Abra no navegador e use 'Salvar em PDF / imprimir' "
                         "para a prestação de contas."}


# ---------------------------------------------------------------- registro ---
CATALOGO = [
    Ferramenta(
        "consultar_indicadores",
        "Números da economia: frota atual e necessária, custo por mês e por "
        "ano, km, litros e CO2 evitados. Use para qualquer pergunta sobre "
        "quanto se economiza ou qual o tamanho da frota.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: consultar_indicadores(),
        ["quanto eu economizo por mês?", "qual a economia anual?",
         "quantos veículos preciso?"]),
    Ferramenta(
        "dimensionar_frota",
        "Composição da frota por tipo de veículo, viagens por veículo em cada "
        "turno e a explicação de por que esse é o número mínimo.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: dimensionar_frota(),
        ["por que preciso desse tanto de ônibus?",
         "qual a composição da frota?"]),
    Ferramenta(
        "simular_cenario",
        "Recalcula a economia com outro preço de diesel ou outro número de "
        "dias letivos no mês.",
        {"type": "object",
         "properties": {
             "preco_diesel": {"type": "number",
                              "description": "preço do litro em reais"},
             "dias_letivos": {"type": "integer",
                              "description": "dias letivos no mês"}},
         "required": []},
        lambda **kw: simular_cenario(kw.get("preco_diesel"),
                                     kw.get("dias_letivos")),
        ["e se o diesel for a R$ 8?", "e com 20 dias letivos?"]),
    Ferramenta(
        "explicar_rota",
        "Detalha uma viagem: escola, alunos, paradas, km, tempo, veículo — e "
        "por que aquele tipo de veículo foi escolhido.",
        {"type": "object",
         "properties": {"viagem": {"type": "string",
                                   "description": "id da viagem, ex. E1-manha-03"}},
         "required": []},
        lambda **kw: explicar_rota(kw.get("viagem")),
        ["por que a rota E1-manha-03 usa uma van?",
         "me explica a maior rota"]),
    Ferramenta(
        "estado_da_operacao",
        "O que aconteceu hoje: eventos recebidos do app do motorista, "
        "reotimizações, km poupados.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: estado_da_operacao(),
        ["como está a operação hoje?", "teve falta hoje?"]),
    Ferramenta(
        "qualidade_da_importacao",
        "Resultado da última importação de planilha: alunos importados, "
        "erros, avisos e quantos endereços precisam de ajuste no mapa.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: qualidade_da_importacao(),
        ["a planilha entrou direito?", "quantos erros teve na importação?"]),
    Ferramenta(
        "elegibilidade_pcd",
        "Fila de elegibilidade ao transporte porta a porta: pedidos em "
        "aberto, atrasados, aprovados, negados, concessões permanentes e "
        "quantas aprovações dispensaram laudo em papel.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: elegibilidade_pcd(),
        ["como está a fila do porta a porta?",
         "quantos pedidos de PCD estão atrasados?"]),
    Ferramenta(
        "o_que_o_sistema_aprendeu",
        "Evolução do aprendizado: erro de previsão de tempo, versão do modelo, "
        "rollbacks e exemplos do que mudou.",
        {"type": "object", "properties": {}, "required": []},
        lambda **_: o_que_o_sistema_aprendeu(),
        ["o que o sistema aprendeu?", "o erro de previsão está caindo?"]),
    Ferramenta(
        "gerar_relatorio",
        "Gera o painel de economia em HTML para virar PDF de prestação de "
        "contas.",
        {"type": "object",
         "properties": {"saida": {"type": "string",
                                  "description": "caminho do arquivo de saída"}},
         "required": []},
        lambda **kw: gerar_relatorio(kw.get("saida")),
        ["gere o relatório para o tribunal de contas"]),
]

POR_NOME = {f.nome: f for f in CATALOGO}


def executar(nome: str, argumentos: dict = None) -> dict:
    """Executa a ferramenta e devolve o resultado — ou um erro explicado."""
    ferramenta = POR_NOME.get(nome)
    if not ferramenta:
        return {"erro": f"Ferramenta desconhecida: {nome}.",
                "disponiveis": sorted(POR_NOME)}
    try:
        return ferramenta.funcao(**(argumentos or {}))
    except FileNotFoundError:
        return {"erro": "Ainda não existe relatório para consultar. Rode "
                        "antes: python motor/dimensionar.py"}
    except Exception as erro:                     # nunca derruba a conversa
        return {"erro": f"A ferramenta {nome} falhou: {erro}"}


def esquemas() -> list:
    """Definições no formato que a API da Anthropic espera em `tools`."""
    return [f.esquema() for f in CATALOGO]


def catalogo_em_texto() -> str:
    return "\n".join(f"- {f.nome}: {f.descricao}" for f in CATALOGO)


if __name__ == "__main__":
    print(catalogo_em_texto())
    print()
    print(json.dumps(consultar_indicadores(), ensure_ascii=False, indent=2))
