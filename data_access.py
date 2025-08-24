"""
Data access utilities for GLPI: search options discovery and ticket collection.
"""
from typing import Dict, List, Any, Optional, Tuple, Set
import pandas as pd

from glpi_client import GLPIClient
from instrumentation import timed


# -------------------- Descoberta de SIDs (Group_Ticket) --------------------

@timed
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


# -------------------- Coleta de tickets observados (método legado) --------------------

@timed
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


@timed
def filter_observer_tickets(
    client: GLPIClient,
    ticket_ids: List[int],
    group_ids: List[int],
    max_tickets: int,
) -> List[int]:
    """LEGADO: Filtra tickets onde o grupo é Observador (type == 3) via subitens.

    Mantido apenas para compatibilidade / fallback. O novo fluxo usa search/Ticket
    diretamente pelo campo "Grupo observador" (id 65) e dispensa esta varredura.
    """
    gids = set(group_ids)
    out: List[int] = []
    for i, tid in enumerate(ticket_ids[: max_tickets]):
        try:
            subs = client.get_subitems("Ticket", tid, "Group_Ticket", params={"range": "0-1999"})
        except Exception:
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


@timed
def fetch_ticket_details(
    client: GLPIClient,
    ticket_ids: List[int],
    dt_ini: Optional[pd.Timestamp],
    dt_fim: Optional[pd.Timestamp],
) -> pd.DataFrame:
    """Carrega detalhes dos tickets dentro de uma janela ampliada.

    Inclui tickets criados antes da janela quando:
    - foram resolvidos dentro da janela, ou
    - permaneciam abertos no início (para backlog inicial).

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


# -------------------- Novo fluxo otimizado: busca em lote via search/Ticket --------------------

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
    """Busca tickets onde qualquer grupo da lista atua como OBSERVADOR usando o campo "Grupo observador" (id 65).

    Elimina a necessidade de:
      - discover_group_ticket_sids
      - find_ticket_ids_by_group_links
      - filter_observer_tickets
      - fetch_ticket_details (loop de get_item)

    Campos usados (IDs conforme listSearchOptions/Ticket fornecido):
      2=ID, 15=date (abertura), 17=solvedate, 16=closedate, 12=status,
      3=priority,10=urgency,11=impact,18=time_to_resolve,7=Categoria (nome),
      5=Técnico (nome), 8=Grupo técnico (nome), 65=Grupo observador (nome)

    Observação: O campo 65 exige o *nome completo* do grupo. Para minimizar
    chamadas extras ao endpoint de Group, tentamos derivar via get_item(Group,<id>). Uma
    chamada por grupo é muito mais barata do que centenas de get_subitems / get_item(Ticket).
    """
    if not observer_group_ids:
        return pd.DataFrame()

    # Descoberta dinâmica do field id (se não informado) procurando por algo como "Grupo observador"
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
        observer_field_id = 65  # fallback original

    # Mapeia id -> nome completo do grupo (com cache simples em memória)
    group_name_cache: Dict[int, Optional[str]] = {}
    for gid in observer_group_ids:
        try:
            g = client.get_item("Group", gid)  # reaproveita get_item genérico
            # GLPI normalmente expõe 'completename'; fallback para 'name'
            group_name_cache[gid] = g.get("completename") or g.get("name")
        except Exception:
            group_name_cache[gid] = None

    rows: List[Dict[str, Any]] = []
    seen_ticket_ids: Set[int] = set()

    # Para cada grupo faz paginação. (Poderíamos tentar OR em uma única chamada, mas
    # multiplicaria critérios e complexidade; custo de poucos grupos costuma ser baixo.)
    for gid, gname in group_name_cache.items():
        # Estratégias de busca (searchtype, valor, descrição)
        strategies: List[Tuple[str, str, str]] = []
        if gname:
            last_seg = gname.split(" > ")[-1].split("/")[-1].strip()
            strategies.extend([
                ("equals", gname, "equals/full"),
                ("contains", gname, "contains/full"),
            ])
            if last_seg and last_seg != gname:
                strategies.append(("contains", last_seg, "contains/last_segment"))
        # Sempre tenta por ID numérico (cobre caso campo armazene id, mesmo sem nome por falta de permissão)
        strategies.append(("equals", str(gid), "equals/id"))

        matched_any = False
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
            # Se esta estratégia adicionou algo, não tenta próximas (evita duplicado via contains)
            if len(rows) > total_added_before_strategy:
                matched_any = True
                break
        # Próximo grupo
        if max_tickets is not None and len(rows) >= max_tickets:
            break

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Aplica a mesma lógica de janela ampliada localmente (como em fetch_ticket_details)
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
