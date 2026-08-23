# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 11 · agent-painel
Monta o protótipo do sistema remodelado (ver docs/ux-modelo.md).

O que este script faz é juntar, num único arquivo HTML autocontido, o estado
real do sistema — os mesmos relatórios que o painel, o console e a proposta
leem — organizado do jeito novo: por pessoa e por momento, e não por módulo.

Nenhum número aqui é escrito à mão. Se um valor aparece na tela, ele saiu de
`relatorios/`, calculado pelas mesmas funções de sempre.

Uso:
    python ui/gerar.py
    python ui/gerar.py --plano relatorios/plano-fretamento.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comercial import diagnostico as diagnostico_mod  # noqa: E402
from dados import agrupar as agrupar_mod  # noqa: E402
from dados import perfis as perfis_mod  # noqa: E402
from comercial import operacao_atual as operacao_mod  # noqa: E402
from comercial import precificacao as precificacao_mod  # noqa: E402
from comercial.precificacao import Premissas  # noqa: E402
from elegibilidade import relatorio as elegibilidade_mod  # noqa: E402
from fiscalizacao import relatorio as fiscalizacao_mod  # noqa: E402
from operacao import onde_esta, registro, rota_do_dia as rotas  # noqa: E402
from painel import economia as economia_mod  # noqa: E402

DIR_UI = os.path.dirname(os.path.abspath(__file__))
DIR_BASE = os.path.dirname(DIR_UI)
DIR_RELATORIOS = os.path.join(DIR_BASE, "relatorios")
DIR_TELAS = os.path.join(DIR_BASE, "docs", "demonstracao", "telas")
SAIDA_PADRAO = os.path.join(DIR_TELAS, "0-sistema.html")
LINHAS_ATUAIS = os.path.join(DIR_BASE, "docs", "demonstracao",
                             "linhas-atuais-demo.csv")

# As duas operações que o protótipo mostra. O seletor no topo troca de uma
# para a outra — é o mesmo sistema, com a linguagem de cada cliente.
OPERACOES = [
    {"chave": "prefeitura", "rotulo": "Prefeitura · escolar",
     "arquivo": "0-sistema.html", "plano": None},
    {"chave": "empresa", "rotulo": "Empresa · fretamento",
     "arquivo": "0-sistema-empresa.html",
     "plano": os.path.join(DIR_RELATORIOS, "plano-fretamento.json")},
]


def _opcional(nome: str) -> dict:
    return economia_mod.carregar_opcional(os.path.join(DIR_RELATORIOS, nome))


def _selo(origem: str) -> dict:
    """O selo é componente, não rodapé: todo número diz de onde veio."""
    return {
        "medido": {"rotulo": "medido", "explicacao":
                   "veio do GPS do veículo ou do aplicativo de quem usa"},
        "planejado": {"rotulo": "planejado", "explicacao":
                      "calculado pelo motor de roteirização, ainda não medido"},
        "informado": {"rotulo": "informado", "explicacao":
                      "veio da planilha de quem opera — não foi medido aqui"},
        "simulado": {"rotulo": "simulado", "explicacao":
                     "dado de demonstração — nenhuma pessoa real"},
    }.get(origem, {"rotulo": origem, "explicacao": ""})


def _contrato(perfil: dict) -> dict:
    """Quem responde por cada destino — a regra vive em dados/perfis.py."""
    return perfis_mod.contrato_por_destino(perfil)


def _chave(texto: str) -> str:
    return perfis_mod.chave_de_destino(texto)


