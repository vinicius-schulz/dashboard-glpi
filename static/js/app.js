let charts = {};
const UI_BASE = document.body.getAttribute('data-ui-base') || '';
const Loader = {
  el: null,
  init() { this.el = document.getElementById('loader'); },
  show(msg) { if (this.el) { this.el.querySelector('.msg').textContent = msg || 'Carregando...'; this.el.classList.remove('hidden'); } },
  hide() { if (this.el) this.el.classList.add('hidden'); }
};
const Toasts = {
  el: null,
  init() { this.el = document.getElementById('toasts'); },
  push(kind, text, timeout=4000) {
    if (!this.el) return;
    const d = document.createElement('div');
    d.className = `toast ${kind}`;
    d.textContent = text;
    this.el.appendChild(d);
    setTimeout(() => { d.remove(); }, timeout);
  }
};
window.addEventListener('DOMContentLoaded', () => { Loader.init(); Toasts.init(); });

// ---- Widget Layout Manager ----
const WidgetLayout = (() => {
  const STORAGE_KEY = 'glpiDashboardLayout.v2'; // bump version for new coordinate-based schema
  const DEFAULT = [
    { id: 'cumGap', cols: 3, rows: 3, visible: true },
    { id: 'backlog', cols: 3, rows: 3, visible: true },
    { id: 'backlogTrend', cols: 3, rows: 3, visible: true },
    { id: 'backlogStatus', cols: 3, rows: 3, visible: true },
    { id: 'sla', cols: 3, rows: 3, visible: true },
    { id: 'aging', cols: 3, rows: 3, visible: true },
  { id: 'openToday', cols: 3, rows: 3, visible: true },
  { id: 'createdToday', cols: 3, rows: 3, visible: true },
    { id: 'category', cols: 3, rows: 3, visible: true },
    { id: 'priority', cols: 3, rows: 3, visible: true },
    { id: 'impact', cols: 3, rows: 3, visible: true }
  ].map((w,i) => ({...w, order: i}));
  // Grid cell size (px) for snap positioning
  const CELL_W = 160; // base logical cell width (will derive snap unit)
  const CELL_H = 160; // base logical cell height
  const DEV_SHOW_GRID = true; // definir para false para ocultar marcações de desenvolvimento
  const AUTO_RESOLVE = false; // quando true empurra outros cards; false permite sobreposição
  const MAX_COLS = 24; // logical columns for coordinate space
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!raw) return DEFAULT.slice();
      // migrate v1 (no x,y) if needed
      if (raw.length && raw[0] && raw[0].x == null && raw[0].y == null) {
        return assignInitialCoords(raw);
      }
      return raw;
    } catch { return DEFAULT.slice(); }
  }
  function save(layout) { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); }
  function assignInitialCoords(layout) {
    // Sequential placement: honor predefined cols/rows if present else minimal 3x3
    let x=0, y=0, rowH=0; const COLS=MAX_COLS;
    layout.forEach(item => {
      const wCols = Math.min(COLS, item.cols || 3);
      const wRows = item.rows || 3;
      if (x + wCols > COLS) { x = 0; y += rowH; rowH = 0; }
      item.x = item.x != null ? item.x : x;
      item.y = item.y != null ? item.y : y;
      item.cols = wCols; item.rows = wRows;
      x += wCols; rowH = Math.max(rowH, wRows);
    });
    return layout;
  }
  function ensureAllHaveCoords(layout) {
    let changed=false;
    layout.forEach(w => { if (w.x==null||w.y==null) { changed=true; } });
    if (changed) assignInitialCoords(layout); // assigns 3x3 only for missing coords/sizes
    // Clamp & sanity
    layout.forEach(w => { w.cols = Math.max(3, w.cols||3); w.rows = Math.max(3, w.rows||3); });
  }
  function apply(layout) {
    const grid = document.querySelector('.grid');
    const map = new Map(layout.map(w => [w.id, w]));
    DEFAULT.forEach(def => { if (!map.has(def.id)) { layout.push({...def}); map.set(def.id, def); } });
    ensureAllHaveCoords(layout);
  grid.classList.add('free-layout');
  if (DEV_SHOW_GRID) { grid.classList.add('dev-grid'); grid.style.setProperty('--cell-w', (CELL_W/2)+'px'); grid.style.setProperty('--cell-h', (CELL_H/2)+'px'); } else { grid.classList.remove('dev-grid'); }
    const SNAP_W = CELL_W/2; // snap unit
    const SNAP_H = CELL_H/2;
    document.querySelectorAll('.card[data-widget]').forEach(el => {
      const id = el.getAttribute('data-widget');
      const w = map.get(id);
      if (!w || w.visible===false) { el.style.display='none'; return; } else el.style.display='';
      el.style.position='absolute';
      el.style.width = (w.cols * SNAP_W) + 'px';
      el.style.height = (w.rows * SNAP_H) + 'px';
      el.style.left = (w.x * SNAP_W) + 'px';
      el.style.top = (w.y * SNAP_H) + 'px';
    });
    const maxBottom = layout.filter(w=>w.visible!==false).reduce((m,w)=> Math.max(m, (w.y + w.rows) * SNAP_H), 0);
    grid.style.height = (maxBottom + 40) + 'px';
    attachWidgetActions(layout);
  }
  function attachWidgetActions(layout) {
    document.querySelectorAll('.card[data-widget]').forEach(card => {
      if (!card.querySelector('.widget-actions')) {
        const act = document.createElement('div');
        act.className = 'widget-actions';
        act.innerHTML = '<button data-act="hide" title="Ocultar">Ocultar</button>';
        card.appendChild(act);
        act.addEventListener('click', (e) => {
          const btn = e.target.closest('button'); if (!btn) return;
          const id = card.getAttribute('data-widget');
            const item = layout.find(x => x.id===id); if (!item) return;
            if (btn.dataset.act === 'hide') { item.visible=false; save(layout); apply(layout); Toasts.push('info', 'Widget ocultado: '+id); }
        });
      }
      // Ensure resize handle exists
      if (!card.querySelector('.resize-handle')) {
        const rh = document.createElement('div'); rh.className='resize-handle'; card.appendChild(rh);
        let sx, sy, sw, sh, startCols, startRows; const snapW = CELL_W/2, snapH = CELL_H/2; const id = card.getAttribute('data-widget');
        rh.addEventListener('mousedown', e => { e.preventDefault(); e.stopPropagation();
          const item = layout.find(x=>x.id===id); if(!item) return; sx=e.clientX; sy=e.clientY; sw=card.offsetWidth; sh=card.offsetHeight; startCols=item.cols; startRows=item.rows;
          function move(ev){
            const dx=ev.clientX-sx; const dy=ev.clientY-sy; const newW=sw+dx; const newH=sh+dy;
            const cols = Math.max(3, Math.round(newW / snapW));
            const rows = Math.max(3, Math.round(newH / snapH));
            if (cols!==item.cols || rows!==item.rows){ item.cols=cols; item.rows=rows; apply(layout); }
          }
          function up(){ save(layout); document.removeEventListener('mousemove',move); document.removeEventListener('mouseup',up); }
          document.addEventListener('mousemove',move); document.addEventListener('mouseup',up);
        });
      }
      if (!card.dataset.freeInit) { initDrag(card, layout); card.dataset.freeInit='1'; }
    });
  }
  function initDrag(card, layout) {
    let startX, startY, origX, origY, previewX, previewY; const id = card.getAttribute('data-widget');
    function onMouseDown(e){
      if(e.button!==0) return;
      const item = layout.find(w=>w.id===id); if(!item) return;
      startX=e.clientX; startY=e.clientY; origX=item.x||0; origY=item.y||0; previewX=origX; previewY=origY;
      card.classList.add('dragging'); document.body.classList.add('drag-mode');
      // bring to front
      card.style.zIndex = 999;
      document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp);
    }
    function onMove(e){
      const item = layout.find(w=>w.id===id); if(!item) return;
      const dx=e.clientX-startX; const dy=e.clientY-startY;
      const snapW = CELL_W/2; const snapH = CELL_H/2;
      const deltaCols=Math.round(dx/snapW); const deltaRows=Math.round(dy/snapH);
      let newX=Math.max(0, origX+deltaCols); let newY=Math.max(0, origY+deltaRows);
      if(newX!==previewX || newY!==previewY){
        previewX=newX; previewY=newY;
        card.style.left = (previewX * snapW) + 'px';
        card.style.top  = (previewY * snapH) + 'px';
      }
    }
    function onUp(){
      const item = layout.find(w=>w.id===id); if(item){ item.x=previewX; item.y=previewY; if (AUTO_RESOLVE) resolveCollisions(item, layout); apply(layout); save(layout); }
      card.classList.remove('dragging'); document.body.classList.remove('drag-mode'); card.style.zIndex='';
      document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp);
    }
    card.addEventListener('mousedown', onMouseDown);
  }
  function boxesOverlap(a,b){ return !(a.x+a.cols<=b.x || b.x+b.cols<=a.x || a.y+a.rows<=b.y || b.y+b.rows<=a.y); }
  function resolveCollisions(moved, layout){
    let changed=true; let guard=0; while(changed && guard<50){ changed=false; guard++; for(const other of layout){ if(other===moved || other.visible===false) continue; if(boxesOverlap(moved, other)){ // push other down
          other.y = moved.y + moved.rows; changed=true; }
      }
    }
  }
  function enableDrag(layout) { /* kept for backward compatibility - no-op now */ }
  function openPanel(layout) {
    const panel = document.getElementById('layoutPanel');
    const tbody = document.getElementById('lpRows');
    tbody.innerHTML = '';
    layout.forEach(w => {
      const row = document.createElement('tr');
      row.innerHTML = `<td>${w.id}</td><td><input type="checkbox" data-f="vis" ${w.visible!==false?'checked':''}></td>
        <td>
          L:<input data-f="cols" type="number" min="3" max="${MAX_COLS}" value="${w.cols|| (w.width||1)*3}" style="width:60px"> 
          H:<input data-f="rows" type="number" min="3" max="60" value="${w.rows|| (w.height||1)*3}" style="width:60px">
        </td>`;
      row.querySelectorAll('input,select').forEach(inp => {
        inp.addEventListener('change', () => {
          if (inp.dataset.f==='vis') w.visible = inp.checked;
          if (inp.dataset.f==='cols') w.cols = Math.min(MAX_COLS, Math.max(3, parseInt(inp.value)||3));
          if (inp.dataset.f==='rows') w.rows = Math.max(3, parseInt(inp.value)||3);
          save(layout); apply(layout);
        });
      });
      tbody.appendChild(row);
    });
    panel.classList.remove('hidden');
  }
  function init() {
    const layout = load();
    apply(layout);
    enableDrag(layout);
    // Panel buttons
    document.getElementById('customizeToggle').addEventListener('click', () => openPanel(layout));
    document.getElementById('lpClose').addEventListener('click', () => document.getElementById('layoutPanel').classList.add('hidden'));
    document.getElementById('lpDone').addEventListener('click', () => document.getElementById('layoutPanel').classList.add('hidden'));
    document.getElementById('lpReset').addEventListener('click', () => { localStorage.removeItem(STORAGE_KEY); const fresh = load(); apply(fresh); Toasts.push('success','Layout redefinido'); });
  }
  return { init };
})();
window.addEventListener('DOMContentLoaded', () => WidgetLayout.init());

