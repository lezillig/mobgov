# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 8 · agent-qa-demo
Gera versões ESTÁTICAS dos dois apps, para abrir com duplo clique.

Os apps de verdade conversam com `operacao/servidor.py`. Numa apresentação
nem sempre dá para subir servidor — o notebook é da prefeitura, a porta está
bloqueada, o wi-fi é de visitante. Estes arquivos resolvem isso: o mesmo HTML,
o mesmo CSS, o mesmo JavaScript, com uma casca que responde às chamadas de API
a partir de dados embutidos no próprio arquivo.

Duas regras que este gerador respeita, e que não são detalhe:

1. **o app não é reescrito.** O HTML entra inteiro; a casca só intercepta
   `fetch`. Se a tela da demonstração funciona, é porque o app funciona — e
   não porque existe uma segunda versão dele feita para a plateia;
2. **a tela diz que é demonstração**, com faixa visível no topo. Ninguém pode
   sair da sala achando que viu um veículo real na rua.

Uso:
    python docs/demonstracao/gerar_apps_estaticos.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from operacao import onde_esta, rota_do_dia as rotas  # noqa: E402
from operacao.servidor import vinculos_de_demonstracao  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
DIR_OPERACAO = os.path.join(DIR, "..", "..", "operacao")
DIR_SAUDE = os.path.join(DIR, "..", "..", "saude")

FAIXA = """
<div style="position:sticky;top:0;z-index:99;background:#E8A24E;color:#1A1206;
  font:700 13px/1.35 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,
  sans-serif;padding:9px 14px;text-align:center;letter-spacing:.02em">
  DEMONSTRAÇÃO — dados embutidos neste arquivo, sem servidor e sem internet
</div>
"""

CASCA = """
<script>
/* Casca de demonstração: responde às chamadas de API com dados embutidos.
   O app abaixo não sabe que ela existe — é o mesmo código que fala com
   operacao/servidor.py numa operação de verdade. */
(function () {
  "use strict";
  var DADOS = %s;
  var estado = {falta: false, paciente_nao_vai: false,
                paciente_liberado: false};

  function resposta(corpo) {
    return Promise.resolve({
      ok: true, status: 200,
      json: function () { return Promise.resolve(corpo); }
    });
  }

  var original = window.fetch;
  window.fetch = function (url, opcoes) {
    var caminho = String(url).split("?")[0];
    if (caminho === "/api/rota-do-dia") { return resposta(DADOS.rota); }
    if (caminho === "/api/situacao") {
      return resposta(estado.falta ? DADOS.situacao_com_falta : DADOS.situacao);
    }
    if (caminho === "/api/falta") {
      estado.falta = true;
      return resposta({registrado: "falta"});
    }
    if (caminho === "/api/desfazer-falta") {
      estado.falta = false;
      return resposta({registrado: "volta_atras"});
    }
    /* app do paciente: as três ações mudam o mesmo estado local, e a tela
       se redesenha sozinha — igual ao app de verdade */
    if (caminho === "/api/minha-viagem") {
      return resposta(estado.paciente_liberado ? DADOS.paciente_liberado
        : (estado.paciente_nao_vai ? DADOS.paciente_nao_vai
                                   : DADOS.paciente));
    }
    if (caminho === "/api/nao-vou") {
      estado.paciente_nao_vai = true;
      return resposta({ok: true});
    }
    if (caminho === "/api/desfazer") {
      estado.paciente_nao_vai = false;
      return resposta({ok: true});
    }
    if (caminho === "/api/liberado") {
      estado.paciente_liberado = true;
      return resposta({ok: true});
    }
    if (caminho === "/api/eventos") {
      var corpo = {};
      try { corpo = JSON.parse((opcoes || {}).body || "{}"); } catch (e) {}
      return resposta({aceitos: (corpo.eventos || []).length, recusados: []});
    }
    return original ? original.apply(window, arguments)
                    : Promise.reject(new Error("sem rede"));
  };
})();
</script>
"""


def _montar(nome_arquivo: str, dados: dict, saida: str,
            diretorio: str = None) -> str:
    with open(os.path.join(diretorio or DIR_OPERACAO, nome_arquivo),
              encoding="utf-8") as f:
        html = f.read()
    # a casca precisa existir ANTES do script do app, que dispara no carregamento
    html = html.replace("<body>", "<body>" + FAIXA
                        + CASCA % json.dumps(dados, ensure_ascii=False), 1)
    caminho = os.path.join(DIR, saida)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return caminho


