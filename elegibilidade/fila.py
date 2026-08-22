# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
A fila de análise: estado, prazo e registro de quem decidiu.

Guardado como diário append-only (um evento por linha), pelo mesmo motivo da
operação: processo administrativo que define direito de pessoa com deficiência
precisa ser reconstituível. Nada é sobrescrito; o estado atual é a soma dos
eventos. Se alguém perguntar "quem aprovou isso e com base em quê", a resposta
está no arquivo, com data.

Estados:

    recebido ─┬─> em_analise ─┬─> aprovado
              │               ├─> negado
              │               └─> pendente_de_informacao ─> em_analise
              └─> cancelado

Duas regras que o código impõe, não confia:

* aprovar sem nome de analista é impossível (levanta erro);
* negar sem justificativa escrita é impossível — negativa sem motivo é o que
  faz a família recorrer no escuro.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elegibilidade.perfil import Concessao, Perfil  # noqa: E402

ARQUIVO_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "operacao", "elegibilidade.jsonl")

PRAZO_DIAS = 15               # prazo que a secretaria assume com a família
VALIDADE_MESES = 12

TIPOS = ("recebido", "em_analise", "informacao_solicitada",
         "informacao_recebida", "aprovado", "negado", "cancelado",
         "revalidado")

ABERTOS = ("recebido", "em_analise", "pendente_de_informacao")


class ErroDeFila(ValueError):
    pass


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _hoje() -> str:
    return date.today().isoformat()


def _somar_meses(data_iso: str, meses: int) -> str:
    d = date.fromisoformat(data_iso[:10])
    ano, mes = divmod(d.month - 1 + meses, 12)
    dia = min(d.day, [31, 29 if (d.year + ano) % 4 == 0 else 28, 31, 30, 31,
                      30, 31, 31, 30, 31, 30, 31][mes])
    return date(d.year + ano, mes + 1, dia).isoformat()


# ------------------------------------------------------------------ diário ---
def registrar(evento: dict, arquivo: str = None) -> dict:
    arquivo = arquivo or ARQUIVO_PADRAO
    if evento.get("tipo") not in TIPOS:
        raise ErroDeFila(f"Tipo de evento desconhecido: {evento.get('tipo')}.")
    if not evento.get("protocolo"):
        raise ErroDeFila("Evento sem protocolo.")
    evento = dict(evento)
    evento.setdefault("em", _agora())
    evento["registrado_em"] = _agora()
    os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    return evento


