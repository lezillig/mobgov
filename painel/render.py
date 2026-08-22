# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 2 · agent-painel
Renderiza o PAINEL DE ECONOMIA como uma página HTML autocontida.

Por que HTML gerado no servidor, e não uma SPA:
- abre num notebook de prefeitura sem internet (CSS, JS e gráficos embutidos,
  zero requisição externa);
- imprime em PDF pelo próprio navegador, com quebra de página tratada, o que
  já resolve a exigência de "exportável para prestação de contas";
- carrega instantaneamente em projetor 1024x768.

Uso:
    python -m painel.render                       # gera relatorios/painel-economia.html
    python -m painel.render --diesel 7.20 --dias 20
    python -m painel.render --saida /tmp/demo.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from .formato import esc, numero, pct, reais, reais_curto
    from . import economia as economia_mod
    from . import aprendizado as aprendizado_mod
    from . import graficos
except ImportError:  # execução direta: python painel/render.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from painel.formato import esc, numero, pct, reais, reais_curto
    from painel import economia as economia_mod
    from painel import aprendizado as aprendizado_mod
    from painel import graficos

DIR_PAINEL = os.path.dirname(os.path.abspath(__file__))
DIR_BASE = os.path.dirname(DIR_PAINEL)
SAIDA_PADRAO = os.path.join(DIR_BASE, "relatorios", "painel-economia.html")


