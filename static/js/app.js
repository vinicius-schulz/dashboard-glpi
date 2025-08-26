let charts = {};
const UI_BASE = document.body.getAttribute('data-ui-base') || '';
// ---- Persistência de filtros (granularidade, categoria, datas, meses, range preset) ----
const FILTERS_KEY = 'glpiDashboardFilters.v1';
let _originalDefaults = null; // guarda valores iniciais vindos do backend (primeiro load)
function captureOriginalDefaultsOnce() {
  if (_originalDefaults) return;
  _originalDefaults = {
    gran: document.getElementById('gran')?.value || '',
    cat: document.getElementById('catFilter')?.value || '',
    start: document.getElementById('start')?.value || '',
    end: document.getElementById('end')?.value || '',
    startMonth: document.getElementById('startMonth')?.value || '',
    endMonth: document.getElementById('endMonth')?.value || ''
  };
}
function getActiveRangeDescriptor() {
  const btn = document.querySelector('.range-btn.active');
  if (!btn) return { mode: 'none' };
  if (btn.classList.contains('custom')) return { mode: 'custom' };
  const { range, days, months } = btn.dataset;
  if (range) return { mode: 'range', range };
  if (days) return { mode: 'days', days: Number(days) };
  if (months) return { mode: 'months', months: Number(months) };
  return { mode: 'unknown' };
}
function saveFilters() {
  try {
    const data = {
      gran: document.getElementById('gran')?.value,
      cat: document.getElementById('catFilter')?.value,
      start: document.getElementById('start')?.value,
      end: document.getElementById('end')?.value,
      startMonth: document.getElementById('startMonth')?.value,
      endMonth: document.getElementById('endMonth')?.value,
      range: getActiveRangeDescriptor()
    };
    localStorage.setItem(FILTERS_KEY, JSON.stringify(data));
  } catch {}
}
function applyRangeDescriptor(desc) {
  if (!desc) return false;
  const btns = Array.from(document.querySelectorAll('.range-btn'));
  btns.forEach(b => b.classList.remove('active'));
  let matched = false;
  btns.forEach(b => {
    if (matched) return;
    if (desc.mode === 'custom' && b.classList.contains('custom')) { b.classList.add('active'); matched = true; return; }
    if (desc.mode === 'range' && b.dataset.range === desc.range) { b.classList.add('active'); matched = true; return; }
    if (desc.mode === 'days' && b.dataset.days && Number(b.dataset.days) === desc.days) { b.classList.add('active'); matched = true; return; }
    if (desc.mode === 'months' && b.dataset.months && Number(b.dataset.months) === desc.months) { b.classList.add('active'); matched = true; return; }
  });
  return matched;
}
function loadFilters() {
  captureOriginalDefaultsOnce();
  let parsed = null;
  try { parsed = JSON.parse(localStorage.getItem(FILTERS_KEY) || 'null'); } catch { parsed = null; }
  if (!parsed) return false;
  try {
    if (parsed.gran && document.getElementById('gran')) document.getElementById('gran').value = parsed.gran;
    if (parsed.cat && document.getElementById('catFilter')) document.getElementById('catFilter').value = parsed.cat;
    if (parsed.start && document.getElementById('start')) document.getElementById('start').value = parsed.start;
    if (parsed.end && document.getElementById('end')) document.getElementById('end').value = parsed.end;
    if (parsed.startMonth && document.getElementById('startMonth')) document.getElementById('startMonth').value = parsed.startMonth;
    if (parsed.endMonth && document.getElementById('endMonth')) document.getElementById('endMonth').value = parsed.endMonth;
    applyRangeDescriptor(parsed.range);
    window._filtersRestored = true;
    toggleDateInputs();
  } catch {}
  return true;
}
function resetFilters() {
  try { localStorage.removeItem(FILTERS_KEY); } catch {}
  if (_originalDefaults) {
    if (document.getElementById('gran')) document.getElementById('gran').value = _originalDefaults.gran || 'Diário';
    if (document.getElementById('catFilter')) document.getElementById('catFilter').value = _originalDefaults.cat || 'todos';
    if (document.getElementById('start')) document.getElementById('start').value = _originalDefaults.start || '';
    if (document.getElementById('end')) document.getElementById('end').value = _originalDefaults.end || '';
    if (document.getElementById('startMonth')) document.getElementById('startMonth').value = _originalDefaults.startMonth || '';
    if (document.getElementById('endMonth')) document.getElementById('endMonth').value = _originalDefaults.endMonth || '';
  }
  // range visual volta para 3 meses
  const btns = Array.from(document.querySelectorAll('.range-btn'));
  btns.forEach(b => b.classList.remove('active'));
  const three = document.querySelector('.range-btn[data-months="3"]');
  if (three) three.classList.add('active');
  if (three) {
    const months = Number(three.dataset.months);
    if (!isNaN(months)) setRangeMonths(months);
  }
  toggleDateInputs();
  saveFilters();
  loadData();
}
// Carrega filtros cedo para evitar corrida com primeiro load
window.addEventListener('DOMContentLoaded', () => { loadFilters(); });
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
  { id: 'cumGap', cols: 8, rows: 8, visible: true },
  { id: 'backlog', cols: 8, rows: 8, visible: true },
    { id: 'backlogStatus', cols: 8, rows: 8, visible: true },
    { id: 'aging', cols: 8, rows: 8, visible: true },
  { id: 'openToday', cols: 8, rows: 8, visible: true },
  { id: 'createdToday', cols: 8, rows: 8, visible: true },
    { id: 'category', cols: 8, rows: 8, visible: true },
    { id: 'priority', cols: 8, rows: 8, visible: true },
    { id: 'impact', cols: 8, rows: 8, visible: true }
  ,{ id: 'resolutionHours', cols: 8, rows: 8, visible: true }
  ].map((w,i) => ({...w, order: i}));
  // Grid cell size (px) for snap positioning
  const CELL_W = 80; // base logical cell width (will derive snap unit)
  const CELL_H = 80; // base logical cell height
  const CARD_GAP = 4; // espaço (px) entre cards para não ficarem colados
  const DEV_SHOW_GRID = false; // ocultar marcações de desenvolvimento (linhas da dev grid)
  const AUTO_RESOLVE = false; // quando true empurra outros cards; false permite sobreposição
  const MAX_COLS = 72; // allow more cards per linha (24 limited 8x -> 3 per row; 72 -> até 9 de largura 8)
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
    // Sequential placement with wrapping so we don't overflow viewport on first load
    let x=0, y=0, rowH=0;
    let COLS = MAX_COLS;
    try {
      // If no stored layout yet, adapt maximum columns to current viewport width
      const hasStored = !!localStorage.getItem(STORAGE_KEY);
      if (!hasStored) {
        const snapW = CELL_W/2; // width of one logical column in px
        const usable = Math.max(320, window.innerWidth - 40); // leave small margin
        const dynCols = Math.floor(usable / snapW);
        if (dynCols >= 3) {
          COLS = Math.min(MAX_COLS, dynCols);
        }
      }
    } catch { /* ignore */ }
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
      // Ajusta larg/alt e posição com espaçamento interno (gap) sem alterar cálculo de maxRight/maxBottom
      const calcW = (w.cols * SNAP_W) - (CARD_GAP * 2);
      const calcH = (w.rows * SNAP_H) - (CARD_GAP * 2);
      el.style.width = (calcW > 20 ? calcW : (w.cols * SNAP_W)) + 'px';
      el.style.height = (calcH > 20 ? calcH : (w.rows * SNAP_H)) + 'px';
      el.style.left = (w.x * SNAP_W + CARD_GAP) + 'px';
      el.style.top = (w.y * SNAP_H + CARD_GAP) + 'px';
    });
  const maxBottom = layout.filter(w=>w.visible!==false).reduce((m,w)=> Math.max(m, (w.y + w.rows) * SNAP_H + CARD_GAP), 0);
  // Calcula a largura máxima usada (extremo direito dos cards visíveis)
  const maxRight = layout.filter(w=>w.visible!==false).reduce((m,w)=> Math.max(m, (w.x + w.cols) * SNAP_W + CARD_GAP), 0);
    grid.style.height = (maxBottom + 40) + 'px';
    // Define explicitamente a largura do grid para garantir que o scrollWidth reflita o conteúdo usado
    grid.style.width = (maxRight + 40) + 'px';

    // Ajusta largura do header e barra de filtros para cobrir toda a área utilizada quando houver overflow horizontal
    function adjustChromeWidths() {
      const header = document.querySelector('header');
      const controls = document.querySelector('.controls');
      const fullWidth = maxRight + 40; // mesma margem usada acima
      const needExpand = fullWidth > window.innerWidth + 1; // tolerância
      [header, controls].forEach(el => {
        if (!el) return;
        if (needExpand) {
          el.style.width = fullWidth + 'px';
        } else {
          el.style.width = '';
        }
      });
    }
    adjustChromeWidths();
    // Recalcula em resize para retornar ao estado original se o usuário ampliar a janela
    if (!window._glpiChromeResizeBound) {
      window.addEventListener('resize', () => {
        // Em resize só precisamos comparar com a largura atual do grid
        const gridEl = document.querySelector('.grid');
        if (!gridEl) return;
        const gWidth = gridEl.scrollWidth; // largura efetiva usada
        const header = document.querySelector('header');
        const controls = document.querySelector('.controls');
        const needExpand = gWidth > window.innerWidth + 1;
        [header, controls].forEach(el => {
          if (!el) return;
          if (needExpand) {
            el.style.width = gWidth + 'px';
          } else {
            el.style.width = '';
          }
        });
      });
      window._glpiChromeResizeBound = true;
    }
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
      // Resize handle
      if (!card.querySelector('.resize-handle')) {
        const rh = document.createElement('div'); rh.className='resize-handle'; card.appendChild(rh);
        const id = card.getAttribute('data-widget');
        rh.addEventListener('mousedown', e => { e.preventDefault(); e.stopPropagation();
          const item = layout.find(x=>x.id===id); if(!item) return; const sx=e.clientX, sy=e.clientY; const sw=card.offsetWidth, sh=card.offsetHeight; const snapW=CELL_W/2, snapH=CELL_H/2;
          function move(ev){
            const dx=ev.clientX-sx, dy=ev.clientY-sy; const newW=sw+dx, newH=sh+dy;
            const cols=Math.max(3, Math.round(newW / snapW)); const rows=Math.max(3, Math.round(newH / snapH));
            if(cols!==item.cols || rows!==item.rows){ item.cols=cols; item.rows=rows; apply(layout); }
          }
            function up(){ save(layout); document.removeEventListener('mousemove',move); document.removeEventListener('mouseup',up); }
          document.addEventListener('mousemove',move); document.addEventListener('mouseup',up);
        });
      }
      // Drag init
      if (!card.dataset.dragInit) { initDrag(card, layout); card.dataset.dragInit='1'; }
    });
  }
  function initDrag(card, layout){
    let startX,startY,origX,origY,previewX,previewY; const id=card.getAttribute('data-widget');
    function onMouseDown(e){ if(e.button!==0) return; const item=layout.find(w=>w.id===id); if(!item) return;
      startX=e.clientX; startY=e.clientY; origX=item.x||0; origY=item.y||0; previewX=origX; previewY=origY;
      card.classList.add('dragging'); document.body.classList.add('drag-mode'); card.style.zIndex=999;
      function onMove(ev){ const dx=ev.clientX-startX, dy=ev.clientY-startY; const snapW=CELL_W/2, snapH=CELL_H/2; const deltaCols=Math.round(dx/snapW), deltaRows=Math.round(dy/snapH); const newX=Math.max(0, origX+deltaCols), newY=Math.max(0, origY+deltaRows); if(newX!==previewX || newY!==previewY){ previewX=newX; previewY=newY; card.style.left=(previewX*snapW)+'px'; card.style.top=(previewY*snapH)+'px'; } }
      function onUp(){ const item=layout.find(w=>w.id===id); if(item){ item.x=previewX; item.y=previewY; if(AUTO_RESOLVE) resolveCollisions(item,layout); apply(layout); save(layout); } card.classList.remove('dragging'); document.body.classList.remove('drag-mode'); card.style.zIndex=''; document.removeEventListener('mousemove',onMove); document.removeEventListener('mouseup',onUp); }
      document.addEventListener('mousemove',onMove); document.addEventListener('mouseup',onUp);
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
    // Panel buttons
    document.getElementById('customizeToggle').addEventListener('click', () => openPanel(layout));
    document.getElementById('lpClose').addEventListener('click', () => document.getElementById('layoutPanel').classList.add('hidden'));
    document.getElementById('lpDone').addEventListener('click', () => document.getElementById('layoutPanel').classList.add('hidden'));
    document.getElementById('lpReset').addEventListener('click', () => {
      localStorage.removeItem(STORAGE_KEY);
      const fresh = load();
      layout.splice(0, layout.length, ...fresh);
      apply(layout);
      save(layout);
      // re-init drag for any newly created cards
      document.querySelectorAll('.card[data-widget]').forEach(c => { if(!c.dataset.dragInit){ initDrag(c, layout); c.dataset.dragInit='1'; } });
      Toasts.push('success','Layout redefinido');
      // width recalibration
      try { const header=document.querySelector('header'); const controls=document.querySelector('.controls'); if(header) header.style.minWidth=''; if(controls) controls.style.minWidth=''; } catch{}
      requestAnimationFrame(()=>requestAnimationFrame(()=>adjustHeaderWidth&&adjustHeaderWidth()));
  // Também redefinir filtros para valores originais
  resetFilters();
    });
  }
  return { init };
})();
window.addEventListener('DOMContentLoaded', () => WidgetLayout.init());
// Click handlers for big counters
window.addEventListener('DOMContentLoaded', () => {
  const o = document.getElementById('openTodayValue');
  if (o) {
    o.style.cursor = 'pointer';
    o.addEventListener('click', () => openTicketsModal('open_today', 'Abertos Agora'));
  }
  const ctd = document.getElementById('createdTodayValue');
  if (ctd) {
    ctd.style.cursor = 'pointer';
    ctd.addEventListener('click', () => openTicketsModal('created_today', 'Criados Hoje'));
  }
});

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
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 200,
      interaction: { mode: 'nearest', intersect: false },
      scales: { y: { beginAtZero: true } },
      plugins: {
        tooltip: {
          callbacks: {
            label: ctx => {
              const dsLabel = ctx.dataset.label || '';
              return `${dsLabel}: ${ctx.parsed.y}`;
            },
            footer: function(tooltipItems) {
              if (!tooltipItems || !tooltipItems.length) return '';
              try {
                const ds = this.chart.data.datasets[tooltipItems[0].datasetIndex];
                return ds && ds.help ? ds.help : '';
              } catch (e) { return ''; }
            }
          }
        }
      }
    }
  });
}

