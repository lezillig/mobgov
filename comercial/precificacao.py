# -*- coding: utf-8 -*-
"""
MOBGOV — Sprint 10 · agent-comercial (etapa 1)
Do plano ao PREÇO: quanto custa operar, e por quanto vender.

O motor responde "essa demanda se atende com 7 veículos e 16 motoristas". A
pergunta seguinte, na mesa de quem vende fretamento, é outra: **por quanto eu
proponho?** — e é ela que decide a concorrência.

A conta é a que uma operadora faz na planilha, aberta linha a linha:

    custo direto      veículo (capital e posse), combustível, manutenção,
                      motorista (salário + encargos + benefícios), monitor
    custo indireto    garagem, supervisão, rastreamento, seguro de RC,
                      administrativo — declarados por veículo ou em %
    ------------------------------------------------------------------
    custo total
    impostos + margem entram por DIVISÃO, não por soma
    preço = custo / (1 − impostos − margem)

A divisão é o detalhe que separa proposta de prejuízo. Somar 12% de margem
sobre o custo e depois pagar 14,25% de imposto sobre a receita deixa margem
real negativa; dividir devolve o preço que de fato entrega a margem.

Nada aqui é chutado dentro do código: alíquotas, encargos, benefícios e
indiretos são PARÂMETROS com padrão declarado, e todos aparecem na proposta
para a contabilidade da empresa conferir. O sistema não sabe o regime
tributário do cliente — ele deixa isso na cara.
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from painel import economia as economia_mod  # noqa: E402
from painel.formato import numero as _numero_ptbr  # noqa: E402


def _reais(valor: float, casas: int = 2) -> str:
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {_numero_ptbr(abs(valor), casas)}"

# Regimes tributários mais comuns em fretamento. São PARÂMETROS declarados:
# a alíquota efetiva depende do município (ISS), do enquadramento e dos
# créditos — quem confere é a contabilidade, não o software.
REGIMES = {
    "simples": {
        "nome": "Simples Nacional (anexo III, faixa média)",
        "aliquota_sobre_receita": 0.1450,
        "observacao": "Alíquota efetiva do Simples varia com o faturamento "
                      "dos últimos 12 meses; confirme a faixa com a "
                      "contabilidade.",
    },
    "presumido": {
        "nome": "Lucro Presumido",
        # PIS 0,65 + COFINS 3,00 + ISS 5,00 + IRPJ/CSLL sobre presunção de 32%
        "aliquota_sobre_receita": 0.1493,
        "observacao": "PIS/COFINS cumulativos, ISS conforme o município "
                      "(usado 5%) e IRPJ/CSLL sobre presunção de 32%.",
    },
    "sem_imposto": {
        "nome": "Sem impostos (uso interno)",
        "aliquota_sobre_receita": 0.0,
        "observacao": "Só para custo interno — não use em proposta.",
    },
}


@dataclass
class Premissas:
    """Tudo o que entra no preço e não vem do motor."""
    regime: str = "presumido"
    margem_alvo: float = 0.12              # 12% sobre a receita
    encargos_sobre_salario: float = 0.68   # INSS, FGTS, férias, 13º, provisões
    beneficios_motorista_mes: float = 900.0   # VT, VR, plano, uniforme
    monitores: int = 0                     # exigidos em algumas operações
    salario_monitor_mes: float = 1800.0
    custo_garagem_por_veiculo_mes: float = 850.0
    custo_rastreamento_por_veiculo_mes: float = 120.0
    custo_seguro_rc_por_veiculo_mes: float = 380.0
    supervisao_por_veiculo_mes: float = 600.0
    administrativo_pct: float = 0.06       # sobre o custo direto
    reserva_tecnica_pct: float = 0.08      # frota reserva e imprevisto
    dias_operacao_mes: int = None          # None = usa o do plano
    preco_diesel_l: float = None           # None = usa o do plano

    def como_dicionario(self) -> dict:
        return asdict(self)


@dataclass
class Linha:
    """Uma linha da planilha de custo, com a conta escrita por extenso."""
    grupo: str
    item: str
    valor_mes: float
    memoria: str = ""

    def como_dicionario(self) -> dict:
        return {"grupo": self.grupo, "item": self.item,
                "valor_mes": round(self.valor_mes, 2), "memoria": self.memoria}


@dataclass
class Orcamento:
    linhas: list = field(default_factory=list)
    premissas: dict = field(default_factory=dict)
    indicadores: dict = field(default_factory=dict)

    def grupo(self, nome: str) -> float:
        return round(sum(l.valor_mes for l in self.linhas
                         if l.grupo == nome), 2)

    @property
    def custo_direto(self) -> float:
        return self.grupo("Veículo") + self.grupo("Rodagem") + self.grupo("Equipe")

    @property
    def custo_indireto(self) -> float:
        return self.grupo("Indiretos")

    @property
    def custo_total(self) -> float:
        return round(self.custo_direto + self.custo_indireto, 2)


def _tipos_do_plano(plano: dict) -> dict:
    return plano["premissas"]["custos_por_tipo"]


def _km_por_tipo(plano: dict) -> dict:
    """Km/dia de cada tipo — o mesmo rateio auditável do painel."""
    frota = plano["frota_otimizada"]
    veiculos = frota.get("veiculos") or []
    viagens_por_rota = plano["premissas"].get("viagens_por_rota", 2)
    if veiculos:
        return economia_mod._km_por_tipo_dos_veiculos(veiculos, viagens_por_rota)
    return economia_mod._km_rateado(frota["composicao"], frota["km_dia"])


def orcar(plano: dict, premissas: Premissas = None) -> Orcamento:
    """Monta a planilha de custo mensal da operação descrita no plano."""
    premissas = premissas or Premissas()
    p = plano["premissas"]
    tipos = _tipos_do_plano(plano)
    composicao = plano["frota_otimizada"]["composicao"]
    dias = premissas.dias_operacao_mes or p["dias_letivos_mes"]
    diesel = premissas.preco_diesel_l or p["preco_diesel_l"]
    diesel_base = p.get("preco_diesel_base_l", p["preco_diesel_l"])
    km_por_tipo = _km_por_tipo(plano)
    orcamento = Orcamento()

    # --- veículo: posse (depreciação, seguro, IPVA, licenciamento) -----------
    for tipo_id, quantidade in sorted(composicao.items()):
        tipo = tipos[tipo_id]
        # o custo fixo do perfil de fretamento é só do veículo; no escolar ele
        # já embute motorista, e por isso a equipe entra zerada mais abaixo
        valor = float(tipo["fixo_mes"]) * quantidade
        orcamento.linhas.append(Linha(
            "Veículo", f"{quantidade}× {tipo['nome']}", valor,
            f"{quantidade} × {_reais(tipo['fixo_mes'])}/mês (posse do veículo)"))

    # --- rodagem: combustível e manutenção, separados ------------------------
    for tipo_id, quantidade in sorted(composicao.items()):
        tipo = tipos[tipo_id]
        km_mes = km_por_tipo.get(tipo_id, 0.0) * dias
        litros = km_mes / float(tipo["consumo_km_l"])
        combustivel = litros * diesel
        manutencao = km_mes * economia_mod.manutencao_km(tipo, diesel_base)
        orcamento.linhas.append(Linha(
            "Rodagem", f"Combustível — {tipo['nome']}", combustivel,
            f"{_numero_ptbr(km_mes)} km/mês ÷ {tipo['consumo_km_l']} km/l × "
            f"{_reais(diesel)}/l = {_numero_ptbr(litros)} litros"))
        orcamento.linhas.append(Linha(
            "Rodagem", f"Manutenção e pneus — {tipo['nome']}", manutencao,
            f"{_numero_ptbr(km_mes)} km/mês × "
            f"{_reais(economia_mod.manutencao_km(tipo, diesel_base))}/km"))

    # --- equipe: motoristas e monitores --------------------------------------
    equipe = plano.get("equipe") or {}
    motoristas = (equipe.get("resumo") or {}).get("motoristas", 0)
    salario = (equipe.get("custo_motorista_mes")
               or plano.get("perfil", {}).get("custo_motorista_mes") or 0.0)
    if motoristas and salario:
        folha = motoristas * salario
        encargos = folha * premissas.encargos_sobre_salario
        beneficios = motoristas * premissas.beneficios_motorista_mes
        orcamento.linhas.append(Linha(
            "Equipe", f"{motoristas} motoristas — salário", folha,
            f"{motoristas} × {_reais(salario)}/mês (escala calculada pela "
            f"jornada, não pelo número de veículos)"))
        orcamento.linhas.append(Linha(
            "Equipe", "Encargos sobre a folha", encargos,
            f"{premissas.encargos_sobre_salario:.0%} sobre {_reais(folha)}"))
        orcamento.linhas.append(Linha(
            "Equipe", "Benefícios (VT, VR, saúde, uniforme)", beneficios,
            f"{motoristas} × {_reais(premissas.beneficios_motorista_mes)}"))
    if premissas.monitores:
        folha_monitor = premissas.monitores * premissas.salario_monitor_mes
        orcamento.linhas.append(Linha(
            "Equipe", f"{premissas.monitores} monitores",
            folha_monitor * (1 + premissas.encargos_sobre_salario),
            f"{premissas.monitores} × {_reais(premissas.salario_monitor_mes)} "
            f"+ {premissas.encargos_sobre_salario:.0%} de encargos"))

    # --- indiretos ------------------------------------------------------------
    veiculos = sum(composicao.values())
    for rotulo, valor_unitario in (
            ("Garagem e pátio", premissas.custo_garagem_por_veiculo_mes),
            ("Rastreamento e telemetria", premissas.custo_rastreamento_por_veiculo_mes),
            ("Seguro de responsabilidade civil", premissas.custo_seguro_rc_por_veiculo_mes),
            ("Supervisão e despacho", premissas.supervisao_por_veiculo_mes)):
        if valor_unitario:
            orcamento.linhas.append(Linha(
                "Indiretos", rotulo, veiculos * valor_unitario,
                f"{veiculos} veículos × {_reais(valor_unitario)}/mês"))

    direto = orcamento.custo_direto
    if premissas.administrativo_pct:
        orcamento.linhas.append(Linha(
            "Indiretos", "Administrativo e estrutura",
            direto * premissas.administrativo_pct,
            f"{premissas.administrativo_pct:.0%} sobre o custo direto "
            f"({_reais(direto)})"))
    if premissas.reserva_tecnica_pct:
        orcamento.linhas.append(Linha(
            "Indiretos", "Reserva técnica (frota reserva e imprevistos)",
            direto * premissas.reserva_tecnica_pct,
            f"{premissas.reserva_tecnica_pct:.0%} sobre o custo direto — "
            f"veículo quebra, motorista falta, e a operação não pode parar"))

    orcamento.premissas = premissas.como_dicionario()
    orcamento.premissas.update({
        "dias_operacao_mes": dias, "preco_diesel_l": diesel,
        "veiculos": veiculos, "motoristas": motoristas,
        "km_dia": plano["frota_otimizada"]["km_dia"],
        "passageiros": plano["demanda"]["alunos"],
    })
    return orcamento


def precificar(plano: dict, premissas: Premissas = None) -> dict:
    """Custo, preço e os indicadores que a proposta mostra."""
    premissas = premissas or Premissas()
    orcamento = orcar(plano, premissas)
    regime = REGIMES.get(premissas.regime, REGIMES["presumido"])
    carga = regime["aliquota_sobre_receita"]
    margem = premissas.margem_alvo

    custo = orcamento.custo_total
    divisor = 1.0 - carga - margem
    if divisor <= 0:
        raise ValueError(
            f"Imposto ({carga:.1%}) mais margem ({margem:.1%}) chegam a 100% "
            f"da receita: não existe preço que feche essa conta.")
    preco = custo / divisor
    impostos = preco * carga
    lucro = preco * margem

    dias = orcamento.premissas["dias_operacao_mes"]
    veiculos = max(1, orcamento.premissas["veiculos"])
    passageiros = max(1, orcamento.premissas["passageiros"])
    motoristas = max(1, orcamento.premissas.get("motoristas") or 1)
    km_mes = orcamento.premissas["km_dia"] * dias

    # margem real de quem soma a margem ao custo em vez de dividir:
    # lucro/preço = (1 − carga) − custo/preço, com preço = custo × (1 + margem)
    margem_somada = (1 - carga) - 1 / (1 + margem)

    # Por que o preço é o que é — a primeira pergunta de quem recebe a proposta
    ocupacoes = [v.get("ocupacao_media_pct") for v
                 in plano["frota_otimizada"].get("veiculos", [])
                 if v.get("ocupacao_media_pct") is not None]
    indicadores = {
        "participacao_no_custo_pct": {
            grupo: round(100 * orcamento.grupo(grupo) / custo, 1)
            for grupo in ("Veículo", "Rodagem", "Equipe", "Indiretos")},
        "passageiros_por_veiculo": round(passageiros / veiculos, 1),
        "passageiros_por_motorista": round(passageiros / motoristas, 1),
        "km_por_passageiro_dia": round(
            orcamento.premissas["km_dia"] / passageiros, 2),
        "ocupacao_media_das_viagens_pct": round(
            sum(ocupacoes) / len(ocupacoes), 1) if ocupacoes else None,
    }


    return {
        "custo": {
            "direto": orcamento.custo_direto,
            "indireto": orcamento.custo_indireto,
            "total_mes": custo,
            "por_grupo": {g: orcamento.grupo(g)
                          for g in ("Veículo", "Rodagem", "Equipe", "Indiretos")},
            "linhas": [l.como_dicionario() for l in orcamento.linhas],
        },
        "preco": {
            "mes": round(preco, 2),
            "ano": round(preco * 12, 2),
            "dia": round(preco / dias, 2),
            "por_veiculo_mes": round(preco / veiculos, 2),
            "por_passageiro_mes": round(preco / passageiros, 2),
            "por_km": round(preco / km_mes, 2) if km_mes else 0.0,
            "impostos_mes": round(impostos, 2),
            "lucro_mes": round(lucro, 2),
            "margem_alvo_pct": round(margem * 100, 2),
            "carga_tributaria_pct": round(carga * 100, 2),
            "regime": regime["nome"],
            "observacao_tributaria": regime["observacao"],
        },
        "premissas": orcamento.premissas,
        "indicadores": indicadores,
        "memoria": [
            f"Custo direto: {_reais(orcamento.custo_direto)}/mês "
            f"(veículo, rodagem e equipe).",
            f"Custo indireto: {_reais(orcamento.custo_indireto)}/mês "
            f"(garagem, supervisão, rastreamento, seguro, administrativo e "
            f"reserva técnica).",
            f"Preço = custo ÷ (1 − {carga:.2%} de impostos − {margem:.2%} de "
            f"margem) = {_reais(preco)}/mês.",
            # A conta abaixo é a razão de existir a divisão. Com esta carga
            # tributária, somar a margem ao custo entrega margem NEGATIVA — o
            # erro clássico de quem faz proposta na planilha do jeito rápido.
            f"Pelo caminho errado (custo × 1 + margem = "
            f"{_reais(custo * (1 + margem))}), a margem real seria "
            f"{margem_somada:.2%}: o imposto incide sobre a receita, não "
            f"sobre o custo.",
        ],
    }


def sensibilidade(plano: dict, premissas: Premissas = None) -> list:
    """E se o diesel subir? E se a margem cair? — o que o cliente vai perguntar.

    Cada cenário reprecifica do zero, com a mesma função. Nenhum número aqui é
    interpolado: são preços de verdade, calculados de novo.
    """
    premissas = premissas or Premissas()
    base = precificar(plano, premissas)
    diesel_base = base["premissas"]["preco_diesel_l"]
    cenarios = []

    def variar(rotulo, **campos):
        alteradas = Premissas(**{**premissas.como_dicionario(), **campos})
        resultado = precificar(plano, alteradas)
        cenarios.append({
            "cenario": rotulo,
            "preco_mes": resultado["preco"]["mes"],
            "custo_mes": resultado["custo"]["total_mes"],
            "diferenca_mes": round(resultado["preco"]["mes"]
                                   - base["preco"]["mes"], 2),
            "diferenca_pct": round(
                100 * (resultado["preco"]["mes"] / base["preco"]["mes"] - 1), 2),
        })

    cenarios.append({
        "cenario": "Proposta base", "preco_mes": base["preco"]["mes"],
        "custo_mes": base["custo"]["total_mes"], "diferenca_mes": 0.0,
        "diferenca_pct": 0.0})
    variar(f"Diesel +10% (R$ {diesel_base * 1.1:,.2f}/l)",
           preco_diesel_l=round(diesel_base * 1.1, 2))
    variar(f"Diesel +25% (R$ {diesel_base * 1.25:,.2f}/l)",
           preco_diesel_l=round(diesel_base * 1.25, 2))
    variar("Margem de 8% em vez de 12%", margem_alvo=0.08)
    variar("Margem de 18%", margem_alvo=0.18)
    variar("Regime Simples Nacional", regime="simples")
    return cenarios
