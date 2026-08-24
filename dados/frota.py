# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 16 · agent-dados
A frota real, veículo a veículo, com placa.

Até aqui o sistema só sabia dizer "4 vans de 15 lugares". Isso basta para
dimensionar no papel e não basta para mais nada: não dá para conferir contrato
sem placa, não dá para medir km por carro, e — o que ficou claro no primeiro
arquivo de cliente — **o tamanho da frota que o motor calcula depende inteira e
diretamente do veículo que se supõe**. Com van de 15 lugares, uma operação de
456 alunos cabe em 33 carros. Com um carro de 2 cadeirantes + 4 alunos
sentados, a mesma operação precisa de 48. A diferença não está na roteirização;
está numa linha de planilha que ninguém tinha mandado.

Por isso este módulo existe: a configuração da frota deixa de ser premissa e
passa a ser dado enviado.

O que ele faz:

1. lê a planilha de frota (uma linha por veículo, com placa);
2. **valida a conta de lugares**: total declarado contra alunos + motorista +
   monitora + assentos que a cadeira de rodas ocupa. Planilha de frota erra
   isso o tempo todo, e o erro vira veículo fantasma no plano;
3. **agrupa em tipos** — veículos com a mesma configuração viram um
   `TipoVeiculo`, que é o que o motor consome, sem perder a placa de cada um;
4. relata em português o que não deu para resolver sozinho.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from dados.importador import detectar_colunas as _detectar_alunos, normalizar
from dados.municipio_modelo import TipoVeiculo
from dados.planilha import ErroDePlanilha, abas as listar_abas, ler

# --------------------------------------------------------------- sinônimos ---
SINONIMOS = {
    "placa": ["placa", "placas", "identificacao", "prefixo", "n do veiculo",
              "numero do veiculo", "veiculo"],
    "tipo": ["tipo", "tipo de veiculo", "modelo", "categoria", "descricao",
             "veiculo tipo", "classificacao"],
    "capacidade_total": ["capacidade total", "capacidade", "lugares",
                         "lugares total", "total de lugares", "assentos",
                         "capacidade homologada", "lotacao"],
    "capacidade_pcd": ["capacidade pcd", "pcd", "cadeirante", "cadeirantes",
                       "posicoes cadeirante", "posicoes de cadeira",
                       "capacidade cadeirante", "cadeiras de rodas",
                       "lugares pcd", "acessivel"],
    "capacidade_alunos": ["capacidade alunos", "alunos", "capacidade de alunos",
                          "lugares alunos", "alunos sentados", "passageiros",
                          "capacidade passageiros"],
    "monitora": ["monitora", "monitor", "leva monitora", "com monitora",
                 "acompanhante", "auxiliar"],
    "contrato": ["contrato", "lote", "n do contrato", "numero do contrato",
                 "fornecedor", "empresa", "cliente"],
    "garagem": ["garagem", "base", "ponto de partida", "origem", "patio",
                "endereco da garagem", "cep da garagem"],
    "turnos": ["turnos", "turno", "periodo", "disponibilidade", "escala"],
    "ativo": ["ativo", "situacao", "status", "em operacao", "disponivel"],
    "custo_km": ["custo km", "r km", "valor km", "custo por km", "preco km"],
    "custo_mes": ["custo mes", "valor mensal", "custo fixo mes", "mensalidade",
                  "valor do contrato mes", "r mes"],
    "consumo": ["consumo", "km l", "consumo km l", "media km l"],
}

# Padrões de quando a planilha não diz. Todos aparecem no relatório: premissa
# que o sistema assume sozinho e não conta é premissa que vira briga depois.
CUSTO_KM_PADRAO = 1.95
CUSTO_MES_PADRAO = 10200.0
CONSUMO_PADRAO = 6.0
# Uma cadeira de rodas presa no assoalho ocupa o espaço de três assentos —
# é a conta que a adaptadora usa para dizer quantos lugares o veículo perde.
ASSENTOS_POR_CADEIRA = 3

