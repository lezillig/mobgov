# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 2 · agent-painel
Gráficos em SVG gerados no servidor.

Sem biblioteca de gráficos e sem CDN: a página precisa abrir num notebook de
prefeitura, sem internet, e imprimir em PDF com os gráficos intactos. As cores
vêm de classes CSS (ver assets/painel.css) para que o modo de impressão e o
modo de projetor usem a mesma marcação.
"""
from __future__ import annotations

import math

from .formato import esc, numero, reais_curto


def _texto(x, y, txt, classe="g-rotulo", ancora="middle", dy=0):
    return (f'<text x="{x:.1f}" y="{y + dy:.1f}" class="{classe}" '
            f'text-anchor="{ancora}">{esc(txt)}</text>')


def _svg(largura, altura, corpo, titulo, descricao=""):
    return (
        f'<svg viewBox="0 0 {largura} {altura}" class="grafico" '
        f'role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{esc(titulo)}">'
        f'<title>{esc(titulo)}</title>'
        + (f'<desc>{esc(descricao)}</desc>' if descricao else "")
        + corpo + '</svg>'
    )


# ------------------------------------------------- custo mensal comparativo ---
def barras_custo(atual: dict, otimizada: dict) -> str:
    """Duas colunas empilhadas (custo fixo + custo variável), atual vs necessária."""
    L, A = 720, 380
    base, topo = A - 62, 40
    altura_util = base - topo
    maior = max(atual["custo_mes"], otimizada["custo_mes"]) or 1

    corpo = [f'<line x1="60" y1="{base}" x2="{L - 30}" y2="{base}" class="g-eixo"/>']
    colunas = [
        (200, atual, "g-atual"),
        (460, otimizada, "g-otim"),
    ]
    for cx, frota, classe in colunas:
        larg = 150
        x = cx - larg / 2
        h_fixo = altura_util * frota["custo_fixo_mes"] / maior
        h_var = altura_util * frota["custo_variavel_mes"] / maior
        y_var = base - h_var
        y_fixo = y_var - h_fixo
        corpo.append(
            f'<rect x="{x:.1f}" y="{y_fixo:.1f}" width="{larg}" '
            f'height="{h_fixo:.1f}" class="{classe} g-fixo"/>')
        corpo.append(
            f'<rect x="{x:.1f}" y="{y_var:.1f}" width="{larg}" '
            f'height="{h_var:.1f}" class="{classe} g-var"/>')
        if h_fixo > 26:
            corpo.append(_texto(cx, y_fixo + h_fixo / 2 + 6,
                                f'Fixo {reais_curto(frota["custo_fixo_mes"])}',
                                "g-dentro"))
        if h_var > 26:
            corpo.append(_texto(cx, y_var + h_var / 2 + 6,
                                f'Variável {reais_curto(frota["custo_variavel_mes"])}',
                                "g-dentro"))
        corpo.append(_texto(cx, y_fixo - 14,
                            f'{reais_curto(frota["custo_mes"])}/mês', "g-valor"))
        corpo.append(_texto(cx, base + 28, frota["rotulo"], "g-rotulo"))
        corpo.append(_texto(cx, base + 50,
                            f'{frota["total_veiculos"]} veículos · '
                            f'{numero(frota["km_dia"])} km/dia', "g-rotulo-fraco"))

    # seta da economia entre as duas colunas
    economia = atual["custo_mes"] - otimizada["custo_mes"]
    if economia > 0:
        y_seta = topo + 4
        corpo.append(f'<line x1="200" y1="{y_seta}" x2="460" y2="{y_seta}" '
                     f'class="g-seta"/>')
        corpo.append(_texto(330, y_seta - 10,
                            f'− {reais_curto(economia)}/mês', "g-destaque"))
    return _svg(L, A, "".join(corpo),
                "Custo mensal da frota atual comparado à frota necessária",
                f"Frota atual {reais_curto(atual['custo_mes'])} por mês; "
                f"frota necessária {reais_curto(otimizada['custo_mes'])} por mês.")


# ------------------------------------------------------- composição da frota ---
def barras_frota(atual: dict, otimizada: dict) -> str:
    """Barras horizontais empilhadas por tipo de veículo."""
    L, A = 720, 300
    x0, larg_max = 250, 420
    maior = max(atual["total_veiculos"], otimizada["total_veiculos"]) or 1

    # o mesmo tipo de veículo recebe o mesmo tom nas duas barras
    ordem, tom = [], {}
    for frota in (atual, otimizada):
        for linha in frota["composicao"]:
            if linha["tipo"] not in tom:
                tom[linha["tipo"]] = len(ordem) % 3
                ordem.append(linha)
    corpo = []
    for i, (frota, classe) in enumerate(((atual, "g-atual"), (otimizada, "g-otim"))):
        y = 60 + i * 110
        corpo.append(_texto(x0 - 16, y + 26, frota["rotulo"], "g-rotulo", "end"))
        corpo.append(_texto(x0 - 16, y + 50,
                            f'{frota["total_veiculos"]} veículos · '
                            f'{numero(frota["assentos"])} assentos',
                            "g-rotulo-fraco", "end"))
        x = x0
        for j, linha in enumerate(frota["composicao"]):
            w = larg_max * linha["qtd"] / maior
            corpo.append(
                f'<rect x="{x:.1f}" y="{y}" width="{max(w - 3, 1):.1f}" height="42" '
                f'rx="3" class="{classe} g-tom{tom[linha["tipo"]]}">'
                f'<title>{esc(linha["nome"])}: {linha["qtd"]} veículo(s), '
                f'{numero(linha["assentos"])} assentos</title></rect>')
            # rótulo só quando cabe inteiro dentro da faixa (~8,5 px por caractere)
            rotulo = f'{linha["qtd"]}× {linha["tipo"]}'
            if w - 6 > 8.5 * len(rotulo):
                corpo.append(_texto(x + w / 2 - 1.5, y + 27, rotulo, "g-dentro"))
            elif w > 30:
                corpo.append(_texto(x + w / 2 - 1.5, y + 27, str(linha["qtd"]), "g-dentro"))
            x += w
    corpo.append(_texto(x0 + larg_max / 2, 34,
                        "Quantidade de veículos por tipo", "g-rotulo-fraco"))

    # legenda: cada tom com o nome por extenso do tipo de veículo
    # cada item traz os dois tons (laranja = frota atual, verde = necessária)
    lx, ly = 60, A - 30
    for linha in ordem:
        rotulo = linha["nome"]
        largura_item = 32 + 7.0 * len(rotulo)
        if lx + largura_item > L - 20:      # quebra de linha da legenda
            lx, ly = 60, ly + 22
        corpo.append(f'<rect x="{lx}" y="{ly - 12}" width="11" height="14" rx="2" '
                     f'class="g-atual g-tom{tom[linha["tipo"]]}"/>')
        corpo.append(f'<rect x="{lx + 12}" y="{ly - 12}" width="11" height="14" rx="2" '
                     f'class="g-otim g-tom{tom[linha["tipo"]]}"/>')
        corpo.append(_texto(lx + 28, ly, rotulo, "g-rotulo-fraco", "start"))
        lx += largura_item
    return _svg(L, A, "".join(corpo), "Composição da frota atual e da frota necessária")


# ---------------------------------------------- ocupação das viagens novas ---
def barras_ocupacao(viagens: list) -> str:
    """Uma barra por viagem otimizada — prova de que a frota menor não deixou
    veículo estourado nem rodando vazio."""
    L, A = 720, 260
    base, topo = A - 56, 44
    if not viagens:
        return _svg(L, A, _texto(L / 2, A / 2, "Sem viagens", "g-rotulo"),
                    "Ocupação")
    rotas = viagens
    largura = min(38, (L - 90) / len(rotas))
    vao = 4 if largura > 10 else max(0.6, largura * 0.18)  # muitas viagens: fresta fina
    x0 = 60
    media = sum(r["ocupacao_pct"] for r in rotas) / len(rotas)
    escala = (base - topo) / 100.0

    corpo = [f'<line x1="52" y1="{base}" x2="{L - 30}" y2="{base}" class="g-eixo"/>']
    for pct_ref in (50, 100):
        y = base - pct_ref * escala
        corpo.append(f'<line x1="52" y1="{y:.1f}" x2="{L - 30}" y2="{y:.1f}" '
                     f'class="g-grade"/>')
        corpo.append(_texto(46, y + 5, f"{pct_ref}%", "g-rotulo-fraco", "end"))
    for i, r in enumerate(sorted(rotas, key=lambda r: -r["ocupacao_pct"])):
        h = min(r["ocupacao_pct"], 110) * escala
        x = x0 + i * largura
        corpo.append(
            f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{largura - vao:.1f}" '
            f'height="{h:.1f}" rx="2" class="g-otim">'
            f'<title>{esc(r["escola"])} · {esc(r.get("turno_nome", ""))} · '
            f'{esc(r["tipo_nome"])} · {r["alunos"]} alunos · '
            f'{r["ocupacao_pct"]}% de ocupação</title></rect>')
    y_media = base - media * escala
    corpo.append(f'<line x1="52" y1="{y_media:.1f}" x2="{L - 30}" y2="{y_media:.1f}" '
                 f'class="g-media"/>')
    corpo.append(_texto(L - 32, y_media - 10,
                        f"média {numero(media, 1)}%", "g-destaque", "end"))
    corpo.append(_texto(L / 2, A - 16,
                        f"{len(rotas)} viagens otimizadas — ocupação de assentos",
                        "g-rotulo-fraco"))
    return _svg(L, A, "".join(corpo), "Ocupação de assentos por viagem otimizada")


# ----------------------------------------------------------------- mapas ---
def _projecao(coordenadas, largura, altura, margem=26):
    """Converte lat/lon em x/y do SVG, sem biblioteca de mapa e sem tiles.

    Projeção equirretangular com correção de longitude por cos(latitude) — em
    escala municipal a distorção é irrelevante, e em troca a página continua
    abrindo offline. Com OSRM ligado, o traçado de cada rota vira a rua de
    verdade; a projeção é a mesma.
    """
    lats = [c[0] for c in coordenadas]
    lons = [c[1] for c in coordenadas]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_media = (lat_min + lat_max) / 2
    cos_lat = math.cos(math.radians(lat_media)) or 1.0

    span_x = max((lon_max - lon_min) * cos_lat, 1e-6)
    span_y = max(lat_max - lat_min, 1e-6)
    escala = min((largura - 2 * margem) / span_x, (altura - 2 * margem) / span_y)
    desloc_x = (largura - span_x * escala) / 2
    desloc_y = (altura - span_y * escala) / 2

    def para_xy(coord):
        x = desloc_x + (coord[1] - lon_min) * cos_lat * escala
        y = altura - (desloc_y + (coord[0] - lat_min) * escala)  # norte para cima
        return x, y
    return para_xy


def mapa_rotas(geografia: dict, viagens: list, turno_id: str = None) -> str:
    """Mapa das rotas escolares: paradas, escolas e o traçado de cada viagem."""
    pontos = (geografia or {}).get("pontos") or {}
    escolas = (geografia or {}).get("escolas") or []
    if not pontos or not escolas:
        return ""
    if turno_id:
        viagens = [v for v in viagens if v.get("turno") == turno_id]
    if not viagens:
        return ""

    L, A = 720, 460
    coordenadas = list(pontos.values()) + [[e["lat"], e["lon"]] for e in escolas]
    xy = _projecao(coordenadas, L, A)
    indice_escola = {e["id"]: i for i, e in enumerate(escolas)}
    corpo = []

    # todas as paradas ao fundo, para dar a forma do município
    for pid, coord in pontos.items():
        x, y = xy(coord)
        corpo.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" class="m-parada"/>')

    # o traçado de cada viagem, colorido pela escola de destino
    for v in viagens:
        escola = next((e for e in escolas if e["id"] == v.get("escola_id")), None)
        if not escola:
            continue
        sequencia = [[escola["lat"], escola["lon"]]]
        sequencia += [pontos[pid] for pid in v.get("paradas", []) if pid in pontos]
        sequencia.append([escola["lat"], escola["lon"]])
        if len(sequencia) < 3:
            continue
        d = " ".join(("M" if i == 0 else "L") + f"{xy(c)[0]:.1f},{xy(c)[1]:.1f}"
                     for i, c in enumerate(sequencia))
        classe = f'm-rota m-e{indice_escola.get(escola["id"], 0) % 3}'
        corpo.append(f'<path d="{d}" class="{classe}">'
                     f'<title>{esc(v["id"])} · {esc(escola["nome"])} · '
                     f'{v.get("alunos", 0)} alunos · '
                     f'{numero(v.get("km_viagem", 0), 1)} km</title></path>')

    # as escolas por cima de tudo
    for e in escolas:
        x, y = xy([e["lat"], e["lon"]])
        i = indice_escola[e["id"]] % 3
        corpo.append(
            f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" '
            f'rx="2" class="m-escola m-e{i}"><title>{esc(e["nome"])}</title></rect>')
        corpo.append(_texto(x, y - 12, e["nome"], "m-rotulo"))

    corpo.append(_texto(L / 2, A - 8,
                        f"{len(viagens)} viagens · {len(pontos)} pontos de "
                        f"embarque · {len(escolas)} escolas",
                        "g-rotulo-fraco"))
    return _svg(L, A, "".join(corpo), "Mapa das rotas escolares",
                "Cada linha é uma viagem; a cor indica a escola de destino.")


def mapa_porta_a_porta(rotas: list, limite: int = 6) -> str:
    """Mapa do porta a porta: o vaivém entre casas e destinos."""
    rotas = [r for r in rotas if r.get("eventos")][:limite]
    coordenadas = [[e["lat"], e["lon"]] for r in rotas for e in r["eventos"]
                   if "lat" in e]
    if len(coordenadas) < 2:
        return ""

    L, A = 720, 420
    xy = _projecao(coordenadas, L, A)
    corpo = []
    for i, r in enumerate(rotas):
        pontos = [e for e in r["eventos"] if "lat" in e]
        d = " ".join(("M" if k == 0 else "L")
                     + f"{xy([e['lat'], e['lon']])[0]:.1f},"
                       f"{xy([e['lat'], e['lon']])[1]:.1f}"
                     for k, e in enumerate(pontos))
        corpo.append(f'<path d="{d}" class="m-rota m-e{i % 3}">'
                     f'<title>{esc(r["id"])} · {r.get("usuarios", 0)} usuários · '
                     f'{numero(r.get("km", 0), 1)} km</title></path>')
        for e in pontos:
            x, y = xy([e["lat"], e["lon"]])
            embarque = e["tipo"] == "embarque"
            corpo.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" '
                f'class="{"m-embarque" if embarque else "m-desembarque"}">'
                f'<title>{esc(e["hora"])} · {esc(e["tipo"])} de '
                f'{esc(e["usuario"])}</title></circle>')
    corpo.append(_texto(L / 2, A - 8,
                        f"{len(rotas)} rotas porta a porta · verde = embarque na "
                        f"casa, laranja = desembarque no destino",
                        "g-rotulo-fraco"))
    return _svg(L, A, "".join(corpo), "Mapa das rotas porta a porta")


# ------------------------------------------- linha do tempo do porta a porta ---
def linha_do_tempo_rota(rota: dict) -> str:
    """Mostra a relação n:n de uma rota porta a porta.

    É o gráfico que explica o vertical PCD numa olhada: os triângulos para
    cima são embarques, para baixo são desembarques, e a escada é quanta gente
    está dentro do veículo em cada momento. Um roteirizador de entrega
    desenharia uma linha só descendo; aqui ela sobe e desce várias vezes.
    """
    L, A = 720, 240
    esq, dir_ = 60, L - 40
    base, topo = A - 56, 56
    eventos = rota.get("eventos", [])
    if len(eventos) < 2:
        return _svg(L, A, _texto(L / 2, A / 2, "Rota sem eventos", "g-rotulo"),
                    "Linha do tempo da rota")

    inicio = eventos[0]["minuto"]
    fim = max(e["minuto"] for e in eventos)
    span = max(1, fim - inicio)
    pico = max(1, max(e["ocupacao_apos"] for e in eventos))

    def x(minuto):
        return esq + (dir_ - esq) * (minuto - inicio) / span

    def y(ocupacao):
        return base - (base - topo) * ocupacao / pico

    corpo = [f'<line x1="{esq - 8}" y1="{base}" x2="{dir_}" y2="{base}" '
             f'class="g-eixo"/>']

    # escada de ocupação
    pontos, anterior = [], base
    for e in eventos:
        px, py = x(e["minuto"]), y(e["ocupacao_apos"])
        pontos.append(f"L{px:.1f},{anterior:.1f} L{px:.1f},{py:.1f}")
        anterior = py
    caminho = (f"M{esq:.1f},{base:.1f} " + " ".join(pontos)
               + f" L{dir_:.1f},{anterior:.1f}")
    corpo.append(f'<path d="{caminho}" class="g-linha"/>')

    for e in eventos:
        px, py = x(e["minuto"]), y(e["ocupacao_apos"])
        embarque = e["tipo"] == "embarque"
        sinal = -1 if embarque else 1
        corpo.append(
            f'<polygon points="{px:.1f},{py + sinal * -9:.1f} '
            f'{px - 5:.1f},{py + sinal * 3:.1f} {px + 5:.1f},{py + sinal * 3:.1f}" '
            f'class="{"g-otim" if embarque else "g-atual"}">'
            f'<title>{esc(e["hora"])} · {"embarque" if embarque else "desembarque"} '
            f'de {esc(e["usuario"])}'
            f'{" (cadeirante)" if e.get("cadeirante") else ""} · '
            f'{e["ocupacao_apos"]} a bordo</title></polygon>')

    corpo.append(_texto(esq - 8, topo - 22, "Pessoas dentro do veículo",
                        "g-rotulo-fraco", "start"))
    corpo.append(_texto(esq, base + 26, eventos[0]["hora"], "g-rotulo-fraco"))
    corpo.append(_texto(dir_, base + 26, eventos[-1]["hora"], "g-rotulo-fraco"))
    corpo.append(_texto(L / 2, A - 12,
                        f"▲ embarque   ▼ desembarque   ·   pico de {pico} a bordo",
                        "g-rotulo-fraco"))
    return _svg(L, A, "".join(corpo),
                f"Linha do tempo da rota {rota.get('id', '')} porta a porta")


# ---------------------------------------------------- evolução do aprendizado ---
def linha_erro(semanas: list) -> str:
    """Erro médio (min) do tempo estimado vs realizado, semana a semana."""
    L, A = 720, 300
    base, topo = A - 62, 40
    esq, dir_ = 64, L - 40
    if len(semanas) < 2:
        return _svg(L, A, _texto(L / 2, A / 2, "Série indisponível", "g-rotulo"),
                    "Evolução do aprendizado")
    maior = max(s["mae_min"] for s in semanas) * 1.15
    passo = (dir_ - esq) / (len(semanas) - 1)

    def ponto(i, s):
        return esq + i * passo, base - (base - topo) * s["mae_min"] / maior

    pontos = [ponto(i, s) for i, s in enumerate(semanas)]
    caminho = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                       for i, (x, y) in enumerate(pontos))
    area = (caminho + f" L{pontos[-1][0]:.1f},{base} L{pontos[0][0]:.1f},{base} Z")

    corpo = [f'<line x1="{esq - 12}" y1="{base}" x2="{dir_}" y2="{base}" class="g-eixo"/>',
             f'<path d="{area}" class="g-area"/>',
             f'<path d="{caminho}" class="g-linha"/>']
    for i, ((x, y), s) in enumerate(zip(pontos, semanas)):
        corpo.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="g-ponto"/>')
        if i in (0, len(semanas) - 1):
            corpo.append(_texto(x, y - 16, f'{numero(s["mae_min"], 1)} min', "g-valor"))
        rotulo = str(s["semana"]).replace("Semana ", "S")
        corpo.append(_texto(x, base + 26, rotulo, "g-rotulo-fraco"))
    corpo.append(_texto(esq - 12, topo - 12,
                        "Erro médio do tempo estimado (minutos)",
                        "g-rotulo-fraco", "start"))
    return _svg(L, A, "".join(corpo),
                "Evolução do erro médio de tempo estimado por semana")
