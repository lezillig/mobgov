# MOBGOV — memória do projeto

> Resumo operacional do prompt-mestre (`prompt-sistema-mobgov-mvp.md`) mais o
> estado real do código. Leia antes de mexer em qualquer coisa deste
> repositório. O MOBGOV nasceu dentro do repositório `gestao-motoristas` (o
> sistema operacional da Azul Mob, em Next.js) e mudou-se para cá nas Sprints
> 1–2; os dois projetos são separados e não devem se misturar.

## O que é

Plataforma brasileira de **roteirização e dimensionamento de frota com IA** para
governos estaduais e municipais, em três verticais: transporte escolar,
transporte PCD (paratransit) e fretamento governamental.

O MVP é apresentado a governos. A demonstração precisa provar **vantagem real e
mensurável**, não telas bonitas.

### Diferencial nº 1 — dimensionamento de frota real
O sistema recebe a demanda (alunos/usuários, endereços, janelas de horário,
restrições de acessibilidade) e responde: quantos veículos são de fato
necessários, de que tipo, em quais rotas — comparando com a frota atual e
quantificando a economia em R$, km, litros, CO₂ e veículos ociosos.

Formato de saída obrigatório (com os números que o motor produz hoje):
> "Sua frota atual: 30 veículos. Necessário: 22 (18 ônibus de 31 lugares +
> 3 vans acessíveis + 1 micro-ônibus). Economia estimada: R$ X/mês, Y km/dia,
> Z litros/dia, W tCO₂/ano" — com todas as premissas listadas.

### Diferencial nº 2 — IA que aprende
Cada dia de operação (GPS real, atrasos, ausências, tempo de embarque)
realimenta os modelos, e isso tem que ser **visível no painel**: "o sistema
previu X, aconteceu Y, ajustou Z".

## Princípios inegociáveis

1. **Economia comprovável.** Toda otimização gera "antes vs depois" com
   premissas auditáveis. Nada de números mágicos.
2. **LGPD por desenho.** Dados de menores (escolar) e de saúde (PCD) exigem
   minimização, criptografia e trilha de auditoria. Nenhum dado pessoal em log
   ou prompt de LLM sem anonimização.
3. **Explicabilidade.** Cada rota e cada recomendação de frota tem que ser
   explicável em português simples para um gestor público e para um tribunal de
   contas.
4. **Offline-first no app do motorista** (zona rural tem sinal ruim).
5. **Português brasileiro** em toda a interface e documentação — inclusive
   nomes de funções, variáveis, commits e comentários deste diretório.

## Estado atual

| Sprint | Módulo | Situação |
|---|---|---|
| 1 | `dados/` — esquema + Município Modelo sintético | ✅ pronto |
| 1 | `motor/` — CVRP escolar (OR-Tools) + dimensionamento + relatório JSON | ✅ pronto |
| 2 | `painel/` — painel de economia (a tela da demo) | ✅ pronto |
| 3 | `motor/escala.py` — roteirização multiviagem + demanda real (~2.900 alunos, 2 turnos) | ✅ pronto |
| 4 | `dados/tempos.py` (trânsito variável), `motor/porta_a_porta.py` (PCD n:n), `motor/reotimizar.py` (falta, cancelamento, inserção dinâmica) | ✅ pronto |
| 5 | `dados/osrm.py` (malha viária real), `aprendizado/` (ciclo com rollback), mapa das rotas em SVG | ✅ pronto |
| 6 | App do motorista (React Native) → troca simulação por GPS real | ⬜ |
| 7 | Camada conversacional + roteiro de demo ensaiado | ⬜ |
| 8 | Elegibilidade PCD (ou pós-MVP, conforme o edital-alvo) | ⬜ |

Resultado atual no Município Modelo (escolar, com trânsito **aprendido**):
**30 → 23 veículos (−23,3%)**, R$ 141.122/mês, R$ 1,69 mi/ano, com 107
viagens/dia e ocupação média de 93%. Era 22 veículos antes do aprendizado: o
ciclo descobriu que a rua é mais lenta do que o planejamento supunha e o motor
corrigiu para cima — economia menor, mas confiável.

Porta a porta (PCD): 80 viagens/dia em 12 veículos, 710 km/dia, tempo a bordo
médio de 43,2 min e 100% dentro do limite.
Reotimização do dia: 10 eventos, resposta máxima de 0,063 s, 5 de 6 pedidos
novos encaixados em rota existente.
Aprendizado: erro do tempo estimado de 5,88 → 2,03 min em 5 semanas
(simulação), 3 rollbacks recusando piora.

## Estrutura