NEGATIVOS = {"nao", "n", "0", "false", "inativo", "parado", "manutencao",
             "baixado", "desativado", "reserva"}


@dataclass
class Veiculo:
    """Um carro de verdade, com placa."""
    placa: str
    tipo_nome: str
    capacidade_alunos: int
    capacidade_pcd: int
    capacidade_total: int = 0
    monitora: bool = True
    contrato: str = ""
    garagem: str = ""
    turnos: tuple = ()
    ativo: bool = True
    custo_km: float = CUSTO_KM_PADRAO
    custo_mes: float = CUSTO_MES_PADRAO
    consumo_km_l: float = CONSUMO_PADRAO
    linha_planilha: int = 0

    @property
    def configuracao(self) -> tuple:
        """O que faz dois veículos serem o mesmo tipo para o motor."""
        return (self.capacidade_alunos, self.capacidade_pcd,
                round(self.custo_km, 2), round(self.custo_mes, 2),
                round(self.consumo_km_l, 2))


@dataclass
class ImportacaoDeFrota:
    veiculos: list = field(default_factory=list)
    problemas: list = field(default_factory=list)
    colunas: dict = field(default_factory=dict)
    aba: str = ""

    def problema(self, linha, campo, valor, descricao, sugestao,
                 gravidade="erro"):
        self.problemas.append({
            "linha": linha, "campo": campo, "valor": valor,
            "problema": descricao, "sugestao": sugestao, "gravidade": gravidade,
        })

    @property
    def ativos(self) -> list:
        return [v for v in self.veiculos if v.ativo]

    def resumo(self) -> dict:
        ativos = self.ativos
        por_tipo = {}
        for v in ativos:
            chave = v.tipo_nome or "(sem tipo)"
            item = por_tipo.setdefault(
                chave, {"veiculos": 0, "alunos": 0, "pcd": 0, "placas": []})
            item["veiculos"] += 1
            item["alunos"] += v.capacidade_alunos
            item["pcd"] += v.capacidade_pcd
            if v.placa:
                item["placas"].append(v.placa)
        return {
            "aba": self.aba,
            "veiculos": len(self.veiculos),
            "veiculos_ativos": len(ativos),
            "parados": len(self.veiculos) - len(ativos),
            "sem_placa": sum(1 for v in self.veiculos if not v.placa),
            "capacidade_alunos": sum(v.capacidade_alunos for v in ativos),
            "capacidade_pcd": sum(v.capacidade_pcd for v in ativos),
            "acessiveis": sum(1 for v in ativos if v.capacidade_pcd > 0),
            "por_tipo": por_tipo,
            "por_contrato": _contar(ativos, "contrato"),
            "erros": sum(1 for p in self.problemas if p["gravidade"] == "erro"),
            "avisos": sum(1 for p in self.problemas if p["gravidade"] == "aviso"),
            "colunas_detectadas": self.colunas,
        }


def _contar(veiculos, campo) -> dict:
    contagem = {}
    for v in veiculos:
        chave = getattr(v, campo) or "(não informado)"
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


# ------------------------------------------------------------- conversões ---
def _inteiro(valor, padrao=None):
    achado = re.search(r"-?\d+", str(valor or "").replace(".", ""))
    return int(achado.group(0)) if achado else padrao


def _decimal(valor, padrao=None):
    bruto = str(valor or "").strip()
    if not bruto:
        return padrao
    # "R$ 1.234,56" e "1234.56" no mesmo arquivo
    limpo = re.sub(r"[^\d,.\-]", "", bruto)
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return padrao


def normalizar_placa(valor: str) -> str:
    """ABC-1D23, abc1d23 e "ABC 1D23" são a mesma placa."""
    limpo = re.sub(r"[^A-Za-z0-9]", "", str(valor or "")).upper()
    return limpo if re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}", limpo) else ""


def _sim(valor, padrao=True):
    alvo = normalizar(valor)
    if not alvo:
        return padrao
    return alvo not in NEGATIVOS


