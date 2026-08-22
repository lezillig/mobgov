# Sprint 7 — Conversa, elegibilidade, rodadas e app da família · resumo executivo

*MOBGOV · MVP para governos*

## O que avançou

Quatro frentes. As três primeiras vieram do benchmarking (Optibus, RideCo,
Spare); a quarta fecha o ciclo do aprendizado, que até aqui tinha um buraco
declarado.

1. **Camada conversacional** — perguntar ao sistema em português e receber o
   mesmo número que está no painel.
2. **Elegibilidade ao porta a porta sem papel** — o processo que hoje leva
   meses vira formulário, leitura assistida e decisão humana registrada.
3. **Reotimização contínua em rodadas** — o plano do dia é revisto de tempos
   em tempos, e uma corrida pode mudar de veículo enquanto ainda dá tempo.
4. **App do responsável** — "onde está o ônibus" e o aviso de falta, que é a
   origem real da taxa de ausência.

Antes disso, na mesma sprint: a **planilha de demonstração** (300 alunos com a
bagunça de sempre) e a correção que ela expôs no leitor de `.xlsx`.

## 1. Camada conversacional (`conversa/`)

O gestor pergunta "quanto eu economizo por mês?" e recebe a resposta com os
números do motor. A regra que organiza o módulo inteiro:

> **O modelo de linguagem escolhe a ferramenta e escreve a frase. O número sai
> do Python.**

Nove ferramentas (indicadores, frota, cenário, rota, operação, importação,
elegibilidade, aprendizado, relatório), expostas no formato de tool use da
API. Três garantias de engenharia:

- **funciona sem internet.** Um roteador por palavra-chave escolhe a mesma
  ferramenta e um redator escreve a resposta em pt-BR. Na sala da prefeitura,
  com wi-fi de visitante, a demonstração não depende de crédito de API;
- **auditoria dos números.** Toda resposta escrita pelo modelo passa por
  `auditar_numeros`, que confere cada valor contra o que as ferramentas
  devolveram — aceitando reescrita ("R$ 1,69 mi" é 1.693.467,84 dito de outro
  jeito) e reprovando invenção. Resposta reprovada é substituída pela versão
  determinística, e o valor errado não é repetido na tela;
- **queda automática.** Sem chave, sem rede, ou com o modelo chamando
  ferramenta sem concluir, o assistente responde offline com o motivo.

```
$ python conversa/cli.py --offline "por que preciso de tantos ônibus?"
Frota que o município declara hoje: …
A frota necessária é 23 veículos porque cada um encadeia 2,61 viagens por
turno dentro da jornada disponível antes do sinal…
```

## 2. Elegibilidade sem papel (`elegibilidade/`)

Como é hoje: a família consegue um laudo, tira cópia, vai até a secretaria,
protocola, espera sem informação e, no ano seguinte, repete tudo — inclusive
quando a condição é permanente.

O que entra no lugar, sem tirar a decisão de quem tem que decidir:

| Peça | O que faz |
|---|---|
| `formulario.py` | Perguntas em língua de família ("a pessoa consegue ir sozinha até um ponto a 300 m de casa?"), campos condicionais, validação explicada |
| `perfil.py` | Traduz as respostas em restrição operacional e calcula tempo de parada, assentos, posições de cadeira e exigências do veículo |
| `extracao.py` | Lê o documento anexado e **sugere** campos, cada um com o trecho literal que o sustenta e a confiança |
| `fila.py` | Estados, prazo de 15 dias, histórico append-only e concessão com validade |

Três regras que o código impõe, e não confia:

- **diagnóstico não roteiriza; necessidade roteiriza.** CID e laudo ficam no
  processo; o que chega ao motor é restrição operacional com identificador
  pseudonimizado. Duas pessoas com o mesmo CID podem precisar de coisas
  opostas;
- **nada entra no perfil sem alguém marcar.** Confiança de 0,95 ordena a tela,
  não decide. E, no modo com IA, sugestão cujo trecho não está no documento é
  descartada — alucinação sobre laudo é grave;
