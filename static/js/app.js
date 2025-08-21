let charts = {};

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
  const gran = document.getElementById('gran').value;
  const start = document.getElementById('start').value;
  const end = document.getElementById('end').value;
  const max = document.getElementById('max').value;

  const r = await fetch(`/api/data?gran=${encodeURIComponent(gran)}&start=${start}&end=${end}&max=${max}`);
  const js = await r.json();
  if (js.error) {
    alert(js.error);
    loading = false;
    return;
  }

  setMeta(js.meta || {}, js.count || 0, js.period || {});

  const s = js.series || {};
  // Line charts
  if (s.created && s.resolved) {
    lineChart('chartCreatedResolved', s.created.labels, [
      { label: 'Criados', data: s.created.data, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.2)', tension: 0.2 },
      { label: 'Resolvidos', data: s.resolved.data, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.2)', tension: 0.2 }
    ]);
  }
  if (s.backlog) {
    lineChart('chartBacklog', s.backlog.labels, [
      { label: 'Backlog', data: s.backlog.data, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', tension: 0.2 }
    ]);
  }

  // Bar charts
  if (s.backlog_status) barChart('chartBacklogStatus', s.backlog_status.labels, s.backlog_status.data, 'Status');
  if (s.aging) barChart('chartAging', s.aging.labels, s.aging.data, 'Aging');
  if (s.category) barChart('chartCat', s.category.labels, s.category.data, 'Categoria');
  if (s.priority) barChart('chartPr', s.priority.labels, s.priority.data, 'Prioridade');
  if (s.impact) barChart('chartImp', s.impact.labels, s.impact.data, 'Impacto');
  if (s.load_by_user) barChart('chartUser', s.load_by_user.labels, s.load_by_user.data, 'Usuário');
  if (s.load_by_group) barChart('chartGroup', s.load_by_group.labels, s.load_by_group.data, 'Grupo');

  // SLA block
  const sla = js.sla || {};
  document.getElementById('sla').textContent = JSON.stringify(sla, null, 2);
  loading = false;
}

document.getElementById('apply').addEventListener('click', () => loadData());
window.addEventListener('DOMContentLoaded', () => loadData());
