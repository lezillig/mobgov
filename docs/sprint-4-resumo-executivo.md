# Sprint 4 — Porta a porta, trânsito e reotimização · resumo executivo

*MOBGOV · MVP para governos*

## O que avançou

Três capacidades que o benchmarking apontou como o que separa os líderes
(RideCo, Spare, Via, Zūm, Optibus) de um roteirizador comum:

1. **Porta a porta n:n** — o vertical PCD ganhou motor próprio. Cada usuário
   tem origem e destino, e a rota intercala vários embarques e desembarques.
2. **Trânsito variável** — o tempo de percurso passou a depender do horário e
   da zona, com o fornecedor de tempos isolado atrás de uma interface.
3. **Reotimização do dia** — falta informada, cancelamento e pedido novo agora
   têm resposta imediata, com diff em português e tempo medido.

## Os números

**Escolar (agora com trânsito no cálculo):**

| Indicador | Frota atual | Necessária | Diferença |
|---|---:|---:|---:|
| Veículos | 30 | 22 | **−8 (−26,7%)** |
| Custo mensal | R$ 661.679 | R$ 501.567 | **−R$ 160.112 (−24,2%)** |
| Custo anual | R$ 7,94 mi | R$ 6,02 mi | **−R$ 1,92 mi** |
| km/dia | 4.404 | 3.030 | −1.374 (−31,2%) |
| Emissões | — | — | **−199,1 tCO₂/ano** |

Ligar o trânsito somou **um veículo** ao turno da manhã em relação à Sprint 3.
É o resultado certo: o pico existe, e planejar como se não existisse produz
uma escala que estoura no primeiro dia.

**Porta a porta (PCD):** 80 viagens/dia atendidas por **11 veículos**,
716 km/dia, 7,3 usuários por veículo, tempo a bordo médio de **38,9 min**
(máximo 67) e **100% dentro do limite** de tempo a bordo.

**Reotimização:** 10 eventos processados, resposta mais lenta de **0,069 s**
(a meta do MVP era 30 s), 10,8 km poupados só nesse lote e **6 de 6 pedidos
novos encaixados** em rota existente, sem veículo extra.

## O que aprendemos com o mercado (e aplicamos)

Do benchmarking completo em `docs/benchmarking-mercado.md`:

- **RideCo** reotimiza a malha inteira a cada 20 segundos considerando
  cancelamentos, trânsito e posição do veículo — economizou US$ 8,8 mi/ano na
  SEPTA. Trouxemos o princípio, evento a evento; o laço contínuo é o próximo
  passo.
- **Spare** devolve ao pool, na hora, a capacidade liberada por cancelamento
  (US$ 14 mi/ano no MBTA). Implementado: o cancelamento dispara a busca por
  alguém da fila de espera.
- **Via** reduziu 60% do custo por viagem no NJ Transit com otimização
  contínua. O indicador "km por usuário" entrou no painel por causa disso.
- **Optibus** corta até 10% da frota de pico e mais 5% otimizando o horário —
  a otimização de horário (mexer no sinal da escola) entrou no backlog.
- **Padrões ADA de *dial-a-ride*** — janela de embarque de 20 minutos e tempo a
  bordo limitado — viraram parâmetros do motor porta a porta, não opinião.

## Decisões de arquitetura

- **O fornecedor de tempos é plugável.** `dados/tempos.py` define o contrato
  `matriz(locais, partida_min, zonas)`. Hoje: haversine + perfil de trânsito,
  offline. Amanhã: OSRM próprio, Mapbox ou Google Routes — o motor de rotas não
  muda uma linha.
- **O que não foi medido vem marcado.** Os fatores de trânsito exibem o selo
  *FATORES ESTIMADOS* até existir GPS real; aí viram *MEDIDO COM GPS* sozinhos.
- **Reotimização em Python puro.** Reotimizar uma rota isolada é um problema
  pequeno; resolver com 2-opt responde em milissegundos, que é o requisito real
  — o despachante está no telefone com a mãe do aluno.
- **Encaixar tem limite de custo.** Um pedido que só cabe com 30 km de desvio é
  recusado com justificativa: viagem dedicada sai mais barato. Aceitar a
  qualquer custo não é economia.

## Dois bugs que valem registro

1. **O veículo esperava com o passageiro dentro.** A primeira versão da agenda
   fazia o veículo aguardar a janela abrir no destino, com a pessoa a bordo.
   Isso inflava o tempo a bordo e a reotimização recusava encaixes que na
   prática cabem — nenhum dos 15 pedidos da fila entrava. Corrigido com duas
   passadas (limite para trás, horários para frente) que **embarcam o mais
   tarde possível**: o usuário sai de casa depois e anda menos tempo dentro do
   veículo. Depois da correção, 6 de 6 pedidos couberam.
2. **A inserção pegava a primeira rota viável, não a mais barata.** Um usuário
   entrou com 21 km de desvio quando outra rota o absorveria por muito menos.
   Agora a busca varre todas as rotas do dia e escolhe a de menor acréscimo.

## O que falta para ser o melhor do mercado

| Capacidade | Quem faz | Prioridade |
|---|---|---|
| Malha viária real (OSRM/Valhalla) | todos | **Alta** — é o que separa demo de piloto |
| Reotimização contínua o dia inteiro | RideCo (20 s), Spare (1 min) | **Alta** |
| Aprendizado realimentando a rota | Zūm | **Alta** (Sprint 5, junto com o app) |
| App do motorista e do responsável | todos | Alta |
| Otimização de horário junto com a rota | Optibus | Média |
| Gêmeo digital / simulação de rede | Via | Média |
| Elegibilidade PCD sem papel | RideCo, Spare | Média |
| Agente em linguagem natural | Optibus (2026) | Média |

## Próxima sprint (recomendação)

1. **OSRM sobre OpenStreetMap do município** — malha viária real, com tabela de
   velocidades por faixa horária. Destrava o mapa no painel e derruba a maior
   limitação declarada.
2. **App do motorista (offline-first)** — o GPS que ele manda é o que troca o
   selo *estimado* por *medido* em trânsito e tempo de parada.
3. **Laço de reotimização contínua** — em vez de evento a evento, uma rodada a
   cada N minutos sobre a malha do dia, no estilo RideCo.
