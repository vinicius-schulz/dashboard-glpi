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
import zoneinfo
import requests

import pandas as pd
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
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
    # session first
    if session.get('auth'):
        return True
    # HTTP Basic header
    auth = request.authorization
    if auth and check_credentials(auth.username, auth.password):
        return True
    return False


@app.before_request
def require_login():
    if not ENABLE_AUTH:
        return None
    path = request.path or ''
    if path.startswith('/static/') or path == '/favicon.ico' or path.startswith('/login') or path == '/health':
        return None
    if is_authenticated():
        return None
    if path.startswith('/api/'):
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
        name = g.get("completename") or g.get("name") or str(i)
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
        name = c.get("completename") or c.get("name") or str(i)
        cache[i] = name
        return name
    except Exception:
        cache[i] = str(i)
        return cache[i]

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


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Simple form-based login; also accept Basic Auth
    notice = None
    # Se autenticação estiver desativada, não faz sentido exibir tela de login
    if not ENABLE_AUTH:
        return redirect(url_for('index'))
    if not DASHBOARD_ADMIN or not DASHBOARD_PASSWORD:
        notice = 'Autenticação não configurada no servidor. Defina DASHBOARD_ADMIN e DASHBOARD_PASSWORD para habilitar o login.'
    if request.method == 'GET':
        return render_template('login.html', notice=notice)
    # POST
    user = request.form.get('user')
    pwd = request.form.get('password')
    if not DASHBOARD_ADMIN or not DASHBOARD_PASSWORD:
        # explicit feedback if server not configured
        return render_template('login.html', error='Autenticação não configurada. Contate o administrador.', notice=notice), 503
    if not user or not pwd:
        return render_template('login.html', error='Informe usuário e senha.', notice=notice), 400
    if check_credentials(user, pwd):
        session['auth'] = True
        return redirect(url_for('index'))
    # invalid credentials -> provide clear feedback
    return render_template('login.html', error='Usuário ou senha inválidos. Verifique e tente novamente.', notice=notice), 401


@app.get('/logout')
def logout():
    session.pop('auth', None)
    # Se auth desativada, voltar direto para index
    if not ENABLE_AUTH:
        return redirect(url_for('index'))
    return redirect(url_for('login'))


