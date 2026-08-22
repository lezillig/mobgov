# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
O formulário que substitui a fila do protocolo.

Como é hoje na maioria dos municípios: a família consegue um laudo, tira
cópia, vai até a secretaria, protocola, espera, liga para saber, volta, e no
ano seguinte repete tudo — inclusive quando a condição é permanente e não vai
mudar nunca.

Como fica: a família responde a estas perguntas pelo celular, anexa o
documento que já tiver (ou nenhum, se o município já tem o cadastro), e
acompanha o protocolo. A análise continua sendo humana; o que some é o papel,
a viagem até o centro e a espera sem informação.

As perguntas são feitas em língua de família, não em língua de secretaria:
"a pessoa consegue ir sozinha até um ponto a 300 m de casa?" é uma pergunta
que a mãe responde de cara — "requer atendimento porta a porta?" não é.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.importador import pseudonimo  # noqa: E402
from elegibilidade.perfil import Perfil, TEMPO_MAX_BORDO_PADRAO  # noqa: E402

FONTES_ACEITAS = {
    "laudo": "Laudo ou relatório médico (foto serve)",
    "declaracao_escolar": "Declaração da escola ou do AEE",
    "cadastro_municipal": "Cadastro que o município já tem (BPC, CadÚnico, "
                          "CER, APAE)",
    "avaliacao_presencial": "Avaliação feita pela equipe do município",
    "renovacao": "Renovação de concessão anterior",
}


@dataclass
class Campo:
    nome: str
    pergunta: str
    tipo: str                       # texto | sim_nao | numero | escolha
    obrigatorio: bool = False
    opcoes: list = field(default_factory=list)
    ajuda: str = ""
    depende_de: str = ""            # só aparece se este campo for "sim"


# A ordem importa: é a ordem em que a tela mostra.
CAMPOS = [
    Campo("nome", "Nome de quem vai ser transportado", "texto", True),
    Campo("nascimento", "Data de nascimento", "texto", True,
          ajuda="dd/mm/aaaa"),
    Campo("responsavel", "Nome de quem responde por ele(a)", "texto", True),
    Campo("telefone", "Telefone com WhatsApp", "texto", True),
    Campo("endereco", "Endereço completo de onde o veículo vai buscar",
          "texto", True),
    Campo("bairro", "Bairro ou distrito", "texto", True),
    Campo("referencia", "Ponto de referência para o motorista achar", "texto",
          ajuda="ex.: portão azul depois da ponte"),
    Campo("destino", "Para onde vai (escola, CER, APAE, hospital)", "texto",
          True),
    Campo("turno", "Turno", "escolha", True, ["Manhã", "Tarde", "Integral"]),

    Campo("vai_sozinho_ate_o_ponto",
          "A pessoa consegue ir sozinha até um ponto de encontro a até 300 "
          "metros de casa?", "sim_nao", True,
          ajuda="Se a resposta for não, o veículo busca na porta."),
    Campo("cadeira_de_rodas", "Usa cadeira de rodas?", "sim_nao", True),
    Campo("cadeira_motorizada", "A cadeira é motorizada?", "sim_nao",
          depende_de="cadeira_de_rodas"),
    Campo("precisa_elevador",
          "Precisa de plataforma elevatória ou rampa para entrar no veículo?",
          "sim_nao", True),
    Campo("acompanhante", "Viaja sempre com acompanhante?", "sim_nao", True,
          ajuda="O acompanhante ocupa um assento — a gente já reserva."),
    Campo("auxilio_no_embarque",
          "Precisa que alguém ajude a entrar e sair do veículo?", "sim_nao",
          True),
    Campo("cinto_especial", "Precisa de cinto de quatro pontos ou contenção "
          "específica?", "sim_nao"),
    Campo("crise_com_lotacao",
          "Ambiente com muita gente ou muito barulho causa crise ou "
          "sofrimento?", "sim_nao", True),
    Campo("max_passageiros_junto",
          "Nesse caso, no máximo quantas pessoas podem viajar junto?",
          "numero", depende_de="crise_com_lotacao"),
    Campo("tempo_max_bordo_min",
          "Existe recomendação de tempo máximo dentro do veículo? Quantos "
          "minutos?", "numero",
          ajuda=f"Deixe em branco se não houver; usamos "
                f"{TEMPO_MAX_BORDO_PADRAO} minutos."),
    Campo("condicao_permanente",
          "A condição é permanente (não vai mudar com tratamento)?", "sim_nao",
          True,
          ajuda="Se for, você não precisa renovar isso todo ano."),
    Campo("fonte", "O que você tem para comprovar?", "escolha", True,
          list(FONTES_ACEITAS)),
    Campo("documento", "Anexe a foto do documento, se tiver", "texto",
          ajuda="Opcional. Sem documento, a equipe do município avalia."),
    Campo("observacoes", "Alguma coisa que o motorista precisa saber?",
          "texto",
          ajuda="ex.: só entra pelo portão da frente; tem cão solto no quintal"),
]

