# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 5 · agent-transito
Provedor de tempos sobre MALHA VIÁRIA REAL (OSRM).

Até aqui o sistema estimava o percurso por distância em linha reta × fator de
sinuosidade. Serve para demonstrar, não para operar: a estrada que contorna o
morro, a ponte que só tem uma faixa e a rua sem saída não aparecem numa reta.
Este módulo troca a estimativa pela malha viária de verdade, servida por um
OSRM próprio sobre o OpenStreetMap do município.

Por que OSRM próprio, e não uma API paga (ver docs/benchmarking-mercado.md):
- a matriz de planejamento é grande (300 pontos = 90 mil pares) e cobrada por
  elemento nas APIs comerciais; no OSRM próprio custa o servidor e mais nada;
- o município roda offline, sem depender de chave de terceiro;
- as velocidades podem ser corrigidas com o histórico do próprio município
  (o CSV de velocidades do OSRM), que é o mesmo caminho que o agent-aprendizado
  já usa para os fatores de trânsito.

O que este cliente resolve, e que um `requests.get` não resolveria:

1. **Limite de tamanho**: o OSRM recusa tabelas grandes (`max-table-size`,
   100 coordenadas por padrão). A matriz é quebrada em blocos e remontada.
2. **Queda do servidor**: se o OSRM não responde, cai para o provedor de
   reserva (haversine) e DIZ que caiu — o painel mostra a origem dos tempos.
3. **Custo de recomputar**: a matriz do planejamento é sempre a mesma. Fica
   em cache no disco, com chave pelo conteúdo.

Uso:
    export MOBGOV_OSRM_URL=http://localhost:5000
    python motor/dimensionar.py        # passa a usar malha real automaticamente
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from dados.tempos import ProvedorDeTempos, ProvedorHaversine

DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CACHE = os.path.join(DIR_BASE, "relatorios", "cache")

# O OSRM padrão aceita 100 coordenadas por tabela. Com blocos de 45 origens ×
# 45 destinos ficam 90 coordenadas por requisição, com folga.
BLOCO_PADRAO = 45
TIMEOUT_S = 30
TENTATIVAS = 3


class ErroOSRM(RuntimeError):
    pass


def _chave_cache(base_url: str, perfil: str, locais) -> str:
    bruto = json.dumps(
        [base_url, perfil, [[round(l[0], 6), round(l[1], 6)] for l in locais]],
        separators=(",", ":"))
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:16]


