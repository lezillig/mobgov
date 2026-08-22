# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-rotas
Da planilha da secretaria às rotas, num comando só.

    planilha  ->  importador  ->  agrupador  ->  motor  ->  plano publicável

Até a Sprint 7 o motor só sabia roteirizar o Município Modelo: a planilha
entrava, virava `importacao.json` e parava ali. Este módulo fecha o caminho —
e é o mesmo `montar_relatorio` que roda nos dois casos, para que o número da
demonstração e o número do piloto não possam divergir.

Uso:
    python motor/planejar.py docs/demonstracao/planilha-prefeitura-demo.xlsx
    python motor/planejar.py --importacao relatorios/importacao.json
    python motor/planejar.py planilha.xlsx --tempo-limite 10 --raio-urbano 400
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dados import agrupar as agrupar_mod
from dados import importador
from dados import perfis as perfis_mod
from dados.municipio_modelo import Escola
from dados.planilha import ErroDePlanilha
from dados.planilha_exemplo import limites_do_municipio, referencias_de_bairro
from motor import dimensionar

DIR_RELATORIOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relatorios")


def importar_planilha(caminho: str, guardar_nomes: bool = False,
                      perfil=None) -> dict:
    """Lê a planilha e devolve o mesmo formato de `relatorios/importacao.json`."""
    perfil = perfil or perfis_mod.PERFIL_ESCOLAR
    resultado = importador.importar(
        caminho, referencias=referencias_de_bairro(),
        guardar_nomes=guardar_nomes, limites=limites_do_municipio(),
        turnos_validos=[t.id for t in perfil.turnos])
    return {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "arquivo": os.path.basename(caminho),
        "resumo": resultado.resumo(),
        "alunos": resultado.alunos,
        "problemas": resultado.problemas,
        "cofre": resultado.cofre if guardar_nomes else {},
    }