POR_NOME = {c.nome: c for c in CAMPOS}
# Campos que carregam dado pessoal — ficam no cofre, não no dado de rota.
PESSOAIS = ("nome", "nascimento", "responsavel", "telefone", "endereco",
            "referencia", "documento")


def _sim(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("sim", "s", "true", "1", "x")


def _numero(valor):
    if valor in (None, "", []):
        return None
    try:
        return int(float(str(valor).replace(",", ".")))
    except ValueError:
        return None


def campos_visiveis(respostas: dict) -> list:
    """Some da tela o que não se aplica — pergunta a menos é desistência a
    menos."""
    return [c for c in CAMPOS
            if not c.depende_de or _sim(respostas.get(c.depende_de))]


def validar(respostas: dict) -> list:
    """Erros que impedem o envio, escritos para a família entender."""
    problemas = []
    for campo in campos_visiveis(respostas):
        valor = respostas.get(campo.nome)
        vazio = valor in (None, "", [])
        if campo.obrigatorio and vazio:
            problemas.append(f"Falta responder: {campo.pergunta}")
            continue
        if vazio:
            continue
        if campo.tipo == "numero" and _numero(valor) is None:
            problemas.append(f"“{campo.pergunta}” precisa de um número.")
        if campo.tipo == "escolha" and str(valor) not in campo.opcoes:
            problemas.append(f"“{campo.pergunta}”: escolha uma das opções "
                             f"({', '.join(campo.opcoes)}).")
    if (_sim(respostas.get("crise_com_lotacao"))
            and not _numero(respostas.get("max_passageiros_junto"))):
        problemas.append("Diga no máximo quantas pessoas podem viajar junto.")
    return problemas


def perfil_de(respostas: dict) -> Perfil:
    """Traduz as respostas da família em restrições operacionais."""
    cadeira = _sim(respostas.get("cadeira_de_rodas"))
    evitar = _sim(respostas.get("crise_com_lotacao"))
    return Perfil(
        # a pergunta é feita ao contrário de propósito: a família responde
        # sobre o que a pessoa CONSEGUE, e o sistema deduz o que ele precisa
        porta_a_porta=not _sim(respostas.get("vai_sozinho_ate_o_ponto")),
        cadeira_de_rodas=cadeira,
        cadeira_motorizada=cadeira and _sim(respostas.get("cadeira_motorizada")),
        elevador_ou_rampa=_sim(respostas.get("precisa_elevador")),
        acompanhante=_sim(respostas.get("acompanhante")),
        auxilio_no_embarque=_sim(respostas.get("auxilio_no_embarque")),
        cinto_de_quatro_pontos=_sim(respostas.get("cinto_especial")),
        evitar_lotacao=evitar,
        max_passageiros_junto=(_numero(respostas.get("max_passageiros_junto"))
                               or 0) if evitar else 0,
        tempo_max_bordo_min=(_numero(respostas.get("tempo_max_bordo_min"))
                             or TEMPO_MAX_BORDO_PADRAO),
        observacoes_operacionais=str(respostas.get("observacoes") or "").strip(),
    )


def montar_pedido(respostas: dict, protocolo: str = None,
                  em: str = None) -> dict:
    """Pedido pronto para entrar na fila. Levanta ValueError se faltar campo.

    A separação é proposital e não é decorativa:
      * `perfil`   -> vira rota, vai para o motor e para o painel;
      * `pessoais` -> fica no cofre da secretaria, sob acesso controlado;
      * `contato`  -> usado só para avisar a família.
    """
    problemas = validar(respostas)
    if problemas:
        raise ValueError("; ".join(problemas))

    identificador = pseudonimo(respostas.get("nome"),
                               respostas.get("endereco"),
                               respostas.get("bairro"))
    perfil = perfil_de(respostas)
    return {
        "protocolo": protocolo or f"P{identificador[1:9].upper()}",
        "usuario": identificador,
        "criado_em": em or "",
        "bairro": respostas.get("bairro"),
        "destino": respostas.get("destino"),
        "turno": respostas.get("turno"),
        "perfil": perfil.como_dicionario(),
        "resumo_do_perfil": perfil.resumo(),
        "condicao_permanente": _sim(respostas.get("condicao_permanente")),
        "fonte": respostas.get("fonte"),
        "tem_documento": bool(str(respostas.get("documento") or "").strip()),
        "pessoais": {c: respostas.get(c) for c in PESSOAIS
                     if respostas.get(c)},
        "avisos_do_perfil": perfil.coerente(),
    }
