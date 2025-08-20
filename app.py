# -*- coding: utf-8 -*-
# GLPI Dash — Observador = Meus grupos (Status = Todos)
# Estratégia:
#  - Só GLPI_USER_TOKEN (sem App-Token)
#  - Pega meus grupos em getFullSession (session.glpigroups)
#  - Descobre SIDs de Group_Ticket (Ticket.id e Group.id) via listSearchOptions
#  - search/Group_Ticket por Group.id => obtém lista de Ticket.id
#  - Para cada ticket, lê Ticket/<id>/Group_Ticket e mantém se houver type==3 para meus grupos (Observador)
#  - Lê detalhes do Ticket/<id> e monta dashboards

import os
from typing import Dict, List, Any, Optional, Tuple, Set
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import streamlit as st
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# -------------------- Config --------------------
load_dotenv()
GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "")
# Limite de tickets a detalhar por execução (proteção)
MAX_TICKETS = int(os.getenv("MAX_TICKETS", "800"))

st.set_page_config(page_title="GLPI — Observador: Meus grupos", layout="wide")
st.title("Tickets GLPI • Filtro: **Observador = Meus grupos** (Status = Todos)")

# -------------------- Cliente GLPI --------------------
class GLPIClient:
    def __init__(self, base_url: str, user_token: str):
        if not base_url:
            raise RuntimeError("GLPI_URL não configurada")
        if not user_token:
            raise RuntimeError("GLPI_USER_TOKEN não configurado")

        # aceita GLPI_URL com ou sem /apirest.php
        if base_url.endswith("/apirest.php"):
            self.base = base_url
        else:
            self.base = base_url + "/apirest.php"

        self.session = requests.Session()
        self.session_token: Optional[str] = None
        self.headers_base = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"user_token {user_token}",
        }

        # dados da sessão
        self.session_blob: Optional[dict] = None
        self.me_user_id: Optional[int] = None
        self.my_group_ids: List[int] = []

    def _headers(self) -> dict:
        h = dict(self.headers_base)
        if self.session_token:
            h["Session-Token"] = self.session_token
        return h

    def _params(self, extra: Optional[dict] = None) -> dict:
        p = dict(extra or {})
        if self.session_token and "session_token" not in p:
            p["session_token"] = self.session_token
        return p

    def _get(self, path: str, params: Optional[dict] = None, timeout=60):
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            r = self.session.get(
                url, headers=self._headers(), params=self._params(params),
                timeout=timeout, allow_redirects=False
            )
            if r.is_redirect or r.is_permanent_redirect:
                raise RuntimeError(f"Redirect detectado em {url}. Ajuste GLPI_URL para a URL final do apirest.php.")
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            body = ""
            try: body = r.text[:2000]
            except Exception: pass
            raise RuntimeError(f"HTTPError {getattr(e.response,'status_code', '???')} em {url} | Resposta: {body}") from e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def init_session(self, get_full: bool = True):
        params = {"get_full_session": "true"} if get_full else {}
        r = self.session.get(
            f"{self.base}/initSession",
            headers=self._headers(),
            params=params,
            timeout=30,
            allow_redirects=False
        )
        if r.is_redirect or r.is_permanent_redirect:
            raise RuntimeError("Redirect durante initSession. Corrija GLPI_URL.")
        r.raise_for_status()
        js = r.json()
        self.session_token = js.get("session_token")
        if not self.session_token:
            raise RuntimeError(f"initSession OK mas sem session_token. Corpo: {r.text[:2000]}")

        # sessão completa
        sess = self._get("getFullSession", params={}).json()
        self.session_blob = sess

        # user_id
        uid = None
        # preferir session.glpiID
        try: uid = sess["session"].get("glpiID")
        except Exception: pass
        if uid is None:
            # fallbacks
            for key in ("user", "glpi_user", "session"):
                if isinstance(sess.get(key), dict):
                    for cand in ("id", "ID", "userid", "userID", "glpiID"):
                        if cand in sess[key]:
                            uid = sess[key][cand]; break
        try:
            self.me_user_id = int(uid) if uid is not None else None
        except Exception:
            self.me_user_id = None
        if not self.me_user_id:
            raise RuntimeError(f"Não foi possível identificar seu user_id via getFullSession. Resposta: {str(sess)[:500]}")

        # meus grupos direto da sessão
        gids = []
        try:
            gids = sess["session"].get("glpigroups", []) or []
        except Exception:
            pass
        self.my_group_ids = []
        for g in gids:
            try: self.my_group_ids.append(int(g))
            except Exception: pass

    def kill_session(self):
        if not self.session_token: return
        try:
            self._get("killSession", params={}, timeout=15)
        finally:
            self.session_token = None

    # APIs
    def list_search_options(self, itemtype: str) -> Dict[str, Any]:
        return self._get(f"listSearchOptions/{itemtype}", params={}, timeout=60).json()

    def raw_search(self, itemtype: str, params: dict):
        return self._get(f"search/{itemtype}", params=params, timeout=120)

    def get_item(self, itemtype: str, item_id: int):
        return self._get(f"{itemtype}/{item_id}", params={}, timeout=60).json()

    def get_subitems(self, itemtype: str, item_id: int, subitemtype: str, params: Optional[dict] = None):
        return self._get(f"{itemtype}/{item_id}/{subitemtype}", params=params or {}, timeout=120).json()