def _frota_por_tipo(plano: dict) -> list:
    """Quantos veículos de cada tipo o plano exige, e por quê aquele tipo.

    O total sozinho não compra nada: quem vai licitar precisa da linha
    "19 ônibus de 31 lugares, 3 vans acessíveis, 1 micro".
    """
    fo = plano.get("frota_otimizada") or {}
    custos = (plano.get("premissas") or {}).get("custos_por_tipo") or {}
    atual = (plano.get("frota_atual") or {}).get("composicao") or {}
    linhas = []
    for tipo, quantos in sorted((fo.get("composicao") or {}).items(),
                                key=lambda kv: -kv[1]):
        c = custos.get(tipo, {})
        linhas.append({
            "id": tipo, "nome": c.get("nome", tipo), "quantos": quantos,
            "capacidade": c.get("capacidade"),
            "posicoes_cadeirante": c.get("posicoes_cadeirante"),
            "custo_fixo_mes": c.get("fixo_mes"),
            "custo_km": c.get("custo_km"),
            "consumo_km_l": c.get("consumo_km_l"),
            "lugares": (c.get("capacidade") or 0) * quantos,
            "hoje": atual.get(tipo),
            "diferenca": (quantos - atual[tipo]) if tipo in atual else None,
        })
    # tipo que a operação tem hoje e o plano não usa mais é informação, não
    # omissão: some da frota, e quem lê precisa saber que sumiu
    for tipo, quantos in atual.items():
        if tipo not in (fo.get("composicao") or {}):
            c = custos.get(tipo, {})
            linhas.append({
                "id": tipo, "nome": c.get("nome", tipo), "quantos": 0,
                "capacidade": c.get("capacidade"),
                "posicoes_cadeirante": c.get("posicoes_cadeirante"),
                "custo_fixo_mes": c.get("fixo_mes"),
                "custo_km": c.get("custo_km"),
                "consumo_km_l": c.get("consumo_km_l"),
                "lugares": 0, "hoje": quantos, "diferenca": -quantos,
            })
    return linhas


def _turnos(perfil: dict, embutido, premissas: dict) -> list:
    """Turno com a janela inteira — meia informação vira uma coluna de '—'."""
    turnos = perfil.get("turnos") or [
        {"id": t.id, "nome": t.nome,
         "janela_chegada": list(t.janela_chegada),
         "jornada_max_min": t.jornada_max_min,
         "duracao_min": t.duracao_min}
        for t in embutido.turnos]
    # o teto de coleta que o motor usou de verdade está nas premissas do plano
    maximos = premissas.get("jornada_max_turno_min") or {}
    return [dict(t, jornada_max_min=maximos.get(t.get("id"),
                                                t.get("jornada_max_min")))
            for t in turnos]


def _ajustes(plano: dict, perfil: dict) -> dict:
    """Os parâmetros que decidem o resultado, num lugar só.

    Tudo aqui muda a rota, o número de veículos ou o preço. Por isso é uma
    tela, e não um arquivo de configuração que ninguém acha.
    """
    premissas = plano.get("premissas") or {}
    agrupamento = plano.get("agrupamento") or {}
    embutido = perfis_mod.EMBUTIDOS.get(perfil.get("id"),
                                        perfis_mod.PERFIL_ESCOLAR)

    def do_perfil(chave):
        return perfil.get(chave, getattr(embutido, chave, None))

    tipos = perfil.get("tipos_veiculo")
    if not tipos:
        # plano antigo não guardou o perfil: o catálogo real é o que está nas
        # premissas do próprio plano — foi com ele que o motor decidiu
        tipos = [{"id": k, "nome": v.get("nome"),
                  "capacidade": v.get("capacidade"),
                  "posicoes_cadeirante": v.get("posicoes_cadeirante"),
                  "custo_km": v.get("custo_km"),
                  "custo_fixo_mes": v.get("fixo_mes"),
                  "consumo_km_l": v.get("consumo_km_l")}
                 for k, v in (premissas.get("custos_por_tipo") or {}).items()]

    return {
        "tempo": {
            "max_trajeto_min": premissas.get(
                "tempo_max_trajeto_min", do_perfil("tempo_max_trajeto_min")),
            "fator_porta_a_porta": do_perfil("fator_tempo_bordo"),
            "folga_porta_a_porta_min": do_perfil("folga_tempo_bordo_min"),
            "embarque_comum_min": do_perfil("embarque_comum_min"),
            "embarque_cadeirante_min": do_perfil("embarque_cadeirante_min"),
            "virada_min": premissas.get("tempo_virada_min"),
        },
        "caminhada": {
            "raio_urbano_m": agrupamento.get(
                "raio_urbano_m", agrupar_mod.RAIO_URBANO_M),
            "raio_rural_m": agrupamento.get(
                "raio_rural_m", agrupar_mod.RAIO_RURAL_M),
        },
        "tipos_veiculo": tipos,
        "turnos": _turnos(perfil, embutido, premissas),
        "jornada": perfil.get("regras_jornada"),
        "custos": {
            "diesel_l": premissas.get("preco_diesel_l"),
            "dias_mes": premissas.get("dias_letivos_mes"),
            "motorista_mes": do_perfil("custo_motorista_mes"),
        },
        "fonte_tempos": premissas.get("fonte_tempos"),
        "endpoint": "POST /api/perfil",
    }


