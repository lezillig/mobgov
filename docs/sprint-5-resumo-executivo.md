# Sprint 5 — Malha viária real, aprendizado e mapa · resumo executivo

*MOBGOV · MVP para governos*

## O que avançou

Três frentes, todas apontadas pelo benchmarking como o que separa uma
demonstração de um piloto:

1. **Malha viária real (OSRM)** — o sistema deixou de depender de distância em
   linha reta. Cliente completo, com uma variável de ambiente ligando tudo.
2. **Ciclo de aprendizado** — o que a operação mostra volta para o motor de
   rotas, com versionamento e rollback. O diferencial nº 2 do prompt-mestre
   virou código rodando, não slide.
3. **Mapa das rotas** — desenhado em SVG a partir do próprio relatório, sem
   tiles e sem internet.

## Malha viária real

`dados/osrm.py` fala com um OSRM próprio sobre o OpenStreetMap do município.
O que o cliente resolve, e que um `GET` simples não resolveria:

- **quebra a matriz em blocos** para respeitar o `max-table-size` do servidor
  (300 pontos são 90 mil pares; o padrão do OSRM aceita 100 coordenadas);
- **cache no disco** com chave pelo conteúdo — replanejar o mesmo cenário não
  consulta o servidor de novo;
- **retry com espera crescente** e **queda para a estimativa geográfica** se o
  servidor não responder, registrando o motivo: a demonstração não trava
  porque um contêiner caiu;
- **erro explícito para ponto fora da malha**, que é o sintoma mais comum de
  endereço rural mal geocodificado na importação.

Ligar é `export MOBGOV_OSRM_URL=http://localhost:5000`. O motor de rotas não
muda uma linha — o contrato `matriz()` já estava isolado desde a Sprint 4.
O passo a passo de instalação está em `docs/osrm-como-rodar.md`, incluindo
como alimentar o trânsito histórico do próprio município pelo CSV de
velocidades do OSRM.

Como aqui não há um OSRM instalado, o cliente é exercitado ponta a ponta
contra um **servidor OSRM falso** em memória — 19 testes cobrindo blocos,
cache, retry, queda, ponto fora da malha e geometria.

## Ciclo de aprendizado

`aprendizado/` fecha o laço:

1. a operação devolve observações — tempo real por trecho, tempo de embarque
   por ponto, faltas por dia;
2. o ciclo estima fatores de trânsito, tempo extra de parada e taxa de
   ausência (mediana, e só com amostra suficiente);
3. o candidato é validado num conjunto separado e **só entra se o erro cair**;
4. os fatores vão para `relatorios/fatores_transito.json` e o motor passa a
   planejar com eles na rodada seguinte.

**Resultado em 8 semanas simuladas:** erro médio do tempo estimado caiu de
**5,88 min para 2,03 min** (−65%) nas primeiras cinco semanas e estabilizou;
a acurácia da previsão de ausência ficou em ~92%; **3 rollbacks** recusaram
versões que teriam piorado a previsão. O sistema descobriu sozinho que o pico
da manhã na zona urbana é ×1,57 e não ×1,35 como o planejamento supunha — e a
verdade oculta do simulador era ×1,52 mais chuva.

E o laço fechou de verdade: com os fatores aprendidos, o motor replanejou e
**pediu um veículo a mais no turno da manhã**. Não é regressão, é a correção
do otimismo: a escala anterior estouraria na rua.

> **Honestidade do selo.** Enquanto o app do motorista não existe, as
> observações vêm de um simulador com verdade oculta. O painel mostra
> *APRENDIDO EM SIMULAÇÃO*, não *medido*. O que é real é o caminho inteiro —
> coleta, estimativa, validação separada, versão, rollback e realimentação do
> motor. Trocar o simulador pelos pings do app não muda mais nada.

## Mapa das rotas

Projeção equirretangular em SVG, gerada a partir do mesmo relatório que
produz os números — não é ilustração. Mostra as paradas, as escolas e o
traçado de cada viagem, além de um segundo mapa com o vaivém do porta a
porta (verde = embarque na casa, laranja = desembarque no destino).

Sem tiles, sem CDN, sem chave de API: continua abrindo offline no notebook da
prefeitura. Com OSRM ligado, `geometria_rota()` troca a poligonal entre
paradas pelo traçado real da rua.

## Três bugs que valem registro

1. **O aprendizado inflava o trânsito a cada rodada** (1,35 → 1,55 → 1,83…).
   O estimador desfazia o fator do *modelo corrente* para achar o tempo sem
   trânsito, quando devia desfazer o fator que o *plano* usou. Agora cada
   observação carrega o `fator_plano` — que é o que a ingestão real também
   saberá.
2. **A simulação empilhava fator sobre fator**, aplicando a verdade oculta em
   cima de um tempo que já vinha com o trânsito do planejamento. O sistema
   "descobria" um congestionamento que não existia.
3. **A curva do erro oscilava com o clima, não com o modelo**, porque a
   validação era sempre "a semana seguinte" e o sorteio de dias de chuva
   mudava. Agora há dois conjuntos fixos: um decide a promoção, outro — que
   nunca influencia decisão — é o que o painel reporta.

## O que falta

| Capacidade | Prioridade |
|---|---|
| App do motorista (offline-first) — troca simulação por GPS real | **Alta** |
| Reotimização contínua o dia inteiro (hoje é evento a evento) | **Alta** |
| Tela de planejamento: importar planilha → otimizar → aprovar → publicar | Alta |
| Otimização de horário junto com a rota (o truque da Optibus) | Média |
| Camada conversacional sobre as ferramentas internas | Média |
| Elegibilidade PCD sem papel | Média |

## Próxima sprint (recomendação)

1. **App do motorista**, mesmo que enxuto: rota do dia, embarque confirmado e
   ping de GPS. É a peça que converte todo o resto de "simulado" em "medido".
2. **Importador de planilha de prefeitura** — sem ele, o piloto não começa.
3. **Laço de reotimização contínua**, em rodadas de N minutos sobre a malha do
   dia, no estilo RideCo.
