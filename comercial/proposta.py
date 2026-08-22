# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-comercial
A proposta: a peça que vai para o cliente, com a conta aberta.

O diferencial não é o preço bonito — é a proposta que mostra COMO o preço foi
formado e o que o cliente ganha. Quem recebe três propostas com um número no
rodapé e uma com a planilha de custo aberta, a frota justificada viagem a
viagem e a escala de motoristas conferida contra a lei, sabe qual delas foi
feita por gente que entende da operação.

Mesma regra do resto do sistema: autocontida (abre sem internet, imprime em
PDF pelo navegador) e sem número que não tenha vindo do motor ou de uma
premissa declarada na própria página.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel.formato import esc, numero, pct, reais, reais_curto  # noqa: E402

DIR_PAINEL = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "painel")
SAIDA_PADRAO = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "relatorios", "proposta.html")

CSS = """
.grupos{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:14px;margin:18px 0}
.grupo{background:var(--papel);border:1px solid var(--linha);border-radius:12px;
  padding:14px}
.grupo .rotulo{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--tinta-fraca)}
.grupo .valor{font-size:24px;font-weight:800}
.grupo .parte{font-size:13.5px;color:var(--tinta-fraca)}
.preco-grande{background:var(--institucional);color:#FFF;border-radius:14px;
  padding:22px;margin:20px 0}
.preco-grande .valor{font-size:44px;font-weight:800;letter-spacing:-.02em}
.preco-grande .detalhe{font-size:15px;opacity:.92;margin-top:6px}
.achado{background:var(--papel);border-left:4px solid var(--otim);
  border-radius:0 12px 12px 0;padding:14px 16px;margin-bottom:12px}
.achado .titulo{font-weight:700}
.achado .valor{color:var(--otim);font-weight:800}
.achado .conferir{font-size:14px;color:var(--tinta-fraca);margin-top:6px}
"""


def _ativo(nome: str) -> str:
    with open(os.path.join(DIR_PAINEL, "assets", nome), encoding="utf-8") as f:
        return f.read()


def _tabela_custo(preco: dict) -> str:
    linhas = "".join(
        f'<tr><td>{esc(l["grupo"])}</td><td>{esc(l["item"])}</td>'
        f'<td class="num">{reais(l["valor_mes"], 2)}</td>'
        f'<td>{esc(l["memoria"])}</td></tr>'
        for l in preco["custo"]["linhas"])
    return (
        '<div class="rolagem"><table>'
        '<caption>Planilha de custo mensal — aberta, item a item</caption>'
        '<thead><tr><th>Grupo</th><th>Item</th><th class="num">R$/mês</th>'
        '<th>Como foi calculado</th></tr></thead>'
        f'<tbody>{linhas}</tbody>'
        f'<tfoot><tr><td colspan="2">Custo total</td>'
        f'<td class="num">{reais(preco["custo"]["total_mes"], 2)}</td>'
        f'<td>direto + indireto</td></tr></tfoot></table></div>')


def _bloco_diagnostico(diagnostico: dict) -> str:
    if not diagnostico or not diagnostico.get("achados"):
        return ""
    r = diagnostico["resumo"]
    achados = "".join(
        f'<div class="achado"><div class="titulo">{esc(a["titulo"])} — '
        f'<span class="valor">{reais(a["economia_mes"])}/mês</span></div>'
        f'<div>{esc(a["detalhe"])}</div>'
        f'<div class="conferir">Antes de aplicar: {esc(a["o_que_conferir"])}'
        f'</div></div>'
        for a in diagnostico["achados"][:8])
    return (
        '<section><h2>O que dá para melhorar no que já roda hoje</h2>'
        '<p class="chamada">Antes de falar de contrato novo: a operação atual '
        'foi analisada linha a linha, com a quilometragem e os passageiros '
        'que a própria empresa informou. Cada achado abaixo aponta para uma '
        'linha com nome — e diz o que conferir antes de mexer, porque mexer '
        'em linha de fretamento é mexer no horário de quem bate ponto.</p>'
        '<div class="grupos">'
        f'<div class="grupo"><div class="rotulo">Linhas analisadas</div>'
        f'<div class="valor">{numero(r["linhas_analisadas"])}</div>'
        f'<div class="parte">ocupação média de '
        f'{pct(r["ocupacao_media_hoje_pct"])}</div></div>'
        f'<div class="grupo"><div class="rotulo">Frota hoje</div>'
        f'<div class="valor">{numero(r["veiculos_hoje"])}</div>'
        f'<div class="parte">contra {numero(r["veiculos_no_plano"])} no plano '
        f'otimizado</div></div>'
        f'<div class="grupo"><div class="rotulo">Ações imediatas</div>'
        f'<div class="valor">{reais_curto(r["economia_acoes_imediatas_mes"])}'
        f'</div><div class="parte">troca de veículo e fusão de linha</div></div>'
        f'<div class="grupo"><div class="rotulo">Teto do que dá para capturar</div>'
        f'<div class="valor">{reais_curto(r["economia_teto_mes"])}</div>'
        f'<div class="parte">já contém as ações acima — não some</div></div>'
        '</div>'
        f'{achados}</section>')