def _por_contrato(viagens: list, contrato: dict) -> dict:
    """Resumo por contraparte, com as duas ressalvas que ele exige.

    1. veículo que serve dois contratos aparece nos dois: a coluna NÃO soma
       para a frota;
    2. o que se conta aqui é ESCALA de veículo (o mesmo carro na manhã e na
       tarde são duas), não veículo — a frota é o pior turno, não a soma.

    As duas são ditas na tela, em vez de virarem número que parece certo.
    """
    if not contrato:
        return {}
    linhas = {}
    for v in viagens:
        chave = v.get("contraparte_id")
        if not chave:
            continue
        linha = linhas.setdefault(chave, {
            "id": chave, "nome": v.get("contraparte"), "rotas": 0,
            "passageiros": 0, "km": 0.0, "veiculos": set(),
            "destinos": set()})
        linha["rotas"] += 1
        linha["passageiros"] += v.get("passageiros") or 0
        linha["km"] += v.get("km") or 0.0
        if v.get("veiculo"):
            linha["veiculos"].add(v["veiculo"])
        if v.get("destino"):
            linha["destinos"].add(v["destino"])
    frota = {v["veiculo"] for v in viagens if v.get("veiculo")}
    itens = [{"id": ln["id"], "nome": ln["nome"], "rotas": ln["rotas"],
              "passageiros": ln["passageiros"], "km": round(ln["km"], 1),
              "escalas_de_veiculo": len(ln["veiculos"]),
              "destinos": sorted(ln["destinos"])}
             for ln in sorted(linhas.values(),
                              key=lambda x: -x["passageiros"])]
    return {
        "rotulo": contrato["rotulo"],
        "itens": itens,
        "escalas_de_veiculo": len(frota),
        "veiculo_em_mais_de_um": (
            sum(i["escalas_de_veiculo"] for i in itens) > len(frota)),
    }


def _na_lingua(texto: str, perfil: dict) -> str:
    """Traduz "aluno" para a palavra de quem está usando o sistema.

    O importador é escolar por dentro — e tudo bem, é o nome do domínio dele.
    Na tela, quem opera fretamento lê "colaborador": o termo técnico fica no
    código, não na frase que a pessoa lê.
    """
    passageiro = perfil.get("rotulo_passageiro", "aluno")
    if passageiro == "aluno" or not texto:
        return texto
    plural = perfil.get("rotulo_passageiro_plural", passageiro + "es")
    for de, para in (("alunos", plural), ("Alunos", plural.capitalize()),
                     ("aluno", passageiro), ("Aluno", passageiro.capitalize())):
        texto = texto.replace(de, para)
    return texto