// ---- Month range controls for "Mensal" granularity ----
function initMonthSelectors() {
  const startMonth = document.getElementById('startMonth');
  const endMonth = document.getElementById('endMonth');
  if (!startMonth || !endMonth) return;
  const now = new Date();
  const ym = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
  startMonth.value = ym;
  endMonth.value = ym;
  function ensureOrder() {
    if (startMonth.value > endMonth.value) endMonth.value = startMonth.value;
  }
  startMonth.addEventListener('change', ensureOrder);
  endMonth.addEventListener('change', ensureOrder);
}

function toggleDateInputs() {
  const gran = document.getElementById('gran').value;
  const dateSpan = document.getElementById('dateRangeInputs');
  const monthSpan = document.getElementById('monthRangeInputs');
  if (!dateSpan || !monthSpan) return;
  if (gran === 'Mensal') {
    dateSpan.classList.add('hidden');
    monthSpan.classList.remove('hidden');
  } else {
    monthSpan.classList.add('hidden');
    dateSpan.classList.remove('hidden');
  }
}
window.addEventListener('DOMContentLoaded', () => { initMonthSelectors(); toggleDateInputs(); });
document.addEventListener('change', (e) => { if (e.target && e.target.id === 'gran') toggleDateInputs(); });

function lineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return; // canvas not present
  // Ensure parent has a fixed height via CSS; Chart.js will fill canvas
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 200,
      interaction: { mode: 'nearest', intersect: false }
    }
  });
}

