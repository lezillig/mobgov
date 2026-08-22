# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-painel
A TELA DO SISTEMA: o console de quem opera o transporte todo dia.

O painel de economia é um relatório — foi feito para virar PDF e ir para a
prestação de contas. Esta é outra coisa: é onde o servidor da secretaria
trabalha. As quatro abas correspondem às quatro perguntas que ele faz por dia:

    Hoje           o que está acontecendo agora, e o que já mudou no plano
    Elegibilidade  quem está esperando decisão, há quanto tempo, e com o quê
    Equipe         quantos motoristas a escala exige, e a jornada de cada um
                   (só aparece quando o plano publicado separa esse custo —
                   no escolar, o motorista vem dentro do custo do veículo)
    Assistente     "quanto eu economizo?" respondido com número do motor
    Economia       o resumo que ele leva para a reunião

Mesmas regras do painel, pelas mesmas razões: página autocontida (abre em
notebook de prefeitura sem internet), todo número vindo do motor, e o que não
foi medido aparece com selo. As abas são JavaScript de dez linhas — sem
framework, porque isto precisa abrir em cinco segundos num Windows velho.

Uso:
    python -m painel.console
    python -m painel.console --saida /tmp/console.html
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

try:
    from .formato import esc, numero, pct, reais, reais_curto
    from . import economia as economia_mod
except ImportError:                       # execução direta
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from painel.formato import esc, numero, pct, reais, reais_curto
    from painel import economia as economia_mod

from conversa import ferramentas as ferramentas_mod  # noqa: E402
from conversa import redator, roteador  # noqa: E402
from elegibilidade import relatorio as elegibilidade_mod  # noqa: E402
from operacao import onde_esta, registro, rota_do_dia as rotas  # noqa: E402

DIR_PAINEL = os.path.dirname(os.path.abspath(__file__))
DIR_BASE = os.path.dirname(DIR_PAINEL)
SAIDA_PADRAO = os.path.join(DIR_BASE, "relatorios", "console.html")

# As perguntas que o gestor faz de verdade, na ordem em que aparecem na
# reunião. A resposta é calculada aqui, no servidor, pelas mesmas ferramentas
# que o assistente usa — a página não pensa, só mostra.
PERGUNTAS = [
    "Quanto eu economizo por mês?",
    "Por que preciso de tantos ônibus?",
    "E se o diesel for a R$ 8,20?",
    "A planilha da secretaria entrou direito?",
    "Como está a fila do porta a porta?",
    "Como está a operação hoje?",
    "O que o sistema aprendeu até agora?",
]


def _ativo(nome: str) -> str:
    with open(os.path.join(DIR_PAINEL, "assets", nome), encoding="utf-8") as f:
        return f.read()


def _kpi(rotulo, valor, detalhe, destaque=False, piora=False) -> str:
    classe = "kpi" + (" destaque" if destaque and not piora else "") + (
        " piora" if piora else "")
    return (f'<div class="{classe}"><div class="rotulo">{esc(rotulo)}</div>'
            f'<div class="valor">{esc(valor)}</div>'
            f'<div class="detalhe">{esc(detalhe)}</div></div>')


