# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-dados
Da planilha para o mapa: alunos viram PONTOS DE EMBARQUE.

Este é o elo que faltava entre o importador e o motor. A planilha traz uma
linha por aluno, com a casa dele; o motor de rotas trabalha com pontos de
encontro, porque no transporte escolar por ponto o veículo não encosta em cada
casa — as crianças caminham até uma esquina combinada.

Como o agrupamento é feito, e por que assim:

- **raio de caminhada, não número de clusters.** A pergunta certa não é
  "quantos pontos eu quero", é "quanto essa criança pode andar". Zona urbana:
  300 m. Zona rural: 800 m, porque lá as casas são esparsas e o ponto na
  entrada da estrada já é o costume;
- **cada escola tem seus pontos.** Duas crianças na mesma esquina indo para
  escolas diferentes são dois pontos no mesmo lugar. Parece desperdício, mas é
  a realidade da operação: são viagens diferentes, em veículos diferentes;
- **o ponto fica no centro de quem ele atende**, recalculado a cada aluno que
  entra. Assim ninguém acaba caminhando muito mais que os outros;
- **cadeirante nunca é agrupado por distância.** Quem usa cadeira de rodas não
  atravessa 300 m de estrada de terra: o ponto dele é a casa dele, sempre.
  Agrupar cadeirante com o vizinho seria a economia mais cara do sistema.