function barChart(canvasId, labels, data, label) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return; // canvas not present
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label, data }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 200,
      scales: { y: { beginAtZero: true } }
    }
  });
}

function setMeta(meta, count, period) {
  const el = document.getElementById('meta');
  const gids = meta?.groups || [];
  let info = `Período: ${period.start} a ${period.end} • Tickets: ${count} `;
  if (meta?.sid_ticket) info += `• SIDs Group_Ticket → Ticket.id=${meta.sid_ticket}, Group.id=${meta.sid_group} `;
  if (typeof meta?.tids_total === 'number') info += `• Vínculos totais=${meta.tids_total} • Observador=${meta.tids_obs}`;
  el.textContent = `Meus grupos: [${gids.join(', ')}] • ${info}`;
  // Aging disclaimer badge
  if (meta?.aging_note) {
    let badge = document.getElementById('aging-note');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'aging-note';
      badge.style.fontSize = '11px';
      badge.style.color = '#7f1d1d';
      badge.style.marginTop = '4px';
      el.appendChild(badge);
    }
    badge.textContent = meta.aging_note;
  }
}

let loading = false;
async function loadData() {
  if (loading) return; // prevent concurrent renders
  loading = true;
  Loader.show('Carregando dados...');
  document.body.style.cursor = 'progress';
  try {
    const gran = document.getElementById('gran').value;
    let startNorm, endNorm;
    if (gran === 'Mensal') {
  const sm = document.getElementById('startMonth').value; // YYYY-MM
  const em = document.getElementById('endMonth').value;   // YYYY-MM
  startNorm = sm + '-01';
  // Compute last day of end month: new Date(year, monthIndex+1, 0)
  const [ey, emon] = em.split('-').map(Number);
  const lastDay = new Date(ey, emon, 0); // because monthIndex is emon (1-based) -> next month day 0
  endNorm = lastDay.toISOString().slice(0,10);
    } else {
      const start = document.getElementById('start').value;
      const end = document.getElementById('end').value;
      startNorm = start;
      endNorm = end;
    }

    const r = await fetch(`/api/data?gran=${encodeURIComponent(gran)}&start=${startNorm}&end=${endNorm}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${txt.slice(0,200)}`);
    }
    const js = await r.json();
    if (js.error) throw new Error(js.error);

    setMeta(js.meta || {}, js.count || 0, js.period || {});

    // Big number snapshot (ignora filtro): campo open_today
    if (typeof js.open_today === 'number') {
      const el = document.getElementById('openTodayValue');
      if (el) el.textContent = js.open_today.toLocaleString('pt-BR');
    }
    if (typeof js.created_today === 'number') {
      const el2 = document.getElementById('createdTodayValue');
      if (el2) el2.textContent = js.created_today.toLocaleString('pt-BR');
    }

    const s = js.series || {};
    // Line charts
    if (s.created && s.resolved && document.getElementById('chartCumGap')) {
      const cumCreated = []; const cumResolved = []; const gap = [];
      let accC=0, accR=0;
      for (let i=0;i<s.created.data.length;i++) {
        const vC = Number(s.created.data[i]||0);
        const vR = Number(s.resolved.data[i]||0);
        accC += vC; accR += vR; cumCreated.push(accC); cumResolved.push(accR); gap.push(accC - accR);
      }
      if (charts['chartCumGap']) charts['chartCumGap'].destroy();
      charts['chartCumGap'] = new Chart(document.getElementById('chartCumGap'), {
        type: 'line',
        data: { labels: s.created.labels, datasets: [
          { label: 'Criados (Acum.)', data: cumCreated, borderColor: '#1d4ed8', backgroundColor: 'rgba(29,78,216,0.15)', tension:0.15 },
          { label: 'Resolvidos (Acum.)', data: cumResolved, borderColor: '#059669', backgroundColor: 'rgba(5,150,105,0.15)', tension:0.15 },
          { label: 'Gap Cumulativo (Criados - Resolvidos)', data: gap, borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,0.15)', tension:0.15 }
        ]},
        options: {
          responsive:true, maintainAspectRatio:false, animation:false, resizeDelay:200,
          interaction:{ mode:'nearest', intersect:false },
          scales:{ y:{ beginAtZero:true } },
          plugins:{ tooltip:{ callbacks:{ label: ctx => {
            const dsLabel = ctx.dataset.label || ''; return `${dsLabel}: ${ctx.parsed.y}`; } } } }
        }
      });
      attachPointClick('chartCumGap', s.created.labels, ['created','resolved']);
    }
    if (s.backlog) {
      lineChart('chartBacklog', s.backlog.labels, [
        { label: 'Backlog', data: s.backlog.data, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', tension: 0.2 }
      ]);
      attachPointClick('chartBacklog', s.backlog.labels, ['backlog']);
    }
    if (s.backlog_trend && s.backlog_trend.labels && s.backlog_trend.labels.length) {
      lineChart('chartBacklogTrend', s.backlog_trend.labels, [
        { label: 'Backlog (Suavizado)', data: s.backlog_trend.data, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.15)', tension:0.25 }
      ]);
    }

    // Bar charts
    if (s.backlog_status) { barChart('chartBacklogStatus', s.backlog_status.labels, s.backlog_status.data, 'Status'); attachBarClick('chartBacklogStatus', s.backlog_status.labels, 'backlog_status'); }
    if (s.aging) { barChart('chartAging', s.aging.labels, s.aging.data, 'Aging'); attachBarClick('chartAging', s.aging.labels, 'aging'); }
    if (s.category) { barChart('chartCat', s.category.labels, s.category.data, 'Categoria'); attachBarClick('chartCat', s.category.labels, 'category'); }
    if (s.priority) { barChart('chartPr', s.priority.labels, s.priority.data, 'Prioridade'); attachBarClick('chartPr', s.priority.labels, 'priority'); }
    if (s.impact) { barChart('chartImp', s.impact.labels, s.impact.data, 'Impacto'); attachBarClick('chartImp', s.impact.labels, 'impact'); }
  // refresh hidden state (in case layout toggled visibility before load)
  document.querySelectorAll('.card[data-widget]').forEach(el => { if (el.style.display==='none') return; /* skip hidden */ });
    if (s.load_by_user) { barChart('chartUser', s.load_by_user.labels, s.load_by_user.data, 'Usuário'); attachBarClick('chartUser', s.load_by_user.labels, 'load_by_user'); }
    if (s.load_by_group) { barChart('chartGroup', s.load_by_group.labels, s.load_by_group.data, 'Grupo'); attachBarClick('chartGroup', s.load_by_group.labels, 'load_by_group'); }

    // SLA block
    const sla = js.sla || {};
    document.getElementById('sla').textContent = JSON.stringify(sla, null, 2);
  } catch (e) {
    Toasts.push('error', String(e));
  } finally {
    Loader.hide();
    document.body.style.cursor = 'default';
    loading = false;
  }
}

