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


@app.get("/")
def index():
    # Defaults: last 30 days
    today = pd.Timestamp.today().normalize()
    start = (today - pd.Timedelta(days=30)).date().isoformat()
    end = today.date().isoformat()
    return render_template("index.html", default_start=start, default_end=end, default_max=DEFAULT_MAX_TICKETS)


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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
