# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 12 · agent-fiscalizacao
Medição do contrato: o que foi planejado contra o que aconteceu.

Este é o módulo que a prefeitura usa TODO MÊS, e é o que hoje não existe em
lugar nenhum. O ciclo real de um contrato de transporte escolar no Brasil é:

    a prefeitura contrata X veículos e Y quilômetros
    o fornecedor declara no fim do mês quanto rodou
    a prefeitura paga o que foi declarado

A declaração do fornecedor é a única fonte. Não porque alguém seja
desonesto — porque não existe outra. O MOBGOV tem duas: o plano que ele mesmo
gerou e os eventos que chegaram do aparelho do motorista. Comparar as duas é
medição de contrato, e é o que sustenta pagamento, glosa e prestação de
contas.

Três regras que fazem esse módulo servir num processo administrativo:

1. **Falta de evidência não é prova de falta.** Viagem sem nenhum evento não
   é "não realizada": é `sem_evidencia`. Celular sem bateria, app sem sinal na
   zona rural e aparelho esquecido acontecem toda semana. Glosar por isso cai
   no primeiro recurso e derruba a credibilidade do sistema inteiro. Essas
   viagens vão para uma fila de decisão humana, separadas.

2. **Toda conclusão cita a evidência.** Cada viagem medida carrega os eventos
   que sustentam o veredicto — quantos, de que tipo, em que horário. Quem
   assina a glosa precisa poder mostrar o porquê, e o fornecedor precisa poder
   contestar olhando o mesmo dado.

3. **O que é medido e o que é planejado nunca se misturam.** Km medido vem do
   rastro de GPS; km planejado vem do motor. Os dois aparecem lado a lado, com
   selo, e a diferença é informação — não erro a ser escondido.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.tempos import haversine_km  # noqa: E402

# Raio para dizer que o veículo PASSOU por uma parada planejada. 150 m cobre
# erro de GPS urbano e o fato de o ponto ser o centroide de quem embarca ali,
# não a guia exata onde o ônibus encosta.
RAIO_PARADA_M = 150

# Atraso a partir do qual a chegada deixa de ser "no horário". Não é
# tolerância de contrato — é o que a tela chama de atrasado. A tolerância
# contratual, essa sim, vive em fiscalizacao/contrato.py.
ATRASO_RELEVANTE_MIN = 15

# Abaixo disto o rastro é curto demais para virar quilometragem: dois pings
# não fazem um percurso, e apresentar "0,4 km" como medição de uma viagem de
# 12 km seria pior do que dizer que não há medida.
PINGS_MINIMOS_PARA_KM = 5

SITUACOES = ("realizada", "parcial", "nao_realizada", "sem_evidencia")


def horarios_planejados(plano: dict, perfil=None) -> dict:
    """Quando cada viagem devia sair e chegar — derivado do plano.

    O relatório do motor guarda a duração de cada viagem e a ordem em que o
    veículo as faz, mas não o relógio. O compromisso do contrato é a janela de
    chegada do turno ("todo mundo na escola até 7h"), então a agenda se monta
    de trás para frente: a última viagem do veículo chega no fim da janela, e
    cada anterior chega antes o suficiente para caber a seguinte.

    É a mesma conta que o despachante faz no papel, e sem ela não existe
    "atrasado": só existe "chegou em algum momento".
    """
    from dados import perfis as perfis_mod

    perfil = perfil or perfis_mod.EMBUTIDOS.get(
        (plano.get("perfil") or {}).get("id"), perfis_mod.PERFIL_ESCOLAR)
    janela = {t.id: t.janela_chegada for t in perfil.turnos}
    virada = (plano.get("premissas") or {}).get("tempo_virada_min", 5)

    duracao = {v["id"]: (v.get("min_viagem") or 30)
               for v in (plano.get("frota_otimizada") or {}).get("viagens", [])}
    agenda = {}
    for veiculo in (plano.get("frota_otimizada") or {}).get("veiculos", []):
        fim_da_janela = (janela.get(veiculo.get("turno")) or (7 * 60,))[-1]
        chegada = fim_da_janela
        # de trás para frente: a última viagem é a que encosta na janela
        for viagem in reversed(veiculo.get("viagens") or []):
            minutos = duracao.get(viagem, 30)
            agenda[viagem] = {"saida_min": chegada - minutos,
                              "chegada_min": chegada}
            chegada = chegada - minutos - virada
    return agenda


