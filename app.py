# -*- coding: utf-8 -*-
# GLPI Dash — Observador = Meus grupos (Status = Todos)
# Arquitetura refatorada em módulos para legibilidade.

import os
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from dotenv import load_dotenv

# módulos internos
from glpi_client import GLPIClient
from data_access import (
    discover_group_ticket_sids,
    find_ticket_ids_by_group_links,
    filter_observer_tickets,
    fetch_ticket_details,
)
from metrics import (
    normalize_ticket_df,
    created_resolved,
    backlog_status,
    sla_solution,
    composition,
    load_by_assignee,
    aging_buckets,
)

# -------------------- Config --------------------
load_dotenv()
GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "")
# Limite de tickets a detalhar por execução (proteção)
MAX_TICKETS = int(os.getenv("MAX_TICKETS", "800"))

st.set_page_config(page_title="GLPI — Observador: Meus grupos", layout="wide")
st.title("Tickets GLPI • Filtro: **Observador = Meus grupos** (Status = Todos)")

# -------------------- UI --------------------
st.sidebar.header("Configuração")
st.sidebar.write("Credenciais via `.env`: GLPI_URL, GLPI_USER_TOKEN.")
gran = st.sidebar.selectbox("Granularidade do fluxo", ["Diário", "Semanal"])
freq = "D" if gran == "Diário" else "W"
dt_ini = st.sidebar.date_input("Início", pd.Timestamp.today().normalize() - pd.Timedelta(days=30))
dt_fim = st.sidebar.date_input("Fim", pd.Timestamp.today().normalize())
max_tickets = st.sidebar.number_input("Limite de tickets a detalhar", min_value=50, max_value=10000, value=MAX_TICKETS, step=50)

if not GLPI_URL or not GLPI_USER_TOKEN:
    st.error("Preencha GLPI_URL e GLPI_USER_TOKEN no .env")
    st.stop()

client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)

@st.cache_data(show_spinner=True, ttl=600)
def fetch_data(dini: pd.Timestamp, dfim: pd.Timestamp, max_tix: int):
    """Fluxo principal de coleta de dados.

    - Abre sessão no GLPI e descobre grupos do usuário.
    - Descobre SIDs de Group_Ticket.
    - Busca todos os tickets vinculados aos grupos e filtra apenas os com type=3 (observador).
    - Carrega detalhes dos tickets e aplica janela por data de criação.
    Retorna: (DataFrame normalizado, metadados do processo).
    """
    client.init_session(get_full=True)
    try:
        if not client.my_group_ids:
            return pd.DataFrame(), {"groups": [], "note": "Nenhum grupo retornado em getFullSession (session.glpigroups)."}

        # Descobrir SIDs de Group_Ticket
        sid_ticket, sid_group = discover_group_ticket_sids(client)

        # Tickets ligados a qualquer um dos meus grupos (qualquer type)
        tset = find_ticket_ids_by_group_links(client, client.my_group_ids, sid_ticket, sid_group)
        if not tset:
            return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket ligado aos grupos (Group_Ticket)."}
        # Filtrar apenas os que têm type==3 (observador) para meus grupos
        tids_obs = filter_observer_tickets(client, sorted(tset), client.my_group_ids, max_tix)
        if not tids_obs:
            return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket com type=3 (Observador) para seus grupos."}

        # Detalhes + janela por data de criação
        df = fetch_ticket_details(client, tids_obs, pd.to_datetime(dini), pd.to_datetime(dfim))
        if df is None or df.empty:
            return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket no intervalo informado."}

        df = normalize_ticket_df(df)
        meta = {"groups": client.my_group_ids, "sid_ticket": sid_ticket, "sid_group": sid_group, "tids_total": len(tset), "tids_obs": len(tids_obs)}
        return df, meta
    finally:
        client.kill_session()

# Execução
try:
    df, meta = fetch_data(pd.Timestamp(dt_ini), pd.Timestamp(dt_fim), max_tickets)
except Exception as e:
    st.error(f"Erro ao buscar dados: {e}")
    st.stop()

st.caption(f"Período: {pd.Timestamp(dt_ini).date()} a {pd.Timestamp(dt_fim).date()} • Tickets: {0 if df.empty else len(df)}")
if meta:
    gids = meta.get("groups", [])
    info = f"Meus grupos (getFullSession): {gids} • SIDs Group_Ticket → Ticket.id={meta.get('sid_ticket','?')}, Group.id={meta.get('sid_group','?')}"
    if "tids_total" in meta and "tids_obs" in meta:
        info += f" • Vínculos totais={meta['tids_total']} • Observador={meta['tids_obs']}"
    st.caption(info)

if meta and meta.get("note"):
    st.warning(meta["note"])

if df.empty:
    st.info("Nenhum ticket encontrado com 'Observador = Meus grupos' nesse intervalo.")
    st.stop()

# Dashboards
c1, c2, c3 = st.columns(3)
created, resolved, backlog = created_resolved(df, freq=("D" if gran == "Diário" else "W"))
with c1:
    st.subheader("Criados vs Resolvidos")
    fig1, ax1 = plt.subplots(); created.plot(ax=ax1); resolved.plot(ax=ax1)
    ax1.set_xlabel("Período"); ax1.set_ylabel("Qtd"); ax1.legend(["Criados","Resolvidos"]); st.pyplot(fig1)

with c2:
    st.subheader("Backlog (tendência)")
    fig2, ax2 = plt.subplots(); backlog.plot(ax=ax2)
    ax2.set_xlabel("Período"); ax2.set_ylabel("Backlog"); st.pyplot(fig2)

with c3:
    st.subheader("Backlog por Status (Abertos)")
    st.bar_chart(backlog_status(df))

st.markdown("---")
st.subheader("SLA de Solução")
st.write(sla_solution(df))

st.subheader("Aging dos Abertos")
st.bar_chart(aging_buckets(df))

st.subheader("Composição")
cat, pr, imp = composition(df)
cc1, cc2, cc3 = st.columns(3)
with cc1: st.bar_chart(cat)
with cc2: st.bar_chart(pr)
with cc3: st.bar_chart(imp)

st.subheader("Carga por Responsável")
load = load_by_assignee(df)
if "by_user" in load: st.write("Por usuário atribuído"); st.bar_chart(load["by_user"])
if "by_group" in load: st.write("Por grupo atribuído"); st.bar_chart(load["by_group"])

st.markdown("---")
st.caption("Filtro aplicado: **Observador = Meus grupos** (via Group_Ticket + Ticket/<id>/Group_Ticket com type=3). Status = **Todos**.")