# ------------------------------------------------------------- pendências ---
def _pendencias(plano, elegibilidade, importacao, equipe) -> list:
    """O coração da tela inicial: o que precisa de decisão humana.

    Ordem: quem espera há mais tempo e quem pode ficar sem transporte vem
    primeiro. Custo entra depois — dinheiro espera, criança no ponto não.
    """
    itens = []
    resumo = (elegibilidade or {}).get("resumo") or {}
    if resumo.get("atrasados"):
        itens.append({
            "urgencia": "alta", "destino": "operar",
            "titulo": f"{resumo['atrasados']} pedidos de porta a porta passaram "
                      f"do prazo",
            "detalhe": f"O prazo assumido é de {resumo.get('prazo_dias', 15)} "
                       f"dias. A média de espera hoje é de "
                       f"{resumo.get('dias_em_aberto_media', 0)} dias.",
            "quem_decide": "analista da secretaria",
            "acao": "Abrir a fila de análise",
        })

    nao_atendida = (plano or {}).get("demanda_nao_atendida") or {}
    if nao_atendida.get("alunos"):
        exemplo = (nao_atendida.get("pontos") or [{}])[0]
        itens.append({
            "urgencia": "alta", "destino": "planejar",
            "titulo": f"{nao_atendida['alunos']} pessoas não cabem em rota "
                      f"nenhuma",
            "detalhe": f"O trajeto mínimo delas já passa do limite de tempo. "
                       f"Ex.: {exemplo.get('ponto', '—')} → "
                       f"{exemplo.get('escola', '—')}, "
                       f"{exemplo.get('minutos_minimos', '—')} min contra "
                       f"{exemplo.get('limite_min', '—')} min permitidos.",
            "quem_decide": "secretaria",
            "acao": "Ver os casos e decidir",
        })

    resumo_imp = (importacao or {}).get("resumo") or {}
    if resumo_imp.get("precisam_ajuste_no_mapa"):
        itens.append({
            "urgencia": "media", "destino": "planejar",
            "titulo": f"{resumo_imp['precisam_ajuste_no_mapa']} endereços estão "
                      f"no ponto do bairro",
            "detalhe": "Eles entraram na rota pela referência do bairro porque "
                       "a planilha não trouxe coordenada. Arrastar cada um "
                       "para a casa certa melhora o percurso e o horário.",
            "quem_decide": "quem conhece o município",
            "acao": "Ajustar no mapa",
        })

    a_vencer = (elegibilidade or {}).get("a_vencer_30_dias") or []
    if a_vencer:
        itens.append({
            "urgencia": "media", "destino": "operar",
            "titulo": f"{len(a_vencer)} concessões vencem em 30 dias",
            "detalhe": "Sem renovação, essas famílias perdem o porta a porta "
                       "no dia seguinte ao vencimento — e descobrem quando o "
                       "veículo não encostar na porta.",
            "quem_decide": "analista da secretaria",
            "acao": "Avisar as famílias",
        })

    if (equipe or {}).get("resumo", {}).get("escalas_com_problema"):
        itens.append({
            "urgencia": "alta", "destino": "operar",
            "titulo": f"{equipe['resumo']['escalas_com_problema']} escalas "
                      f"fora da regra de jornada",
            "detalhe": "Jornada, intervalo ou interjornada acima do permitido. "
                       "Escala assim não pode ir para a rua.",
            "quem_decide": "quem assina a escala",
            "acao": "Rever a escala",
        })

    avisos = (plano or {}).get("coerencia") or []
    if avisos:
        itens.append({
            "urgencia": "media", "destino": "planejar",
            "titulo": "A frota informada não bate com a demanda da planilha",
            "detalhe": avisos[0],
            "quem_decide": "quem enviou a base",
            "acao": "Conferir a base",
        })

    extras = (equipe or {}).get("resumo", {}).get("com_hora_extra") or 0
    if extras:
        minutos = (equipe or {}).get("resumo", {}).get("hora_extra_total_min", 0)
        itens.append({
            "urgencia": "baixa", "destino": "operar",
            "titulo": f"{extras} escala fecha com hora extra"
                      if extras == 1 else
                      f"{extras} escalas fecham com hora extra",
            "detalhe": f"São {minutos} min além da jornada normal, dentro do "
                       f"limite legal de 120 min por dia. Cabe na lei, mas "
                       f"custa — dá para redistribuir entre os turnos.",
            "quem_decide": "quem assina a escala",
            "acao": "Ver a escala do dia",
        })
    return itens