```
mobgov/                          (raiz deste repositório)
  dados/municipio_modelo.py      esquema do domínio + gerador sintético (seed 42)
  motor/dimensionar.py           fase 1: CVRP por escola e turno (OR-Tools)
  motor/escala.py                fase 2: escala multiviagem (heurística, sem OR-Tools)
  motor/porta_a_porta.py         PDPTW do vertical PCD: n embarques e n desembarques
  motor/reotimizar.py            dia em andamento: falta, cancelamento, inserção dinâmica
  motor/rodar_dia.py             orquestra o porta a porta e os eventos do dia
  dados/tempos.py                trânsito variável e provedores plugáveis de tempo
  dados/osrm.py                  malha viária real: blocos, cache, retry e fallback
  aprendizado/simulador.py       operação simulada com verdade oculta (troca pelo app)
  aprendizado/aprender.py        estimativas, métricas, versão e rollback do modelo
  motor/rodar_aprendizado.py     roda o ciclo e grava os fatores que o motor usa
  dados/demanda_pcd.py           demanda sintética do porta a porta (sem dado pessoal)
  painel/economia.py             recálculo auditável + cenários + memória de cálculo
  painel/aprendizado.py          série "o que o sistema aprendeu" (real ou demonstração)
  painel/graficos.py             gráficos SVG gerados no servidor
  painel/render.py               monta a página HTML autocontida
  painel/servidor.py             servidor e API (biblioteca padrão)
  painel/assets/                 painel.css e painel.js embutidos na página
  relatorios/                    dimensionamento.json (motor) e painel-economia.html
  testes/                        unittest, sem dependências
  docs/                          resumo executivo por sprint
```

## Comandos

```bash
pip install -r requirements.txt        # só o motor precisa (OR-Tools)
python motor/dimensionar.py            # planejamento escolar (~5 min)
python motor/rodar_dia.py              # porta a porta + eventos do dia (~40 s)
python motor/rodar_aprendizado.py      # ciclo de aprendizado (~5 s)
MOBGOV_OSRM_URL=http://localhost:5000 python motor/dimensionar.py   # malha real
python -m painel.render                # gera relatorios/painel-economia.html
python -m painel.render --diesel 7.20 --dias 20
python -m painel.servidor              # http://127.0.0.1:8000/
python -m unittest discover -s testes -v
```

## Regras ao mexer no código

- **Todo número exibido sai do motor.** O navegador não calcula nada: o
  simulador de cenários apenas escolhe um cenário já resolvido em Python e
  embutido na página. Vale igual para a futura camada conversacional — o LLM
  chama ferramenta, nunca inventa número.
- **O painel recalcula, não copia** os totais gravados pelo motor: refaz a conta
  a partir da composição de frota, do km e das premissas, e imprime a memória de
  cálculo junto.
- **Toda premissa nova é declarada na tela.** Se mudar o resultado, aparece na
  seção de premissas e na memória de cálculo.
- **O que não foi medido vem marcado.** A série de aprendizado usa o selo *SÉRIE
  DE DEMONSTRAÇÃO* até existir `relatorios/aprendizado.json` da operação real.
  Nunca apresentar dado ilustrativo como medido.
- **A página do painel é autocontida**: CSS, JS e SVG embutidos, zero requisição
  externa, funciona sem JavaScript, contraste e fonte para projetor 1024x768, e
  imprime em A4 pelo navegador (é assim que sai o PDF de prestação de contas).
  Há teste que quebra se entrar `http://`, `src=` ou `href=` na página.
- **Painel e testes só com biblioteca padrão.** Dependência nova só no motor, e
  com justificativa: a demo tem que subir em máquina de prefeitura.
- **Teste antes de commitar.** As fórmulas, a coerência dos indicadores e a meta
  de ≥20% de redução de frota são cobertas por testes; se a economia cair abaixo
  disso, a suíte quebra de propósito.

## Os dois tipos de rota (não confundir)

| | Ponto de encontro (escolar) | Porta a porta (PCD) |
|---|---|---|
| Quem anda até onde | o aluno caminha até o ponto | o veículo encosta na casa |
| Destino | único por viagem | um por usuário |
| Relação | n embarques → 1 desembarque | **n embarques ↔ n desembarques** |
| Janela | o sinal da escola | por usuário, ~20 min |
| Limite de tempo | tempo do aluno no veículo | tempo A BORDO de cada usuário |
| Motor | `motor/dimensionar.py` (CVRPTW) | `motor/porta_a_porta.py` (PDPTW) |

## Armadilhas conhecidas

- **OR-Tools não vem instalado** no ambiente remoto; sem ele o motor não roda,
  mas o painel funciona a partir do `dimensionamento.json` já gravado.
- **Rodar o motor leva ~5 minutos** (6 solves de 30 s + matrizes). Rode em
  segundo plano e não conclua que travou.
- **PATH_CHEAPEST_ARC sozinho não resolve** a escola do centro: o motor tenta
  PARALLEL_CHEAPEST_INSERTION primeiro e só depois cai nas outras estratégias.
  Se mexer nisso, confira que as três escolas e os dois turnos ainda fecham.
- **A frota atual do município fictício é derivada**, não informada
  (`frota_atual_sintetica`): ocupação de 85%, 2,5 viagens por veículo/turno e
  rotas 25% mais longas. Trocar essas premissas muda a economia — por isso elas
  aparecem na tela. Num município real, esse dado é entrada, não estimativa.
