# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-conversa
O assistente: entende a pergunta, chama ferramenta, responde em português.

Dois modos, mesma resposta numérica:

* **offline** (padrão, e o único que roda na demonstração sem internet):
  `conversa/roteador.py` escolhe a ferramenta por palavra-chave e
  `conversa/redator.py` escreve a resposta a partir do resultado.
* **com LLM** (quando há `ANTHROPIC_API_KEY` e `MOBGOV_MODELO` no ambiente):
  o modelo entende pergunta torta, encadeia mais de uma ferramenta e escreve
  melhor — mas os números continuam saindo das ferramentas.

A regra "o modelo não inventa número" não fica só no prompt: toda resposta do
LLM passa por `auditar_numeros`, que confere cada número escrito contra o que
as ferramentas devolveram. Número que não bate faz a resposta cair para a
versão determinística, com aviso. É chato de propósito — numa prestação de
contas, um número inventado custa o contrato.

Configuração:
    export ANTHROPIC_API_KEY=...      # sem isso, roda offline
    export MOBGOV_MODELO=...          # identificador do modelo a usar
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversa import ferramentas as ferramentas_mod  # noqa: E402
from conversa import redator, roteador  # noqa: E402

URL_API = "https://api.anthropic.com/v1/messages"
VERSAO_API = "2023-06-01"
MAX_RODADAS = 5          # ferramenta -> resultado -> ferramenta -> ... -> texto

SISTEMA = """Você é o assistente do MOBGOV, sistema de roteirização e economia
do transporte escolar de um município brasileiro. Fala com secretários de
educação, gestores de frota e vereadores — gente que decide, não gente de TI.

Regras invioláveis:
1. TODO número que você escrever tem que ter vindo de uma ferramenta desta
   conversa. Não estime, não arredonde para um número "mais bonito", não
   complete uma série. Se a ferramenta não trouxe o dado, diga que não tem.
2. Chame a ferramenta antes de responder. Nunca responda de memória.
3. Português do Brasil, direto, sem jargão de tecnologia. Reais no formato
   R$ 141.122,32; porcentagem com vírgula.
4. Diga a origem quando o dado for de demonstração ou simulação — o campo
   'selo' e o campo 'origem' das ferramentas dizem isso.
5. Nada de dado pessoal de aluno. Se pedirem, explique que o sistema trabalha
   com pontos e pseudônimos por causa da LGPD.
6. Resposta curta: a manchete primeiro, os detalhes em lista depois."""


class ErroDeAPI(RuntimeError):
    pass


# ------------------------------------------------------------- cliente API ---
class ClienteAnthropic:
    """Cliente mínimo em urllib — o projeto não instala SDK para isso."""

    def __init__(self, chave: str = None, modelo: str = None,
                 url: str = URL_API, tempo_limite: int = 60,
                 max_tokens: int = 1200):
        self.chave = chave or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modelo = modelo or os.environ.get("MOBGOV_MODELO", "")
        self.url = url
        self.tempo_limite = tempo_limite
        self.max_tokens = max_tokens

    def configurado(self) -> bool:
        return bool(self.chave and self.modelo)

    def mensagem(self, mensagens: list, ferramentas: list,
                 sistema: str = SISTEMA) -> dict:
        corpo = json.dumps({
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": sistema,
            "tools": ferramentas,
            "messages": mensagens,
        }, ensure_ascii=False).encode("utf-8")
        requisicao = urllib.request.Request(
            self.url, data=corpo, method="POST",
            headers={"content-type": "application/json",
                     "x-api-key": self.chave,
                     "anthropic-version": VERSAO_API})
        try:
            with urllib.request.urlopen(requisicao,
                                        timeout=self.tempo_limite) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")[:400]
            raise ErroDeAPI(f"API respondeu {erro.code}: {detalhe}") from erro
        except Exception as erro:                 # rede, DNS, timeout, proxy
            raise ErroDeAPI(f"Não consegui falar com a API: {erro}") from erro


# ------------------------------------------------------ auditoria numérica ---
_NUMERO_NO_TEXTO = re.compile(r"-?\d[\d.]*(?:,\d+)?")


def _numeros_do_texto(texto: str) -> list:
    """Números escritos em português: 1.287,2 -> 1287.2"""
    achados = []
    for bruto in _NUMERO_NO_TEXTO.findall(texto or ""):
        limpo = bruto.replace(".", "").replace(",", ".")
        try:
            achados.append((bruto, float(limpo)))
        except ValueError:
            continue
    return achados


def _numeros_do_resultado(valor, saco: set = None) -> set:
    """Todo número que as ferramentas devolveram, em qualquer profundidade."""
    saco = set() if saco is None else saco
    if isinstance(valor, bool):
        return saco
    if isinstance(valor, (int, float)):
        saco.add(float(valor))
    elif isinstance(valor, dict):
        for item in valor.values():
            _numeros_do_resultado(item, saco)
    elif isinstance(valor, (list, tuple)):
        for item in valor:
            _numeros_do_resultado(item, saco)
    elif isinstance(valor, str):
        for _, numero in _numeros_do_texto(valor):
            saco.add(numero)
    return saco


def _bate(escrito: float, conhecidos: set) -> bool:
    """Aceita o mesmo número, o arredondado e o expresso em mil/milhão.

    'R$ 1,69 mi' é 1693467.84 dito de outro jeito — isso é reescrita, não
    invenção. Já 'R$ 1,80 mi' não bate com nada e cai na auditoria.
    """
    for conhecido in conhecidos:
        for escala in (1.0, 1000.0, 1_000_000.0):
            alvo = conhecido / escala
            if abs(escrito - alvo) <= max(0.05, abs(alvo) * 0.005):
                return True
    return False


