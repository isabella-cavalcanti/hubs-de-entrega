"""Modelo de otimização (MILP) para escolher onde abrir hubs de entrega.

Problema de localização de facilidades com capacidade:
  - y[j] = 1 se o hub j for aberto
  - x[i, j] = 1 se o bairro i for atendido pelo hub j

Minimiza:  custo fixo dos hubs abertos + custo de deslocamento dos entregadores
Sujeito a: todo bairro atendido por um hub, só por hubs abertos,
           dentro do tempo máximo de entrega (SLA) e da capacidade de cada hub.
"""
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import pandas as pd
import pulp

DADOS = Path(__file__).resolve().parent.parent / "dados"

FATOR_RUA = 1.35       # a rua não é linha reta: distância real ≈ 1,35 × a reta
PREPARO_MIN = 10       # minutos entre o pedido chegar ao hub e sair para entrega
PENALIDADE = 1_000     # R$ por pedido não atendido (o modelo evita ao máximo)


def SOLVER():
    if "HiGHS" in pulp.listSolvers(onlyAvailable=True):
        return pulp.HiGHS(msg=False, timeLimit=8, gapRel=0.001)
    return pulp.PULP_CBC_CMD(msg=0, timeLimit=8, gapRel=0.001)


@dataclass
class Parametros:
    sla_min: int = 30             # tempo máximo de entrega (minutos)
    custo_km: float = 1.20        # R$ por km rodado pelo entregador
    velocidade_kmh: float = 22.0  # velocidade média de moto na cidade
    max_hubs: int | None = None   # limite de hubs (None = sem limite)
    fator_demanda: float = 1.0    # 1.3 = simular um pico de 30% a mais
    forcar_abertos: tuple = ()
    forcar_fechados: tuple = ()


@dataclass
class Resultado:
    status: str
    custo_total: float
    custo_fixo: float
    custo_entrega: float
    hubs: pd.DataFrame          # um registro por candidato
    alocacao: pd.DataFrame      # um registro por bairro
    params: Parametros
    contrafactuais: dict = field(default_factory=dict)


def carregar_dados():
    return pd.read_csv(DADOS / "bairros.csv"), pd.read_csv(DADOS / "candidatos.csv")


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def matriz_distancias(bairros, cand, p: Parametros):
    linhas = []
    for _, b in bairros.iterrows():
        for _, h in cand.iterrows():
            km = _haversine_km(b.lat, b.lon, h.lat, h.lon) * FATOR_RUA
            minutos = PREPARO_MIN + km / p.velocidade_kmh * 60
            linhas.append((b.bairro, h.hub, round(km, 2), round(minutos, 1)))
    return pd.DataFrame(linhas, columns=["bairro", "hub", "km", "minutos"])


def otimizar(p: Parametros = Parametros(), bairros=None, cand=None,
             calcular_contrafactuais=True) -> Resultado:
    if bairros is None:
        bairros, cand = carregar_dados()
    bairros = bairros.copy()
    bairros["pedidos_dia"] = (bairros["pedidos_dia"] * p.fator_demanda).round()

    dist = matriz_distancias(bairros, cand, p)
    viaveis = dist[dist.minutos <= p.sla_min]
    demanda = bairros.set_index("bairro")["pedidos_dia"].to_dict()
    custo = cand.set_index("hub")["custo_dia"].to_dict()
    cap = cand.set_index("hub")["capacidade"].to_dict()
    arcos = list(zip(viaveis.bairro, viaveis.hub))
    km = {(r.bairro, r.hub): r.km for r in viaveis.itertuples()}

    m = pulp.LpProblem("hubs_de_entrega", pulp.LpMinimize)
    y = pulp.LpVariable.dicts("abre", custo.keys(), cat="Binary")
    x = pulp.LpVariable.dicts("atende", arcos, cat="Binary")
    falta = pulp.LpVariable.dicts("nao_atendido", demanda.keys(), cat="Binary")

    m += (
        pulp.lpSum(custo[j] * y[j] for j in custo)
        + pulp.lpSum(2 * demanda[i] * p.custo_km * km[i, j] * x[i, j]  # ida e volta
                     for i, j in arcos)
        + pulp.lpSum(PENALIDADE * demanda[i] * falta[i] for i in demanda)
    )
    for i in demanda:  # cada bairro: um hub (ou fica sem atendimento)
        m += pulp.lpSum(x[a] for a in arcos if a[0] == i) + falta[i] == 1
    for i, j in arcos:  # só hubs abertos atendem
        m += x[i, j] <= y[j]
    for j in custo:  # capacidade
        m += pulp.lpSum(demanda[i] * x[i, jj] for i, jj in arcos if jj == j) <= cap[j] * y[j]
    if p.max_hubs:
        m += pulp.lpSum(y.values()) <= p.max_hubs
    for j in p.forcar_abertos:
        m += y[j] == 1
    for j in p.forcar_fechados:
        m += y[j] == 0

    m.solve(SOLVER())
    status = pulp.LpStatus[m.status]
    if status == "Not Solved" and pulp.value(m.objective) is not None:
        status = "Optimal"  # parou no limite de tempo com uma boa solução

    aloc = []
    for i in demanda:
        hub = next((j for (ii, j) in arcos if ii == i and x[ii, j].value() > 0.5), None)
        linha = dist[(dist.bairro == i) & (dist.hub == hub)] if hub else None
        aloc.append({
            "bairro": i,
            "pedidos_dia": int(demanda[i]),
            "hub": hub or "SEM ATENDIMENTO",
            "km": float(linha.km.iloc[0]) if hub else None,
            "minutos": float(linha.minutos.iloc[0]) if hub else None,
        })
    aloc = pd.DataFrame(aloc).merge(bairros[["bairro", "lat", "lon"]], on="bairro")

    hubs = cand.copy()
    hubs["aberto"] = hubs.hub.map(lambda j: y[j].value() > 0.5)
    carga = aloc.groupby("hub")["pedidos_dia"].sum()
    hubs["pedidos_dia"] = hubs.hub.map(carga).fillna(0).astype(int)
    hubs["ocupacao"] = (hubs.pedidos_dia / hubs.capacidade).round(3)
    hubs["bairros_atendidos"] = hubs.hub.map(aloc.groupby("hub").size()).fillna(0).astype(int)

    custo_fixo = float(hubs.loc[hubs.aberto, "custo_dia"].sum())
    atendidos = aloc[aloc.hub != "SEM ATENDIMENTO"]
    custo_entrega = float((atendidos.pedidos_dia * atendidos.km * p.custo_km * 2).sum())

    res = Resultado(status, custo_fixo + custo_entrega, custo_fixo, custo_entrega,
                    hubs, aloc, p)

    # "E se?": para cada hub, quanto o custo mudaria se a decisão fosse a contrária?
    # Isso dá à IA um motivo concreto, calculado, para cada decisão.
    if calcular_contrafactuais and status == "Optimal":
        base = _sem_fator(bairros, p)
        for r in hubs.itertuples():
            chave = "forcar_fechados" if r.aberto else "forcar_abertos"
            p2 = Parametros(**{**p.__dict__, chave: (r.hub,)})
            r2 = otimizar(p2, bairros=base, cand=cand, calcular_contrafactuais=False)
            sem_atend = int(r2.alocacao.loc[r2.alocacao.hub == "SEM ATENDIMENTO", "pedidos_dia"].sum())
            res.contrafactuais[r.hub] = {
                "custo_extra_dia": round(r2.custo_total - res.custo_total, 2),
                "pedidos_sem_atendimento": sem_atend,
            }
    return res


