"""
Flask web app replacing Streamlit: HTML front-end + JSON API.

Endpoints:
- GET /            -> HTML page
- GET /api/data    -> Returns computed metrics as JSON

Env vars: GLPI_URL, GLPI_USER_TOKEN, MAX_TICKETS (optional)
"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import pandas as pd
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

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


load_dotenv()
GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "")
DEFAULT_MAX_TICKETS = int(os.getenv("MAX_TICKETS", "800"))

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


def _fetch_data(dini: pd.Timestamp, dfim: pd.Timestamp, max_tix: int) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if not GLPI_URL or not GLPI_USER_TOKEN:
        raise RuntimeError("GLPI_URL e GLPI_USER_TOKEN precisam estar definidos no .env")

    client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)
    client.init_session(get_full=True)
    try:
        if not client.my_group_ids:
            return pd.DataFrame(), {"groups": [], "note": "Nenhum grupo retornado em getFullSession (session.glpigroups)."}

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
        meta = {
            "groups": client.my_group_ids,
            "sid_ticket": sid_ticket,
            "sid_group": sid_group,
            "tids_total": len(tset),
            "tids_obs": len(tids_obs),
        }
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
    if gran.lower().startswith("di"):
        end = start + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    else:
        end = start + pd.Timedelta(weeks=1) - pd.Timedelta(microseconds=1)
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
        default_max=DEFAULT_MAX_TICKETS,
        ui_base=ui_base,
    )


@app.get("/api/data")
def api_data():
    try:
        gran = request.args.get("gran", "Diário")
        freq = "D" if gran.lower().startswith("di") else "W"
        start_s = request.args.get("start")
        end_s = request.args.get("end")
        max_tix = int(request.args.get("max", str(DEFAULT_MAX_TICKETS)))

        if not start_s or not end_s:
            today = pd.Timestamp.today().normalize()
            start_s = (today - pd.Timedelta(days=30)).date().isoformat()
            end_s = today.date().isoformat()

        df, meta = _fetch_data(pd.Timestamp(start_s), pd.Timestamp(end_s), max_tix)

        if df is None or df.empty:
            return jsonify({
                "meta": meta,
                "count": 0,
                "note": meta.get("note", "Nenhum ticket encontrado"),
                "series": {},
            })

        created, resolved, backlog = created_resolved(df, freq=freq)
        bs = backlog_status(df)
        sla = sla_solution(df)
        age = aging_buckets(df)
        cat, pr, imp = composition(df)
        load = load_by_assignee(df)

        payload: Dict[str, Any] = {
            "meta": meta,
            "count": int(len(df)),
            "period": {"start": start_s, "end": end_s, "gran": gran},
            "series": {
                "created": _series_to_labels_data(created),
                "resolved": _series_to_labels_data(resolved), 
                "backlog": _series_to_labels_data(backlog),
                "backlog_status": _dict_to_labels_data(bs),
                "aging": _dict_to_labels_data(age),
                "category": _dict_to_labels_data(cat),
                "priority": _dict_to_labels_data(pr),
                "impact": _dict_to_labels_data(imp),
                "load_by_user": _dict_to_labels_data(load.get("by_user")) if "by_user" in load else {"labels": [], "data": []},
                "load_by_group": _dict_to_labels_data(load.get("by_group")) if "by_group" in load else {"labels": [], "data": []},
            },
            "sla": sla,
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/favicon.ico")
def favicon():
    # Avoid 404 noise; you can replace with a real icon in static if desired
    return ("", 204)


@app.get("/api/tickets")
def api_tickets():
    """Return ticket list for a clicked chart point/bar.

    Query params:
    - start, end, gran, max: same window as main view
    - source: created|resolved|backlog|backlog_status|aging|category|priority|impact|load_by_user|load_by_group
    - label: label or id clicked (string)
    """
    try:
        gran = request.args.get("gran", "Diário")
        start_s = request.args.get("start")
        end_s = request.args.get("end")
        max_tix = int(request.args.get("max", str(DEFAULT_MAX_TICKETS)))
        source = request.args.get("source", "")
        label = request.args.get("label", "")
        now = pd.Timestamp.now()

        if not start_s or not end_s:
            today = pd.Timestamp.today().normalize()
            start_s = (today - pd.Timedelta(days=30)).date().isoformat()
            end_s = today.date().isoformat()

        df, meta = _fetch_data(pd.Timestamp(start_s), pd.Timestamp(end_s), max_tix)
        if df is None or df.empty:
            return jsonify({"meta": meta, "count": 0, "tickets": []})

        # Apply selection filter
        sel = pd.DataFrame()
        if source in ("created", "resolved", "backlog"):
            ps, pe = _period_bounds_from_label(label, gran)
            if source == "created":
                sel = df[
                    (pd.to_datetime(df["created_at"]) >= ps) & (pd.to_datetime(df["created_at"]) <= pe)
                ]
            elif source == "resolved":
                sel = df[
                    (df["solved_at"].notna()) & (pd.to_datetime(df["solved_at"]) >= ps) & (pd.to_datetime(df["solved_at"]) <= pe)
                ]
            else:  # backlog at period end
                sel = df[
                    (pd.to_datetime(df["created_at"]) <= pe)
                    & (
                        (df["solved_at"].isna())
                        | (pd.to_datetime(df["solved_at"]) > pe)
                    )
                ]
        elif source == "backlog_status":
            try:
                st = int(float(label))
            except Exception:
                st = None
            open_mask = df["closed_at"].isna()
            sel = df[open_mask & ((df["status"] == st) if st is not None else False)]
        elif source == "aging":
            ages = (now - pd.to_datetime(df["created_at"])) .dt.total_seconds() / 86400.0
            bins = [-1, 2, 7, 14, 30, 999999]
            labels = ["0–2d", "3–7d", "8–14d", "15–30d", ">30d"]
            cats = pd.cut(ages, bins=bins, labels=labels)
            sel = df[(df["closed_at"].isna()) & (cats.astype(str) == label)]
        elif source in ("category", "priority", "impact"):
            col = {"category": "category", "priority": "priority", "impact": "impact"}[source]
            sel = df[df[col].astype(str) == str(label)]
        elif source in ("load_by_user", "load_by_group"):
            col = "assigned_user" if source == "load_by_user" else "assigned_group"
            try:
                v = int(float(label))
            except Exception:
                v = None
            if v is None:
                sel = df[df[col].isna()]
            else:
                sel = df[df[col] == v]
        else:
            sel = df

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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
