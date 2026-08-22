# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
Leitura assistida do documento — que sugere, e nunca decide.

O documento que a família anexa (laudo, relatório do AEE, declaração) é texto
corrido escrito por outra profissão. Ler cem desses por semana é o gargalo da
secretaria; foi por isso que a fila virou meses.

Este módulo lê e propõe. Cada proposta vem com três coisas:

    campo sugerido · o trecho exato que a sustenta · a confiança

Nada entra no perfil sem alguém clicar. É decisão administrativa sobre
direito de uma pessoa com deficiência: tem que ter nome de quem decidiu.

Duas travas que valem para o modo com IA:

1. **Toda sugestão precisa de trecho literal do documento.** Se o modelo
   devolver uma justificativa que não está escrita ali, a sugestão é
   descartada — é alucinação, e alucinação sobre laudo é grave.
2. **CID e diagnóstico não viram restrição.** O código é detectado para o
   analista ver, marcado como dado sensível, e nunca é traduzido
   automaticamente em necessidade. Duas pessoas com o mesmo CID podem ter
   necessidades opostas de transporte.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CID = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d)?)\b")


@dataclass
class Sugestao:
    campo: str
    valor: object
    confianca: float
    trecho: str
    porque: str

    def como_dicionario(self) -> dict:
        return {"campo": self.campo, "valor": self.valor,
                "confianca": self.confianca, "trecho": self.trecho,
                "porque": self.porque}


@dataclass
class Extracao:
    sugestoes: list = field(default_factory=list)
    codigos_sensiveis: list = field(default_factory=list)
    alertas: list = field(default_factory=list)
    origem: str = "regras"

    def por_campo(self) -> dict:
        """Uma sugestão por campo — fica a de maior confiança."""
        melhor = {}
        for s in self.sugestoes:
            if s.campo not in melhor or s.confianca > melhor[s.campo].confianca:
                melhor[s.campo] = s
        return melhor

    def para_aprovacao(self) -> list:
        """O que a tela do analista mostra, em ordem de confiança."""
        return [s.como_dicionario()
                for s in sorted(self.por_campo().values(),
                                key=lambda s: -s.confianca)]


# Cada regra: (campo, valor, confiança, padrão, por quê).
# A confiança é honesta: "usa cadeira de rodas" escrito com todas as letras é
# 0,95; inferir isolamento a partir de um diagnóstico é 0,4 e existe só para
# o analista olhar — nunca para entrar sozinho.
REGRAS = [
    ("cadeira_de_rodas", True, 0.95,
     r"cadeira de rodas|cadeirante", "o documento cita cadeira de rodas"),
    ("cadeira_motorizada", True, 0.9,
     r"cadeira (de rodas )?(motorizada|el[eé]trica)",
     "o documento cita cadeira motorizada"),
    ("elevador_ou_rampa", True, 0.85,
     r"plataforma elevat[oó]ria|elevador veicular|acesso por rampa|"
     r"ve[ií]culo adaptado",
     "o documento cita acesso por plataforma ou rampa"),
    ("porta_a_porta", True, 0.9,
     r"n[ãa]o deambula|sem deambula[çc][ãa]o|acamad[oa]|"
     r"impossibilidade de locomo[çc][ãa]o|n[ãa]o se locomove",
     "o documento diz que a pessoa não se locomove sozinha"),
    ("porta_a_porta", True, 0.7,
     r"mobilidade reduzida|deambula com (aux[ií]lio|apoio|andador)|"
     r"dificuldade de locomo[çc][ãa]o",
     "o documento cita mobilidade reduzida"),
    ("acompanhante", True, 0.9,
     r"necessita de acompanhante|acompanhante em tempo integral|"
     r"acompanhamento permanente|n[ãa]o pode (ficar|permanecer) sozinh[oa]",
     "o documento indica necessidade de acompanhante"),
    ("auxilio_no_embarque", True, 0.8,
     r"aux[ií]lio para (transfer[êe]ncia|embarque|entrar)|"
     r"transfer[êe]ncia assistida|necessita de apoio para (subir|entrar)",
     "o documento cita auxílio na transferência"),
    ("cinto_de_quatro_pontos", True, 0.85,
     r"cinto de (quatro|4) pontos|conten[çc][ãa]o (postural|no ve[ií]culo)|"
     r"colete postural",
     "o documento cita contenção ou cinto específico"),
    ("evitar_lotacao", True, 0.55,
     r"hipersensibilidade (auditiva|sensorial)|sobrecarga sensorial|"
     r"crise em ambiente (com muitas pessoas|barulhento)|"
     r"evitar (aglomera[çc][ãa]o|ambientes lotados)",
     "o documento cita sensibilidade a ambiente cheio ou barulhento"),
]

