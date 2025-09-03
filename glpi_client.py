"""
GLPI client wrapper: handles session, auth, and low-level REST calls.
"""
from typing import Optional, Dict, Any, List
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from instrumentation import timed


class GLPIClient:
    """Cliente para a API REST do GLPI.

    Responsável por:
    - Gerenciar a sessão (init/kill) usando user token.
    - Encapsular headers/parâmetros comuns.
    - Fornecer métodos auxiliares de busca e leitura de itens/subitens.
    """
    def __init__(self, base_url: str, user_token: str):
        """Inicializa o cliente GLPI.

        Parâmetros:
        - base_url: URL base do GLPI (com ou sem sufixo /apirest.php).
        - user_token: token de usuário do GLPI (Authorization: user_token ...).
        """
        if not base_url:
            raise RuntimeError("GLPI_URL não configurada")
        if not user_token:
            raise RuntimeError("GLPI_USER_TOKEN não configurado")

        # aceita GLPI_URL com ou sem /apirest.php
        if base_url.endswith("/apirest.php"):
            self.base = base_url
        else:
            self.base = base_url + "/apirest.php"

        self.session = requests.Session()
        self.session_token: Optional[str] = None
        self.headers_base = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"user_token {user_token}",
        }

        # dados da sessão
        self.session_blob: Optional[dict] = None
        self.me_user_id: Optional[int] = None
        self.my_group_ids: List[int] = []

    def _headers(self) -> dict:
        """Retorna headers padrão da requisição, incluindo Session-Token se existir."""
        h = dict(self.headers_base)
        if self.session_token:
            h["Session-Token"] = self.session_token
        return h

    def _params(self, extra: Optional[dict] = None) -> dict:
        """Mescla parâmetros extras com o session_token quando ativo."""
        p = dict(extra or {})
        if self.session_token and "session_token" not in p:
            p["session_token"] = self.session_token
        return p

    @timed
    def _get(self, path: str, params: Optional[dict] = None, timeout=60):
        """Executa GET simples na rota informada.

        Levanta RuntimeError com detalhes em caso de erro HTTP ou redirect inesperado.
        """
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            r = self.session.get(
                url, headers=self._headers(), params=self._params(params),
                timeout=timeout, allow_redirects=False
            )
            if r.is_redirect or r.is_permanent_redirect:
                raise RuntimeError(f"Redirect detectado em {url}. Ajuste GLPI_URL para a URL final do apirest.php.")
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            body = ""
            try:
                body = r.text[:2000]
            except Exception:
                pass
            raise RuntimeError(
                f"HTTPError {getattr(e.response,'status_code', '???')} em {url} | Resposta: {body}"
            ) from e

    @timed
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def init_session(self, get_full: bool = True):
        """Abre uma sessão no GLPI.

        - Se get_full=True, também chama getFullSession para descobrir grupos do usuário.
        - Preenche: session_token, session_blob, me_user_id, my_group_ids.
        """
        params = {"get_full_session": "true"} if get_full else {}
        r = self.session.get(
            f"{self.base}/initSession",
            headers=self._headers(),
            params=params,
            timeout=30,
            allow_redirects=False
        )
        if r.is_redirect or r.is_permanent_redirect:
            raise RuntimeError("Redirect durante initSession. Corrija GLPI_URL.")
        r.raise_for_status()
        js = r.json()
        self.session_token = js.get("session_token")
        if not self.session_token:
            raise RuntimeError(f"initSession OK mas sem session_token. Corpo: {r.text[:2000]}")

        # sessão completa
        sess = self._get("getFullSession", params={}).json()
        self.session_blob = sess

        # user_id
        uid = None
        # preferir session.glpiID
        try:
            uid = sess["session"].get("glpiID")
        except Exception:
            pass
        if uid is None:
            # fallbacks
            for key in ("user", "glpi_user", "session"):
                if isinstance(sess.get(key), dict):
                    for cand in ("id", "ID", "userid", "userID", "glpiID"):
                        if cand in sess[key]:
                            uid = sess[key][cand]
                            break
        try:
            self.me_user_id = int(uid) if uid is not None else None
        except Exception:
            self.me_user_id = None
        if not self.me_user_id:
            raise RuntimeError(
                f"Não foi possível identificar seu user_id via getFullSession. Resposta: {str(sess)[:500]}"
            )

        # meus grupos direto da sessão
        gids = []
        try:
            gids = sess["session"].get("glpigroups", []) or []
        except Exception:
            pass
        self.my_group_ids = []
        for g in gids:
            try:
                self.my_group_ids.append(int(g))
            except Exception:
                pass

    @timed
    def kill_session(self):
        """Encerra a sessão atual no GLPI (se existir)."""
        if not self.session_token:
            return
        try:
            self._get("killSession", params={}, timeout=15)
        finally:
            self.session_token = None

    @timed
    def raw_search(self, itemtype: str, params: dict):
        """Faz uma chamada crua à rota search/<itemtype> (retorna Response)."""
        return self._get(f"search/{itemtype}", params=params, timeout=120)

    @timed
    def get_item(self, itemtype: str, item_id: int):
        """Obtém um item por ID (ex.: Ticket/123)."""
        return self._get(f"{itemtype}/{item_id}", params={}, timeout=60).json()

    @timed
    def get_subitems(self, itemtype: str, item_id: int, subitemtype: str, params: Optional[dict] = None):
        """Obtém subitens de um item (ex.: Ticket/123/Group_Ticket)."""
        return self._get(f"{itemtype}/{item_id}/{subitemtype}", params=params or {}, timeout=120).json()
