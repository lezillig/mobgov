# Sprint 3 — Roteirização multiviagem · resumo executivo

*MOBGOV · MVP para governos — módulo de transporte escolar*

## O que avançou

A Sprint 2 entregou a tela da demonstração, mas com uma trava declarada: o motor
assumia **uma rota por veículo por turno**, e por isso o município de teste só
comportava 466 alunos — longe dos ~3.000 do roteiro. Prefeitura nenhuma opera
assim. O mesmo ônibus sai, coleta, entrega na escola, volta e faz a próxima
viagem.

A Sprint 3 modelou isso. O motor passou a trabalhar em duas fases: o OR-Tools
resolve as **viagens** de cada escola em cada turno; em seguida uma etapa de
escala encaixa essas viagens em **veículos físicos**, respeitando a jornada
disponível antes do sinal, o deslocamento até a próxima escola e o tempo de
virada. Com isso a demanda subiu para o tamanho real e a comparação passou a
fazer sentido.

## Os números do Município Modelo

Demanda: **2.915 alunos/dia** em 300 pontos de embarque, 3 escolas, dois turnos
(1.613 de manhã, 1.302 à tarde), 13 alunos cadeirantes.

| Indicador | Frota atual | Frota necessária | Diferença |
|---|---:|---:|---:|
| Veículos | 30 | 22 | **−8 (−26,7%)** |
| Custo mensal | R$ 661.679 | R$ 510.145 | **−R$ 151.535 (−22,9%)** |
| Custo anual | R$ 7,94 mi | R$ 6,12 mi | **−R$ 1,82 mi** |
| Quilômetros por dia | 4.404 | 3.159 | −1.244 (−28,3%) |
| Diesel por dia | — | — | −242 l (−64.020 l/ano) |
| Emissões | — | — | **−171,5 tCO₂/ano** |
| Viagens por veículo/turno | 2,5 | 2,72 | +0,22 |

E o serviço melhorou junto: 106 viagens diárias com ocupação média de **93,4%**
(era 91,1% na sprint anterior), nenhum aluno mais de **57 minutos** dentro do
veículo (o limite da secretaria é 75), folga de lugares nos dois turnos e todas
as viagens com cadeirante em veículo acessível.

> A meta do MVP é redução de frota ≥ 20%. O cenário fecha em 26,7% — e há teste
> automatizado que quebra a build se cair abaixo de 20%.

## Uma correção de rota importante

Ao subir a demanda, a "frota atual" de 25 veículos herdada do cenário antigo
deixou de fazer sentido: ela não teria nem assentos para o turno da manhã.
Comparar contra ela teria inflado ou destruído a economia por acidente.

A frota atual passou a ser **derivada de premissas declaradas**, não escolhida a
dedo: ocupação média de 85%, 2,5 viagens por veículo/turno e rotas 25% mais
longas que as otimizadas, aplicadas ao turno mais cheio. O painel mostra essa
conta na tela e diz, com todas as letras, que **num município real esse dado vem
do cadastro da secretaria** — aqui ele é gerado porque o município é fictício.

Sem isso, o número da economia seria exatamente o tipo de "número mágico" que o
projeto proíbe.

## Como a escala é explicada a um gestor

A regra de encaixe é dita em uma frase: *a viagem mais longa entra primeiro, no
veículo que ficar com menos folga, desde que caiba a jornada, o deslocamento até
a próxima escola e o perfil de acessibilidade*. É heurística, não otimização
exata — e o painel declara isso entre as limitações.

Duas decisões de projeto sustentam a auditoria:

- **A frota necessária é o pior caso de cada tipo entre os turnos, não a soma.**
  O mesmo veículo atende manhã e tarde; somar seria comprar em dobro.
- **A escala é determinística.** Mesma entrada, mesma escala — requisito para a
  demonstração ser reprodutível diante do tribunal de contas.

## O que ficou de fora (e por quê)

- **Malha viária real (OSRM)**: os tempos ainda vêm de distância em linha reta
  com fator rural, agora somados ao tempo de embarque por parada. É o próximo
  item do motor.
- **Dispersão roteirizada**: a volta é considerada espelhada da coleta. Rotear
  a dispersão separadamente muda pouco o custo e adiaria itens mais visíveis.
- **Otimização exata da escala**: o ganho marginal não paga o custo agora.
- **Mapa das rotas no painel**: depende do OSRM, entra junto.

## Notas técnicas que valem registrar

- A construção gulosa clássica do OR-Tools (`PATH_CHEAPEST_ARC`) **não achava
  solução** para a escola do centro com 95 pontos e limite de 75 min por aluno.
  O motor agora tenta `PARALLEL_CHEAPEST_INSERTION` primeiro e só depois cai nas
  outras estratégias.
- A fase de escala vive em `motor/escala.py`, separada do OR-Tools, e por isso
  roda e é testada sem dependência nenhuma — 12 testes só dela.
- O painel ganhou tratamento de sinal: um indicador que **piora** aparece com
  "+" e em vermelho, em vez do "−-49,1 t" que apareceu durante o
  desenvolvimento. Um painel que não sabe mostrar resultado ruim não serve para
  auditoria.

## Próxima sprint (recomendação)

1. OSRM/OpenStreetMap no lugar da distância em linha reta — é o que separa a
   demonstração de um piloto real.
2. Importador da planilha bagunçada de prefeitura, ligando o painel a dados
   reais.
3. Mapa das rotas no painel, completando o roteiro de 20 minutos da demo.
