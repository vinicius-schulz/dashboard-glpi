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

function lineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
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
