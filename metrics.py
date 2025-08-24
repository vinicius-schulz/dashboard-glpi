"""
Metrics and aggregations for GLPI tickets.
"""
from typing import Tuple, Dict, Any
import numpy as np
from instrumentation import timed
import pandas as pd
import datetime


@timed
def normalize_ticket_df(df: pd.DataFrame) -> pd.DataFrame:
    """Converte campos de data para datetime ingênuo (sem timezone).

    Campos: created_at, solved_at, closed_at, ttr_deadline.
    """
    for c in ["created_at", "solved_at", "closed_at", "ttr_deadline"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True).dt.tz_convert(None)
    return df


@timed
def created_resolved(df: pd.DataFrame, freq: str = "D"):
        """Computa séries de criados, resolvidos e backlog considerando backlog inicial.

        Premissas:
        - O dataframe já pode conter tickets criados antes do intervalo solicitado
            (via lógica de fetch ampliada) para permitir cálculo de backlog inicial.
        - A série de criados inclui apenas ocorrências com created_at dentro do range
            coberto pela indexação resultante.
        - Backlog = backlog_inicial + cumul(criados) - cumul(resolvidos).
        """
        if df.empty:
                return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)

        # Série base de datas para união: combinar datas de criação e solução
        created_idx = pd.to_datetime(df["created_at"], errors="coerce")
        solved_idx = pd.to_datetime(df["solved_at"], errors="coerce")
        min_date = min(created_idx.min(), solved_idx.min(skipna=True) if solved_idx.notna().any() else created_idx.min())
        max_date = max(created_idx.max(), solved_idx.max(skipna=True) if solved_idx.notna().any() else created_idx.max())

        # Resample window — restringe à janela solicitada, se disponível em attrs
        win_start = getattr(df, 'attrs', {}).get('window_start', None)
        win_end = getattr(df, 'attrs', {}).get('window_end', None)
        if win_start is not None:
            min_date = pd.to_datetime(win_start)
        if win_end is not None:
            max_date = pd.to_datetime(win_end)
        rng = pd.date_range(min_date.normalize(), max_date.normalize(), freq=freq)

        s_created = (
                pd.Series(1, index=created_idx).sort_index().resample(freq).sum().reindex(rng, fill_value=0)
        )
        s_resolved = (
                pd.Series(1, index=solved_idx.dropna()).sort_index().resample(freq).sum().reindex(rng, fill_value=0)
        )

        # Backlog inicial: tickets criados antes da primeira data da janela e não resolvidos antes dessa data
        start_boundary = rng[0]
        created_before = created_idx < start_boundary
        solved_before_start = solved_idx.notna() & (solved_idx < start_boundary)
        backlog_inicial = ((created_before) & (~solved_before_start)).sum()

        backlog = (backlog_inicial + s_created.cumsum() - s_resolved.cumsum()).rename("backlog")
        return s_created.rename("Criados"), s_resolved.rename("Resolvidos"), backlog


@timed
def backlog_status(df: pd.DataFrame):
    """Distribuição do backlog aberto por status.

    Critério de backlog: ticket ainda não resolvido (solved_at nulo). Usar
    closed_at pode manter tickets já resolvidos (status 5) indevidamente.
    """
    open_mask = df["solved_at"].isna()
    return df[open_mask].groupby("status", dropna=False)["ticket_id"].count().sort_values(ascending=False)