def ler_eventos(arquivo: str = None, protocolo: str = None) -> list:
    arquivo = arquivo or ARQUIVO_PADRAO
    if not os.path.exists(arquivo):
        return []
    eventos = []
    with open(arquivo, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue                     # linha torta não derruba o resto
            if protocolo and evento.get("protocolo") != protocolo:
                continue
            eventos.append(evento)
    return eventos


# ------------------------------------------------------------------ ações ---
def receber(pedido: dict, arquivo: str = None) -> dict:
    """Entrada do pedido — o protocolo nasce aqui e a família já pode
    acompanhar."""
    evento = registrar({"tipo": "recebido", "protocolo": pedido["protocolo"],
                        "pedido": pedido}, arquivo)
    return evento


def iniciar_analise(protocolo: str, analista: str, arquivo: str = None) -> dict:
    if not analista:
        raise ErroDeFila("Análise sem analista responsável.")
    return registrar({"tipo": "em_analise", "protocolo": protocolo,
                      "analista": analista}, arquivo)


def pedir_informacao(protocolo: str, analista: str, o_que: str,
                     arquivo: str = None) -> dict:
    if not o_que:
        raise ErroDeFila("Diga exatamente o que falta — 'documentação "
                         "incompleta' faz a família voltar sem saber o quê.")
    return registrar({"tipo": "informacao_solicitada", "protocolo": protocolo,
                      "analista": analista, "o_que": o_que}, arquivo)


def receber_informacao(protocolo: str, o_que: str = "",
                       arquivo: str = None) -> dict:
    return registrar({"tipo": "informacao_recebida", "protocolo": protocolo,
                      "o_que": o_que}, arquivo)


def aprovar(protocolo: str, analista: str, perfil: Perfil, fontes: list,
            permanente: bool = False, justificativa: str = "",
            sugestoes_aplicadas: list = None, validade_meses: int = None,
            arquivo: str = None, em: str = None) -> dict:
    """Aprovação — sempre com nome de gente e com o perfil que vai roteirizar.

    `permanente=True` é a diferença que a família sente: condição que não muda
    não volta para a fila todo ano.
    """
    if not analista:
        raise ErroDeFila("Aprovação exige o nome de quem aprovou.")
    if not fontes:
        raise ErroDeFila("Aprovação exige ao menos uma fonte de evidência.")
    problemas = perfil.coerente()
    hoje = (em or _hoje())[:10]
    evento = {
        "tipo": "aprovado", "protocolo": protocolo, "analista": analista,
        "perfil": perfil.como_dicionario(), "resumo": perfil.resumo(),
        "fontes": list(fontes), "permanente": bool(permanente),
        "justificativa": justificativa,
        "sugestoes_aplicadas": sugestoes_aplicadas or [],
        "avisos": problemas,
        "vence_em": "" if permanente else _somar_meses(
            hoje, validade_meses or VALIDADE_MESES),
    }
    if em:
        evento["em"] = em
    return registrar(evento, arquivo)


def negar(protocolo: str, analista: str, justificativa: str,
          como_recorrer: str = "", arquivo: str = None) -> dict:
    if not analista:
        raise ErroDeFila("Negativa exige o nome de quem decidiu.")
    if not (justificativa or "").strip():
        raise ErroDeFila("Negativa exige justificativa escrita.")
    return registrar({"tipo": "negado", "protocolo": protocolo,
                      "analista": analista, "justificativa": justificativa,
                      "como_recorrer": como_recorrer or
                      "A família pode pedir revisão respondendo a este "
                      "protocolo, ou solicitar avaliação presencial."},
                     arquivo)


def cancelar(protocolo: str, motivo: str = "", arquivo: str = None) -> dict:
    return registrar({"tipo": "cancelado", "protocolo": protocolo,
                      "motivo": motivo}, arquivo)


# ------------------------------------------------------------------ estado ---
def _estado_de(eventos: list) -> str:
    estado = "recebido"
    for evento in eventos:
        tipo = evento["tipo"]
        if tipo == "em_analise":
            estado = "em_analise"
        elif tipo == "informacao_solicitada":
            estado = "pendente_de_informacao"
        elif tipo == "informacao_recebida":
            estado = "em_analise"
        elif tipo in ("aprovado", "negado", "cancelado", "revalidado"):
            estado = "aprovado" if tipo == "revalidado" else tipo
    return estado


def situacao(protocolo: str, arquivo: str = None, hoje: str = None) -> dict:
    """O que a família vê ao consultar o protocolo, e o analista ao abrir."""
    eventos = ler_eventos(arquivo, protocolo)
    if not eventos:
        return {}
    hoje = hoje or _hoje()
    primeiro = eventos[0]
    pedido = primeiro.get("pedido", {})
    estado = _estado_de(eventos)
    decisao = next((e for e in reversed(eventos)
                    if e["tipo"] in ("aprovado", "negado", "revalidado")), None)

    criado = primeiro.get("em", "")[:10] or hoje
    prazo = _somar_dias(criado, PRAZO_DIAS)
    return {
        "protocolo": protocolo,
        "estado": estado,
        "estado_em_portugues": EM_PORTUGUES[estado],
        "aberto_em": criado,
        "prazo_ate": prazo,
        "atrasado": estado in ABERTOS and hoje > prazo,
        "dias_em_aberto": _dias_entre(criado, hoje) if estado in ABERTOS else 0,
        "usuario": pedido.get("usuario"),
        "bairro": pedido.get("bairro"),
        "destino": pedido.get("destino"),
        "resumo_do_perfil": (decisao or pedido).get(
            "resumo", pedido.get("resumo_do_perfil", "")),
        "analista": (decisao or {}).get("analista"),
        "vence_em": (decisao or {}).get("vence_em", ""),
        "permanente": (decisao or {}).get("permanente", False),
        "justificativa": (decisao or {}).get("justificativa", ""),
        "pendencia": _pendencia(eventos, estado),
        "historico": [{"em": e.get("em"), "tipo": e["tipo"],
                       "analista": e.get("analista"),
                       "detalhe": e.get("o_que") or e.get("justificativa")
                       or e.get("motivo") or ""} for e in eventos],
    }


EM_PORTUGUES = {
    "recebido": "Recebido — aguardando análise",
    "em_analise": "Em análise",
    "pendente_de_informacao": "Esperando uma informação sua",
    "aprovado": "Aprovado",
    "negado": "Negado",
    "cancelado": "Cancelado",
}


def _pendencia(eventos: list, estado: str) -> str:
    if estado != "pendente_de_informacao":
        return ""
    for evento in reversed(eventos):
        if evento["tipo"] == "informacao_solicitada":
            return evento.get("o_que", "")
    return ""


def _somar_dias(data_iso: str, dias: int) -> str:
    return (date.fromisoformat(data_iso[:10]) + timedelta(days=dias)).isoformat()


def _dias_entre(inicio: str, fim: str) -> int:
    return (date.fromisoformat(fim[:10]) - date.fromisoformat(inicio[:10])).days


def protocolos(arquivo: str = None) -> list:
    vistos = []
    for evento in ler_eventos(arquivo):
        if evento["protocolo"] not in vistos:
            vistos.append(evento["protocolo"])
    return vistos


def listar(arquivo: str = None, estado: str = None, hoje: str = None) -> list:
    fila = [situacao(p, arquivo, hoje) for p in protocolos(arquivo)]
    if estado:
        fila = [s for s in fila if s["estado"] == estado]
    # atrasado primeiro, depois o mais antigo — é a ordem em que se trabalha
    return sorted(fila, key=lambda s: (not s["atrasado"], s["aberto_em"]))


def concessoes_vigentes(arquivo: str = None, hoje: str = None) -> list:
    """As concessões que valem hoje — é isto que vira demanda porta a porta."""
    hoje = hoje or _hoje()
    vigentes = []
    for protocolo in protocolos(arquivo):
        eventos = ler_eventos(arquivo, protocolo)
        if _estado_de(eventos) != "aprovado":
            continue
        decisao = next(e for e in reversed(eventos)
                       if e["tipo"] in ("aprovado", "revalidado"))
        pedido = eventos[0].get("pedido", {})
        concessao = Concessao(
            pedido=protocolo, perfil=Perfil.de_dicionario(decisao["perfil"]),
            analista=decisao.get("analista", ""),
            decidido_em=decisao.get("em", "")[:10],
            vence_em=decisao.get("vence_em", ""),
            permanente=decisao.get("permanente", False),
            justificativa=decisao.get("justificativa", ""),
            fontes=decisao.get("fontes", []))
        if concessao.vigente_em(hoje):
            vigentes.append((pedido.get("usuario", protocolo), concessao))
    return vigentes


def demanda_para_roteirizacao(arquivo: str = None, hoje: str = None) -> list:
    """A ponte com o motor: só restrição operacional, nenhum dado pessoal."""
    saida = []
    for usuario, concessao in concessoes_vigentes(arquivo, hoje):
        registro = concessao.perfil.para_roteirizacao(usuario)
        registro["protocolo"] = concessao.pedido
        saida.append(registro)
    return saida


def a_vencer(dias: int = 30, arquivo: str = None, hoje: str = None) -> list:
    """Quem vai precisar renovar — para avisar antes, não depois de parar de
    ser buscado na porta de casa."""
    hoje = hoje or _hoje()
    limite = _somar_dias(hoje, dias)
    return [{"protocolo": c.pedido, "vence_em": c.vence_em,
             "usuario": usuario}
            for usuario, c in concessoes_vigentes(arquivo, hoje)
            if not c.permanente and c.vence_em and hoje <= c.vence_em <= limite]


def resumo(arquivo: str = None, hoje: str = None) -> dict:
    fila = listar(arquivo, hoje=hoje)
    por_estado = {}
    for item in fila:
        por_estado[item["estado"]] = por_estado.get(item["estado"], 0) + 1
    abertos = [s for s in fila if s["estado"] in ABERTOS]
    concluidos = [s for s in fila if s["estado"] in ("aprovado", "negado")]
    return {
        "pedidos": len(fila),
        "por_estado": por_estado,
        "em_aberto": len(abertos),
        "atrasados": len([s for s in abertos if s["atrasado"]]),
        "prazo_dias": PRAZO_DIAS,
        "dias_em_aberto_media": round(
            sum(s["dias_em_aberto"] for s in abertos) / len(abertos), 1)
        if abertos else 0.0,
        "aprovados": por_estado.get("aprovado", 0),
        "negados": por_estado.get("negado", 0),
        "decididos": len(concluidos),
        "permanentes": len([s for s in fila if s.get("permanente")]),
        "a_vencer_30_dias": len(a_vencer(30, arquivo, hoje)),
    }
