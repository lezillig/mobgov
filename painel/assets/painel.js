/* MOBGOV — Painel de Economia (Sprint 2)
   O simulador NÃO faz conta: ele apenas seleciona um cenário já calculado
   pelo motor (painel/economia.py) e embutido na página. Regra do projeto —
   todo número exibido sai do motor, nunca do navegador.
   A página funciona sem JavaScript: sem ele, ficam na tela os números do
   cenário padrão, já renderizados no servidor. */
(function () {
  "use strict";

  var fonte = document.getElementById("dados-cenarios");
  if (!fonte) return;

  var cenarios;
  try {
    cenarios = JSON.parse(fonte.textContent);
  } catch (e) {
    return;
  }
  if (!cenarios || !cenarios.length) return;

  var precos = [], dias = [];
  cenarios.forEach(function (c) {
    if (precos.indexOf(c.preco_diesel_l) < 0) precos.push(c.preco_diesel_l);
    if (dias.indexOf(c.dias_letivos_mes) < 0) dias.push(c.dias_letivos_mes);
  });
  precos.sort(function (a, b) { return a - b; });
  dias.sort(function (a, b) { return a - b; });

  var moeda = new Intl.NumberFormat("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0
  });
  var moedaCentavos = new Intl.NumberFormat("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2
  });
  var decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

  var elPreco = document.getElementById("controle-diesel");
  var elDias = document.getElementById("controle-dias");
  var painelControles = document.querySelector(".controles");
  if (!elPreco || !elDias) return;

  elPreco.max = precos.length - 1;
  elDias.max = dias.length - 1;

  var padrao = cenarios.filter(function (c) { return c.padrao; })[0] || cenarios[0];
  elPreco.value = precos.indexOf(padrao.preco_diesel_l);
  elDias.value = dias.indexOf(padrao.dias_letivos_mes);

  function escreve(id, texto) {
    var el = document.getElementById(id);
    if (el) el.textContent = texto;
  }

  function atualiza() {
    var preco = precos[Number(elPreco.value)];
    var d = dias[Number(elDias.value)];
    var c = cenarios.filter(function (x) {
      return x.preco_diesel_l === preco && x.dias_letivos_mes === d;
    })[0];
    if (!c) return;

    escreve("leitura-diesel", moedaCentavos.format(c.preco_diesel_l) + "/litro");
    escreve("leitura-dias", c.dias_letivos_mes + " dias letivos/mês");
    escreve("cen-economia-mes", moeda.format(c.economia_mes));
    escreve("cen-economia-ano", moeda.format(c.economia_ano));
    escreve("cen-custo-atual", moeda.format(c.custo_atual_mes));
    escreve("cen-custo-otim", moeda.format(c.custo_otimizado_mes));
    escreve("cen-reducao", decimal.format(c.reducao_custo_pct) + "%");
    escreve("cen-situacao", c.padrao
      ? "Cenário base do relatório."
      : "Cenário simulado — o relatório oficial acima usa o cenário base.");
  }

  elPreco.addEventListener("input", atualiza);
  elDias.addEventListener("input", atualiza);
  if (painelControles) painelControles.removeAttribute("hidden");
  var semJs = document.querySelector(".sem-js");
  if (semJs) semJs.remove();
  atualiza();

  var botao = document.getElementById("botao-pdf");
  if (botao) {
    botao.addEventListener("click", function () { window.print(); });
    botao.removeAttribute("hidden");
  }
})();