function barChart(canvasId, labels, data, label, help) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return; // canvas not present
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label, data, help }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 200,
      scales: { y: { beginAtZero: true } },
      plugins: {
        tooltip: {
          callbacks: {
            footer: function(tooltipItems) {
              if (!tooltipItems || !tooltipItems.length) return '';
              try {
                const ds = this.chart.data.datasets[tooltipItems[0].datasetIndex];
                return ds && ds.help ? ds.help : '';
              } catch (e) { return ''; }
            }
          }
        }
      }
    }
  });
}

function destroyChart(id) {
  if (charts[id]) {
    try { charts[id].destroy(); } catch(e) {}
    delete charts[id];
  }
  const cv = document.getElementById(id);
  if (cv && cv.getContext) {
    try { const g = cv.getContext('2d'); g && g.clearRect(0,0,cv.width,cv.height); } catch(e) {}
  }
}

function setMeta(meta, count, period) {
  const el = document.getElementById('meta');
  const gids = meta?.groups || [];
  let info = `Período: ${period.start} a ${period.end} • Tickets: ${count} `;
  if (typeof meta?.tids === 'number') info += `• Tickets retornados=${meta.tids}`;
  el.textContent = `Meus grupos: [${gids.join(', ')}] • ${info}`;
  // Marca widgets que ignoram período (fallback se HTML não tiver badge)
  const ignore = meta?.ignore_period_widgets || [];
  ignore.forEach(id => {
    const card = document.querySelector(`.card[data-widget="${id}"] h2`);
    if (card && !card.querySelector('.badge-period')) {
      const span = document.createElement('span');
      span.className = 'badge-period';
      span.textContent = '(Ignora filtro de período)';
      span.title = 'Ignora filtro de período';
      card.appendChild(document.createTextNode(' '));
      card.appendChild(span);
    }
  });
}

