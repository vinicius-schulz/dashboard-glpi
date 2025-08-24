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
    discover_group_ticket_sids,  # legado
    find_ticket_ids_by_group_links,  # legado
    filter_observer_tickets,  # legado
    fetch_ticket_details,  # legado
    bulk_search_observer_tickets,  # novo fluxo otimizado
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
from instrumentation import new_request_id, get_request_id, timed

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
@timed
def fetch_data(dini: pd.Timestamp, dfim: pd.Timestamp, max_tix: int, modo_legacy: bool):
    """Fluxo principal de coleta de dados.

    Dois modos:
      - legacy=True  : pipeline antigo (Group_Ticket + get_subitems + get_item)
      - legacy=False : novo fluxo otimizado usando search/Ticket campo "Grupo observador" (id 65)
    """
    rid = new_request_id()
    client.init_session(get_full=True)
    try:
        if not client.my_group_ids:
            return pd.DataFrame(), {"groups": [], "note": "Nenhum grupo retornado em getFullSession (session.glpigroups)."}

        if modo_legacy:
            sid_ticket, sid_group = discover_group_ticket_sids(client)
            tset = find_ticket_ids_by_group_links(client, client.my_group_ids, sid_ticket, sid_group)
            if not tset:
                return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket ligado aos grupos (Group_Ticket)."}
            tids_obs = filter_observer_tickets(client, sorted(tset), client.my_group_ids, max_tix)
            if not tids_obs:
                return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket com type=3 (Observador) para seus grupos."}
            df = fetch_ticket_details(client, tids_obs, pd.to_datetime(dini), pd.to_datetime(dfim))
            if df is None or df.empty:
                return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket no intervalo informado."}
            df = normalize_ticket_df(df)
            meta = {"modo": "legacy", "groups": client.my_group_ids, "sid_ticket": sid_ticket, "sid_group": sid_group, "tids_total": len(tset), "tids_obs": len(tids_obs), "request_id": rid}
            return df, meta
        else:
            # Novo fluxo: busca direta em search/Ticket por cada grupo como observador
            df = bulk_search_observer_tickets(
                client,
                observer_group_ids=client.my_group_ids,
                dt_ini=pd.to_datetime(dini),
                dt_fim=pd.to_datetime(dfim),
                max_tickets=max_tix,
            )
            if df is None or df.empty:
                return pd.DataFrame(), {"groups": client.my_group_ids, "note": "Nenhum ticket retornado via 'Grupo observador'."}
            # Normaliza para manter compatibilidade com métricas (espera colunas e tipos)
            df = normalize_ticket_df(df)
            meta = {"modo": "bulk", "groups": client.my_group_ids, "tids": len(df), "request_id": rid}
            return df, meta
    finally:
        client.kill_session()

# Execução
try:
    modo_legacy = st.sidebar.checkbox("Usar modo legacy (subitens)", value=False, help="Ative apenas para comparar performance ou fallback.")
    df, meta = fetch_data(pd.Timestamp(dt_ini), pd.Timestamp(dt_fim), max_tickets, modo_legacy)
except Exception as e:
    st.error(f"Erro ao buscar dados: {e}")
    st.stop()

st.caption(f"Período: {pd.Timestamp(dt_ini).date()} a {pd.Timestamp(dt_fim).date()} • Tickets: {0 if df.empty else len(df)}")
if meta:
    gids = meta.get("groups", [])
    if meta.get("modo") == "legacy":
        info = f"[LEGACY] Grupos: {gids} • SIDs → Ticket.id={meta.get('sid_ticket','?')} / Group.id={meta.get('sid_group','?')}"
        if "tids_total" in meta and "tids_obs" in meta:
            info += f" • Vínculos totais={meta['tids_total']} • Observador={meta['tids_obs']}"
    else:
        info = f"[BULK] Grupos: {gids} • Tickets retornados={meta.get('tids','?')}"
    if meta.get("request_id"):
        info += f" • req_id={meta['request_id']}"
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
if meta.get("modo") == "legacy":
    st.caption("Filtro aplicado (LEGACY): Observador = Meus grupos via Group_Ticket + subitens (type=3).")
else:
    st.caption("Filtro aplicado (BULK): Observador = Meus grupos via search/Ticket campo 'Grupo observador' (id 65).")