def _turnos(valor) -> tuple:
    alvo = normalizar(valor)
    achados = []
    for turno, marcas in (("manha", ("manha", "matutino", "m")),
                          ("tarde", ("tarde", "vespertino", "t")),
                          ("noite", ("noite", "noturno", "n"))):
        if any(m in alvo.split() or alvo.startswith(m) for m in marcas):
            achados.append(turno)
    if "ambos" in alvo or "todos" in alvo or "integral" in alvo:
        return ("manha", "tarde")
    return tuple(achados)


# ------------------------------------------------------------- importação ---
def importar(caminho: str, aba=None) -> ImportacaoDeFrota:
    """Lê a planilha de frota. Procura a aba de frota sozinho.

    `aba` restringe a uma aba (nome ou índice). Sem isso, procura em todas e
    fica com a primeira que tenha cara de frota — o mesmo arquivo do cliente
    costuma trazer alunos numa aba e veículos noutra.
    """
    resultado = ImportacaoDeFrota()
    candidatas = [aba] if aba is not None else (listar_abas(caminho) or [None])

    for alvo in candidatas:
        try:
            linhas = ler(caminho, alvo) if alvo is not None else ler(caminho)
        except ErroDePlanilha as erro:
            resultado.problema(0, "arquivo", str(alvo),
                               f"Não consegui ler a aba: {erro}",
                               "Confira se o arquivo é mesmo uma planilha.")
            continue
        if _carregar_aba(linhas, str(alvo or "única"), resultado):
            return resultado

    if not resultado.veiculos and not resultado.problemas:
        resultado.problema(
            0, "arquivo", "", "Não achei aba de frota nesta planilha.",
            "A aba precisa de um cabeçalho com placa (ou tipo de veículo) e "
            "capacidade. Uma linha por carro.")
    return resultado


def _carregar_aba(linhas, nome_da_aba, resultado) -> bool:
    if not linhas:
        return False
    inicio = _achar_cabecalho(linhas)
    colunas = detectar_colunas(linhas[inicio])
    # Uma lista de alunos tem "nome" e "endereço" e nenhuma capacidade. Sem
    # esta guarda, a aba "Sul-2" viraria frota e o CEP viraria lugar.
    if _detectar_alunos(linhas[inicio]).get("nome") is not None and \
            "capacidade_total" not in colunas and \
            "capacidade_alunos" not in colunas:
        return False
    if "placa" not in colunas and "tipo" not in colunas:
        return False
    if not any(c in colunas for c in
               ("capacidade_total", "capacidade_alunos", "capacidade_pcd")):
        return False

    resultado.colunas = colunas
    resultado.aba = nome_da_aba
    vistas = {}
    for numero, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        if not any((c or "").strip() for c in linha):
            continue
        veiculo = _converter_linha(linha, numero, colunas, resultado)
        if veiculo is None:
            continue
        if veiculo.placa and veiculo.placa in vistas:
            resultado.problema(
                numero, "placa", veiculo.placa,
                f"Placa repetida (já aparece na linha {vistas[veiculo.placa]}).",
                "Mantive só a primeira. Dois carros não podem ter a mesma "
                "placa — se forem carros diferentes, corrija uma delas.",
                "aviso")
            continue
        if veiculo.placa:
            vistas[veiculo.placa] = numero
        resultado.veiculos.append(veiculo)
    return bool(resultado.veiculos)


def _achar_cabecalho(linhas: list, limite: int = 10) -> int:
    melhor, pontos = 0, -1
    for i, linha in enumerate(linhas[:limite]):
        atual = len(detectar_colunas(linha))
        if atual > pontos:
            melhor, pontos = i, atual
    return melhor


def detectar_colunas(cabecalho: list) -> dict:
    normalizado = [normalizar(c) for c in cabecalho]
    colunas = {}
    for campo, opcoes in SINONIMOS.items():
        for i, titulo in enumerate(normalizado):
            if not titulo or i in colunas.values():
                continue
            if titulo in opcoes or any(titulo.startswith(o + " ") or titulo == o
                                       for o in opcoes):
                colunas[campo] = i
                break
    return colunas


