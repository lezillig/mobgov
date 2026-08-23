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
| 6 | `dados/importador.py` (planilha da prefeitura) + `operacao/` (app do motorista offline-first, API e ingestão para o aprendizado) | ✅ pronto |
| 7 | `conversa/` — camada conversacional (ferramentas + roteador offline + auditoria de números) | ✅ pronto |
| 7 | `elegibilidade/` — porta a porta sem papel: formulário, leitura assistida, fila com decisão humana | ✅ pronto |
| 7 | `motor/rodadas.py` — reotimização contínua em rodadas (ruin & recreate com horizonte de compromisso) | ✅ pronto |
| 7 | `operacao/app_responsavel.html` — "onde está o ônibus" e aviso de falta (origem real da taxa de ausência) | ✅ pronto |
| 8 | `painel/console.py` — a tela do sistema (Hoje, Elegibilidade, Assistente, Economia) | ✅ pronto |
| 8 | `planejamento/` + `motor/planejar.py` + `dados/agrupar.py` — planilha → pontos → rotas → publicar | ✅ pronto |
| 9 | `dados/perfis.py` + `motor/jornada.py` — perfil de fretamento: turnos configuráveis e jornada do motorista (Lei 13.103) como restrição | ✅ pronto |
| 10 | `comercial/` — precificação (custo → preço com margem por divisão) e diagnóstico da operação existente | ✅ pronto |
| 11 | `ui/` — o sistema remodelado por momento de trabalho (Início · Planejar · Operar · Fiscalizar · Vender · Ajustes), descrito em `docs/ux-modelo.md` | ✅ pronto |
| 12 | `fiscalizacao/` — medição do contrato: planejado × realizado, pagamento, glosa com evidência e boletim mensal por fornecedor | ✅ pronto |
| 8 | Roteiro de demonstração ensaiado (agent-qa-demo) | ⬜ |

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
  dados/planilha.py              lê csv/tsv/xlsx sem dependência (xlsx = zip + xml)
  dados/importador.py            colunas por sinônimo, dedup, geocodificação com plano B
  dados/agrupar.py               alunos importados -> pontos de embarque (raio de caminhada)
  dados/perfis.py                perfil de operação: escolar, fretamento ou JSON do cliente
  motor/jornada.py               fase 3: escala de motoristas (jornada, intervalo, interjornada)
  comercial/precificacao.py      custo aberto -> preço (margem e imposto por divisão)
  comercial/diagnostico.py       o que dá para cortar na operação que já roda
  comercial/operacao_atual.py    importa o quadro de linhas operadas hoje
  comercial/proposta.py          a proposta em HTML, com a conta aberta
  motor/planejar.py              planilha -> importador -> agrupador -> motor -> plano
  planejamento/servidor.py       a tela da roteirização: envia, confere, ajusta, publica
  planejamento/tela.html         os cinco passos numa página só
  planejamento/multipart.py      envio de arquivo sem dependência (o cgi saiu do 3.13)
  ui/app.html                    o sistema remodelado: 5 destinos, mapa vivo, trilha
  ui/gerar.py                    monta o payload real e escreve a tela autocontida
  fiscalizacao/medicao.py        plano publicado × eventos: o que de fato rodou
  fiscalizacao/contrato.py       do medido para o pago: modelo, glosa e suspenso
  fiscalizacao/simulador.py      um mês de execução imperfeita (selo simulado)
  fiscalizacao/relatorio.py      o boletim de medição que vai para o processo
  painel/console.py              console: Hoje, Elegibilidade, Equipe, Assistente
  docs/demonstracao/gerar_telas_estaticas.py  todas as telas em HTML autocontido
  motor/rodadas.py               reotimização contínua: o dia inteiro em rodadas
  motor/rodar_rodadas.py         roda a manhã em rodadas e grava rodadas.json
  operacao/app_motorista.html    app offline-first (fila local + sincronização)
  operacao/app_responsavel.html  app da família: previsão, paradas, aviso de falta
  operacao/onde_esta.py          "onde está o ônibus" com origem da previsão declarada
  operacao/servidor.py           API dos dois apps: rota do dia, situação, eventos
  operacao/registro.py           trilha append-only dos eventos da operação
  elegibilidade/perfil.py        necessidade operacional (nunca diagnóstico)
  elegibilidade/formulario.py    perguntas em língua de família -> restrições
  elegibilidade/extracao.py      leitura assistida do documento: sugere, não decide
  elegibilidade/fila.py          estados, prazo e registro de quem decidiu
  conversa/ferramentas.py        as 9 ferramentas — única fonte de número da resposta
  conversa/roteador.py           escolhe a ferramenta por palavra-chave, sem LLM
  conversa/redator.py            resposta em pt-BR a partir do resultado bruto
  conversa/assistente.py         laço de tool use + auditoria dos números escritos
  aprendizado/ingestao.py        eventos do app -> observações do ciclo de aprendizado
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
python motor/importar.py --gerar-exemplo   # planilha bagunçada -> demanda
python motor/rodar_rodadas.py          # reotimização contínua da manhã (~1 min)
python -m planejamento.servidor        # tela da roteirização (127.0.0.1:8090)
python motor/planejar.py planilha.xlsx # mesmo caminho pela linha de comando
python motor/planejar.py rh.csv --perfil fretamento --frota-atual "RODO46=9,EXEC28=6"
python comercial/cli.py precificar --plano relatorios/plano-fretamento.json --margem 12
python comercial/cli.py diagnosticar --plano ... --linhas linhas-atuais.csv
python comercial/cli.py proposta --plano ... --linhas ... --cliente "Empresa X"
python ui/gerar.py                     # o sistema remodelado (prefeitura + empresa)
python -m fiscalizacao.relatorio       # boletim de medição do mês
python -m fiscalizacao.relatorio --modelo viagem --valor-viagem 180
python -m painel.console               # gera relatorios/console.html
python docs/demonstracao/gerar_telas_estaticas.py   # o sistema inteiro em HTML
python -m operacao.servidor            # apps do motorista e do responsável (8080)
python conversa/cli.py --offline "quanto eu economizo por mês?"
python elegibilidade/demonstracao.py && python elegibilidade/relatorio.py
python elegibilidade/cli.py fila
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
- **O modelo de linguagem nunca escreve número.** As ferramentas de
  `conversa/` são a única fonte; `auditar_numeros` confere cada número da
  resposta contra o que as ferramentas devolveram e reprova a resposta que
  inventar. Sem chave de API, o roteador por palavra-chave responde igual.
