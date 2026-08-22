# O sistema remodelado — por pessoa e por momento

*MOBGOV · proposta de arquitetura de informação e experiência*

## O que estava errado

A organização atual espelha o organograma do código, não o trabalho de quem
usa:

| Menu de hoje | O que ele é de verdade |
|---|---|
| Console (4 abas) | os módulos que existiam quando ele foi feito |
| Planejamento (7 passos) | as etapas do algoritmo, numeradas |
| Comercial (CLI) | um módulo que ninguém acha |
| Painel de economia | um relatório com cara de tela |

Três sintomas disso:

1. **o usuário precisa saber onde as coisas moram.** "A fila do porta a porta
   está no console; o mapa, no planejamento; o preço, no terminal";
2. **nada diz o que fazer agora.** A tela abre cheia de números certos e
   nenhuma frase do tipo "5 famílias esperam sua decisão há mais de 15 dias";
3. **os 7 passos numerados travam.** Passo é do algoritmo. O servidor real
   entra, ajusta 20 endereços, é interrompido, volta amanhã — e um fluxo
   numerado não perdoa isso.

## O modelo novo

Três destinos e um começo. O critério não é "que módulo é isso", é **quem
está usando e em que momento**.

```
     Início            Planejar             Operar              Vender
  "o que precisa    "da planilha às     "o dia acontecendo"  "quanto custa,
   de você agora"     rotas"                                  por quanto vender"
  ─────────────    ────────────────     ─────────────────    ───────────────
   pendências       dados → mapa →        rotas de hoje        proposta
   com dono e       rotas → publicar      avisos das           diagnóstico do
   ação             trilha com estado     famílias             que já roda
                    salva sozinha         reotimizações
```

**Quem usa cada um:** o secretário e o dono da operação vivem no Início; o
analista de planejamento, em Planejar; o despachante, em Operar; o comercial,
em Vender. Ninguém precisa entrar onde não trabalha — mas tudo continua a um
clique, porque em município pequeno é a mesma pessoa fazendo os quatro.

## Os sete princípios aplicados

1. **Comece pela pendência, não pelo painel.** A tela inicial é uma lista de
   coisas que precisam de decisão humana, cada uma com quem decide, há quanto
   tempo espera e o botão que resolve. Números de contexto vêm depois.

2. **Trilha, não passos numerados.** Planejar mostra quatro marcos com estado
   (*pronto · precisa de você · esperando*), e dá para entrar por qualquer um.
   O rascunho é salvo sozinho: sair no meio é comportamento previsto, não erro.

3. **Todo número diz de onde veio.** Um selo, sempre no mesmo lugar:
   `medido` (veio do GPS ou do app), `planejado` (saiu do motor),
   `informado` (veio da planilha de quem opera), `simulado` (demonstração).
   É a regra que já existia no código; aqui ela vira componente visual, e não
   parágrafo de rodapé.

4. **Explicação sob demanda.** Cada número tem "por quê?" que abre a memória
   de cálculo no lugar. Quem confia, segue; quem precisa auditar, abre.

5. **Linguagem de quem usa.** "Quantos ônibus eu preciso?", não
   "dimensionamento de frota". "Hoje ele(a) não vai", não "registro de
   ausência". O termo técnico fica na documentação e no código.

6. **Erro é ponto de partida, não beco.** Cada problema aparece com a ação ao
   lado: 78 endereços sem coordenada viram um botão "ajustar no mapa", não um
   alerta vermelho.

7. **Ninguém publica sem saber o que muda.** Ações que afetam gente na rua
   (publicar rota, aprovar concessão, recusar pedido) dizem antes o tamanho do
   efeito: "vai trocar a rota de 7 veículos e 21 viagens".

## Experiência de quem está na ponta (CX)

O sistema tem dois públicos que não escolheram usá-lo: a família e o
motorista. Para eles, a régua é outra — confiança, não eficiência.

- **nunca prometer o que não se sabe.** A previsão do app da família diz se é
  medição ou horário de plano, com selo. Errar uma vez custa a confiança do
  ano;
- **dar controle onde ele existe.** "Hoje ele(a) não vai" é desfazível
  enquanto o veículo não passou — porque a mãe muda de ideia, e o sistema
  precisa acompanhar a vida real;
- **falar com quem espera.** Pedido de porta a porta mostra prazo, situação e
  o que falta — a fila sem informação é o que faz a família ligar três vezes
  por semana para a secretaria.

## O que muda na prática

| Antes | Depois |
|---|---|
| 4 abas de módulo | 4 destinos por momento de trabalho |
| passos 1–7 numerados | trilha com estado, entrando por onde precisar |
| KPIs no topo | pendências no topo, contexto embaixo |
| selo em parágrafo | selo como componente, ao lado do número |
| proposta no terminal | Vender, com o preço explicado ao lado |
| "dimensionamento" | "quantos veículos eu preciso" |

O protótipo navegável está em `ui/` e sai em HTML autocontido com
`python ui/gerar.py`. Ele usa os números reais dos relatórios do projeto —
não é maquete com dado inventado.
