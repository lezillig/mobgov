# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-qa-demo
Gera TODAS as telas do sistema em HTML estático, para abrir com duplo clique.

O sistema tem telas de três naturezas, e só uma delas é arquivo por natureza:

    relatório     painel de economia e proposta — já nascem arquivo
    console       a tela de operação — gerada pelo servidor a cada abertura
    aplicação     planejamento, app do motorista e app do responsável — falam
                  com um servidor por HTTP

Aqui as três viram arquivo. As aplicações ganham uma casca que responde às
chamadas de API com dados embutidos: o HTML e o JavaScript são os mesmos que
rodam de verdade — se a tela funciona aqui, é porque a tela funciona.

Cada arquivo leva uma faixa dizendo que é demonstração. Ninguém pode sair da
sala achando que viu um veículo real na rua.

Uso:
    python docs/demonstracao/gerar_telas_estaticas.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from comercial import diagnostico as diagnostico_mod  # noqa: E402
from comercial import operacao_atual as operacao_mod  # noqa: E402
from comercial import precificacao as precificacao_mod  # noqa: E402
from comercial.precificacao import Premissas  # noqa: E402
from docs.demonstracao import gerar_apps_estaticos as apps  # noqa: E402
from painel import console as console_mod  # noqa: E402
from painel import render as render_mod  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
DIR_BASE = os.path.dirname(os.path.dirname(DIR))
DIR_RELATORIOS = os.path.join(DIR_BASE, "relatorios")
DIR_SAIDA = os.path.join(DIR, "telas")

PLANO_FRETAMENTO = os.path.join(DIR_RELATORIOS, "plano-fretamento.json")
RASCUNHO = os.path.join(DIR_RELATORIOS, "planejamento", "rascunho.json")
LINHAS_ATUAIS = os.path.join(DIR, "linhas-atuais-demo.csv")


def _casca_do_planejamento(estado: dict) -> str:
    """Responde às chamadas da tela de planejamento com o estado já pronto."""
    return """
<script>
/* Casca de demonstração: a tela de planejamento abaixo é a de verdade, com
   o mesmo JavaScript. O que muda é que o /api/... responde daqui, com um
   planejamento já feito, em vez de rodar o solver na hora. */
(function () {
  "use strict";
  var ESTADO = %s;
  function resposta(corpo) {
    return Promise.resolve({ok: true, status: 200,
      json: function () { return Promise.resolve(corpo); }});
  }
  var original = window.fetch;
  window.fetch = function (url, opcoes) {
    var caminho = String(url).split("?")[0];
    if (caminho === "/api/estado") { return resposta(ESTADO); }
    if (caminho === "/api/enviar-planilha") {
      var imp = JSON.parse(JSON.stringify(ESTADO.importacao));
      imp.perfil = ESTADO.perfil;
      return resposta(imp);
    }
    if (caminho === "/api/ajustar") { return resposta({ok: true, faltam: 0}); }
    if (caminho === "/api/roteirizar") { return resposta({iniciado: true}); }
    if (caminho === "/api/precificar") { return resposta(ESTADO.preco); }
    if (caminho === "/api/enviar-linhas") { return resposta(ESTADO.diagnostico); }
    if (caminho === "/api/publicar") {
      return resposta({publicado: true, veiculos: ESTADO.plano.frota.total,
                       viagens: ESTADO.plano.viagens,
                       mensagem: "Demonstração: nada foi publicado de verdade."});
    }
    return original ? original.apply(window, arguments)
                    : Promise.reject(new Error("sem rede"));
  };
  window.open = function () {
    alert("Nesta demonstração a proposta é o arquivo proposta.html, ao lado.");
  };
})();
</script>
""" % json.dumps(estado, ensure_ascii=False)


