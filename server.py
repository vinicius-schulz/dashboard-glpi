"""
Flask web app replacing Streamlit: HTML front-end + JSON API.

Endpoints:
- GET /            -> HTML page
- GET /api/data    -> Returns computed metrics as JSON

Env vars: GLPI_URL, GLPI_USER_TOKEN
"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import pandas as pd
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from glpi_client import GLPIClient
from data_access import (
    bulk_search_observer_tickets,  # fluxo otimizado (agora também inclui Grupo técnico)
)
from metrics import (
    normalize_ticket_df,
    created_resolved,
    backlog_status,
    sla_solution,
    composition,
    load_by_assignee,
    aging_buckets,
    backlog_trend_series,
    resolution_time_series,
)


load_dotenv()
GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "")

app = Flask(__name__, template_folder="templates", static_folder="static")


def _series_to_labels_data(s: pd.Series) -> Dict[str, Any]:
    s = s.copy()
    # Normalize index to string labels
    if isinstance(s.index, pd.PeriodIndex):
        labels = [str(p.start_time.date()) for p in s.index]
    elif isinstance(s.index, pd.DatetimeIndex):
        labels = [i.date().isoformat() for i in s.index]
    else:
        labels = [str(i) for i in s.index]
    return {"labels": labels, "data": [float(x) if pd.notna(x) else 0 for x in s.values]}


def _dict_to_labels_data(d: pd.Series | pd.DataFrame) -> Dict[str, Any]:
    if isinstance(d, pd.Series):
        return {"labels": [str(i) for i in d.index], "data": [int(v) for v in d.values]}
    return {"labels": [], "data": []}


def _fetch_data(dini: pd.Timestamp, dfim: pd.Timestamp, mode: str = "bulk") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Busca dados usando o fluxo otimizado (bulk search por "Grupo observador").

    Parâmetro `mode` mantido apenas para compatibilidade futura.
    Não há mais limitação artificial de quantidade de tickets; o intervalo de datas define o volume.
    """
    if not GLPI_URL or not GLPI_USER_TOKEN:
        raise RuntimeError("GLPI_URL e GLPI_USER_TOKEN precisam estar definidos no .env")

    client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)
    client.init_session(get_full=True)
    try:
        if not client.my_group_ids:
            return pd.DataFrame(), {"groups": [], "note": "Nenhum grupo retornado em getFullSession (session.glpigroups)."}

        df = bulk_search_observer_tickets(
            client,
            observer_group_ids=client.my_group_ids,
            dt_ini=pd.to_datetime(dini),
            dt_fim=pd.to_datetime(dfim),
            max_tickets=None,
            include_assigned_groups=True,
        )
        if df is None or df.empty:
            return pd.DataFrame(), {"modo": "bulk", "groups": client.my_group_ids, "note": "Nenhum ticket retornado via campo 'Grupo observador'."}
        df = normalize_ticket_df(df)
        meta = {"modo": "bulk", "groups": client.my_group_ids, "tids": len(df)}
        return df, meta
    finally:
        client.kill_session()

# --- Helpers for names/mappings ---
STATUS_MAP = {1: "Novo", 2: "Atribuído", 3: "Planejado", 4: "Pendente", 5: "Resolvido", 6: "Fechado"}
LEVEL_MAP = {1: "Muito baixo", 2: "Baixo", 3: "Médio", 4: "Alto", 5: "Muito alto"}

def _resolve_user_name(client: GLPIClient, uid: Any, cache: Dict[int, str]) -> str:
    try:
        i = int(uid)
    except Exception:
        return ""
    if i in cache:
        return cache[i]
    try:
        u = client.get_item("User", i)
        name = u.get("name") or u.get("realname") or str(i)
        cache[i] = name
        return name
    except Exception:
        cache[i] = str(i)
        return cache[i]

def _resolve_group_name(client: GLPIClient, gid: Any, cache: Dict[int, str]) -> str:
    try:
        i = int(gid)
    except Exception:
        return ""
    if i in cache:
        return cache[i]
    try:
        g = client.get_item("Group", i)
        name = g.get("name") or str(i)
        cache[i] = name
        return name
    except Exception:
        cache[i] = str(i)
        return cache[i]