def _converter_linha(linha, numero, colunas, resultado):
    def campo(nome):
        indice = colunas.get(nome)
        if indice is None or indice >= len(linha):
            return ""
        return str(linha[indice] or "").strip()

    bruto_placa = campo("placa")
    placa = normalizar_placa(bruto_placa)
    tipo = campo("tipo") or ""
    if bruto_placa and not placa:
        resultado.problema(
            numero, "placa", bruto_placa, "Placa fora do formato.",
            "Esperado ABC1D23 (Mercosul) ou ABC1234. Guardei o veículo sem "
            "placa — sem ela não dá para medir km nem conferir contrato.",
            "aviso")
    if not placa and not tipo:
        return None                       # rodapé, total, linha de anotação

    total = _inteiro(campo("capacidade_total"))
    pcd = _inteiro(campo("capacidade_pcd"), 0) or 0
    alunos = _inteiro(campo("capacidade_alunos"))
    monitora = _sim(campo("monitora"), padrao=True)

    if alunos is None:
        alunos = _deduzir_alunos(total, pcd, monitora)
        if alunos is None:
            resultado.problema(
                numero, "capacidade", f"total={total} pcd={pcd}",
                "Não sei quantos alunos cabem neste veículo.",
                "Informe “capacidade alunos” (alunos sentados, já sem "
                "motorista e monitora) ou “capacidade total”. Sem isso o "
                "carro não entra no plano.")
            return None
        conta = [f"{total} lugares", "menos o motorista"]
        if monitora:
            conta.append("menos a monitora")
        if pcd:
            conta.append(f"menos {pcd * ASSENTOS_POR_CADEIRA} assentos que as "
                         f"{pcd} cadeiras de rodas ocupam")
            conta.append(f"mais as {pcd} posições de cadeira")
        resultado.problema(
            numero, "capacidade_alunos", str(total),
            "Capacidade de alunos não informada.",
            f"Deduzi {alunos}: " + ", ".join(conta) + ". Confira — este número "
            "é o que decide o tamanho da frota.", "aviso")
    elif total:
        _conferir_conta(total, pcd, alunos, monitora, numero, resultado)

    if alunos <= 0:
        resultado.problema(
            numero, "capacidade_alunos", str(alunos),
            "Veículo sem lugar para aluno nenhum.",
            "Confira a capacidade: com este número o carro não transporta "
            "ninguém e o plano ficaria impossível.")
        return None

    return Veiculo(
        placa=placa, tipo_nome=tipo or _nome_do_tipo(alunos, pcd),
        capacidade_alunos=alunos, capacidade_pcd=pcd,
        capacidade_total=total or 0, monitora=monitora,
        contrato=campo("contrato"), garagem=campo("garagem"),
        turnos=_turnos(campo("turnos")), ativo=_sim(campo("ativo"), True),
        custo_km=_decimal(campo("custo_km"), CUSTO_KM_PADRAO),
        custo_mes=_decimal(campo("custo_mes"), CUSTO_MES_PADRAO),
        consumo_km_l=_decimal(campo("consumo"), CONSUMO_PADRAO),
        linha_planilha=numero)


def _deduzir_alunos(total, pcd, monitora):
    """Quantos alunos sentados sobram nos lugares homologados.

    Conta: total − motorista − monitora − assentos que as cadeiras ocupam,
    e depois soma de volta as próprias posições de cadeira, porque cadeirante
    também é aluno transportado.
    """
    if not total:
        return None
    livres = total - 1 - (1 if monitora else 0) - pcd * ASSENTOS_POR_CADEIRA
    return max(0, livres) + pcd


