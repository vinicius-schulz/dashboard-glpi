"""
Data access utilities for GLPI: search options discovery and ticket collection.
"""
from typing import Dict, List, Any, Optional, Tuple, Set
import pandas as pd

from glpi_client import GLPIClient


# -------------------- Descoberta de SIDs (Group_Ticket) --------------------

def discover_group_ticket_sids(client: GLPIClient) -> Tuple[int, int]:
    """Descobre os SIDs de campos em Group_Ticket.

    Retorna uma tupla (sid_ticket_id, sid_group_id) para uso nas buscas.
    Caso não encontre nos metadados, usa fallback (3, 4).
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
    """Busca tickets relacionados a grupos em Group_Ticket (qualquer type).

    - Faz paginação por "range" na rota search/Group_Ticket.
    - Retorna o conjunto de Ticket.id vinculados a qualquer grupo em group_ids.
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
    """Filtra tickets onde o grupo é Observador (type == 3).

    Mantém apenas os tickets que possuem vínculo Group_Ticket com:
    - groups_id presente em group_ids, e
    - type == 3 (observador).
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
    """Carrega detalhes dos tickets e aplica filtro por data de criação.

    Colunas retornadas: ticket_id, created_at, solved_at, closed_at, status,
    priority, urgency, impact, ttr_deadline, category, assigned_user, assigned_group.
    """
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
    # Filtro ampliado de janela:
    # - Mantém tickets criados dentro do intervalo
    # - Inclui tickets criados antes mas resolvidos dentro do intervalo
    # - Inclui tickets criados antes e ainda abertos no início do intervalo (para backlog inicial)
    if not df.empty and (dt_ini is not None or dt_fim is not None):
        c = pd.to_datetime(df["created_at"], errors="coerce")
        s = pd.to_datetime(df["solved_at"], errors="coerce")
        # Limites (fim exclusivo +1 dia para facilitar comparação por dia inteiro)
        dt_start = pd.to_datetime(dt_ini) if dt_ini is not None else c.min()
        dt_end = (pd.to_datetime(dt_fim) + pd.Timedelta(days=1)) if dt_fim is not None else (c.max() + pd.Timedelta(days=1))
        # Condições
        in_created_window = (c >= dt_start) & (c < dt_end)
        resolved_in_window = s.notna() & (s >= dt_start) & (s < dt_end)
        open_at_start = (c < dt_start) & ((s.isna()) | (s >= dt_start))
        mask = in_created_window | resolved_in_window | open_at_start
        df = df[mask]
        # Guardar metadados da janela (end inclusivo) para cálculo de séries posterior
        try:
            df.attrs["window_start"] = dt_start.normalize()
            # end inclusivo real = dt_end - 1 dia
            df.attrs["window_end"] = (dt_end - pd.Timedelta(days=1)).normalize()
        except Exception:
            pass
    return df
