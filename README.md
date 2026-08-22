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

## Como rodar

```bash
pip install -r requirements.txt      # só o motor precisa de dependência (OR-Tools)

python motor/dimensionar.py          # 1) otimiza e grava relatorios/dimensionamento.json
python -m painel.render              # 2) gera relatorios/painel-economia.html
python -m painel.servidor            # 3) ou sirva em http://127.0.0.1:8000/
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
3. **Dimensionamento** — "sua frota atual: 25 veículos; necessário: 17 (…)".
4. **Qualidade do serviço** — ocupação por rota, tempo dentro do veículo,
   posições de cadeirante: a prova de que a frota menor não piorou o serviço.
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

## Limitações conhecidas (declaradas também dentro do painel)

- A demanda é sintética. O Município Modelo hoje gera **466 alunos**, e não os
  ~3.000 previstos no roteiro de demonstração: o modelo atual assume **uma rota
  por veículo por turno**, então uma demanda maior explodiria a frota
  necessária. Encadear duas ou três viagens por veículo (multiviagem) é
  pré-requisito para subir a demanda — está no backlog do motor de rotas.
- Tempos de percurso saem de distância em linha reta com fator de sinuosidade
  rural (1,35), ainda não de malha viária real (OSRM) nem de GPS.
- O km/dia da frota atual é rateado entre os tipos de veículo, porque a
  prefeitura declara apenas o total.
- O PDF sai pela impressão do navegador. Geração de PDF no servidor (para
  agendar envio ao tribunal de contas) fica para quando houver backend
  definitivo.

## Próximos passos

- **Motor**: roteirização multiviagem para sustentar a demanda de 3.000 alunos.
- **Painel**: mapa das rotas (MapLibre) e tela de planejamento (importar
  planilha → otimizar → aprovar e publicar).
- **App do motorista**: GPS real alimentando o ciclo de aprendizado, que troca
  o selo de demonstração por dado medido.