def _ativo(nome: str) -> str:
    with open(os.path.join(DIR_PAINEL, "assets", nome), "r", encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ blocos ---
def _kpi(rotulo, valor, detalhe, destaque=False, piora=False):
    classe = "kpi" + (" destaque" if destaque and not piora else "") + (
        " piora" if piora else "")
    return (f'<div class="{classe}">'
            f'<div class="rotulo">{esc(rotulo)}</div>'
            f'<div class="valor">{esc(valor)}</div>'
            f'<div class="detalhe">{esc(detalhe)}</div></div>')


def _delta(valor: float, texto: str) -> str:
    """Sinal explícito: − quando economiza, + quando piora.

    Sem isso, um indicador que piora sairia como "−-49,1 t" na tela — e um
    painel que não sabe mostrar resultado ruim não serve para auditoria.
    """
    return ("−" if valor > 0 else "+") + texto


def bloco_kpis(p: dict) -> str:
    e, atual, otim = p["economia"], p["atual"], p["otimizada"]
    return '<div class="kpis">' + "".join([
        _kpi("Veículos a menos", _delta(e["veiculos"], str(abs(e["veiculos"]))),
             f'de {atual["total_veiculos"]} para {otim["total_veiculos"]} '
             f'({pct(abs(e["reducao_frota_pct"]))} de redução)',
             destaque=True, piora=e["veiculos"] < 0),
        _kpi("Economia por mês", reais_curto(e["custo_mes"]),
             f'{reais(atual["custo_mes"])} → {reais(otim["custo_mes"])} '
             f'({pct(e["reducao_custo_pct"])})',
             destaque=True, piora=e["custo_mes"] < 0),
        _kpi("Economia por ano", reais_curto(e["custo_ano"]),
             f'{reais(e["custo_mes"])} × 12 meses',
             piora=e["custo_ano"] < 0),
        _kpi("Quilômetros por dia",
             _delta(e["km_dia"], f'{numero(abs(e["km_dia"]))} km'),
             f'de {numero(atual["km_dia"])} para {numero(otim["km_dia"])} km/dia '
             f'({pct(e["reducao_km_pct"])})', piora=e["km_dia"] < 0),
        _kpi("Diesel por dia",
             _delta(e["litros_dia"], f'{numero(abs(e["litros_dia"]))} l'),
             f'{numero(abs(e["litros_ano"]))} litros por ano',
             piora=e["litros_dia"] < 0),
        _kpi("Emissões evitadas",
             _delta(e["tco2_ano"], f'{numero(abs(e["tco2_ano"]), 1)} t'),
             'toneladas de CO₂ por ano', piora=e["tco2_ano"] < 0),
    ]) + "</div>"


def _tabela_frota(frota: dict, classe_marcador: str) -> str:
    linhas = "".join(
        f'<tr><td>{esc(l["nome"])}</td>'
        f'<td class="num">{l["qtd"]}</td>'
        f'<td class="num">{numero(l["km_dia"])}</td>'
        f'<td class="num">{reais(l["custo_fixo_mes"])}</td>'
        f'<td class="num">{reais(l["custo_variavel_mes"])}</td>'
        f'<td class="num">{reais(l["custo_mes"])}</td></tr>'
        for l in frota["composicao"]
    )
    return (
        f'<div class="rolagem"><table>'
        f'<caption><span class="marcador {classe_marcador}">{esc(frota["rotulo"])}</span> '
        f'· {frota["total_veiculos"]} veículos · {numero(frota["assentos"])} assentos '
        f'· {numero(frota["km_dia"])} km/dia</caption>'
        f'<thead><tr><th>Tipo de veículo</th><th class="num">Qtd</th>'
        f'<th class="num">km/dia</th><th class="num">Custo fixo/mês</th>'
        f'<th class="num">Custo variável/mês</th><th class="num">Total/mês</th></tr></thead>'
        f'<tbody>{linhas}</tbody>'
        f'<tfoot><tr><td>Total</td><td class="num">{frota["total_veiculos"]}</td>'
        f'<td class="num">{numero(frota["km_dia"])}</td>'
        f'<td class="num">{reais(frota["custo_fixo_mes"])}</td>'
        f'<td class="num">{reais(frota["custo_variavel_mes"])}</td>'
        f'<td class="num">{reais(frota["custo_mes"])}</td></tr></tfoot>'
        f'</table></div>'
    )


def bloco_antes_depois(p: dict) -> str:
    return (
        '<section><h2>Antes e depois — custo mensal da operação</h2>'
        '<p class="chamada">O custo fixo é o que se paga por ter o veículo '
        '(motorista, depreciação, seguro); o variável é o que se paga por rodá-lo. '
        'A otimização mexe nos dois: tira veículo da conta e encurta o percurso.</p>'
        + graficos.barras_custo(p["atual"], p["otimizada"])
        + '<div style="margin-top:22px">'
        + _tabela_frota(p["atual"], "atual")
        + '</div><div style="margin-top:20px">'
        + _tabela_frota(p["otimizada"], "otim")
        + '</div></section>'
    )


def bloco_frota(p: dict) -> str:
    otim, atual, q = p["otimizada"], p["atual"], p["qualidade"]
    detalhe = " + ".join(f'{l["qtd"]} {l["nome"].lower()}' for l in otim["composicao"])
    return (
        '<section><h2>Dimensionamento da frota</h2>'
        f'<p class="chamada">Sua frota atual: <b>{atual["total_veiculos"]} veículos</b>. '
        f'Necessário para atender a mesma demanda: <b>{otim["total_veiculos"]} veículos</b> '
        f'({esc(detalhe)}). Cada veículo da frota necessária existe porque há uma viagem '
        f'que não cabe nos demais dentro do limite de '
        f'{p["premissas"]["tempo_max_trajeto_min"]} minutos por aluno.</p>'
        f'<p class="chamada">O ganho não vem de cortar aluno, vem de <b>multiviagem</b>: '
        f'cada veículo faz {numero(q["viagens_por_veiculo_turno"] or 0, 2)} viagens por '
        f'turno na proposta, contra {numero(q["viagens_por_veiculo_atual"] or 0, 1)} na '
        f'operação de hoje — sempre respeitando a jornada disponível antes do sinal e o '
        f'tempo de virada de {p["premissas"]["tempo_virada_min"]} minutos entre uma '
        f'viagem e a seguinte.</p>'
        + graficos.barras_frota(atual, otim)
        + '</section>'
    )


def _tabela_turnos(q: dict) -> str:
    linhas = "".join(
        f'<tr><td>{esc(t["turno"])}</td>'
        f'<td class="num">{numero(t["alunos"])}</td>'
        f'<td class="num">{t["viagens"]}</td>'
        f'<td class="num">{t["veiculos"]}</td>'
        f'<td class="num">{numero(t["viagens_por_veiculo"], 2)}</td>'
        f'<td class="num">{numero(t["lugares_ofertados"])}</td>'
        f'<td class="num">{numero(t["lugares_folga"])}</td>'
        f'<td class="num">{numero(t["jornada_media_min"], 1)} / '
        f'{t["jornada_max_min"]} min</td>'
        f'<td class="num">{t["jornada_limite_min"]} min</td></tr>'
        for t in q["por_turno"]
    )
    return (
        '<div class="rolagem"><table>'
        '<caption>Cada turno tem que fechar sozinho — a frota é a mesma nos dois</caption>'
        '<thead><tr><th>Turno</th><th class="num">Alunos</th>'
        '<th class="num">Viagens</th><th class="num">Veículos</th>'
        '<th class="num">Viagens por veículo</th>'
        '<th class="num">Lugares ofertados</th><th class="num">Folga</th>'
        '<th class="num">Jornada média / máx</th>'
        '<th class="num">Limite</th></tr></thead>'
        f'<tbody>{linhas}</tbody></table></div>'
    )


def bloco_qualidade(p: dict, viagens: list) -> str:
    q = p["qualidade"]
    d = p["demanda"]
    atende = ("todas as viagens com cadeirante em veículo acessível"
              if q["atende_cadeirantes"]
              else "ATENÇÃO: há viagem com cadeirante sem veículo acessível")
    return (
        '<section><h2>A frota menor continua atendendo todo mundo</h2>'
        f'<p class="chamada">Cortar veículo só vale se o serviço não piorar. '
        f'As {q["viagens"]} viagens propostas transportam os '
        f'{numero(d["alunos"])} alunos em {numero(d["pontos_embarque"])} pontos de '
        f'embarque, com folga de lugares nos dois turnos e nenhuma viagem acima do '
        f'limite de {p["premissas"]["tempo_max_trajeto_min"]} minutos por aluno.</p>'
        + graficos.barras_ocupacao(viagens)
        + '<ul class="lista">'
        f'<li>Ocupação média de {pct(q["ocupacao_media_pct"])} '
        f'(menor viagem {q["ocupacao_min_pct"]}%, maior {q["ocupacao_max_pct"]}%) — '
        f'sem veículo rodando vazio nem aluno em pé.</li>'
        f'<li>Tempo dentro do veículo: {numero(q["tempo_medio_viagem_min"], 1)} min em '
        f'média, máximo de {q["tempo_max_viagem_min"]} min — o limite da secretaria '
        f'é {p["premissas"]["tempo_max_trajeto_min"]} min.</li>'
        f'<li>Alunos cadeirantes: {d["cadeirantes"]} · posições em veículo acessível na '
        f'frota proposta: {q["posicoes_cadeirante"]} — {esc(atende)}.</li>'
        '</ul>'
        '<div style="margin-top:20px">' + _tabela_turnos(q) + '</div>'
        '</section>'
    )


def bloco_importacao(imp: dict) -> str:
    """Qualidade dos dados que entraram — o primeiro passo da demonstração."""
    if not imp or not imp.get("resumo"):
        return ""
    r = imp["resumo"]
    problemas = imp.get("problemas") or []

    # agrupa por tipo: a secretaria quer saber "o que" está errado, não ler
    # 39 linhas repetindo a mesma coisa
    tipos = {}
    for p_ in problemas:
        chave = (p_["problema"], p_["gravidade"], p_["sugestao"])
        tipos.setdefault(chave, []).append(p_["linha"])
    linhas = "".join(
        f'<tr><td><span class="marcador '
        f'{"atual" if grav == "erro" else "otim"}">{esc(grav)}</span></td>'
        f'<td>{esc(problema)}</td>'
        f'<td class="num">{len(linhas_afetadas)}</td>'
        f'<td>{esc(", ".join(str(l) for l in linhas_afetadas[:6]))}'
        f'{"…" if len(linhas_afetadas) > 6 else ""}</td>'
        f'<td>{esc(sugestao)}</td></tr>'
        for (problema, grav, sugestao), linhas_afetadas
        in sorted(tipos.items(), key=lambda kv: -len(kv[1])))

    return (
        '<section><h2>Importação da planilha da secretaria</h2>'
        f'<p class="chamada">A planilha veio como planilha de prefeitura vem: '
        f'com título antes do cabeçalho, turno escrito de seis jeitos, aluno '
        f'repetido e endereço rural sem coordenada. O sistema importou '
        f'<b>{numero(r["alunos_importados"])} alunos</b> e apontou linha a '
        f'linha o que não deu para resolver sozinho — em vez de recusar o '
        f'arquivo.</p>'
        '<div class="kpis">'
        + _kpi("Alunos importados", numero(r["alunos_importados"]),
               f'de {esc(imp.get("arquivo", "planilha"))}')
        + _kpi("Precisam de ajuste no mapa",
               numero(r["precisam_ajuste_no_mapa"]),
               'endereço sem coordenada — usei o ponto do bairro')
        + _kpi("Erros apontados", numero(r["erros"]),
               'linhas que exigem decisão humana',
               piora=r["erros"] > 0)
        + _kpi("Avisos", numero(r["avisos"]),
               'resolvidos automaticamente, mas registrados')
        + '</div>'
        '<div class="rolagem" style="margin-top:18px"><table>'
        '<caption>O que o importador encontrou, agrupado por tipo</caption>'
        '<thead><tr><th>Gravidade</th><th>Problema</th>'
        '<th class="num">Linhas</th><th>Onde</th><th>O que fazer</th></tr></thead>'
        f'<tbody>{linhas}</tbody></table></div>'
        '<ul class="lista">'
        f'<li>Colunas reconhecidas automaticamente: '
        f'{esc(", ".join(sorted(r.get("colunas_detectadas", {}))))}.</li>'
        '<li>O nome do aluno <b>não entra</b> no dado de roteirização: cada '
        'aluno vira um pseudônimo estável. A lista nominal só é gravada se o '
        'município pedir, em arquivo separado.</li>'
        '</ul></section>'
    )


def bloco_elegibilidade(el: dict) -> str:
    """Elegibilidade ao porta a porta — a fila que costuma levar meses."""
    if not el or not el.get("resumo"):
        return ""
    r = el["resumo"]
    classe_selo = "selo" if el.get("origem") != "operacao_real" else "selo medido"

    estados = "".join(
        f'<tr><td>{esc(rotulo)}</td>'
        f'<td class="num">{numero(r["por_estado"].get(chave, 0))}</td></tr>'
        for chave, rotulo in (
            ("recebido", "Recebido, aguardando análise"),
            ("em_analise", "Em análise"),
            ("pendente_de_informacao", "Esperando informação da família"),
            ("aprovado", "Aprovado"),
            ("negado", "Negado"),
        ))
    fontes = "".join(
        f'<tr><td>{esc(f["rotulo"])}</td>'
        f'<td class="num">{numero(f["decisoes"])}</td></tr>'
        for f in el.get("fontes", []))
    aviso = ""
    if el.get("origem") != "operacao_real":
        aviso = ('<div class="aviso"><b>Leia com atenção:</b> esta fila é '
                 'simulada para a demonstração. O fluxo é o real — formulário, '
                 'leitura assistida do documento, decisão com nome do analista '
                 'e registro que não se apaga —, mas nenhuma pessoa aqui '
                 'existe.</div>')

    return (
        '<section><h2>Elegibilidade ao porta a porta '
        f'<span class="{classe_selo}">{esc(el.get("selo", ""))}</span></h2>'
        '<p class="chamada">Hoje a família consegue um laudo, tira cópia, vai '
        'até a secretaria, protocola e espera sem informação — e no ano '
        'seguinte repete tudo, mesmo quando a condição é permanente. Aqui ela '
        'responde ao formulário pelo celular, anexa o que já tiver e acompanha '
        'o protocolo. A análise continua humana: o que some é o papel e a '
        'espera no escuro.</p>'
        '<div class="kpis">'
        + _kpi("Pedidos na fila", numero(r["pedidos"]),
               f'{numero(r["em_aberto"])} em aberto')
        + _kpi("Dias em aberto (média)", numero(r["dias_em_aberto_media"], 1),
               f'prazo assumido: {r["prazo_dias"]} dias')
        + _kpi("Fora do prazo", numero(r["atrasados"]),
               'aparecem no topo da fila do analista',
               piora=r["atrasados"] > 0)
        + _kpi("Decisões com analista identificado",
               pct(el.get("decisoes_com_analista_pct", 0)),
               'aprovar sem nome é impossível no sistema', destaque=True)
        + '</div>'
        '<div class="colunas" style="margin-top:18px">'
        '<div><table><caption>Situação dos pedidos</caption>'
        '<thead><tr><th>Estado</th><th class="num">Pedidos</th></tr></thead>'
        f'<tbody>{estados}</tbody></table></div>'
        '<div><table><caption>Em que a decisão se baseou</caption>'
        '<thead><tr><th>Fonte</th><th class="num">Decisões</th></tr></thead>'
        f'<tbody>{fontes}</tbody></table></div>'
        '</div>'
        '<ul class="lista">'
        f'<li><b>{pct(el.get("aprovacoes_sem_laudo_pct", 0))} das aprovações '
        f'não exigiram laudo em papel</b>: o município usou o cadastro que já '
        f'tinha, a declaração da escola ou a avaliação presencial.</li>'
        f'<li>{numero(r.get("permanentes", 0))} concessão(ões) marcada(s) como '
        f'permanente — essas famílias não voltam para a fila todo ano.</li>'
        f'<li>{numero(r.get("a_vencer_30_dias", 0))} concessão(ões) vencendo '
        f'nos próximos 30 dias: o sistema avisa antes, e não depois de o '
        f'veículo deixar de encostar na porta.</li>'
        f'<li>{numero(el.get("usuarios_para_roteirizacao", 0))} usuários '
        f'aprovados alimentam a roteirização porta a porta — só com restrição '
        f'operacional: nome, endereço e diagnóstico ficam no processo, nunca '
        f'no dado de rota.</li>'
        '</ul>'
        + aviso
        + '</section>'
    )


def bloco_mapa(p: dict) -> str:
    """Mapa das rotas — desenhado em SVG, sem tiles e sem internet."""
    geografia = p.get("geografia") or {}
    viagens = p.get("viagens_mapa") or []
    pcd = (p.get("porta_a_porta") or {}).get("rotas") or []
    escolar = graficos.mapa_rotas(geografia, viagens, turno_id="manha")
    porta = graficos.mapa_porta_a_porta(pcd)
    if not escolar and not porta:
        return ""
    partes = ['<section><h2>Mapa das rotas</h2>'
              '<p class="chamada">O desenho sai do mesmo relatório que gera os '
              'números — não é ilustração. Cada linha é uma viagem; a cor diz a '
              'escola de destino. O traçado é reto entre paradas porque o sistema '
              'ainda calcula sobre distância geográfica; com o servidor de malha '
              'viária (OSRM) ligado, aparece a rua de verdade.</p>']
    if escolar:
        partes.append('<h3 class="sub">Escolar · turno da manhã</h3>' + escolar)
    if porta:
        partes.append('<h3 class="sub">Porta a porta · primeiras rotas do dia</h3>'
                      + porta)
    partes.append('</section>')
    return "".join(partes)


def bloco_porta_a_porta(pcd: dict) -> str:
    """Vertical PCD: a rota que encosta na porta, com n embarques e n desembarques."""
    if not pcd or not pcd.get("rotas"):
        return ""
    ind = pcd.get("indicadores", {})
    pr = pcd.get("premissas", {})
    # a rota com mais eventos é a que melhor mostra o n:n
    rota = max(pcd["rotas"], key=lambda r: len(r.get("eventos", [])))
    cadeirantes = sum(r.get("cadeirantes", 0) for r in pcd["rotas"])

    return (
        '<section><h2>Transporte porta a porta (PCD)</h2>'
        f'<p class="chamada">O escolar leva todo mundo ao mesmo destino; o porta '
        f'a porta não. Cada usuário tem origem e destino próprios, e a mesma rota '
        f'intercala <b>n embarques e n desembarques</b> — sem que ninguém passe do '
        f'tempo máximo a bordo. São {numero(pcd["pedidos"])} viagens do dia '
        f'atendidas por {pcd["total_veiculos"]} veículos, '
        f'{numero(ind.get("usuarios_por_veiculo", 0), 2)} usuários por veículo.</p>'
        '<div class="kpis">'
        + _kpi("Viagens no dia", numero(pcd["pedidos"]),
               f'{cadeirantes} em cadeira de rodas')
        + _kpi("Veículos", str(pcd["total_veiculos"]),
               f'{numero(pcd["km_dia"])} km/dia · '
               f'{numero(ind.get("km_por_usuario", 0), 2)} km por usuário')
        + _kpi("Tempo a bordo", f'{numero(ind.get("tempo_bordo_medio_min", 0), 1)} min',
               f'máximo de {ind.get("tempo_bordo_max_min", 0)} min')
        + _kpi("Dentro do limite", pct(ind.get("dentro_do_limite_pct", 0)),
               f'limite = tempo direto × {pr.get("fator_tempo_bordo", "—")} + '
               f'{pr.get("folga_tempo_bordo_min", "—")} min',
               piora=ind.get("dentro_do_limite_pct", 100) < 100)
        + '</div>'
        + graficos.linha_do_tempo_rota(rota)
        + f'<p class="chamada" style="margin-top:6px">Rota {esc(rota["id"])}: '
        f'{rota["usuarios"]} usuários, {numero(rota["km"])} km, das '
        f'{esc(rota["inicio"])} às {esc(rota["fim"])} — o veículo chega a levar '
        f'{rota["ocupacao_maxima"]} pessoas ao mesmo tempo e volta a esvaziar '
        f'antes de encher de novo.</p>'
        '<ul class="lista">'
        f'<li>Janela de chegada de {pr.get("janela_embarque_min", "—")} minutos por '
        f'usuário — o padrão do <i>dial-a-ride</i>: se a consulta é 9h, o veículo '
        f'chega entre 8h40 e 9h.</li>'
        f'<li>Quem embarca com um veículo desembarca com o mesmo, e o embarque vem '
        f'antes do desembarque — restrição do próprio modelo, não confere manual.</li>'
        f'<li>Posição de cadeira de rodas conta separado do assento; acompanhante '
        f'ocupa assento.</li>'
        '</ul></section>'
    )


def _lista_diff(itens: list) -> str:
    return "".join(f'<li>{esc(x)}</li>' for x in itens)


def bloco_reotimizacao(evt: dict) -> str:
    """O dia depois do plano: faltas, cancelamentos e pedidos novos."""
    if not evt or not evt.get("resumo"):
        return ""
    r = evt["resumo"]
    cartoes = []
    for e in evt.get("escolar", [])[:2]:
        cartoes.append(
            f'<div class="card-evento"><div class="rotulo">Falta informada · '
            f'viagem {esc(e["viagem"])}</div>'
            f'<div class="tempo">respondido em {numero(e["segundos"], 3)} s</div>'
            f'<ul class="lista">{_lista_diff(e["diff"])}</ul></div>')
    for e in evt.get("porta_a_porta", [])[:2]:
        cartoes.append(
            f'<div class="card-evento"><div class="rotulo">Cancelamento porta a '
            f'porta · {esc(e["cancelado"])}</div>'
            f'<div class="tempo">respondido em {numero(e["segundos"], 3)} s</div>'
            f'<ul class="lista">{_lista_diff(e["diff"])}</ul></div>')
    for e in evt.get("pedidos_novos", [])[:3]:
        estado = "aceito" if e.get("aceito") else "recusado"
        cartoes.append(
            f'<div class="card-evento"><div class="rotulo">Pedido novo · '
            f'{esc(e["usuario"])} ({estado})</div>'
            f'<div class="tempo">decidido em {numero(e["segundos"], 3)} s</div>'
            f'<ul class="lista">{_lista_diff(e["diff"])}</ul></div>')

    return (
        '<section><h2>O dia depois do plano — reotimização</h2>'
        '<p class="chamada">Planejar à noite é metade do trabalho. O que separa um '
        'sistema de uma planilha é o que acontece quando o responsável avisa que o '
        'aluno não vai, quando o usuário cancela a consulta e quando chega pedido '
        'novo às 8h da manhã. Cada evento abaixo foi processado agora, com o tempo '
        'de resposta medido.</p>'
        '<div class="kpis">'
        + _kpi("Eventos processados", str(r["eventos"]),
               f'tempo médio de {numero(r["tempo_medio_s"], 3)} s')
        + _kpi("Resposta mais lenta", f'{numero(r["tempo_max_s"], 3)} s',
               'a meta do MVP é reagir em menos de 30 s', destaque=True)
        + _kpi("Quilômetros poupados", f'−{numero(r["km_economizados"], 1)} km',
               'só com os eventos deste lote')
        + _kpi("Pedidos novos aceitos",
               f'{r["pedidos_aceitos"]}/{r["pedidos_avaliados"]}',
               'encaixados em rota existente, sem veículo extra')
        + '</div>'
        f'<div class="eventos">{"".join(cartoes)}</div>'
        '</section>'
    )


def bloco_transito(pcd: dict) -> str:
    """Como o trânsito entrou na conta — e de onde vieram os fatores."""
    pr = (pcd or {}).get("premissas", {})
    perfil = pr.get("perfil_transito") or []
    if not perfil:
        return ""
    origem = pr.get("transito_origem")
    medido = origem == "gps_real"
    if medido:
        selo = '<span class="selo medido">MEDIDO COM GPS</span>'
    elif origem == "simulacao":
        selo = '<span class="selo">APRENDIDO EM SIMULAÇÃO</span>'
    else:
        selo = '<span class="selo">FATORES ESTIMADOS</span>' 
    linhas = "".join(
        f'<tr><td>{esc(f["faixa"])}</td><td>{esc(f["inicio"])} — {esc(f["fim"])}</td>'
        f'<td class="num">{numero(f["fator_urbano"], 2)}×</td>'
        f'<td class="num">{numero(f["fator_rural"], 2)}×</td></tr>'
        for f in perfil)
    return (
        f'<section><h2>Trânsito considerado {selo}</h2>'
        '<p class="chamada">A mesma rota não leva o mesmo tempo às 6h40 e às 14h. '
        'O tempo de cada trecho é multiplicado pelo fator da faixa horária e da '
        'zona, e é por isso que o turno da manhã precisa de mais veículo que o da '
        'tarde para a mesma quantidade de aluno.</p>'
        '<div class="rolagem"><table>'
        '<thead><tr><th>Faixa</th><th>Horário</th>'
        '<th class="num">Fator urbano</th><th class="num">Fator rural</th></tr></thead>'
        f'<tbody>{linhas}</tbody></table></div>'
        + ('' if medido else
           ('<div class="aviso"><b>Aprendido em simulação:</b> estes fatores não '
            'são mais o chute inicial — saíram do ciclo de aprendizado rodando '
            'sobre uma operação simulada, e já corrigiram o planejamento. Com o '
            'app do motorista na rua, a mesma rotina roda sobre os pings reais e '
            'o selo vira "medido com GPS".</div>') if origem == "simulacao" else
           ('<div class="aviso"><b>Fatores estimados:</b> são premissas de projeto '
            'enquanto não houver dados de operação. Trocar por malha viária real '
            'com trânsito (OSRM, Mapbox ou Google Routes) é implementar uma '
            'função — o motor de rotas não muda.</div>'))
        + '</section>'
    )


def bloco_cenarios(p: dict) -> str:
    cenarios = p.get("cenarios") or []
    base = next((c for c in cenarios if c["padrao"]), None) or {}
    # "</" escapado para o JSON nunca fechar a tag <script> antes da hora
    dados = json.dumps(cenarios, ensure_ascii=False).replace("</", "<\\/")
    return (
        '<section><h2>E se o diesel subir? — simulador de cenários</h2>'
        '<p class="chamada">Os cenários abaixo já foram calculados pelo motor de '
        'dimensionamento com as mesmas fórmulas do relatório. Os controles apenas '
        'escolhem qual deles mostrar: nenhum número é estimado na tela.</p>'
        '<div class="controles" hidden>'
        '<div class="controle"><label for="controle-diesel">Preço do diesel</label>'
        '<input type="range" id="controle-diesel" min="0" max="1" step="1">'
        f'<div class="leitura" id="leitura-diesel">'
        f'{esc(reais(p["premissas"]["preco_diesel_l"], 2))}/l</div></div>'
        '<div class="controle"><label for="controle-dias">Dias letivos no mês</label>'
        '<input type="range" id="controle-dias" min="0" max="1" step="1">'
        f'<div class="leitura" id="leitura-dias">'
        f'{p["premissas"]["dias_letivos_mes"]} dias letivos/mês</div></div>'
        '</div>'
        '<div class="resultado-cenario">'
        '<div><div class="rotulo">Economia por mês</div>'
        f'<div class="valor" id="cen-economia-mes">{esc(reais(base.get("economia_mes", 0)))}</div></div>'
        '<div><div class="rotulo">Economia por ano</div>'
        f'<div class="valor" id="cen-economia-ano">{esc(reais(base.get("economia_ano", 0)))}</div></div>'
        '<div><div class="rotulo">Custo da frota atual</div>'
        f'<div class="valor" id="cen-custo-atual">{esc(reais(base.get("custo_atual_mes", 0)))}</div></div>'
        '<div><div class="rotulo">Custo da frota necessária</div>'
        f'<div class="valor" id="cen-custo-otim">{esc(reais(base.get("custo_otimizado_mes", 0)))}</div></div>'
        '<div><div class="rotulo">Redução de custo</div>'
        f'<div class="valor" id="cen-reducao">{esc(pct(base.get("reducao_custo_pct", 0)))}</div></div>'
        '</div>'
        '<p class="chamada" style="margin:14px 0 0" id="cen-situacao">'
        'Cenário base do relatório.</p>'
        '<p class="sem-js">Simulação interativa indisponível sem JavaScript — '
        'os valores acima são os do cenário base do relatório.</p>'
        f'<script type="application/json" id="dados-cenarios">{dados}</script>'
        '</section>'
    )


def bloco_aprendizado(serie: dict) -> str:
    exemplos = "".join(f'<li>{esc(x)}</li>' for x in serie.get("exemplos", []))
    classe_selo = "selo" if serie["e_demonstracao"] else "selo medido"
    if serie.get("semanas"):
        resumo = (
            f'<p class="chamada">Erro médio do tempo estimado caiu de '
            f'{numero(serie["erro_inicial_min"], 1)} min para '
            f'{numero(serie["erro_atual_min"], 1)} min em '
            f'{len(serie["semanas"])} semanas ({pct(serie["queda_erro_pct"])} de queda), '
            f'com {numero(serie["viagens_observadas"])} viagens observadas. '
            f'A previsão de ausência de alunos ganhou '
            f'{numero(serie["ganho_ausencia_pp"], 1)} pontos percentuais de acurácia.</p>')
    else:
        resumo = '<p class="chamada">Série ainda sem semanas registradas.</p>'
    if serie.get("e_simulacao"):
        aviso = ('<div class="aviso"><b>Leia com atenção:</b> o ciclo de '
                 'aprendizado rodou de verdade — coleta, estimativa, validação '
                 'em conjunto separado, versão e rollback —, mas sobre uma '
                 'operação SIMULADA. Os pings reais entram quando o app do '
                 'motorista for ao ar; os números de economia das seções '
                 'anteriores não dependem desta série.</div>')
    elif serie["e_demonstracao"]:
        aviso = ('<div class="aviso"><b>Leia com atenção:</b> esta série é '
                 'ilustrativa, escrita à mão para a apresentação.</div>')
    else:
        aviso = ""
    versoes = ""
    if serie.get("versao_modelo"):
        versoes = (
            f'<ul class="lista"><li>Modelo na versão '
            f'{serie["versao_modelo"]} depois de {len(serie.get("semanas", []))} '
            f'semanas: cada versão só entra se o erro cair no conjunto de '
            f'validação.</li>'
            f'<li>{serie.get("rollbacks", 0)} rollback(s): o sistema recusou '
            f'trocar o modelo quando a versão nova pioraria a previsão. '
            f'Aprender também é saber não mexer.</li></ul>')
    return (
        '<section><h2>O que o sistema aprendeu '
        f'<span class="{classe_selo}">{esc(serie["selo"])}</span></h2>'
        + resumo
        + graficos.linha_erro(serie.get("semanas", []))
        + (f'<ul class="lista">{exemplos}</ul>' if exemplos else "")
        + versoes
        + aviso
        + '</section>'
    )


def bloco_premissas(p: dict) -> str:
    pr = p["premissas"]
    jornadas = " · ".join(
        f'{t["nome"]}: {t["jornada_max_min"]} min' for t in p["demanda"]["turnos"])

    o = p.get("atual_origem")
    if o:
        origem_frota_atual = esc(
            f'A frota atual deste município fictício não é um número escolhido a dedo: '
            f'sai de ocupação média de {round(o["ocupacao_media"] * 100)}%, '
            f'{numero(o["viagens_por_veiculo_turno"], 1)} viagens por veículo/turno e '
            f'rotas {round((o["fator_km_roteiro"] - 1) * 100)}% mais longas que as '
            f'otimizadas, aplicados ao turno mais cheio '
            f'({numero(o["turno_critico_alunos"])} alunos). '
            f'Num município real, este dado vem do cadastro da secretaria.')
    else:
        origem_frota_atual = esc(
            'A frota atual foi informada pela secretaria e usada como está.')
    passos = "".join(
        f'<tr><td>{esc(m["passo"])}</td><td>{esc(m["formula"])}</td>'
        f'<td>{esc(m["valores"])}</td></tr>'
        for m in p["memoria_calculo"]
    )
    return (
        '<section><h2>Premissas e memória de cálculo</h2>'
        '<p class="chamada">Tudo o que entra na conta está aqui. Trocar qualquer '
        'premissa muda o resultado — e é para isso que ela está declarada.</p>'
        '<div class="colunas">'
        '<div><div class="rolagem"><table><caption>Premissas adotadas</caption>'
        '<tbody>'
        f'<tr><td>Preço do diesel</td><td class="num">{esc(reais(pr["preco_diesel_l"], 2))}/litro</td></tr>'
        f'<tr><td>Dias letivos no mês</td><td class="num">{pr["dias_letivos_mes"]}</td></tr>'
        f'<tr><td>Viagens por rota (coleta e dispersão)</td><td class="num">{pr["viagens_por_rota"]}</td></tr>'
        f'<tr><td>Tempo máximo do aluno no veículo</td><td class="num">{pr["tempo_max_trajeto_min"]} min</td></tr>'
        f'<tr><td>Virada entre duas viagens do mesmo veículo</td><td class="num">{pr["tempo_virada_min"]} min</td></tr>'
        f'<tr><td>Jornada disponível por turno</td><td class="num">{jornadas}</td></tr>'
        f'<tr><td>Fator de emissão do diesel</td><td class="num">{numero(pr["fator_co2_kg_l"], 2)} kg CO₂/litro</td></tr>'
        f'<tr><td>Origem dos tempos de percurso</td><td>{esc(pr["fonte_tempos"])}</td></tr>'
        '</tbody></table></div></div>'
        '<div><div class="rolagem"><table><caption>Limitações declaradas desta versão</caption>'
        '<tbody>'
        '<tr><td>Demanda usada é sintética (município fictício gerado para a demonstração); '
        'com a planilha real da prefeitura os números mudam.</td></tr>'
        f'<tr><td>{origem_frota_atual}</td></tr>'
        '<tr><td>As viagens de um turno são encaixadas nos veículos por heurística '
        '(a mais longa primeiro, no veículo com menos folga), não por otimização exata: '
        'a escala é sempre válida, mas pode existir arranjo um pouco melhor.</td></tr>'
        '<tr><td>A frota necessária toma o maior número de veículos de cada tipo entre os '
        'turnos. É o lado seguro — garante cobrir manhã e tarde, e pode sobrar veículo de '
        'um tipo em um dos turnos.</td></tr>'
        '<tr><td>Tempos de percurso vêm de distância em linha reta com fator de sinuosidade '
        'rural mais o tempo de embarque por parada, ainda não de malha viária real nem de '
        'GPS.</td></tr>'
        '<tr><td>Custo por km da frota atual é rateado pelo número de veículos, porque a '
        'prefeitura declara apenas o km/dia total.</td></tr>'
        '<tr><td>A dispersão no fim do turno é considerada espelhada da coleta (mesmo '
        'percurso, sentido inverso), e não roteirizada separadamente.</td></tr>'
        '</tbody></table></div></div>'
        '</div>'
        '<div class="rolagem" style="margin-top:22px"><table>'
        '<caption>Memória de cálculo — passo a passo</caption>'
        '<thead><tr><th>Passo</th><th>Fórmula</th><th>Valores</th></tr></thead>'
        f'<tbody>{passos}</tbody></table></div>'
        '</section>'
    )


# ------------------------------------------------------------------ página ---
def renderizar(p: dict, serie: dict, viagens: list, origem: str) -> str:
    css, js = _ativo("painel.css"), _ativo("painel.js")
    d = p["demanda"]
    titulo = f'Painel de Economia · {p["municipio"]}'
    turnos = " · ".join(
        f'{t["nome"]} {numero(d["alunos_por_turno"][t["id"]])}'
        for t in d["turnos"])
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOBGOV — {esc(titulo)}</title>
<meta name="description" content="Relatório antes e depois do dimensionamento de frota do transporte escolar, com premissas auditáveis.">
<style>{css}</style>
</head>
<body>
<header class="topo"><div class="folha">
  <div class="marca"><span class="produto">MOBGOV</span>
    <span class="modulo">Painel de economia · transporte escolar</span></div>
  <h1>Dimensionamento de frota: {esc(p["municipio"])}</h1>
  <p class="subtitulo">Quantos veículos a rede realmente precisa para transportar
  a mesma demanda, quanto isso economiza por mês e por quê — com todas as
  premissas abertas para auditoria.</p>
  <div class="identificacao">
    <span>Demanda atendida: <b>{numero(d["alunos"])} alunos/dia</b></span>
    <span>Por turno: <b>{esc(turnos)}</b></span>
    <span>Pontos de embarque: <b>{numero(d["pontos_embarque"])}</b></span>
    <span>Escolas: <b>{d["escolas"]}</b></span>
    <span>Relatório gerado em: <b>{esc(p["gerado_em"])}</b></span>
  </div>
</div></header>

<div class="folha">
  <div class="acoes">
    <button class="acao" id="botao-pdf" hidden>Salvar em PDF / imprimir</button>
  </div>

  {bloco_kpis(p)}
  {bloco_antes_depois(p)}
  {bloco_frota(p)}
  {bloco_qualidade(p, viagens)}
  {bloco_importacao(p.get("importacao"))}
  {bloco_elegibilidade(p.get("elegibilidade"))}
  {bloco_mapa(p)}
  {bloco_porta_a_porta(p.get("porta_a_porta"))}
  {bloco_reotimizacao(p.get("reotimizacao"))}
  {bloco_transito(p.get("porta_a_porta"))}
  {bloco_cenarios(p)}
  {bloco_aprendizado(serie)}
  {bloco_premissas(p)}

  <div class="so-impressao">
    <p style="font-size:11pt;margin-top:10px">Documento gerado automaticamente pelo
    MOBGOV a partir do arquivo <b>{esc(origem)}</b> em {esc(p["gerado_em"])}.
    Os valores podem ser reproduzidos executando novamente o motor de
    dimensionamento com as mesmas premissas.</p>
    <p style="font-size:11pt;margin-top:24px">Responsável pela conferência:
    ______________________________________  Data: ____/____/______</p>
  </div>

  <footer>
    <span>MOBGOV · plataforma de roteirização e dimensionamento de frota para
    governos — módulo de transporte escolar</span>
    <span>Fonte dos dados: {esc(origem)}</span>
  </footer>
</div>
<script>{js}</script>
</body>
</html>
"""


def montar_html(caminho_relatorio: str = economia_mod.RELATORIO_PADRAO,
                diesel: float = None, dias: int = None,
                caminho_serie: str = None):
    """Devolve (html, painel) — usado pelo gerador de arquivo e pelo servidor."""
    rel = economia_mod.carregar_relatorio(caminho_relatorio)
    rel.setdefault("porta_a_porta",
                   economia_mod.carregar_opcional(economia_mod.RELATORIO_PCD))
    rel.setdefault("reotimizacao",
                   economia_mod.carregar_opcional(
                       economia_mod.RELATORIO_REOTIMIZACAO))
    rel.setdefault("importacao",
                   economia_mod.carregar_opcional(
                       economia_mod.RELATORIO_IMPORTACAO))
    rel.setdefault("elegibilidade",
                   economia_mod.carregar_opcional(
                       economia_mod.RELATORIO_ELEGIBILIDADE))
    premissas = economia_mod.premissas_do_relatorio(rel).substituir(
        preco_diesel_l=diesel, dias_letivos_mes=dias)
    p = economia_mod.montar_painel(rel, premissas)
    serie = aprendizado_mod.carregar_serie(
        caminho_serie or aprendizado_mod.SERIE_PADRAO)
    html = renderizar(p, serie, rel["frota_otimizada"]["viagens"],
                      os.path.basename(caminho_relatorio))
    return html, p


def gerar(caminho_relatorio: str = economia_mod.RELATORIO_PADRAO,
          saida: str = SAIDA_PADRAO, diesel: float = None,
          dias: int = None, caminho_serie: str = None) -> str:
    html, _ = montar_html(caminho_relatorio, diesel, dias, caminho_serie)
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(html)
    return saida


def main():
    ap = argparse.ArgumentParser(description="Gera o painel de economia do MOBGOV")
    ap.add_argument("--relatorio", default=economia_mod.RELATORIO_PADRAO,
                    help="JSON produzido por motor/dimensionar.py")
    ap.add_argument("--saida", default=SAIDA_PADRAO, help="arquivo HTML de saída")
    ap.add_argument("--diesel", type=float, default=None,
                    help="preço do diesel por litro (padrão: o do relatório)")
    ap.add_argument("--dias", type=int, default=None,
                    help="dias letivos no mês (padrão: o do relatório)")
    ap.add_argument("--aprendizado", default=None,
                    help="JSON da série de aprendizado (padrão: relatorios/aprendizado.json)")
    a = ap.parse_args()
    html, p = montar_html(a.relatorio, a.diesel, a.dias, a.aprendizado)
    os.makedirs(os.path.dirname(os.path.abspath(a.saida)), exist_ok=True)
    with open(a.saida, "w", encoding="utf-8") as f:
        f.write(html)
    e = p["economia"]
    print(f"Painel gerado: {a.saida}")
    print(f"  {p['atual']['total_veiculos']} → {p['otimizada']['total_veiculos']} veículos "
          f"({pct(e['reducao_frota_pct'])}) · {reais(e['custo_mes'])}/mês · "
          f"{reais(e['custo_ano'])}/ano")


if __name__ == "__main__":
    main()
