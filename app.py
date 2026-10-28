"""Dashboard: onde abrir hubs de entrega em São Paulo (dados fictícios)."""
import plotly.graph_objects as go
import streamlit as st

from src import ia
from src.modelo import Parametros, carregar_dados, otimizar, resumo

st.set_page_config(page_title="Hubs de entrega · Otimização + IA", page_icon="🛵", layout="wide")

VERMELHO = "#EA1D2C"
CINZA = "#9AA0A6"


def brl(v):
    return f"R$ {v:,.0f}".replace(",", ".")


def md(texto):
    """Escapa o $ para o Streamlit não tratar "R$ ... R$" como fórmula."""
    return texto.replace("$", "\\$")


def segredos():
    try:
        return dict(st.secrets)
    except Exception:
        return {}


@st.cache_data(show_spinner="Otimizando a rede de hubs…")
def rodar(sla, custo_km, max_hubs, fator):
    r = otimizar(Parametros(sla_min=sla, custo_km=custo_km,
                            max_hubs=max_hubs or None, fator_demanda=fator))
    return r, resumo(r)


# ---------- barra lateral ----------
with st.sidebar:
    st.header("⚙️ Cenário")
    sla = st.slider("Tempo máximo de entrega (min)", 20, 45, 30, step=5)
    custo_km = st.slider("Custo por km do entregador (R$)", 0.60, 2.00, 1.20, step=0.10)
    fator = st.select_slider("Demanda", options=[0.8, 1.0, 1.2, 1.3, 1.5], value=1.0,
                             format_func=lambda v: "normal" if v == 1 else f"{v:.0%} do normal")
    max_hubs = st.select_slider("Limite de hubs", options=[0, 8, 9, 10, 11, 12],
                                value=0, format_func=lambda v: "sem limite" if v == 0 else str(v))
    st.caption("Mude os parâmetros e o modelo recalcula a melhor rede.")
    prov = ia.provedor_disponivel(segredos())
    st.divider()
    st.caption(f"🤖 IA: **{prov.upper() if prov else 'modo demonstração'}**")

res, rs = rodar(sla, custo_km, max_hubs, fator)

# ---------- topo ----------
st.title("🛵 Onde abrir hubs de entrega?")
st.markdown("Otimização (MILP) decide **quais hubs abrir e quem atende cada bairro**; "
            "a **IA generativa** explica a decisão. *Dados fictícios.*")

if res.status != "Optimal":
    st.error("Não existe solução com esses parâmetros. Aumente o tempo máximo ou o limite de hubs.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Hubs abertos", f"{len(rs['hubs_abertos'])} de {len(res.hubs)}")
c2.metric("Custo por dia", brl(rs["custo_total_dia_R$"]))
c3.metric("Tempo médio de entrega", f"{rs['tempo_medio_entrega_min']:.1f} min".replace(".", ","))
falta = rs["pedidos_sem_atendimento"]
c4.metric("Pedidos fora do prazo", f"{falta}", delta=None if not falta else "atenção",
          delta_color="inverse")

aba_mapa, aba_ia, aba_resumo, aba_dados = st.tabs(
    ["🗺️ Rede de hubs", "💬 Pergunte à IA", "📄 Resumo executivo", "📊 Dados"])