def renderizar(plano: dict, preco: dict, cenarios: list,
               diagnostico: dict = None, cliente: str = None) -> str:
    frota = plano["frota_otimizada"]
    equipe = (plano.get("equipe") or {}).get("resumo") or {}
    perfil = plano.get("perfil") or {}
    passageiro = perfil.get("rotulo_passageiro_plural", "passageiros")
    p = preco["preco"]
    ind = preco.get("indicadores", {})

    composicao = "".join(
        f'<tr><td>{esc(_nome_do_tipo(plano, tipo))}</td>'
        f'<td class="num">{quantidade}</td></tr>'
        for tipo, quantidade in sorted(frota["composicao"].items()))

    grupos = "".join(
        f'<div class="grupo"><div class="rotulo">{esc(grupo)}</div>'
        f'<div class="valor">{reais_curto(valor)}</div>'
        f'<div class="parte">{pct(ind.get("participacao_no_custo_pct", {}).get(grupo, 0))} '
        f'do custo</div></div>'
        for grupo, valor in preco["custo"]["por_grupo"].items())

    linhas_cenario = "".join(
        f'<tr><td>{esc(c["cenario"])}</td>'
        f'<td class="num">{reais(c["preco_mes"])}</td>'
        f'<td class="num">{"—" if not c["diferenca_pct"] else pct(c["diferenca_pct"])}</td></tr>'
        for c in cenarios)

    premissas = preco["premissas"]
    itens_premissas = "".join(
        f'<tr><td>{esc(rotulo)}</td><td class="num">{esc(valor)}</td></tr>'
        for rotulo, valor in (
            ("Regime tributário", p["regime"]),
            ("Carga sobre a receita", pct(p["carga_tributaria_pct"])),
            ("Margem alvo", pct(p["margem_alvo_pct"])),
            ("Dias de operação por mês", numero(premissas["dias_operacao_mes"])),
            ("Preço do diesel", reais(premissas["preco_diesel_l"], 2) + "/l"),
            ("Encargos sobre a folha",
             pct(premissas["encargos_sobre_salario"] * 100)),
            ("Benefícios por motorista",
             reais(premissas["beneficios_motorista_mes"]) + "/mês"),
            ("Administrativo", pct(premissas["administrativo_pct"] * 100)),
            ("Reserva técnica", pct(premissas["reserva_tecnica_pct"] * 100)),
        ))

    titulo = cliente or plano.get("municipio", "Proposta de fretamento")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOBGOV — Proposta · {esc(titulo)}</title>
<style>{_ativo("painel.css")}{CSS}</style>
</head>
<body>
<header class="topo"><div class="folha">
  <div class="marca"><span class="produto">MOBGOV</span>
    <span class="modulo">Proposta de transporte</span></div>
  <h1>{esc(titulo)}</h1>
  <p class="subtitulo">Dimensionamento, escala de motoristas e formação de
  preço — com a conta aberta e as premissas na mesa.</p>
  <div class="identificacao">
    <span>Demanda: <b>{numero(plano["demanda"]["alunos"])} {esc(passageiro)}</b></span>
    <span>Turnos: <b>{len(plano["demanda"]["turnos"])}</b></span>
    <span>Viagens/dia: <b>{numero(len(frota["viagens"]))}</b></span>
    <span>Emitida em: <b>{esc(datetime.now().strftime("%d/%m/%Y"))}</b></span>
  </div>
</div></header>

