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
from datetime import datetime
import time
import zoneinfo
import requests

import pandas as pd
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
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
from business_calendar import previous_business_day, business_days_between, consecutive_non_business_start


load_dotenv()
GLPI_URL = os.getenv("GLPI_URL", "").rstrip("/")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "") 

app = Flask(__name__, template_folder="templates", static_folder="static")

# Authentication: single admin user from env
DASHBOARD_ADMIN = os.getenv('DASHBOARD_ADMIN')
DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD')
# session secret
app.secret_key = os.getenv('FLASK_SECRET_KEY') or os.urandom(24)
# Feature flag: enable/disable authentication globally (default: enabled)
# When False, the app does not require login and serves the dashboard directly.
DASHBOARD_ENABLE_AUTHENTICATION = os.getenv('DASHBOARD_ENABLE_AUTHENTICATION', 'true')
ENABLE_AUTH = str(DASHBOARD_ENABLE_AUTHENTICATION).strip().lower() in ('1', 'true', 'yes', 'on')

# OIDC (Keycloak) configuration
OIDC_ISSUER_URL = os.getenv('OIDC_ISSUER_URL')
OIDC_CLIENT_ID = os.getenv('OIDC_CLIENT_ID')
OIDC_CLIENT_SECRET = os.getenv('OIDC_CLIENT_SECRET')
OIDC_REDIRECT_URI = os.getenv('OIDC_REDIRECT_URI')
OIDC_SCOPES = os.getenv('OIDC_SCOPES', 'openid profile email')
OIDC_VERIFY_TLS = str(os.getenv('OIDC_VERIFY_TLS', 'true')).strip().lower() in ('1','true','yes','on')
OIDC_CA_BUNDLE = os.getenv('OIDC_CA_BUNDLE')  # caminho para arquivo .pem com CA(s)
if OIDC_CA_BUNDLE:
    # remove aspas acidentais e espaços
    OIDC_CA_BUNDLE = OIDC_CA_BUNDLE.strip().strip('"').strip("'")

"""Ajuste global do Requests para OIDC (antes de criar o cliente)."""
if OIDC_CA_BUNDLE:
    # Força requests (incl. Authlib) a usar este CA bundle
    os.environ['REQUESTS_CA_BUNDLE'] = OIDC_CA_BUNDLE
    os.environ['SSL_CERT_FILE'] = OIDC_CA_BUNDLE
    os.environ['CURL_CA_BUNDLE'] = OIDC_CA_BUNDLE
elif not OIDC_VERIFY_TLS:
    # Desabilita verificação (apenas para DEV)
    os.environ['PYTHONHTTPSVERIFY'] = '0'

oauth = OAuth(app)
OIDC_CONFIGURED = bool(OIDC_ISSUER_URL and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI)
if ENABLE_AUTH and OIDC_CONFIGURED:
    issuer = OIDC_ISSUER_URL.rstrip('/')
    kc_base = f"{issuer}/protocol/openid-connect"
    server_metadata = {
        'issuer': issuer,
        'authorization_endpoint': f"{kc_base}/auth",
        'token_endpoint': f"{kc_base}/token",
        'userinfo_endpoint': f"{kc_base}/userinfo",
        'end_session_endpoint': f"{kc_base}/logout",
        'jwks_uri': f"{kc_base}/certs",
        'revocation_endpoint': f"{kc_base}/revoke",
        'introspection_endpoint': f"{kc_base}/token/introspect",
        'scopes_supported': ['openid','profile','email'],
        'response_types_supported': ['code','code id_token','id_token'],
        'grant_types_supported': ['authorization_code','refresh_token'],
    }
    oauth.register(
        name='keycloak',
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata=server_metadata,
        authorize_url=server_metadata['authorization_endpoint'],
        access_token_url=server_metadata['token_endpoint'],
        api_base_url=issuer,
        client_kwargs={'scope': OIDC_SCOPES},
    )
    # Ajusta explicitamente a verificação TLS na sessão do cliente
    try:
        client = oauth.create_client('keycloak')
        if client is not None:
            client.session.verify = (OIDC_CA_BUNDLE if OIDC_CA_BUNDLE else (True if OIDC_VERIFY_TLS else False))
    except Exception:
        pass

# Harden session cookies in production
if os.getenv('FLASK_ENV', 'production') == 'production':
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )


def is_glpi_operational(timeout: int = 5) -> Tuple[bool, str]:
    """Checa disponibilidade básica do GLPI com uma única chamada HTTP.

    Timeout é limitado a no máximo 30s. Retorna (True, 'ok') em sucesso.
    """
    if not GLPI_URL or not GLPI_USER_TOKEN:
        return False, "GLPI_URL ou GLPI_USER_TOKEN não configurados"
    use_timeout = min(max(int(timeout or 5), 1), 30)
    try:  # main processing block
        base = GLPI_URL.rstrip('/')
        if not base.endswith('/apirest.php'):
            base = base + '/apirest.php'
        url = f"{base}/initSession"
        r = requests.get(
            url,
            headers={
                'Authorization': f'user_token {GLPI_USER_TOKEN}',
                'Accept': 'application/json'
            },
            params={'get_full_session': 'false'},
            timeout=use_timeout,
            allow_redirects=False
        )
        if r.is_redirect or r.is_permanent_redirect:
            return False, 'Redirect detectado (verifique GLPI_URL)'
        if r.status_code >= 400:
            snippet = ''
            try:
                snippet = r.text[:150]
            except Exception:
                pass
            return False, f'HTTP {r.status_code} {snippet}'
        try:
            js = r.json()
        except Exception:
            return False, 'Resposta não JSON'
        if isinstance(js, dict) and (js.get('session_token') or js.get('session')):
            return True, 'ok'
        return False, 'Resposta inesperada'
    except requests.exceptions.Timeout:
        return False, 'Timeout'
    except Exception as e:
        return False, str(e)


def check_credentials(user: str, pwd: str) -> bool:
    if not DASHBOARD_ADMIN or not DASHBOARD_PASSWORD:
        return False
    return str(user) == str(DASHBOARD_ADMIN) and str(pwd) == str(DASHBOARD_PASSWORD)


def is_authenticated() -> bool:
    # OIDC session (preferred)
    if session.get('user'):
        if _validate_oidc_session():
            return True
        # If invalid, session was cleared by validator
        return False
    # legacy session
    if session.get('auth'):
        return True
    # HTTP Basic header
    auth = request.authorization
    if auth and check_credentials(auth.username, auth.password):
        return True
    return False