document.getElementById('apply').addEventListener('click', () => loadData());
window.addEventListener('DOMContentLoaded', () => loadData());

// --- Modal helpers ---
const modal = {
  el: null, rows: null, title: null, info: null, closeBtn: null,
  init() {
    this.el = document.getElementById('modal');
    this.rows = document.getElementById('modal-rows');
    this.title = document.getElementById('modal-title');
    this.info = document.getElementById('modal-info');
    this.closeBtn = document.getElementById('modal-close');
    this.closeBtn.addEventListener('click', () => this.hide());
    this.el.addEventListener('click', (e) => { if (e.target === this.el) this.hide(); });
  },
  show() { this.el.classList.remove('hidden'); },
  hide() { this.el.classList.add('hidden'); }
};
modal.init();

function attachPointClick(canvasId, labels, sources) {
  const c = charts[canvasId];
  const canvas = document.getElementById(canvasId);
  canvas.onclick = async (evt) => {
    const points = c.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true);
    if (!points.length) return;
    const idx = points[0].index;
    const label = labels[idx];
    // prefer source based on dataset index if provided
    const dsIndex = points[0].datasetIndex || 0;
    const source = sources[Math.min(dsIndex, sources.length - 1)];
    await openTicketsModal(source, label);
  };
}

function attachBarClick(canvasId, labels, source) {
  const c = charts[canvasId];
  const canvas = document.getElementById(canvasId);
  canvas.onclick = async (evt) => {
    const bars = c.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true);
    if (!bars.length) return;
    const idx = bars[0].index;
    const label = labels[idx];
    await openTicketsModal(source, label);
  };
}

