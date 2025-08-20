"""
Metrics and aggregations for GLPI tickets.
"""
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd


def normalize_ticket_df(df: pd.DataFrame) -> pd.DataFrame:
    """Converte campos de data para datetime ingênuo (sem timezone).

    Campos: created_at, solved_at, closed_at, ttr_deadline.
    """
    for c in ["created_at", "solved_at", "closed_at", "ttr_deadline"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True).dt.tz_convert(None)
    return df


def created_resolved(df: pd.DataFrame, freq: str = "D"):
    """Computa séries temporais de criados, resolvidos e backlog na frequência informada."""
    s_created = (
        df.set_index("created_at").sort_index().assign(v=1)["v"].resample(freq).sum().fillna(0)
    )
    s_resolved = (
        df[df["solved_at"].notna()].set_index("solved_at").sort_index().assign(v=1)["v"].resample(freq).sum().fillna(0)
    )
    backlog = (s_created.cumsum() - s_resolved.cumsum()).rename("backlog")
    return s_created.rename("Criados"), s_resolved.rename("Resolvidos"), backlog


def backlog_status(df: pd.DataFrame):
    """Distribuição do backlog aberto por status (considera closed_at nulo)."""
    open_mask = df["closed_at"].isna()
    return (
        df[open_mask].groupby("status", dropna=False)["ticket_id"].count().sort_values(ascending=False)
    )


def sla_solution(df: pd.DataFrame, now=None) -> Dict[str, Any]:
    """Calcula indicadores de SLA de solução e estatísticas de lead time.

    Retorna: tickets_com_deadline, cumpridos, violados_abertos, pct_cumpridos,
    lead_mediana_dias, lead_p95_dias.
    """
    now = now or pd.Timestamp.now()
    tmp = df.copy()
    tmp["deadline"] = pd.to_datetime(tmp.get("ttr_deadline"), errors="coerce")
    tmp["resolved_at"] = pd.to_datetime(tmp.get("solved_at"), errors="coerce")
    tmp["effective"] = tmp["resolved_at"].fillna(now)
    tmp["on_time"] = (tmp["deadline"].notna()) & (tmp["effective"] <= tmp["deadline"])
    total = tmp["deadline"].notna().sum()
    cumpridos = tmp["on_time"].sum()
    violados_abertos = (
        (tmp["deadline"].notna()) & tmp["resolved_at"].isna() & (now > tmp["deadline"])
    ).sum()
    p_ok = (cumpridos / total * 100) if total else np.nan
    tmp["lead_days"] = (
        tmp["effective"] - pd.to_datetime(tmp["created_at"], errors="coerce")
    ).dt.total_seconds() / 86400.0
    mediana = float(np.nanmedian(tmp["lead_days"])) if len(tmp) else np.nan
    p95 = float(np.nanpercentile(tmp["lead_days"], 95)) if len(tmp) else np.nan
    return {
        "tickets_com_deadline": int(total),
        "cumpridos": int(cumpridos),
        "violados_abertos": int(violados_abertos),
        "pct_cumpridos": None if np.isnan(p_ok) else float(round(p_ok, 2)),
        "lead_mediana_dias": None if np.isnan(mediana) else round(mediana, 2),
        "lead_p95_dias": None if np.isnan(p95) else round(p95, 2),
    }


def composition(df: pd.DataFrame):
    """Composição por categoria, prioridade e impacto."""
    cat = (
        df.groupby("category", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(15)
    )
    pr = df.groupby("priority", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    imp = df.groupby("impact", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    return cat, pr, imp


def load_by_assignee(df: pd.DataFrame):
    """Carga de tickets por usuário e grupo atribuídos (top 20)."""
    out = {}
    if "assigned_user" in df.columns:
        out["by_user"] = (
            df.groupby("assigned_user", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
        )
    if "assigned_group" in df.columns:
        out["by_group"] = (
            df.groupby("assigned_group", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(20)
        )
    return out


def aging_buckets(df: pd.DataFrame, now=None):
    """Distribuição de idade (em dias) dos chamados abertos por faixas."""
    now = now or pd.Timestamp.now()
    open_df = df[df["closed_at"].isna()].copy()
    open_df["age_days"] = (
        now - pd.to_datetime(open_df["created_at"], errors="coerce")
    ).dt.total_seconds() / 86400.0
    bins = [-1, 2, 7, 14, 30, 999999]
    labels = ["0–2d", "3–7d", "8–14d", "15–30d", ">30d"]
    cats = pd.cut(open_df["age_days"], bins=bins, labels=labels)
    return cats.value_counts().reindex(labels, fill_value=0)