- **Diagnóstico não roteiriza; necessidade roteiriza.** Em `elegibilidade/`,
  CID e laudo ficam no processo; o que vai para o motor é restrição
  operacional com identificador pseudonimizado. Não acrescente campo clínico
  ao `Perfil`.
- **Decisão sobre direito de pessoa com deficiência tem nome.** Aprovar sem
  analista, aprovar sem evidência ou negar sem justificativa levantam erro no
  código, não são convenção.
- **Previsão para a família tem origem declarada**: `medido` só quando houve
  embarque ou ping do veículo hoje; senão é `planejado`, e a tela diz isso.
- **A tela começa pela pendência, não pelo painel.** Em `ui/`, o Início lista o
  que precisa de decisão humana — cada item com quem decide, há quanto tempo
  espera e o botão que resolve. KPI é contexto, vem depois. Pendência nova só
  entra se tiver dono e ação; há teste que quebra sem isso.
- **Relatório auxiliar só entra se for do mesmo plano.** `ui/gerar.py` confere
  `origem.arquivo` antes de usar `importacao.json`: mostrar o erro de uma
  planilha em cima dos números de outra é o pior tipo de bug, porque parece
  certo. Pelo mesmo motivo, fila de porta a porta não aparece em operação de
  fretamento.
- **Número que o sistema duvida não aparece limpo.** Se `coerencia` traz aviso
  sobre a base de comparação, o cartão de economia diz isso ao lado do número.
- **Falta de evidência não é prova de falta.** Viagem sem nenhum evento é
  `sem_evidencia`, nunca `nao_realizada`: aparelho descarregado e zona rural
  sem sinal acontecem toda semana. Ela vira valor EM SUSPENSO, com dono da
  decisão — nem pago, nem glosado. Glosar por ausência de sinal cai no
  primeiro recurso e derruba a credibilidade do sistema inteiro.
- **Toda glosa cita a evidência.** Cada linha traz viagem, motivo e os
  eventos que sustentam a conclusão. O boletim é peça de processo
  administrativo, e o fornecedor tem direito de contestar olhando o mesmo
  dado.
- **Cobertura antes de dinheiro.** O boletim abre com quantas viagens têm
  evidência; abaixo de 70% ele diz, na cara, que não sustenta glosa. Relatório
  que abre com o valor da glosa e esconde a cobertura já perdeu a discussão.