def _validate_oidc_session() -> bool:
    """Valida a sessão OIDC: expiração do access_token e status no IdP via userinfo.

    Se inválido ou revogado, limpa a sessão e retorna False.
    """
    try:
        if not (ENABLE_AUTH and OIDC_CONFIGURED):
            return True
        tok = session.get('token') or {}
        access_token = tok.get('access_token')
        if not access_token:
            session.clear()
            return False
        # Expiração local
        obtained_at = session.get('token_obtained_at')
        expires_in = tok.get('expires_in')
        try:
            if obtained_at is not None and expires_in is not None:
                exp_ts = int(obtained_at) + int(expires_in)
                if time.time() >= (exp_ts - 15):  # 15s de margem
                    session.clear()
                    return False
        except Exception:
            pass
        issuer = (OIDC_ISSUER_URL or '').rstrip('/')
        userinfo_url = f"{issuer}/protocol/openid-connect/userinfo"
        introspect_url = f"{issuer}/protocol/openid-connect/token/introspect"
        verify_opt = (OIDC_CA_BUNDLE if OIDC_CA_BUNDLE else (True if OIDC_VERIFY_TLS else False))
        try:
            # 1) Tenta introspecção (mais explícito para detectar revogação)
            try:
                ir = requests.post(introspect_url, data={'client_id': OIDC_CLIENT_ID, 'client_secret': OIDC_CLIENT_SECRET, 'token': access_token}, timeout=5, verify=verify_opt)
                if ir.status_code == 200:
                    irj = ir.json()
                    if isinstance(irj, dict) and not irj.get('active', False):
                        session.clear();
                        return False
            except Exception:
                pass
            # 2) Fallback: userinfo (401/403 indica token inválido/revogado)
            r = requests.get(userinfo_url, headers={'Authorization': f'Bearer {access_token}'}, timeout=5, verify=verify_opt)
            if r.status_code == 200:
                # opcional: atualizar user info
                try:
                    ui = r.json()
                    if isinstance(ui, dict):
                        session['user'] = {
                            'sub': ui.get('sub'),
                            'name': ui.get('name') or ui.get('preferred_username'),
                            'email': ui.get('email'),
                        }
                except Exception:
                    pass
                return True
            # 401/403 ou outros => inválido
            session.clear()
            return False
        except Exception:
            # Em erro de rede, por segurança, considerar inválido para forçar re-login
            session.clear()
            return False
    except Exception:
        session.clear()
        return False


@app.before_request
def require_login():
    if not ENABLE_AUTH:
        return None
    path = request.path or ''
    if path.startswith('/static/') or path == '/favicon.ico' or path.startswith('/login') or path.startswith('/auth/callback') or path.startswith('/logout') or path in ('/health','/ready'):
        return None
    if is_authenticated():
        return None
    if path.startswith('/api/'):
        # For APIs, do not trigger browser auth if OIDC is configured
        if OIDC_CONFIGURED:
            return jsonify({'error': 'Unauthorized'}), 401
        return jsonify({'error': 'Unauthorized'}), 401, {'WWW-Authenticate': 'Basic realm="Dashboard"'}
    return redirect(url_for('login'))


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