class ProvedorOSRM(ProvedorDeTempos):
    """Matriz de tempo e distância pela malha viária real.

    `fallback` é o provedor usado quando o OSRM não responde. Deixar `None`
    faz o erro subir — bom para um job noturno que precisa falhar alto, ruim
    para uma demonstração ao vivo. O padrão é cair para o haversine e marcar.
    """

    # sentinela: distingue "não passei fallback" de "quero explicitamente sem"
    PADRAO = object()

    def __init__(self, base_url: str = None, perfil: str = "driving",
                 fallback=PADRAO, bloco: int = BLOCO_PADRAO,
                 cache_dir: str = DIR_CACHE, timeout_s: int = TIMEOUT_S,
                 tentativas: int = TENTATIVAS):
        self.base_url = (base_url or os.environ.get("MOBGOV_OSRM_URL", "")).rstrip("/")
        self.perfil = perfil
        self.fallback = (ProvedorHaversine() if fallback is ProvedorOSRM.PADRAO
                         else fallback)
        self.bloco = bloco
        self.cache_dir = cache_dir
        self.timeout_s = timeout_s
        self.tentativas = tentativas
        self.nome = "osrm"
        self.ultima_origem = "osrm"      # "osrm", "cache" ou "fallback"
        self.ultimo_erro = None

    # ---------------------------------------------------------------- HTTP
    def _consultar(self, url: str) -> dict:
        ultimo = None
        for tentativa in range(self.tentativas):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout_s) as r:
                    dados = json.loads(r.read().decode("utf-8"))
                if dados.get("code") != "Ok":
                    raise ErroOSRM(f"OSRM respondeu {dados.get('code')}: "
                                   f"{dados.get('message', 'sem mensagem')}")
                return dados
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError, ErroOSRM) as erro:
                ultimo = erro
                if tentativa < self.tentativas - 1:
                    time.sleep(0.5 * (2 ** tentativa))   # 0,5s, 1s, 2s…
        raise ErroOSRM(f"OSRM em {self.base_url} não respondeu: {ultimo}")

    def disponivel(self) -> bool:
        """Bate na porta antes de prometer malha real ao usuário."""
        if not self.base_url:
            return False
        try:
            self._consultar(f"{self.base_url}/table/v1/{self.perfil}/"
                            f"-47.80,-21.15;-47.79,-21.14?annotations=duration")
            return True
        except ErroOSRM as erro:
            self.ultimo_erro = str(erro)
            return False

    # -------------------------------------------------------------- matriz
    def _tabela(self, locais, origens, destinos):
        """Uma requisição de tabela para um bloco de origens × destinos."""
        indices = list(dict.fromkeys(list(origens) + list(destinos)))
        posicao = {no: i for i, no in enumerate(indices)}
        coords = ";".join(f"{locais[i][1]:.6f},{locais[i][0]:.6f}"
                          for i in indices)
        url = (f"{self.base_url}/table/v1/{self.perfil}/{coords}"
               f"?annotations=duration,distance"
               f"&sources={';'.join(str(posicao[o]) for o in origens)}"
               f"&destinations={';'.join(str(posicao[d]) for d in destinos)}")
        dados = self._consultar(url)
        return dados["durations"], dados.get("distances")

    def matriz(self, locais, partida_min: int = None, zonas=None):
        n = len(locais)
        if n < 2:
            return [[0.0]] * n, [[0]] * n

        cache = self._ler_cache(locais)
        if cache:
            self.ultima_origem = "cache"
            return cache

        if not self.base_url:
            return self._cair_para_reserva(
                locais, partida_min, zonas,
                "MOBGOV_OSRM_URL não configurada")
        try:
            dist, tempo = self._matriz_em_blocos(locais, n)
        except ErroOSRM as erro:
            return self._cair_para_reserva(locais, partida_min, zonas, str(erro))

        self.ultima_origem = "osrm"
        self.ultimo_erro = None
        self._gravar_cache(locais, dist, tempo)
        return dist, tempo

    def _matriz_em_blocos(self, locais, n):
        dist = [[0.0] * n for _ in range(n)]
        tempo = [[0] * n for _ in range(n)]
        blocos = [list(range(i, min(i + self.bloco, n)))
                  for i in range(0, n, self.bloco)]
        for origens in blocos:
            for destinos in blocos:
                duracoes, distancias = self._tabela(locais, origens, destinos)
                for a, i in enumerate(origens):
                    for b, j in enumerate(destinos):
                        if i == j:
                            continue
                        segundos = duracoes[a][b]
                        if segundos is None:
                            raise ErroOSRM(
                                f"OSRM não encontrou caminho entre os pontos "
                                f"{i} e {j} — endereço fora da malha viária?")
                        tempo[i][j] = max(1, round(segundos / 60))
                        if distancias:
                            dist[i][j] = distancias[a][b] / 1000.0
        return dist, tempo

    def _cair_para_reserva(self, locais, partida_min, zonas, motivo):
        self.ultima_origem = "fallback"
        self.ultimo_erro = motivo
        if self.fallback is None:
            raise ErroOSRM(motivo)
        return self.fallback.matriz(locais, partida_min=partida_min, zonas=zonas)

    # --------------------------------------------------------------- cache
    def _caminho_cache(self, locais) -> str:
        return os.path.join(
            self.cache_dir,
            f"osrm-{_chave_cache(self.base_url, self.perfil, locais)}.json")

    def _ler_cache(self, locais):
        if not self.cache_dir:
            return None
        caminho = self._caminho_cache(locais)
        if not os.path.exists(caminho):
            return None
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return dados["distancias"], dados["tempos"]
        except (OSError, KeyError, json.JSONDecodeError):
            return None   # cache corrompido não pode derrubar a operação

    def _gravar_cache(self, locais, dist, tempo):
        if not self.cache_dir:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self._caminho_cache(locais), "w", encoding="utf-8") as f:
            json.dump({"pontos": len(locais), "perfil": self.perfil,
                       "distancias": dist, "tempos": tempo}, f)

    # ------------------------------------------------------------ geometria
    def geometria_rota(self, locais) -> list:
        """Traçado real da rota, para desenhar no mapa (lista de lat/lon).

        Sem OSRM, devolve os próprios pontos — o mapa vira uma poligonal reta
        entre paradas, que é honesto: é o que o sistema sabe.
        """
        if not self.base_url or len(locais) < 2:
            return list(locais)
        coords = ";".join(f"{l[1]:.6f},{l[0]:.6f}" for l in locais)
        url = (f"{self.base_url}/route/v1/{self.perfil}/{coords}"
               f"?overview=full&geometries=geojson")
        try:
            dados = self._consultar(url)
            linha = dados["routes"][0]["geometry"]["coordinates"]
            return [(lat, lon) for lon, lat in linha]
        except (ErroOSRM, KeyError, IndexError):
            return list(locais)