# ---------- mapa ----------
with aba_mapa:
    a = res.alocacao
    hubs = res.hubs
    pos = hubs.set_index("hub")[["lat", "lon"]]
    fig = go.Figure()
    xs, ys = [], []
    for r in a[a.hub.isin(pos.index)].itertuples():
        xs += [r.lon, pos.loc[r.hub, "lon"], None]
        ys += [r.lat, pos.loc[r.hub, "lat"], None]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#F4A6AC", width=1),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=a.lon, y=a.lat, mode="markers", name="Bairros",
        marker=dict(size=a.pedidos_dia / 9, color="#3E3E3E", opacity=0.55),
        text=[f"<b>{r.bairro}</b><br>{r.pedidos_dia} pedidos/dia<br>hub: {r.hub}"
              + (f"<br>{r.minutos:.0f} min" if r.minutos else "") for r in a.itertuples()],
        hoverinfo="text"))
    fech = hubs[~hubs.aberto]
    fig.add_trace(go.Scatter(
        x=fech.lon, y=fech.lat, mode="markers", name="Hub fechado",
        marker=dict(symbol="x", size=13, color=CINZA, line=dict(width=1)),
        text=[f"<b>{h}</b> (fechado)" for h in fech.hub], hoverinfo="text"))
    ab = hubs[hubs.aberto]
    fig.add_trace(go.Scatter(
        x=ab.lon, y=ab.lat, mode="markers+text", name="Hub aberto",
        marker=dict(symbol="square", size=18, color=VERMELHO, line=dict(color="white", width=2)),
        text=ab.hub, textposition="top center", textfont=dict(size=12, color="#222"),
        hovertext=[f"<b>{r.hub}</b><br>{r.pedidos_dia} pedidos/dia<br>ocupação {r.ocupacao:.0%}"
                   for r in ab.itertuples()], hoverinfo="text"))
    fig.update_layout(height=620, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="#FAFAF7",
                      legend=dict(orientation="h", y=1.02, x=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x",
                                                            scaleratio=1.1))
    col_mapa, col_tab = st.columns([5, 4])
    col_mapa.plotly_chart(fig, width="stretch")
    tabela = ab[["hub", "pedidos_dia", "capacidade", "ocupacao", "bairros_atendidos"]].sort_values(
        "ocupacao", ascending=False)
    col_tab.markdown("**Hubs abertos**")
    col_tab.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config={
            "hub": "Hub", "pedidos_dia": "Pedidos/dia", "capacidade": "Capacidade",
            "bairros_atendidos": "Bairros",
            "ocupacao": st.column_config.ProgressColumn("Ocupação", format="percent",
                                                        min_value=0, max_value=1),
        })
    col_tab.caption(md(f"Custo fixo dos hubs: {brl(rs['custo_fixo_hubs_dia_R$'])}/dia · "
                    f"entregas: {brl(rs['custo_entregas_dia_R$'])}/dia"))

# ---------- IA ----------
with aba_ia:
    st.markdown("Pergunte sobre a decisão. A IA responde **só com os números do modelo**.")
    exemplos = ["Por que o hub Itaim Bibi ficou fechado?", "Por que abrir Santana?",
                "Quem atende a Vila Olímpia?", "Quais hubs correm risco num pico de demanda?"]
    cols = st.columns(len(exemplos))
    for c, ex in zip(cols, exemplos):
        if c.button(ex, width="stretch"):
            st.session_state["pergunta"] = ex
    pergunta = st.chat_input("Escreva sua pergunta…")
    pergunta = pergunta or st.session_state.pop("pergunta", None)
    if pergunta:
        with st.chat_message("user"):
            st.write(pergunta)
        with st.chat_message("assistant"):
            with st.spinner("Pensando…"):
                resposta, origem = ia.perguntar(pergunta, rs, segredos())
            st.markdown(md(resposta))
            st.caption(f"Respondido por: {origem}")

# ---------- resumo ----------
with aba_resumo:
    if st.button("✍️ Gerar resumo executivo", type="primary"):
        with st.spinner("Escrevendo…"):
            st.session_state["resumo"] = ia.resumo_executivo(rs, segredos())
    if "resumo" in st.session_state:
        texto, origem = st.session_state["resumo"]
        st.markdown(md(texto))
        st.caption(f"Gerado por: {origem}")

# ---------- dados ----------
with aba_dados:
    bairros, cand = carregar_dados()
    st.markdown("Todos os dados são **fictícios**, gerados por `dados/gerar_dados.py`.")
    d1, d2 = st.columns(2)
    d1.markdown("**Bairros e demanda**")
    d1.dataframe(res.alocacao[["bairro", "pedidos_dia", "hub", "km", "minutos"]],
                 hide_index=True, width="stretch")
    d2.markdown("**Candidatos a hub**")
    d2.dataframe(cand[["hub", "custo_dia", "capacidade"]], hide_index=True,
                 width="stretch")
