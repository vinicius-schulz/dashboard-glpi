import pandas as pd
import numpy as np
from datetime import datetime, timezone

def normalize_ticket_df(df: pd.DataFrame) -> pd.DataFrame:
    # Renomeia colunas de acordo com mapeamentos feitos no app
    for c in ["created_at","solved_at","closed_at","ttr_deadline"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True).dt.tz_convert(None)
    return df

def created_resolved(df: pd.DataFrame, freq: str = "D"):
    s_created = df.set_index("created_at").sort_index().assign(val=1)["val"].resample(freq).sum().fillna(0)
    s_resolved = df[df["solved_at"].notna()].set_index("solved_at").sort_index().assign(val=1)["val"].resample(freq).sum().fillna(0)
    # backlog cumulativo
    backlog = (s_created.cumsum() - s_resolved.cumsum()).rename("backlog")
    return s_created.rename("created"), s_resolved.rename("resolved"), backlog

def backlog_status(df: pd.DataFrame):
    open_mask = df["closed_at"].isna()
    by_status = df[open_mask].groupby("status", dropna=False)["ticket_id"].count().sort_values(ascending=False)
    return by_status

def sla_solution(df: pd.DataFrame, now=None):
    now = now or pd.Timestamp.now(tz=None)
    # Considera ttr_deadline (deadline de solução). Se solved_at <= ttr_deadline → cumpriu.
    tmp = df.copy()
    tmp["deadline"] = pd.to_datetime(tmp.get("ttr_deadline"), errors="coerce")
    tmp["resolved_at"] = pd.to_datetime(tmp.get("solved_at"), errors="coerce")
    tmp["effective"]   = tmp["resolved_at"].fillna(now)
    tmp["on_time"] = (tmp["deadline"].notna()) & (tmp["effective"] <= tmp["deadline"])
    # métricas
    total_com_deadline = tmp["deadline"].notna().sum()
    cumpridos = tmp["on_time"].sum()
    violados_abertos = ((tmp["deadline"].notna()) & tmp["resolved_at"].isna() & (now > tmp["deadline"])).sum()
    p_ok = (cumpridos / total_com_deadline * 100) if total_com_deadline else np.nan
    # tempos (em dias)
    tmp["lead_days"] = (tmp["effective"] - pd.to_datetime(tmp["created_at"], errors="coerce")).dt.total_seconds() / 86400.0
    mediana = np.nanmedian(tmp["lead_days"]) if len(tmp) else np.nan
    p95 = np.nanpercentile(tmp["lead_days"], 95) if len(tmp) else np.nan
    return {
        "total_com_deadline": int(total_com_deadline),
        "cumpridos": int(cumpridos),
        "violados_abertos": int(violados_abertos),
        "pct_cumpridos": float(np.round(p_ok, 2)) if not np.isnan(p_ok) else np.nan,
        "lead_mediana_dias": float(np.round(mediana, 2)) if not np.isnan(mediana) else np.nan,
        "lead_p95_dias": float(np.round(p95, 2)) if not np.isnan(p95) else np.nan
    }

def aging_buckets(df: pd.DataFrame, now=None):
    now = now or pd.Timestamp.now(tz=None)
    open_df = df[df["closed_at"].isna()].copy()
    open_df["age_days"] = (now - pd.to_datetime(open_df["created_at"], errors="coerce")).dt.total_seconds() / 86400.0
    bins = [-1, 2, 7, 14, 30, 999999]
    labels = ["0–2d","3–7d","8–14d","15–30d",">30d"]
    cats = pd.cut(open_df["age_days"], bins=bins, labels=labels)
    return cats.value_counts().reindex(labels, fill_value=0)

def composition(df: pd.DataFrame):
    cat = df.groupby("category", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(15)
    pr  = df.groupby("priority", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    imp = df.groupby("impact", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    return cat, pr, imp

def load_by_assignee(df: pd.DataFrame):
    # Se tiver user assign e group assign
    cols = [c for c in df.columns if c in ("assigned_user","assigned_group")]
    out = {}
    if "assigned_user" in cols:
        out["by_user"] = df.groupby("assigned_user", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
    if "assigned_group" in cols:
        out["by_group"] = df.groupby("assigned_group", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
    return out