def _montar_estado_do_planejamento() -> dict:
    """Reaproveita o que já foi calculado — não roda solver de novo."""
    from planejamento import servidor as servidor_mod

    with open(PLANO_FRETAMENTO, encoding="utf-8") as f:
        plano = json.load(f)
    with open(RASCUNHO, encoding="utf-8") as f:
        importacao = json.load(f)

    servidor_mod.ESTADO.importacao = importacao
    servidor_mod.ESTADO.plano = plano
    from dados import perfis as perfis_mod
    servidor_mod.ESTADO.perfil = perfis_mod.PERFIL_FRETAMENTO

    premissas = Premissas()
    preco = precificacao_mod.precificar(plano, premissas)
    preco["cenarios"] = precificacao_mod.sensibilidade(plano, premissas)

    tipos = plano["premissas"]["custos_por_tipo"]
    lido = operacao_mod.importar(LINHAS_ATUAIS, tipos)
    diagnostico = diagnostico_mod.diagnosticar(lido["linhas"], plano)
    diagnostico["problemas_da_planilha"] = lido["problemas"][:6]

    return {
        "importacao": servidor_mod.ESTADO.resumo_da_importacao(),
        "rodando": False, "erro": "",
        "progresso": [
            {"em": "09:12:04", "etapa": "agrupando",
             "detalhe": "339 colaboradores em pontos de embarque"},
            {"em": "09:12:05", "etapa": "agrupado",
             "detalhe": "229 pontos · 3 plantas"},
            {"em": "09:13:41", "etapa": "escalado",
             "detalhe": "1º turno (06h): 7 viagens em 6 veículos"},
            {"em": "09:14:52", "etapa": "equipe",
             "detalhe": "16 motoristas para 36 blocos de trabalho"},
            {"em": "09:14:52", "etapa": "concluido", "detalhe": "7 veículos"},
        ],
        "plano": servidor_mod._plano_resumido(plano),
        "perfil": servidor_mod.ESTADO.perfil_em_dicionario(),
        "equipe": plano.get("equipe"),
        "preco": preco,
        "diagnostico": diagnostico,
        "linhas_atuais": len(lido["linhas"]),
        "publicado": False,
    }


def gerar_planejamento() -> str:
    with open(os.path.join(DIR_BASE, "planejamento", "tela.html"),
              encoding="utf-8") as f:
        html = f.read()
    estado = _montar_estado_do_planejamento()
    html = html.replace("<body>", "<body>" + apps.FAIXA
                        + _casca_do_planejamento(estado), 1)
    caminho = os.path.join(DIR_SAIDA, "3-planejamento.html")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return caminho


def gerar_consoles() -> list:
    saidas = []
    for rotulo, plano, nome in (
            ("escolar", None, "1-console-escolar.html"),
            ("fretamento", PLANO_FRETAMENTO, "2-console-fretamento.html")):
        html, _ = console_mod.montar_html(plano)
        caminho = os.path.join(DIR_SAIDA, nome)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(html)
        saidas.append(caminho)
    return saidas


INDICE = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOBGOV — o sistema, tela por tela</title>
<style>
:root{--papel:#FFF;--papel-2:#F4F7F9;--tinta:#0E1D27;--fraca:#4E6273;
  --linha:#D3DDE4;--institucional:#123E6B}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--papel-2);color:var(--tinta);font-size:17px;line-height:1.5;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
header{background:var(--papel);border-bottom:3px solid var(--institucional);
  padding:26px 0}
.folha{max-width:960px;margin:0 auto;padding:0 22px}
.produto{font-weight:800;letter-spacing:.08em;color:var(--institucional)}
h1{font-size:27px;margin-top:6px}
p.sub{color:var(--fraca);margin-top:6px}
main{padding:26px 0 70px}
.grupo{margin-bottom:30px}
.grupo h2{font-size:16px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--fraca);margin-bottom:12px}
a.tela{display:block;background:var(--papel);border:1px solid var(--linha);
  border-radius:14px;padding:18px 20px;margin-bottom:12px;text-decoration:none;
  color:inherit}
a.tela:hover{border-color:var(--institucional)}
a.tela b{font-size:18px;color:var(--institucional)}
a.tela span{display:block;color:var(--fraca);font-size:15px;margin-top:4px}
.nota{background:#FCF3DF;border-left:4px solid #8A5A00;border-radius:0 12px 12px 0;
  padding:14px 16px;margin:22px 0;font-size:15px}
