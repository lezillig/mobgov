# MOBGOV — MVP para governos

Plataforma de roteirização e **dimensionamento de frota** com IA para
secretarias estaduais e municipais (transporte escolar, transporte PCD e
fretamento governamental). Este repositório é o MVP de demonstração — projeto
separado do sistema operacional da Azul Mob (`gestao-motoristas`).

O diferencial que a demonstração precisa provar: dada a demanda real, **quantos
veículos são de fato necessários** e quanto isso economiza — com premissas
auditáveis, nada de número mágico.

## O que já existe

| Sprint | Módulo | Entrega |
|---|---|---|
| 1 | `dados/` (agent-dados) | Esquema do domínio e gerador do "Município Modelo" sintético (Ribeirão Modelo) |
| 1 | `motor/` (agent-rotas) | CVRP escolar com frota heterogênea (OR-Tools) + dimensionamento de frota e relatório antes/depois em JSON |
| 2 | `painel/` (agent-painel) | **Painel de economia** — a tela da demo: antes vs depois em R$, km, litros, CO₂ e veículos, simulador de cenários, memória de cálculo e exportação em PDF |
| 3 | `motor/escala.py` + `dados/` | **Roteirização multiviagem**: cada veículo encadeia várias viagens por turno, como a prefeitura opera de verdade. Destrava a demanda real (~3.000 alunos, dois turnos) e a frota atual passa a ser derivada de premissas declaradas |
| 4 | `dados/tempos.py`, `motor/porta_a_porta.py`, `motor/reotimizar.py` | **Trânsito variável** por faixa horária e zona (com provedor externo plugável), **porta a porta n:n** para o vertical PCD (PDPTW) e **reotimização do dia**: falta informada, cancelamento e inserção dinâmica de pedido novo |

Resultado atual do Município Modelo: **30 → 22 veículos (−26,7%)**, R$ 160.112/mês,
R$ 1,92 mi/ano, −1.374 km/dia, −281 litros/dia, −199,1 tCO₂/ano — com 106 viagens
diárias, ocupação média de 93,7% e nenhum aluno mais de 63 min dentro do veículo
(o limite da secretaria é 75). No porta a porta, 80 viagens/dia em 11 veículos com
100% dentro do limite de tempo a bordo; e a reotimização do dia responde em
menos de 0,1 segundo.

## Como rodar

```bash
pip install -r requirements.txt      # só o motor precisa de dependência (OR-Tools)

python motor/dimensionar.py          # 1) planejamento escolar (~5 min)
python motor/rodar_dia.py            # 2) porta a porta + eventos do dia (~40 s)
python -m painel.render              # 3) gera relatorios/painel-economia.html
python -m painel.servidor            # 4) ou sirva em http://127.0.0.1:8000/
```

O painel também aceita premissas pela linha de comando:

```bash
python -m painel.render --diesel 7.20 --dias 20 --saida /tmp/cenario-pessimista.html
```

Testes (biblioteca padrão, sem dependências):

```bash
python -m unittest discover -s testes -v
```

## O painel de economia (Sprint 2)

Uma página HTML **autocontida**: CSS, JavaScript e gráficos SVG embutidos, zero
requisição externa. Ela abre num notebook de prefeitura sem internet, escala em
projetor 1024x768 e imprime em A4 pelo próprio navegador — é assim que sai o
PDF de prestação de contas (botão "Salvar em PDF / imprimir").

Seções, na ordem da demonstração:

1. **Manchete** — veículos a menos, R$/mês, R$/ano, km/dia, litros/dia, tCO₂/ano.
2. **Antes e depois** — custo fixo e variável das duas frotas, veículo a veículo.
3. **Dimensionamento** — "sua frota atual: 30 veículos; necessário: 22 (…)",
   com quantas viagens cada veículo encadeia por turno.
4. **Qualidade do serviço** — ocupação por viagem, tempo dentro do veículo,
   posições de cadeirante e a jornada de cada turno: a prova de que a frota
   menor não piorou o serviço.
5. **Simulador de cenários** — preço do diesel e dias letivos.
6. **O que o sistema aprendeu** — evolução do erro de tempo estimado.
7. **Premissas, limitações e memória de cálculo** — o passo a passo da conta.

### Regras que o painel respeita

- **Nenhum número nasce no navegador.** Os controles do simulador apenas
  escolhem um cenário já calculado por `painel/economia.py` e embutido na
  página. Sem JavaScript, o cenário base continua na tela.
- **O painel recalcula, não copia.** Ele não repete os totais gravados pelo
  motor: refaz a conta a partir da composição de frota, do km rodado e das
  premissas, e imprime a memória de cálculo junto.
- **Custo por km é decomposto** em manutenção + diesel ÷ consumo, para que
  simular o preço do combustível mude o resultado de verdade. Com o diesel do
  relatório, a decomposição reproduz exatamente o custo da Sprint 1 (testado).
- **O que ainda não foi medido aparece marcado.** A série "o que o sistema
  aprendeu" leva o selo *SÉRIE DE DEMONSTRAÇÃO* até existir
  `relatorios/aprendizado.json` vindo da operação real (Sprint 5); aí o selo
  vira *MEDIDO NA OPERAÇÃO* sozinho.

