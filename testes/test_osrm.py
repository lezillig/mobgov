# -*- coding: utf-8 -*-
"""Testes do provedor OSRM (Sprint 5).

Sobem um servidor OSRM FALSO em memória (http.server da biblioteca padrão) e
conversam com ele pelo cliente de verdade. Assim o cliente é exercitado ponta
a ponta — chunking, cache, retry e queda — sem depender de um OSRM instalado.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dados import osrm as osrm_mod  # noqa: E402
from dados.tempos import ProvedorHaversine  # noqa: E402

PONTOS = [(-21.150 + 0.01 * i, -47.800 + 0.005 * i) for i in range(6)]


class OSRMFalso(BaseHTTPRequestHandler):
    """Responde no formato do OSRM. Contadores para inspeção nos testes."""
    requisicoes = 0
    maior_lote = 0
    falhar = False
    sem_caminho = False

    def do_GET(self):
        OSRMFalso.requisicoes += 1
        if OSRMFalso.falhar:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"code":"Error"}')
            return

        rota = urlparse(self.path)
        # Atenção: urlparse trata o que vem depois de ";" no último segmento
        # como "params" da URL — e o OSRM separa coordenadas exatamente com
        # ";". Sem recolar, o servidor falso enxergaria uma coordenada só.
        caminho = rota.path + (";" + rota.params if rota.params else "")
        partes = caminho.strip("/").split("/")
        coords = partes[-1].split(";")
        OSRMFalso.maior_lote = max(OSRMFalso.maior_lote, len(coords))
        q = parse_qs(rota.query)

        if partes[0] == "route":
            corpo = {"code": "Ok", "routes": [{"geometry": {"coordinates": [
                [float(c.split(",")[0]), float(c.split(",")[1])] for c in coords]}}]}
        else:
            n_orig = len(q.get("sources", [""])[0].split(";")) if "sources" in q \
                else len(coords)
            n_dest = len(q.get("destinations", [""])[0].split(";")) if "destinations" in q \
                else len(coords)
            if OSRMFalso.sem_caminho:
                duracoes = [[None] * n_dest for _ in range(n_orig)]
            else:
                duracoes = [[(i + j + 1) * 60.0 for j in range(n_dest)]
                            for i in range(n_orig)]
            distancias = [[(i + j + 1) * 1000.0 for j in range(n_dest)]
                          for i in range(n_orig)]
            corpo = {"code": "Ok", "durations": duracoes, "distances": distancias}

        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


class BaseOSRM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), OSRMFalso)
        cls.porta = cls.servidor.server_address[1]
        cls.thread = threading.Thread(target=cls.servidor.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.porta}"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        OSRMFalso.requisicoes = 0
        OSRMFalso.maior_lote = 0
        OSRMFalso.falhar = False
        OSRMFalso.sem_caminho = False
        self.cache = tempfile.mkdtemp(prefix="mobgov-cache-")

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def provedor(self, **kw):
        kw.setdefault("cache_dir", self.cache)
        kw.setdefault("tentativas", 2)
        return osrm_mod.ProvedorOSRM(self.url, **kw)


class TestMatriz(BaseOSRM):
    def test_traz_tempo_e_distancia_da_malha(self):
        dist, tempo = self.provedor().matriz(PONTOS)
        self.assertEqual(len(dist), len(PONTOS))
        self.assertEqual(dist[0][0], 0.0)
        self.assertGreater(tempo[0][1], 0)
        self.assertGreater(dist[0][1], 0)

    def test_converte_unidades(self):
        """OSRM fala em segundos e metros; o sistema, em minutos e km."""
        dist, tempo = self.provedor().matriz(PONTOS)
        self.assertEqual(tempo[0][1], 2)      # (0+1+1)*60 s = 120 s = 2 min
        self.assertEqual(dist[0][1], 2.0)     # (0+1+1)*1000 m = 2 km

    def test_marca_a_origem_dos_tempos(self):
        p = self.provedor()
        p.matriz(PONTOS)
        self.assertEqual(p.ultima_origem, "osrm")

    def test_quebra_matriz_grande_em_blocos(self):
        muitos = [(-21.15 + 0.001 * i, -47.80 + 0.001 * i) for i in range(20)]
        p = self.provedor(bloco=5)
        dist, tempo = p.matriz(muitos)
        self.assertEqual(len(tempo), 20)
        self.assertEqual(OSRMFalso.requisicoes, 16)      # 4 blocos × 4 blocos
        self.assertLessEqual(OSRMFalso.maior_lote, 10)   # nunca estoura o limite
        for i in range(20):
            for j in range(20):
                if i != j:
                    self.assertGreater(tempo[i][j], 0, f"{i}→{j} vazio")

    def test_dois_pontos_ou_menos_nao_chama_o_servidor(self):
        p = self.provedor()
        p.matriz([PONTOS[0]])
        self.assertEqual(OSRMFalso.requisicoes, 0)


class TestCache(BaseOSRM):
    def test_segunda_chamada_vem_do_cache(self):
        p = self.provedor()
        primeira = p.matriz(PONTOS)
        chamadas = OSRMFalso.requisicoes
        segunda = p.matriz(PONTOS)
        self.assertEqual(primeira, segunda)
        self.assertEqual(OSRMFalso.requisicoes, chamadas)
        self.assertEqual(p.ultima_origem, "cache")

    def test_pontos_diferentes_nao_compartilham_cache(self):
        p = self.provedor()
        p.matriz(PONTOS)
        chamadas = OSRMFalso.requisicoes
        p.matriz([(lat + 1, lon) for lat, lon in PONTOS])
        self.assertGreater(OSRMFalso.requisicoes, chamadas)

    def test_cache_corrompido_nao_derruba(self):
        p = self.provedor()
        p.matriz(PONTOS)
        with open(p._caminho_cache(PONTOS), "w", encoding="utf-8") as f:
            f.write("{lixo")
        dist, tempo = p.matriz(PONTOS)
        self.assertGreater(tempo[0][1], 0)


class TestQuedaDoServidor(BaseOSRM):
    def test_cai_para_o_provedor_de_reserva(self):
        OSRMFalso.falhar = True
        p = self.provedor(fallback=ProvedorHaversine())
        dist, tempo = p.matriz(PONTOS)
        self.assertEqual(p.ultima_origem, "fallback")
        self.assertIsNotNone(p.ultimo_erro)
        self.assertGreater(tempo[0][1], 0)   # a operação continua

    def test_sem_reserva_o_erro_sobe(self):
        OSRMFalso.falhar = True
        p = self.provedor(fallback=None)
        with self.assertRaises(osrm_mod.ErroOSRM):
            p.matriz(PONTOS)

    def test_tenta_de_novo_antes_de_desistir(self):
        OSRMFalso.falhar = True
        p = self.provedor(fallback=ProvedorHaversine(), tentativas=3)
        p.matriz(PONTOS)
        self.assertGreaterEqual(OSRMFalso.requisicoes, 3)

    def test_ponto_fora_da_malha_vira_erro_explicito(self):
        OSRMFalso.sem_caminho = True
        p = self.provedor(fallback=None)
        with self.assertRaises(osrm_mod.ErroOSRM) as ctx:
            p.matriz(PONTOS)
        self.assertIn("fora da malha", str(ctx.exception))

    def test_sem_url_usa_reserva_e_explica(self):
        p = osrm_mod.ProvedorOSRM("", cache_dir=self.cache)
        p.matriz(PONTOS)
        self.assertEqual(p.ultima_origem, "fallback")
        self.assertIn("MOBGOV_OSRM_URL", p.ultimo_erro)

    def test_disponivel(self):
        self.assertTrue(self.provedor().disponivel())
        OSRMFalso.falhar = True
        self.assertFalse(self.provedor().disponivel())


class TestGeometria(BaseOSRM):
    def test_traz_o_tracado_da_rua(self):
        linha = self.provedor().geometria_rota(PONTOS[:3])
        self.assertEqual(len(linha), 3)
        self.assertAlmostEqual(linha[0][0], PONTOS[0][0], places=5)

    def test_sem_servidor_devolve_a_poligonal(self):
        p = osrm_mod.ProvedorOSRM("", cache_dir=self.cache)
        self.assertEqual(p.geometria_rota(PONTOS[:3]), PONTOS[:3])


class TestProvedorPadraoComOSRM(BaseOSRM):
    def test_variavel_de_ambiente_liga_o_osrm(self):
        from dados import tempos
        os.environ["MOBGOV_OSRM_URL"] = self.url
        try:
            p = tempos.provedor_padrao()
            self.assertIsInstance(p, tempos.ComTransito)
            self.assertIsInstance(p.base, osrm_mod.ProvedorOSRM)
            p_sem = tempos.provedor_padrao(com_transito=False)
            self.assertIsInstance(p_sem, osrm_mod.ProvedorOSRM)
        finally:
            del os.environ["MOBGOV_OSRM_URL"]

    def test_osrm_com_transito_proprio_dispensa_o_perfil(self):
        from dados import tempos
        os.environ["MOBGOV_OSRM_URL"] = self.url
        os.environ["MOBGOV_OSRM_COM_TRANSITO"] = "0"
        try:
            self.assertIsInstance(tempos.provedor_padrao(),
                                  osrm_mod.ProvedorOSRM)
        finally:
            del os.environ["MOBGOV_OSRM_URL"]
            del os.environ["MOBGOV_OSRM_COM_TRANSITO"]

    def test_sem_variavel_continua_offline(self):
        from dados import tempos
        os.environ.pop("MOBGOV_OSRM_URL", None)
        p = tempos.provedor_padrao()
        self.assertIsInstance(p.base, tempos.ProvedorHaversine)


if __name__ == "__main__":
    unittest.main()
