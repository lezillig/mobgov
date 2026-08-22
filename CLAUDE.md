# MOBGOV — memória do projeto

> Resumo operacional do prompt-mestre (`prompt-sistema-mobgov-mvp.md`) mais o
> estado real do código. Leia antes de mexer em qualquer coisa dentro de
> `mobgov/`. O restante do repositório é o sistema de gestão de motoristas da
> Azul Mob (Next.js) — projeto diferente, não misturar.

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

Formato de saída obrigatório:
> "Sua frota atual: 25 veículos. Necessário: 17 (16 ônibus de 31 lugares + 1 van
> acessível). Economia estimada: R$ X/mês, Y km/dia, Z litros/dia, W tCO₂/ano" —
> com todas as premissas listadas.

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
| 3–4 | Tela de planejamento (importar → otimizar → aprovar) e mapa MapLibre | ⬜ |
| 5–6 | App do motorista (React Native) → aprendizado contínuo real | ⬜ |
| 7 | Camada conversacional + roteiro de demo ensaiado | ⬜ |
| 8 | Elegibilidade PCD (ou pós-MVP, conforme o edital-alvo) | ⬜ |

Resultado atual no Município Modelo: **25 → 17 veículos (−32%)**,
R$ 125.099/mês, R$ 1,50 mi/ano, −707 km/dia, −169 l/dia, −119,5 tCO₂/ano,
ocupação média 91,1%, tempo máximo 63 min (limite 75).

## Estrutura

```
mobgov/
  dados/municipio_modelo.py      esquema do domínio + gerador sintético (seed 42)
  motor/dimensionar.py           CVRP por escola, frota heterogênea, relatório JSON
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
python motor/dimensionar.py            # gera relatorios/dimensionamento.json
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

## Armadilhas conhecidas

- **OR-Tools não vem instalado** no ambiente remoto; sem ele o motor não roda,
  mas o painel funciona a partir do `dimensionamento.json` já gravado.
- **Demanda do Município Modelo é de 466 alunos**, não dos ~3.000 do roteiro de
  demonstração. O motor assume **uma rota por veículo por turno**; subir a
  demanda sem roteirização multiviagem produziria uma frota necessária irreal.
  Multiviagem é o próximo item do motor — está declarado no painel e no README.
- **Tempos de percurso** vêm de distância em linha reta com fator rural 1,35,
  ainda não de OSRM nem de GPS.
- **km/dia da frota atual é rateado** entre os tipos, porque a prefeitura declara
  só o total.
- O gerador usa `random.seed(42)`: a demanda é reprodutível, e deve continuar
  sendo — a demo depende disso.

## Módulos previstos (agentes do prompt-mestre)

| Agente | Responsabilidade |
|---|---|
| `agent-dados` | Esquema PostGIS, importador de planilha de prefeitura, geocodificação com fallback, anonimização |
| `agent-rotas` | CVRPTW escolar, dimensionamento de frota, paratransit dinâmico, reotimização diária |
| `agent-aprendizado` | Tempo por trecho, tempo de parada, previsão de ausência, re-treino noturno com rollback |
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

- Redução de frota ≥ 20% no Município Modelo, com premissas auditáveis. ✅ (32%)
- Reotimização após imprevisto em < 30 segundos. ⬜
- Erro de previsão de tempo caindo semana a semana no painel. ⬜ (série ainda ilustrativa)
- Planilha real de prefeitura → rotas publicadas em < 1 hora. ⬜

## Benchmarks de referência

Spare (reotimização contínua com tráfego ao vivo), Zūm (embarque verificado +
app dos pais + self-learning), RideCo (elegibilidade PCD sem papel), Optibus
(otimização veículo+motorista, agente em linguagem natural; único presente no
Brasil, e só em rota fixa urbana), CharterUP (command center + apps duplos),
Via (simulação de cenários / gêmeo digital).