# ------------------------------------------------------------------ dados ---
def coletar(caminho_relatorio: str = None) -> dict:
    """Junta tudo o que as abas mostram. Nenhuma fonte é obrigatória."""
    rel = economia_mod.carregar_relatorio(
        caminho_relatorio or economia_mod.RELATORIO_PADRAO)
    premissas = economia_mod.premissas_do_relatorio(rel)
    painel = economia_mod.montar_painel(rel, premissas, com_cenarios=False)

    plano = rotas.carregar_plano()
    eventos = registro.ler_eventos()
    respostas = []
    for pergunta in PERGUNTAS:
        nome, argumentos, _ = roteador.escolher(pergunta)
        resultado = ferramentas_mod.executar(nome, argumentos)
        respostas.append({"pergunta": pergunta, "ferramenta": nome,
                          "resposta": redator.escrever(nome, resultado)})

    return {
        "painel": painel,
        "plano": plano,
        "equipe": rel.get("equipe"),
        "perfil": rel.get("perfil"),
        "motoristas": rotas.motoristas(plano),
        "eventos": eventos,
        "resumo_eventos": registro.resumo(),
        "faltas": onde_esta.faltas_do_dia(eventos),
        "rodadas": economia_mod.carregar_opcional(
            economia_mod.RELATORIO_RODADAS),
        "elegibilidade": elegibilidade_mod.montar(),
        "respostas": respostas,
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ------------------------------------------------------------------- abas ---
def aba_hoje(d: dict) -> str:
    resumo, faltas = d["resumo_eventos"], d["faltas"]
    rodadas = (d["rodadas"] or {}).get("resumo", {})
    plano, p = d["plano"], d["painel"]
    veiculos = (plano.get("frota_otimizada") or {}).get("veiculos", [])

    # Armadilha do projeto: cada linha aqui é um veículo EM UM TURNO. A frota
    # é o pior turno, não a soma dos dois — contar as linhas daria 41 veículos
    # numa operação que roda com 23.
    escalas = len(veiculos)
    frota = p["otimizada"]["total_veiculos"]
    turnos = {}
    for v in veiculos:
        turnos[v["turno_nome"]] = turnos.get(v["turno_nome"], 0) + 1

    mostradas = veiculos[:14]
    linhas = "".join(
        f'<tr><td><b>{esc(v["id"])}</b></td>'
        f'<td class="curta">{esc(v["tipo_nome"])}</td>'
        f'<td>{esc(v["turno_nome"])}</td>'
        f'<td class="num">{len(v["viagens"])}</td>'
        f'<td class="num">{numero(v["alunos"])}</td>'
        f'<td class="num">{numero(v["capacidade"] * len(v["viagens"]))}</td>'
        f'<td class="num">{numero(v["min_turno"])} min</td></tr>'
        for v in mostradas)
    rodape_tabela = (
        f'<tfoot><tr><td colspan="7">Mostrando {len(mostradas)} de '
        f'{escalas} escalas — a lista completa está no plano '
        f'(<code>relatorios/dimensionamento.json</code>).</td></tr></tfoot>'
        if escalas > len(mostradas) else "")

    ultimos = sorted(d["eventos"], key=lambda e: e.get("em") or "",
                     reverse=True)[:8]
    eventos_html = "".join(
        f'<tr><td>{esc((e.get("em") or "")[11:16])}</td>'
        f'<td><span class="marcador {"atual" if e["tipo"] in ("imprevisto", "falta") else "otim"}">'
        f'{esc(e["tipo"])}</span></td>'
        f'<td>{esc(e.get("motorista") or e.get("aluno") or "—")}</td>'
        f'<td>{esc(e.get("ponto") or e.get("motivo") or e.get("viagem") or "—")}</td>'
        f'</tr>' for e in ultimos) or (
        '<tr><td colspan="4">Nenhum evento recebido ainda hoje. Os eventos '
        'chegam quando o app do motorista sincroniza.</td></tr>')

    por_viagem = "".join(
        f'<li><b>{esc(viagem or "sem viagem")}</b>: '
        f'{len(alunos)} aviso(s) — {esc(", ".join(a["ponto"] for a in alunos))}</li>'
        for viagem, alunos in faltas["por_viagem"].items()) or (
        '<li>Nenhuma família avisou falta hoje.</li>')

    detalhe_turnos = " · ".join(f"{nome}: {qtd}"
                                for nome, qtd in sorted(turnos.items()))
    return (
        '<section><h2>Operação de hoje</h2>'
        '<div class="kpis">'
        + _kpi("Frota do dia", f'{frota} veículos',
               f'{escalas} escalas ({esc(detalhe_turnos)}) — o mesmo veículo '
               f'atende os dois turnos', destaque=True)
        + _kpi("Viagens programadas",
               numero(sum(len(v["viagens"]) for v in veiculos)),
               f'{numero(p["demanda"]["alunos"])} alunos por dia')
        + _kpi("Eventos recebidos", numero(resumo.get("eventos", 0)),
               f'{numero(resumo.get("motoristas", 0))} motorista(s) '
               f'sincronizaram')
        + _kpi("Faltas avisadas pela família", numero(faltas["faltas"]),
               f'{numero(faltas["avisos_desfeitos"])} aviso(s) desfeito(s)')
        + _kpi("Km poupados nas rodadas",
               f'−{numero(rodadas.get("km_economizados", 0), 1)} km',
               f'{numero(rodadas.get("corridas_remanejadas", 0))} corridas '
               f'trocaram de veículo · '
               f'{numero(rodadas.get("promessas_quebradas", 0))} horários '
               f'quebrados')
        + '</div>'
        '<div class="rolagem" style="margin-top:20px"><table>'
        '<caption>Escala do dia — cada linha é um veículo em um turno</caption>'
        '<thead><tr><th>Veículo</th><th>Tipo</th><th>Turno</th>'
        '<th class="num">Viagens</th><th class="num">Alunos</th>'
        '<th class="num">Lugares</th><th class="num">Jornada</th></tr></thead>'
        f'<tbody>{linhas}</tbody>{rodape_tabela}</table></div>'
        '<div class="colunas" style="margin-top:22px">'
        '<div><div class="rolagem"><table>'
        '<caption>Últimos eventos recebidos</caption>'
        '<thead><tr><th>Hora</th><th>Tipo</th><th>Quem</th><th>Onde</th></tr>'
        f'</thead><tbody>{eventos_html}</tbody></table></div></div>'
        '<div><table><caption>Avisos das famílias hoje</caption>'
        f'<tbody><tr><td><ul class="lista">{por_viagem}</ul></td></tr>'
        '</tbody></table></div></div>'
        '<div class="aviso"><b>De onde vem cada coisa:</b> a escala sai do '
        'plano do motor; os eventos, do app do motorista; os avisos de falta, '
        'do app do responsável. Nada aqui é digitado à mão.</div>'
        '</section>'
    )


def aba_elegibilidade(d: dict) -> str:
    el = d["elegibilidade"]
    if not el or not el.get("resumo"):
        return ('<section><h2>Elegibilidade</h2><p class="chamada">Nenhum '
                'pedido ainda. Rode <code>python elegibilidade/demonstracao.py'
                '</code> para ver a fila de exemplo.</p></section>')
    r = el["resumo"]
    classe_selo = "selo" if el.get("origem") != "operacao_real" else "selo medido"

    linhas = "".join(
        f'<tr class="{"atrasada" if s["atrasado"] else ""}">'
        f'<td><b>{esc(s["protocolo"])}</b></td>'
        f'<td>{esc(s["estado_em_portugues"])}</td>'
        f'<td>{esc(s["aberto_em"])}</td>'
        # pedido já decidido não tem "dias em aberto"; zero ali se leria como
        # "decidido no mesmo dia", que é outra coisa
        f'<td class="num">{numero(s["dias_em_aberto"]) if s["estado"] in ("recebido", "em_analise", "pendente_de_informacao") else "—"}</td>'
        f'<td>{esc(s["bairro"] or "—")} → {esc(s["destino"] or "—")}</td>'
        f'<td>{esc(s["resumo_do_perfil"] or "—")}</td>'
        f'<td>{esc(s["analista"] or "—")}</td></tr>'
        for s in el["fila"][:16])

    vencendo = "".join(
        f'<li>{esc(v["protocolo"])} vence em {esc(v["vence_em"])}</li>'
        for v in el.get("a_vencer_30_dias", [])) or (
        '<li>Nenhuma concessão vence nos próximos 30 dias.</li>')

    return (
        '<section><h2>Elegibilidade ao porta a porta '
        f'<span class="{classe_selo}">{esc(el.get("selo", ""))}</span></h2>'
        '<div class="kpis">'
        + _kpi("Em aberto", numero(r["em_aberto"]),
               f'de {numero(r["pedidos"])} pedidos', destaque=True)
        + _kpi("Fora do prazo", numero(r["atrasados"]),
               f'prazo assumido: {r["prazo_dias"]} dias',
               piora=r["atrasados"] > 0)
        + _kpi("Dias em aberto (média)", numero(r["dias_em_aberto_media"], 1),
               'do protocolo até hoje')
        + _kpi("Aprovações sem laudo em papel",
               pct(el.get("aprovacoes_sem_laudo_pct", 0)),
               'cadastro do município, escola ou avaliação presencial')
        + '</div>'
        '<div class="rolagem" style="margin-top:20px"><table>'
        '<caption>Fila de análise — atrasados primeiro</caption>'
        '<thead><tr><th>Protocolo</th><th>Situação</th><th>Aberto em</th>'
        '<th class="num">Dias</th><th>Trajeto</th><th>Perfil</th>'
        '<th>Analista</th></tr></thead>'
        f'<tbody>{linhas}</tbody></table></div>'
        f'<ul class="lista">{vencendo}</ul>'
        '<div class="aviso"><b>O sistema não decide:</b> ele organiza, propõe '
        'com o trecho do documento que sustenta cada proposta e registra quem '
        'decidiu. Aprovar sem analista, aprovar sem evidência ou negar sem '
        'justificativa são recusados pelo próprio código.</div>'
        '</section>'
    )


def _observacao_da_escala(motorista: dict, horas) -> str:
    partes = []
    if motorista.get("dupla_pegada"):
        partes.append("dupla pegada")
    if motorista.get("hora_extra_min"):
        partes.append(f"{horas(motorista['hora_extra_min'])} extra")
    return esc(" · ".join(partes)) if partes else "—"


def aba_equipe(d: dict) -> str:
    """Escala de motoristas — a conta que o número de veículos não responde."""
    equipe = d.get("equipe")
    if not equipe or not equipe.get("resumo"):
        return ""
    r = equipe["resumo"]
    regras = equipe.get("regras", {})

    def horas(minutos):
        minutos = int(round(minutos or 0))
        return f"{minutos // 60}h{minutos % 60:02d}"

    linhas = "".join(
        f'<tr class="{"atrasada" if m.get("problemas") else ""}">'
        f'<td><b>{esc(m["id"])}</b></td>'
        f'<td>{esc(m["inicio"])}–{esc(m["fim"])}</td>'
        f'<td class="num">{horas(m["jornada_min"])}</td>'
        f'<td class="num">{horas(m["amplitude_min"])}</td>'
        f'<td>{esc(", ".join(m.get("turnos", [])))}</td>'
        f'<td>{esc(", ".join(m.get("veiculos", [])))}</td>'
        f'<td>{_observacao_da_escala(m, horas)}</td>'
        f'<td>{esc(m["problemas"][0]) if m.get("problemas") else "—"}</td></tr>'
        for m in equipe.get("motoristas", [])[:20])

    por_turno = "".join(
        f'<tr><td>{esc(turno)}</td><td class="num">{numero(qtd)}</td></tr>'
        for turno, qtd in sorted((r.get("por_turno") or {}).items()))

    return (
        '<section><h2>Equipe — quantos motoristas a operação exige</h2>'
        '<p class="chamada">O veículo roda todos os turnos; o motorista não. '
        'Este número sai da jornada, não da frota — e é ele que entra no '
        'custo. As regras usadas estão listadas abaixo: acordo coletivo muda '
        'quase todas, e quem assina a escala precisa poder conferir.</p>'
        '<div class="kpis">'
        + _kpi("Motoristas", numero(r["motoristas"]),
               f'para {numero(r["blocos"])} blocos de trabalho', destaque=True)
        + _kpi("Jornada média", horas(r["jornada_media_min"]),
               f'{pct(r["ocupacao_da_jornada_pct"])} da jornada normal')
        + _kpi("Com dupla pegada", numero(r["com_dupla_pegada"]),
               'pega cedo, larga, volta à tarde')
        + _kpi("Escalas fora da regra", numero(r["escalas_com_problema"]),
               'jornada, intervalo ou interjornada',
               piora=r["escalas_com_problema"] > 0)
        + '</div>'
        '<div class="rolagem" style="margin-top:18px"><table>'
        '<caption>Escala do dia — motorista a motorista</caption>'
        '<thead><tr><th>Motorista</th><th>Da primeira à última hora</th>'
        '<th class="num">Jornada</th><th class="num">Amplitude</th>'
        '<th>Turnos</th><th>Veículos</th><th>Observação</th>'
        '<th>Problema</th></tr></thead>'
        f'<tbody>{linhas}</tbody></table></div>'
        '<div class="colunas" style="margin-top:18px">'
        '<div><table><caption>Motoristas por turno</caption>'
        '<thead><tr><th>Turno</th><th class="num">Motoristas</th></tr></thead>'
        f'<tbody>{por_turno}</tbody></table></div>'
        '<div><table><caption>Regras usadas nesta escala</caption><tbody>'
        + "".join(
            f'<tr><td>{esc(rotulo)}</td><td class="num">{esc(valor)}</td></tr>'
            for rotulo, valor in (
                ("Jornada normal", horas(regras.get("jornada_normal_min"))),
                ("Hora extra máxima", horas(regras.get("hora_extra_max_min"))),
                ("Direção contínua máxima",
                 horas(regras.get("direcao_continua_max_min"))),
                ("Parada obrigatória depois disso",
                 f'{regras.get("parada_obrigatoria_min", "?")} min'),
                ("Intervalo de refeição",
                 f'{regras.get("intervalo_refeicao_min", "?")} min'),
                ("Interjornada", horas(regras.get("interjornada_min"))),
                ("Amplitude máxima", horas(regras.get("amplitude_max_min"))),
                ("Dupla pegada permitida",
                 "sim" if regras.get("permite_dupla_pegada") else "não")))
        + '</tbody></table></div></div>'
        f'<div class="aviso"><b>Custo da equipe:</b> '
        f'{reais(equipe.get("custo_equipe_mes", 0))}/mês — '
        f'{numero(r["motoristas"])} motoristas a '
        f'{reais(equipe.get("custo_motorista_mes", 0))} cada, sem encargos e '
        f'benefícios (que entram na precificação).</div>'
        '</section>'
    )


def aba_assistente(d: dict) -> str:
    cartoes = "".join(
        f'<details class="pergunta"{" open" if i == 0 else ""}>'
        f'<summary>{esc(r["pergunta"])}</summary>'
        f'<div class="ferramenta">ferramenta: '
        f'<code>{esc(r["ferramenta"])}</code></div>'
        f'<pre>{esc(r["resposta"])}</pre></details>'
        for i, r in enumerate(d["respostas"]))
    return (
        '<section><h2>Perguntar ao sistema</h2>'
        '<p class="chamada">O gestor pergunta em português e a resposta sai '
        'com o número do motor. Cada resposta abaixo foi produzida agora, '
        'chamando a ferramenta indicada — o modelo de linguagem escolhe a '
        'ferramenta e escreve a frase, <b>o número vem do Python</b>. Quando '
        'há chave de API, o assistente ainda confere cada valor escrito '
        'contra o que a ferramenta devolveu e reprova o que não bater.</p>'
        f'<div class="perguntas">{cartoes}</div>'
        '<div class="aviso">No terminal: '
        '<code>python conversa/cli.py "quanto eu economizo por mês?"</code> — '
        'com <code>--offline</code>, responde sem internet e sem chave.</div>'
        '</section>'
    )


def aba_economia(d: dict) -> str:
    p = d["painel"]
    e, atual, otim = p["economia"], p["atual"], p["otimizada"]
    composicao = "".join(
        f'<tr><td>{esc(l["nome"])}</td><td class="num">{l["qtd"]}</td>'
        f'<td class="num">{numero(l["km_dia"])}</td>'
        f'<td class="num">{reais(l["custo_mes"])}</td></tr>'
        for l in otim["composicao"])
    return (
        '<section><h2>Economia — o resumo da reunião</h2>'
        '<div class="kpis">'
        + _kpi("Veículos", f'{atual["total_veiculos"]} → {otim["total_veiculos"]}',
               f'{pct(abs(e["reducao_frota_pct"]))} de redução', destaque=True)
        + _kpi("Economia por mês", reais_curto(e["custo_mes"]),
               f'{reais(atual["custo_mes"])} → {reais(otim["custo_mes"])}',
               destaque=True)
        + _kpi("Economia por ano", reais_curto(e["custo_ano"]),
               f'{reais(e["custo_mes"])} × 12 meses')
        + _kpi("Emissões evitadas", f'{numero(e["tco2_ano"], 1)} t',
               'CO₂ por ano')
        + '</div>'
        '<div class="rolagem" style="margin-top:20px"><table>'
        '<caption>Frota necessária</caption>'
        '<thead><tr><th>Tipo</th><th class="num">Qtd</th>'
        '<th class="num">km/dia</th><th class="num">Custo/mês</th></tr></thead>'
        f'<tbody>{composicao}</tbody></table></div>'
        '<div class="aviso">O relatório completo, com memória de cálculo, '
        'premissas e mapa, é o arquivo <code>painel-economia.html</code> — '
        'é ele que vira PDF para a prestação de contas. Gere com '
        '<code>python -m painel.render</code>.</div>'
        '</section>'
    )


CSS_CONSOLE = """
.abas{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 22px}
.abas button{font:inherit;font-size:15.5px;font-weight:700;cursor:pointer;
  border:1px solid var(--linha);background:var(--papel);color:var(--tinta-fraca);
  border-radius:10px 10px 0 0;padding:12px 18px;min-height:48px}
.abas button[aria-selected="true"]{background:var(--institucional);color:#FFF;
  border-color:var(--institucional)}
.painel-aba[hidden]{display:none}
.colunas{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
  gap:24px}
tr.atrasada td{background:var(--alerta-fundo)}
/* nome de tipo de veículo é comprido ("Ônibus escolar 31 lugares") e quebrava
   em quatro linhas dentro da coluna estreita */
td.curta{white-space:nowrap;font-size:15px}
.perguntas{display:grid;gap:10px}
details.pergunta{background:var(--papel);border:1px solid var(--linha);
  border-radius:12px;padding:14px 16px}
details.pergunta summary{font-weight:700;cursor:pointer;font-size:16.5px}
details.pergunta .ferramenta{font-size:13.5px;color:var(--tinta-fraca);
  margin-top:8px}
details.pergunta pre{white-space:pre-wrap;font-size:15px;margin-top:10px;
  font-family:inherit;background:var(--papel-2);border-radius:10px;padding:14px;
  overflow-x:auto}
code{background:var(--papel-2);border:1px solid var(--linha);border-radius:6px;
  padding:1px 6px;font-size:14.5px}
.rodape-console{color:var(--tinta-fraca);font-size:14px;margin-top:30px;
  border-top:1px solid var(--linha);padding-top:16px}
@media print{.abas{display:none}.painel-aba[hidden]{display:block}}
"""

JS_CONSOLE = """
(function () {
  "use strict";
  var botoes = Array.prototype.slice.call(
    document.querySelectorAll(".abas button"));
  function mostrar(id) {
    botoes.forEach(function (b) {
      var alvo = document.getElementById(b.getAttribute("data-aba"));
      var ativa = b.getAttribute("data-aba") === id;
      b.setAttribute("aria-selected", ativa ? "true" : "false");
      if (alvo) { alvo.hidden = !ativa; }
    });
    try { localStorage.setItem("mobgov.console.aba", id); } catch (e) {}
  }
  botoes.forEach(function (b) {
    b.addEventListener("click", function () {
      mostrar(b.getAttribute("data-aba"));
    });
  });
  var guardada = null;
  try { guardada = localStorage.getItem("mobgov.console.aba"); } catch (e) {}
  mostrar(guardada && document.getElementById(guardada) ? guardada : "hoje");
})();
"""


def renderizar(d: dict) -> str:
    p = d["painel"]
    abas = [("hoje", "Hoje", aba_hoje(d)),
            ("elegibilidade", "Elegibilidade", aba_elegibilidade(d))]
    equipe = aba_equipe(d)
    if equipe:
        # só existe quando o plano publicado separa o custo do motorista —
        # no escolar a prefeitura contrata veículo COM motorista
        abas.append(("equipe", "Equipe", equipe))
    abas += [("assistente", "Perguntar ao sistema", aba_assistente(d)),
             ("economia", "Economia", aba_economia(d))]
    botoes = "".join(
        f'<button data-aba="{ident}" role="tab" '
        f'aria-selected="{"true" if i == 0 else "false"}">{esc(rotulo)}</button>'
        for i, (ident, rotulo, _) in enumerate(abas))
    conteudo = "".join(
        f'<div class="painel-aba" id="{ident}"{"" if i == 0 else " hidden"}>'
        f'{html}</div>' for i, (ident, _, html) in enumerate(abas))

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOBGOV — Console de operação</title>
<style>{_ativo("painel.css")}{CSS_CONSOLE}</style>
</head>
<body>
<header class="topo"><div class="folha">
  <div class="marca"><span class="produto">MOBGOV</span>
    <span class="modulo">Console de operação · {esc(p["municipio"])}</span></div>
  <h1>A tela de quem opera o transporte</h1>
  <p class="subtitulo">O que está acontecendo hoje, quem espera decisão, o que
  o sistema responde quando se pergunta em português, e o resumo da economia —
  numa página que abre sem internet.</p>
  <div class="identificacao">
    <span>Alunos atendidos: <b>{numero(p["demanda"]["alunos"])}/dia</b></span>
    <span>Frota necessária: <b>{p["otimizada"]["total_veiculos"]} veículos</b></span>
    <span>Economia: <b>{reais_curto(p["economia"]["custo_mes"])}/mês</b></span>
    <span>Atualizado em: <b>{esc(d["gerado_em"])}</b></span>
  </div>
</div></header>

<div class="folha">
  <div class="abas" role="tablist">{botoes}</div>
  {conteudo}
  <p class="rodape-console">Página gerada pelo próprio sistema, com os dados
  dos relatórios em <code>relatorios/</code>. Sem requisição externa: o que
  está na tela está no arquivo.</p>
</div>
<script>{JS_CONSOLE}</script>
</body>
</html>
"""


def montar_html(caminho_relatorio: str = None) -> tuple:
    dados = coletar(caminho_relatorio)
    return renderizar(dados), dados


def gerar(saida: str = SAIDA_PADRAO, caminho_relatorio: str = None) -> str:
    html, _ = montar_html(caminho_relatorio)
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(html)
    return saida


def main():
    ap = argparse.ArgumentParser(description="Console de operação do MOBGOV")
    ap.add_argument("--saida", default=SAIDA_PADRAO)
    ap.add_argument("--relatorio", default=None)
    a = ap.parse_args()
    print(f"Console em {gerar(a.saida, a.relatorio)}")


if __name__ == "__main__":
    main()