def _conferir_conta(total, pcd, alunos, monitora, numero, resultado):
    esperado = _deduzir_alunos(total, pcd, monitora)
    if esperado is None or alunos == esperado:
        return
    # A confusão mais provável, e a mais cara: "capacidade alunos" contando só
    # os sentados, sem os cadeirantes. Num carro de 2 cadeiras + 4 assentos,
    # isso tira 2 alunos de cada carro e inventa frota que não falta.
    if pcd and alunos == esperado - pcd:
        resultado.problema(
            numero, "capacidade_alunos", str(alunos),
            "Parece que os cadeirantes ficaram de fora da capacidade.",
            f"“Capacidade alunos” é o total que o carro transporta, cadeirante "
            f"incluído: aqui seriam {esperado} ({alunos} sentados + {pcd} em "
            f"cadeira). Se {alunos} for mesmo o total, ignore este aviso — mas "
            f"cada aluno a menos por carro vira frota a mais no plano.",
            "aviso")
        return
    resultado.problema(
        numero, "capacidade", f"total={total}, alunos={alunos}, pcd={pcd}",
        "A conta de lugares não fecha.",
        f"Com {total} lugares, motorista"
        + (", monitora" if monitora else "")
        + (f" e {pcd} cadeira(s) de rodas" if pcd else "")
        + f", eu esperava {esperado} alunos, e a planilha diz {alunos}. Usei o "
          f"que a planilha diz — mas confira, porque este número é o que "
          f"decide o tamanho da frota.", "aviso")


def _nome_do_tipo(alunos, pcd) -> str:
    if pcd:
        return f"Veículo {alunos} alunos ({pcd} cadeirante)"
    return f"Veículo {alunos} alunos"


# ---------------------------------------------------- ponte com o motor ----
def tipos_e_composicao(veiculos: list, prefixo: str = "F"):
    """Veículos com placa -> (tipos, composição, placas por tipo).

    O motor raciocina em tipo + quantidade; a operação raciocina em placa.
    Esta função é a tradução, e ela guarda o caminho de volta: cada tipo sabe
    quais placas o compõem, senão o plano sai sem dizer qual carro faz o quê.
    """
    tipos, composicao, placas = [], {}, {}
    por_configuracao = {}
    for v in veiculos:
        if not v.ativo:
            continue
        chave = v.configuracao
        if chave not in por_configuracao:
            ident = f"{prefixo}{len(por_configuracao) + 1}"
            por_configuracao[chave] = ident
            tipos.append(TipoVeiculo(
                id=ident, nome=v.tipo_nome or _nome_do_tipo(
                    v.capacidade_alunos, v.capacidade_pcd),
                capacidade=v.capacidade_alunos,
                posicoes_cadeirante=v.capacidade_pcd,
                custo_km=v.custo_km, custo_fixo_mes=v.custo_mes,
                consumo_km_l=v.consumo_km_l))
        ident = por_configuracao[chave]
        composicao[ident] = composicao.get(ident, 0) + 1
        placas.setdefault(ident, []).append(v.placa or "(sem placa)")
    return tipos, composicao, placas


COLUNAS_DO_MODELO = [
    "Placa", "Tipo/modelo", "Capacidade total", "Capacidade PCD",
    "Capacidade alunos", "Monitora", "Turnos", "Contrato", "Garagem (CEP)",
    "Ativo", "Custo km", "Custo mês", "Consumo km/l",
]