# -------------------------------------------------------------- montagem ---
def montar(caminho_plano: str = None, com_comercial: bool = True,
           chave_atual: str = None) -> dict:
    plano = economia_mod.carregar_relatorio(
        caminho_plano or economia_mod.RELATORIO_PADRAO)
    premissas = economia_mod.premissas_do_relatorio(plano)
    painel = economia_mod.montar_painel(plano, premissas, com_cenarios=False)

    perfil = plano.get("perfil") or {}
    e_fretamento = perfil.get("vertical") == "fretamento"

    # Porta a porta e concessão de PCD são do transporte escolar. Numa
    # operação de empresa esses números seriam de outra operação — mostrar
    # aqui seria mentira com cara de dado.
    elegibilidade = None if e_fretamento else elegibilidade_mod.montar()

    # O relatório de importação só vale para o plano que saiu daquela
    # planilha. Sem conferir o nome do arquivo, a tela mostra o erro de uma
    # importação em cima dos números de outra.
    origem = plano.get("origem") or {}
    lido = _opcional("importacao.json")
    importacao = lido if (lido or {}).get("arquivo") == origem.get("arquivo") \
        else None
    rodadas = _opcional("rodadas.json")
    aprendizado = _opcional("aprendizado.json")
    equipe = plano.get("equipe")
    eventos = registro.ler_eventos()
    faltas = onde_esta.faltas_do_dia(eventos)

    passageiro = perfil.get("rotulo_passageiro_plural", "alunos")

    comercial = None
    if com_comercial and e_fretamento:
        preco = precificacao_mod.precificar(plano, Premissas())
        cenarios = precificacao_mod.sensibilidade(plano, Premissas())
        diagnostico = None
        if os.path.exists(LINHAS_ATUAIS):
            lido = operacao_mod.importar(
                LINHAS_ATUAIS, plano["premissas"]["custos_por_tipo"])
            if lido["linhas"]:
                diagnostico = diagnostico_mod.diagnosticar(lido["linhas"], plano)
        comercial = {"preco": preco, "cenarios": cenarios,
                     "diagnostico": diagnostico}

    veiculos = (plano.get("frota_otimizada") or {}).get("veiculos", [])
    rota_exemplo = rotas.rota_do_dia(veiculos[0]["id"], plano) if veiculos else {}

    # Mapa vivo: é o centro da tela de operação nos sistemas que funcionam
    # (Spare, RideCo). Vai o desenho, não a tabela — a tabela fica ao lado.
    geografia = plano.get("geografia") or {}
    viagens = (plano.get("frota_otimizada") or {}).get("viagens", [])
    # Quem responde pelo destino: fornecedor do lote (prefeitura) ou cliente
    # dono da planta (transportadora). Vai por viagem, nunca por veículo — o
    # mesmo carro pode servir contratos diferentes no mesmo dia.
    contrato = _contrato(perfil)
    por_destino = contrato.get("por_destino", {})

    def _parte(destino_id, nome=None):
        return (por_destino.get(_chave(destino_id))
                or por_destino.get(_chave(nome)) or {})

    nome_do_destino = {d.get("id"): d.get("nome")
                       for d in geografia.get("escolas", [])}

    mapa = {
        "destinos": [dict(d,
                          contraparte=_parte(d.get("id"),
                                             d.get("nome")).get("nome"),
                          contraparte_id=_parte(d.get("id"),
                                                d.get("nome")).get("id"))
                     for d in geografia.get("escolas", [])],
        "pontos": geografia.get("pontos", {}),
        "viagens": [{"id": v["id"], "destino": v.get("escola"),
                     "destino_id": v.get("escola_id"),
                     "contraparte": _parte(
                         v.get("escola_id"),
                         v.get("escola") or nome_do_destino.get(
                             v.get("escola_id"))).get("nome"),
                     "contraparte_id": _parte(
                         v.get("escola_id"),
                         v.get("escola") or nome_do_destino.get(
                             v.get("escola_id"))).get("id"),
                     "turno": v.get("turno_nome"), "veiculo": v.get("veiculo"),
                     "paradas": v.get("paradas", []),
                     "passageiros": v.get("alunos"),
                     "ocupacao": v.get("ocupacao_pct"),
                     "km": v.get("km_viagem"), "min": v.get("min_viagem")}
                    for v in viagens],
        "pings": [{"lat": e.get("lat"), "lon": e.get("lon"),
                   "veiculo": e.get("motorista"), "em": e.get("em")}
                  for e in eventos
                  if e.get("tipo") == "ping" and e.get("lat") is not None][-12:],
    }

    # Cenários: o padrão que Optibus e Via provaram — comparar antes de
    # publicar, em vez de recalcular no escuro.
    cenarios_plano = economia_mod.grade_de_cenarios(
        plano, premissas,
        precos_diesel=sorted({premissas.preco_diesel_l,
                              round(premissas.preco_diesel_l * 1.15, 2),
                              round(premissas.preco_diesel_l * 1.3, 2)}),
        dias_letivos=sorted({premissas.dias_letivos_mes, 20, 24}))

    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "operacao": {
            "nome": plano.get("municipio"),
            "vertical": perfil.get("vertical", "escolar"),
            "passageiro": perfil.get("rotulo_passageiro", "aluno"),
            "passageiros": passageiro,
            "destino": perfil.get("rotulo_destino", "escola"),
            "destinos": perfil.get("rotulo_destino_plural", "escolas"),
        },
        "operacoes": [{"rotulo": o["rotulo"], "arquivo": o["arquivo"],
                       "atual": o["chave"] == chave_atual}
                      for o in OPERACOES],
        "pendencias": _pendencias(plano, elegibilidade, importacao, equipe),
        "resumo": {
            "passageiros": painel["demanda"]["alunos"],
            "veiculos": painel["otimizada"]["total_veiculos"],
            "viagens": painel["qualidade"]["viagens"],
            "motoristas": (equipe or {}).get("resumo", {}).get("motoristas"),
            "economia_mes": (painel.get("economia") or {}).get("custo_mes"),
            "ocupacao_pct": painel["qualidade"]["ocupacao_media_pct"],
            "selo": _selo("planejado"),
        },
        "hoje": {
            "eventos": registro.resumo(),
            "faltas": {"avisadas": faltas["faltas"],
                       "desfeitas": faltas["avisos_desfeitos"]},
            "rodadas": (rodadas or {}).get("resumo", {}),
            "politica": (rodadas or {}).get("politica", {}),
            "selo": _selo("medido" if registro.resumo().get("eventos")
                          else "planejado"),
            "rota_exemplo": rota_exemplo,
        },
        "planejar": {
            "importacao": (importacao or {}).get("resumo", {}),
            "problemas": [
                dict(p, problema=_na_lingua(p.get("problema"), perfil),
                     sugestao=_na_lingua(p.get("sugestao"), perfil))
                for p in ((importacao or {}).get("problemas") or [])[:60]],
            "agrupamento": plano.get("agrupamento", {}),
            "nao_atendida": plano.get("demanda_nao_atendida", {}),
            "coerencia": plano.get("coerencia", []),
            "frota": painel["otimizada"],
            "frota_por_tipo": _frota_por_tipo(plano),
            "frota_atual": painel.get("atual"),
            "economia": painel.get("economia"),
            "memoria": painel.get("memoria_calculo", []),
            "por_turno": painel["qualidade"].get("por_turno", []),
            "arquivo": (importacao or {}).get("arquivo"),
            "origem": origem,
            "demanda": plano.get("demanda", {}),
            "cenarios": cenarios_plano,
            "premissas": painel.get("premissas", {}),
        },
        "mapa": mapa,
        "operar": {
            "veiculos": [{"id": v["id"], "tipo": v["tipo_nome"],
                          "turno": v["turno_nome"], "viagens": len(v["viagens"]),
                          "passageiros": v["alunos"],
                          "ocupacao": v.get("ocupacao_media_pct"),
                          "jornada": v["min_turno"]}
                         for v in veiculos[:18]],
            "equipe": equipe,
            "contratos": _por_contrato(mapa["viagens"], contrato),
            "elegibilidade": elegibilidade,
            "aprendizado": {
                "erro_inicial": (aprendizado or {}).get("semanas", [{}])[0]
                .get("mae_min"),
                "erro_atual": (aprendizado or {}).get("semanas", [{}])[-1]
                .get("mae_min"),
                "origem": (aprendizado or {}).get("origem"),
            },
        },
        "fiscalizar": _opcional("fiscalizacao.json"),
        "ajustes": _ajustes(plano, perfil),
        "vender": comercial,
    }


def gerar(saida: str = SAIDA_PADRAO, caminho_plano: str = None,
          chave_atual: str = "prefeitura") -> str:
    with open(os.path.join(DIR_UI, "app.html"), encoding="utf-8") as f:
        molde = f.read()
    dados = montar(caminho_plano, chave_atual=chave_atual)
    html = molde.replace("__DADOS__",
                         json.dumps(dados, ensure_ascii=False))
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(html)
    return saida


def gerar_todas(dir_saida: str = DIR_TELAS) -> list:
    """As duas operações, para o seletor do topo ter para onde ir."""
    return [gerar(os.path.join(dir_saida, o["arquivo"]), o["plano"], o["chave"])
            for o in OPERACOES]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Protótipo do sistema remodelado")
    ap.add_argument("--plano", default=None)
    ap.add_argument("--saida", default=None)
    a = ap.parse_args(argv)
    if a.saida or a.plano:
        print(f"Sistema em {gerar(a.saida or SAIDA_PADRAO, a.plano)}")
    else:
        for caminho in gerar_todas():
            print(f"Sistema em {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
