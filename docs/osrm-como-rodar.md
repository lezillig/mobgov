# Malha viária real — como ligar o OSRM

*MOBGOV · Sprint 5. Este guia sobe um servidor de roteirização sobre o
OpenStreetMap do município e liga o MOBGOV nele. Do lado do sistema, é uma
variável de ambiente: o motor de rotas não muda uma linha.*

## 1. Por que servidor próprio

| | OSRM próprio | API comercial (Google, Mapbox, HERE) |
|---|---|---|
| Custo da matriz de planejamento (300 pontos = 90 mil pares) | só o servidor | cobrada por elemento — inviável no plano diário |
| Funciona sem internet | sim | não |
| Trânsito | histórico, alimentado pelo próprio município | ao vivo, o melhor do mercado |
| Dado sai do município | não | sim |

**Recomendação:** OSRM próprio para o planejamento (a matriz grande) e, se um
dia fizer falta, uma API comercial só para o ETA do dia — que é uma consulta
pequena. É a divisão que o benchmarking mostrou nos operadores maiores.

## 2. Subir o servidor

Baixe o recorte do OpenStreetMap que cobre o município (Geofabrik publica por
estado; recorte com `osmium extract` se quiser só a região):

```bash
mkdir -p osrm && cd osrm
wget https://download.geofabrik.de/south-america/brazil/sudeste-latest.osm.pbf

docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/sudeste-latest.osm.pbf
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-partition /data/sudeste-latest.osrm
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-customize /data/sudeste-latest.osrm

docker run -t -i -p 5000:5000 -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-routed --algorithm mld --max-table-size 200 /data/sudeste-latest.osrm
```

`--max-table-size 200` importa: o padrão (100) é baixo e o cliente do MOBGOV
quebra a matriz em blocos para respeitá-lo. Com 200, são menos requisições.

Máquina: um extrato estadual pede ~8 GB de RAM para processar e ~2 GB para
servir. Um município sozinho cabe folgado em 4 GB.

## 3. Ligar o MOBGOV

```bash
export MOBGOV_OSRM_URL=http://localhost:5000
python motor/dimensionar.py     # agora sobre ruas de verdade
```

É só isso. `dados/tempos.py` monta o provedor conforme o ambiente; o motor
enxerga a mesma função `matriz()` de sempre.

O que o cliente (`dados/osrm.py`) resolve sozinho:

- **quebra a matriz em blocos** respeitando o `max-table-size`;
- **guarda em cache** no disco (`relatorios/cache/`), com chave pelo conteúdo:
  replanejar o mesmo cenário não consulta o servidor de novo;
- **tenta de novo** com espera crescente antes de desistir;
- **cai para a estimativa geográfica** se o servidor não responder, e registra
  o motivo — a demonstração não trava por causa de um contêiner que caiu;
- **avisa quando um ponto está fora da malha**, em vez de devolver tempo zero:
  endereço rural mal geocodificado é o erro mais comum de importação.

## 4. Trânsito histórico do próprio município

O OSRM aceita uma tabela de velocidades por segmento — é assim que se coloca
o trânsito real (e não o de free-flow) dentro do cálculo:

```bash
# de_osm_id,para_osm_id,velocidade_kmh
osrm-customize /data/municipio.osrm --segment-speed-file /data/velocidades.csv
```

O arquivo sai do que o app do motorista coletar. Enquanto ele não existe, o
MOBGOV aplica o perfil de trânsito por faixa horária (`dados/tempos.py`) por
cima do tempo do OSRM. Quando as velocidades do CSV já embutirem o trânsito,
desligue o perfil para não contar duas vezes:

```bash
export MOBGOV_OSRM_COM_TRANSITO=0
```

## 5. Conferir se está valendo

```bash
python -c "
from dados.osrm import ProvedorOSRM
p = ProvedorOSRM()
print('servidor disponível:', p.disponivel())
d, t = p.matriz([(-21.150, -47.800), (-21.095, -47.775)])
print('origem dos tempos:', p.ultima_origem, '·', d[0][1], 'km ·', t[0][1], 'min')
"
```

`origem dos tempos` responde `osrm`, `cache` ou `fallback`. Se vier
`fallback`, `p.ultimo_erro` diz o porquê.

## 6. Depois disso

Com malha real ligada, duas coisas melhoram de imediato:

1. **O km fica auditável.** Hoje a distância é linha reta × 1,35; com OSRM é a
   rua. O valor de economia deixa de ter esse asterisco.
2. **O mapa do painel mostra o traçado da rua**, não a poligonal entre paradas
   (`ProvedorOSRM.geometria_rota`).

E abre a porta para o Valhalla, quando entrarem restrições de veículo (peso em
ponte de estrada rural, altura, tipo de via permitido para escolar) — o mesmo
contrato `matriz()`, outro provedor.
