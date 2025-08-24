"""
Data access utilities for GLPI: simplified to a single optimized bulk-search flow.

This module provides `bulk_search_observer_tickets` which queries the Ticket
search endpoint using the "Grupo observador" field and returns a pandas DataFrame
with the selected fields. Legacy code paths that iterated Group_Ticket or made
per-ticket get_item calls were removed to reduce complexity.
"""

from typing import Dict, List, Any, Optional, Set
import pandas as pd

from glpi_client import GLPIClient
from instrumentation import timed


@timed
def bulk_search_observer_tickets(
    client: GLPIClient,
    observer_group_ids: List[int],
    dt_ini: Optional[pd.Timestamp],
    dt_fim: Optional[pd.Timestamp],
    range_chunk: int = 200,
    max_tickets: Optional[int] = None,
    observer_field_id: Optional[int] = None,
) -> pd.DataFrame:
    """Busca tickets onde qualquer grupo da lista atua como observador.

    Retorna um DataFrame com colunas compatíveis com as métricas do projeto
    (ticket_id, created_at, solved_at, closed_at, status, priority, urgency,
    impact, ttr_deadline, category, assigned_user, assigned_group, observer_group).
    """
    if not observer_group_ids:
        return pd.DataFrame()

    # Detecta dinamicamente o field id do "Grupo observador" quando possível
    if observer_field_id is None:
        try:
            opts = client.list_search_options("Ticket") or {}
            for k, spec in opts.items():
                if not str(k).isdigit():
                    continue
                nm = (spec.get("name") or "").lower()
                if "observador" in nm and "grupo" in nm:
                    observer_field_id = int(k)
                    break
        except Exception:
            observer_field_id = None
    if observer_field_id is None:
        observer_field_id = 65

    # Resolve nomes dos grupos (ou None) para tentar buscas por nome quando possível
    group_name_cache: Dict[int, Optional[str]] = {}
    for gid in observer_group_ids:
        try:
            if hasattr(client, "try_get_group_name"):
                name = client.try_get_group_name(gid)  # type: ignore[attr-defined]
            else:
                g = client.get_item("Group", gid)
                name = g.get("completename") or g.get("name")
        except Exception:
            name = None
        group_name_cache[gid] = name

    rows: List[Dict[str, Any]] = []
    seen_ticket_ids: Set[int] = set()

    for gid, gname in group_name_cache.items():
        strategies: List[tuple] = []
        if gname:
            last_seg = gname.split(" > ")[-1].split("/")[-1].strip()
            strategies.extend([
                ("equals", gname, "equals/full"),
                ("contains", gname, "contains/full"),
            ])
            if last_seg and last_seg != gname:
                strategies.append(("contains", last_seg, "contains/last_segment"))
        strategies.append(("equals", str(gid), "equals/id"))

        for searchtype, value, tag in strategies:
            start = 0
            total_added_before_strategy = len(rows)
            while True:
                params = {
                    "criteria[0][field]": str(observer_field_id),
                    "criteria[0][searchtype]": searchtype,
                    "criteria[0][value]": value,
                    "forcedisplay[0]": "2",
                    "forcedisplay[1]": "15",
                    "forcedisplay[2]": "17",
                    "forcedisplay[3]": "16",
                    "forcedisplay[4]": "12",
                    "forcedisplay[5]": "3",
                    "forcedisplay[6]": "10",
                    "forcedisplay[7]": "11",
                    "forcedisplay[8]": "18",
                    "forcedisplay[9]": "7",
                    "forcedisplay[10]": "5",
                    "forcedisplay[11]": "8",
                    "expand_dropdowns": "true",
                    "range": f"{start}-{start+range_chunk-1}",
                }
                try:
                    r = client.raw_search("Ticket", params)
                    js = r.json()
                except Exception:
                    break
                data = js.get("data", []) or []
                if not data:
                    break
                for row in data:
                    try:
                        tid_raw = row.get("2")
                        if tid_raw is None:
                            continue
                        tid = int(str(tid_raw))
                    except Exception:
                        continue
                    if tid in seen_ticket_ids:
                        continue
                    seen_ticket_ids.add(tid)
                    rec: Dict[str, Any] = {
                        "ticket_id": tid,
                        "created_at": row.get("15"),
                        "solved_at": row.get("17"),
                        "closed_at": row.get("16"),
                        "status": row.get("12"),
                        "priority": row.get("3"),
                        "urgency": row.get("10"),
                        "impact": row.get("11"),
                        "ttr_deadline": row.get("18"),
                        "category": row.get("7"),
                        "assigned_user": row.get("5"),
                        "assigned_group": row.get("8"),
                        "observer_group": gname,
                        "observer_strategy": tag,
                        "observer_field_id": observer_field_id,
                    }
                    rows.append(rec)
                    if max_tickets is not None and len(rows) >= max_tickets:
                        break
                if max_tickets is not None and len(rows) >= max_tickets:
                    break
                cr = r.headers.get("Content-Range", "0-0/0")
                try:
                    end = int(cr.split("/")[0].split("-")[1])
                    total = int(cr.split("/")[1])
                except Exception:
                    break
                if end + 1 >= total:
                    break
                start = end + 1
            if len(rows) > total_added_before_strategy:
                break
        if max_tickets is not None and len(rows) >= max_tickets:
            break

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Aplica a mesma lógica de janela ampliada usada anteriormente
    if dt_ini is not None or dt_fim is not None:
        c = pd.to_datetime(df["created_at"], errors="coerce")
        s = pd.to_datetime(df["solved_at"], errors="coerce")
        dt_start = pd.to_datetime(dt_ini) if dt_ini is not None else c.min()
        dt_end = (pd.to_datetime(dt_fim) + pd.Timedelta(days=1)) if dt_fim is not None else (c.max() + pd.Timedelta(days=1))
        in_created_window = (c >= dt_start) & (c < dt_end)
        resolved_in_window = s.notna() & (s >= dt_start) & (s < dt_end)
        open_at_start = (c < dt_start) & ((s.isna()) | (s >= dt_start))
        mask = in_created_window | resolved_in_window | open_at_start
        df = df[mask]
        try:
            df.attrs["window_start"] = dt_start.normalize()
            df.attrs["window_end"] = (dt_end - pd.Timedelta(days=1)).normalize()
        except Exception:
            pass
    return df