# -------------------- Descoberta de SIDs (Group_Ticket) --------------------
def discover_group_ticket_sids(client: GLPIClient) -> Tuple[int, int]:
    """
    Retorna (sid_ticket_id, sid_group_id) para Group_Ticket.
    Fallback para (3,4) se não encontrar.
    """
    opts = client.list_search_options("Group_Ticket")
    sid_ticket, sid_group = None, None
    for key, spec in opts.items():
        if not str(key).isdigit(): continue
        uid = spec.get("uid") or ""
        table = (spec.get("table") or "").lower()
        field = (spec.get("field") or "").lower()
        # Ticket.id
        if uid == "Group_Ticket.Ticket.id" or (table == "glpi_tickets" and field == "id"):
            sid_ticket = int(key)
        # Group.id
        if uid == "Group_Ticket.Group.id" or (table == "glpi_groups" and field == "id"):
            sid_group = int(key)
    if sid_ticket is None: sid_ticket = 3   # conforme seu ambiente
    if sid_group  is None: sid_group  = 4
    return sid_ticket, sid_group

# -------------------- Coleta de tickets observados --------------------
def find_ticket_ids_by_group_links(client: GLPIClient, group_ids: List[int],
                                   sid_ticket: int, sid_group: int,
                                   range_chunk: int = 2000) -> Set[int]:
    """
    Retorna o conjunto de ticket_ids ligados a qualquer um dos 'group_ids' (qualquer type).
    Usa search/Group_Ticket com criteria em sid_group e forcedisplay sid_ticket.
    """
    ticket_ids: Set[int] = set()
    for gid in group_ids:
        start = 0
        while True:
            params = {
                "range": f"{start}-{start+range_chunk-1}",
                f"criteria[0][field]": str(sid_group),
                f"criteria[0][searchtype]": "equals",
                f"criteria[0][value]": str(gid),
                "forcedisplay[0]": str(sid_ticket),
            }
            r = client.raw_search("Group_Ticket", params)
            data = r.json().get("data", [])
            if not data:
                break
            for row in data:
                # na sua instância, a coluna com o ticket.id é o índice do sid_ticket
                tid = row.get(str(sid_ticket))
                if tid:
                    try: ticket_ids.add(int(str(tid)))
                    except: pass
            # paginação
            cr = r.headers.get("Content-Range", "0-0/0")
            try:
                end = int(cr.split("/")[0].split("-")[1])
                total = int(cr.split("/")[1])
            except Exception:
                break
            if end + 1 >= total:
                break
            start = end + 1
    return ticket_ids

def filter_observer_tickets(client: GLPIClient, ticket_ids: List[int], group_ids: List[int],
                            max_tickets: int) -> List[int]:
    """
    Mantém apenas tickets em que pelo menos um vínculo Group_Ticket tem:
      - groups_id ∈ group_ids
      - type == 3 (observador)
    Consulta Ticket/<id>/Group_Ticket ticket-a-ticket.
    """
    gids = set(group_ids)
    out: List[int] = []
    for i, tid in enumerate(ticket_ids[:max_tickets]):
        try:
            subs = client.get_subitems("Ticket", tid, "Group_Ticket", params={"range": "0-1999"})
        except Exception as e:
            # sem permissão para subitens => não conseguimos filtrar por type; ignore esse ticket
            continue
        ok = False
        for link in subs or []:
            try:
                if int(str(link.get("groups_id"))) in gids and int(str(link.get("type"))) == 3:
                    ok = True; break
            except Exception:
                continue
        if ok:
            out.append(tid)
    return out