- **Km medido por rastro esparso é PISO, não medida.** Somar retas entre pings
  distantes corta as curvas e sempre dá menos do que o veículo rodou — pagar
  por esse número é pagar a menos por defeito de aparelho. `medicao.py` marca
  `km_medido_confiavel` e a tela avisa.
- **Medir e pagar são módulos separados.** `medicao.py` responde "o que
  aconteceu" (técnico); `contrato.py`, "quanto vale" (jurídico). É o que
  permite contestar o valor sem rediscutir o fato.
- **Parâmetro que decide rota, frota ou preço mora numa tela.** O tempo
  máximo a bordo, o raio de caminhada, o catálogo de tipos de veículo, os
  turnos, a jornada e os custos ficam em Ajustes (`ui/app.html`) e são
  gravados pelo `POST /api/perfil`. Regra que decide quanto tempo uma criança
  fica dentro do ônibus não pode morar numa constante de módulo.
- **São dois tetos de tempo a bordo, não um.** Na rota coletiva vale
  `tempo_max_trajeto_min`, igual para todos; no porta a porta vale
  `direto × fator_tempo_bordo + folga_tempo_bordo_min`, relativo ao trajeto de
  cada um — 20 min de casa até a escola não podem virar 75 só porque o limite
  geral permite. `planejar(tempo_max_trajeto_min=...)` e o campo na tela
  sobrescrevem o teto só naquela rodada, e a tela mostra sempre o valor que o
  motor **usou**, não o padrão do perfil.
- **O motor só usa tipo de veículo cadastrado.** Salvar um perfil sem nenhum
  tipo é recusado no `POST /api/perfil` (400): `de_dicionario` trata lista
  vazia como "não configurado" e devolveria o catálogo padrão — apagar tudo na
  tela é decisão, não omissão.
- **Frota por tipo, nunca só o total.** O total não compra nada: quem licita
  precisa de "19 ônibus de 31 lugares, 3 vans acessíveis, 1 micro". Tipo que a
  operação tem hoje e o plano não usa mais continua na tabela com quantidade
  zero — sumir da lista esconderia o corte.
- **Contraparte é um campo só, com rótulo dos dois lados.** `Contraparte` em
  `dados/perfis.py` é o FORNECEDOR do lote quando quem usa é a prefeitura, e o
  CLIENTE dono da planta quando quem usa é a transportadora. O vínculo é com o
  **destino** (é assim que os dois contratos são escritos) e a atribuição é da
  **viagem**, nunca do veículo — o mesmo carro serve contratos diferentes no
  mesmo dia, e por isso a coluna de escalas por contrato não soma para a frota.
  Casa por id **ou** por nome do destino: plano vindo de planilha renumera os
  destinos (E1, E2, E3) e só preserva o nome da coluna.
- **Teste antes de commitar.** As fórmulas, a coerência dos indicadores e a meta
  de ≥20% de redução de frota são cobertas por testes; se a economia cair abaixo
  disso, a suíte quebra de propósito.

## Os dois verticais (o motor é o mesmo; a moldura, não)

| | Escolar (prefeitura) | Fretamento (empresa) |
|---|---|---|
| Turnos | 2, sinal fixo | 3 ou 4, virada quebrada, configuráveis |
| Destino | escola | planta, unidade, obra |
| Passageiro | aluno (≤75 min) | colaborador (≤90 min) |
| "Antes" | frota do PNATE | contrato de fretamento vigente |
| Motorista | embutido no custo do veículo | **custo próprio, com lei própria** |
| Volta | não modelada | bloco de dispersão no fim do turno |

A última linha é a que muda o resultado: no fretamento, o veículo roda os
quatro turnos e o motorista não pode. **7 veículos exigiram 16 motoristas** na
demonstração — é essa conta que decide o preço da proposta, e ela vive em
`motor/jornada.py`.

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
- **Screenshot headless engana**: o Chromium legado ignora `--window-size`
  para o layout (a viewport fica em ~500px) e só recorta a imagem. Um elemento
  "cortado" na captura pode estar perfeitamente dentro da página — meça
  `document.documentElement.scrollWidth` antes de "consertar" CSS que não está
  quebrado.
- **Reotimizar não pode remarcar quem já foi avisado.** As rodadas congelam o
  horizonte de compromisso (20 min) e só mexem em horário ainda não firme
  (janela de aviso, 60 min). Uma melhoria que quebre promessa é descartada
  inteira — e a rodada devolve o plano anterior.
