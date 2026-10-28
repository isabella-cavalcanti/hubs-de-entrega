"""Gera os dados FICTÍCIOS usados no projeto.

As coordenadas dos bairros são aproximadas (centro do bairro).
Demanda, custos e capacidades são inventados, com uma semente fixa
para que o resultado seja sempre o mesmo.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEMENTE = 42
PASTA = Path(__file__).parent

# nome, latitude, longitude, perfil (1 = mais denso / mais pedidos)
BAIRROS = [
    ("Pinheiros", -23.5670, -46.6930, 1.0),
    ("Vila Madalena", -23.5530, -46.6910, 0.9),
    ("Itaim Bibi", -23.5850, -46.6780, 1.0),
    ("Moema", -23.6010, -46.6650, 0.9),
    ("Vila Mariana", -23.5890, -46.6340, 0.9),
    ("Bela Vista", -23.5610, -46.6460, 0.8),
    ("Consolação", -23.5540, -46.6590, 0.8),
    ("Perdizes", -23.5370, -46.6780, 0.8),
    ("Lapa", -23.5220, -46.7040, 0.6),
    ("Butantã", -23.5710, -46.7230, 0.5),
    ("Morumbi", -23.6000, -46.7200, 0.5),
    ("Campo Belo", -23.6230, -46.6690, 0.6),
    ("Brooklin", -23.6150, -46.6930, 0.7),
    ("Santo Amaro", -23.6540, -46.7090, 0.6),
    ("Saúde", -23.6180, -46.6380, 0.6),
    ("Ipiranga", -23.5890, -46.6070, 0.6),
    ("Aclimação", -23.5720, -46.6290, 0.6),
    ("Liberdade", -23.5580, -46.6350, 0.7),
    ("Sé", -23.5500, -46.6340, 0.5),
    ("República", -23.5430, -46.6420, 0.7),
    ("Santa Cecília", -23.5370, -46.6510, 0.7),
    ("Barra Funda", -23.5250, -46.6650, 0.5),
    ("Bom Retiro", -23.5260, -46.6390, 0.4),
    ("Santana", -23.5020, -46.6250, 0.6),
    ("Tucuruvi", -23.4800, -46.6030, 0.4),
    ("Casa Verde", -23.5070, -46.6560, 0.4),
    ("Freguesia do Ó", -23.4990, -46.6970, 0.4),
    ("Mooca", -23.5600, -46.5990, 0.7),
    ("Brás", -23.5440, -46.6160, 0.4),
    ("Belém", -23.5410, -46.5900, 0.4),
    ("Tatuapé", -23.5400, -46.5760, 0.8),
    ("Vila Prudente", -23.5850, -46.5800, 0.5),
    ("Penha", -23.5270, -46.5430, 0.5),
    ("Vila Formosa", -23.5650, -46.5450, 0.4),
    ("Jabaquara", -23.6430, -46.6430, 0.5),
    ("Cambuci", -23.5680, -46.6180, 0.4),
    ("Jardim Paulista", -23.5710, -46.6640, 1.0),
    ("Vila Olímpia", -23.5960, -46.6850, 0.9),
    ("Higienópolis", -23.5450, -46.6560, 0.7),
    ("Água Branca", -23.5240, -46.6870, 0.4),
]

# bairros onde existe um imóvel disponível para virar hub
# nome, aluguel + operação por dia (R$), capacidade (pedidos/dia)
CANDIDATOS = [
    ("Pinheiros", 2600, 750),
    ("Itaim Bibi", 3000, 750),
    ("Vila Mariana", 2200, 700),
    ("Consolação", 2400, 650),
    ("Lapa", 1500, 650),
    ("Santo Amaro", 1600, 700),
    ("Saúde", 1700, 600),
    ("Mooca", 1700, 700),
    ("Tatuapé", 1800, 700),
    ("Santana", 1500, 650),
    ("Barra Funda", 1400, 750),
    ("Brooklin", 2100, 650),
    ("Penha", 1200, 550),
    ("Butantã", 1400, 550),
]


def gerar():
    rng = np.random.default_rng(SEMENTE)
    bairros = pd.DataFrame(BAIRROS, columns=["bairro", "lat", "lon", "perfil"])
    # pedidos por dia: base proporcional ao perfil + ruído
    bairros["pedidos_dia"] = (
        bairros["perfil"] * rng.normal(170, 20, len(bairros))
    ).round().astype(int)
    bairros = bairros.drop(columns="perfil")

    pos = bairros.set_index("bairro")[["lat", "lon"]]
    cand = pd.DataFrame(CANDIDATOS, columns=["hub", "custo_dia", "capacidade"])
    cand["lat"] = cand["hub"].map(pos["lat"])
    cand["lon"] = cand["hub"].map(pos["lon"])

    bairros.to_csv(PASTA / "bairros.csv", index=False)
    cand.to_csv(PASTA / "candidatos.csv", index=False)
    print(f"{len(bairros)} bairros, {bairros.pedidos_dia.sum()} pedidos/dia, "
          f"{len(cand)} candidatos a hub")


if __name__ == "__main__":
    gerar()
