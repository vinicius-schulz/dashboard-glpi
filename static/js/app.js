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
  const STORAGE_KEY = 'glpiDashboardLayout.v1';
  const DEFAULT = [
    { id: 'createdResolved', width: 2, height: 1, visible: true },
    { id: 'backlog', width: 1, height: 1, visible: true },
    { id: 'backlogStatus', width: 1, height: 1, visible: true },
    { id: 'sla', width: 1, height: 1, visible: true },
    { id: 'aging', width: 1, height: 1, visible: true },
    { id: 'category', width: 1, height: 1, visible: true },
    { id: 'priority', width: 1, height: 1, visible: true },
    { id: 'impact', width: 1, height: 1, visible: true }
  ];
  function load() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || DEFAULT; } catch { return DEFAULT; }
  }
  function save(layout) { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); }
  function apply(layout) {
    const grid = document.querySelector('.grid');
    const map = new Map(layout.map(w => [w.id, w]));
    // Ensure every default exists (handle new widgets added later)
    DEFAULT.forEach(def => { if (!map.has(def.id)) { layout.push(def); map.set(def.id, def); } });
    const ordered = layout.filter(w => w.visible);
    ordered.sort((a,b) => (a.order ?? 0) - (b.order ?? 0));
    // reorder DOM
    ordered.forEach(w => {
      const el = grid.querySelector(`.card[data-widget="${w.id}"]`);
      if (el) grid.appendChild(el);
    });
    // apply visibility + width/height
    document.querySelectorAll('.card[data-widget]').forEach(el => {
      const id = el.getAttribute('data-widget');
      const w = map.get(id);
      if (!w || w.visible === false) {
        el.classList.add('hidden-by-layout');
        el.style.display = 'none';
      } else {
        el.classList.remove('hidden-by-layout');
        el.style.display = '';
        el.classList.remove('w-1','w-2','w-3','h-1','h-2','h-3');
        el.classList.add(`w-${w.width || 1}`);
        el.classList.add(`h-${w.height || 1}`);
      }
    });
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
          if (btn.dataset.act === 'hide') { item.visible = false; save(layout); apply(layout); Toasts.push('info', `Widget ocultado: ${id}`); }
        });
      }
      // resize handle
      if (!card.querySelector('.resize-handle')) {
        const rh = document.createElement('div'); rh.className='resize-handle'; card.appendChild(rh);
        let startX, startY, startW, startH;
        rh.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation();
          const id = card.getAttribute('data-widget');
          const item = layout.find(x=>x.id===id); if (!item) return;
          startX = e.clientX; startY = e.clientY; startW = card.offsetWidth; startH = card.offsetHeight;
          function move(ev){
            const dx = ev.clientX - startX; const dy = ev.clientY - startY;
            const newW = startW + dx; const newH = startH + dy;
            // snap horizontal to grid width (approx width of one auto column ~ min 300px)
            const colBase = 300; const spanW = Math.min(3, Math.max(1, Math.round(newW / colBase)));
            const rowBase = 280; const spanH = Math.min(3, Math.max(1, Math.round(newH / rowBase)));
            item.width = spanW; item.height = spanH;
            save(layout); apply(layout);
          }
            function up(){ document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
          document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
        });
      }
      card.setAttribute('draggable','true');
    });
  }
  function enableDrag(layout) {
    const grid = document.querySelector('.grid');
    let dragEl = null;
    grid.addEventListener('dragstart', e => {
      const card = e.target.closest('.card[data-widget]');
      if (!card) return;
      dragEl = card; card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    grid.addEventListener('dragend', () => { if (dragEl) dragEl.classList.remove('dragging'); dragEl = null; saveOrder(layout); });
    grid.addEventListener('dragover', e => {
      if (!dragEl) return; e.preventDefault();
      const after = getDragAfterElement(grid, e.clientY, e.clientX);
      if (after == null) grid.appendChild(dragEl); else grid.insertBefore(dragEl, after);
    });
    function saveOrder(layout) {
      const ids = Array.from(grid.querySelectorAll('.card[data-widget]')).map(c=>c.getAttribute('data-widget'));
      ids.forEach((id, idx) => { const item = layout.find(w=>w.id===id); if (item) item.order = idx; });
      save(layout);
    }
    function getDragAfterElement(container, y, x) {
      const els = [...container.querySelectorAll('.card[data-widget]:not(.dragging)')];
      return els.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) { return { offset, element: child }; }
        return closest;
      }, { offset: Number.NEGATIVE_INFINITY }).element;
    }
  }
  function openPanel(layout) {
    const panel = document.getElementById('layoutPanel');
    const tbody = document.getElementById('lpRows');
    tbody.innerHTML = '';
    layout.forEach(w => {
      const row = document.createElement('tr');
      row.innerHTML = `<td>${w.id}</td><td><input type="checkbox" data-f="vis" ${w.visible!==false?'checked':''}></td>
        <td>
          L:<select data-f="w"><option value="1" ${w.width==1?'selected':''}>1</option><option value="2" ${w.width==2?'selected':''}>2</option><option value="3" ${w.width==3?'selected':''}>3</option></select>
          H:<select data-f="h"><option value="1" ${w.height==1?'selected':''}>1</option><option value="2" ${w.height==2?'selected':''}>2</option><option value="3" ${w.height==3?'selected':''}>3</option></select>
        </td>`;
      row.querySelectorAll('input,select').forEach(inp => {
        inp.addEventListener('change', () => {
          if (inp.dataset.f==='vis') w.visible = inp.checked;
          if (inp.dataset.f==='w') w.width = parseInt(inp.value)||1;
          if (inp.dataset.f==='h') w.height = parseInt(inp.value)||1;
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
}

let loading = false;
async function loadData() {
  if (loading) return; // prevent concurrent renders
  loading = true;
  Loader.show('Carregando dados...');
  document.body.style.cursor = 'progress';
  try {
    const gran = document.getElementById('gran').value;
    const start = document.getElementById('start').value;
    const end = document.getElementById('end').value;
    const max = document.getElementById('max').value;

    const r = await fetch(`/api/data?gran=${encodeURIComponent(gran)}&start=${start}&end=${end}&max=${max}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${txt.slice(0,200)}`);
    }
    const js = await r.json();
    if (js.error) throw new Error(js.error);

    setMeta(js.meta || {}, js.count || 0, js.period || {});

    const s = js.series || {};
    // Line charts
    if (s.created && s.resolved) {
      lineChart('chartCreatedResolved', s.created.labels, [
        { label: 'Criados', data: s.created.data, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.2)', tension: 0.2 },
        { label: 'Resolvidos', data: s.resolved.data, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.2)', tension: 0.2 }
      ]);
      attachPointClick('chartCreatedResolved', s.created.labels, ['created', 'resolved']);
    }
    if (s.backlog) {
      lineChart('chartBacklog', s.backlog.labels, [
        { label: 'Backlog', data: s.backlog.data, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', tension: 0.2 }
      ]);
      attachPointClick('chartBacklog', s.backlog.labels, ['backlog']);
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
  const max = document.getElementById('max').value;
  modal.title.textContent = `Chamados — ${source} · ${label}`;
  modal.info.textContent = 'Carregando...';
  modal.rows.innerHTML = '';
  modal.show();
  Loader.show('Carregando chamados...');
  document.body.style.cursor = 'progress';
  try {
    const r = await fetch(`/api/tickets?gran=${encodeURIComponent(gran)}&start=${start}&end=${end}&max=${max}&source=${encodeURIComponent(source)}&label=${encodeURIComponent(label)}`);
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