O resultado é uma lista de `PontoEmbarque`, exatamente o que
`motor/dimensionar.py` já consome — o motor não sabe se veio do Município
Modelo ou da planilha da secretaria.
"""
from __future__ import annotations

import math
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados.municipio_modelo import ESCOLAS, PontoEmbarque  # noqa: E402

RAIO_URBANO_M = 300
RAIO_RURAL_M = 800
RAIO_TERRA_M = 6371000.0

# Bairro cujo nome contém uma destas palavras é tratado como rural — é
# heurística declarada, e o gestor vê o raio usado na tela.
PALAVRAS_RURAIS = ("rural", "assentamento", "sitio", "chacara", "estrada",
                   "distrito", "colonia", "linha", "zona rural")


def _normalizar(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).lower().strip()


def distancia_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * RAIO_TERRA_M * math.asin(math.sqrt(h))


def e_rural(bairro: str) -> bool:
    alvo = _normalizar(bairro)
    return any(palavra in alvo for palavra in PALAVRAS_RURAIS)


def raio_de(bairro: str, raio_urbano=RAIO_URBANO_M, raio_rural=RAIO_RURAL_M):
    return raio_rural if e_rural(bairro) else raio_urbano


class _Grupo:
    """Um ponto em formação: centro móvel e os alunos que já entraram."""

    def __init__(self, ident, aluno):
        self.id = ident
        self.lat, self.lon = aluno["lat"], aluno["lon"]
        self.alunos = []
        self.escola = aluno["escola"]
        self.bairro = aluno.get("bairro") or ""
        self.exclusivo = bool(aluno.get("cadeirante"))
        self.adicionar(aluno)

    def adicionar(self, aluno):
        self.alunos.append(aluno)
        n = len(self.alunos)
        # média corrida: o ponto vai para o meio de quem ele atende
        self.lat += (aluno["lat"] - self.lat) / n
        self.lon += (aluno["lon"] - self.lon) / n

    def cabe(self, aluno, raio_m: float) -> bool:
        if self.exclusivo or aluno.get("cadeirante"):
            return False               # cadeirante embarca na porta de casa
        if aluno["escola"] != self.escola:
            return False
        return distancia_m((self.lat, self.lon),
                           (aluno["lat"], aluno["lon"])) <= raio_m

    def para_ponto(self, turnos) -> PontoEmbarque:
        alunos = {t: 0 for t in turnos}
        cadeirantes = {t: 0 for t in turnos}
        for aluno in self.alunos:
            turno = aluno["turno"] if aluno["turno"] in alunos else turnos[0]
            alunos[turno] += 1
            if aluno.get("cadeirante"):
                cadeirantes[turno] += 1
        return PontoEmbarque(
            id=self.id, lat=round(self.lat, 6), lon=round(self.lon, 6),
            alunos=alunos, alunos_cadeirantes=cadeirantes,
            escola_id=self.escola, distrito=self.bairro)


def _escolas_do_municipio_modelo() -> dict:
    return {_normalizar(e.nome): e for e in ESCOLAS}


def resolver_escolas(alunos: list, coordenadas: dict = None) -> tuple:
    """(escolas, avisos) — cada escola com coordenada e a origem dela.

    Ordem de preferência, e todas ficam registradas:
    1. coordenada informada pelo gestor na tela;
    2. escola conhecida do Município Modelo (só serve para a demonstração);
    3. centro dos alunos daquela escola — que é um chute útil, e por isso
       aparece com aviso: alguém precisa arrastar o ponto para o lugar certo
       antes de publicar rota.
    """
    coordenadas = {_normalizar(k): v for k, v in (coordenadas or {}).items()}
    conhecidas = _escolas_do_municipio_modelo()
    por_nome = {}
    for aluno in alunos:
        por_nome.setdefault(aluno["escola"], []).append(aluno)

    escolas, avisos = [], []
    for i, (nome, lista) in enumerate(sorted(por_nome.items()), start=1):
        chave = _normalizar(nome)
        if chave in coordenadas:
            lat, lon = coordenadas[chave]
            origem = "informada pelo município"
        elif chave in conhecidas:
            lat, lon = conhecidas[chave].lat, conhecidas[chave].lon
            origem = "cadastro do Município Modelo"
        else:
            # só entra no centro quem tem coordenada; sem nenhum, não há
            # centro que se possa calcular — e inventar um seria pior
            com_coordenada = [a for a in lista
                              if a.get("lat") is not None
                              and a.get("lon") is not None]
            if not com_coordenada:
                avisos.append(
                    f"A escola “{nome}” não tem coordenada no cadastro e "
                    f"nenhum dos {len(lista)} alunos dela tem endereço "
                    f"localizado. Marque a escola no mapa para poder "
                    f"roteirizar esta unidade.")
                continue
            lat = sum(a["lat"] for a in com_coordenada) / len(com_coordenada)
            lon = sum(a["lon"] for a in com_coordenada) / len(com_coordenada)
            origem = "estimada pelo centro dos alunos"
            avisos.append(
                f"A escola “{nome}” não tem coordenada no cadastro. Usei o "
                f"centro dos {len(com_coordenada)} alunos dela — marque a "
                f"escola no mapa antes de publicar a rota.")
        escolas.append({"id": f"E{i}", "nome": nome,
                        "lat": round(lat, 6), "lon": round(lon, 6),
                        "alunos": len(lista), "origem_da_coordenada": origem})
    return escolas, avisos


def agrupar(alunos: list, turnos: list = None, coordenadas_escolas: dict = None,
            raio_urbano: float = RAIO_URBANO_M,
            raio_rural: float = RAIO_RURAL_M) -> dict:
    """Alunos importados -> pontos de embarque + escolas, prontos para o motor.

    Devolve também as contas que a tela mostra: quantos alunos por ponto,
    quanto o aluno mais distante caminha e o que ficou por resolver.
    """
    turnos = turnos or ["manha", "tarde"]
    escolas, avisos = resolver_escolas(alunos, coordenadas_escolas)
    id_da_escola = {e["nome"]: e["id"] for e in escolas}

    utilizaveis = [a for a in alunos
                   if a.get("lat") is not None and a.get("lon") is not None]
    if len(utilizaveis) < len(alunos):
        avisos.append(f"{len(alunos) - len(utilizaveis)} aluno(s) ficaram de "
                      f"fora por não ter coordenada nenhuma.")

    # ordem estável: mesma planilha, mesmos pontos, sempre
    ordenados = sorted(utilizaveis,
                       key=lambda a: (a["escola"], round(a["lat"], 5),
                                      round(a["lon"], 5), a["id"]))
    grupos = []
    for aluno in ordenados:
        raio = raio_de(aluno.get("bairro"), raio_urbano, raio_rural)
        alvo = None
        melhor = None
        for grupo in grupos:
            if not grupo.cabe(aluno, raio):
                continue
            d = distancia_m((grupo.lat, grupo.lon), (aluno["lat"], aluno["lon"]))
            if melhor is None or d < melhor:
                melhor, alvo = d, grupo
        if alvo is None:
            grupos.append(_Grupo(f"P{len(grupos) + 1:03d}", aluno))
        else:
            alvo.adicionar(aluno)

    pontos, caminhadas = [], []
    for grupo in grupos:
        grupo.escola = id_da_escola.get(grupo.escola, grupo.escola)
        pontos.append(grupo.para_ponto(turnos))
        for aluno in grupo.alunos:
            caminhadas.append(distancia_m((grupo.lat, grupo.lon),
                                          (aluno["lat"], aluno["lon"])))

    exclusivos = sum(1 for g in grupos if g.exclusivo)
    return {
        "pontos": pontos,
        "escolas": escolas,
        "avisos": avisos,
        "resumo": {
            "alunos": len(utilizaveis),
            "pontos": len(pontos),
            "alunos_por_ponto": round(len(utilizaveis) / max(1, len(pontos)), 2),
            "caminhada_media_m": round(sum(caminhadas) / max(1, len(caminhadas))),
            "caminhada_maxima_m": round(max(caminhadas)) if caminhadas else 0,
            "pontos_exclusivos_de_cadeirante": exclusivos,
            "raio_urbano_m": raio_urbano,
            "raio_rural_m": raio_rural,
            "escolas": len(escolas),
            "escolas_com_coordenada_estimada": sum(
                1 for e in escolas
                if e["origem_da_coordenada"].startswith("estimada")),
        },
    }


if __name__ == "__main__":
    import json

    caminho = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "relatorios", "importacao.json")
    with open(caminho, encoding="utf-8") as f:
        importacao = json.load(f)
    resultado = agrupar(importacao["alunos"])
    print(json.dumps(resultado["resumo"], ensure_ascii=False, indent=2))
    for aviso in resultado["avisos"]:
        print(f"  ⚠ {aviso}")