def _sem_fator(bairros, p):
    b = bairros.copy()
    b["pedidos_dia"] = b["pedidos_dia"] / p.fator_demanda
    return b


def resumo(res: Resultado) -> dict:
    """Resumo estruturado do resultado: é o que a IA recebe como contexto."""
    a = res.alocacao
    atend = a[a.hub != "SEM ATENDIMENTO"]
    total = a.pedidos_dia.sum()
    abertos = res.hubs[res.hubs.aberto]
    fechados = res.hubs[~res.hubs.aberto]
    return {
        "parametros": {
            "tempo_maximo_entrega_min": res.params.sla_min,
            "custo_por_km_R$": res.params.custo_km,
            "velocidade_media_kmh": res.params.velocidade_kmh,
            "limite_de_hubs": res.params.max_hubs,
            "fator_de_demanda": res.params.fator_demanda,
        },
        "status_otimizacao": res.status,
        "custo_total_dia_R$": round(res.custo_total, 2),
        "custo_fixo_hubs_dia_R$": round(res.custo_fixo, 2),
        "custo_entregas_dia_R$": round(res.custo_entrega, 2),
        "pedidos_dia_total": int(total),
        "pedidos_sem_atendimento": int(total - atend.pedidos_dia.sum()),
        "tempo_medio_entrega_min": round(
            float((atend.minutos * atend.pedidos_dia).sum() / max(atend.pedidos_dia.sum(), 1)), 1),
        "hubs_abertos": [
            {
                "hub": r.hub,
                "custo_dia_R$": r.custo_dia,
                "capacidade": r.capacidade,
                "pedidos_dia": r.pedidos_dia,
                "ocupacao_%": round(r.ocupacao * 100, 1),
                "bairros": a.loc[a.hub == r.hub, "bairro"].tolist(),
                "custo_extra_se_fechasse_R$_dia": res.contrafactuais.get(r.hub, {}).get("custo_extra_dia"),
                "pedidos_sem_atendimento_se_fechasse": res.contrafactuais.get(r.hub, {}).get("pedidos_sem_atendimento"),
            }
            for r in abertos.itertuples()
        ],
        "hubs_fechados": [
            {
                "hub": r.hub,
                "custo_dia_R$": r.custo_dia,
                "capacidade": r.capacidade,
                "custo_extra_se_abrisse_R$_dia": res.contrafactuais.get(r.hub, {}).get("custo_extra_dia"),
            }
            for r in fechados.itertuples()
        ],
        "bairros": a[["bairro", "pedidos_dia", "hub", "km", "minutos"]].to_dict("records"),
    }


if __name__ == "__main__":
    r = otimizar()
    print(r.status, round(r.custo_total, 2))
    print(r.hubs[r.hubs.aberto][["hub", "pedidos_dia", "capacidade", "ocupacao"]])
    print(r.contrafactuais)
