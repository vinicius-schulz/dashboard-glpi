import os, base64
from typing import Dict, List, Any, Optional
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

class GLPIClient:
    def __init__(self, base_url: str, app_token: str = "", user: str = "", password: str = "", user_token: str = ""):
        self.base = base_url.rstrip("/") + "/apirest.php"
        self.session = requests.Session()
        self.session_token = None
        self.headers = {"Content-Type": "application/json"}
        if app_token:
            self.headers["App-Token"] = app_token
        self._user = user
        self._password = password
        self._user_token = user_token

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def init_session(self, get_full: bool = True):
        url = f"{self.base}/initSession"
        hdrs = dict(self.headers)
        if self._user_token:
            hdrs["Authorization"] = f"user_token {self._user_token}"
        else:
            basic = base64.b64encode(f"{self._user}:{self._password}".encode()).decode()
            hdrs["Authorization"] = f"Basic {basic}"
        params = {"get_full_session": "true"} if get_full else {}
        r = self.session.get(url, headers=hdrs, params=params, timeout=30)
        r.raise_for_status()
        self.session_token = r.json()["session_token"]
        self.headers["Session-Token"] = self.session_token

    def kill_session(self):
        if not self.session_token: return
        try:
            self.session.get(f"{self.base}/killSession", headers=self.headers, timeout=15)
        finally:
            self.session_token = None
            self.headers.pop("Session-Token", None)

    def list_search_options(self, itemtype: str) -> Dict[str, Any]:
        r = self.session.get(f"{self.base}/listSearchOptions/{itemtype}", headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.json()

    def search(self, itemtype: str, criteria: List[Dict[str, Any]], forcedisplay: List[int], range_chunk=2000) -> List[Dict[str, Any]]:
        """Varre com paginação via Content-Range."""
        url = f"{self.base}/search/{itemtype}"
        start, out = 0, []
        while True:
            params = {"range": f"{start}-{start+range_chunk-1}"}
            for i, c in enumerate(criteria):
                for k, v in c.items():
                    params[f"criteria[{i}][{k}]"] = v
            for i, fd in enumerate(forcedisplay):
                params[f"forcedisplay[{i}]"] = fd
            r = self.session.get(url, headers=self.headers, params=params, timeout=120)
            if r.status_code not in (200, 206):
                r.raise_for_status()
            data = r.json()
            rows = data.get("data", [])
            if not rows:
                break
            out.extend(rows)
            cr = r.headers.get("Content-Range", "0-0/0")
            end = int(cr.split("/")[0].split("-")[1])
            total = int(cr.split("/")[1])
            if end + 1 >= total:
                break
            start = end + 1
        return out

def find_field_ids(ticket_opts: Dict[str, Any], uids: List[str], fallbacks: List[str]) -> Dict[str, int]:
    found = {}
    for sid, spec in ticket_opts.items():
        if not str(sid).isdigit(): continue
        uid = spec.get("uid") or ""
        name = (spec.get("name") or "").lower()
        if uid in uids:
            found[uid] = int(sid)
        for fb in fallbacks:
            if fb in name and fb not in found:
                found[fb] = int(sid)
    return found


# ... resto do arquivo igual ...

    def get_item(self, itemtype: str, item_id: int):
        r = self.session.get(f"{self.base}/{itemtype}/{item_id}", headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.json()

    def raw_search(self, itemtype: str, params: dict):
        """Search genérico quando precisamos montar params na unha (ex.: Group_Ticket)."""
        url = f"{self.base}/search/{itemtype}"
        r = self.session.get(url, headers=self.headers, params=params, timeout=120)
        if r.status_code not in (200, 206):
            r.raise_for_status()
        return r