def _eventos_de_hoje(viagem: dict, paradas: list, atraso_min: int = 3) -> list:
    """Um embarque na primeira parada, com atraso plausível.

    É o que faz a previsão do app da família aparecer como MEDIDA — que é
    justamente o ponto da tela na apresentação.
    """
    hora, minuto = paradas[0]["hora_prevista"].split("h")
    quando = (int(hora) * 60 + int(minuto) + atraso_min) % (24 * 60)
    return [{"tipo": "embarque", "motorista": viagem["veiculo"],
             "viagem": viagem["id"], "ponto": paradas[0]["ponto"],
             "em": f"{date.today().isoformat()}T"
                   f"{quando // 60:02d}:{quando % 60:02d}:00"}]


def main():
    plano = rotas.carregar_plano()
    if not plano:
        raise SystemExit("Sem relatorios/dimensionamento.json — rode antes: "
                         "python motor/dimensionar.py")

    viagens = plano["frota_otimizada"]["viagens"]
    vinculos = vinculos_de_demonstracao(plano)
    # o vínculo bom para a demonstração é o de um ponto do MEIO da viagem:
    # é o que já tem embarque antes dele, e portanto previsão medida
    vinculo = next(v for v in vinculos
                   if v["ponto"] != next(t for t in viagens
                                         if v["ponto"] in t["paradas"])["paradas"][0])
    viagem = next(t for t in viagens if vinculo["ponto"] in t["paradas"])
    motorista = viagem["veiculo"]

    rota = rotas.rota_do_dia(motorista, plano)
    dados_viagem = next(t for t in rota["viagens"] if t["viagem"] == viagem["id"])
    eventos = _eventos_de_hoje(viagem, dados_viagem["paradas"])

    situacao = onde_esta.situacao(vinculo, plano, eventos)
    com_falta = onde_esta.situacao(
        vinculo, plano,
        eventos + [{"tipo": "falta", "aluno": vinculo["aluno"],
                    "ponto": vinculo["ponto"], "viagem": viagem["id"],
                    "em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}])

    paciente_html = _gerar_app_do_paciente()

    motorista_html = _montar("app_motorista.html", {"rota": rota},
                             "app-motorista-demo.html")
    familia_html = _montar("app_responsavel.html",
                           {"situacao": situacao,
                            "situacao_com_falta": com_falta},
                           "app-responsavel-demo.html")

    print(f"App do motorista:   {motorista_html}")
    print(f"  {motorista} · {len(rota['viagens'])} viagens · "
          f"{rota['total_alunos']} alunos")
    print(f"App do responsável: {familia_html}")
    print(f"  ponto {vinculo['ponto']} · previsão {situacao['previsao']} "
          f"({situacao['origem_da_previsao']})")
    if paciente_html:
        print(f"App do paciente:    {paciente_html}")
    return 0


def _gerar_app_do_paciente():
    """O app do transporte sanitário, com os três estados que ele tem.

    Escolhe um tratamento de volta POR CHAMADA de propósito: é ele que mostra
    o botão "já fui liberado", que é a parte do app que não existe em nenhum
    outro sistema.
    """
    from saude import acompanhamento as ac
    from saude import demanda as demanda_saude

    tratamentos = demanda_saude.gerar_tratamentos()
    escolhido = next((t for t in tratamentos
                      if not t.retorno_previsivel and t.dias_da_semana), None)
    if not escolhido:
        return None
    dia_da_semana = escolhido.dias_da_semana[0]
    dia = date.today().isoformat()
    comum = dict(dia_da_semana=dia_da_semana, dia=dia,
                 tratamentos=tratamentos, agora_min=escolhido.hora_chegada_min
                 - 90)

    def com(eventos):
        d = ac.situacao(escolhido.paciente_id, eventos=eventos, **comum)
        d["demonstracao"] = True
        return d

    aviso = {"tipo": "nao_vou", "paciente": escolhido.paciente_id,
             "em": f"{dia}T06:00:00"}
    liberacao = {"tipo": "liberado", "paciente": escolhido.paciente_id,
                 "em": f"{dia}T11:30:00"}
    return _montar("app_paciente.html",
                   {"paciente": com([]),
                    "paciente_nao_vai": com([aviso]),
                    "paciente_liberado": com([liberacao])},
                   "app-paciente-demo.html", DIR_SAUDE)


if __name__ == "__main__":
    sys.exit(main())