### API

O servidor da Sprint 2 usa só a biblioteca padrão, mas o contrato já é o que o
front em React e o `agent-conversa` vão consumir:

| Rota | Devolve |
|---|---|
| `GET /` | painel HTML (aceita `?diesel=7.20&dias=20`) |
| `GET /api/economia` | indicadores antes/depois, qualidade e memória de cálculo |
| `GET /api/cenarios` | grade de cenários pré-calculados |
| `GET /api/aprendizado` | série de aprendizado com o selo de origem |
| `GET /api/relatorio` | relatório bruto do motor |

## A roteirização multiviagem (Sprint 3)

O motor trabalha em duas fases:

1. **Roteirizar** (`motor/dimensionar.py`, OR-Tools): para cada escola e cada
   turno, resolve o CVRP com frota heterogênea, tempo de embarque por parada e
   limite de 75 min por aluno. Cada "veículo" do solver é uma **viagem**.
2. **Escalar** (`motor/escala.py`, heurística pura): encaixa as viagens de um
   turno em veículos físicos — a mais longa primeiro, no veículo que ficar com
   menos folga — respeitando a jornada disponível antes do sinal, o
   deslocamento até a próxima escola, o tempo de virada e a compatibilidade de
   tipo (assentos e posições de cadeirante).

A frota necessária é o **maior número de veículos de cada tipo entre os
turnos**, não a soma: o mesmo ônibus atende manhã e tarde.

A separação das fases não é estética: a fase 2 roda sem OR-Tools e por isso é
testada isoladamente (`testes/test_escala.py`), inclusive quanto ao
determinismo — mesma entrada, mesma escala, requisito para a demo ser
reprodutível.

## Limitações conhecidas (declaradas também dentro do painel)

- A demanda é sintética (~2.900 alunos/dia em dois turnos). Com a planilha real
  da prefeitura os números mudam.
- **A frota atual do município fictício é derivada**, não informada: sai de
  ocupação média de 85%, 2,5 viagens por veículo/turno e rotas 25% mais longas
  que as otimizadas, aplicadas ao turno mais cheio. Num município real este
  dado vem do cadastro da secretaria — e é assim que o painel diz na tela.
- O encaixe das viagens é heurístico, não ótimo: a escala é sempre válida, mas
  pode existir arranjo um pouco melhor.
- Tempos de percurso saem de distância em linha reta com fator de sinuosidade
  rural (1,35) mais o tempo de embarque por parada, ainda não de malha viária
  real (OSRM) nem de GPS.
- O km/dia da frota atual é rateado entre os tipos de veículo, porque a
  prefeitura declara apenas o total.
- A dispersão no fim do turno é considerada espelhada da coleta, não
  roteirizada separadamente.
- O PDF sai pela impressão do navegador. Geração de PDF no servidor (para
  agendar envio ao tribunal de contas) fica para quando houver backend
  definitivo.

## Os dois tipos de rota

| | Ponto de encontro (escolar) | Porta a porta (PCD) |
|---|---|---|
| Quem se desloca | o aluno caminha até o ponto | o veículo encosta na casa |
| Destino | um por viagem (a escola) | um por usuário |
| Relação | n embarques → 1 desembarque | **n embarques ↔ n desembarques** |
| Janela | o sinal da escola | por usuário, 20 min (padrão *dial-a-ride*) |
| Limite | tempo do aluno no veículo | tempo a bordo de cada usuário |
| Motor | `motor/dimensionar.py` (CVRPTW) | `motor/porta_a_porta.py` (PDPTW) |

## Trânsito variável

`dados/tempos.py` isola o motor do fornecedor de tempos. Hoje roda offline
(`ProvedorHaversine` + `ComTransito`, com fatores por faixa horária e zona
declarados no painel). Trocar por malha viária real com trânsito — OSRM,
Valhalla, Mapbox Matrix ou Google Routes `TRAFFIC_AWARE_OPTIMAL` — é
implementar uma função `matriz()`; o motor de rotas não muda. Quando o app do
motorista entrar (Sprint 5), os fatores medidos com GPS substituem os
estimados sozinhos e o selo do painel muda de *FATORES ESTIMADOS* para
*MEDIDO COM GPS*.

## Reotimização do dia

Planejar à noite é metade do trabalho. `motor/reotimizar.py` trata os eventos
que acontecem depois:

- **falta informada** no escolar: a parada some da rota, o percurso é refeito e
  o sistema avisa se a viagem passou a caber num veículo menor;
- **cancelamento** no porta a porta: os dois eventos saem e a capacidade
  liberada volta ao pool na hora;
- **pedido novo**: inserção mais barata entre todas as rotas do dia,
  respeitando janela, tempo a bordo e capacidade — com limite de km por
  encaixe, porque encaixar a qualquer custo não é economia.

Tudo em Python puro, respondendo em milissegundos (a meta do MVP é 30 s).

## Próximos passos

- **Motor**: malha viária real (OSRM) no lugar da distância em linha reta.
- **Painel**: mapa das rotas (MapLibre) e tela de planejamento (importar
  planilha → otimizar → aprovar e publicar).
- **App do motorista**: GPS real alimentando o ciclo de aprendizado, que troca
  o selo de demonstração por dado medido.