- **aprovar exige nome e evidência; negar exige justificativa escrita.** As
  três coisas levantam erro quando faltam. Negativa sem motivo é o que faz a
  família recorrer no escuro.

Concessão marcada como permanente não vence; as temporárias entram no aviso de
renovação 30 dias antes, para ninguém descobrir que perdeu o direito no dia em
que o veículo não encostou na porta.

## 3. Reotimização contínua (`motor/rodadas.py`)

O módulo anterior responde a um acontecimento — resolve o telefonema. Este
revê o plano inteiro de tempos em tempos: aplica as faltas, encaixa os pedidos
novos na rota mais barata de todas e faz *ruin & recreate* (tira os pedidos de
maior desvio e reinsere cada um onde ficar mais barato, inclusive em outro
veículo).

O que ele se recusa a fazer é o que o torna utilizável:

- **horizonte de compromisso (20 min)**: quem já embarcou ou embarca dentro
  desse prazo não é remarcado;
- **janela de aviso (60 min)**: o horário vira firme perto da hora; daí em
  diante só muda dentro da tolerância. Pedido novo que atrasaria horário firme
  é recusado com o motivo escrito, mesmo cabendo em quilômetros;
- **ganho mínimo**: mexer na rota por duzentos metros é retrabalho de despacho
  sem retorno;
- **descarte inteiro**: se a reconstrução não fecha ou quebra promessa, a
  rodada devolve o plano anterior.

Manhã simulada (6h às 9h, rodada a cada 5 min): **37 rodadas, 50,0 km
economizados** (15,0 deles por remanejar corrida entre veículos), 6 faltas
absorvidas, 4 de 8 pedidos novos aceitos, 3 corridas trocaram de veículo,
**0 horários combinados quebrados**, resposta máxima de **0,097 s**.

Cada informação entra na rodada em que chegaria de verdade — decidir sabendo
o dia inteiro de antemão é fácil e não é a realidade.

## 4. App do responsável (`operacao/app_responsavel.html`)

Uma tela, letra grande, três ações: ver a previsão, avisar que hoje não vai,
desfazer o aviso.

- **a previsão tem origem declarada**: `medido` quando houve embarque anterior
  ou ping do veículo hoje, `planejado` quando não houve — e a tela diz qual é,
  com selo. Prometer "chega em 3 minutos" sem saber custa a confiança da
  família na primeira vez;
- **o token assina aluno + ponto + turno**: trocar o `?ponto=` da URL não abre
  a rota de outra criança;
- **vale o último aviso do dia**: quem avisou e depois desdisse não é falta —
  contar como falta faria o veículo passar direto pela criança no ponto.

E é daqui que sai a **taxa de ausência**, a última coisa do aprendizado que
continuava estimada. `aprendizado/ingestao.faltas_observadas` converte os
avisos em observação por viagem e por dia; `taxa_de_ausencia` devolve `None`
antes de cinco dias, porque dia sem aviso não é dia sem falta — é dia sem
informação.

## Correções que a própria demonstração encontrou

- **Linha vazia some do XML do Excel.** Uma linha em branco no meio da
  planilha deslocava toda a numeração seguinte, e o "conserte a linha 88" do
  relatório de importação mandava o servidor para a linha errada. O leitor
  agora respeita o atributo `r` do `<row>`.
- **Evidência cortada no ponto do CID.** O trecho que sustenta uma sugestão
  começava em "1), não deambula…" porque o ponto de "CID G80.1" era tratado
  como fim de frase.
- **"878 min atrasado" escrito com toda a confiança.** Um embarque com horário
  de outro turno virava previsão na tela da família. Divergência acima de 120
  minutos agora volta ao horário planejado e explica por quê.
- **Encaixe de pedido novo atropelando horário combinado.** A conferência de
  promessa passou a rodar também na aceitação do pedido, e não só no
  remanejamento.

## Situação

314 testes passando, biblioteca padrão (OR-Tools só no motor). Painel com dois
blocos novos — elegibilidade e rodadas —, cada um declarando a origem do dado.