def fetch_ticket_details(client: GLPIClient, ticket_ids: List[int],
                         dt_ini: Optional[pd.Timestamp], dt_fim: Optional[pd.Timestamp]) -> pd.DataFrame:
    rows = []
    for tid in ticket_ids:
        try:
            t = client.get_item("Ticket", tid)
        except Exception:
            continue
        rec = {
            "ticket_id": tid,
            "created_at": t.get("date"),
            "solved_at": t.get("solvedate"),
            "closed_at": t.get("closedate"),
            "status": t.get("status"),
            "priority": t.get("priority"),
            "urgency": t.get("urgency"),
            "impact": t.get("impact"),
            "ttr_deadline": t.get("time_to_resolve"),
            "category": str(t.get("itilcategories_id")) if t.get("itilcategories_id") is not None else None,
            "assigned_user": t.get("users_id_assign"),
            "assigned_group": t.get("groups_id_assign"),
        }
        rows.append(rec)
    df = pd.DataFrame(rows)
    # filtro por data de criação (janela)
    if not df.empty and dt_ini is not None:
        df = df[pd.to_datetime(df["created_at"], errors="coerce") >= pd.to_datetime(dt_ini)]
    if not df.empty and dt_fim is not None:
        df = df[pd.to_datetime(df["created_at"], errors="coerce") < (pd.to_datetime(dt_fim) + pd.Timedelta(days=1))]
    return df

# -------------------- Métricas e gráficos --------------------
def normalize_ticket_df(df: pd.DataFrame) -> pd.DataFrame:
    for c in ["created_at","solved_at","closed_at","ttr_deadline"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True).dt.tz_convert(None)
    return df

def created_resolved(df: pd.DataFrame, freq: str = "D"):
    s_created = df.set_index("created_at").sort_index().assign(v=1)["v"].resample(freq).sum().fillna(0)
    s_resolved = df[df["solved_at"].notna()].set_index("solved_at").sort_index().assign(v=1)["v"].resample(freq).sum().fillna(0)
    backlog = (s_created.cumsum() - s_resolved.cumsum()).rename("backlog")
    return s_created.rename("Criados"), s_resolved.rename("Resolvidos"), backlog

def backlog_status(df: pd.DataFrame):
    open_mask = df["closed_at"].isna()
    return df[open_mask].groupby("status", dropna=False)["ticket_id"].count().sort_values(ascending=False)

def sla_solution(df: pd.DataFrame, now=None):
    now = now or pd.Timestamp.now()
    tmp = df.copy()
    tmp["deadline"] = pd.to_datetime(tmp.get("ttr_deadline"), errors="coerce")
    tmp["resolved_at"] = pd.to_datetime(tmp.get("solved_at"), errors="coerce")
    tmp["effective"]   = tmp["resolved_at"].fillna(now)
    tmp["on_time"] = (tmp["deadline"].notna()) & (tmp["effective"] <= tmp["deadline"])
    total = tmp["deadline"].notna().sum()
    cumpridos = tmp["on_time"].sum()
    violados_abertos = ((tmp["deadline"].notna()) & tmp["resolved_at"].isna() & (now > tmp["deadline"])).sum()
    p_ok = (cumpridos / total * 100) if total else np.nan
    tmp["lead_days"] = (tmp["effective"] - pd.to_datetime(tmp["created_at"], errors="coerce")).dt.total_seconds()/86400.0
    mediana = float(np.nanmedian(tmp["lead_days"])) if len(tmp) else np.nan
    p95     = float(np.nanpercentile(tmp["lead_days"], 95)) if len(tmp) else np.nan
    return {
        "tickets_com_deadline": int(total),
        "cumpridos": int(cumpridos),
        "violados_abertos": int(violados_abertos),
        "pct_cumpridos": None if np.isnan(p_ok) else float(round(p_ok,2)),
        "lead_mediana_dias": None if np.isnan(mediana) else round(mediana,2),
        "lead_p95_dias": None if np.isnan(p95) else round(p95,2),
    }

def composition(df: pd.DataFrame):
    cat = df.groupby("category", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(15)
    pr  = df.groupby("priority", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    imp = df.groupby("impact", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    return cat, pr, imp

def load_by_assignee(df: pd.DataFrame):
    out = {}
    if "assigned_user" in df.columns:
        out["by_user"] = df.groupby("assigned_user", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
    if "assigned_group" in df.columns:
        out["by_group"] = df.groupby("assigned_group", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
    return out

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
def aging_buckets(df: pd.DataFrame, now=None):
    now = now or pd.Timestamp.now()
    open_df = df[df["closed_at"].isna()].copy()
    open_df["age_days"] = (now - pd.to_datetime(open_df["created_at"], errors="coerce")).dt.total_seconds()/86400.0
    bins = [-1,2,7,14,30,999999]; labels = ["0–2d","3–7d","8–14d","15–30d",">30d"]
    cats = pd.cut(open_df["age_days"], bins=bins, labels=labels)
    return cats.value_counts().reindex(labels, fill_value=0)
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