# Diagnósticos frequentes que o analista costuma "traduzir" na cabeça. O
# sistema mostra o achado, mas com confiança baixa e sempre com a nota de que
# diagnóstico não é necessidade.
DIAGNOSTICOS = re.compile(
    r"transtorno do espectro autista|\bTEA\b|autis|paralisia cerebral|"
    r"s[ií]ndrome de down|distrofia muscular|epilepsia|defici[êe]ncia visual",
    re.IGNORECASE)

# O gancho e o número raramente ficam colados: "não deve permanecer MAIS DE 40
# minutos", "tempo máximo DE ATÉ 40 minutos". Daí o vão de até 20 caracteres —
# que não atravessa linha, para não casar gancho de uma frase com número de
# outra.
TEMPO = re.compile(
    r"(?:n[ãa]o (?:deve|pode) permanecer|tempo m[áa]ximo|limite de|"
    r"no m[áa]ximo|at[ée])[^\d\n]{0,20}(\d{1,3})\s*(?:min\b|minutos)",
    re.IGNORECASE)

PESSOAS = re.compile(
    r"(?:no m[áa]ximo|at[ée]|limite de)\s*(\d{1,2})\s*(?:pessoas|passageiros|"
    r"crian[çc]as|usu[áa]rios)", re.IGNORECASE)


# Fim de frase é ponto SEGUIDO DE ESPAÇO — ou quebra de linha. O ponto de
# "CID G80.1" não termina frase nenhuma, e cortar ali entregava ao analista
# uma evidência que começava em "1), não deambula…".
_FIM_DE_FRASE = re.compile(r"[.!?](?=\s|$)|\n")


def _frase_de(texto: str, inicio: int, fim: int) -> str:
    """A frase inteira em volta do achado — evidência sem contexto não serve
    para o analista decidir."""
    esquerda = 0
    direita = len(texto)
    for marca in _FIM_DE_FRASE.finditer(texto):
        if marca.end() <= inicio:
            esquerda = marca.end()
        elif marca.start() >= fim:
            direita = marca.end()
            break
    return texto[esquerda:direita].strip()


def analisar(texto: str) -> Extracao:
    """Lê o documento e devolve sugestões com evidência. Sem IA, sem rede."""
    extracao = Extracao()
    if not (texto or "").strip():
        extracao.alertas.append("Documento vazio ou ilegível.")
        return extracao

    for campo, valor, confianca, padrao, porque in REGRAS:
        achado = re.search(padrao, texto, re.IGNORECASE)
        if achado:
            extracao.sugestoes.append(Sugestao(
                campo, valor, confianca,
                _frase_de(texto, achado.start(), achado.end()), porque))

    tempo = TEMPO.search(texto)
    if tempo:
        extracao.sugestoes.append(Sugestao(
            "tempo_max_bordo_min", int(tempo.group(1)), 0.8,
            _frase_de(texto, tempo.start(), tempo.end()),
            "o documento indica um limite de tempo em minutos"))

    pessoas = PESSOAS.search(texto)
    if pessoas:
        extracao.sugestoes.append(Sugestao(
            "max_passageiros_junto", int(pessoas.group(1)), 0.6,
            _frase_de(texto, pessoas.start(), pessoas.end()),
            "o documento indica um número máximo de pessoas junto"))

    for codigo in dict.fromkeys(CID.findall(texto)):
        extracao.codigos_sensiveis.append(codigo)
    diagnostico = DIAGNOSTICOS.search(texto)
    if extracao.codigos_sensiveis or diagnostico:
        extracao.alertas.append(
            "O documento traz diagnóstico. Diagnóstico é dado sensível de "
            "saúde: fica no processo, não vai para a rota, e não define "
            "sozinho nenhuma necessidade — duas pessoas com o mesmo "
            "diagnóstico podem precisar de coisas opostas.")
    if not extracao.sugestoes:
        extracao.alertas.append(
            "Não encontrei no documento nada que descreva necessidade de "
            "transporte. Vale conversar com a família ou marcar avaliação.")
    return extracao