@timed
def backlog_trend_series(backlog: pd.Series) -> pd.Series:
    """Gera série suavizada (tendência) para backlog diário/semanal.

    Preferência: LOWESS (statsmodels). Fallback: média exponencial.
    """
    if backlog is None or backlog.empty:
        return backlog
    s = backlog.astype(float).copy()
    # índice deve permanecer igual
    x = np.arange(len(s))
    trend = None
    try:
        from statsmodels.nonparametric.smoothers_lowess import lowess  # type: ignore
        # largura da janela: mais pontos => fração menor
        frac = 0.3 if len(s) > 30 else 0.5
        fitted = lowess(s.values, x, frac=frac, return_sorted=False)
        trend = pd.Series(fitted, index=s.index, name="BacklogTrend")
    except Exception:
        # fallback: EWM suave
        span = min(14, max(3, len(s)//3 or 3))
        trend = s.ewm(span=span, adjust=False).mean().rename("BacklogTrend")
    return trend


@timed
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


@timed
def composition(df: pd.DataFrame):
    """Composição por categoria, prioridade e impacto."""
    cat = (
        df.groupby("category", dropna=True)["ticket_id"].count().sort_values(ascending=False).head(15)
    )
    pr = df.groupby("priority", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    imp = df.groupby("impact", dropna=True)["ticket_id"].count().sort_values(ascending=False)
    return cat, pr, imp


@timed
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


@timed
def aging_buckets(df: pd.DataFrame, now=None):
    """Distribuição de idade (em dias) dos tickets em backlog (não resolvidos).

    Critério: solved_at nulo. Tickets resolvidos aguardando fechamento não entram.
    """
    now = now or pd.Timestamp.now()
    open_df = df[df["solved_at"].isna()].copy()
    open_df["age_days"] = (now - pd.to_datetime(open_df["created_at"], errors="coerce")).dt.total_seconds() / 86400.0
    # Faixas não sobrepostas incluindo separação 31–60d e >60d
    bins = [-1, 2, 7, 14, 30, 60, 999999]
    labels = ["0–2d", "3–7d", "8–14d", "15–30d", "31–60d", ">60d"]
    cats = pd.cut(open_df["age_days"], bins=bins, labels=labels)
    return cats.value_counts().reindex(labels, fill_value=0)


@timed
def business_hours_between(start: pd.Timestamp, end: pd.Timestamp, start_hour: int = 9, end_hour: int = 18) -> float:
    """Retorna número de horas úteis (flutuante) entre start e end.

    Considera dias úteis como segunda a sexta e o intervalo diário [start_hour, end_hour).
    Ambos start e end devem ser pd.Timestamp (naive ou timezone-aware); função trabalha com seus valores como UTC-naive.
    """
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return 0.0
    # Ensure timestamps
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    if e <= s:
        return 0.0

    total_seconds = 0.0
    cur_date = s.normalize()
    last_date = e.normalize()
    one_day = pd.Timedelta(days=1)

    while cur_date <= last_date:
        # weekday: Mon=0 .. Sun=6
        if cur_date.weekday() < 5:
            day_start = pd.Timestamp(datetime.datetime.combine(cur_date.date(), datetime.time(hour=start_hour)))
            day_end = pd.Timestamp(datetime.datetime.combine(cur_date.date(), datetime.time(hour=end_hour)))
            # overlap between [s,e] and [day_start, day_end)
            interval_start = max(s, day_start)
            interval_end = min(e, day_end)
            if interval_end > interval_start:
                total_seconds += (interval_end - interval_start).total_seconds()
        cur_date += one_day

    return total_seconds / 3600.0


@timed
def resolution_time_series(df: pd.DataFrame, freq: str = "D", work_start: int = 9, work_end: int = 18) -> pd.Series:
    """Calcula série (média horas úteis) por data de criação.

    - x-axis: data de criação (resample por `freq`)
    - y-axis: média do tempo entre created_at e solved_at/closed_at em horas úteis
    - usa business_hours_between para contabilizar apenas dias/horas úteis
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)

    created = pd.to_datetime(df.get("created_at"), errors="coerce")
    solved = pd.to_datetime(df.get("solved_at"), errors="coerce")
    closed = pd.to_datetime(df.get("closed_at"), errors="coerce")

    # prefer solved then closed
    resolved = solved.fillna(closed)

    # keep only rows with resolved time
    mask = resolved.notna() & created.notna()
    if not mask.any():
        return pd.Series(dtype=float)

    sub = pd.DataFrame({"created_at": created[mask], "resolved_at": resolved[mask]})

    # compute lead hours per row
    def compute_row(r):
        return business_hours_between(r["created_at"], r["resolved_at"], start_hour=work_start, end_hour=work_end)

    sub["lead_hours"] = sub.apply(compute_row, axis=1)

    # group by created_at resampled index
    sub.index = pd.to_datetime(sub["created_at"])
    # aggregate: mean of lead_hours per bin
    grouped = sub["lead_hours"].groupby(pd.Grouper(freq=freq)).mean()
    # drop bins without any resolved tickets (NaN)
    grouped = grouped.dropna()
    return grouped.rename("resolution_hours")