def auditar_numeros(texto: str, resultados: list) -> list:
    """Devolve os números escritos que NÃO vieram de nenhuma ferramenta."""
    conhecidos = set()
    for resultado in resultados:
        _numeros_do_resultado(resultado, conhecidos)
    # números pequenos são contagem de lista, ano abreviado, item "1." — não
    # vale acusar; o que interessa é valor, quantidade e porcentagem.
    suspeitos = []
    for bruto, numero in _numeros_do_texto(texto):
        if abs(numero) < 10:
            continue
        if 1900 <= numero <= 2100 and "," not in bruto:
            continue                              # ano
        if not _bate(numero, conhecidos):
            suspeitos.append(bruto)
    return suspeitos


# ------------------------------------------------------------- assistente ---
class Assistente:
    def __init__(self, cliente: ClienteAnthropic = None, offline: bool = False,
                 max_rodadas: int = MAX_RODADAS):
        self.cliente = cliente or ClienteAnthropic()
        self.offline = offline
        self.max_rodadas = max_rodadas
        self.historico = []

    # -- modo offline --------------------------------------------------------
    def responder_offline(self, pergunta: str, motivo: str = None) -> dict:
        nome, argumentos, confianca = roteador.escolher(pergunta)
        resultado = ferramentas_mod.executar(nome, argumentos)
        texto = redator.escrever(nome, resultado)
        if confianca < 0.4:
            texto = ("Não tenho certeza do que você perguntou, então respondi o "
                     "mais provável. Se não era isso, pergunte de outro jeito — "
                     f"eu sei responder sobre: {_lista_de_temas()}.\n\n" + texto)
        return {"resposta": texto, "modo": "offline", "confianca": confianca,
                "ferramentas": [{"nome": nome, "argumentos": argumentos,
                                 "resultado": resultado}],
                "numeros_conferidos": True,
                "motivo_offline": motivo}

    # -- modo com LLM --------------------------------------------------------
    def responder(self, pergunta: str) -> dict:
        if self.offline or not self.cliente.configurado():
            motivo = ("Modo offline pedido." if self.offline else
                      "Sem ANTHROPIC_API_KEY/MOBGOV_MODELO no ambiente.")
            return self.responder_offline(pergunta, motivo)
        try:
            return self._responder_com_llm(pergunta)
        except ErroDeAPI as erro:
            # a demonstração não pode parar porque o wi-fi caiu
            return self.responder_offline(pergunta, str(erro))

    def _responder_com_llm(self, pergunta: str) -> dict:
        mensagens = list(self.historico) + [{"role": "user", "content": pergunta}]
        esquemas = ferramentas_mod.esquemas()
        chamadas, resultados = [], []

        for _ in range(self.max_rodadas):
            resposta = self.cliente.mensagem(mensagens, esquemas)
            blocos = resposta.get("content", [])
            mensagens.append({"role": "assistant", "content": blocos})

            pedidos = [b for b in blocos if b.get("type") == "tool_use"]
            if not pedidos:
                texto = "\n".join(b.get("text", "") for b in blocos
                                  if b.get("type") == "text").strip()
                return self._entregar(pergunta, texto, chamadas, resultados,
                                      mensagens)

            devolucoes = []
            for pedido in pedidos:
                resultado = ferramentas_mod.executar(pedido.get("name"),
                                                     pedido.get("input") or {})
                chamadas.append({"nome": pedido.get("name"),
                                 "argumentos": pedido.get("input") or {},
                                 "resultado": resultado})
                resultados.append(resultado)
                devolucoes.append({
                    "type": "tool_result", "tool_use_id": pedido.get("id"),
                    "content": json.dumps(resultado, ensure_ascii=False)})
            mensagens.append({"role": "user", "content": devolucoes})

        # rodadas demais: não insiste, entrega o que as ferramentas já deram
        return self.responder_offline(
            pergunta, "O modelo ficou chamando ferramenta sem concluir.")

    def _entregar(self, pergunta: str, texto: str, chamadas: list,
                  resultados: list, mensagens: list) -> dict:
        if not chamadas:
            # respondeu de cabeça, sem consultar nada: não vale
            return self.responder_offline(
                pergunta, "O modelo respondeu sem chamar ferramenta.")

        suspeitos = auditar_numeros(texto, resultados)
        if suspeitos:
            oficial = redator.escrever(chamadas[0]["nome"],
                                       chamadas[0]["resultado"])
            # de propósito: o número reprovado NÃO é repetido na tela. Numa
            # apresentação, ver o valor errado escrito já basta para plantar
            # a dúvida — ele fica só no retorno, para o registro.
            quantos = len(suspeitos)
            texto = (f"Refiz esta resposta com os números do sistema: a versão "
                     f"escrita trazia {quantos} "
                     f"{'valor' if quantos == 1 else 'valores'} que não "
                     f"{'saiu' if quantos == 1 else 'saíram'} de nenhuma "
                     f"consulta.\n\n" + oficial)
        else:
            self.historico = mensagens[-8:]       # memória curta da conversa
        return {"resposta": texto, "modo": "llm", "confianca": 1.0,
                "ferramentas": chamadas,
                "numeros_conferidos": not suspeitos,
                "numeros_suspeitos": suspeitos}


def _lista_de_temas() -> str:
    return ", ".join(f.nome.replace("_", " ") for f in ferramentas_mod.CATALOGO)


def perguntar(pergunta: str, offline: bool = False) -> str:
    """Atalho de uma linha, para script e para teste."""
    return Assistente(offline=offline).responder(pergunta)["resposta"]