<div class="folha">
  <section><h2>O que está sendo proposto</h2>
    <div class="preco-grande">
      <div class="valor">{reais(p["mes"])}/mês</div>
      <div class="detalhe">{reais(p["ano"])} por ano ·
      {reais(p["por_passageiro_mes"])} por {esc(perfil.get("rotulo_passageiro", "passageiro"))}/mês ·
      {reais(p["por_km"], 2)}/km</div>
    </div>
    <div class="colunas">
      <div><table><caption>Frota necessária</caption>
        <thead><tr><th>Tipo</th><th class="num">Qtd</th></tr></thead>
        <tbody>{composicao}
        <tr><td><b>Total</b></td>
        <td class="num"><b>{frota["total_veiculos"]}</b></td></tr></tbody>
      </table></div>
      <div><table><caption>Equipe</caption>
        <tbody>
        <tr><td>Motoristas</td><td class="num">{numero(equipe.get("motoristas", 0))}</td></tr>
        <tr><td>Jornada média</td>
        <td class="num">{numero((equipe.get("jornada_media_min") or 0) / 60, 1)} h</td></tr>
        <tr><td>Escalas com dupla pegada</td>
        <td class="num">{numero(equipe.get("com_dupla_pegada", 0))}</td></tr>
        <tr><td>Escalas fora da regra</td>
        <td class="num">{numero(equipe.get("escalas_com_problema", 0))}</td></tr>
        </tbody></table></div>
    </div>
    <ul class="lista">
      <li>A frota sai da roteirização da demanda real, viagem a viagem — não
      de uma média por passageiro.</li>
      <li>O número de motoristas é calculado pela jornada (Lei 13.103 e as
      regras declaradas no fim desta proposta), e não pelo número de
      veículos: no fretamento com vários turnos, os dois números são
      diferentes, e é essa diferença que costuma faltar na conta.</li>
    </ul>
  </section>

  <section><h2>Como o preço foi formado</h2>
    <div class="grupos">{grupos}</div>
    {_tabela_custo(preco)}
    <ul class="lista">{"".join(f'<li>{esc(linha)}</li>' for linha in preco["memoria"])}</ul>
  </section>

  <section><h2>E se as condições mudarem</h2>
    <p class="chamada">Cada cenário abaixo foi recalculado do zero, com a
    mesma conta — não é interpolação sobre o preço base.</p>
    <table><thead><tr><th>Cenário</th><th class="num">Preço/mês</th>
    <th class="num">Diferença</th></tr></thead>
    <tbody>{linhas_cenario}</tbody></table>
  </section>

  {_bloco_diagnostico(diagnostico)}

  <section><h2>Premissas — para a contabilidade conferir</h2>
    <p class="chamada">Alíquota, encargo e indireto não são invenção do
    sistema: são parâmetros, e estão todos aqui. Se algum não bate com a
    realidade da empresa, o preço muda — e muda na mesma tela.</p>
    <table><tbody>{itens_premissas}</tbody></table>
    <p class="chamada" style="margin-top:14px">{esc(p["observacao_tributaria"])}</p>
  </section>

  <div class="so-impressao">
    <p style="font-size:11pt;margin-top:24px">Proposta gerada pelo MOBGOV em
    {esc(datetime.now().strftime("%d/%m/%Y %H:%M"))} a partir do plano
    {esc(plano.get("origem", {}).get("arquivo", "dimensionamento"))}.</p>
    <p style="font-size:11pt;margin-top:24px">_______________________________
    &nbsp;&nbsp;&nbsp; _______________________________</p>
  </div>

  <footer>
    <span>MOBGOV · dimensionamento, escala e formação de preço</span>
    <span>Todos os números desta proposta vêm do plano roteirizado e das
    premissas declaradas acima.</span>
  </footer>
</div>
</body>
</html>
"""


def _nome_do_tipo(plano: dict, tipo_id: str) -> str:
    tipos = plano["premissas"]["custos_por_tipo"]
    return tipos.get(tipo_id, {}).get("nome", tipo_id)


def gerar(plano: dict, preco: dict, cenarios: list, diagnostico: dict = None,
          cliente: str = None, saida: str = None) -> str:
    html = renderizar(plano, preco, cenarios, diagnostico, cliente)
    saida = saida or SAIDA_PADRAO
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(html)
    return saida