@app.get("/api/data")
def api_data():
    """Endpoint principal de dados.

    Requisitos novos:
    - Sempre coletar (por padrão) os ÚLTIMOS 6 MESES de tickets (janela baseline),
      independentemente do filtro informado na tela, para alimentar widgets que
      precisam de histórico amplo.
    - EXCETO: se o range solicitado pelo usuário estiver FORA da janela padrão
      (isto é, não contido totalmente dentro dos últimos 6 meses). Nesse caso, a
      coleta usa o range do usuário (não forçamos truncar para 6 meses).
    - Widgets que DEVEM respeitar o filtro informado na tela (usar df_filtrado):
        cumGap (created/resolved), backlog (e trend), category, resolutionHours.
        - Widgets que DEVEM ignorar o filtro e usar SEMPRE a janela baseline de 6 meses
            (ou o range estendido quando o usuário sai dessa janela): aging, backlogStatus,
            openToday, createdToday.
    - Sinalizar nos widgets que ignoram o período com a mensagem
      "Ignora filtro de período" (markup em index.html cuida da exibição; aqui
      expomos metadados para possível uso futuro).
    """
    try:
        # Disponibilidade GLPI
        ok_glpi, _msg = is_glpi_operational(timeout=10)
        if not ok_glpi:
            return jsonify({"mensagem": "O GLPI está temporariamente indisponível. Tente novamente em alguns instantes."}), 503

        gran = request.args.get("gran", "Diário")
        mode = request.args.get("mode", "bulk").lower()
        cat_filter = request.args.get("cat", "todos").lower()
        assigned_group_param = request.args.get('assigned_group', 'todos')
        gl = gran.lower()
        freq = "D" if gl.startswith("di") else ("W" if gl.startswith("se") else "M")

        # Timezone -> usar data naïve para comparações
        try:
            _tz = zoneinfo.ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
        except Exception:
            _tz = None
        now_dt = datetime.now(_tz) if _tz else datetime.now()
        today_norm = pd.Timestamp(now_dt.date())  # naive midnight

        # Intervalo do usuário
        start_s = request.args.get("start")
        end_s = request.args.get("end")
        if not start_s or not end_s:
            start_s = (today_norm - pd.Timedelta(days=30)).date().isoformat()
            end_s = today_norm.date().isoformat()
        user_start = pd.Timestamp(start_s).normalize()
        user_end = pd.Timestamp(end_s).normalize()

        # Baseline (últimos 6 meses)
        baseline_start = (today_norm - pd.DateOffset(months=6)).normalize()
        baseline_end = today_norm

        baseline_df, baseline_meta = _fetch_data(baseline_start, baseline_end, mode=mode)
        # Guardar baseline bruto antes de QUALQUER filtro (usado para lista de títulos SLA estável)
        baseline_df_raw = baseline_df.copy() if (baseline_df is not None and not baseline_df.empty) else baseline_df
        user_df, user_meta = _fetch_data(user_start, user_end, mode=mode)
        meta = {**baseline_meta, "tids_baseline": baseline_meta.get("tids"), "tids_user": user_meta.get("tids")}

        def filter_category(df: pd.DataFrame) -> pd.DataFrame:
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

        def filter_assigned_group(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty or assigned_group_param in (None, '', 'todos'):
                return df
            param_lower = str(assigned_group_param).strip().lower()
            # Valores sintéticos
            if param_lower in ('holding', 'unimed', 'aguardando aprovação'):
                # Função para extrair nome textual do grupo
                def _gname(val):
                    if isinstance(val, dict):
                        return (val.get('completename') or val.get('name') or '').strip()
                    return str(val).strip() if val is not None else ''
                if param_lower == 'holding':
                    # Manter apenas "Suporte Holding"
                    mask = df['assigned_group'].apply(lambda v: _gname(v) == 'Suporte Holding') if 'assigned_group' in df.columns else []
                    return df[mask].copy()
                if param_lower == 'aguardando aprovação':
                    mask = df['assigned_group'].apply(lambda v: _gname(v) == 'Aguardando Aprovação') if 'assigned_group' in df.columns else []
                    return df[mask].copy()
                if param_lower == 'unimed':
                    # Excluir "Suporte Holding" e "Aguardando Aprovação"
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

        # Primeiro aplicamos somente o filtro de categoria; guardamos baseline sem filtro de grupo
        baseline_df_cat = filter_category(baseline_df)  # baseline filtrado por categoria para métricas que ignoram período
        user_df_cat = filter_category(user_df)

        # Guardar baseline não filtrado por grupo para montar lista completa de grupos atribuídos
        baseline_df_unfiltered_groups = baseline_df_cat.copy() if baseline_df_cat is not None else None

        # Agora aplicamos filtro de grupo (quando selecionado) para as métricas
        baseline_df = filter_assigned_group(baseline_df_cat)
        user_df = filter_assigned_group(user_df_cat)

        if user_df is None or user_df.empty:
            empty_series = {"labels": [], "data": []}
            if baseline_df is None or baseline_df.empty:
                return jsonify({
                    "meta": {**meta, "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                              "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                              "ignore_period_widgets": ["aging","backlog_status","open_today","created_today","resolved_today","updated_today"]},
                    "count": 0,
                    "note": "Nenhum ticket no filtro e baseline vazia.",
                    "series": {k: empty_series for k in ["created","resolved","backlog","backlog_trend","category","resolution_hours","resolution_hours_trend","backlog_status","aging","load_by_user","load_by_group"]},
                    "sla": {},
                    "open_today": 0,
                    "created_today": 0,
                    "resolved_today": 0,
                    "updated_today": 0,
                    "baseline_titles": [],
                    "tickets_sla": [],
                })
            bs_full = backlog_status(baseline_df)
            age_full = aging_buckets(baseline_df)
            sla = sla_solution(baseline_df)
            open_today_full = int(baseline_df[baseline_df['solved_at'].isna()].shape[0])
            # Created today: include today plus any immediately preceding non-business days
            prev_bd = consecutive_non_business_start(today_norm)
            today_end = today_norm + pd.Timedelta(days=1)
            created_today_mask = (pd.to_datetime(baseline_df['created_at']) >= prev_bd) & (pd.to_datetime(baseline_df['created_at']) < today_end)
            created_today_count = int(created_today_mask.sum())
            # Resolved today: include today plus any immediately preceding non-business days
            today_end = today_norm + pd.Timedelta(days=1)
            solved_today_mask = (pd.to_datetime(baseline_df['solved_at'], errors='coerce') >= prev_bd) & (pd.to_datetime(baseline_df['solved_at'], errors='coerce') < today_end)
            resolved_today_count = int(solved_today_mask.sum())
            # Atualizados hoje (date_mod): incluir sempre HOJE + o dia útil anterior e quaisquer dias não úteis intermediários.
            def _updated_today_count(df_in: pd.DataFrame) -> int:
                """Conta tickets ATIVOS (não resolvidos/fechados) atualizados desde o último dia útil.

                Exclui tickets com solved_at preenchido (considerados concluídos). Fecha a janela em today_end e
                inicia em previous_business_day(today_norm), incluindo dias não úteis intermediários.
                """
                if df_in is None or df_in.empty or 'updated_at' not in df_in.columns:
                    return 0
                upd = pd.to_datetime(df_in['updated_at'], errors='coerce')
                if upd.isna().all():
                    return 0
                prev_bd_loc = previous_business_day(today_norm)
                today_end_loc = today_norm + pd.Timedelta(days=1)
                mask_range = (upd >= prev_bd_loc) & (upd < today_end_loc)
                # Apenas tickets ainda não resolvidos / não fechados
                open_mask = pd.Series([True] * len(df_in), index=df_in.index)
                if 'solved_at' in df_in.columns:
                    open_mask &= pd.to_datetime(df_in['solved_at'], errors='coerce').isna()
                if 'closed_at' in df_in.columns:
                    open_mask &= pd.to_datetime(df_in['closed_at'], errors='coerce').isna()
                return int((mask_range & open_mask).sum())
            updated_today_count = _updated_today_count(baseline_df)
            # títulos baseline
            try:
                baseline_titles = []
                baseline_titles_detail = []
                src_titles_df = baseline_df_raw  # usar baseline bruto para estabilidade
                if src_titles_df is not None and not src_titles_df.empty and 'title' in src_titles_df.columns:
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
                    for t, cat in agg.items():
                        title_clean = str(t).strip()
                        if not title_clean:
                            continue
                        baseline_titles.append(title_clean)
                        baseline_titles_detail.append({'title': title_clean, 'category': (cat or '').strip()})
                    baseline_titles.sort(key=lambda x: x.lower())
                    baseline_titles_detail.sort(key=lambda d: d['title'].lower())
            except Exception:
                baseline_titles = []
                baseline_titles_detail = []
            return jsonify({
                "meta": {**meta, "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                          "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                          "ignore_period_widgets": ["aging","backlog_status","open_today","created_today","resolved_today","updated_today"]},
                "count": 0,
                "note": "Sem tickets no intervalo filtrado; exibindo métricas de baseline.",
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
                "baseline_titles": baseline_titles,
                "baseline_titles_detail": baseline_titles_detail,
                "tickets_sla": [],
            })

        # Janela estendida
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
            pr_filtered = pd.Series(dtype=float)
            imp_filtered = pd.Series(dtype=float)
            cat_status_pivot = pd.DataFrame()
        else:
            created, resolved, _discard = created_resolved(df_strict, freq=freq)
            _c_ext, _r_ext, backlog_ext = created_resolved(df_extended, freq=freq)
            backlog_trend = backlog_trend_series(backlog_ext)
            cat_filtered, _pr_filtered_unused, imp_filtered = composition(df_strict)
            try:
                tmp_cat = df_strict[['category', 'status']].copy()
                tmp_cat['status_name'] = tmp_cat['status'].apply(lambda x: STATUS_MAP.get(int(x), str(x)) if pd.notna(x) else 'Desconhecido')
                cat_status_pivot = tmp_cat.groupby(['category', 'status_name']).size().unstack(fill_value=0)
                if not cat_filtered.empty:
                    ordered_index = [c for c in cat_filtered.index if c in cat_status_pivot.index]
                    cat_status_pivot = cat_status_pivot.reindex(ordered_index)
            except Exception:
                cat_status_pivot = pd.DataFrame()

        # Resolution hours
        solved_dt_ext = pd.to_datetime(df_extended['solved_at'], errors='coerce')
        res_mask = solved_dt_ext.notna() & (solved_dt_ext >= user_start) & (solved_dt_ext < end_boundary)
        df_resolved_window = df_extended[res_mask].copy()
        resolution_hours_series = resolution_time_series(df_resolved_window, freq=freq)
        resolution_hours_trend = backlog_trend_series(resolution_hours_series)

        # Baseline-only metrics
        bs_full = backlog_status(baseline_df)
        age_full = aging_buckets(baseline_df)
        sla = sla_solution(baseline_df)
        open_today_full = int(baseline_df[baseline_df['solved_at'].isna()].shape[0])
        # Created today (include today and immediately preceding non-business days)
        prev_bd = consecutive_non_business_start(today_norm)
        today_end = today_norm + pd.Timedelta(days=1)
        created_today_mask = (pd.to_datetime(baseline_df['created_at']) >= prev_bd) & (pd.to_datetime(baseline_df['created_at']) < today_end)
        created_today_count = int(created_today_mask.sum())
        # Resolved today: include today plus any immediately preceding non-business days (same rule as created_today)
        solved_today_mask = (pd.to_datetime(baseline_df['solved_at'], errors='coerce') >= prev_bd) & (pd.to_datetime(baseline_df['solved_at'], errors='coerce') < today_end)
        resolved_today_count = int(solved_today_mask.sum())
        def _updated_today_count(df_in: pd.DataFrame) -> int:
            """Conta apenas tickets ainda em aberto atualizados desde o último dia útil (exclui resolvidos/fechados)."""
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
        updated_today_count = _updated_today_count(baseline_df)
        load = load_by_assignee(df_strict)

        # Lista de grupos (sempre derivada do baseline SEM filtro de grupo para não "encolher" o dropdown)
        assigned_groups = []
        try:
            src_groups_df = baseline_df_unfiltered_groups
            if src_groups_df is not None and not src_groups_df.empty and 'assigned_group' in src_groups_df.columns:
                seen = set()
                gids_to_resolve = []
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
                    assigned_groups.append({"id": gid if gid is not None else gname, "name": gname if gname is not None else (str(gid) if gid is not None else str(gname))})
                    if gid is not None and (gname is None or gname == str(gid)):
                        gids_to_resolve.append(gid)
                if gids_to_resolve and GLPI_URL and GLPI_USER_TOKEN:
                    client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)
                    try:
                        client.init_session(get_full=False)
                        cache = {}
                        for i, ag in enumerate(assigned_groups):
                            try:
                                if isinstance(ag.get('id'), int):
                                    name = _resolve_group_name(client, ag['id'], cache)
                                    if name:
                                        assigned_groups[i]['name'] = name
                            except Exception:
                                continue
                    finally:
                        try:
                            client.kill_session()
                        except Exception:
                            pass
        except Exception:
            assigned_groups = []

        def map_series_labels(s: pd.Series, mapper: dict):
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

        bs_named = map_series_labels(bs_full, STATUS_MAP)
    # prioridade removida; ignorar pr_filtered
        imp_named = map_series_labels(imp_filtered, LEVEL_MAP)

        category_stacked_payload = {"labels": [], "datasets": []}
        if 'cat_status_pivot' not in locals():
            cat_status_pivot = pd.DataFrame()
        if cat_status_pivot is not None and not cat_status_pivot.empty:
            category_stacked_payload['labels'] = [str(i) for i in cat_status_pivot.index]
            status_order = [v for _, v in STATUS_MAP.items() if v in cat_status_pivot.columns]
            for extra in [c for c in cat_status_pivot.columns if c not in status_order]:
                status_order.append(extra)
            for st in status_order:
                vals = cat_status_pivot.get(st)
                if vals is None:
                    continue
                category_stacked_payload['datasets'].append({'label': st, 'data': [int(v) for v in vals.values]})

        # --- Group stacked (assigned group x status) similar to category_stacked ---
        load_by_group_stacked_payload = {"labels": [], "datasets": []}
        try:
            if not df_strict.empty and 'assigned_group' in df_strict.columns and 'status' in df_strict.columns:
                tmp_grp = df_strict[['assigned_group', 'status']].copy()
                def _gdisplay(v):
                    if isinstance(v, dict):
                        return (v.get('completename') or v.get('name') or '').strip()
                    return str(v).strip() if v is not None else ''
                tmp_grp['group_name'] = tmp_grp['assigned_group'].apply(_gdisplay).fillna('').replace({'None': ''})
                tmp_grp['status_name'] = tmp_grp['status'].apply(lambda x: STATUS_MAP.get(int(x), str(x)) if pd.notna(x) else 'Desconhecido')
                grp_status_pivot = tmp_grp.groupby(['group_name', 'status_name']).size().unstack(fill_value=0)
                # Remove linha vazia (sem nome) se existir
                if '' in grp_status_pivot.index and grp_status_pivot.shape[0] > 1:
                    grp_status_pivot = grp_status_pivot.drop(index=[''])
                if not grp_status_pivot.empty:
                    # Ordenar grupos por total desc
                    totals = grp_status_pivot.sum(axis=1).sort_values(ascending=False)
                    grp_status_pivot = grp_status_pivot.loc[totals.index]
                    load_by_group_stacked_payload['labels'] = [str(i) for i in grp_status_pivot.index]
                    status_order_g = [v for _, v in STATUS_MAP.items() if v in grp_status_pivot.columns]
                    for extra in [c for c in grp_status_pivot.columns if c not in status_order_g]:
                        status_order_g.append(extra)
                    for st in status_order_g:
                        vals = grp_status_pivot.get(st)
                        if vals is None:
                            continue
                        load_by_group_stacked_payload['datasets'].append({'label': st, 'data': [int(v) for v in vals.values]})
        except Exception:
            load_by_group_stacked_payload = {"labels": [], "datasets": []}

        # baseline titles (6 meses) para configuração SLA manual por título
        try:
            baseline_titles = []
            baseline_titles_detail = []
            src_titles_df = baseline_df_raw
            if src_titles_df is not None and not src_titles_df.empty and 'title' in src_titles_df.columns:
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
                for t, cat in agg.items():
                    title_clean = str(t).strip()
                    if not title_clean:
                        continue
                    baseline_titles.append(title_clean)
                    baseline_titles_detail.append({'title': title_clean, 'category': (cat or '').strip()})
                baseline_titles.sort(key=lambda x: x.lower())
                baseline_titles_detail.sort(key=lambda d: d['title'].lower())
        except Exception:
            baseline_titles = []
            baseline_titles_detail = []

        payload = {
            "meta": {**meta,
                      "baseline_window": {"start": str(baseline_start.date()), "end": str(baseline_end.date()), "used": True},
                      "user_window": {"start": str(user_start.date()), "end": str(user_end.date())},
                      "ignore_period_widgets": ["aging","backlog_status","open_today","created_today","resolved_today","updated_today"]},
            "count": int(len(df_strict)),
            "period": {"start": start_s, "end": end_s, "gran": gran},
            "assigned_groups": assigned_groups,
            "series": {
                "created": _series_to_labels_data(created),
                "resolved": _series_to_labels_data(resolved),
                "backlog": _series_to_labels_data(backlog_ext),
                "backlog_trend": _series_to_labels_data(backlog_trend) if backlog_trend is not None else {"labels": [], "data": []},
                "category": _dict_to_labels_data(cat_filtered),
                "category_stacked": category_stacked_payload,
                "resolution_hours": _series_to_labels_data(resolution_hours_series),
                "resolution_hours_trend": _series_to_labels_data(resolution_hours_trend) if resolution_hours_trend is not None else {"labels": [], "data": []},
                "backlog_status": _dict_to_labels_data(bs_named),
                "aging": _dict_to_labels_data(age_full),
                "load_by_user": _series_to_labels_data(load.get('by_user')) if 'by_user' in load else {"labels": [], "data": []},
                "load_by_group": _series_to_labels_data(load.get('by_group')) if 'by_group' in load else {"labels": [], "data": []},
                "load_by_group_stacked": load_by_group_stacked_payload,
            },
            "sla": sla,
            "open_today": open_today_full,
            "created_today": created_today_count,
            "resolved_today": resolved_today_count,
            "updated_today": updated_today_count,
            "baseline_titles": baseline_titles,
            "baseline_titles_detail": baseline_titles_detail,
            "tickets_sla": (lambda _df: [
                {
                    "id": int(r.ticket_id),
                    "title": (str(getattr(r, 'title', '') or '')).strip(),
                    "created_at": (pd.to_datetime(r.created_at, errors='coerce').isoformat() if pd.notna(pd.to_datetime(r.created_at, errors='coerce')) else None),
                    "solved_at": (pd.to_datetime(r.solved_at, errors='coerce').isoformat() if pd.notna(pd.to_datetime(r.solved_at, errors='coerce')) else None)
                }
                for _, r in _df.head(5000).iterrows()
                if str(getattr(r, 'title', '') or '').strip()
            ])( (
                (baseline_df[ pd.to_datetime(baseline_df['solved_at'], errors='coerce').isna() ])
                if (baseline_df is not None and not baseline_df.empty and 'solved_at' in baseline_df.columns)
                else (baseline_df if baseline_df is not None else pd.DataFrame())
            ) ),
        }
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
        if df_in is None or df_in.empty or assigned_group_param in (None, '', 'todos'):
            return df_in
        param_lower = str(assigned_group_param).strip().lower()
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
            return df_in[df_in.apply(match, axis=1)].copy()
        except Exception:
            if 'assigned_group' in df_in.columns and df_in['assigned_group'].dtype == object:
                s = df_in['assigned_group'].astype(str).fillna('')
                return df_in[s == assigned_group_param].copy()
            return df_in

    df = filter_assigned_group(df)
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

    gran_lower = gran.lower()
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

    client = GLPIClient(GLPI_URL, GLPI_USER_TOKEN)
    client.init_session(get_full=False)
    try:
        rows = []
        for _, r in sel.head(1000).iterrows():
            tid = int(r.get('ticket_id'))
            try:
                t = client.get_item('Ticket', tid)
            except Exception:
                t = {}
            title = t.get('name') or t.get('title') or ''
            created = t.get('date') or r.get('created_at')
            updated = t.get('date_mod') or t.get('date_modification') or None
            status_val = t.get('status') if t.get('status') is not None else r.get('status')
            status_name = STATUS_MAP.get(int(status_val)) if status_val is not None else ''
            raw_assigned_group = r.get('assigned_group')
            assigned_gid = t.get('groups_id_assign') or (raw_assigned_group.get('id') if isinstance(raw_assigned_group, dict) else raw_assigned_group)
            raw_cat_val = r.get('category')
            cat_name = ''
            if raw_cat_val is not None:
                try:
                    if isinstance(raw_cat_val, dict):
                        cand = raw_cat_val.get('completename') or raw_cat_val.get('name') or ''
                    else:
                        cand = str(raw_cat_val)
                    if any(ch.isalpha() for ch in cand):
                        cat_name = cand
                except Exception:
                    pass
            cat_id = t.get('itilcategories_id') or (raw_cat_val if (isinstance(raw_cat_val, int) or (isinstance(raw_cat_val, str) and raw_cat_val.isdigit())) else None)
            if not cat_name and cat_id:
                try:
                    cat_name = _resolve_category_name(client, cat_id, {})
                except Exception:
                    cat_name = ''
            if cat_name.isdigit():
                try:
                    resolved_name = _resolve_category_name(client, cat_name, {})
                    if resolved_name and not resolved_name.isdigit():
                        cat_name = resolved_name
                    else:
                        cat_name = ''
                except Exception:
                    cat_name = ''
            assigned_group_name = ''
            if raw_assigned_group is not None:
                if isinstance(raw_assigned_group, dict):
                    assigned_group_name = raw_assigned_group.get('completename') or raw_assigned_group.get('name') or ''
                else:
                    try:
                        sgrp = str(raw_assigned_group)
                        if any(ch.isalpha() for ch in sgrp):
                            assigned_group_name = sgrp
                    except Exception:
                        pass
            if not assigned_group_name and assigned_gid:
                try:
                    assigned_group_name = _resolve_group_name(client, assigned_gid, {})
                except Exception:
                    assigned_group_name = ''
            rows.append({
                'id': tid,
                'titulo': title,
                'status': status_name,
                'categoria': cat_name,
                'abertura': created,
                'ultima_atualizacao': updated,
                'grupo_atribuido': assigned_group_name,
            })
    finally:
        try:
            client.kill_session()
        except Exception:
            pass

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
    app.run(host="0.0.0.0", port=port, debug=True)