def ler_frota_declarada(caminho: str, aba: int = 1, perfil=None) -> dict:
    """Procura na planilha a aba com a frota que o município tem hoje.

    Prefeitura costuma mandar isso na segunda aba do mesmo arquivo ("Frota
    atual", "Veículos", "Contrato"), com uma linha por tipo. Ler daqui evita
    pedir de novo o que já veio — e é o número sem o qual não existe "antes"
    para comparar.

    Devolve {} quando a aba não existe ou não é reconhecível: aí a tela
    pergunta ao gestor, em vez de o sistema inventar.
    """
    from dados.planilha import ler

    try:
        linhas = ler(caminho, aba=aba)
    except Exception:
        return {}

    tipos = (perfil or perfis_mod.PERFIL_ESCOLAR).tipos_veiculo
    por_nome = {_normalizar(t.nome): t for t in tipos}
    por_capacidade = {t.capacidade: t for t in tipos}
    composicao, km_dia = {}, 0.0
    for linha in linhas:
        celulas = [str(c or "").strip() for c in linha]
        texto = " ".join(celulas)
        achado = re.search(r"([\d.,]+)\s*km", texto, re.IGNORECASE)
        if achado and "km" in texto.lower():
            try:
                km_dia = float(achado.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
        if not celulas or not celulas[0]:
            continue
        tipo = por_nome.get(_normalizar(celulas[0]))
        numeros = [_inteiro(c) for c in celulas[1:]]
        numeros = [n for n in numeros if n is not None]
        if tipo is None and numeros:
            tipo = por_capacidade.get(numeros[0])
        if tipo is None or not numeros:
            continue
        # a quantidade é o último número inteiro pequeno da linha que não é
        # capacidade nem posição de cadeira; na prática, o penúltimo ou o
        # último — pega-se o maior candidato plausível
        candidatos = [n for n in numeros if 0 < n <= 500
                      and n != tipo.capacidade
                      and n != tipo.posicoes_cadeirante]
        if not candidatos:
            continue
        composicao[tipo.id] = composicao.get(tipo.id, 0) + candidatos[0]

    if not composicao:
        return {}
    return {"composicao": composicao, "km_dia": km_dia,
            "origem": f"aba {aba + 1} da planilha enviada"}


def _normalizar(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).lower().strip()


def _inteiro(texto: str):
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    try:
        valor = float(texto)
    except ValueError:
        return None
    return int(valor) if valor == int(valor) else None


def planejar(importacao: dict, coordenadas_escolas: dict = None,
             frota_declarada: dict = None, municipio: str = None,
             tempo_limite_s: int = dimensionar.TEMPO_LIMITE_SOLVER_S,
             raio_urbano: float = agrupar_mod.RAIO_URBANO_M,
             raio_rural: float = agrupar_mod.RAIO_RURAL_M,
             progresso=None, perfil=None) -> dict:
    """Agrupa os alunos importados em pontos e roteiriza.

    O relatório sai no mesmo formato do Município Modelo — o painel, o console
    e os apps não precisam saber de onde a demanda veio.
    """
    avisar = progresso or (lambda etapa, detalhe="": None)
    alunos = importacao.get("alunos") or []
    if not alunos:
        raise ValueError("A importação não tem nenhum aluno para roteirizar.")

    perfil = perfil or perfis_mod.PERFIL_ESCOLAR
    conhecidos = {d.nome: (d.lat, d.lon) for d in perfil.destinos}
    conhecidos.update(coordenadas_escolas or {})
    avisar("agrupando", f"{len(alunos)} {perfil.rotulo_passageiro_plural} em "
                        f"pontos de embarque")
    agrupado = agrupar_mod.agrupar(
        alunos, turnos=[t.id for t in perfil.turnos],
        coordenadas_escolas=conhecidos,
        raio_urbano=raio_urbano, raio_rural=raio_rural)

    escolas = [Escola(e["id"], e["nome"], e["lat"], e["lon"])
               for e in agrupado["escolas"]]
    avisar("agrupado", f"{agrupado['resumo']['pontos']} pontos · "
                       f"{len(escolas)} {perfil.rotulo_destino_plural} · "
                       f"caminhada média de "
                       f"{agrupado['resumo']['caminhada_media_m']} m")

    relatorio = dimensionar.montar_relatorio(
        agrupado["pontos"], escolas=escolas, turnos=perfil.turnos,
        tipos=perfil.tipos_veiculo, perfil=perfil,
        municipio=municipio or ("Cliente (planilha importada)"
                                if perfil.vertical == "fretamento"
                                else "Município (planilha importada)"),
        tempo_limite_s=tempo_limite_s, frota_declarada=frota_declarada,
        # com planilha real, o "antes" é informado ou não existe
        permitir_estimativa=False, progresso=progresso)

    # A procedência fica gravada no próprio plano: quem abrir daqui a um ano
    # precisa saber de qual arquivo aquelas rotas saíram.
    relatorio["origem"] = {
        "tipo": "planilha_importada",
        "arquivo": importacao.get("arquivo"),
        "importado_em": importacao.get("gerado_em"),
        "alunos_na_planilha": importacao.get("resumo", {}).get(
            "alunos_importados"),
        "erros_na_importacao": importacao.get("resumo", {}).get("erros"),
        "avisos_na_importacao": importacao.get("resumo", {}).get("avisos"),
    }
    relatorio["agrupamento"] = agrupado["resumo"]
    relatorio["agrupamento"]["avisos"] = agrupado["avisos"]
    relatorio["geografia"]["escolas"] = agrupado["escolas"]
    return relatorio


def gravar(relatorio: dict, saida: str = None) -> str:
    saida = saida or os.path.join(DIR_RELATORIOS, "dimensionamento.json")
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    return saida


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Planilha da prefeitura -> rotas publicáveis")
    ap.add_argument("planilha", nargs="?", help=".xlsx, .csv ou .tsv")
    ap.add_argument("--importacao", default=None,
                    help="usar uma importação já feita (JSON)")
    ap.add_argument("--saida", default=None)
    ap.add_argument("--municipio", default=None)
    ap.add_argument("--tempo-limite", dest="tempo_limite", type=int,
                    default=dimensionar.TEMPO_LIMITE_SOLVER_S)
    ap.add_argument("--raio-urbano", dest="raio_urbano", type=float,
                    default=agrupar_mod.RAIO_URBANO_M)
    ap.add_argument("--raio-rural", dest="raio_rural", type=float,
                    default=agrupar_mod.RAIO_RURAL_M)
    ap.add_argument("--frota-atual", dest="frota_atual", default=None,
                    help='frota declarada, ex.: "ONIBUS31=17,MICRO20=10,'
                         'VAN15A=3" (km/dia com --km-dia)')
    ap.add_argument("--km-dia", dest="km_dia", type=float, default=None)
    ap.add_argument("--perfil", default="escolar",
                    help="escolar, fretamento ou caminho de um perfil .json")
    a = ap.parse_args(argv)

    perfil = perfis_mod.carregar(a.perfil)
    print(f"Perfil: {perfil.nome} — {len(perfil.turnos)} turnos, "
          f"{perfil.rotulo_passageiro_plural}, limite de "
          f"{perfil.tempo_max_trajeto_min} min por trajeto")
    if a.importacao:
        with open(a.importacao, encoding="utf-8") as f:
            importacao = json.load(f)
    elif a.planilha:
        try:
            importacao = importar_planilha(a.planilha, perfil=perfil)
        except ErroDePlanilha as erro:
            print(f"Não deu para ler a planilha: {erro}")
            return 1
        gravar(importacao, os.path.join(DIR_RELATORIOS, "importacao.json"))
        r = importacao["resumo"]
        print(f"Importação: {r['alunos_importados']} alunos · {r['erros']} "
              f"erros · {r['avisos']} avisos")
    else:
        ap.error("informe a planilha ou --importacao")

    frota = None
    if a.frota_atual:
        frota = {"composicao": dict(
            (par.split("=")[0].strip(), int(par.split("=")[1]))
            for par in a.frota_atual.split(",") if "=" in par),
            "km_dia": a.km_dia or 0.0, "origem": "informada na linha de comando"}
    elif a.planilha:
        frota = ler_frota_declarada(a.planilha, perfil=perfil) or None
        if frota:
            print(f"Frota atual lida da planilha ({frota['origem']}): "
                  f"{sum(frota['composicao'].values())} veículos · "
                  f"{frota['km_dia']} km/dia")
    if a.km_dia and frota:
        frota["km_dia"] = a.km_dia

    relatorio = planejar(
        importacao, frota_declarada=frota, perfil=perfil,
        municipio=a.municipio, tempo_limite_s=a.tempo_limite,
        raio_urbano=a.raio_urbano, raio_rural=a.raio_rural,
        progresso=lambda etapa, detalhe="": print(f"  {etapa}: {detalhe}",
                                                  flush=True))
    caminho = gravar(relatorio, a.saida)
    fo, e = relatorio["frota_otimizada"], relatorio["economia"]
    print(f"\nFrota necessária: {fo['total_veiculos']} veículos · "
          f"{len(fo['viagens'])} viagens/dia · {fo['km_dia']} km/dia")
    if e:
        print(f"Economia: {e['veiculos']} veículos a menos "
              f"(−{e['reducao_frota_pct']}%) · R$ {e['custo_mes']:,}/mês")
    else:
        print(relatorio["comparacao_indisponivel"])
    equipe = relatorio.get("equipe")
    if equipe:
        r = equipe["resumo"]
        media = int(round(r["jornada_media_min"]))
        print(f"Equipe: {r['motoristas']} motoristas · jornada média de "
              f"{media // 60}h{media % 60:02d}"
              f" ({r['ocupacao_da_jornada_pct']}% da jornada normal) · "
              f"{r['com_dupla_pegada']} com dupla pegada · "
              f"{r['escalas_com_problema']} escalas com problema")
        print(f"        custo da equipe: R$ {equipe['custo_equipe_mes']:,}/mês")
        for linha in equipe["explicacao"][:3]:
            print(f"  - {linha}")
    for aviso in relatorio.get("coerencia") or []:
        print(f"\n  ⚠ {aviso}")
    nao = relatorio.get("demanda_nao_atendida") or {}
    if nao.get("alunos"):
        print(f"\nATENÇÃO: {nao['alunos']} aluno(s) em {len(nao['pontos'])} "
              f"ponto(s) não cabem no limite de "
              f"{dimensionar.TEMPO_MAX_TRAJETO_MIN} min:")
        for item in nao["pontos"][:5]:
            print(f"  - {item['ponto']} ({item['bairro']}) → {item['escola']}: "
                  f"{item['minutos_minimos']} min")
    for aviso in relatorio["agrupamento"].get("avisos", []):
        print(f"  ⚠ {aviso}")
    print(f"Plano: {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