async function openTicketsModal(source, label) {
  const gran = document.getElementById('gran').value;
  const start = document.getElementById('start').value;
  const end = document.getElementById('end').value;
  // no max param anymore
  modal.title.textContent = `Chamados — ${source} · ${label}`;
  modal.info.textContent = 'Carregando...';
  modal.rows.innerHTML = '';
  modal.show();
  Loader.show('Carregando chamados...');
  document.body.style.cursor = 'progress';
  try {
  const r = await fetch(`/api/tickets?gran=${encodeURIComponent(gran)}&start=${start}&end=${end}&source=${encodeURIComponent(source)}&label=${encodeURIComponent(label)}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${txt.slice(0,200)}`);
    }
    const js = await r.json();
    if (js.error) throw new Error(js.error);
    modal.info.textContent = `Total no filtro: ${js.count} • Mostrando: ${js.returned}`;
    const rows = js.tickets || [];
    const tBody = rows.map(t => `
      <tr>
        <td><a href="${buildGlpiLink(t.id)}" target="_blank" rel="noopener noreferrer">${t.id}</a></td>
        <td>${escapeHtml(t.titulo)}</td>
        <td>${escapeHtml(t.status || '')}</td>
        <td>${escapeHtml(t.categoria || '')}</td>
        <td>${escapeHtml(t.abertura || '')}</td>
        <td>${escapeHtml(t.ultima_atualizacao || '')}</td>
        <td>${escapeHtml(t.requerente || '')}</td>
        <td>${escapeHtml(t.grupo_atribuido || '')}</td>
        <td>${escapeHtml(t.tecnico_atribuido || '')}</td>
      </tr>`).join('');
    modal.rows.innerHTML = tBody || '<tr><td colspan="9">Nenhum chamado</td></tr>';
    Toasts.push('success', `Lista carregada (${rows.length})`);
  } catch (e) {
    modal.info.textContent = String(e);
    Toasts.push('error', String(e));
  } finally {
    Loader.hide();
    document.body.style.cursor = 'default';
  }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildGlpiLink(id) {
  if (!UI_BASE) return `#${id}`;
  // Typical GLPI ticket URL pattern
  // e.g., https://glpi.example.com/front/ticket.form.php?id=123
  let base = UI_BASE;
  if (base.endsWith('/')) base = base.slice(0, -1);
  return `${base}/front/ticket.form.php?id=${encodeURIComponent(id)}`;
}