COMO_PREENCHER = [
    ["Coluna", "Obrigatória?", "O que escrever"],
    ["Placa", "sim", "ABC1D23 ou ABC-1234. Sem ela não dá para medir km por "
                     "carro nem conferir contrato."],
    ["Tipo/modelo", "sim", "Texto livre: “Van 12 lugares acessível”. Só serve "
                           "para o relatório ficar legível."],
    ["Capacidade total", "sim", "Lugares homologados no documento do veículo, "
                               "contando o motorista."],
    ["Capacidade PCD", "sim", "Quantas cadeiras de rodas o carro prende ao "
                             "mesmo tempo. 0 se não for acessível."],
    ["Capacidade alunos", "sim", "Alunos que o carro leva ao todo, CADEIRANTE "
                                "INCLUÍDO, já sem motorista e sem monitora. "
                                "É o número que decide o tamanho da frota."],
    ["Monitora", "não", "sim/não. Padrão sim. Só é usada para conferir a conta "
                        "de lugares."],
    ["Turnos", "não", "manhã, tarde, ambos. Vazio = o carro pode fazer "
                      "qualquer turno."],
    ["Contrato", "não", "Número do contrato ou lote. Separa a operação por "
                        "fornecedor no plano e na fiscalização."],
    ["Garagem (CEP)", "não", "De onde o carro sai. Muda a rota de verdade: "
                             "sem isso assumimos a garagem única."],
    ["Ativo", "não", "sim/não, ou “manutenção”. Carro parado não entra no "
                     "plano, mas continua no cadastro."],
    ["Custo km", "não", "R$ por km rodado (combustível + manutenção). Sem "
                        "isso a economia sai em carros, não em reais."],
    ["Custo mês", "não", "R$ fixos por mês do veículo, ou o valor mensal que "
                         "o contrato paga por ele."],
    ["Consumo km/l", "não", "Para o cálculo de diesel e de CO₂."],
    [],
    ["Uma linha por carro.", "", "Se dois carros são idênticos, mesmo assim "
                                 "escreva as duas linhas, com as duas placas."],
]


def modelo_de_planilha(caminho: str) -> str:
    """Gera o arquivo em branco para o município preencher.

    Vem com duas linhas de exemplo — preenchidas com valores plausíveis, para
    que ninguém precise adivinhar o formato — e uma aba explicando coluna por
    coluna. Apague as linhas de exemplo antes de mandar de volta.
    """
    from dados.planilha_exemplo import escrever_xlsx

    exemplo = [
        ["ABC1D23", "Van 12 lugares acessível", "12", "2", "6", "sim",
         "ambos", "01/2025", "04416-200", "sim", "1,95", "10200,00", "6,0"],
        ["XYZ2E45", "Micro-ônibus 20 lugares", "20", "0", "18", "sim",
         "manhã", "01/2025", "04416-200", "sim", "2,40", "13500,00", "4,5"],
    ]
    return escrever_xlsx(caminho, {
        "Frota": [["EXEMPLO — apague estas duas linhas antes de enviar"],
                  COLUNAS_DO_MODELO] + exemplo,
        "Como preencher": COMO_PREENCHER,
    })


def cabe_a_demanda(veiculos: list, alunos_por_turno: dict,
                   cadeirantes_por_turno: dict, viagens_por_veiculo: int = 1):
    """A frota declarada dá conta da demanda? Turno a turno, sem roteirizar.

    É a conferência que se faz ANTES de chamar o motor: se a frota não cabe
    nem na conta de assentos, o solver vai rodar minutos para descobrir o
    óbvio, e a resposta certa é dizer quantos carros faltam.
    """
    ativos = [v for v in veiculos if v.ativo]
    saida = {}
    for turno, quantos in alunos_por_turno.items():
        doturno = [v for v in ativos if not v.turnos or turno in v.turnos]
        cadeirantes = cadeirantes_por_turno.get(turno, 0)
        lugares = sum(v.capacidade_alunos for v in doturno) * viagens_por_veiculo
        posicoes = sum(v.capacidade_pcd for v in doturno) * viagens_por_veiculo
        faltam_lugares = max(0, quantos - lugares)
        faltam_posicoes = max(0, cadeirantes - posicoes)
        saida[turno] = {
            "alunos": quantos, "cadeirantes": cadeirantes,
            "veiculos_no_turno": len(doturno),
            "lugares_ofertados": lugares, "posicoes_ofertadas": posicoes,
            "cabe": not faltam_lugares and not faltam_posicoes,
            "faltam_lugares": faltam_lugares,
            "faltam_posicoes_cadeirante": faltam_posicoes,
            # o que limita: assento ou posição de cadeira. Os dois exigem
            # veículos diferentes, e confundir os dois é o erro clássico
            "limita": ("posição de cadeira de rodas" if faltam_posicoes
                       else ("assento" if faltam_lugares else None)),
        }
    return saida
