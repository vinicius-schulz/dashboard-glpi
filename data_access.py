"""
Data access utilities for GLPI: search options discovery and ticket collection.
"""
from typing import Dict, List, Any, Optional, Tuple, Set
import pandas as pd

from glpi_client import GLPIClient


# -------------------- Descoberta de SIDs (Group_Ticket) --------------------

def discover_group_ticket_sids(client: GLPIClient) -> Tuple[int, int]:
    """
    Retorna (sid_ticket_id, sid_group_id) para Group_Ticket.
    Fallback para (3,4) se não encontrar.
    """
    opts = client.list_search_options("Group_Ticket")
    sid_ticket, sid_group = None, None
    for key, spec in opts.items():
        if not str(key).isdigit():
            continue
        uid = spec.get("uid") or ""
        table = (spec.get("table") or "").lower()
        field = (spec.get("field") or "").lower()
        # Ticket.id
        if uid == "Group_Ticket.Ticket.id" or (table == "glpi_tickets" and field == "id"):
            sid_ticket = int(key)
        # Group.id
        if uid == "Group_Ticket.Group.id" or (table == "glpi_groups" and field == "id"):
            sid_group = int(key)
    if sid_ticket is None:
        sid_ticket = 3  # conforme seu ambiente
    if sid_group is None:
        sid_group = 4
    return sid_ticket, sid_group


# -------------------- Coleta de tickets observados --------------------

def find_ticket_ids_by_group_links(
    client: GLPIClient,
    group_ids: List[int],
    sid_ticket: int,
    sid_group: int,
    range_chunk: int = 2000,
) -> Set[int]:
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
                    try:
                        ticket_ids.add(int(str(tid)))
                    except Exception:
                        pass
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


def filter_observer_tickets(
    client: GLPIClient,
    ticket_ids: List[int],
    group_ids: List[int],
    max_tickets: int,
) -> List[int]:
    """
    Mantém apenas tickets em que pelo menos um vínculo Group_Ticket tem:
      - groups_id ∈ group_ids
      - type == 3 (observador)
    Consulta Ticket/<id>/Group_Ticket ticket-a-ticket.
    """
    gids = set(group_ids)
    out: List[int] = []
    for i, tid in enumerate(ticket_ids[: max_tickets]):
        try:
            subs = client.get_subitems("Ticket", tid, "Group_Ticket", params={"range": "0-1999"})
        except Exception:
            # sem permissão para subitens => não conseguimos filtrar por type; ignore esse ticket
            continue
        ok = False
        for link in subs or []:
            try:
                if int(str(link.get("groups_id"))) in gids and int(str(link.get("type"))) == 3:
                    ok = True
                    break
            except Exception:
                continue
        if ok:
            out.append(tid)
    return out


def fetch_ticket_details(
    client: GLPIClient,
    ticket_ids: List[int],
    dt_ini: Optional[pd.Timestamp],
    dt_fim: Optional[pd.Timestamp],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for tid in ticket_ids:
        try:
            t = client.get_item("Ticket", tid)
        except Exception:
            continue
        rec: Dict[str, Any] = {
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