def _window_filter(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Filtra um DataFrame já carregado para a janela [start, end] usando
    a mesma lógica de inclusão aplicada em `bulk_search_observer_tickets`:
    - Tickets criados dentro da janela
    - Tickets resolvidos dentro da janela
    - Tickets abertos antes do início mas ainda em aberto ou resolvidos dentro/ após o início

    O parâmetro `end` é inclusivo (dia final). Retorna novo DataFrame filtrado.
    """
    if df is None or df.empty:
        return df
    c = pd.to_datetime(df['created_at'], errors='coerce')
    s = pd.to_datetime(df['solved_at'], errors='coerce')
    # end_boundary exclusivo (mesma convenção usada em bulk_search)
    end_boundary = pd.to_datetime(end) + pd.Timedelta(days=1)
    mask = (
        (c >= start) & (c < end_boundary) |
        (s.notna() & (s >= start) & (s < end_boundary)) |
        ((c < start) & ((s.isna()) | (s >= start)))
    )
    return df[mask].copy()

# --- Helpers for names/mappings ---
STATUS_MAP = {1: "Novo", 2: "Atribuído", 3: "Planejado", 4: "Pendente", 5: "Resolvido", 6: "Fechado"}
LEVEL_MAP = {1: "Muito baixo", 2: "Baixo", 3: "Médio", 4: "Alto", 5: "Muito alto"}
IGNORE_PERIOD_WIDGETS = ["aging","backlog_status","open_today","created_today","resolved_today","updated_today","awaiting_approval"]

# ---------------------- Helpers de modularização api_data ----------------------

def _current_timezone():
    """Retorna timezone configurada (ou None)."""
    try:
        return zoneinfo.ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
    except Exception:
        return None


def _now_and_today():
    tz = _current_timezone()
    now_dt = datetime.now(tz) if tz else datetime.now()
    return now_dt, pd.Timestamp(now_dt.date())


def _parse_user_window(req, today_norm: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, str, str]:
    start_s = req.args.get("start")
    end_s = req.args.get("end")
    if not start_s or not end_s:
        start_s = (today_norm - pd.Timedelta(days=30)).date().isoformat()
        end_s = today_norm.date().isoformat()
    user_start = pd.Timestamp(start_s).normalize()
    user_end = pd.Timestamp(end_s).normalize()
    return user_start, user_end, start_s, end_s


def _apply_category_filter(df: pd.DataFrame, cat_filter: str) -> pd.DataFrame:
    if df is None or df.empty or cat_filter == "todos":
        return df
    name_cols = [c for c in ["category_fullname", "category_name", "category_label"] if c in df.columns]
    if name_cols:
        s = df[name_cols[0]].astype(str).fillna("")
    else:
        if 'category' in df.columns and df['category'].dtype == object:
            s = df['category'].astype(str).fillna("")
        else:
            return df
    mask_h = s.str.startswith("Holding", na=False)
    if cat_filter == "holding":
        return df[mask_h].copy()
    if cat_filter == "unimed":
        return df[~mask_h].copy()
    return df


def _apply_assigned_group_filter(df: pd.DataFrame, assigned_group_param: str) -> pd.DataFrame:
    """Suporta agora múltiplos grupos separados por vírgula.
    Regras especiais (holding/unimed/aguardando aprovação) aplicam-se somente se parâmetro único.
    Quando múltiplo: concatena resultados (OR lógico) mantendo unicidade.
    """
    if df is None or df.empty or assigned_group_param in (None, '', 'todos'):
        return df
    raw = str(assigned_group_param).strip()
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',') if p.strip()]
        if not parts:
            return df
        frames = []
        for p in parts:
            try:
                sub = _apply_assigned_group_filter(df, p)  # reuse single logic recursively
                if sub is not None and not sub.empty:
                    frames.append(sub)
            except Exception:
                continue
        if not frames:
            return df
        return pd.concat(frames).drop_duplicates(subset=['ticket_id']) if 'ticket_id' in df.columns else pd.concat(frames).drop_duplicates()
    param_lower = raw.lower()
    if param_lower in ('holding', 'unimed', 'aguardando aprovação'):
        def _gname(val):
            if isinstance(val, dict):
                return (val.get('completename') or val.get('name') or '').strip()
            return str(val).strip() if val is not None else ''
        if param_lower == 'holding':
            mask = df['assigned_group'].apply(lambda v: _gname(v) == 'Suporte Holding') if 'assigned_group' in df.columns else []
            return df[mask].copy()
        if param_lower == 'aguardando aprovação':
            mask = df['assigned_group'].apply(lambda v: _gname(v) == 'Aguardando Aprovação') if 'assigned_group' in df.columns else []
            return df[mask].copy()
        if param_lower == 'unimed':
            mask = df['assigned_group'].apply(lambda v: _gname(v) not in ('Suporte Holding','Aguardando Aprovação')) if 'assigned_group' in df.columns else []
            return df[mask].copy()
    try:
        aid = int(float(assigned_group_param))
        def match(row):
            val = row.get('assigned_group')
            if isinstance(val, dict):
                try:
                    return int(val.get('id')) == aid
                except Exception:
                    return False
            try:
                return int(float(val)) == aid
            except Exception:
                return False
        return df[df.apply(match, axis=1)].copy()
    except Exception:
        if 'assigned_group' in df.columns and df['assigned_group'].dtype == object:
            s = df['assigned_group'].astype(str).fillna('')
            return df[s == assigned_group_param].copy()
        return df


def _baseline_titles(src_titles_df: pd.DataFrame) -> tuple[list[str], list[dict]]:
    """Extrai títulos e categorias predominantes da baseline (para SLA)."""
    if src_titles_df is None or src_titles_df.empty or 'title' not in src_titles_df.columns:
        return [], []
    try:
        title_series = src_titles_df['title'].dropna().astype(str)
        if 'category' in src_titles_df.columns:
            cat_col = src_titles_df['category']
            cat_text = []
            for v in cat_col:
                if isinstance(v, dict):
                    name = v.get('completename') or v.get('name') or ''
                else:
                    name = str(v) if v is not None else ''
                cat_text.append(name)
            cats = pd.Series(cat_text, index=src_titles_df.index)
        else:
            cats = pd.Series([''] * len(src_titles_df), index=src_titles_df.index)
        tmp = pd.DataFrame({'title': title_series, 'category_text': cats})
        tmp['category_text'] = tmp['category_text'].fillna('').replace({'None': ''})
        agg = tmp.groupby('title')['category_text'].agg(lambda s: s.value_counts().index[0] if len(s.value_counts()) else '')
        baseline_titles = []
        baseline_titles_detail = []
        for t, cat in agg.items():
            title_clean = str(t).strip()
            if not title_clean:
                continue
            baseline_titles.append(title_clean)
            baseline_titles_detail.append({'title': title_clean, 'category': (cat or '').strip()})
        baseline_titles.sort(key=lambda x: x.lower())
        baseline_titles_detail.sort(key=lambda d: d['title'].lower())
        return baseline_titles, baseline_titles_detail
    except Exception:
        return [], []


def _assigned_groups_list(src_groups_df: pd.DataFrame) -> list[dict]:
    if src_groups_df is None or src_groups_df.empty or 'assigned_group' not in src_groups_df.columns:
        return []
    try:
        seen = set(); out = []
        for val in src_groups_df['assigned_group'].dropna().unique():
            gid = None; gname = None
            if isinstance(val, dict):
                gid = val.get('id')
                gname = val.get('completename') or val.get('name') or None
            else:
                s = str(val)
                if s.isdigit():
                    gid = int(s)
                else:
                    gname = s
            key = gid if gid is not None else gname
            if key is None or key in seen:
                continue
            seen.add(key)
            out.append({"id": gid if gid is not None else gname, "name": gname if gname is not None else (str(gid) if gid is not None else str(gname))})
        return out
    except Exception:
        return []


def _map_series_labels(s: pd.Series, mapper: dict) -> pd.Series:
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


def _category_stacked(cat_status_pivot: pd.DataFrame) -> dict:
    payload = {"labels": [], "datasets": []}
    if cat_status_pivot is None or cat_status_pivot.empty:
        return payload
    payload['labels'] = [str(i) for i in cat_status_pivot.index]
    status_order = [v for _, v in STATUS_MAP.items() if v in cat_status_pivot.columns]
    for extra in [c for c in cat_status_pivot.columns if c not in status_order]:
        status_order.append(extra)
    for st in status_order:
        vals = cat_status_pivot.get(st)
        if vals is None:
            continue
        payload['datasets'].append({'label': st, 'data': [int(v) for v in vals.values]})
    return payload


def _group_stacked(df_strict: pd.DataFrame) -> dict:
    payload = {"labels": [], "datasets": []}
    try:
        if df_strict is None or df_strict.empty or 'assigned_group' not in df_strict.columns or 'status' not in df_strict.columns:
            return payload
        tmp_grp = df_strict[['assigned_group', 'status']].copy()
        def _gdisplay(v):
            if isinstance(v, dict):
                return (v.get('completename') or v.get('name') or '').strip()
            return str(v).strip() if v is not None else ''
        tmp_grp['group_name'] = tmp_grp['assigned_group'].apply(_gdisplay).fillna('').replace({'None': ''})
        tmp_grp['status_name'] = tmp_grp['status'].apply(lambda x: STATUS_MAP.get(int(x), str(x)) if pd.notna(x) else 'Desconhecido')
        grp_status_pivot = tmp_grp.groupby(['group_name', 'status_name']).size().unstack(fill_value=0)
        if '' in grp_status_pivot.index and grp_status_pivot.shape[0] > 1:
            grp_status_pivot = grp_status_pivot.drop(index=[''])
        if grp_status_pivot.empty:
            return payload
        totals = grp_status_pivot.sum(axis=1).sort_values(ascending=False)
        grp_status_pivot = grp_status_pivot.loc[totals.index]
        payload['labels'] = [str(i) for i in grp_status_pivot.index]
        status_order_g = [v for _, v in STATUS_MAP.items() if v in grp_status_pivot.columns]
        for extra in [c for c in grp_status_pivot.columns if c not in status_order_g]:
            status_order_g.append(extra)
        for st in status_order_g:
            vals = grp_status_pivot.get(st)
            if vals is None:
                continue
            payload['datasets'].append({'label': st, 'data': [int(v) for v in vals.values]})
        return payload
    except Exception:
        return {"labels": [], "datasets": []}


def _updated_today_count(df_in: pd.DataFrame, today_norm: pd.Timestamp) -> int:
    if df_in is None or df_in.empty or 'updated_at' not in df_in.columns:
        return 0
    upd = pd.to_datetime(df_in['updated_at'], errors='coerce')
    if upd.isna().all():
        return 0
    prev_bd_loc = previous_business_day(today_norm)
    today_end_loc = today_norm + pd.Timedelta(days=1)
    mask_range = (upd >= prev_bd_loc) & (upd < today_end_loc)
    open_mask = pd.Series([True] * len(df_in), index=df_in.index)
    if 'solved_at' in df_in.columns:
        open_mask &= pd.to_datetime(df_in['solved_at'], errors='coerce').isna()
    if 'closed_at' in df_in.columns:
        open_mask &= pd.to_datetime(df_in['closed_at'], errors='coerce').isna()
    return int((mask_range & open_mask).sum())


def _empty_payload(meta, baseline_start, baseline_end, user_start, user_end, today_norm, baseline_df, baseline_df_raw):
    """Payload para caso de user_df vazio (mantendo métricas baseline)."""
    empty_series = {"labels": [], "data": []}
    bs_full = backlog_status(baseline_df) if baseline_df is not None and not baseline_df.empty else pd.Series(dtype=float)
    age_full = aging_buckets(baseline_df) if baseline_df is not None and not baseline_df.empty else pd.Series(dtype=float)
    sla = sla_solution(baseline_df) if baseline_df is not None and not baseline_df.empty else {}
    open_today_full = int(baseline_df[baseline_df['solved_at'].isna()].shape[0]) if baseline_df is not None and not baseline_df.empty else 0
    prev_bd = consecutive_non_business_start(today_norm)
    today_end = today_norm + pd.Timedelta(days=1)
    created_today_count = int(((pd.to_datetime(baseline_df['created_at']) >= prev_bd) & (pd.to_datetime(baseline_df['created_at']) < today_end)).sum()) if baseline_df is not None and not baseline_df.empty else 0
    solved_today_mask = (pd.to_datetime(baseline_df['solved_at'], errors='coerce') >= prev_bd) & (pd.to_datetime(baseline_df['solved_at'], errors='coerce') < today_end) if baseline_df is not None and not baseline_df.empty else pd.Series([], dtype=bool)
    resolved_today_count = int(solved_today_mask.sum()) if baseline_df is not None and not baseline_df.empty else 0
    updated_today_count = _updated_today_count(baseline_df, today_norm)
    baseline_titles, baseline_titles_detail = _baseline_titles(baseline_df_raw)
    def _count_awaiting(dfref):
        try:
            if dfref is None or dfref.empty or 'assigned_group' not in dfref.columns:
                return 0
            def _g(v):
                if isinstance(v, dict):
                    return (v.get('completename') or v.get('name') or '').strip()
                return str(v).strip() if v is not None else ''
            names = dfref['assigned_group'].apply(_g).astype(str)
            # match se o texto contiver "aguardando aprovação" em qualquer parte (case-insensitive)
            mask_group = names.str.casefold().str.contains('aguardando aprovação')
            mask_open = pd.to_datetime(dfref.get('solved_at'), errors='coerce').isna() if 'solved_at' in dfref.columns else pd.Series([True]*len(dfref), index=dfref.index)
            return int((mask_group & mask_open).sum())
        except Exception:
            return 0
    awaiting_appr = _count_awaiting(baseline_df)
    return {
        "meta": {**meta, "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                  "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                  "ignore_period_widgets": IGNORE_PERIOD_WIDGETS},
        "count": 0,
        "note": "Sem tickets no intervalo filtrado; exibindo métricas de baseline." if (baseline_df is not None and not baseline_df.empty) else "Nenhum ticket no filtro e baseline vazia.",
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
            "load_by_user": empty_series,
            "load_by_group": empty_series,
        },
        "sla": sla,
        "open_today": open_today_full,
        "created_today": created_today_count,
        "resolved_today": resolved_today_count,
        "updated_today": updated_today_count,
    "awaiting_approval": awaiting_appr,
        "baseline_titles": baseline_titles,
        "baseline_titles_detail": baseline_titles_detail,
        "tickets_sla": [],
    }

# -------------------- Fim helpers api_data --------------------

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
        enable_auth=ENABLE_AUTH,
    )


@app.get("/health")
def health():
    """Lightweight health endpoint intended for Kubernetes liveness/readiness probes.

    This endpoint is explicitly allowed without authentication in `require_login()`.
    """
    try:
        now = datetime.utcnow().isoformat() + "Z"
        payload = {
            "status": "ok",
            "time": now,
            "service": "dashboard-glpi",
            "version": os.getenv("APP_VERSION", "unknown"),
            "auth_enabled": ENABLE_AUTH,
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.get("/ready")
def ready():
    """Readiness probe para Kubernetes."""
    try:
        ok_glpi, _msg = is_glpi_operational(timeout=5)
        if not ok_glpi:
            return jsonify({"status": "degraded", "glpi": False}), 503
        if ENABLE_AUTH and OIDC_CONFIGURED and 'keycloak' not in oauth._clients:
            return jsonify({"status": "degraded", "auth": False}), 503
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Se OIDC configurado, redireciona para Keycloak; caso contrário, mantém login legado se credenciais estiverem setadas
    if not ENABLE_AUTH:
        return redirect(url_for('index'))
    if OIDC_CONFIGURED and 'keycloak' in oauth._clients:
        return oauth.keycloak.authorize_redirect(redirect_uri=OIDC_REDIRECT_URI)
    # fallback legado
    notice = None
    if not (DASHBOARD_ADMIN and DASHBOARD_PASSWORD):
        return jsonify({'error': 'OIDC não configurado e login legado indisponível'}), 503
    if request.method == 'GET':
        return render_template('login.html', notice=notice)
    user = request.form.get('user'); pwd = request.form.get('password')
    if not user or not pwd:
        return render_template('login.html', error='Informe usuário e senha.', notice=notice), 400
    if check_credentials(user, pwd):
        session['auth'] = True
        return redirect(url_for('index'))
    return render_template('login.html', error='Usuário ou senha inválidos. Verifique e tente novamente.', notice=notice), 401


@app.route('/auth/callback', methods=['GET'])
def auth_callback():
    if not ENABLE_AUTH:
        return redirect(url_for('index'))
    if not (OIDC_CONFIGURED and 'keycloak' in oauth._clients):
        return jsonify({'error': 'OIDC não configurado no servidor'}), 503
    try:
        # Troca o authorization code manualmente (requests) para evitar validação de id_token/jwks
        auth_code = request.args.get('code')
        if not auth_code:
            return jsonify({'error': 'Código de autorização ausente no callback'}), 400
        issuer = (OIDC_ISSUER_URL or '').rstrip('/')
        oidc_base = f"{issuer}/protocol/openid-connect"
        token_url = f"{oidc_base}/token"
        userinfo_url = f"{oidc_base}/userinfo"
        verify_opt = (OIDC_CA_BUNDLE if OIDC_CA_BUNDLE else (True if OIDC_VERIFY_TLS else False))
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': OIDC_REDIRECT_URI,
            'client_id': OIDC_CLIENT_ID,
            'client_secret': OIDC_CLIENT_SECRET,
        }
        tr = requests.post(token_url, data=data, timeout=15, verify=verify_opt)
        tr.raise_for_status()
        token = tr.json()
        access_token = token.get('access_token')
        if not access_token:
            return jsonify({'error': 'Access token não retornado pelo servidor OIDC'}), 400
        ur = requests.get(userinfo_url, headers={'Authorization': f'Bearer {access_token}'}, timeout=15, verify=verify_opt)
        ur.raise_for_status()
        userinfo = ur.json() if ur.headers.get('content-type','').lower().startswith('application/json') else {}
        # Salva sessão de usuário e tokens
        session['user'] = {
            'sub': userinfo.get('sub'),
            'name': userinfo.get('name') or userinfo.get('preferred_username'),
            'email': userinfo.get('email'),
        }
        session['token'] = token
        session['token_obtained_at'] = int(time.time())
        return redirect(url_for('index'))
    except Exception as e:
        return jsonify({'error': f'Falha no callback OIDC: {e}'}), 400


@app.get('/logout')
def logout():
    # Limpa sessão e tenta RP-initiated logout no Keycloak
    id_token = None
    refresh_token = None
    try:
        tok = session.get('token') or {}
        id_token = tok.get('id_token')
        refresh_token = tok.get('refresh_token') or tok.get('refreshToken')
    except Exception:
        id_token = None
        refresh_token = None
    # Preserve base URL for redirect before clearing session
    post_logout_redirect = request.url_root.rstrip('/')
    session.clear()
    if ENABLE_AUTH and OIDC_CONFIGURED:
        try:
            end_session = None
            if 'keycloak' in oauth._clients:
                end_session = oauth.keycloak.load_server_metadata().get('end_session_endpoint')
            if not end_session:
                issuer = (OIDC_ISSUER_URL or '').rstrip('/')
                end_session = f"{issuer}/protocol/openid-connect/logout"
        except Exception:
            issuer = (OIDC_ISSUER_URL or '').rstrip('/')
            end_session = f"{issuer}/protocol/openid-connect/logout"

        if end_session and id_token:
            from urllib.parse import urlencode
            params = {
                'post_logout_redirect_uri': post_logout_redirect,
                'id_token_hint': id_token,
                'client_id': OIDC_CLIENT_ID,
            }
            return redirect(f"{end_session}?{urlencode(params)}")
        elif end_session and refresh_token:
            # Faz POST para invalidar refresh_token (encerra sessão no IdP)
            verify_opt = (OIDC_CA_BUNDLE if OIDC_CA_BUNDLE else (True if OIDC_VERIFY_TLS else False))
            try:
                requests.post(
                    end_session,
                    data={'client_id': OIDC_CLIENT_ID, 'refresh_token': refresh_token},
                    timeout=10,
                    verify=verify_opt,
                )
            except Exception:
                pass
            return redirect(post_logout_redirect)
    return redirect(url_for('index'))


@app.get("/api/data")
def api_data():
    """Endpoint principal de dados (refatorado e com filtro de status)."""
    try:
        ok_glpi, _msg = is_glpi_operational(timeout=10)
        if not ok_glpi:
            return jsonify({"mensagem": "O GLPI está temporariamente indisponível. Tente novamente em alguns instantes."}), 503

        gran = request.args.get("gran", "Diário")
        mode = request.args.get("mode", "bulk").lower()
        cat_filter = request.args.get("cat", "todos").lower()
        assigned_group_param = request.args.get('assigned_group', 'todos')
        status_param = request.args.get('status', 'todos').lower()
        freq = "D" if gran.lower().startswith("di") else ("W" if gran.lower().startswith("se") else "M")

        _now, today_norm = _now_and_today()
        user_start, user_end, start_s, end_s = _parse_user_window(request, today_norm)
        baseline_start = (today_norm - pd.DateOffset(months=6)).normalize()
        baseline_end = today_norm
        baseline_df, baseline_meta = _fetch_data(baseline_start, baseline_end, mode=mode)
        baseline_df_raw = baseline_df.copy() if (baseline_df is not None and not baseline_df.empty) else baseline_df

        if (baseline_df is not None and not baseline_df.empty and user_start >= baseline_start and user_end <= baseline_end):
            user_df = _window_filter(baseline_df, user_start, user_end)
            user_meta = {**baseline_meta, 'tids': len(user_df) if user_df is not None else 0}
        else:
            user_df, user_meta = _fetch_data(user_start, user_end, mode=mode)
        meta = {**baseline_meta, 'tids_baseline': baseline_meta.get('tids'), 'tids_user': user_meta.get('tids')}

        # Categoria e grupo
        baseline_df_cat = _apply_category_filter(baseline_df, cat_filter)
        user_df_cat = _apply_category_filter(user_df, cat_filter)
        baseline_df_unfiltered_groups = baseline_df_cat.copy() if baseline_df_cat is not None else None
        baseline_df_grp = _apply_assigned_group_filter(baseline_df_cat, assigned_group_param)
        user_df_grp = _apply_assigned_group_filter(user_df_cat, assigned_group_param)

        def _apply_status_filter(df: pd.DataFrame, status_param: str) -> pd.DataFrame:
            if df is None or df.empty or not status_param or status_param in ('todos', 'all'):
                return df
            sp = status_param.strip().lower()
            # Agregados
            if sp in ('solucionado', 'resolvido', 'resolved', 'closed'):
                solved_mask = pd.Series([False] * len(df), index=df.index)
                if 'status' in df.columns:
                    try:
                        solved_mask |= df['status'].astype(str).isin(['5', '6'])
                    except Exception:
                        pass
                if 'solved_at' in df.columns:
                    solved_mask |= pd.to_datetime(df['solved_at'], errors='coerce').notna()
                return df[solved_mask].copy()
            if sp in ('nao_solucionado', 'não_solucionado', 'nao', 'nao-resolvido', 'nao_resolvido', 'open', 'aberto'):
                open_mask = pd.Series([True] * len(df), index=df.index)
                if 'status' in df.columns:
                    try:
                        open_mask &= ~df['status'].astype(str).isin(['5', '6'])
                    except Exception:
                        pass
                if 'solved_at' in df.columns:
                    open_mask &= pd.to_datetime(df['solved_at'], errors='coerce').isna()
                return df[open_mask].copy()
            # Específico (código ou nome)
            code = None
            try:
                code = int(float(status_param))
            except Exception:
                pass
            if code is not None and 'status' in df.columns:
                try:
                    return df[df['status'].astype(str) == str(code)].copy()
                except Exception:
                    return df
            inv = {v.lower(): k for k, v in STATUS_MAP.items()}
            code2 = inv.get(sp)
            if code2 is not None and 'status' in df.columns:
                try:
                    return df[df['status'].astype(str) == str(code2)].copy()
                except Exception:
                    return df
            return df

        baseline_df = _apply_status_filter(baseline_df_grp, status_param)
        user_df = _apply_status_filter(user_df_grp, status_param)

        if user_df is None or user_df.empty:
            return jsonify(_empty_payload(meta, baseline_start, baseline_end, user_start, user_end, today_norm, baseline_df, baseline_df_raw))

        created_all = pd.to_datetime(user_df['created_at'], errors='coerce')
        solved_all = pd.to_datetime(user_df['solved_at'], errors='coerce')
        end_boundary = user_end + pd.Timedelta(days=1)
        mask_strict = (created_all >= user_start) & (created_all < end_boundary)
        spans_window = ((created_all < user_start) & ((solved_all.isna()) | (solved_all >= user_start))) | ((solved_all.notna()) & (solved_all >= user_start) & (solved_all < end_boundary))
        df_extended = user_df[mask_strict | spans_window].copy()
        df_strict = user_df[mask_strict].copy()

        if df_strict.empty:
            created = pd.Series(dtype=float)
            resolved = pd.Series(dtype=float)
            _c_ext, _r_ext, backlog_ext = created_resolved(df_extended, freq=freq)
            backlog_trend = backlog_trend_series(backlog_ext)
            cat_filtered = pd.Series(dtype=float)
            imp_filtered = pd.Series(dtype=float)
            cat_status_pivot = pd.DataFrame()
        else:
            created, resolved, _discard = created_resolved(df_strict, freq=freq)
            _c_ext, _r_ext, backlog_ext = created_resolved(df_extended, freq=freq)
            backlog_trend = backlog_trend_series(backlog_ext)
            cat_filtered, _pr_unused, imp_filtered = composition(df_strict)
            try:
                tmp_cat = df_strict[['category', 'status']].copy()
                tmp_cat['status_name'] = tmp_cat['status'].apply(lambda x: STATUS_MAP.get(int(x), str(x)) if pd.notna(x) else 'Desconhecido')
                cat_status_pivot = tmp_cat.groupby(['category', 'status_name']).size().unstack(fill_value=0)
                if not cat_filtered.empty:
                    ordered_index = [c for c in cat_filtered.index if c in cat_status_pivot.index]
                    cat_status_pivot = cat_status_pivot.reindex(ordered_index)
            except Exception:
                cat_status_pivot = pd.DataFrame()

        solved_dt_ext = pd.to_datetime(df_extended['solved_at'], errors='coerce')
        res_mask = solved_dt_ext.notna() & (solved_dt_ext >= user_start) & (solved_dt_ext < end_boundary)
        df_resolved_window = df_extended[res_mask].copy()
        resolution_hours_series = resolution_time_series(df_resolved_window, freq=freq)
        resolution_hours_trend = backlog_trend_series(resolution_hours_series)

        # --- Recorte explícito das séries para o intervalo solicitado pelo usuário ---
        def _clip_daily_fill(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp, freq_code: str) -> pd.Series:
            if s is None or s.empty:
                if freq_code == 'D':
                    idx_full = pd.date_range(start.normalize(), end.normalize(), freq='D')
                    return pd.Series([0]*len(idx_full), index=idx_full)
                return s
            if isinstance(s.index, pd.DatetimeIndex):
                # Filtra limites (inclusive)
                s = s[(s.index.normalize() >= start.normalize()) & (s.index.normalize() <= end.normalize())]
                if freq_code == 'D':
                    idx_full = pd.date_range(start.normalize(), end.normalize(), freq='D')
                    s = s.reindex(idx_full, fill_value=0)
            return s

        created = _clip_daily_fill(created, user_start, user_end, freq)
        resolved = _clip_daily_fill(resolved, user_start, user_end, freq)
        backlog_ext = _clip_daily_fill(backlog_ext, user_start, user_end, freq)
        backlog_trend = _clip_daily_fill(backlog_trend, user_start, user_end, freq)
        resolution_hours_series = _clip_daily_fill(resolution_hours_series, user_start, user_end, freq)
        resolution_hours_trend = _clip_daily_fill(resolution_hours_trend, user_start, user_end, freq)

        bs_full = backlog_status(baseline_df)
        age_full = aging_buckets(baseline_df)
        sla = sla_solution(baseline_df)
        open_today_full = int(baseline_df[baseline_df['solved_at'].isna()].shape[0])
        prev_bd = consecutive_non_business_start(today_norm)
        today_end = today_norm + pd.Timedelta(days=1)
        created_today_mask = (pd.to_datetime(baseline_df['created_at']) >= prev_bd) & (pd.to_datetime(baseline_df['created_at']) < today_end)
        created_today_count = int(created_today_mask.sum())
        solved_today_mask = (pd.to_datetime(baseline_df['solved_at'], errors='coerce') >= prev_bd) & (pd.to_datetime(baseline_df['solved_at'], errors='coerce') < today_end)
        resolved_today_count = int(solved_today_mask.sum())
        updated_today_count = _updated_today_count(baseline_df, today_norm)
        # Novo: quantidade de tickets em aberto cujo grupo atribuído é "Aguardando Aprovação" (ignora filtro de período)
        def _count_awaiting(dfref):
            try:
                if dfref is None or dfref.empty or 'assigned_group' not in dfref.columns:
                    return 0
                def _g(v):
                    if isinstance(v, dict):
                        return (v.get('completename') or v.get('name') or '').strip()
                    return str(v).strip() if v is not None else ''
                names = dfref['assigned_group'].apply(_g).astype(str)
                mask_group = names.str.casefold().str.contains('aguardando aprovação')
                mask_open = pd.to_datetime(dfref.get('solved_at'), errors='coerce').isna() if 'solved_at' in dfref.columns else pd.Series([True]*len(dfref), index=dfref.index)
                return int((mask_group & mask_open).sum())
            except Exception:
                return 0
        awaiting_approval_count = _count_awaiting(baseline_df_unfiltered_groups)
        load = load_by_assignee(df_strict)

        assigned_groups = _assigned_groups_list(baseline_df_unfiltered_groups)
        bs_named = _map_series_labels(bs_full, STATUS_MAP)
        imp_named = _map_series_labels(imp_filtered, LEVEL_MAP)
        category_stacked_payload = _category_stacked(cat_status_pivot)
        load_by_group_stacked_payload = _group_stacked(df_strict)
        baseline_titles, baseline_titles_detail = _baseline_titles(baseline_df_raw)

        tickets_sla_df = (baseline_df[pd.to_datetime(baseline_df['solved_at'], errors='coerce').isna()]
                          if (baseline_df is not None and not baseline_df.empty and 'solved_at' in baseline_df.columns)
                          else (baseline_df if baseline_df is not None else pd.DataFrame()))
        tickets_sla = [
            {
                'id': int(r.ticket_id),
                'title': (str(getattr(r, 'title', '') or '')).strip(),
                'created_at': (pd.to_datetime(r.created_at, errors='coerce').isoformat() if pd.notna(pd.to_datetime(r.created_at, errors='coerce')) else None),
                'solved_at': (pd.to_datetime(r.solved_at, errors='coerce').isoformat() if pd.notna(pd.to_datetime(r.solved_at, errors='coerce')) else None)
            }
            for _, r in tickets_sla_df.head(5000).iterrows()
            if str(getattr(r, 'title', '') or '').strip()
        ]

        payload = {
            'meta': {**meta,
                     'baseline_window': {'start': str(baseline_start.date()), 'end': str(baseline_end.date()), 'used': True},
                     'user_window': {'start': str(user_start.date()), 'end': str(user_end.date())},
                     'ignore_period_widgets': IGNORE_PERIOD_WIDGETS,
                     'filters': {'categoria': cat_filter, 'grupo_atribuido': assigned_group_param, 'status': status_param}},
            'count': int(len(df_strict)),
            'period': {'start': start_s, 'end': end_s, 'gran': gran},
            'assigned_groups': assigned_groups,
            'series': {
                'created': _series_to_labels_data(created),
                'resolved': _series_to_labels_data(resolved),
                'backlog': _series_to_labels_data(backlog_ext),
                'backlog_trend': _series_to_labels_data(backlog_trend) if backlog_trend is not None else {'labels': [], 'data': []},
                'category': _dict_to_labels_data(cat_filtered),
                'category_stacked': category_stacked_payload,
                'resolution_hours': _series_to_labels_data(resolution_hours_series),
                'resolution_hours_trend': _series_to_labels_data(resolution_hours_trend) if resolution_hours_trend is not None else {'labels': [], 'data': []},
                'backlog_status': _dict_to_labels_data(bs_named),
                'aging': _dict_to_labels_data(age_full),
                'load_by_user': _series_to_labels_data(load.get('by_user')) if 'by_user' in load else {'labels': [], 'data': []},
                'load_by_group': _series_to_labels_data(load.get('by_group')) if 'by_group' in load else {'labels': [], 'data': []},
                'load_by_group_stacked': load_by_group_stacked_payload,
            },
            'sla': sla,
            'open_today': open_today_full,
            'created_today': created_today_count,
            'resolved_today': resolved_today_count,
            'updated_today': updated_today_count,
            'awaiting_approval': awaiting_approval_count,
            'baseline_titles': baseline_titles,
            'baseline_titles_detail': baseline_titles_detail,
            'tickets_sla': tickets_sla,
        }
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.get("/favicon.ico")
def favicon():
    # Avoid 404 noise; you can replace with a real icon in static if desired
    return ("", 204)


@app.get("/api/tickets")
def api_tickets():
    """Lista de tickets correspondente a um ponto / barra clicado."""
    ok_glpi, _ = is_glpi_operational(timeout=10)
    if not ok_glpi:
        return jsonify({"mensagem": "O GLPI está temporariamente indisponível. Tente novamente em alguns instantes."}), 503

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
    assigned_group_param = request.args.get('assigned_group', 'todos')
    status_param = request.args.get('status', 'todos').lower()
    ids_param = request.args.get("ids")

    try:
        _tz = zoneinfo.ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
    except Exception:
        _tz = None
    now_dt = datetime.now(_tz) if _tz else datetime.now()
    today_norm = pd.Timestamp(now_dt.date())

    if not start_s or not end_s:
        start_s = (today_norm - pd.Timedelta(days=30)).date().isoformat()
        end_s = today_norm.date().isoformat()

    df, meta = _fetch_data(pd.Timestamp(start_s), pd.Timestamp(end_s), mode=mode)
    if df is None or df.empty:
        return jsonify({"meta": meta, "count": 0, "tickets": []})

    # Categoria
    if cat_filter not in ("todos", ""):
        name_cols = [c for c in ["category_fullname", "category_name", "category_label"] if c in df.columns]
        if name_cols:
            s = df[name_cols[0]].astype(str).fillna("")
        else:
            s = df['category'].astype(str).fillna("") if 'category' in df.columns and df['category'].dtype == object else None
        if s is not None:
            mask_h = s.str.startswith("Holding", na=False)
            if cat_filter == "holding":
                df = df[mask_h].copy()
            elif cat_filter == "unimed":
                df = df[~mask_h].copy()
            meta['cat_filter'] = cat_filter

    # Grupo atribuído
    def filter_assigned_group(df_in: pd.DataFrame) -> pd.DataFrame:
        """Filtra por um ou múltiplos grupos atribuídos (separados por vírgula) sem recursão infinita."""
        if df_in is None or df_in.empty or assigned_group_param in (None, '', 'todos'):
            return df_in
        raw = str(assigned_group_param).strip()
        if ',' in raw:
            parts = [p.strip() for p in raw.split(',') if p.strip() and p.lower() != 'todos']
            if not parts:
                return df_in
            frames = [filter_assigned_group_single(df_in, p) for p in parts]
            frames = [f for f in frames if f is not None and not f.empty]
            if not frames:
                return df_in
            merged = pd.concat(frames, ignore_index=True)
            if 'ticket_id' in merged.columns:
                merged = merged.drop_duplicates(subset=['ticket_id'])
            else:
                merged = merged.drop_duplicates()
            return merged
        return filter_assigned_group_single(df_in, raw)

    def filter_assigned_group_single(df_in: pd.DataFrame, single_param: str) -> pd.DataFrame:
        if df_in is None or df_in.empty or single_param in (None, '', 'todos'):
            return df_in
        param_lower = str(single_param).strip().lower()
        if param_lower in ('holding', 'unimed', 'aguardando aprovação'):
            def _gname(val):
                if isinstance(val, dict):
                    return (val.get('completename') or val.get('name') or '').strip()
                return str(val).strip() if val is not None else ''
        if param_lower == 'holding':
            mask = df_in['assigned_group'].apply(lambda v: _gname(v) == 'Suporte Holding') if 'assigned_group' in df_in.columns else []
            return df_in[mask].copy()
        if param_lower == 'aguardando aprovação':
            mask = df_in['assigned_group'].apply(lambda v: _gname(v) == 'Aguardando Aprovação') if 'assigned_group' in df_in.columns else []
            return df_in[mask].copy()
        if param_lower == 'unimed':
            mask = df_in['assigned_group'].apply(lambda v: _gname(v) not in ('Suporte Holding','Aguardando Aprovação')) if 'assigned_group' in df_in.columns else []
            return df_in[mask].copy()
        try:
            aid = int(float(single_param))
            def match(row):
                val = row.get('assigned_group')
                if isinstance(val, dict):
                    try:
                        return int(val.get('id')) == aid
                    except Exception:
                        return False
                try:
                    return int(float(val)) == aid
                except Exception:
                    return False
            return df_in[df_in.apply(match, axis=1)].copy()
        except Exception:
            if 'assigned_group' in df_in.columns and df_in['assigned_group'].dtype == object:
                s = df_in['assigned_group'].astype(str).fillna('')
                return df_in[s == single_param].copy()
            return df_in

    df = filter_assigned_group(df)
    # Status filter (reuse logic similar to api_data)
    def _apply_status_filter(df_in: pd.DataFrame, status_param: str) -> pd.DataFrame:
        if df_in is None or df_in.empty or not status_param or status_param in ('todos','all'):
            return df_in
        sp = status_param.strip().lower()
        if sp in ('solucionado','resolvido','resolved','closed'):
            solved_mask = pd.Series([False]*len(df_in), index=df_in.index)
            if 'status' in df_in.columns:
                try: solved_mask |= df_in['status'].astype(str).isin(['5','6'])
                except Exception: pass
            if 'solved_at' in df_in.columns:
                solved_mask |= pd.to_datetime(df_in['solved_at'], errors='coerce').notna()
            return df_in[solved_mask].copy()
        if sp in ('nao_solucionado','não_solucionado','nao','nao-resolvido','nao_resolvido','open','aberto'):
            open_mask = pd.Series([True]*len(df_in), index=df_in.index)
            if 'status' in df_in.columns:
                try: open_mask &= ~df_in['status'].astype(str).isin(['5','6'])
                except Exception: pass
            if 'solved_at' in df_in.columns:
                open_mask &= pd.to_datetime(df_in['solved_at'], errors='coerce').isna()
            return df_in[open_mask].copy()
        code = None
        try: code = int(float(status_param))
        except Exception: pass
        if code is not None and 'status' in df_in.columns:
            try: return df_in[df_in['status'].astype(str)==str(code)].copy()
            except Exception: return df_in
        inv = {v.lower(): k for k,v in STATUS_MAP.items()}
        code2 = inv.get(sp)
        if code2 is not None and 'status' in df_in.columns:
            try: return df_in[df_in['status'].astype(str)==str(code2)].copy()
            except Exception: return df_in
        return df_in

    df = _apply_status_filter(df, status_param)
    if df is None or df.empty:
        return jsonify({"meta": meta, "count": 0, "tickets": []})

    # Subconjuntos (strict/extended)
    df_created = pd.to_datetime(df['created_at'], errors='coerce')
    df_solved = pd.to_datetime(df['solved_at'], errors='coerce')
    user_start = pd.Timestamp(user_start_s).normalize()
    user_end = pd.Timestamp(user_end_s).normalize()
    end_boundary = user_end + pd.Timedelta(days=1)
    mask_strict = (df_created >= user_start) & (df_created < end_boundary)
    df_strict = df[mask_strict].copy()
    spans_window = ((df_created < user_start) & ((df_solved.isna()) | (df_solved >= user_start))) | ((df_solved.notna()) & (df_solved >= user_start) & (df_solved < end_boundary))
    df_extended = df[mask_strict | spans_window].copy()

    # Seleção inicial vazia
    sel = pd.DataFrame(); used_ids = False
    if ids_param:
        try:
            wanted_ids = {int(x) for x in ids_param.split(',') if x.strip().isdigit()}
        except Exception:
            wanted_ids = set()
        if wanted_ids:
            sel = df[df['ticket_id'].isin(wanted_ids)].copy()
            used_ids = True

    if not used_ids:
        if source in ('created','resolved'):
            ps, pe = _period_bounds_from_label(label, gran)
            base = df_strict
            if source == 'created':
                dt = pd.to_datetime(base['created_at'], errors='coerce')
            else:
                dt = pd.to_datetime(base['solved_at'], errors='coerce')
            sel = base[(dt.notna() if source=='resolved' else pd.Series([True]*len(dt), index=dt.index)) & (dt >= ps) & (dt <= pe)]
        elif source == 'resolution_hours':
            ps, pe = _period_bounds_from_label(label, gran)
            base = df_strict
            dt = pd.to_datetime(base['solved_at'], errors='coerce')
            sel = base[(dt.notna()) & (dt >= ps) & (dt <= pe)]
        elif source == 'backlog':
            ps, pe = _period_bounds_from_label(label, gran)
            base = df_extended
            created_dt = pd.to_datetime(base['created_at'], errors='coerce')
            solved_dt = pd.to_datetime(base['solved_at'], errors='coerce')
            sel = base[(created_dt <= pe) & ((solved_dt.isna()) | (solved_dt > pe))]
        elif source == 'backlog_status':
            try:
                st = int(float(label))
            except Exception:
                inv = {v.lower(): k for k, v in STATUS_MAP.items()}
                st = inv.get(label.lower())
            base = df if baseline_flag else df_strict
            open_mask = base['solved_at'].isna()
            sel = base[open_mask & ((base['status'] == st) if st is not None else False)]
        elif source == 'aging':
            base = df if baseline_flag else df_strict
            created_dt = pd.to_datetime(base['created_at'], errors='coerce')
            today_local = today_norm
            def _bucket_match(cdt):
                try:
                    if pd.isna(cdt): return False
                    age_bd = business_days_between(pd.Timestamp(cdt).normalize(), today_local)
                except Exception:
                    return False
                if age_bd <= 2: b = '0–2d'
                elif age_bd <=7: b = '3–7d'
                elif age_bd <=14: b = '8–14d'
                elif age_bd <=30: b = '15–30d'
                elif age_bd <=60: b = '31–60d'
                else: b = '>60d'
                return b == label
            mask_open = base['solved_at'].isna()
            sel = base[mask_open & created_dt.apply(_bucket_match).astype(bool)].copy()
        elif source == 'open_today':
            sel = df[df['solved_at'].isna()]
        elif source == 'created_today':
            created_dt = pd.to_datetime(df['created_at'], errors='coerce')
            prev_bd = consecutive_non_business_start(today_norm)
            end_today = today_norm + pd.Timedelta(days=1)
            sel = df[(created_dt >= prev_bd) & (created_dt < end_today)]
        elif source == 'resolved_today':
            solved_dt = pd.to_datetime(df['solved_at'], errors='coerce')
            prev_bd = consecutive_non_business_start(today_norm)
            end_today = today_norm + pd.Timedelta(days=1)
            sel = df[(solved_dt.notna()) & (solved_dt >= prev_bd) & (solved_dt < end_today)]
        elif source == 'updated_today':
            if 'updated_at' in df.columns:
                upd_dt = pd.to_datetime(df['updated_at'], errors='coerce')
                prev_bd = previous_business_day(today_norm)
                end_today = today_norm + pd.Timedelta(days=1)
                # Apenas tickets ainda abertos (sem solved_at / closed_at) e atualizados no intervalo
                solved_dt_all = pd.to_datetime(df['solved_at'], errors='coerce') if 'solved_at' in df.columns else pd.Series([pd.NaT]*len(df), index=df.index)
                closed_dt_all = pd.to_datetime(df['closed_at'], errors='coerce') if 'closed_at' in df.columns else pd.Series([pd.NaT]*len(df), index=df.index)
                open_mask_modal = solved_dt_all.isna() & closed_dt_all.isna()
                sel = df[open_mask_modal & (upd_dt >= prev_bd) & (upd_dt < end_today)]
            else:
                sel = pd.DataFrame()
        elif source == 'awaiting_approval':
            def _g(v):
                if isinstance(v, dict):
                    return (v.get('completename') or v.get('name') or '').strip()
                return str(v).strip() if v is not None else ''
            solved_dt_all = pd.to_datetime(df['solved_at'], errors='coerce') if 'solved_at' in df.columns else pd.Series([pd.NaT]*len(df), index=df.index)
            mask_open = solved_dt_all.isna()
            sel = df[mask_open & df['assigned_group'].apply(_g).eq('Aguardando Aprovação')]
        elif source in ('category'):
            base = df_strict
            col = source
            sel = base[base[col].astype(str) == str(label)]
        elif source in ('load_by_user','load_by_group'):
            base = df_strict
            col = 'assigned_user' if source=='load_by_user' else 'assigned_group'
            try:
                aid = int(float(label))
                def match_id(row):
                    val = row.get(col)
                    if isinstance(val, dict):
                        try: return int(val.get('id'))==aid
                        except Exception: return False
                    try: return int(float(val))==aid
                    except Exception: return False
                sel = base[base.apply(match_id, axis=1)].copy()
            except Exception:
                if col in base.columns and base[col].dtype==object:
                    def match_name(row):
                        val=row.get(col)
                        if isinstance(val, dict):
                            nm = val.get('completename') or val.get('name') or ''
                            return nm==label
                        return str(val)==str(label)
                    sel = base[base.apply(match_name, axis=1)].copy()
                else:
                    try: sel = base[base[col].astype(str)==str(label)].copy()
                    except Exception: sel = pd.DataFrame()
        else:
            sel = df_strict

    # Construção otimizada sem chamadas per-ticket: todos os campos necessários já vêm do bulk_search
    rows = []
    for _, r in sel.head(1000).iterrows():
        try:
            tid = int(r.get('ticket_id'))
        except Exception:
            continue
        title = (r.get('title') or '').strip()
        created = r.get('created_at')
        updated = r.get('updated_at') or r.get('solved_at') or r.get('closed_at')
        status_val = r.get('status')
        status_name = ''
        try:
            if status_val is not None and str(status_val).isdigit():
                status_name = STATUS_MAP.get(int(status_val), str(status_val))
            elif status_val:
                status_name = str(status_val)
        except Exception:
            status_name = str(status_val) if status_val is not None else ''

        # Categoria: pode vir como dict expandido ou id/nome simples
        raw_cat_val = r.get('category')
        cat_name = ''
        if isinstance(raw_cat_val, dict):
            cat_name = (raw_cat_val.get('completename') or raw_cat_val.get('name') or '').strip()
        elif raw_cat_val is not None:
            s = str(raw_cat_val).strip()
            # Se contém letras, já é nome; se só dígitos fica em branco (evita segunda chamada)
            if any(ch.isalpha() for ch in s):
                cat_name = s

        # Grupo atribuído
        raw_assigned_group = r.get('assigned_group')
        assigned_group_name = ''
        if isinstance(raw_assigned_group, dict):
            assigned_group_name = (raw_assigned_group.get('completename') or raw_assigned_group.get('name') or '').strip()
        elif raw_assigned_group is not None:
            sgrp = str(raw_assigned_group).strip()
            if any(ch.isalpha() for ch in sgrp):
                assigned_group_name = sgrp

        rows.append({
            'id': tid,
            'titulo': title,
            'status': status_name,
            'categoria': cat_name,
            'abertura': created,
            'ultima_atualizacao': updated,
            'grupo_atribuido': assigned_group_name,
        })

    return jsonify({
        'meta': meta,
        'count': len(sel),
        'returned': len(rows),
        'tickets': rows,
        'source': source,
        'label': label,
        'baseline': baseline_flag,
        'user_window': {'start': user_start_s, 'end': user_end_s},
        'fetch_window': {'start': start_s, 'end': end_s},
    })
    # (Erros serão propagados e retornados pelo handler global se houver)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