- **Tempos de percurso** vêm de distância em linha reta com fator rural 1,35
  mais o tempo de embarque por parada, ainda não de OSRM nem de GPS.
- **km/dia da frota atual é rateado** entre os tipos, porque a prefeitura declara
  só o total; o da frota otimizada vem da jornada real de cada veículo.
- O gerador usa `random.seed(42)`: a demanda é reprodutível, e deve continuar
  sendo — a demo depende disso. O porta a porta tem gerador próprio
  (`random.Random(2026)`) para não deslocar a sequência do escolar.
- **No porta a porta, o veículo espera FORA, não com gente dentro.** A agenda é
  montada em duas passadas (limite para trás, horários para frente) para
  embarcar o mais tarde possível. Mexer nisso sem entender infla o tempo a
  bordo e faz a reotimização recusar encaixes que na prática cabem — foi um bug
  real da Sprint 4.
- **Trânsito muda a frota.** Ligar o perfil de trânsito ao motor escolar somou
  um veículo no turno da manhã. É o resultado certo: o pico existe. Depois do
  aprendizado (fatores maiores que os estimados), somou outro.
- **O aprendizado precisa saber qual fator o plano usou.** Cada observação
  carrega `fator_plano`; sem isso, o estimador desfaz o fator errado e o
  trânsito "aprendido" cresce a cada rodada (1,35 → 1,55 → 1,83 → …). Foi um
  bug real da Sprint 5.
- **Métrica de aprendizado usa dois conjuntos fixos**: um valida (decide
  promoção), outro reporta. Medir no conjunto que escolheu o modelo infla o
  resultado; e reusar a "semana seguinte" faz a curva oscilar com o clima, não
  com o modelo.
- **`urlparse` corta o que vem depois de `;`** no último segmento da URL (vira
  `params`) — e o OSRM separa coordenadas com `;`. Qualquer código que
  interprete URLs do OSRM precisa recolar `path + ';' + params`.

## Módulos previstos (agentes do prompt-mestre)

| Agente | Responsabilidade |
|---|---|
| `agent-dados` | Esquema PostGIS, importador de planilha de prefeitura, geocodificação com fallback, anonimização |
| `agent-rotas` | CVRPTW escolar, dimensionamento de frota, multiviagem |
| `agent-porta-a-porta` | PDPTW do vertical PCD: par embarque/desembarque, janela por usuário, tempo máximo a bordo, cadeira de rodas |
| `agent-transito` | Camada de tempos: perfil por faixa horária e zona, provedores externos (OSRM/Valhalla/Google/Mapbox), fatores aprendidos |
| `agent-reotimizacao` | Operação do dia: falta informada, cancelamento, inserção dinâmica de pedido novo, diff legível em segundos |
| `agent-aprendizado` | Tempo por trecho, tempo de parada, previsão de ausência, re-treino com validação separada e rollback |
| `agent-painel` | Mapa vivo, planejamento, **painel de economia**, gestão de cadastros |
| `agent-apps` | App do motorista (offline-first) e app do responsável/usuário (WCAG) |
| `agent-elegibilidade` | Cadastro PCD, ficha médica com revisão humana obrigatória |
| `agent-conversa` | Assistente em português sobre ferramentas internas, sem dado pessoal bruto |
| `agent-qa-demo` | Testes e2e, dados do Município Modelo, roteiro de 20 min, modo relógio acelerado |

## Stack alvo

Backend Python (FastAPI), PostgreSQL + PostGIS, Redis · otimização com OR-Tools
(VRP/CVRPTW) sobre OSRM/Valhalla + OpenStreetMap · ML com scikit-learn/XGBoost ·
front React + MapLibre, apps em React Native · LLM via API com function calling
sobre os serviços internos · Docker, deploy em nuvem BR.

O MVP atual roda um passo antes disso de propósito: scripts Python e servidor da
biblioteca padrão. As funções de `painel/economia.py` são puras justamente para
que o FastAPI as reaproveite sem reescrita.

## Métricas de sucesso do MVP

- Redução de frota ≥ 20% no Município Modelo, com premissas auditáveis. ✅ (26,7%)
- Reotimização após imprevisto em < 30 segundos. ✅ (máximo medido: 0,07 s)
- Erro de previsão de tempo caindo semana a semana no painel. ✅ em simulação
  (5,88 → 2,03 min em 5 semanas, com 3 rollbacks recusando piora); vira medição
  real quando o app do motorista entrar.
- Planilha real de prefeitura → rotas publicadas em < 1 hora. ⬜

## Benchmarks de referência

Spare (reotimização contínua com tráfego ao vivo), Zūm (embarque verificado +
app dos pais + self-learning), RideCo (elegibilidade PCD sem papel), Optibus
(otimização veículo+motorista, agente em linguagem natural; único presente no
Brasil, e só em rota fixa urbana), CharterUP (command center + apps duplos),
Via (simulação de cenários / gêmeo digital).