let loading = false;
let lastMeta = null; // guarda metadados da última chamada /api/data
let lastSeries = null; // guarda as últimas séries retornadas (/api/data)
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

  const catSel = document.getElementById('catFilter').value;
  const r = await fetch(`/api/data?gran=${encodeURIComponent(gran)}&start=${startNorm}&end=${endNorm}&cat=${encodeURIComponent(catSel)}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${txt.slice(0,200)}`);
    }
    const js = await r.json();
    if (js.error) throw new Error(js.error);

  setMeta(js.meta || {}, js.count || 0, js.period || {});
  lastMeta = js.meta || null;

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
  lastSeries = s;
    // Line charts
  if (s.created && s.resolved && s.created.data && s.resolved.data && s.created.data.length && s.resolved.data.length && document.getElementById('chartCumGap')) {
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
          { label: 'Criados (Acum.)', data: cumCreated, borderColor: '#1d4ed8', backgroundColor: 'rgba(29,78,216,0.15)', tension:0.15, help: 'Acumulado de tickets criados desde o início do período selecionado.' },
          { label: 'Resolvidos (Acum.)', data: cumResolved, borderColor: '#059669', backgroundColor: 'rgba(5,150,105,0.15)', tension:0.15, help: 'Acumulado de tickets resolvidos desde o início do período selecionado.' },
          { label: 'Gap Cumulativo (Criados - Resolvidos)', data: gap, borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,0.15)', tension:0.15, help: 'Diferença acumulada entre tickets criados e resolvidos; valores positivos indicam aumento do backlog.' }
        ]},
        options: {
          responsive:true, maintainAspectRatio:false, animation:false, resizeDelay:200,
          interaction:{ mode:'nearest', intersect:false },
          scales:{ y:{ beginAtZero:true } },
          plugins:{ tooltip:{ callbacks:{ label: ctx => {
            const dsLabel = ctx.dataset.label || ''; return `${dsLabel}: ${ctx.parsed.y}`; }, footer: function(items){ try{ const ds = this.chart.data.datasets[items[0].datasetIndex]; return ds && ds.help ? ds.help : ''; }catch(e){ return ''; } } } } }
        }
      });
      attachPointClick('chartCumGap', s.created.labels, ['created','resolved']);
  } else { destroyChart('chartCumGap'); }
    // Unified Backlog widget: combined canvas with toggle between raw backlog and smoothed trend
  if (s.backlog && s.backlog.data && s.backlog.data.length) {
      const labels = (s.backlog && s.backlog.labels && s.backlog.labels.length) ? s.backlog.labels : (s.backlog_trend.labels || []);
      const rawData = (s.backlog && s.backlog.data) ? s.backlog.data : [];
      const smoothData = (s.backlog_trend && s.backlog_trend.data) ? s.backlog_trend.data : [];

      const datasets = [
        { label: 'Backlog (Tendência)', data: rawData, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', tension: 0.2, help: 'Número de tickets em aberto por ponto do período (valor bruto).'},
        { label: 'Backlog (Suavizado)', data: smoothData, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.15)', tension:0.25, help: 'Série suavizada para destacar a tendência do backlog ao longo do tempo.' }
      ];

      lineChart('chartBacklogCombined', labels, datasets);
      attachPointClick('chartBacklogCombined', labels, ['backlog']);
  } else { destroyChart('chartBacklogCombined'); }

    // Bar charts
  if (s.backlog_status && s.backlog_status.data && s.backlog_status.data.length) { barChart('chartBacklogStatus', s.backlog_status.labels, s.backlog_status.data, 'Status', 'Distribuição atual dos tickets em aberto por status (snapshot — ignora filtro de período).'); attachBarClick('chartBacklogStatus', s.backlog_status.labels, 'backlog_status'); } else if (charts['chartBacklogStatus']) { charts['chartBacklogStatus'].destroy(); }
  if (s.aging && s.aging.data && s.aging.data.length) { barChart('chartAging', s.aging.labels, s.aging.data, 'Aging', 'Agrupa tickets abertos por faixas de idade para identificar chamados antigos em backlog (ignora filtro de período).'); attachBarClick('chartAging', s.aging.labels, 'aging'); } else if (charts['chartAging']) { charts['chartAging'].destroy(); }
  if (s.category && s.category.data && s.category.data.length) { barChart('chartCat', s.category.labels, s.category.data, 'Categoria', 'Distribuição de tickets por categoria no período selecionado. Use para identificar áreas com maior volume.'); attachBarClick('chartCat', s.category.labels, 'category'); } else if (charts['chartCat']) { charts['chartCat'].destroy(); }
  if (s.priority && s.priority.data && s.priority.data.length) { barChart('chartPr', s.priority.labels, s.priority.data, 'Prioridade', 'Número de tickets agrupados por nível de prioridade. Útil para visualizar criticidade.'); attachBarClick('chartPr', s.priority.labels, 'priority'); } else if (charts['chartPr']) { charts['chartPr'].destroy(); }
  if (s.impact && s.impact.data && s.impact.data.length) { barChart('chartImp', s.impact.labels, s.impact.data, 'Impacto', 'Distribuição por impacto dos tickets; ajuda a priorizar correções que afetam mais usuários ou sistemas.'); attachBarClick('chartImp', s.impact.labels, 'impact'); } else if (charts['chartImp']) { charts['chartImp'].destroy(); }
  if (s.resolution_hours && s.resolution_hours.data && s.resolution_hours.data.length) {
      const labels = s.resolution_hours.labels;
      const meanData = s.resolution_hours.data;
      const smoothData = (s.resolution_hours_trend && s.resolution_hours_trend.data) ? s.resolution_hours_trend.data : [];
      const datasets = [
        { label: 'Horas úteis (média)', data: meanData, borderColor: '#0ea5e9', backgroundColor: 'rgba(14,165,233,0.08)', tension:0.15, help: 'Tempo médio entre abertura e solução em horas úteis; útil para acompanhar SLAs.' },
        { label: 'Horas úteis (suavizado)', data: smoothData, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.08)', tension:0.25, help: 'Versão suavizada para destacar tendências de tempo de resolução.' }
      ];
      lineChart('chartResolutionHours', labels, datasets);
  } else { destroyChart('chartResolutionHours'); }
  // refresh hidden state (in case layout toggled visibility before load)
  document.querySelectorAll('.card[data-widget]').forEach(el => { if (el.style.display==='none') return; /* skip hidden */ });
  if (s.load_by_user) { barChart('chartUser', s.load_by_user.labels, s.load_by_user.data, 'Usuário', 'Quantidade de tickets abertos por usuário (pode representar solicitante ou responsável conforme configuração).'); attachBarClick('chartUser', s.load_by_user.labels, 'load_by_user'); }
  if (s.load_by_group) { barChart('chartGroup', s.load_by_group.labels, s.load_by_group.data, 'Grupo', 'Quantidade de tickets por grupo. Útil para identificar equipes com maior carga de chamados.'); attachBarClick('chartGroup', s.load_by_group.labels, 'load_by_group'); }

  } catch (e) {
    Toasts.push('error', String(e));
  } finally {
    Loader.hide();
    document.body.style.cursor = 'default';
    loading = false;
  }
}

