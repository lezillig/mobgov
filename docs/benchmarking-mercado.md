# Benchmarking de mercado — IA para roteirizar e cortar custo

*MOBGOV · pesquisa de agosto de 2026. Consolida o mapeamento anterior
(blueprint B2G e análise Cobli vs. concorrentes) com pesquisa nova, e ordena
os players pelo que interessa: **quem usa IA para roteirizar e reduzir o custo
do transporte**, com resultado comprovado.*

---

## 1. Os que provam corte de custo com IA (prioridade máxima)

| Player | O que a IA faz | Resultado comprovado | O que copiar |
|---|---|---|---|
| **RideCo** (paratransit EUA) | *Continuous Dynamic Optimization*: o solver reotimiza **a cada 20 segundos** toda a malha do dia, considerando viagens novas, cancelamentos, trânsito, posição do veículo e pausa do motorista | SEPTA/Filadélfia: 400+ veículos, **US$ 8,8 mi/ano**; contratos em LA, Houston, San Antonio | O laço de reotimização contínua — não é otimização noturna, é o dia inteiro |
| **Via** | ViaAlgo (otimização contínua) + Via Intelligence, "gêmeo digital" para simular a rede antes de mudar | NJ Transit: 33 mil viagens, 98% de pontualidade e **−60% de custo por viagem**; 689+ clientes governo | Simulação de cenário antes de publicar a rota — e o número que vende: custo por viagem |
| **Zūm** (escolar K-12) | Roteirização *self-learning*: cada dia de operação corrige a rota do dia seguinte | **−20% de frota**, −25% de horas de trajeto, 98% OTP, 4.000+ escolas | O ciclo de aprendizado ligado à roteirização, não só ao ETA |
| **Optibus** (rota fixa, **presente no Brasil**) | Otimização simultânea de veículo + motorista; otimização de *timetable*; agente de IA em linguagem natural (lançado em 2026) | **−10% de PVR** (340 → 307 veículos), €600 mil de economia com −5% de jornadas; +5% de redução extra com otimização de horários | Otimizar o horário, não só a rota: mexer no sinal da escola muda a frota |
| **Spare** | Spare Engine com reotimização por minuto usando trânsito ao vivo; AI Scan (lê ficha médica) e AI Voice (reserva por telefone) | MBTA: **US$ 14 mi/ano**; Votran 97% OTP; CapMetro +40% OTP | Mesmo-dia de verdade: capacidade liberada por cancelamento volta ao pool na hora |

**Leitura para o MOBGOV:** os cinco vendem o mesmo produto — *número*. Nenhum
vende tela. E os três maiores ganhos vêm de **reotimização contínua**,
**aprendizado realimentando a rota** e **otimização de horário junto com a
rota**. É exatamente essa a ordem de prioridade do nosso backlog.

## 2. Os que operam o nicho, sem IA de otimização no centro

| Player | Posição | Onde é forte | Onde deixa espaço |
|---|---|---|---|
| **Transfinder** (Routefinder PLUS/Pro) | Líder de roteirização escolar nos EUA, 10.645+ relações com redes K-12 | Motor proprietário com ajuste dinâmico por trânsito, clima e frequência; apps para família e motorista | Produto de rede escolar americana; nada de licitação, PNATE ou prestação de contas brasileira |
| **Tyler Technologies (Traversa)** | Alternativa corporativa | Gestão completa: excursão, GPS, manutenção, comunicação | Roteirização é módulo, não é o coração |
| **BusPatrol** | Operação em tempo real e segurança | Rastreamento ao vivo, detecção de ultrapassagem de stop-arm com IA | Não dimensiona frota nem prova economia |
| **Ecolane** | Paratransit/microtransit | Agendamento sob demanda consolidado | Motor menos agressivo que RideCo/Spare em reotimização contínua |
| **CharterUP** | Fretamento | Command center + apps duplos, capacidade dinâmica | Fretamento privado, não governo |
| **Cobli, Sascar, Contele, Safecar** (Brasil) | Telemetria e videotelemetria | Rastreamento, câmera com IA de fadiga, roteirização de **entrega** | Falam a língua de carga; nenhum dimensiona frota de passageiros nem fala com edital |

**Faixa de preço observada:** software de transporte escolar nos EUA custa de
US$ 2,8 mil a US$ 592 mil por ano por rede, conforme porte e módulos. No
Brasil, a única tabela pública encontrada foi a da Contele (câmera com IA:
R$ 249,90/mês + R$ 220 de instalação) — referência de custo, não de valor.

## 3. Infraestrutura de roteirização — o que existe para comprar ou hospedar

### Motores de otimização

| Opção | Perfil | Nota para o MOBGOV |
|---|---|---|
| **OR-Tools** (atual) | Grátis, maduro, CVRPTW e *pickup & delivery* nativos | Acima de ~600 pontos por instância o gap ultrapassa 10% — daí decompor por escola e turno, como já fazemos |
| **VROOM** | C++, microserviço HTTP, integra com OSRM; ~100 ms para 50 veículos / 200 tarefas | Candidato natural para a **reotimização do dia** (resposta em milissegundos) |
| **Timefold** (ex-OptaPlanner) | Solver de restrições Java/Kotlin, agora com API Python | Bom quando entrar escala de motorista junto com rota (o truque da Optibus) |
| **Hexaly / Gurobi** | Comerciais, melhores em instância grande | Só se um contrato estadual justificar a licença |

