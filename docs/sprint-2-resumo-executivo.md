# Sprint 2 — Painel de Economia · resumo executivo

*MOBGOV · MVP para governos — módulo de transporte escolar*

## O que avançou

A Sprint 1 provou o diferencial em linha de comando: o motor calcula quantos
veículos a rede realmente precisa. A Sprint 2 transforma esse resultado na
**tela que vai à frente do secretário**: uma página única que mostra o antes e o
depois em dinheiro, quilômetros, combustível, emissões e veículos — e explica de
onde cada número saiu.

## Os números do Município Modelo (demanda sintética)

| Indicador | Frota atual | Frota necessária | Diferença |
|---|---:|---:|---:|
| Veículos | 25 | 17 | **−8 (−32%)** |
| Custo mensal | R$ 399.078 | R$ 273.979 | **−R$ 125.099 (−31,3%)** |
| Custo anual | R$ 4,79 mi | R$ 3,29 mi | **−R$ 1,50 mi** |
| Quilômetros por dia | 1.180 | 473 | −707 (−59,9%) |
| Diesel por dia | 314 l | 145 l | −169 l (−44.590 l/ano) |
| Emissões | — | — | **−119,5 tCO₂/ano** |

E o serviço não piorou: ocupação média de 91,1% nas 17 rotas, nenhuma acima de
100%, tempo máximo de 63 minutos dentro do veículo (o limite da secretaria é
75), 45 assentos de folga e as posições de cadeirante atendidas.

> A meta de sucesso do MVP era redução de frota ≥ 20%. O cenário fecha em 32%, e
> há um teste automatizado que quebra a build se esse número cair abaixo de 20%.

## Como a tela sustenta uma sabatina

O risco da demonstração não é a tela ser feia; é o gestor (ou o tribunal de
contas) perguntar "de onde saiu esse número?". As decisões de projeto foram
todas para responder isso:

- **O painel refaz a conta**, não copia os totais do motor. A memória de cálculo
  — fórmula, valores de entrada e resultado de cada passo — vai impressa junto.
- **As premissas são visíveis e ajustáveis**: preço do diesel, dias letivos,
  tempo máximo do aluno no veículo, fator de emissão, origem dos tempos.
- **As limitações estão na própria página**, não escondidas: demanda sintética,
  uma rota por veículo por turno, tempos ainda sem malha viária real.
- **O simulador não inventa nada**: os cenários de preço do diesel e de dias
  letivos são calculados pelo motor antes de a página ser gerada; os controles
  só escolhem qual mostrar.
- **O que ainda não foi medido vem marcado.** A seção "o que o sistema aprendeu"
  carrega o selo *SÉRIE DE DEMONSTRAÇÃO* até chegar GPS real da operação.

## Pronto para a sala da prefeitura

- Página autocontida: abre **sem internet**, sem instalar nada, num duplo clique.
- Contraste alto e fonte grande, testada em 1024x768 (projetor).
- Botão "Salvar em PDF / imprimir" gera o documento A4 de prestação de contas,
  com quebras de página tratadas e campo de assinatura do responsável.
- Funciona **sem JavaScript** — se o navegador da prefeitura for antigo, o
  cenário base continua na tela.

## O que ficou de fora (e por quê)

- **Mapa das rotas**: exige a malha viária real (OSRM); entra junto da troca do
  cálculo de tempos.
- **Tela de planejamento** (importar planilha → otimizar → aprovar → publicar):
  depende do importador de planilhas de prefeitura, próximo item do agent-dados.
- **PDF gerado no servidor**: hoje sai pela impressão do navegador, o que já
  atende a demonstração; virar rotina automática só quando houver backend
  definitivo.
- **Demanda de 3.000 alunos**: o Município Modelo gera 466 hoje. Subir esse
  número sem antes implementar roteirização multiviagem (um veículo fazendo duas
  ou três viagens por turno) produziria uma frota necessária irreal — seria
  exatamente o "número mágico" que o projeto proíbe. É o próximo item do motor.

## Próxima sprint (recomendação)

1. Multiviagem no motor de rotas + demanda do Município Modelo em escala real.
2. Importador da planilha bagunçada de prefeitura, ligando o painel a dados reais.
3. Mapa das rotas no painel, para completar o roteiro de 20 minutos da demo.