// Removido botão Aplicar: atualização automática ao alterar filtros.
function bindAutoFilterReload() {
  const granSel = document.getElementById('gran');
  const catSel = document.getElementById('catFilter');
  const startInp = document.getElementById('start');
  const endInp = document.getElementById('end');
  const startMonthInp = document.getElementById('startMonth');
  const endMonthInp = document.getElementById('endMonth');
  const fire = () => { saveFilters(); loadData(); };
  [granSel, catSel, startInp, endInp, startMonthInp, endMonthInp].forEach(el => {
    if (!el) return;
    el.addEventListener('change', () => {
      // range buttons já chamam loadData; não duplicar se for preset (detecção básica)
      fire();
    });
  });
}
window.addEventListener('DOMContentLoaded', bindAutoFilterReload);
// Removido o loadData inicial antecipado para evitar corrida onde o primeiro carregamento (1 mês)
// ocorre antes de aplicar o range padrão (3 meses). Agora o primeiro load acontece via
// clique programático do botão de range default em initRangeButtons().

// --- Export / Print dashboard ---
async function exportDashboard() {
  // Gather metadata and visible widgets
  const meta = document.getElementById('meta')?.textContent || '';
  const title = document.querySelector('header h1')?.textContent || 'Dashboard';
  const cards = Array.from(document.querySelectorAll('.card[data-widget]')).filter(c => c.style.display !== 'none');

  const parts = [];
  parts.push(`<h1 style="font-family:Inter,system-ui,Arial,sans-serif;color:#0f172a;font-size:22px;margin:8px 0">${escapeHtml(title)}</h1>`);
  parts.push(`<div style="color:#475569;margin-bottom:8px;font-size:13px">${escapeHtml(meta)}</div>`);

  for (const card of cards) {
    const widgetId = card.getAttribute('data-widget') || '';
    const heading = (card.querySelector('h2')?.innerText || widgetId).trim();
    // find canvas inside
    const cv = card.querySelector('canvas');
    let imgHtml = '';
    if (cv && charts[cv.id]) {
      try {
        const dataUrl = charts[cv.id].toBase64Image();
        imgHtml = `<img src="${dataUrl}" style="max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:6px;" />`;
      } catch (e) {
        // fallback: try canvas.toDataURL
        try { imgHtml = `<img src="${cv.toDataURL()}" style="max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:6px;" />`; } catch(e2) { imgHtml = '<div style="color:#a00">(Imagem indisponível)</div>'; }
      }
  } else {
      // maybe big-number or non-canvas widget
      const big = card.querySelector('.big-number');
      if (big) imgHtml = `<div style="font-size:28px;font-weight:700;color:#0f172a;margin:8px 0">${escapeHtml(big.textContent)}</div>`;
      else imgHtml = '<div style="color:#64748b">(Sem visualização)</div>';
    }
  // help text from the DOM button title or dataset
  const helpBtn = card.querySelector('button.help');
  const helpText = helpBtn ? helpBtn.getAttribute('title') : (charts[cv?.id]?.data?.datasets?.[0]?.help || '');
  // generate an automated insight where possible
  const insight = generateInsight(widgetId, lastSeries, lastMeta);

  parts.push(`<section style="margin-bottom:22px;page-break-inside:avoid"><h2 style="font-size:18px;color:#0f172a;margin:0 0 8px">${escapeHtml(heading)}</h2><div style="color:#475569;margin-bottom:8px;font-size:13px">${escapeHtml(helpText || '')}</div>${imgHtml}<div style="margin-top:8px;padding:10px;border-left:3px solid #e2e8f0;background:#fbfdff;border-radius:6px"><strong>Interpretação:</strong><p style="margin:6px 0;color:#0f172a">${escapeHtml(insight || 'Nenhuma observação automática disponível.')}</p></div></section>`);
  }

  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>body{font-family:Inter,system-ui,Arial,sans-serif;padding:18px;color:#0f172a} h1{margin:0 0 6px} h2{margin:8px 0}</style></head><body>${parts.join('\n')}<script>window.onload=function(){ setTimeout(()=>{window.print();},200); };</script></body></html>`;

  const w = window.open('', '_blank');
  if (!w) { Toasts.push('error', 'Não foi possível abrir nova janela — verifique bloqueador de pop-ups.'); return; }
  w.document.open(); w.document.write(html); w.document.close();
}

document.getElementById('exportBtn').addEventListener('click', exportDashboard);

function generateInsight(widgetId, series, meta) {
  try {
    if (!series) return '';
    switch (widgetId) {
      case 'cumGap': {
        const created = series.created?.data || [];
        const resolved = series.resolved?.data || [];
        const lastCreated = Number(created[created.length-1]||0);
        const lastResolved = Number(resolved[resolved.length-1]||0);
        const trend = (created.length>=2 && (created[created.length-1] - created[0]) > (resolved[resolved.length-1] - (resolved[0]||0))) ? 'O volume de criação cresceu mais que o de resoluções, indicando pressão de backlog.' : 'Criações e resoluções acompanham-se de forma semelhante.';
        return `${trend} No período apurado (${meta?.period?.start||''} a ${meta?.period?.end||''}), foram criados ${created.reduce((a,b)=>a+Number(b||0),0)} chamados e resolvidos ${resolved.reduce((a,b)=>a+Number(b||0),0)}.`;
      }
      case 'backlog': {
        const backlog = series.backlog?.data || [];
        const last = Number(backlog[backlog.length-1]||0);
        return `Backlog atual estimado em ${last.toLocaleString('pt-BR')} chamados. Verifique tendência nas últimas semanas para priorizar ações.`;
      }
      case 'backlogStatus': {
        const labels = series.backlog_status?.labels || [];
        const data = series.backlog_status?.data || [];
        const maxIdx = data.reduce((ix, v, i, arr) => v>arr[ix]?i:ix, 0);
        return `Status predominante: ${labels[maxIdx] || 'N/A'} com ${Number(data[maxIdx]||0).toLocaleString('pt-BR')} chamados. Esta visão é um snapshot atual.`;
      }
      case 'aging': {
        const labels = series.aging?.labels || [];
        const data = series.aging?.data || [];
        if (!data.length) return '';
        const maxIdx = data.reduce((ix, v, i, arr) => v>arr[ix]?i:ix, 0);
        return `Faixa com maior concentração de tickets: ${labels[maxIdx] || 'N/A'} (${Number(data[maxIdx]||0).toLocaleString('pt-BR')}). Focar em reduzir tickets nas faixas mais antigas.`;
      }
      case 'resolutionHours': {
        const d = series.resolution_hours?.data || [];
        if (!d.length) return '';
        const avg = (d.reduce((a,b)=>a+Number(b||0),0) / d.length).toFixed(1);
        return `Tempo médio de resolução (amostra): ${avg} horas úteis. Compare com o SLA alvo para avaliar desempenho.`;
      }
      case 'category': {
        const labels = series.category?.labels || []; const data = series.category?.data || [];
        if (!data.length) return '';
        const maxIdx = data.reduce((ix, v, i, arr) => v>arr[ix]?i:ix, 0);
        return `Categoria com maior volume: ${labels[maxIdx] || 'N/A'} — ${Number(data[maxIdx]||0).toLocaleString('pt-BR')} chamados no período.`;
      }
      case 'priority': {
        const labels = series.priority?.labels || []; const data = series.priority?.data || [];
        return `Distribuição por prioridade apresentada; analise picos em prioridades altas para alocar recursos.`;
      }
      case 'impact': {
        return `Distribuição por impacto apresentada; priorize correções com maior impacto operacional.`;
      }
      case 'load_by_user':
      case 'load_by_group': {
        return `Carga por ${widgetId==='load_by_user'?'usuário':'grupo'} mostrada; identifique responsáveis com maior volume para balanceamento.`;
      }
      default: return '';
    }
  } catch (e) { return ''; }
}

// --- Help popover for small ❔ buttons ---
function createHelpPopover(text) {
  const el = document.createElement('div');
  el.className = 'help-popover';
  el.tabIndex = -1;
  el.innerHTML = `<button class="help-close" aria-label="Fechar">×</button><div class="help-popover-inner"></div>`;
  el.querySelector('.help-popover-inner').textContent = text;
  el.querySelector('.help-close').addEventListener('click', () => { if (el && el.parentNode) el.parentNode.removeChild(el); });
  return el;
}

function attachHelpPopovers() {
  // Delegated so we can call it after dynamic changes if needed
  document.querySelectorAll('button.help').forEach(btn => {
    if (btn._helpAttached) return; // idempotent
    btn._helpAttached = true;
    btn.type = 'button';
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      // close any other popovers
      document.querySelectorAll('.help-popover').forEach(p => p.remove());
      const helpText = btn.getAttribute('title') || btn.dataset.help || '';
      const pop = createHelpPopover(helpText);
      document.body.appendChild(pop);
      // position near button (prefer below-right)
      const r = btn.getBoundingClientRect();
      const left = Math.min(window.innerWidth - 16 - 360, r.left + window.scrollX + 6);
      const top = r.bottom + window.scrollY + 8;
      pop.style.left = `${left}px`;
      pop.style.top = `${top}px`;
      btn.setAttribute('aria-expanded', 'true');

      // close on outside click or Escape
      function onDocClick(e) {
        if (!pop.contains(e.target) && e.target !== btn) { pop.remove(); btn.setAttribute('aria-expanded','false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); }
      }
      function onEsc(e) { if (e.key === 'Escape') { pop.remove(); btn.setAttribute('aria-expanded','false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); } }
      setTimeout(() => document.addEventListener('click', onDocClick));
      document.addEventListener('keydown', onEsc);
      // focus popover for keyboard users
      pop.focus();
    });
  });
}

window.addEventListener('DOMContentLoaded', attachHelpPopovers);

// Preset range buttons: set start/end quickly. Default active = 3 months
function isoDate(d) { return d.toISOString().slice(0,10); }
function setRangeDays(days) {
  const end = new Date();
  const start = new Date();
  // user requested exact N days before today
  start.setDate(end.getDate() - days);
  document.getElementById('start').value = isoDate(start);
  document.getElementById('end').value = isoDate(end);
}
function setRangeMonths(months) {
  const end = new Date();
  const start = new Date();
  // use approximate month = 30 days as requested (1 month = 30 days)
  const days = months * 30;
  start.setDate(end.getDate() - days);
  document.getElementById('start').value = isoDate(start);
  document.getElementById('end').value = isoDate(end);
}

let _suppressRangeChange = false; // suppress custom activation when programmatically changing inputs
function initRangeButtons(){
  const btns = Array.from(document.querySelectorAll('.range-btn'));
  const dateInputs = [document.getElementById('start'), document.getElementById('end')].filter(Boolean);
  const monthInputs = [document.getElementById('startMonth'), document.getElementById('endMonth')].filter(Boolean);

  btns.forEach(b => {
    // Botão 'Personalizado' não deve ser clicável diretamente
    if (b.classList.contains('custom')) {
      b.classList.add('non-clickable'); // classe opcional para estilização futura
      return;
    }
    b.addEventListener('click', (e) => {
      btns.forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      const rangeType = b.dataset.range || null;
      const days = b.dataset.days ? Number(b.dataset.days) : null;
      const months = b.dataset.months ? Number(b.dataset.months) : null;
      _suppressRangeChange = true;
      try {
        if (rangeType === 'current_month') {
          // first day of this month to today
          const now = new Date();
          const start = new Date(now.getFullYear(), now.getMonth(), 1);
          const end = new Date();
          document.getElementById('start').value = isoDate(start);
          document.getElementById('end').value = isoDate(end);
        } else if (rangeType === 'prev_month') {
          const now = new Date();
          const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
          const end = new Date(now.getFullYear(), now.getMonth(), 0); // last day previous month
          document.getElementById('start').value = isoDate(start);
          document.getElementById('end').value = isoDate(end);
        } else if (days) {
          setRangeDays(days);
        } else if (months) {
          setRangeMonths(months);
        }
        // If current granularity is Mensal, also set month inputs
        if (document.getElementById('gran').value === 'Mensal') {
          const s = document.getElementById('start').value.slice(0,7);
          const e = document.getElementById('end').value.slice(0,7);
          if (document.getElementById('startMonth')) document.getElementById('startMonth').value = s;
          if (document.getElementById('endMonth')) document.getElementById('endMonth').value = e;
        }
      } finally { _suppressRangeChange = false; }
  loadData();
  saveFilters();
    });
  });

  // If user manually edits date/month inputs, mark 'Personalizado'
  function onManualChange() {
    if (_suppressRangeChange) return; // ignore programmatic changes
    btns.forEach(x => x.classList.remove('active'));
    const custom = document.querySelector('.range-btn.custom'); if (custom) custom.classList.add('active');
    saveFilters();
  }
  dateInputs.forEach(inp => inp.addEventListener('change', onManualChange));
  monthInputs.forEach(inp => inp.addEventListener('change', onManualChange));

  // default: só aplica preset se filtros não foram restaurados do storage
  if (!window._filtersRestored) {
    const def = document.querySelector('.range-btn.active');
    if (def) def.click();
  } else {
    // filtros restaurados -> garantir primeiro carregamento
    loadData();
  }
}
window.addEventListener('DOMContentLoaded', initRangeButtons);

// ---- Auto Refresh ----
let autoTimer = null;
function setupAutoRefresh() {
  const inp = document.getElementById('autoRefreshMin');
  if (!inp) return;
  const STORAGE_KEY = 'glpiAutoRefreshMin';
  // load saved
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null && saved !== '') {
      inp.value = saved;
    } else {
      // default 30 minutes
      inp.value = '30';
    }
  } catch {}
  function applyInterval() {
    if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
    const mins = parseInt(inp.value, 10);
    if (!isNaN(mins) && mins > 0) {
      const ms = mins * 60 * 1000;
      autoTimer = setInterval(() => {
        if (!loading) loadData();
      }, ms);
    }
    try { localStorage.setItem(STORAGE_KEY, inp.value || ''); } catch {}
  }
  inp.addEventListener('change', applyInterval);
  applyInterval();
}
window.addEventListener('DOMContentLoaded', setupAutoRefresh);

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

// --- Dynamic modal table (sortable & resizable) ---
const TicketTable = (() => {
  const columns = [
    { key: 'id', label: 'ID', numeric: true },
    { key: 'titulo', label: 'Título' },
    { key: 'status', label: 'Status' },
    { key: 'categoria', label: 'Categoria' },
    { key: 'abertura', label: 'Abertura', type: 'date' },
    { key: 'ultima_atualizacao', label: 'Última atualização', type: 'date' },
    { key: 'grupo_atribuido', label: 'Grupo atribuído' }
  ];
  let currentRows = [];
  let sortState = { key: 'id', dir: 'asc' };
  function buildHeader() {
    const tr = document.getElementById('modal-head-row');
    if (!tr) return;
    tr.innerHTML = '';
    columns.forEach(col => {
      const th = document.createElement('th');
      th.textContent = col.label;
      th.dataset.key = col.key;
      th.className = 'sortable';
      // Sort click
      th.addEventListener('click', () => {
        if (sortState.key === col.key) {
          sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
        } else {
          sortState.key = col.key; sortState.dir = 'asc';
        }
        renderBody();
      });
      // Resizer
      const resizer = document.createElement('div');
      resizer.className = 'col-resizer';
      let startX, startW;
      resizer.addEventListener('mousedown', e => {
        e.preventDefault(); e.stopPropagation();
        startX = e.clientX; startW = th.offsetWidth;
        function move(ev){
          const dx = ev.clientX - startX;
          const newW = Math.max(50, startW + dx);
          th.style.width = newW + 'px';
        }
        function up(){
          document.removeEventListener('mousemove', move);
          document.removeEventListener('mouseup', up);
        }
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
      });
      th.appendChild(resizer);
      tr.appendChild(th);
    });
  }
  function compare(a, b) {
    const { key, dir } = sortState;
    let va = a[key], vb = b[key];
    if (va == null) va = ''; if (vb == null) vb = '';
    // Date parse
    const col = columns.find(c => c.key === key);
    if (col && col.type === 'date') {
      const da = Date.parse(va) || 0; const db = Date.parse(vb) || 0;
      return dir === 'asc' ? da - db : db - da;
    }
    if (col && col.numeric) {
      const na = Number(va); const nb = Number(vb);
      return dir === 'asc' ? na - nb : nb - na;
    }
    const sa = String(va).toLowerCase();
    const sb = String(vb).toLowerCase();
    if (sa < sb) return dir === 'asc' ? -1 : 1;
    if (sa > sb) return dir === 'asc' ? 1 : -1;
    return 0;
  }
  function renderBody() {
    const tbody = document.getElementById('modal-rows');
    if (!tbody) return;
    const rows = currentRows.slice().sort(compare).map(r => {
      return `<tr>
        <td><a href="${buildGlpiLink(r.id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.id)}</a></td>
        <td>${escapeHtml(r.titulo)}</td>
        <td>${escapeHtml(r.status)}</td>
        <td>${escapeHtml(r.categoria)}</td>
        <td>${escapeHtml(r.abertura)}</td>
        <td>${escapeHtml(r.ultima_atualizacao || '')}</td>
    <td>${escapeHtml(r.grupo_atribuido)}</td>
      </tr>`;
    }).join('');
  tbody.innerHTML = rows || '<tr><td colspan="7">Nenhum chamado</td></tr>';
    // Update sort indicators
    document.querySelectorAll('#modal-head-row th').forEach(th => {
      th.classList.remove('sort-asc','sort-desc');
      if (th.dataset.key === sortState.key) th.classList.add(sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    });
  }
  function setRows(data){ currentRows = data || []; renderBody(); }
  function init(){ buildHeader(); }
  return { init, setRows };
})();
window.addEventListener('DOMContentLoaded', () => TicketTable.init());

function attachPointClick(canvasId, labels, sources) {
  const c = charts[canvasId];
  const canvas = document.getElementById(canvasId);
  if (!canvas || !c) return; // defensive: canvas may be missing on some pages
  canvas.onclick = async (evt) => {
    try {
      const points = (typeof c.getElementsAtEventForMode === 'function')
        ? c.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true)
        : [];
      if (!points.length) return;
      const idx = points[0].index;
      const label = labels[idx];
      // prefer source based on dataset index if provided
  const dsIndex = points[0].datasetIndex || 0;
  // Se clicar em dataset além dos mapeados (ex: linha Gap cumulativo), ignora
  if (dsIndex >= sources.length) return;
  const source = sources[dsIndex];
      await openTicketsModal(source, label);
    } catch (err) {
      console.error('attachPointClick error', err);
    }
  };
}

function attachBarClick(canvasId, labels, source) {
  const c = charts[canvasId];
  const canvas = document.getElementById(canvasId);
  if (!canvas || !c) return; // defensive: guard when canvas/chart missing
  canvas.onclick = async (evt) => {
    try {
      const bars = (typeof c.getElementsAtEventForMode === 'function')
        ? c.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true)
        : [];
      if (!bars.length) return;
      const idx = bars[0].index;
      const label = labels[idx];
      await openTicketsModal(source, label);
    } catch (err) {
      console.error('attachBarClick error', err);
    }
  };
}

async function openTicketsModal(source, label) {
  const gran = document.getElementById('gran').value;
  let userStart, userEnd;
  if (gran === 'Mensal') {
    // Recalcula como em loadData
    const sm = document.getElementById('startMonth').value; // YYYY-MM
    const em = document.getElementById('endMonth').value;   // YYYY-MM
    userStart = sm + '-01';
    const [ey, emon] = em.split('-').map(Number);
    const lastDay = new Date(ey, emon, 0); // ultimo dia mês final
    userEnd = lastDay.toISOString().slice(0,10);
  } else {
    userStart = document.getElementById('start').value;
    userEnd = document.getElementById('end').value;
  }

  // Decidir se precisamos da janela baseline ampliada na consulta de tickets
  const ignoreList = (lastMeta && lastMeta.ignore_period_widgets) || [];
  const baselineWin = lastMeta && lastMeta.baseline_window && lastMeta.baseline_window.used ? lastMeta.baseline_window : null;
  const needBaseline = !!(baselineWin && (ignoreList.includes(source) || source === 'backlog'));
  const bstart = needBaseline ? baselineWin.start : userStart;
  const bend = needBaseline ? baselineWin.end : userEnd;

  // Enviar também userStart/userEnd para o backend poder restringir as séries que respeitam filtro
  const catSel = document.getElementById('catFilter').value;
  const params = new URLSearchParams({
    gran,
    start: bstart,
    end: bend,
    source,
    label,
    ustart: userStart,
    uend: userEnd,
    baseline: needBaseline ? '1' : '0',
    cat: catSel
  });

  modal.title.textContent = `Chamados — ${source} · ${label}`;
  modal.info.textContent = 'Carregando...';
  modal.rows.innerHTML = '';
  modal.show();
  Loader.show('Carregando chamados...');
  document.body.style.cursor = 'progress';
  try {
  const r = await fetch(`/api/tickets?${params.toString()}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${txt.slice(0,200)}`);
    }
    const js = await r.json();
    if (js.error) throw new Error(js.error);
    modal.info.textContent = `Total no filtro: ${js.count} • Mostrando: ${js.returned}`;
  const rows = js.tickets || [];
  TicketTable.setRows(rows);
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