def _dia(carimbo: str) -> str:
    return (carimbo or "")[:10]


def _minuto(carimbo: str):
    try:
        d = datetime.strptime(carimbo, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return d.hour * 60 + d.minute


# Densidade de rastro a partir da qual a quilometragem medida vale como
# medida. Abaixo disso ela é LIMITE INFERIOR: a soma de retas entre pings
# esparsos corta as curvas e sempre dá menos do que o veículo rodou. Pagar
# por esse número seria pagar a menos por um defeito do aparelho.
PINGS_POR_MINUTO_CONFIAVEL = 0.8


def _km_do_rastro(pings: list) -> tuple:
    """Quilometragem medida e se ela pode ser usada para pagar.

    Devolve `(km, confiavel)`. A soma das retas entre pings consecutivos é
    sempre menor ou igual ao percurso real — quanto mais esparso o rastro,
    maior o corte. Por isso o número vem acompanhado do veredicto, e nunca
    sozinho.
    """
    coords = [(p["lat"], p["lon"]) for p in pings
              if p.get("lat") is not None and p.get("lon") is not None]
    if len(coords) < PINGS_MINIMOS_PARA_KM:
        return None, False
    km = round(sum(haversine_km(a, b) for a, b in zip(coords, coords[1:])), 1)

    minutos = [_minuto(p.get("em")) for p in pings]
    minutos = [m for m in minutos if m is not None]
    duracao = (max(minutos) - min(minutos)) if len(minutos) > 1 else 0
    densidade = len(coords) / duracao if duracao else 0
    return km, densidade >= PINGS_POR_MINUTO_CONFIAVEL


def _paradas_visitadas(pings: list, paradas: list, pontos: dict) -> list:
    """Quais paradas planejadas o rastro prova que o veículo passou."""
    visitadas = []
    for parada in paradas:
        coord = pontos.get(parada)
        if not coord:
            continue
        for p in pings:
            if p.get("lat") is None:
                continue
            if haversine_km(tuple(coord), (p["lat"], p["lon"])) * 1000 \
                    <= RAIO_PARADA_M:
                visitadas.append(parada)
                break
    return visitadas


def _eventos_da_viagem(viagem: dict, por_veiculo: dict, data: str) -> list:
    """Eventos do dia atribuíveis à viagem.

    Casa primeiro pelo campo `viagem` do evento (o app manda). Sem ele, cai
    no veículo — que é como fica quando o evento vem de um GPS embarcado, sem
    o app saber de qual viagem se trata.
    """
    do_veiculo = [e for e in por_veiculo.get(viagem.get("veiculo"), [])
                  if _dia(e.get("em")) == data]
    marcados = [e for e in do_veiculo if e.get("viagem") == viagem["id"]]
    if marcados:
        # o rastro de GPS raramente vem marcado com a viagem; junta os pings
        # do mesmo veículo que caem entre o primeiro e o último evento marcado
        inicio = min(_minuto(e["em"]) for e in marcados
                     if _minuto(e.get("em")) is not None)
        fim = max(_minuto(e["em"]) for e in marcados
                  if _minuto(e.get("em")) is not None)
        pings = [e for e in do_veiculo
                 if e.get("tipo") == "ping" and not e.get("viagem")
                 and _minuto(e.get("em")) is not None
                 and inicio <= _minuto(e["em"]) <= fim]
        return sorted(marcados + pings, key=lambda e: e.get("em") or "")
    return []


def _situacao(eventos: list, viagem: dict, visitadas: list) -> tuple:
    """Veredicto e o motivo dele, em português de quem vai ler."""
    if not eventos:
        return "sem_evidencia", ("Nenhum evento chegou deste veículo nesta "
                                 "viagem. Pode ter rodado sem sinal — não "
                                 "conte como falta sem confirmar.")

    cancelada = [e for e in eventos
                 if e.get("tipo") == "imprevisto"
                 and e.get("cancelou_viagem")]
    if cancelada:
        motivo = cancelada[0].get("motivo") or "sem motivo declarado"
        return "nao_realizada", f"O motorista registrou: {motivo}."

    planejadas = len(viagem.get("paradas") or [])
    embarques = len({e.get("ponto") for e in eventos
                     if e.get("tipo") in ("embarque", "desembarque")
                     and e.get("ponto")})
    cobertas = len(set(visitadas) | {e.get("ponto") for e in eventos
                                     if e.get("ponto")} - {None})

    if planejadas and cobertas >= planejadas:
        return "realizada", (f"Passou pelas {planejadas} paradas planejadas "
                             f"({embarques} com embarque registrado).")
    if cobertas:
        return "parcial", (f"Passou por {cobertas} das {planejadas} paradas "
                           f"planejadas.")
    return "parcial", ("Chegaram eventos do veículo, mas nenhum prova "
                       "passagem pelas paradas planejadas.")


def medir_viagem(viagem: dict, eventos: list, pontos: dict,
                 horario: dict = None) -> dict:
    """Uma viagem planejada contra o que os eventos dizem que aconteceu."""
    pings = [e for e in eventos if e.get("tipo") == "ping"]
    visitadas = _paradas_visitadas(pings, viagem.get("paradas") or [], pontos)
    situacao, motivo = _situacao(eventos, viagem, visitadas)

    chegada = [e for e in eventos if e.get("tipo") == "fim"]
    minuto_chegada = _minuto(chegada[0]["em"]) if chegada else None
    prometido = (viagem.get("chegada_planejada_min")
                 or (horario or {}).get("chegada_min"))
    atraso = (minuto_chegada - prometido
              if minuto_chegada is not None and prometido is not None else None)

    km_medido, km_confiavel = _km_do_rastro(pings)
    passageiros = len({e.get("aluno") for e in eventos
                       if e.get("tipo") == "embarque" and e.get("aluno")})

    return {
        "viagem": viagem["id"],
        "veiculo": viagem.get("veiculo"),
        "destino": viagem.get("escola"),
        "destino_id": viagem.get("escola_id"),
        "turno": viagem.get("turno_nome"),
        "situacao": situacao,
        "motivo": motivo,
        "km_planejado": viagem.get("km_viagem"),
        "km_medido": km_medido,
        "km_medido_confiavel": km_confiavel,
        "paradas_planejadas": len(viagem.get("paradas") or []),
        "paradas_com_evidencia": len(visitadas),
        "passageiros_planejados": viagem.get("alunos"),
        "passageiros_embarcados": passageiros or None,
        "atraso_min": atraso,
        "atrasada": atraso is not None and atraso >= ATRASO_RELEVANTE_MIN,
        "evidencia": {
            "eventos": len(eventos),
            "por_tipo": _contar_por_tipo(eventos),
            "primeiro": eventos[0]["em"] if eventos else None,
            "ultimo": eventos[-1]["em"] if eventos else None,
        },
    }


def _contar_por_tipo(eventos: list) -> dict:
    por_tipo = {}
    for e in eventos:
        por_tipo[e.get("tipo")] = por_tipo.get(e.get("tipo"), 0) + 1
    return por_tipo


def medir_dia(plano: dict, eventos: list, data: str,
              contraparte_por_destino: dict = None,
              agenda: dict = None) -> dict:
    """Mede um dia inteiro do contrato.

    `contraparte_por_destino` liga cada destino ao fornecedor do lote — é por
    fornecedor que a medição vira pagamento.
    """
    viagens = (plano.get("frota_otimizada") or {}).get("viagens") or []
    pontos = (plano.get("geografia") or {}).get("pontos") or {}
    contraparte_por_destino = contraparte_por_destino or {}
    agenda = agenda if agenda is not None else horarios_planejados(plano)

    por_veiculo = {}
    for e in eventos:
        por_veiculo.setdefault(e.get("motorista"), []).append(e)
    for lista in por_veiculo.values():
        lista.sort(key=lambda e: e.get("em") or "")

    medidas = []
    for viagem in viagens:
        do_dia = _eventos_da_viagem(viagem, por_veiculo, data)
        medida = medir_viagem(viagem, do_dia, pontos,
                              agenda.get(viagem["id"]))
        parte = contraparte_por_destino.get(viagem.get("escola_id")) \
            or contraparte_por_destino.get(viagem.get("escola")) or {}
        medida["fornecedor"] = parte.get("nome")
        medida["fornecedor_id"] = parte.get("id")
        medidas.append(medida)

    return {"data": data, "viagens": medidas, "resumo": resumir(medidas)}


def resumir(medidas: list) -> dict:
    """Os números do período — com o que não tem evidência à parte, sempre."""
    def conta(situacao):
        return sum(1 for m in medidas if m["situacao"] == situacao)

    com_medida = [m for m in medidas if m["km_medido"] is not None]
    confiaveis = [m for m in com_medida if m.get("km_medido_confiavel")]
    com_atraso = [m for m in medidas if m["atraso_min"] is not None]
    return {
        "viagens_planejadas": len(medidas),
        "realizadas": conta("realizada"),
        "parciais": conta("parcial"),
        "nao_realizadas": conta("nao_realizada"),
        "sem_evidencia": conta("sem_evidencia"),
        "atrasadas": sum(1 for m in medidas if m["atrasada"]),
        "km_planejado": round(sum(m["km_planejado"] or 0 for m in medidas), 1),
        "km_medido": round(sum(m["km_medido"] for m in com_medida), 1)
        if com_medida else None,
        "viagens_com_km_medido": len(com_medida),
        "viagens_com_km_confiavel": len(confiaveis),
        # rastro esparso corta as curvas: o número existe, mas é piso, não
        # medida — e quem for pagar por ele precisa saber disso antes
        "km_medido_e_piso": bool(com_medida) and len(confiaveis) < len(com_medida),
        "atraso_medio_min": round(
            sum(m["atraso_min"] for m in com_atraso) / len(com_atraso), 1)
        if com_atraso else None,
        # a cobertura diz o quanto a medição vale: 30% de evidência não
        # sustenta glosa nenhuma, e quem lê precisa saber disso antes do resto
        "cobertura_pct": round(
            100 * (len(medidas) - conta("sem_evidencia")) / len(medidas), 1)
        if medidas else 0.0,
    }


def medir_periodo(plano: dict, eventos: list, dias: list,
                  contraparte_por_destino: dict = None) -> dict:
    """O mês fechado, que é a unidade de pagamento."""
    agenda = horarios_planejados(plano)
    por_dia = [medir_dia(plano, eventos, dia, contraparte_por_destino, agenda)
               for dia in dias]
    todas = [m for d in por_dia for m in d["viagens"]]
    return {
        "dias": [{"data": d["data"], "resumo": d["resumo"]} for d in por_dia],
        "viagens": todas,
        "resumo": resumir(todas),
        "por_fornecedor": _por_fornecedor(todas),
    }


def _por_fornecedor(medidas: list) -> list:
    grupos = {}
    for m in medidas:
        chave = m.get("fornecedor_id") or "—"
        grupo = grupos.setdefault(chave, {"id": chave,
                                          "nome": m.get("fornecedor"),
                                          "medidas": []})
        grupo["medidas"].append(m)
    return [{"id": g["id"], "nome": g["nome"], "resumo": resumir(g["medidas"])}
            for g in sorted(grupos.values(),
                            key=lambda g: -len(g["medidas"]))]
