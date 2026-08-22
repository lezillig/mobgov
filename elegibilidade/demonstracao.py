# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 7 · agent-elegibilidade
Fila de elegibilidade SIMULADA, para a demonstração e para o painel.

Enquanto nenhum município real tiver mandado pedido, é isto que o painel
mostra — com selo, dizendo que é simulação. Assim que existir o arquivo de
eventos de verdade, o mesmo código lê os dois do mesmo jeito e o selo muda
sozinho (é a regra que já vale para o aprendizado e para a operação).

Os casos não são bonitos de propósito: tem pedido atrasado, tem pedido
esperando informação, tem negativa, tem gente aprovada sem laudo nenhum
porque o município já tinha o cadastro, e tem concessão permanente — que é
justamente a que hoje faz a família refazer o processo todo ano à toa.
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elegibilidade import fila, formulario  # noqa: E402
from elegibilidade.extracao import analisar  # noqa: E402

ARQUIVO_DEMO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "relatorios", "operacao", "elegibilidade-demonstracao.jsonl")

BAIRROS = ["Sede Urbana", "Distrito Norte", "Distrito Leste",
           "Assentamento Oeste", "Vila Rural Sul"]
DESTINOS = ["EMEF Centro", "CER — Centro de Reabilitação", "APAE",
            "EMEF Vila Rural Sul", "Hospital Municipal"]
ANALISTAS = ["Ana Prado (SME)", "Carlos Menezes (SME)", "Rita Alves (SME)"]

LAUDOS = [
    "Paciente com paralisia cerebral (CID G80.0), não deambula e utiliza "
    "cadeira de rodas motorizada. Necessita de acompanhante durante todo o "
    "deslocamento. Indicado veículo adaptado com plataforma elevatória.",
    "Aluno com transtorno do espectro autista (CID F84.0). Apresenta "
    "hipersensibilidade auditiva, com crise em ambiente com muitas pessoas. "
    "Recomenda-se transporte com no máximo 4 passageiros.",
    "Paciente com distrofia muscular, mobilidade reduzida, deambula com "
    "auxílio de andador. Necessita de apoio para subir no veículo.",
    "Relatório do AEE: o estudante tem deficiência visual e necessita de "
    "acompanhante no trajeto até a escola.",
    "Atestado de comparecimento à consulta no dia 12/03.",
]


def _respostas(i: int, rng: random.Random) -> dict:
    cadeira = i % 3 == 0
    crise = i % 5 == 1
    return {
        "nome": f"Usuário de demonstração {i:03d}",
        "nascimento": "01/01/2014",
        "responsavel": f"Responsável {i:03d}",
        "telefone": f"16 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
        "endereco": f"Rua Demonstração, {rng.randint(1, 900)}",
        "bairro": BAIRROS[i % len(BAIRROS)],
        "referencia": "casa de esquina",
        "destino": DESTINOS[i % len(DESTINOS)],
        "turno": ["Manhã", "Tarde", "Integral"][i % 3],
        "vai_sozinho_ate_o_ponto": "não" if i % 4 else "sim",
        "cadeira_de_rodas": "sim" if cadeira else "não",
        "cadeira_motorizada": "sim" if cadeira and i % 6 == 0 else "não",
        "precisa_elevador": "sim" if cadeira and i % 2 == 0 else "não",
        "acompanhante": "sim" if i % 3 != 1 else "não",
        "auxilio_no_embarque": "sim" if i % 2 == 0 else "não",
        "cinto_especial": "sim" if i % 7 == 0 else "não",
        "crise_com_lotacao": "sim" if crise else "não",
        "max_passageiros_junto": "4" if crise else "",
        "tempo_max_bordo_min": "40" if i % 4 == 0 else "",
        "condicao_permanente": "sim" if i % 3 == 0 else "não",
        "fonte": ["laudo", "cadastro_municipal", "declaracao_escolar",
                  "laudo", "avaliacao_presencial"][i % 5],
        "documento": "foto-laudo.jpg" if i % 5 in (0, 3) else "",
        "observacoes": "portão sem campainha" if i % 4 == 0 else "",
    }


def gerar(arquivo: str = None, quantidade: int = 24,
          hoje: str = "2026-08-22") -> str:
    """Escreve o diário de eventos simulado. Apaga o anterior, se houver."""
    arquivo = arquivo or ARQUIVO_DEMO
    os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
    if os.path.exists(arquivo):
        os.remove(arquivo)

    rng = random.Random(2026)
    for i in range(quantidade):
        respostas = _respostas(i, rng)
        destino = i % 6
        # Pedido decidido é pedido antigo; pedido em aberto chegou nas últimas
        # três semanas. Sem isso a fila apareceria 100% atrasada — que seria
        # uma demonstração errada, e das piores: a que promete pouco demais.
        atras = (25 + i) if destino > 2 else (3 + (i * 3) % 20)
        dia = fila._somar_dias(hoje, -atras)
        pedido = formulario.montar_pedido(respostas, em=dia)
        fila.registrar({"tipo": "recebido", "protocolo": pedido["protocolo"],
                        "pedido": pedido, "em": f"{dia}T08:00:00"}, arquivo)

        if destino == 0:
            continue                                  # ainda na fila de espera
        analista = ANALISTAS[i % len(ANALISTAS)]
        analise = fila._somar_dias(dia, 2)
        fila.registrar({"tipo": "em_analise", "protocolo": pedido["protocolo"],
                        "analista": analista, "em": f"{analise}T09:00:00"},
                       arquivo)
        if destino == 1:
            continue                                  # em análise, sem decisão
        if destino == 2:
            fila.registrar({"tipo": "informacao_solicitada",
                            "protocolo": pedido["protocolo"],
                            "analista": analista,
                            "o_que": "Foto do documento com o nome legível.",
                            "em": f"{analise}T09:20:00"}, arquivo)
            continue

        perfil = formulario.perfil_de(respostas)
        laudo = LAUDOS[i % len(LAUDOS)]
        extraido = analisar(laudo)
        aplicadas = [{"campo": s.campo, "valor": s.valor, "trecho": s.trecho}
                     for s in extraido.por_campo().values()
                     if s.confianca >= 0.8][:3]
        decisao = fila._somar_dias(analise, 1 + (i % 5))
        if i % 7 == 4:
            fila.registrar({
                "tipo": "negado", "protocolo": pedido["protocolo"],
                "analista": analista, "em": f"{decisao}T14:00:00",
                "justificativa": "Na avaliação presencial, o usuário chega ao "
                                 "ponto de encontro a 120 m de casa com "
                                 "autonomia. Fica no transporte regular, com "
                                 "prioridade de assento.",
                "como_recorrer": "A família pode pedir revisão respondendo a "
                                 "este protocolo."}, arquivo)
            continue
        fila.aprovar(pedido["protocolo"], analista, perfil,
                     fontes=[respostas["fonte"]],
                     permanente=respostas["condicao_permanente"] == "sim",
                     justificativa=f"Perfil confirmado: {perfil.resumo()}.",
                     sugestoes_aplicadas=aplicadas,
                     # concessão curta existe de verdade (condição em
                     # tratamento) — e é ela que aparece no aviso de renovação
                     validade_meses=2 if i % 5 == 2 else 12,
                     arquivo=arquivo, em=f"{decisao}T14:00:00")
    return arquivo


if __name__ == "__main__":
    print(f"Fila simulada escrita em {gerar()}")