- **A conta da rodada tem três parcelas** (km liberado por falta, km de
  demanda nova, ganho de remanejamento). Somar tudo num número só faz
  "atender mais gente" virar economia negativa — ou some com o custo.
- **Linha vazia some do XML do Excel.** O leitor de `.xlsx` respeita o
  atributo `r` do `<row>`; sem isso, uma linha em branco no meio desloca toda
  a numeração e o "conserte a linha 88" do relatório manda o servidor para a
  linha errada.
- **Sinal com horário absurdo não vira previsão.** Divergência acima de 120
  min entre o evento e o plano faz o app da família voltar ao horário
  planejado e dizer por quê — apareceu numa demonstração como "878 min
  atrasado" escrito com toda a confiança.
- **A frota atual estimada só vale para o Município Modelo.** Com planilha
  real, `montar_relatorio(permitir_estimativa=False)`: sem a frota declarada,
  o plano sai SEM comparação. A estimativa supõe ocupação de 85% e 2,5
  viagens por veículo; com 297 alunos em 196 pontos ela projetou 3 veículos
  contra os 23 do plano, e a "economia" saiu em −666%.
- **Oferta de veículos ao solver tem dois mínimos**: por assentos e por tempo
  (`viagens_pelo_tempo`). Demanda esparsa esgota o tempo muito antes dos
  assentos — só com o mínimo por assentos o solver não achava solução.
- **Aluno cuja ida-e-volta já passa do limite não tem rota possível.**
  `_separar_inviaveis` tira esses pontos e devolve por escrito em
  `demanda_nao_atendida`: é decisão da secretaria (endereço errado, escola do
  outro lado do município ou atendimento individual), não do sistema.
- **Frota declarada e planilha de alunos podem não falar do mesmo universo.**
  `_conferir_coerencia` avisa quando os lugares declarados passam de 2× o
  maior turno — foi o caso da primeira planilha real: frota do município
  inteiro contra 297 alunos.
- **Separador de CSV não se decide pela primeira linha.** Planilha de verdade
  começa com título sem separador nenhum; `_separador` olha 12 linhas. Antes,
  um CSV de RH inteiro virava uma coluna só e o importador respondia "não
  reconheci as colunas" — a mensagem mais frustrante possível para quem
  mandou o arquivo certo.
- **Contar só a ida subdimensiona a equipe.** Quem foi levado às 6h volta às
  14h: cada bloco de coleta tem o par dele na dispersão quando o turno declara
  `duracao_min`. Na demonstração de fretamento isso levou a equipe de 11 para
  16 motoristas.
- **As regras de jornada são parâmetros declarados**, não constantes
  escondidas: acordo coletivo muda quase todas, e elas vão para o relatório
  para o jurídico da empresa conferir.
- **Margem entra por DIVISÃO, não por soma.** `preço = custo / (1 − imposto −
  margem)`. Somar 12% ao custo e depois pagar 14,93% sobre a receita dá margem
  real de −4,2% — a proposta sai no prejuízo com cara de lucro.
- **Economia de diagnóstico não se soma.** Troca de veículo, fusão de linha e
  frota ociosa se contêm: o teto é o achado de frota ociosa, e os outros são
  parcelas dele. Somar tudo venderia economia que não existe.
- **Ponto pode ser milhar ou decimal.** `numero_br` decide pela forma (ponto
  seguido de exatamente três dígitos é milhar) e NÃO serve para coordenada:
  "-21.150" cairia na regra do milhar. Coordenada tem parser próprio, de
  propósito. `100.3` km/dia virando `1003` inflava a economia em quatro vezes.
- **A escala gulosa deixa restos.** Depois de distribuir os blocos, `_consolidar`
  tenta esvaziar quem ficou com sobra e redistribuir — apareceram motoristas
  com 1h09 de jornada na primeira escala do fretamento. A consolidação só
  aceita movimento que continua dentro da jornada, do descanso e da
  interjornada: consolidar quebrando a lei seria economia falsa.
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
- Taxa de ausência medida, e não estimada. ✅ o app do responsável é a origem
  (`aprendizado/ingestao.faltas_observadas`); vira número real com uso real.

## Benchmarks de referência

Spare (reotimização contínua com tráfego ao vivo), Zūm (embarque verificado +
app dos pais + self-learning), RideCo (elegibilidade PCD sem papel), Optibus
(otimização veículo+motorista, agente em linguagem natural; único presente no
Brasil, e só em rota fixa urbana), CharterUP (command center + apps duplos),
Via (simulação de cenários / gêmeo digital).
