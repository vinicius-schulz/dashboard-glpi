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
        include_assigned_groups: bool = True,
        assigned_group_field_id: Optional[int] = None,
) -> pd.DataFrame:
    """Busca tickets onde qualquer grupo informado atua como Observador e (opcional) onde atua como Grupo técnico (atribuído).

    Expansão: incluir (quando include_assigned_groups=True) tickets onde o grupo é "Grupo técnico" (atribuição),
    além do papel "Grupo observador". Tickets duplicados são deduplicados por ticket_id.
    """
    if not observer_group_ids:
        return pd.DataFrame()

    # 1. Descobrir dinamicamente IDs dos campos (observer / grupo técnico)
    if observer_field_id is None or (include_assigned_groups and assigned_group_field_id is None):
        try:
            opts = client.list_search_options("Ticket") or {}
        except Exception:
            opts = {}
        if observer_field_id is None:
            for k, spec in opts.items():
                if str(k).isdigit():
                    nm = (spec.get("name") or "").lower()
                    if "observador" in nm and "grupo" in nm:
                        try:
                            observer_field_id = int(k)
                            break
                        except Exception:
                            pass
        if include_assigned_groups and assigned_group_field_id is None:
            for k, spec in opts.items():
                if str(k).isdigit():
                    nm = (spec.get("name") or "").lower()
                    if "grupo" in nm and "técnico" in nm:
                        try:
                            assigned_group_field_id = int(k)
                            break
                        except Exception:
                            pass
    if observer_field_id is None:
        observer_field_id = 65
    if include_assigned_groups and assigned_group_field_id is None:
        assigned_group_field_id = 8

    # 2. Cache de nomes de grupos
    group_name_cache: Dict[int, Optional[str]] = {}
    for gid in observer_group_ids:
        try:
            name = client.try_get_group_name(gid) if hasattr(client, "try_get_group_name") else None
            if not name:
                g = client.get_item("Group", gid)
                name = g.get("completename") or g.get("name")
        except Exception:
            name = None
        group_name_cache[gid] = name

    rows: List[Dict[str, Any]] = []
    seen_ticket_ids: Set[int] = set()

    def _run(field_id: int, role: str):
        for gid, gname in group_name_cache.items():
            strategies: List[tuple] = []
            if gname:
                last_seg = gname.split(" > ")[-1].split("/")[-1].strip()
                strategies.append(("equals", gname, f"{role}:equals/full"))
                strategies.append(("contains", gname, f"{role}:contains/full"))
                if last_seg and last_seg != gname:
                    strategies.append(("contains", last_seg, f"{role}:contains/last_segment"))
            strategies.append(("equals", str(gid), f"{role}:equals/id"))

            for searchtype, value, tag in strategies:
                start = 0
                before = len(rows)
                while True:
                    params = {
                        "criteria[0][field]": str(field_id),
                        "criteria[0][searchtype]": searchtype,
                        "criteria[0][value]": value,
                        # forcedisplay selecionado para alimentar métricas
                        # 1 = título/name do ticket
                        "forcedisplay[0]": "1",
                        "forcedisplay[1]": "2",
                        "forcedisplay[2]": "15",
                        "forcedisplay[3]": "17",
                        "forcedisplay[4]": "16",
                        "forcedisplay[5]": "12",
                        "forcedisplay[6]": "3",
                        "forcedisplay[7]": "10",
                        "forcedisplay[8]": "11",
                        "forcedisplay[9]": "18",
                        "forcedisplay[10]": "7",
                        "forcedisplay[11]": "5",
                        "forcedisplay[12]": "8",
                        "forcedisplay[13]": "19",
                        "expand_dropdowns": "true",
                        "range": f"{start}-{start+range_chunk-1}",
                    }
                    try:
                        resp = client.raw_search("Ticket", params)
                        js = resp.json()
                    except Exception:
                        break
                    data = js.get("data", []) or []
                    if not data:
                        break
                    for row in data:
                        try:
                            tid = int(str(row.get("2")))
                        except Exception:
                            continue
                        if tid in seen_ticket_ids:
                            continue
                        seen_ticket_ids.add(tid)
                        rows.append({
                            "ticket_id": tid,
                            "title": row.get("1"),
                            "created_at": row.get("15"),
                            "solved_at": row.get("17"),
                            "closed_at": row.get("16"),
                            "status": row.get("12"),
                            "urgency": row.get("10"),
                            # impact removido
                            "ttr_deadline": row.get("18"),
                            "category": row.get("7"),
                            "assigned_user": row.get("5"),
                            "assigned_group": row.get("8"),
                            "observer_group": gname if role == "observer" else None,
                            "observer_strategy": tag if role == "observer" else None,
                            "observer_field_id": observer_field_id if role == "observer" else None,
                            "match_role": "observer" if role == "observer" else "assigned_group",
                            # Campo de última atualização (date_mod) — pode vir ausente em alguns registros.
                            "updated_at": row.get("19"),
                        })
                        if max_tickets is not None and len(rows) >= max_tickets:
                            break
                    if max_tickets is not None and len(rows) >= max_tickets:
                        break
                    cr = resp.headers.get("Content-Range", "0-0/0")
                    try:
                        end = int(cr.split("/")[0].split("-")[1])
                        total = int(cr.split("/")[1])
                    except Exception:
                        break
                    if end + 1 >= total:
                        break
                    start = end + 1
                if len(rows) > before:  # encontrou algo nesta estratégia => parar para próximo grupo
                    break
            if max_tickets is not None and len(rows) >= max_tickets:
                break

    _run(observer_field_id, role="observer")
    if include_assigned_groups and assigned_group_field_id is not None and (max_tickets is None or len(rows) < max_tickets):
        _run(assigned_group_field_id, role="assigned")

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if dt_ini is not None or dt_fim is not None:
        c = pd.to_datetime(df["created_at"], errors="coerce")
        s = pd.to_datetime(df["solved_at"], errors="coerce")
        dt_start = pd.to_datetime(dt_ini) if dt_ini is not None else c.min()
        dt_end = (pd.to_datetime(dt_fim) + pd.Timedelta(days=1)) if dt_fim is not None else (c.max() + pd.Timedelta(days=1))
        mask = (
            (c >= dt_start) & (c < dt_end)  # criados dentro
            | (s.notna() & (s >= dt_start) & (s < dt_end))  # resolvidos dentro
            | ((c < dt_start) & ((s.isna()) | (s >= dt_start)))  # abertos na borda inicial
        )
        df = df[mask]
        try:
            df.attrs["window_start"] = dt_start.normalize()
            df.attrs["window_end"] = (dt_end - pd.Timedelta(days=1)).normalize()
        except Exception:
            pass
    return df