### Malha viária e trânsito

| Fonte | Trânsito | Custo | Quando usar |
|---|---|---|---|
| **OSRM** próprio | Histórico, via atualização de velocidades por CSV (suporte experimental) | Grátis + servidor | Base do piloto: malha real do município, sem conta de API |
| **Valhalla** próprio | Custo por segmento em tempo de execução, roteirização com hora | Grátis + servidor | Quando entrarem restrições de veículo (peso, altura, via rural) |
| **Mapbox Matrix** | Histórico + ao vivo | Por elemento de matriz | Matriz média com trânsito, sem manter servidor |
| **Google Routes** (`TRAFFIC_AWARE_OPTIMAL`) | O melhor ao vivo do mercado | SKU Pro, caro em matriz grande | ETA do dia e reotimização, nunca a matriz inteira do planejamento |
| **HERE / TomTom** | Ao vivo, roteirização com perfil de veículo | Comercial | Alternativa ao Google com preço melhor em volume |

**Decisão adotada (Sprint 4):** a camada `dados/tempos.py` isola o motor do
fornecedor. Hoje roda `ProvedorHaversine + ComTransito` (offline, perfil de
trânsito declarado); trocar por OSRM, Mapbox ou Google é implementar uma
função `matriz()` — o motor de rotas não muda.

## 4. Padrões operacionais que o mercado já consolidou

Coletados de manuais de operação ADA e da documentação dos players — são
requisitos, não opinião:

- **Janela de embarque de ~20 minutos** no porta a porta: se a viagem é 7h30,
  o veículo pode chegar entre 7h30 e 7h50.
- **Tempo a bordo limitado**: o usuário não pode ficar mais de ~1 hora além do
  tempo direto da viagem — é o que impede a otimização de "empilhar" gente.
- **Falta (*no-show*) e cancelamento no mesmo dia** liberam capacidade que
  precisa voltar ao pool **imediatamente**, para absorver pedido novo.
- **Inserção dinâmica**: aceitar um pedido novo é encaixá-lo numa rota
  existente; recusar só quando nenhuma inserção é viável.
- **Elegibilidade sem papel**: IA lê a ficha médica (inclusive manuscrita) e o
  servidor aprova — a IA sugere, o humano decide.

## 5. Onde o MOBGOV está e o que falta

| Capacidade | Mercado | MOBGOV hoje | Prioridade |
|---|---|---|---|
| Dimensionamento de frota com prova auditável | Ninguém entrega isso pronto para tribunal de contas | ✅ Sprint 1–3 | — |
| Multiviagem por veículo | Padrão | ✅ Sprint 3 | — |
| Rota por ponto de encontro | Padrão escolar | ✅ Sprint 1 | — |
| **Porta a porta n:n (PCD)** | RideCo, Spare, Via, Ecolane | ✅ Sprint 4 | — |
| **Trânsito variável por horário** | Todos | ✅ Sprint 4 (perfil declarado; provedor externo plugável) | — |
| **Reotimização por falta/cancelamento** | RideCo (20 s), Spare (1 min) | ✅ Sprint 4 (evento a evento) | — |
| Reotimização contínua o dia todo | RideCo, Spare | ⬜ | **Alta** |
| Aprendizado realimentando a rota | Zūm | ⬜ (Sprint 5) | **Alta** |
| Otimização de horário junto com a rota | Optibus | ⬜ | Média |
| Malha viária real (OSRM/Valhalla) | Todos | ⬜ | **Alta** |
| Simulação de cenário / gêmeo digital | Via | ⬜ (simulador de custo já existe) | Média |
| Elegibilidade PCD sem papel | RideCo, Spare | ⬜ (Sprint 8) | Média |
| App do motorista e do responsável | Todos | ⬜ (Sprint 5–6) | Alta |
| Agente em linguagem natural | Optibus (2026) | ⬜ (Sprint 7) | Média |

## 6. O que nos diferencia de todos eles

1. **Prestação de contas embutida.** Nenhum player estrangeiro produz relatório
   com premissas auditáveis para tribunal de contas brasileiro. O painel do
   MOBGOV nasce com memória de cálculo e limitações declaradas.
2. **Verba que já existe.** PNATE e Caminho da Escola financiam o escolar sem
   depender de o município criar orçamento novo.
3. **Software + operação.** Zūm e RideCo venceram unindo tecnologia e frota —
   é o combo que a Azul Mob já tem pela metade.
4. **Offline de verdade.** O painel e o motor rodam sem internet. Numa
   prefeitura do interior, isso não é detalhe.

---

*Fontes: RideCo (Continuous Dynamic Optimization, caso SEPTA), Spare (blog
"What Modern Paratransit Software Looks Like in 2026", casos MBTA/Votran/
CapMetro), Via (7 proven concepts for reducing costs, caso NJ Transit),
Optibus (blog de otimização de PVR e timetable, lançamento do AI Agent 2026),
comparativos de software de transporte escolar 2026 (Transfinder, Tyler
Traversa, BusPatrol), documentação de Google Routes API, Mapbox Matrix, OSRM,
Valhalla, VROOM, Timefold, e manuais de operação de dial-a-ride ADA.*