</style></head><body>
<header><div class="folha">
  <div class="produto">MOBGOV</div>
  <h1>O sistema, tela por tela</h1>
  <p class="sub">Todas as telas abrem sem internet e sem servidor. As de
  aplicação levam dados embutidos — o HTML e o JavaScript são os mesmos que
  rodam de verdade.</p>
</div></header>
<main><div class="folha">
%s
  <div class="nota"><b>O que é demonstração:</b> os dados são do município e
  da empresa fictícios do projeto. O mecanismo é o real — roteirização,
  escala de motoristas, precificação e diagnóstico foram calculados por estas
  mesmas funções antes de a página ser escrita.</div>
</div></main></body></html>
"""

TELAS = [
    ("Operação do dia", [
        ("1-console-escolar.html", "Console de operação — escolar",
         "O que está acontecendo hoje, a fila de elegibilidade ao porta a "
         "porta, o assistente e o resumo da economia."),
        ("2-console-fretamento.html", "Console de operação — fretamento",
         "O mesmo console para uma operação de empresa, com a aba Equipe: "
         "16 motoristas, jornada de cada um e as regras usadas."),
    ]),
    ("Planejamento e comercial", [
        ("3-planejamento.html", "Planejamento: da planilha às rotas",
         "Os sete passos: enviar a planilha, conferir, ajustar no mapa, "
         "roteirizar, publicar, precificar e comparar com a operação atual."),
        ("4-proposta.html", "Proposta comercial",
         "O preço com a planilha de custo aberta, os cenários e o "
         "diagnóstico da operação que já roda."),
        ("5-painel-economia.html", "Painel de economia",
         "O relatório que vira PDF de prestação de contas: antes e depois, "
         "mapa, premissas e memória de cálculo."),
    ]),
    ("Quem está na rua", [
        ("6-app-motorista.html", "App do motorista",
         "Offline-first: a rota do dia no aparelho, embarque por parada e "
         "fila local que sobe sozinha quando volta o sinal."),
        ("7-app-responsavel.html", "App do responsável",
         "Onde está o ônibus, com a previsão marcada como medida ou "
         "planejada — e o aviso de falta, que alimenta o aprendizado."),
    ]),
]


def gerar_indice() -> str:
    grupos = []
    for titulo, telas in TELAS:
        itens = "".join(
            f'  <a class="tela" href="{arquivo}"><b>{nome}</b>'
            f'<span>{descricao}</span></a>\n'
            for arquivo, nome, descricao in telas
            if os.path.exists(os.path.join(DIR_SAIDA, arquivo)))
        if itens:
            grupos.append(f'  <div class="grupo"><h2>{titulo}</h2>\n{itens}</div>')
    caminho = os.path.join(DIR_SAIDA, "index.html")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(INDICE % "\n".join(grupos))
    return caminho


def main():
    os.makedirs(DIR_SAIDA, exist_ok=True)
    feitas = []

    feitas += gerar_consoles()
    feitas.append(gerar_planejamento())

    for origem, destino in (("proposta.html", "4-proposta.html"),
                            ("painel-economia.html", "5-painel-economia.html")):
        caminho = os.path.join(DIR_RELATORIOS, origem)
        if origem == "painel-economia.html" and not os.path.exists(caminho):
            render_mod.gerar(saida=caminho)
        if os.path.exists(caminho):
            alvo = os.path.join(DIR_SAIDA, destino)
            shutil.copyfile(caminho, alvo)
            feitas.append(alvo)

    # os dois apps já têm gerador próprio; aqui só se copia para a mesma pasta
    apps.main()
    for origem, destino in (("app-motorista-demo.html", "6-app-motorista.html"),
                            ("app-responsavel-demo.html",
                             "7-app-responsavel.html")):
        caminho = os.path.join(DIR, origem)
        if os.path.exists(caminho):
            alvo = os.path.join(DIR_SAIDA, destino)
            shutil.copyfile(caminho, alvo)
            feitas.append(alvo)

    indice = gerar_indice()
    print(f"{len(feitas)} telas em {DIR_SAIDA}")
    for caminho in feitas:
        print(f"  {os.path.basename(caminho)}")
    print(f"Comece por {indice}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