# ------------------------------------------------------------- com modelo ---
INSTRUCAO_LLM = """Você lê um documento de saúde ou escolar e extrai APENAS
necessidades operacionais de transporte. Responda só com JSON:

{"sugestoes": [{"campo": "...", "valor": true, "confianca": 0.0,
                "trecho": "texto copiado LITERALMENTE do documento",
                "porque": "..."}]}

Campos possíveis: porta_a_porta, cadeira_de_rodas, cadeira_motorizada,
elevador_ou_rampa, acompanhante, auxilio_no_embarque,
cinto_de_quatro_pontos, evitar_lotacao (booleanos),
tempo_max_bordo_min, max_passageiros_junto (números inteiros).

Regras: o campo "trecho" tem que ser recorte literal do documento — se você
não achar a frase, não sugira. Não traduza diagnóstico em necessidade. Não
invente número. Se o documento não descrever necessidade nenhuma, devolva
{"sugestoes": []}."""


def _texto_da_resposta(resposta: dict) -> str:
    return "".join(b.get("text", "") for b in resposta.get("content", [])
                   if b.get("type") == "text")


def _so_com_evidencia(sugestoes: list, texto: str) -> tuple:
    """Descarta o que não tem trecho literal — é a trava anti-alucinação."""
    validas, descartadas = [], []
    alvo = " ".join((texto or "").lower().split())
    for item in sugestoes:
        trecho = str(item.get("trecho") or "")
        normalizado = " ".join(trecho.lower().split())
        if normalizado and normalizado in alvo:
            validas.append(item)
        else:
            descartadas.append(trecho or "(sem trecho)")
    return validas, descartadas


def analisar_com_modelo(texto: str, cliente) -> Extracao:
    """Mesma saída de `analisar`, com um modelo lendo o texto corrido.

    Cai para as regras se não houver cliente, se a API falhar ou se a resposta
    vier fora do contrato. O resultado do modelo NUNCA substitui o das regras:
    os dois entram na mesma lista, e quem aprova é gente.
    """
    base = analisar(texto)
    if cliente is None or not getattr(cliente, "configurado", lambda: False)():
        return base
    try:
        resposta = cliente.mensagem(
            [{"role": "user", "content": f"{INSTRUCAO_LLM}\n\nDOCUMENTO:\n{texto}"}],
            [], sistema="Você extrai necessidades de transporte de documentos.")
        bruto = _texto_da_resposta(resposta)
        dados = json.loads(bruto[bruto.find("{"):bruto.rfind("}") + 1])
        validas, descartadas = _so_com_evidencia(dados.get("sugestoes", []),
                                                 texto)
    except Exception as erro:                     # rede, JSON torto, contrato
        base.alertas.append(f"A leitura por IA não funcionou ({erro}); "
                            f"segui só com as regras do sistema.")
        return base

    campos_validos = {c for c, *_ in REGRAS} | {"tempo_max_bordo_min",
                                                "max_passageiros_junto"}
    for item in validas:
        if item.get("campo") not in campos_validos:
            continue
        base.sugestoes.append(Sugestao(
            item["campo"], item.get("valor"),
            min(0.9, float(item.get("confianca") or 0.5)),
            str(item.get("trecho")), str(item.get("porque") or "leitura por IA")))
    if descartadas:
        base.alertas.append(
            f"Descartei {len(descartadas)} sugestão(ões) da IA porque o trecho "
            f"citado não está no documento.")
    base.origem = "regras+ia"
    return base


def aplicar(perfil, extracao: Extracao, campos_aprovados: list):
    """Aplica ao perfil SÓ os campos que o analista marcou.

    Devolve (perfil_novo, aplicados). O que não foi marcado não entra, mesmo
    com confiança 0,95 — a confiança serve para ordenar a tela, não para
    decidir por ninguém.
    """
    melhor = extracao.por_campo()
    aplicados = []
    dados = perfil.como_dicionario()
    for campo in campos_aprovados:
        sugestao = melhor.get(campo)
        if sugestao is None:
            continue
        dados[campo] = sugestao.valor
        aplicados.append({"campo": campo, "valor": sugestao.valor,
                          "trecho": sugestao.trecho})
    return type(perfil).de_dicionario(dados), aplicados