def _resolve_category_name(client: GLPIClient, cid: Any, cache: Dict[int, str]) -> str:
    try:
        i = int(cid)
    except Exception:
        return ""
    if i in cache:
        return cache[i]
    try:
        c = client.get_item("ITILCategory", i)
        name = c.get("name") or str(i)
        cache[i] = name
        return name
    except Exception:
        cache[i] = str(i)
        return cache[i]

def _period_bounds_from_label(label: str, gran: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    # label is ISO date (start of day or start of week)
    start = pd.Timestamp(label)
    gl = gran.lower()
    if gl.startswith("di"):
        end = start + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    elif gl.startswith("se"):
        end = start + pd.Timedelta(weeks=1) - pd.Timedelta(microseconds=1)
    else:  # mensal
        # start assumed first day of month (we format labels as date ISO), end = last day of that month
        next_month = (start + pd.offsets.MonthBegin(1)).normalize()
        end = next_month - pd.Timedelta(microseconds=1)
    return start, end


@app.get("/")
def index():
    # Defaults: last 30 days
    today = pd.Timestamp.today().normalize()
    start = (today - pd.Timedelta(days=30)).date().isoformat()
    end = today.date().isoformat()
    ui_base = GLPI_URL
    if ui_base.endswith("/apirest.php"):
        ui_base = ui_base[: -len("/apirest.php")]
    return render_template(
        "index.html",
        default_start=start,
        default_end=end,
        ui_base=ui_base,
    )


@app.get("/api/data")
def api_data():
    """Endpoint principal de dados.

    Requisitos novos:
    - Sempre coletar (por padrão) os ÚLTIMOS 6 MESES de tickets (janela baseline),
      independentemente do filtro informado na tela, para alimentar widgets que
      precisam de histórico amplo.
    - EXCETO: se o range solicitado pelo usuário estiver FORA da janela padrão
      (isto é, não contido totalmente dentro dos últimos 6 meses). Nesse caso, a
      coleta usa o range do usuário (não forçamos truncar para 6 meses).
    - Widgets que DEVEM respeitar o filtro informado na tela (usar df_filtrado):
        cumGap (created/resolved), backlog (e trend), category, resolutionHours.
        - Widgets que DEVEM ignorar o filtro e usar SEMPRE a janela baseline de 6 meses
            (ou o range estendido quando o usuário sai dessa janela): aging, backlogStatus,
            openToday, createdToday.
    - Sinalizar nos widgets que ignoram o período com a mensagem
      "Ignora filtro de período" (markup em index.html cuida da exibição; aqui
      expomos metadados para possível uso futuro).
    """
    try:
        # --- Params ---
        gran = request.args.get("gran", "Diário")
        mode = request.args.get("mode", "bulk").lower()
        cat_filter = request.args.get("cat", "todos").lower()
        gl = gran.lower()
        freq = "D" if gl.startswith("di") else ("W" if gl.startswith("se") else "M")

        # --- Date range (user) ---
        start_s = request.args.get("start")
        end_s = request.args.get("end")
        if not start_s or not end_s:
            today_norm = pd.Timestamp.today().normalize()
            start_s = (today_norm - pd.Timedelta(days=30)).date().isoformat()
            end_s = today_norm.date().isoformat()
        user_start = pd.Timestamp(start_s).normalize()
        user_end = pd.Timestamp(end_s).normalize()

        # --- Baseline range (fixed last 6 months) ---
        today_norm = pd.Timestamp.today().normalize()
        baseline_start = (today_norm - pd.DateOffset(months=6)).normalize()
        baseline_end = today_norm

        # Fetch both datasets
        baseline_df, baseline_meta = _fetch_data(baseline_start, baseline_end, mode=mode)
        user_df, user_meta = _fetch_data(user_start, user_end, mode=mode)
        meta = {**baseline_meta, "tids_baseline": baseline_meta.get("tids"), "tids_user": user_meta.get("tids")}

        def filter_category(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty or cat_filter == "todos":
                return df
            # We'll try to classify by category name fields captured in bulk (we only have ID). Without name we can't split.
            # If only numeric id present, skip filtering (can't determine prefix) to avoid dropping all.
            name_cols = [c for c in ["category_fullname", "category_name", "category_label"] if c in df.columns]
            if name_cols:
                col = name_cols[0]
                s = df[col].astype(str).fillna("")
            else:
                # Try to reuse raw 'category' if it already contains text (some GLPI setups expand dropdowns to text)
                if df["category"].dtype == object:
                    s = df["category"].astype(str).fillna("")
                else:
                    return df  # cannot classify
            mask_h = s.str.startswith("Holding", na=False)
            if cat_filter == "holding":
                return df[mask_h].copy()
            if cat_filter == "unimed":
                return df[~mask_h].copy()
            return df

        baseline_df = filter_category(baseline_df)
        user_df = filter_category(user_df)

        # If user filtered dataset empty -> return baseline widgets + empty filtered ones
        if user_df is None or user_df.empty:
            empty = {"labels": [], "data": []}
            if baseline_df is None or baseline_df.empty:
                return jsonify({
                    "meta": {**meta, "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                              "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                              "ignore_period_widgets": ["aging","backlog_status","open_today","created_today"],
                              "aging_note": "Gráfico Aging mostra backlog atual ignorando filtro de período."},
                    "count": 0,
                    "note": "Nenhum ticket no filtro e baseline vazia.",
                    "series": {k: empty for k in ["created","resolved","backlog","backlog_trend","category","resolution_hours","resolution_hours_trend","backlog_status","aging","priority","impact","load_by_user","load_by_group"]},
                    "sla": {},
                    "open_today": 0,
                    "created_today": 0,
                })
            # Baseline-only metrics
            bs_full = backlog_status(baseline_df)
            age_full = aging_buckets(baseline_df)
            sla = sla_solution(baseline_df)
            open_today_full = int(baseline_df[baseline_df["solved_at"].isna()].shape[0])
            today_norm = pd.Timestamp.today().normalize()
            created_today_mask = (pd.to_datetime(baseline_df["created_at"]) >= today_norm) & (pd.to_datetime(baseline_df["created_at"]) < today_norm + pd.Timedelta(days=1))
            created_today_count = int(created_today_mask.sum())
            empty_series = {"labels": [], "data": []}
            return jsonify({
                "meta": {**meta, "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                          "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                          "ignore_period_widgets": ["aging","backlog_status","open_today","created_today"],
                          "aging_note": "Gráfico Aging mostra backlog atual ignorando filtro de período."},
                "count": 0,
                "note": "Sem tickets no intervalo filtrado; exibindo métricas de baseline.",
                "series": {
                    "created": empty_series,
                    "resolved": empty_series,
                    "backlog": empty_series,
                    "backlog_trend": empty_series,
                    "category": empty_series,
                    "resolution_hours": empty_series,
                    "resolution_hours_trend": empty_series,
                    "backlog_status": _dict_to_labels_data(bs_full),
                    "aging": _dict_to_labels_data(age_full),
                    "priority": empty_series,
                    "impact": empty_series,
                    "load_by_user": empty_series,
                    "load_by_group": empty_series,
                },
                "sla": sla,
                "open_today": open_today_full,
                "created_today": created_today_count,
            })

        # Build extended + strict windows for user data
        created_all = pd.to_datetime(user_df["created_at"], errors="coerce")
        solved_all = pd.to_datetime(user_df["solved_at"], errors="coerce")
        end_boundary = user_end + pd.Timedelta(days=1)
        mask_strict = (created_all >= user_start) & (created_all < end_boundary)
        spans_window = ((created_all < user_start) & ((solved_all.isna()) | (solved_all >= user_start))) | (
            (solved_all.notna()) & (solved_all >= user_start) & (solved_all < end_boundary))
        df_extended = user_df[mask_strict | spans_window].copy()
        df_strict = user_df[mask_strict].copy()
        df_extended.attrs.update(window_start=user_start, window_end=user_end)
        df_strict.attrs.update(window_start=user_start, window_end=user_end)

        if df_strict.empty:
            created = pd.Series(dtype=float)
            resolved = pd.Series(dtype=float)
            _c_ext, _r_ext, backlog_ext = created_resolved(df_extended, freq=freq)
            backlog_trend = backlog_trend_series(backlog_ext)
            cat_filtered = pd.Series(dtype=float)
            pr_filtered = pd.Series(dtype=float)
            imp_filtered = pd.Series(dtype=float)
        else:
            created, resolved, _discard = created_resolved(df_strict, freq=freq)
            _c_ext, _r_ext, backlog_ext = created_resolved(df_extended, freq=freq)
            backlog_trend = backlog_trend_series(backlog_ext)
            cat_filtered, pr_filtered, imp_filtered = composition(df_strict)

        # Resolution hours by solved_at in window
        solved_dt_ext = pd.to_datetime(df_extended["solved_at"], errors="coerce")
        res_mask = solved_dt_ext.notna() & (solved_dt_ext >= user_start) & (solved_dt_ext < end_boundary)
        df_resolved_window = df_extended[res_mask].copy()
        resolution_hours_series = resolution_time_series(df_resolved_window, freq=freq)
        resolution_hours_trend = backlog_trend_series(resolution_hours_series)

        # Baseline-only widgets
        bs_full = backlog_status(baseline_df)
        age_full = aging_buckets(baseline_df)
        sla = sla_solution(baseline_df)
        open_today_full = int(baseline_df[baseline_df["solved_at"].isna()].shape[0])
        created_today_mask = (pd.to_datetime(baseline_df["created_at"]) >= today_norm) & (pd.to_datetime(baseline_df["created_at"]) < today_norm + pd.Timedelta(days=1))
        created_today_count = int(created_today_mask.sum())
        load = load_by_assignee(df_strict)

        def map_series_labels(s: pd.Series, mapper: dict):
            if s is None or s.empty:
                return s
            mapped = []
            for k in s.index:
                try:
                    name = mapper.get(int(k))
                except Exception:
                    name = mapper.get(str(k)) if isinstance(k, str) else None
                if name is None:
                    name = str(k)
                mapped.append(name)
            out = pd.Series(s.values, index=mapped)
            return out.groupby(level=0).sum()

        bs_named = map_series_labels(bs_full, STATUS_MAP)
        pr_named = map_series_labels(pr_filtered, LEVEL_MAP)
        imp_named = map_series_labels(imp_filtered, LEVEL_MAP)

        payload = {
            "meta": {**meta,
                      "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                      "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                      "ignore_period_widgets": ["aging","backlog_status","open_today","created_today"],
                      "aging_note": "Gráfico Aging mostra backlog atual ignorando filtro de período."},
            "count": int(len(df_strict)),
            "period": {"start": start_s, "end": end_s, "gran": gran},
            "series": {
                "created": _series_to_labels_data(created),
                "resolved": _series_to_labels_data(resolved),
                "backlog": _series_to_labels_data(backlog_ext),
                "backlog_trend": _series_to_labels_data(backlog_trend) if backlog_trend is not None else {"labels": [], "data": []},
                "category": _dict_to_labels_data(cat_filtered),
                "resolution_hours": _series_to_labels_data(resolution_hours_series),
                "resolution_hours_trend": _series_to_labels_data(resolution_hours_trend) if resolution_hours_trend is not None else {"labels": [], "data": []},
                "backlog_status": _dict_to_labels_data(bs_named),
                "aging": _dict_to_labels_data(age_full),
                "priority": _dict_to_labels_data(pr_named),
                "impact": _dict_to_labels_data(imp_named),
                "load_by_user": _dict_to_labels_data(load.get("by_user")) if "by_user" in load else {"labels": [], "data": []},
                "load_by_group": _dict_to_labels_data(load.get("by_group")) if "by_group" in load else {"labels": [], "data": []},
            },
            "sla": sla,
            "open_today": open_today_full,
            "created_today": created_today_count,
        }
        return jsonify(payload)
    except Exception as e:  # pragma: no cover
        return jsonify({"error": str(e)}), 500


@app.get("/favicon.ico")
def favicon():
    # Avoid 404 noise; you can replace with a real icon in static if desired
    return ("", 204)


@app.get("/api/tickets")
def api_tickets():
    """Return ticket list for a clicked chart point/bar.

    Query params:
    - start, end: janela efetiva usada para coleta (baseline ou user)
    - ustart, uend: janela original solicitada pelo usuário (para filtrar séries que respeitam filtro)
    - source: created|resolved|backlog|backlog_status|aging|category|priority|impact|load_by_user|load_by_group|open_today|created_today
    - label: label ou id clicado
    - baseline=1 indica que start/end representam a janela baseline de 6 meses
    """
    try:
        gran = request.args.get("gran", "Diário")
        mode = request.args.get("mode", "bulk").lower()
        start_s = request.args.get("start")
        end_s = request.args.get("end")
        user_start_s = request.args.get("ustart") or start_s
        user_end_s = request.args.get("uend") or end_s
        source = request.args.get("source", "")
        label = request.args.get("label", "")
        baseline_flag = request.args.get("baseline", "0") == "1"
        cat_filter = request.args.get("cat", "todos").lower()

        if not start_s or not end_s:
            today = pd.Timestamp.today().normalize()
            start_s = (today - pd.Timedelta(days=30)).date().isoformat()
            end_s = today.date().isoformat()
        df, meta = _fetch_data(pd.Timestamp(start_s), pd.Timestamp(end_s), mode=mode)
        # Aplicar filtro de categoria igual ao /api/data
        if df is not None and not df.empty and cat_filter not in ("todos", ""):
            name_cols = [c for c in ["category_fullname", "category_name", "category_label"] if c in df.columns]
            if name_cols:
                col = name_cols[0]
                s = df[col].astype(str).fillna("")
            else:
                if df["category"].dtype == object:
                    s = df["category"].astype(str).fillna("")
                else:
                    s = None
            if s is not None:
                mask_h = s.str.startswith("Holding", na=False)
                if cat_filter == "holding":
                    df = df[mask_h].copy()
                elif cat_filter == "unimed":
                    df = df[~mask_h].copy()
                meta["cat_filter"] = cat_filter
        if df is None or df.empty:
            return jsonify({"meta": meta, "count": 0, "tickets": []})

        # Converter campos de data
        df_created = pd.to_datetime(df["created_at"], errors="coerce")
        df_solved = pd.to_datetime(df["solved_at"], errors="coerce")
        user_start = pd.Timestamp(user_start_s).normalize()
        user_end = pd.Timestamp(user_end_s).normalize()
        end_boundary = user_end + pd.Timedelta(days=1)

        # Determinar subset que respeita filtro (created dentro da janela do usuário)
        mask_strict = (df_created >= user_start) & (df_created < end_boundary)
        df_strict = df[mask_strict].copy()

        # Para backlog precisamos incluir tickets criados antes mas abertos ou resolvidos dentro
        spans_window = (
            (df_created < user_start) & ((df_solved.isna()) | (df_solved >= user_start))
        ) | (
            (df_solved.notna()) & (df_solved >= user_start) & (df_solved < end_boundary)
        )
        df_extended = df[mask_strict | spans_window].copy()

        now = pd.Timestamp.now()

        # Seleção baseada na fonte
        sel = pd.DataFrame()
        if source in ("created", "resolved"):
            # label => período
            ps, pe = _period_bounds_from_label(label, gran)
            if source == "created":
                base = df_strict  # created respeita filtro
                created_dt = pd.to_datetime(base["created_at"], errors="coerce")
                sel = base[(created_dt >= ps) & (created_dt <= pe)]
            else:  # resolved
                base = df_strict
                solved_dt = pd.to_datetime(base["solved_at"], errors="coerce")
                sel = base[(solved_dt.notna()) & (solved_dt >= ps) & (solved_dt <= pe)]
        elif source == "backlog":
            ps, pe = _period_bounds_from_label(label, gran)
            base = df_extended  # backlog precisa considerar anteriores
            created_dt = pd.to_datetime(base["created_at"], errors="coerce")
            solved_dt = pd.to_datetime(base["solved_at"], errors="coerce")
            sel = base[(created_dt <= pe) & ((solved_dt.isna()) | (solved_dt > pe))]
        elif source == "backlog_status":
            st = None
            try:
                st = int(float(label))
            except Exception:
                inv = {v.lower(): k for k, v in STATUS_MAP.items()}
                st = inv.get(str(label).lower())
            base = df if baseline_flag else df_strict
            open_mask = base["solved_at"].isna()
            sel = base[open_mask & ((base["status"] == st) if st is not None else False)]
        elif source == "aging":
            base = df if baseline_flag else df_strict
            ages = (now - pd.to_datetime(base["created_at"], errors="coerce")) .dt.total_seconds() / 86400.0
            bins = [-1, 2, 7, 14, 30, 60, 999999]
            labels = ["0–2d", "3–7d", "8–14d", "15–30d", "31–60d", ">60d"]
            cats = pd.cut(ages, bins=bins, labels=labels)
            sel = base[(base["solved_at"].isna()) & (cats.astype(str) == label)]
        elif source == "open_today":
            base = df
            sel = base[base["solved_at"].isna()]
        elif source == "created_today":
            base = df
            today_norm = pd.Timestamp.today().normalize()
            created_dt = pd.to_datetime(base["created_at"], errors="coerce")
            sel = base[(created_dt >= today_norm) & (created_dt < today_norm + pd.Timedelta(days=1))]
        elif source in ("category", "priority", "impact"):
            base = df_strict  # respeitam filtro agora
            col = {"category": "category", "priority": "priority", "impact": "impact"}[source]
            if source in ("priority", "impact"):
                try:
                    v = int(float(label))
                    sel = base[base[col] == v]
                except Exception:
                    inv = {v.lower(): k for k, v in LEVEL_MAP.items()}
                    mapped = inv.get(str(label).lower())
                    if mapped is None:
                        sel = base[base[col].astype(str) == str(label)]
                    else:
                        sel = base[base[col] == mapped]
            else:
                sel = base[base[col].astype(str) == str(label)]
        elif source in ("load_by_user", "load_by_group"):
            base = df_strict
            col = "assigned_user" if source == "load_by_user" else "assigned_group"
            try:
                v = int(float(label))
            except Exception:
                v = None
            if v is None:
                sel = base[base[col].isna()]
            else:
                sel = base[base[col] == v]
        else:
            sel = df_strict

        # Build detailed rows with names
        client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)
        client.init_session(get_full=False)
        try:
            user_cache: Dict[int, str] = {}
            group_cache: Dict[int, str] = {}
            cat_cache: Dict[int, str] = {}
            rows = []
            for _, r in sel.head(1000).iterrows():  # safety cap
                tid = int(r.get("ticket_id"))
                try:
                    t = client.get_item("Ticket", tid)
                except Exception:
                    t = {}
                title = t.get("name") or t.get("title") or ""
                created = t.get("date") or r.get("created_at")
                updated = t.get("date_mod") or t.get("date_modification") or None
                status_val = t.get("status") if t.get("status") is not None else r.get("status")
                status_name = STATUS_MAP.get(int(status_val)) if status_val is not None else ""
                req_id = t.get("users_id_recipient")
                if not req_id:
                    # fallback via Ticket_User type=1
                    try:
                        tus = client.get_subitems("Ticket", tid, "Ticket_User", params={"range": "0-99"})
                        for tu in tus or []:
                            if int(str(tu.get("type") or 0)) == 1:
                                req_id = tu.get("users_id")
                                break
                    except Exception:
                        pass
                assigned_uid = t.get("users_id_assign") or r.get("assigned_user")
                assigned_gid = t.get("groups_id_assign") or r.get("assigned_group")
                cat_id = t.get("itilcategories_id") or r.get("category")

                requester_name = _resolve_user_name(client, req_id, user_cache) if req_id else ""
                assigned_user_name = _resolve_user_name(client, assigned_uid, user_cache) if assigned_uid else ""
                assigned_group_name = _resolve_group_name(client, assigned_gid, group_cache) if assigned_gid else ""
                cat_name = _resolve_category_name(client, cat_id, cat_cache) if cat_id else ""

                rows.append({
                    "id": tid,
                    "titulo": title,
                    "status": status_name,
                    "categoria": cat_name,
                    "abertura": created,
                    "ultima_atualizacao": updated,
                    "requerente": requester_name,
                    "grupo_atribuido": assigned_group_name,
                    "tecnico_atribuido": assigned_user_name,
                })
        finally:
            client.kill_session()

        return jsonify({
            "meta": meta,
            "count": len(sel),
            "returned": len(rows),
            "tickets": rows,
            "source": source,
            "label": label,
            "baseline": baseline_flag,
            "user_window": {"start": user_start_s, "end": user_end_s},
            "fetch_window": {"start": start_s, "end": end_s},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
