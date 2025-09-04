let charts = {};
const UI_BASE = document.body.getAttribute('data-ui-base') || '';
// ---- Tooltip custom para badge-period (ignora filtro de período) ----
function initBadgePeriodTooltips() {
  // Use the same popover implementation as help buttons (createHelpPopover)
  function showPopoverFor(el) {
    // close any other help popovers
    document.querySelectorAll('.help-popover').forEach(p => p.remove());
    const helpText = el.getAttribute('title') || 'Ignora filtro de período';
    const pop = createHelpPopover(helpText);
    document.body.appendChild(pop);
    const r = el.getBoundingClientRect();
    // position similar to help buttons (below-right if possible)
    const left = Math.min(window.innerWidth - 16 - 360, r.left + window.scrollX + 6);
    const top = r.bottom + window.scrollY + 8;
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    // aria state
    el.setAttribute('aria-expanded', 'true');
    function onDocClick(e) {
      if (!pop.contains(e.target) && e.target !== el) { pop.remove(); el.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); }
    }
    function onEsc(e) { if (e.key === 'Escape') { pop.remove(); el.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); } }
    setTimeout(() => document.addEventListener('click', onDocClick));
    document.addEventListener('keydown', onEsc);
    pop.focus();
  }
  function bind(el) {
    if (el._bpBound) return; el._bpBound = true;
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'button');
    el.addEventListener('click', (e) => { e.stopPropagation(); showPopoverFor(el); });
    el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); showPopoverFor(el); } });
  }
  document.querySelectorAll('.badge-period').forEach(bind);
  const obs = new MutationObserver(() => { document.querySelectorAll('.badge-period').forEach(bind); });
  obs.observe(document.body, { childList: true, subtree: true });
}
window.addEventListener('DOMContentLoaded', initBadgePeriodTooltips);
// ---- Persistência de filtros (granularidade, categoria, datas, meses, range preset) ----
const FILTERS_KEY = 'glpiDashboardFilters.v1';
let _originalDefaults = null; // guarda valores iniciais vindos do backend (primeiro load)
function captureOriginalDefaultsOnce() {
  if (_originalDefaults) return;
  _originalDefaults = {
    gran: document.getElementById('gran')?.value || '',
    cat: document.getElementById('catFilter')?.value || '',
  assignedGroup: getAssignedGroupSelectedValues && getAssignedGroupSelectedValues().length ? getAssignedGroupSelectedValues() : 'todos',
  status: document.getElementById('statusFilter')?.value || 'todos',
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
  assignedGroup: getAssignedGroupSelectedValues(),
  status: document.getElementById('statusFilter')?.value,
      start: document.getElementById('start')?.value,
      end: document.getElementById('end')?.value,
      startMonth: document.getElementById('startMonth')?.value,
      endMonth: document.getElementById('endMonth')?.value,
      range: getActiveRangeDescriptor()
    };
    localStorage.setItem(FILTERS_KEY, JSON.stringify(data));
  } catch { }
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
  // eventos de mudança agora tratados dentro do dropdown custom (checkboxes)
  try {
    if (parsed.gran && document.getElementById('gran')) document.getElementById('gran').value = parsed.gran;
    if (parsed.cat && document.getElementById('catFilter')) document.getElementById('catFilter').value = parsed.cat;
  if (parsed.assignedGroup) { window._pendingAssignedGroupRestore = Array.isArray(parsed.assignedGroup)? parsed.assignedGroup : [parsed.assignedGroup]; }
  if (parsed.status && document.getElementById('statusFilter')) document.getElementById('statusFilter').value = parsed.status;
    if (parsed.start && document.getElementById('start')) document.getElementById('start').value = parsed.start;
    if (parsed.end && document.getElementById('end')) document.getElementById('end').value = parsed.end;
    if (parsed.startMonth && document.getElementById('startMonth')) document.getElementById('startMonth').value = parsed.startMonth;
    if (parsed.endMonth && document.getElementById('endMonth')) document.getElementById('endMonth').value = parsed.endMonth;
    applyRangeDescriptor(parsed.range);
    window._filtersRestored = true;
    toggleDateInputs();
  } catch { }
  return true;
}
function resetFilters() {
  try { localStorage.removeItem(FILTERS_KEY); } catch { }
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

// ---- Checkbox Dropdown (Assigned Groups) ----
function initAssignedGroupDropdown() {
  const ddExisting = document.getElementById('assignedGroupDropdown');
  // Fallback: se ainda existir um <select multiple id="assignedGroupFilter"> (layout antigo) converter
  if (!ddExisting) {
    const legacySel = document.querySelector('select#assignedGroupFilter[multiple]');
    if (legacySel) {
      const wrapper = document.createElement('div');
      wrapper.className = 'checkbox-dropdown';
      wrapper.id = 'assignedGroupDropdown';
      wrapper.dataset.open = 'false';
  wrapper.innerHTML = `\n        <button type="button" class="chkdd-toggle" id="assignedGroupToggle" aria-haspopup="listbox" aria-expanded="false" title="Selecionar grupos atribuídos">Todos</button>\n        <div class="chkdd-panel hidden" id="assignedGroupPanel" role="listbox" aria-multiselectable="true">\n          <div class="chkdd-search-wrapper"><input type="text" id="assignedGroupSearch" placeholder="Filtrar..." aria-label="Filtrar grupos" /></div>\n          <div class="chkdd-actions">\n            <button type="button" id="assignedGroupClear" class="mini">Limpar</button>\n          </div>\n          <div class="chkdd-options" id="assignedGroupOptions"></div>\n        </div>\n        <input type="hidden" id="assignedGroupFilter" value="todos" />`; // hidden substitui select
      legacySel.parentNode.replaceChild(wrapper, legacySel);
    }
  }
  const dd = document.getElementById('assignedGroupDropdown');
  if (!dd || dd._initDone) return; dd._initDone = true;
  const toggleBtn = document.getElementById('assignedGroupToggle');
  const panel = document.getElementById('assignedGroupPanel');
  const optsBox = document.getElementById('assignedGroupOptions');
  const hiddenInput = document.getElementById('assignedGroupFilter');
  // Botão 'Marcar todos' removido
  const btnClear = document.getElementById('assignedGroupClear');
  const searchInp = document.getElementById('assignedGroupSearch');
  function closePanel() { panel.classList.add('hidden'); toggleBtn.setAttribute('aria-expanded','false'); dd.dataset.open='false'; }
  function openPanel() { panel.classList.remove('hidden'); toggleBtn.setAttribute('aria-expanded','true'); dd.dataset.open='true'; searchInp && searchInp.focus(); }
  toggleBtn.addEventListener('click', (e)=>{ e.stopPropagation(); if (dd.dataset.open==='true') closePanel(); else openPanel(); });
  document.addEventListener('click', (e)=>{ if (!dd.contains(e.target)) closePanel(); });
  document.addEventListener('keydown', (e)=>{ if (e.key==='Escape') closePanel(); });
  function renderOptions(list) {
    optsBox.innerHTML='';
    list.forEach(item=>{
      const row=document.createElement('label'); row.className='chkdd-opt'; row.setAttribute('data-value', item.value);
      row.innerHTML=`<input type="checkbox" value="${escapeHtml(item.value)}" ${item.checked? 'checked':''}/> <span>${escapeHtml(item.label)}</span>`;
  if (item.checked) row.classList.add('is-checked');
      optsBox.appendChild(row);
    });
  }
  function updateToggleLabel() {
    const values = getAssignedGroupSelectedValues();
    if (!values.length || values.includes('todos')) { toggleBtn.textContent='Todos'; return; }
    if (values.length===1) { toggleBtn.textContent=findAssignedGroupLabel(values[0]) || '1 selecionado'; return; }
    toggleBtn.textContent = `${values.length} selecionados`;
  }
  function syncHiddenAndPersist(fireReload=true){
    const vals = getAssignedGroupSelectedValues();
    hiddenInput.value = vals.length? vals.join(',') : 'todos';
    updateToggleLabel();
    saveFilters();
    if (fireReload) {
      // debounce para permitir múltiplos cliques antes de recarregar
      if (window._assignedGroupReloadTimer) clearTimeout(window._assignedGroupReloadTimer);
      window._assignedGroupReloadTimer = setTimeout(()=> { loadData(); }, 450);
    }
  }
  optsBox.addEventListener('change', (e)=>{ 
    if (!e.target.matches('input[type="checkbox"]')) return; 
    const cb = e.target; 
    const val = cb.value; 
    const row = cb.closest('.chkdd-opt'); if (row) { if (cb.checked) row.classList.add('is-checked'); else row.classList.remove('is-checked'); }
    if (val === 'todos') {
      // Novo comportamento: ao marcar explicitamente 'Todos', marcar todos os demais checkboxes
      if (cb.checked) {
        const all = optsBox.querySelectorAll('input[type="checkbox"]');
        all.forEach(x => { x.checked = true; const r = x.closest('.chkdd-opt'); r && r.classList.add('is-checked'); });
        // segue para persistência (não remove 'todos' aqui; função de coleta filtrará se necessário)
        syncHiddenAndPersist();
        return; // já sincronizado
      }
      // Se usuário desmarca "Todos" e não há outros, mantém todos selecionados como default
      if (!cb.checked) {
        const any = [...optsBox.querySelectorAll('input[type="checkbox"]')].some(x=> x.value !== 'todos' && x.checked);
        if (!any) { cb.checked = true; row && row.classList.add('is-checked'); }
      }
    } else {
      // Se marcou outro e 'todos' está marcado, apenas remove 'todos' da seleção (mas não força única seleção)
      if (cb.checked) {
        const todosCb = optsBox.querySelector('input[type="checkbox"][value="todos"]');
        if (todosCb && todosCb.checked) { todosCb.checked = false; const tr = todosCb.closest('.chkdd-opt'); tr && tr.classList.remove('is-checked'); }
      } else {
        // Se desmarcou e não restou nenhum, reativa 'todos'
        const any = [...optsBox.querySelectorAll('input[type="checkbox"]')].some(x=> x.value !== 'todos' && x.checked);
        if (!any) {
          const todosCb = optsBox.querySelector('input[type="checkbox"][value="todos"]');
          if (todosCb) { todosCb.checked = true; const tr = todosCb.closest('.chkdd-opt'); tr && tr.classList.add('is-checked'); }
        }
      }
    }
    syncHiddenAndPersist();
  });
  btnClear && btnClear.addEventListener('click', ()=>{
    const all = optsBox.querySelectorAll('input[type="checkbox"]');
    let todosCb = null;
    all.forEach(cb=> {
      const row = cb.closest('.chkdd-opt');
      if (cb.value === 'todos') { todosCb = cb; }
      cb.checked = false; row && row.classList.remove('is-checked');
    });
    if (todosCb) { todosCb.checked = true; const tr = todosCb.closest('.chkdd-opt'); tr && tr.classList.add('is-checked'); }
    syncHiddenAndPersist(); // hiddenInput recebe 'todos'
  });
  searchInp && searchInp.addEventListener('input', ()=>{
    const q = searchInp.value.toLowerCase();
    optsBox.querySelectorAll('.chkdd-opt').forEach(row=>{
      const txt = row.textContent.toLowerCase();
      row.style.display = txt.includes(q)? '' : 'none';
    });
  });
  // Expor funções globais usadas quando dados chegam do backend
  window._assignedGroupDropdown = {
    populate(data, selectedValues){
      // data: array {value,label}; selectedValues: array de valores previamente escolhidos
      let restore = Array.isArray(selectedValues) && selectedValues.length ? selectedValues : (window._pendingAssignedGroupRestore || []);
      // Se restore incluir 'todos' ignore outros
      if (restore.includes('todos')) restore = ['todos'];
      const list = data.map(d=> ({...d, checked: restore.length ? restore.includes(d.value) : d.value==='todos'}));
  renderOptions(list);
  updateToggleLabel();
    },
    rebuildSelection(){ updateToggleLabel(); }
  };
}
function findAssignedGroupLabel(value){
  const row = document.querySelector(`.chkdd-opt[data-value="${CSS.escape(value)}"] span`);
  return row ? row.textContent : value;
}
function getAssignedGroupSelectedValues(){
  const cbs = document.querySelectorAll('#assignedGroupOptions input[type="checkbox"]');
  if (!cbs.length) return [];
  let vals = [...cbs].filter(cb=> cb.checked).map(cb=> cb.value);
  if (vals.includes('todos') && vals.length > 1) {
    // se "todos" está junto com outros, removemos para enviar lista explícita
    vals = vals.filter(v=> v !== 'todos');
  }
  return vals.length ? vals : ['todos'];
}
window.addEventListener('DOMContentLoaded', initAssignedGroupDropdown);
// Recarregar ao mudar status
window.addEventListener('DOMContentLoaded', () => {
  const sf = document.getElementById('statusFilter');
  if (sf) {
    sf.addEventListener('change', () => { saveFilters(); loadData(); });
  }
});
const Loader = {
  el: null,
  init() { this.el = document.getElementById('loader'); },
  show(msg) { if (this.el) { this.el.querySelector('.msg').textContent = msg || 'Carregando...'; this.el.classList.remove('hidden'); } },
  hide() { if (this.el) this.el.classList.add('hidden'); }
};
const Toasts = {
  el: null,
  init() { this.el = document.getElementById('toasts'); },
  push(kind, text, timeout = 4000) {
    if (!this.el) return;
    const d = document.createElement('div');
    d.className = `toast ${kind}`;
    d.textContent = text;
    this.el.appendChild(d);
    setTimeout(() => { d.remove(); }, timeout);
  }
};
window.addEventListener('DOMContentLoaded', () => { Loader.init(); Toasts.init(); });
// Bind core filter change events (gran, cat, group, dates) to auto save + reload
window.addEventListener('DOMContentLoaded', () => {
  const bindIds = ['gran','catFilter','start','end','startMonth','endMonth'];
  bindIds.forEach(id => {
    const el = document.getElementById(id);
    if (el && !el._bindReload) {
      el.addEventListener('change', () => { saveFilters(); loadData(); });
      el._bindReload = true;
    }
  });
});

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
    { id: 'resolvedToday', cols: 8, rows: 8, visible: true },
    { id: 'updatedToday', cols: 8, rows: 8, visible: true },
  { id: 'category', cols: 8, rows: 8, visible: true }
    , { id: 'load_by_group', cols: 8, rows: 8, visible: true }
    , { id: 'resolutionHours', cols: 8, rows: 8, visible: true }
    , { id: 'slaBuckets', cols: 8, rows: 8, visible: true }

  ].map((w, i) => ({ ...w, order: i }));
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
  // Migração: remover widgets obsoletos 'priority' e 'impact'
      try {
        if (Array.isArray(raw)) {
          for (let i = raw.length - 1; i >= 0; i--) {
    if (raw[i] && (raw[i].id === 'priority' || raw[i].id === 'impact')) raw.splice(i, 1);
          }
        }
      } catch { /* noop */ }
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
    let x = 0, y = 0, rowH = 0;
    let COLS = MAX_COLS;
    try {
      // If no stored layout yet, adapt maximum columns to current viewport width
      const hasStored = !!localStorage.getItem(STORAGE_KEY);
      if (!hasStored) {
        const snapW = CELL_W / 2; // width of one logical column in px
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
    let changed = false;
    layout.forEach(w => { if (w.x == null || w.y == null) { changed = true; } });
    if (changed) assignInitialCoords(layout); // assigns 3x3 only for missing coords/sizes
    // Clamp & sanity
    layout.forEach(w => { w.cols = Math.max(3, w.cols || 3); w.rows = Math.max(3, w.rows || 3); });
  }
  function apply(layout) {
    const grid = document.querySelector('.grid');
    const map = new Map(layout.map(w => [w.id, w]));
    DEFAULT.forEach(def => { if (!map.has(def.id)) { layout.push({ ...def }); map.set(def.id, def); } });
    ensureAllHaveCoords(layout);
    grid.classList.add('free-layout');
    if (DEV_SHOW_GRID) { grid.classList.add('dev-grid'); grid.style.setProperty('--cell-w', (CELL_W / 2) + 'px'); grid.style.setProperty('--cell-h', (CELL_H / 2) + 'px'); } else { grid.classList.remove('dev-grid'); }
    const SNAP_W = CELL_W / 2; // snap unit
    const SNAP_H = CELL_H / 2;
    document.querySelectorAll('.card[data-widget]').forEach(el => {
      const id = el.getAttribute('data-widget');
      const w = map.get(id);
      if (!w || w.visible === false) { el.style.display = 'none'; return; } else el.style.display = '';
      el.style.position = 'absolute';
      // Ajusta larg/alt e posição com espaçamento interno (gap) sem alterar cálculo de maxRight/maxBottom
      const calcW = (w.cols * SNAP_W) - (CARD_GAP * 2);
      const calcH = (w.rows * SNAP_H) - (CARD_GAP * 2);
      el.style.width = (calcW > 20 ? calcW : (w.cols * SNAP_W)) + 'px';
      el.style.height = (calcH > 20 ? calcH : (w.rows * SNAP_H)) + 'px';
      el.style.left = (w.x * SNAP_W + CARD_GAP) + 'px';
      el.style.top = (w.y * SNAP_H + CARD_GAP) + 'px';
    });
    const maxBottom = layout.filter(w => w.visible !== false).reduce((m, w) => Math.max(m, (w.y + w.rows) * SNAP_H + CARD_GAP), 0);
    // Calcula a largura máxima usada (extremo direito dos cards visíveis)
    const maxRight = layout.filter(w => w.visible !== false).reduce((m, w) => Math.max(m, (w.x + w.cols) * SNAP_W + CARD_GAP), 0);
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
        // Captura e remove botão de ajuda existente no header (para reposicionar)
        let oldHelp = card.querySelector('h2 button.help');
        let helpTitle = oldHelp ? (oldHelp.getAttribute('title') || 'Ajuda') : 'Ajuda';
        if (oldHelp) oldHelp.remove();
        // Captura badge-period se estiver no h2 e move para a barra
        let badge = card.querySelector('h2 .badge-period');
        if (badge) { badge.remove(); }
        const leftBox = document.createElement('div');
        leftBox.className = 'actions-left';
        if (badge) leftBox.appendChild(badge); else {
          // se widget é um dos que ignoram período mas span não existe (caso dinâmico) cria
          if ((lastMeta && Array.isArray(lastMeta.ignore_period_widgets) && lastMeta.ignore_period_widgets.includes(card.getAttribute('data-widget')))) {
            const b = document.createElement('span'); b.className = 'badge-period'; b.title = 'Ignora filtro de período'; leftBox.appendChild(b);
          }
        }
        const helpBtn = document.createElement('button');
        helpBtn.className = 'help';
        helpBtn.type = 'button';
        helpBtn.setAttribute('title', helpTitle);
        helpBtn.setAttribute('aria-label', 'Ajuda');
        helpBtn.textContent = '?';
        const closeBtn = document.createElement('button');
        closeBtn.dataset.act = 'hide';
        closeBtn.title = 'Ocultar';
        closeBtn.setAttribute('aria-label', 'Ocultar');
        closeBtn.style.fontWeight = '700';
        closeBtn.style.lineHeight = '1';
        closeBtn.textContent = '×';
        act.appendChild(leftBox);
        const rightBox = document.createElement('div');
        rightBox.style.display = 'flex';
        rightBox.style.gap = '6px';
        rightBox.appendChild(helpBtn);
        rightBox.appendChild(closeBtn);
        act.appendChild(rightBox);
        card.appendChild(act);
        act.addEventListener('click', (e) => {
          const btn = e.target.closest('button'); if (!btn) return;
          const id = card.getAttribute('data-widget');
          const item = layout.find(x => x.id === id); if (!item) return;
          if (btn.dataset.act === 'hide') { item.visible = false; save(layout); apply(layout); Toasts.push('info', 'Widget ocultado: ' + id); }
        });
        // Reaplica comportamento de popover de ajuda no novo botão
        try { attachHelpPopovers && attachHelpPopovers(); } catch { }
      }
  // Multi-edge / corner resize (remove handle; detect edges by proximity)
      if (!card._resizeBound) {
        initMultiResize(card, layout);
        card._resizeBound = true;
      }
  // Drag init only if not yet bound to widget-actions
  if (card.dataset.dragHandle !== 'widget-actions') { initDrag(card, layout); }
    });
  }
  function initMultiResize(card, layout) {
    const EDGE = 8; // px detection zone
    const id = card.getAttribute('data-widget');
    let resizing = false; let region = ''; let startX = 0, startY = 0; let startW = 0, startH = 0; let startCols = 0, startRows = 0; let startGridX = 0, startGridY = 0;
    function detectRegion(e) {
      const r = card.getBoundingClientRect();
      const x = e.clientX - r.left; const y = e.clientY - r.top;
      const left = x <= EDGE; const right = (r.width - x) <= EDGE; const top = y <= EDGE; const bottom = (r.height - y) <= EDGE;
      let reg = '';
      if (top && left) reg = 'nw'; else if (top && right) reg = 'ne'; else if (bottom && left) reg = 'sw'; else if (bottom && right) reg = 'se';
      else if (top) reg = 'n'; else if (bottom) reg = 's'; else if (left) reg = 'w'; else if (right) reg = 'e';
      return reg;
    }
    function regionCursor(reg) {
      switch (reg) {
        case 'n': case 's': return 'ns-resize';
        case 'e': case 'w': return 'ew-resize';
        case 'ne': case 'sw': return 'nesw-resize';
        case 'nw': case 'se': return 'nwse-resize';
        default: return '';
      }
    }
    card.addEventListener('mousemove', e => {
      if (resizing) return; // keep cursor during resize
      const reg = detectRegion(e);
      region = reg;
      const cur = regionCursor(reg);
      card.style.cursor = cur || '';
      card.dataset.resizeRegion = reg;
    });
    card.addEventListener('mouseleave', () => { if (!resizing) { card.style.cursor = ''; region = ''; } });
    // Support pointer events + touch fallback for resize start so mobile users can resize by touch
    function startResizeFromEvent(e) {
      // Normalize touch event to have clientX/clientY
      let cx = e.clientX, cy = e.clientY;
      if (e.type === 'touchstart' && e.touches && e.touches[0]) { cx = e.touches[0].clientX; cy = e.touches[0].clientY; }
      // If mouse, require left button
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      // only start if on edge region (and not inside interactive header buttons)
      if (!region) return;
      const item = layout.find(x => x.id === id); if (!item) return;
      resizing = true; card.dataset.resizing = '1';
      e.stopPropagation();
      try { e.preventDefault(); } catch (err) {}
      startX = cx; startY = cy; startW = card.offsetWidth; startH = card.offsetHeight;
      startCols = item.cols; startRows = item.rows; startGridX = item.x; startGridY = item.y;
      const snapW = CELL_W / 2, snapH = CELL_H / 2;
      function move(ev) {
        let mvX = ev.clientX, mvY = ev.clientY;
        if (ev.type === 'touchmove' && ev.touches && ev.touches[0]) { mvX = ev.touches[0].clientX; mvY = ev.touches[0].clientY; }
        const dx = mvX - startX; const dy = mvY - startY;
        let dColsRight = 0, dRowsDown = 0, dColsLeft = 0, dRowsUp = 0;
        if (region.includes('e')) dColsRight = Math.round(dx / snapW);
        if (region.includes('s')) dRowsDown = Math.round(dy / snapH);
        if (region.includes('w')) dColsLeft = Math.round(-dx / snapW); // moving left increases width
        if (region.includes('n')) dRowsUp = Math.round(-dy / snapH);
        let newCols = startCols + dColsRight + dColsLeft; // dColsLeft acts like expansion
        let newRows = startRows + dRowsDown + dRowsUp;
        let newX = startGridX - dColsLeft;
        let newY = startGridY - dRowsUp;
        // clamp
        if (newX < 0) { newCols += newX; newX = 0; }
        if (newY < 0) { newRows += newY; newY = 0; }
        newCols = Math.max(3, newCols);
        newRows = Math.max(3, newRows);
        // apply tentative
        if (newCols !== item.cols || newRows !== item.rows || newX !== item.x || newY !== item.y) {
          item.cols = newCols; item.rows = newRows; item.x = newX; item.y = newY;
          apply(layout);
          // keep resizing flag on updated DOM card
          const fresh = document.querySelector(`.card[data-widget="${id}"]`);
          if (fresh) { fresh.dataset.resizing = '1'; fresh.style.cursor = regionCursor(region); }
        }
      }
      function up() {
        resizing = false; delete card.dataset.resizing; save(layout);
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        document.removeEventListener('touchmove', move, { passive: false });
        document.removeEventListener('touchend', up);
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        card.style.cursor = '';
      }
      // Attach appropriate move/up listeners for pointer/mouse/touch
      if (window.PointerEvent) {
        document.addEventListener('pointermove', move);
        document.addEventListener('pointerup', up);
      } else {
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
        document.addEventListener('touchmove', move, { passive: false });
        document.addEventListener('touchend', up);
      }
    }

    // Bind start event for resize using Pointer Events when available, otherwise mouse+touch
    if (window.PointerEvent) {
      card.addEventListener('pointerdown', startResizeFromEvent);
    } else {
      card.addEventListener('mousedown', startResizeFromEvent);
      card.addEventListener('touchstart', function (t) { try { t.preventDefault(); } catch (e) { } startResizeFromEvent(t); }, { passive: false });
    }
  }
  function initDrag(card, layout) {
    let startX, startY, origX, origY, previewX, previewY; const id = card.getAttribute('data-widget');
    const handle = card.querySelector('.widget-actions');
    if (!handle) return;
    handle.classList.add('drag-handle');
    card.dataset.dragHandle = 'widget-actions';
    // Use Pointer Events when available (unifies mouse/touch/stylus). Fallback to mouse+touch.
    handle.style.touchAction = handle.style.touchAction || 'none'; // prevent browser panning during touch drag
    function getClientFromEvent(ev) {
      if (!ev) return { clientX: 0, clientY: 0 };
      if (ev.touches && ev.touches[0]) return { clientX: ev.touches[0].clientX, clientY: ev.touches[0].clientY };
      return { clientX: ev.clientX, clientY: ev.clientY };
    }
    function onPointerDown(ev) {
      // If mouse, only left button
      if (ev.pointerType === 'mouse' && ev.button !== 0) return;
      if (ev.target && ev.target.closest('button')) return; // don't start drag when clicking icons
      if (card.dataset.resizing === '1' || card.dataset.resizeRegion) return;
      const item = layout.find(w => w.id === id); if (!item) return;
      const pt = getClientFromEvent(ev);
      startX = pt.clientX; startY = pt.clientY; origX = item.x || 0; origY = item.y || 0; previewX = origX; previewY = origY;
      card.classList.add('dragging'); document.body.classList.add('drag-mode'); card.style.zIndex = 999;
      function onMove(ev2) {
        try {
          const p = getClientFromEvent(ev2);
          const dx = p.clientX - startX, dy = p.clientY - startY; const snapW = CELL_W / 2, snapH = CELL_H / 2;
          const deltaCols = Math.round(dx / snapW), deltaRows = Math.round(dy / snapH);
          const newX = Math.max(0, origX + deltaCols), newY = Math.max(0, origY + deltaRows);
          if (newX !== previewX || newY !== previewY) { previewX = newX; previewY = newY; card.style.left = (previewX * snapW) + 'px'; card.style.top = (previewY * snapH) + 'px'; }
        } catch (err) { }
      }
      function onUp() {
        const item2 = layout.find(w => w.id === id); if (item2) { item2.x = previewX; item2.y = previewY; if (AUTO_RESOLVE) resolveCollisions(item2, layout); apply(layout); save(layout); }
        card.classList.remove('dragging'); document.body.classList.remove('drag-mode'); card.style.zIndex = '';
        if (window.PointerEvent) {
          document.removeEventListener('pointermove', onMove);
          document.removeEventListener('pointerup', onUp);
        } else {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.removeEventListener('touchmove', onMove, { passive: false });
          document.removeEventListener('touchend', onUp);
        }
      }
      if (window.PointerEvent) {
        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', onUp);
      } else {
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onUp);
      }
    }
    if (window.PointerEvent) {
      handle.addEventListener('pointerdown', onPointerDown);
    } else {
      handle.addEventListener('mousedown', onPointerDown);
      handle.addEventListener('touchstart', function (t) { try { t.preventDefault(); } catch (e) {} onPointerDown(t); }, { passive: false });
    }
  }
  function boxesOverlap(a, b) { return !(a.x + a.cols <= b.x || b.x + b.cols <= a.x || a.y + a.rows <= b.y || b.y + b.rows <= a.y); }
  function resolveCollisions(moved, layout) {
    let changed = true; let guard = 0; while (changed && guard < 50) {
      changed = false; guard++; for (const other of layout) {
        if (other === moved || other.visible === false) continue; if (boxesOverlap(moved, other)) { // push other down
          other.y = moved.y + moved.rows; changed = true;
        }
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
      // Provide explicit X/Y coordinate inputs (grid units) so keyboard-only users can position widgets.
      const curX = (typeof w.x === 'number') ? w.x : (w.x || 0);
      const curY = (typeof w.y === 'number') ? w.y : (w.y || 0);
      row.innerHTML = `<td>${w.id}</td><td><input type="checkbox" data-f="vis" ${w.visible !== false ? 'checked' : ''}></td>
        <td>
          X:<input data-f="x" type="number" min="0" value="${curX}" style="width:60px"> 
          Y:<input data-f="y" type="number" min="0" value="${curY}" style="width:60px"> 
          L:<input data-f="cols" type="number" min="3" max="${MAX_COLS}" value="${w.cols || (w.width || 1) * 3}" style="width:60px"> 
          H:<input data-f="rows" type="number" min="3" max="60" value="${w.rows || (w.height || 1) * 3}" style="width:60px">
        </td>`;
      row.querySelectorAll('input,select').forEach(inp => {
        inp.addEventListener('change', () => {
          const f = inp.dataset.f;
          if (f === 'vis') {
            w.visible = inp.checked;
          } else if (f === 'cols') {
            w.cols = Math.min(MAX_COLS, Math.max(3, parseInt(inp.value) || 3));
          } else if (f === 'rows') {
            w.rows = Math.max(3, parseInt(inp.value) || 3);
          } else if (f === 'x') {
            let v = parseInt(inp.value);
            if (isNaN(v) || v < 0) v = 0;
            w.x = v;
          } else if (f === 'y') {
            let v2 = parseInt(inp.value);
            if (isNaN(v2) || v2 < 0) v2 = 0;
            w.y = v2;
          }
          save(layout); apply(layout);
        });
      });
      tbody.appendChild(row);
    });
    // Definir tamanho inicial apenas na primeira abertura (se ainda não customizado pelo usuário)
    if (!panel.dataset.initedSize) {
      try {
        panel.style.width = Math.round(window.innerWidth * 0.5) + 'px';
        panel.style.height = Math.round(window.innerHeight * 0.8) + 'px';
        panel.dataset.initedSize = '1';
      } catch { }
    }
    panel.classList.remove('hidden');
    initLayoutTabs();
    // ao abrir, garantir SLA carregada se já temos baseline_titles em lastMeta (chamado após loadData)
    if (window._lastBaselineTitlesDetail) buildSlaTable(window._lastBaselineTitlesDetail);
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
      document.querySelectorAll('.card[data-widget]').forEach(c => { if (!c.dataset.dragInit) { initDrag(c, layout); c.dataset.dragInit = '1'; } });
      Toasts.push('success', 'Layout redefinido');
      // width recalibration
      try { const header = document.querySelector('header'); const controls = document.querySelector('.controls'); if (header) header.style.minWidth = ''; if (controls) controls.style.minWidth = ''; } catch { }
      // Removido: chamada a adjustHeaderWidth inexistente que causava ReferenceError após redefinir layout.
      // Se no futuro for reintroduzida uma função global adjustHeaderWidth, esta verificação segura a execução.
      requestAnimationFrame(() => requestAnimationFrame(() => { try { if (typeof adjustHeaderWidth === 'function') adjustHeaderWidth(); } catch (e) { /* noop */ } }));
      // Também redefinir filtros para valores originais
      resetFilters();
    });
    // Export / Import setup handlers
    const exportBtn = document.getElementById('exportSetupBtn');
    const importBtn = document.getElementById('importSetupBtn');
    const importFile = document.getElementById('importSetupFile');
    if (exportBtn) exportBtn.addEventListener('click', () => {
      try {
        const payload = buildFullSetupSnapshot();
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'glpi_dashboard_setup.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
        Toasts.push('success', 'Setup exportado');
      } catch (e) { Toasts.push('error', 'Falha ao exportar setup'); }
    });
    if (importBtn && importFile) importBtn.addEventListener('click', () => importFile.click());
    if (importFile) importFile.addEventListener('change', async (e) => {
      const f = e.target.files && e.target.files[0]; if (!f) return; try {
        const txt = await f.text(); const obj = JSON.parse(txt);
        applyImportedSetup(obj);
        Toasts.push('success', 'Setup importado');
      } catch (err) { Toasts.push('error', 'Arquivo inválido'); }
      importFile.value = '';
    });
  }
  return { init };
})();
window.addEventListener('DOMContentLoaded', () => WidgetLayout.init());

// ---- Abas do painel de layout (Layout / Dados / SLA) ----
function initLayoutTabs() {
  const tabs = document.querySelectorAll('#layoutPanel .lp-tab');
  const panes = document.querySelectorAll('#layoutPanel .lp-pane');
  if (!tabs.length) return;
  tabs.forEach(tab => {
    if (tab._tabBound) return; tab._tabBound = true;
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.dataset.tab;
      panes.forEach(p => {
        if (p.dataset.pane === target) p.classList.remove('hidden'); else p.classList.add('hidden');
      });
      // lazy build SLA table if switching to sla
      if (target === 'sla' && window._lastBaselineTitlesDetail) buildSlaTable(window._lastBaselineTitlesDetail);
    });
  });
}

// ---- SLA por título (inputs) ----
const SLA_TITLES_KEY = 'glpiDashboardSlaTitles.v1';
let _slaTitlesCache = null;
function loadSlaTitleConfig() {
  if (_slaTitlesCache) return _slaTitlesCache;
  try { _slaTitlesCache = JSON.parse(localStorage.getItem(SLA_TITLES_KEY) || '{}') || {}; } catch { _slaTitlesCache = {}; }
  return _slaTitlesCache;
}
function saveSlaTitleConfig() {
  try { localStorage.setItem(SLA_TITLES_KEY, JSON.stringify(_slaTitlesCache || {})); } catch { }
}
let _slaSort = { key: 'title', dir: 'asc' };
function buildSlaTable(detailList) {
  const tb = document.getElementById('slaTitleRows');
  const table = tb ? tb.closest('table') : null;
  if (!tb) return;
  if (!Array.isArray(detailList)) { tb.innerHTML = '<tr><td colspan="5">Sem dados de baseline.</td></tr>'; return; }
  const cfg = loadSlaTitleConfig();
  if (!detailList.length) { tb.innerHTML = '<tr><td colspan="5">Nenhum título encontrado nos últimos 6 meses.</td></tr>'; return; }
  // Ordenar
  const data = detailList.slice().sort((a, b) => {
    const k = _slaSort.key; const dir = _slaSort.dir === 'asc' ? 1 : -1;
    let va = a[k] || ''; let vb = b[k] || '';
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return -1 * dir; if (va > vb) return 1 * dir; return 0;
  });
  const rowsHtml = data.map(obj => {
    const title = obj.title;
    const category = obj.category || '';
    const rec = cfg[title] || {};
    const n = rec.normal != null ? rec.normal : '';
    const m = rec.moderate != null ? rec.moderate : '';
    const c = rec.critical != null ? rec.critical : '';
    return `<tr data-title="${escapeHtml(title)}" data-category="${escapeHtml(category)}">
      <td style="font-size:12px;">${escapeHtml(category)}</td>
      <td style="font-size:12px;">${escapeHtml(title)}</td>
      <td><input type="number" min="0" data-f="normal" value="${n}" /></td>
      <td><input type="number" min="0" data-f="moderate" value="${m}" /></td>
      <td><input type="number" min="0" data-f="critical" value="${c}" /></td></tr>`;
  }).join('');
  tb.innerHTML = rowsHtml;
  tb.querySelectorAll('input').forEach(inp => {
    if (inp._slaBound) return; inp._slaBound = true;
    inp.addEventListener('change', () => {
      const tr = inp.closest('tr'); if (!tr) return;
      const title = tr.getAttribute('data-title'); if (!title) return;
      const field = inp.dataset.f;
      const val = inp.value === '' ? undefined : (isNaN(parseInt(inp.value)) ? undefined : parseInt(inp.value));
      if (!cfg[title]) cfg[title] = {};
      if (val == null) delete cfg[title][field]; else cfg[title][field] = val;
      if (Object.keys(cfg[title]).length === 0) delete cfg[title];
      _slaTitlesCache = cfg; saveSlaTitleConfig();
    });
  });
  // Cabeçalho sort + resize
  if (table && !table._slaHeadEnhanced) {
    table._slaHeadEnhanced = true;
    const headCells = table.querySelectorAll('thead th');
    const mapKeys = ['category', 'title', 'normal', 'moderate', 'critical'];
    headCells.forEach((th, idx) => {
      // adicionar resizer
      const rz = document.createElement('div'); rz.className = 'col-resizer'; th.appendChild(rz);
      let startX, startW;
      rz.addEventListener('mousedown', e => {
        e.preventDefault(); startX = e.clientX; startW = th.offsetWidth;
        function move(ev) { const dx = ev.clientX - startX; const nw = Math.max(60, startW + dx); th.style.width = nw + 'px'; }
        function up() { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
        document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
      });
      // sort (somente categoria e título por enquanto; tempos ordenam numericamente se existirem)
      th.addEventListener('click', (ev) => {
        if (ev.target === rz) return; // ignore click on resizer
        const key = mapKeys[idx]; if (!key) return;
        if (_slaSort.key === key) { _slaSort.dir = _slaSort.dir === 'asc' ? 'desc' : 'asc'; } else { _slaSort.key = key; _slaSort.dir = 'asc'; }
        // limpar classes
        headCells.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
        th.classList.add(_slaSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        // reconstruir tabela usando cache de detalhes
        if (window._lastBaselineTitlesDetail) buildSlaTable(window._lastBaselineTitlesDetail);
      });
    });
  } else if (table) {
    // atualizar estado visual do sort
    const headCells = table.querySelectorAll('thead th');
    headCells.forEach((th, idx) => {
      const key = ['category', 'title', 'normal', 'moderate', 'critical'][idx];
      th.classList.remove('sort-asc', 'sort-desc');
      if (key === _slaSort.key) th.classList.add(_slaSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    });
  }
}

// Removido openLocalSlaModal: usamos modal padrão via /api/tickets com ids
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
  const rtd = document.getElementById('resolvedTodayValue');
  if (rtd) {
    rtd.style.cursor = 'pointer';
    rtd.addEventListener('click', () => openTicketsModal('resolved_today', 'Resolvidos Hoje'));
  }
  const upd = document.getElementById('updatedTodayValue');
  if (upd) {
    upd.style.cursor = 'pointer';
    upd.addEventListener('click', () => openTicketsModal('updated_today', 'Atualizados Hoje'));
  }
});

// ---- Month range controls for "Mensal" granularity ----
function initMonthSelectors() {
  const startMonth = document.getElementById('startMonth');
  const endMonth = document.getElementById('endMonth');
  if (!startMonth || !endMonth) return;
  const now = new Date();
  const ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
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
            footer: function (tooltipItems) {
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
            footer: function (tooltipItems) {
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

// Novo: gráfico de barras empilhadas
function stackedBarChart(canvasId, stackedSeries, help) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (charts[canvasId]) charts[canvasId].destroy();
  const labels = stackedSeries.labels || [];
  const datasetsRaw = stackedSeries.datasets || [];
  // Paleta de cores consistente (extendida se necessário)
  const palette = [
    '#1d4ed8', '#059669', '#f59e0b', '#dc2626', '#7c3aed', '#0ea5e9', '#10b981', '#6366f1', '#ef4444', '#14b8a6'
  ];
  const datasets = datasetsRaw.map((d, i) => ({
    label: d.label,
    data: d.data,
    backgroundColor: palette[i % palette.length],
    borderColor: palette[i % palette.length],
    borderWidth: 1,
    stack: 'status'
  }));
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      resizeDelay: 200,
      scales: { x: { stacked: true }, y: { beginAtZero: true, stacked: true } },
      plugins: {
        tooltip: {
          callbacks: {
            footer: function (items) {
              // Somatório total daquela barra
              if (!items || !items.length) return '';
              const total = items.reduce((acc, it) => acc + (it.parsed.y || 0), 0);
              return `Total: ${total}` + (help ? `\n${help}` : '');
            }
          }
        },
        legend: { position: 'bottom' }
      }
    }
  });
}

function destroyChart(id) {
  if (charts[id]) {
    try { charts[id].destroy(); } catch (e) { }
    delete charts[id];
  }
  const cv = document.getElementById(id);
  if (cv && cv.getContext) {
    try { const g = cv.getContext('2d'); g && g.clearRect(0, 0, cv.width, cv.height); } catch (e) { }
  }
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
  const lastDay = new Date(ey, emon, 0); // (ano, mês final, dia 0) => último dia do mês final
  endNorm = isoDate(lastDay);
    } else {
      const start = document.getElementById('start').value;
      const end = document.getElementById('end').value;
      startNorm = start;
      endNorm = end;
    }

    const catSel = document.getElementById('catFilter').value;
  let assignedList = 'todos';
  const selectedGroups = getAssignedGroupSelectedValues();
  if (selectedGroups && selectedGroups.length && !selectedGroups.includes('todos')) assignedList = selectedGroups.join(',');
    const statusSel = (document.getElementById('statusFilter') && document.getElementById('statusFilter').value) || 'todos';
    const r = await fetch(`/api/data?gran=${encodeURIComponent(gran)}&start=${startNorm}&end=${endNorm}&cat=${encodeURIComponent(catSel)}&assigned_group=${encodeURIComponent(assignedList)}&status=${encodeURIComponent(statusSel)}`);
    let js = null;
    try { js = await r.clone().json(); } catch { /* ignore parse errors */ }
    if (r.status === 503) {
      const friendly = (js && (js.mensagem || js.message)) || 'Serviço temporariamente indisponível.';
      Toasts.push('error', friendly);
      return; // encerra sem lançar erro técnico
    }
    if (!r.ok) {
      const msg = (js && (js.mensagem || js.message || js.error)) || `Falha (HTTP ${r.status})`;
      throw new Error(msg);
    }
    if (js && js.error) throw new Error(js.error);

    if (Array.isArray(js.baseline_titles_detail)) {
      window._lastBaselineTitlesDetail = js.baseline_titles_detail;
      window._lastBaselineTitles = js.baseline_titles_detail.map(o => o.title);
      const activeSla = document.querySelector('#layoutPanel .lp-tab.active[data-tab="sla"]');
      if (activeSla) buildSlaTable(js.baseline_titles_detail);
    } else if (Array.isArray(js.baseline_titles)) {
      // fallback (sem detalhe de categoria)
      window._lastBaselineTitles = js.baseline_titles;
      window._lastBaselineTitlesDetail = js.baseline_titles.map(t => ({ title: t, category: '' }));
      const activeSla = document.querySelector('#layoutPanel .lp-tab.active[data-tab="sla"]');
      if (activeSla) buildSlaTable(window._lastBaselineTitlesDetail);
    }

    // SLA Buckets (3 níveis) usando thresholds configurados localmente
    try {
      const tickets = Array.isArray(js.tickets_sla) ? js.tickets_sla : [];
      // Função para calcular diferença em dias úteis (pode retornar fração, descontando fins de semana)
      function businessDaysDiff(start, end) {
        if (!start || !end || end <= start) return 0;
        const msDay = 86400000;
        let cur = new Date(start.getFullYear(), start.getMonth(), start.getDate(), start.getHours(), start.getMinutes(), start.getSeconds());
        let totalMs = 0;
        while (cur < end) {
          const next = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() + 1);
          const segEnd = next < end ? next : end;
          const dow = cur.getDay();
          if (dow !== 0 && dow !== 6) { // Mon-Fri
            totalMs += (segEnd - cur);
          }
          cur = next;
        }
        return totalMs / msDay;
      }
      window._ticketsSlaRaw = tickets; // cache
      const cfg = loadSlaTitleConfig();
      const nowIso = new Date();
      const buckets = { normal: [], moderado: [], critico: [] };
      tickets.forEach(t => {
        const title = t.title || ''; if (!title) return;
        const conf = cfg[title] || {}; // {normal, moderate, critical}
        // thresholds (dias) convertidos para números
        const thNorm = Number.isFinite(conf.normal) ? conf.normal : (conf.normal != null ? parseInt(conf.normal) : undefined);
        const thMod = Number.isFinite(conf.moderate) ? conf.moderate : (conf.moderate != null ? parseInt(conf.moderate) : undefined);
        const thCrit = Number.isFinite(conf.critical) ? conf.critical : (conf.critical != null ? parseInt(conf.critical) : undefined);
        // calcular idade em dias (se resolvido usar solved_at, senão now)
        const created = t.created_at ? new Date(t.created_at) : null;
        if (!created || isNaN(created.getTime())) return;
        const solved = t.solved_at ? new Date(t.solved_at) : null;
        const effectiveEnd = solved && !isNaN(solved.getTime()) ? solved : nowIso;
        const ageDays = businessDaysDiff(created, effectiveEnd); // dias úteis (fração)
        // classificação
        if (thNorm != null && ageDays <= thNorm) { buckets.normal.push(t); return; }
        if (thMod != null && ageDays <= thMod) { buckets.moderado.push(t); return; }
        // Critico: acima dos limites anteriores e com threshold crítico definido
        if (thCrit != null) { buckets.critico.push(t); return; }
        if (thNorm == null && thMod == null && thCrit == null) return; // sem config => ignora
        // Caso sem crítico definido mas passou moderado => classifica como crítico lógico
        buckets.critico.push(t);
      });
      // montar gráfico
      const labelsSla = ['Normal', 'Moderado', 'Crítico'];
      const dataSla = [buckets.normal.length, buckets.moderado.length, buckets.critico.length];
      if (labelsSla.some((_, i) => dataSla[i] > 0)) {
        barChart('chartSlaBuckets', labelsSla, dataSla, 'Expectativa', 'Tickets em aberto (não resolvidos) por faixa de SLA (dias úteis; ignora filtro de período) conforme limites configurados por título nos últimos 6 meses.');
        // clique -> modal local com tickets (sem nova chamada API)
        const canvas = document.getElementById('chartSlaBuckets');
        if (canvas) {
          canvas.onclick = (evt) => {
            const chart = charts['chartSlaBuckets'];
            if (!chart) return;
            const points = chart.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true);
            if (!points.length) return;
            const idx = points[0].index;
            const key = ['normal', 'moderado', 'critico'][idx];
            const arr = buckets[key] || [];
            const human = key === 'normal' ? 'Normal' : key === 'moderado' ? 'Moderado' : 'Crítico';
            const ids = arr.map(t => t.id).filter(x => x != null);
            if (!ids.length) return;
            openTicketsModal('ids', human, ids);
          };
        }
        // guardar para refresh (ex: se thresholds mudarem -> reconstruir manual depois)
        window._slaBucketsCache = { buckets, labels: labelsSla, data: dataSla };
      } else {
        destroyChart('chartSlaBuckets');
      }
    } catch (e) { console.warn('SLA buckets error', e); }
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
    if (typeof js.resolved_today === 'number') {
      const el3 = document.getElementById('resolvedTodayValue');
      if (el3) el3.textContent = js.resolved_today.toLocaleString('pt-BR');
    }
    if (typeof js.updated_today === 'number') {
      const el4 = document.getElementById('updatedTodayValue');
      if (el4) el4.textContent = js.updated_today.toLocaleString('pt-BR');
    }

    const s = js.series || {};
    lastSeries = s;
    // Populate checkbox dropdown for assigned groups
    try {
      if (js.assigned_groups && window._assignedGroupDropdown) {
        const currentSel = getAssignedGroupSelectedValues();
        const raw = js.assigned_groups.map(g=> ({ id: g.id, name: (g.name||'').trim() }));
        const aguard = raw.find(g=> g.name.toLowerCase() === 'aguardando aprovação');
        const exclude = new Set(['suporte holding']);
        const remaining = raw.filter(g=> !exclude.has(g.name.toLowerCase()) && g.name.toLowerCase() !== 'aguardando aprovação')
          .sort((a,b)=> a.name.localeCompare(b.name));
        const data = [
          { value:'todos', label:'Todos' },
          { value:'Holding', label:'Holding' },
          { value:'Unimed', label:'Unimed' },
          ...(aguard? [{ value:'Aguardando Aprovação', label:'Aguardando Aprovação'}]:[]),
          ...remaining.map(g=> ({ value:String(g.id), label:g.name }))
        ];
        window._assignedGroupDropdown.populate(data, currentSel);
      }
    } catch(e) { /* ignore */ }
    // Line charts
    if (s.created && s.resolved && s.created.data && s.resolved.data && s.created.data.length && s.resolved.data.length && document.getElementById('chartCumGap')) {
      const cumCreated = []; const cumResolved = []; const gap = [];
      let accC = 0, accR = 0;
      for (let i = 0; i < s.created.data.length; i++) {
        const vC = Number(s.created.data[i] || 0);
        const vR = Number(s.resolved.data[i] || 0);
        accC += vC; accR += vR; cumCreated.push(accC); cumResolved.push(accR); gap.push(accC - accR);
      }
      if (charts['chartCumGap']) charts['chartCumGap'].destroy();
      charts['chartCumGap'] = new Chart(document.getElementById('chartCumGap'), {
        type: 'line',
        data: {
          labels: s.created.labels, datasets: [
            { label: 'Criados (Acum.)', data: cumCreated, borderColor: '#1d4ed8', backgroundColor: 'rgba(29,78,216,0.15)', tension: 0.15, help: 'Acumulado de tickets criados desde o início do período selecionado.' },
            { label: 'Resolvidos (Acum.)', data: cumResolved, borderColor: '#059669', backgroundColor: 'rgba(5,150,105,0.15)', tension: 0.15, help: 'Acumulado de tickets resolvidos desde o início do período selecionado.' },
            { label: 'Gap Cumulativo (Criados - Resolvidos)', data: gap, borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,0.15)', tension: 0.15, help: 'Diferença acumulada entre tickets criados e resolvidos; valores positivos indicam aumento do backlog.' }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false, resizeDelay: 200,
          interaction: { mode: 'nearest', intersect: false },
          scales: { y: { beginAtZero: true } },
          plugins: {
            tooltip: {
              callbacks: {
                label: ctx => {
                  const dsLabel = ctx.dataset.label || ''; return `${dsLabel}: ${ctx.parsed.y}`;
                }, footer: function (items) { try { const ds = this.chart.data.datasets[items[0].datasetIndex]; return ds && ds.help ? ds.help : ''; } catch (e) { return ''; } }
              }
            }
          }
        }
      });
      attachPointClick('chartCumGap', s.created.labels, ['created', 'resolved']);
    } else { destroyChart('chartCumGap'); }
    // Unified Backlog widget: combined canvas with toggle between raw backlog and smoothed trend
    if (s.backlog && s.backlog.data && s.backlog.data.length) {
      const labels = (s.backlog && s.backlog.labels && s.backlog.labels.length) ? s.backlog.labels : (s.backlog_trend.labels || []);
      const rawData = (s.backlog && s.backlog.data) ? s.backlog.data : [];
      const smoothData = (s.backlog_trend && s.backlog_trend.data) ? s.backlog_trend.data : [];

      const datasets = [
        { label: 'Backlog (Tendência)', data: rawData, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', tension: 0.2, help: 'Número de tickets em aberto por ponto do período (valor bruto).' },
        { label: 'Backlog (Suavizado)', data: smoothData, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.15)', tension: 0.25, help: 'Série suavizada para destacar a tendência do backlog ao longo do tempo.' }
      ];

      lineChart('chartBacklogCombined', labels, datasets);
      attachPointClick('chartBacklogCombined', labels, ['backlog']);
    } else { destroyChart('chartBacklogCombined'); }

    // Bar charts
    if (s.backlog_status && s.backlog_status.data && s.backlog_status.data.length) { barChart('chartBacklogStatus', s.backlog_status.labels, s.backlog_status.data, 'Status', 'Distribuição atual dos tickets em aberto por status (snapshot — ignora filtro de período).'); attachBarClick('chartBacklogStatus', s.backlog_status.labels, 'backlog_status'); } else if (charts['chartBacklogStatus']) { charts['chartBacklogStatus'].destroy(); }
    if (s.aging && s.aging.data && s.aging.data.length) { barChart('chartAging', s.aging.labels, s.aging.data, 'Aging', 'Agrupa tickets abertos por faixas de idade para identificar chamados antigos em backlog (ignora filtro de período).'); attachBarClick('chartAging', s.aging.labels, 'aging'); } else if (charts['chartAging']) { charts['chartAging'].destroy(); }
    // Categoria: se existir série empilhada (category_stacked) usar empilhada; senão fallback simples
    if (s.category_stacked && s.category_stacked.labels && s.category_stacked.labels.length && s.category_stacked.datasets && s.category_stacked.datasets.length) {
      stackedBarChart('chartCat', s.category_stacked, 'Distribuição de tickets por categoria subdividida por status (barras empilhadas) no período selecionado.');
      attachBarClick('chartCat', s.category_stacked.labels, 'category');
    } else if (s.category && s.category.data && s.category.data.length) {
      barChart('chartCat', s.category.labels, s.category.data, 'Categoria', 'Distribuição de tickets por categoria no período selecionado. Use para identificar áreas com maior volume.');
      attachBarClick('chartCat', s.category.labels, 'category');
    } else if (charts['chartCat']) { charts['chartCat'].destroy(); }
  // (widget 'priority' removido)
  // (widget 'impact' removido)
    if (s.resolution_hours && s.resolution_hours.data && s.resolution_hours.data.length) {
      const labels = s.resolution_hours.labels;
      const meanData = s.resolution_hours.data;
      const smoothData = (s.resolution_hours_trend && s.resolution_hours_trend.data) ? s.resolution_hours_trend.data : [];
      const datasets = [
        { label: 'Horas úteis (média)', data: meanData, borderColor: '#0ea5e9', backgroundColor: 'rgba(14,165,233,0.08)', tension: 0.15, help: 'Tempo médio entre abertura e solução em horas úteis; útil para acompanhar SLAs.' },
        { label: 'Horas úteis (suavizado)', data: smoothData, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.08)', tension: 0.25, help: 'Versão suavizada para destacar tendências de tempo de resolução.' }
      ];
      lineChart('chartResolutionHours', labels, datasets);
      // Enable clicking a point to open the modal with tickets resolved in that period
      attachPointClick('chartResolutionHours', labels, ['resolution_hours', 'resolution_hours']);
    } else { destroyChart('chartResolutionHours'); }
    // refresh hidden state (in case layout toggled visibility before load)
    document.querySelectorAll('.card[data-widget]').forEach(el => { if (el.style.display === 'none') return; /* skip hidden */ });
    if (s.load_by_user) { barChart('chartUser', s.load_by_user.labels, s.load_by_user.data, 'Usuário', 'Quantidade de tickets abertos por usuário (pode representar solicitante ou responsável conforme configuração).'); attachBarClick('chartUser', s.load_by_user.labels, 'load_by_user'); }
    if (s.load_by_group_stacked && s.load_by_group_stacked.labels && s.load_by_group_stacked.labels.length && s.load_by_group_stacked.datasets && s.load_by_group_stacked.datasets.length) {
      stackedBarChart('chartGroup', s.load_by_group_stacked, 'Quantidade de tickets por grupo subdividida por status no período selecionado.');
      attachBarClick('chartGroup', s.load_by_group_stacked.labels, 'load_by_group');
    } else if (s.load_by_group) {
      try {
        const labels = (s.load_by_group.labels || []).slice();
        const data = (s.load_by_group.data || []).slice();
        const pairs = labels.map((lab, i) => ({ lab, val: Number(data[i] || 0) }));
        pairs.sort((a, b) => b.val - a.val);
        const sortedLabels = pairs.map(p => p.lab);
        const sortedData = pairs.map(p => p.val);
        barChart('chartGroup', sortedLabels, sortedData, 'Grupo', 'Quantidade de tickets por grupo. Útil para identificar equipes com maior carga de chamados.');
        attachBarClick('chartGroup', sortedLabels, 'load_by_group');
      } catch (e) {
        barChart('chartGroup', s.load_by_group.labels, s.load_by_group.data, 'Grupo', 'Quantidade de tickets por grupo. Útil para identificar equipes com maior carga de chamados.');
        attachBarClick('chartGroup', s.load_by_group.labels, 'load_by_group');
      }
    }

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
  const assignedSel = document.getElementById('assignedGroupFilter');
  const startInp = document.getElementById('start');
  const endInp = document.getElementById('end');
  const startMonthInp = document.getElementById('startMonth');
  const endMonthInp = document.getElementById('endMonth');
  const fire = () => { saveFilters(); loadData(); };
  [granSel, catSel, assignedSel, startInp, endInp, startMonthInp, endMonthInp].forEach(el => {
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
        try { imgHtml = `<img src="${cv.toDataURL()}" style="max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:6px;" />`; } catch (e2) { imgHtml = '<div style="color:#a00">(Imagem indisponível)</div>'; }
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
        const lastCreated = Number(created[created.length - 1] || 0);
        const lastResolved = Number(resolved[resolved.length - 1] || 0);
        const trend = (created.length >= 2 && (created[created.length - 1] - created[0]) > (resolved[resolved.length - 1] - (resolved[0] || 0))) ? 'O volume de criação cresceu mais que o de resoluções, indicando pressão de backlog.' : 'Criações e resoluções acompanham-se de forma semelhante.';
        return `${trend} No período apurado (${meta?.period?.start || ''} a ${meta?.period?.end || ''}), foram criados ${created.reduce((a, b) => a + Number(b || 0), 0)} chamados e resolvidos ${resolved.reduce((a, b) => a + Number(b || 0), 0)}.`;
      }
      case 'backlog': {
        const backlog = series.backlog?.data || [];
        const last = Number(backlog[backlog.length - 1] || 0);
        return `Backlog atual estimado em ${last.toLocaleString('pt-BR')} chamados. Verifique tendência nas últimas semanas para priorizar ações.`;
      }
      case 'backlogStatus': {
        const labels = series.backlog_status?.labels || [];
        const data = series.backlog_status?.data || [];
        const maxIdx = data.reduce((ix, v, i, arr) => v > arr[ix] ? i : ix, 0);
        return `Status predominante: ${labels[maxIdx] || 'N/A'} com ${Number(data[maxIdx] || 0).toLocaleString('pt-BR')} chamados. Esta visão é um snapshot atual.`;
      }
      case 'aging': {
        const labels = series.aging?.labels || [];
        const data = series.aging?.data || [];
        if (!data.length) return '';
        const maxIdx = data.reduce((ix, v, i, arr) => v > arr[ix] ? i : ix, 0);
        return `Faixa com maior concentração de tickets: ${labels[maxIdx] || 'N/A'} (${Number(data[maxIdx] || 0).toLocaleString('pt-BR')}). Focar em reduzir tickets nas faixas mais antigas.`;
      }
      case 'resolutionHours': {
        const d = series.resolution_hours?.data || [];
        if (!d.length) return '';
        const avg = (d.reduce((a, b) => a + Number(b || 0), 0) / d.length).toFixed(1);
        return `Tempo médio de resolução (amostra): ${avg} horas úteis. Compare com o SLA alvo para avaliar desempenho.`;
      }
      case 'category': {
        const labels = series.category?.labels || []; const data = series.category?.data || [];
        if (!data.length) return '';
        const maxIdx = data.reduce((ix, v, i, arr) => v > arr[ix] ? i : ix, 0);
        return `Categoria com maior volume: ${labels[maxIdx] || 'N/A'} — ${Number(data[maxIdx] || 0).toLocaleString('pt-BR')} chamados no período.`;
      }
  // priority widget removido
  // impact widget removido
      case 'load_by_user':
      case 'load_by_group': {
        return `Carga por ${widgetId === 'load_by_user' ? 'usuário' : 'grupo'} mostrada; identifique responsáveis com maior volume para balanceamento.`;
      }
      default: return '';
    }
  } catch (e) { return ''; }
}

// --- Help popover for small ? buttons ---
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
        if (!pop.contains(e.target) && e.target !== btn) { pop.remove(); btn.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); }
      }
      function onEsc(e) { if (e.key === 'Escape') { pop.remove(); btn.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onEsc); } }
      setTimeout(() => document.addEventListener('click', onDocClick));
      document.addEventListener('keydown', onEsc);
      // focus popover for keyboard users
      pop.focus();
    });
  });
}

window.addEventListener('DOMContentLoaded', attachHelpPopovers);

// Preset range buttons: set start/end quickly. Default active = 3 months
// Usa componentes locais para evitar avanço de dia em fusos atrás de UTC
function isoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
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
function initRangeButtons() {
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
          const s = document.getElementById('start').value.slice(0, 7);
          const e = document.getElementById('end').value.slice(0, 7);
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
  } catch { }
  function applyInterval() {
    if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
    const mins = parseInt(inp.value, 10);
    if (!isNaN(mins) && mins > 0) {
      const ms = mins * 60 * 1000;
      autoTimer = setInterval(() => {
        if (!loading) loadData();
      }, ms);
    }
    try { localStorage.setItem(STORAGE_KEY, inp.value || ''); } catch { }
  }
  inp.addEventListener('change', applyInterval);
  applyInterval();
}
window.addEventListener('DOMContentLoaded', setupAutoRefresh);

// Build a single JSON snapshot containing all relevant storage keys
function buildFullSetupSnapshot() {
  const snapshot = { meta: { exported_at: new Date().toISOString(), app: 'dashboard-glpi' }, storage: {} };
  // Keys we manage
  const keys = ['glpiDashboardLayout.v2', FILTERS_KEY, 'glpiAutoRefreshMin', SLA_TITLES_KEY];
  keys.forEach(k => {
    try {
      const v = localStorage.getItem(k);
      snapshot.storage[k] = v === null ? null : JSON.parse(v);
    } catch (e) {
      // fallback: store raw string
      try { snapshot.storage[k] = localStorage.getItem(k); } catch { snapshot.storage[k] = null; }
    }
  });
  // Also include any other key starting with our app prefix
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k) continue;
      if (k.startsWith('glpiDashboard') && !snapshot.storage[k]) {
        try { snapshot.storage[k] = JSON.parse(localStorage.getItem(k)); } catch { snapshot.storage[k] = localStorage.getItem(k); }
      }
    }
  } catch (e) { }
  return snapshot;
}

// Apply imported setup object into localStorage and refresh UI
function applyImportedSetup(obj) {
  if (!obj || !obj.storage) throw new Error('Formato inválido');
  const mapping = obj.storage;
  // Overwrite known keys
  Object.keys(mapping).forEach(k => {
    try {
      const v = mapping[k];
      if (v === null) { localStorage.removeItem(k); }
      else { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); }
    } catch (e) { /* ignore */ }
  });
  // Re-apply changes to the UI: reload filters, layout, auto-refresh
  try { loadFilters(); } catch (e) { }
  try { const wl = WidgetLayout && WidgetLayout.init && (function () { WidgetLayout.init(); return true; })(); } catch (e) { }
  try { setupAutoRefresh(); } catch (e) { }
  // Reload data to reflect imported filters/layout
  try { loadData(); } catch (e) { }
}

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
        function move(ev) {
          const dx = ev.clientX - startX;
          const newW = Math.max(50, startW + dx);
          th.style.width = newW + 'px';
        }
        function up() {
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
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.key === sortState.key) th.classList.add(sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    });
  }
  function setRows(data) { currentRows = data || []; renderBody(); }
  function init() { buildHeader(); }
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

async function openTicketsModal(source, label, idsList) {
  const gran = document.getElementById('gran').value;
  let userStart, userEnd;
  if (gran === 'Mensal') {
    // Recalcula como em loadData
    const sm = document.getElementById('startMonth').value; // YYYY-MM
    const em = document.getElementById('endMonth').value;   // YYYY-MM
    userStart = sm + '-01';
    const [ey, emon] = em.split('-').map(Number);
  const lastDay = new Date(ey, emon, 0); // último dia do mês final
  userEnd = isoDate(lastDay);
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
  let assignedSel='todos';
  const vals=getAssignedGroupSelectedValues();
  if (vals && vals.length && !vals.includes('todos')) assignedSel = vals.join(',');
  const statusSel = document.getElementById('statusFilter') ? document.getElementById('statusFilter').value : 'todos';
  const params = new URLSearchParams({
    gran,
    start: bstart,
    end: bend,
    source: idsList && idsList.length ? 'ids' : source,
    label,
    ustart: userStart,
    uend: userEnd,
    baseline: needBaseline ? '1' : '0',
  cat: catSel,
  assigned_group: assignedSel,
  status: statusSel
  });
  if (idsList && idsList.length) params.set('ids', idsList.join(','));

  modal.title.textContent = idsList && idsList.length ? `Chamados — SLA ${label}` : `Chamados — ${source} · ${label}`;
  modal.info.textContent = 'Carregando...';
  modal.rows.innerHTML = '';
  modal.show();
  Loader.show('Carregando chamados...');
  document.body.style.cursor = 'progress';
  try {
    const r = await fetch(`/api/tickets?${params.toString()}`);
    let js = null;
    try { js = await r.clone().json(); } catch { /* ignore */ }
    if (r.status === 503) {
      const friendly = (js && (js.mensagem || js.message)) || 'Serviço temporariamente indisponível.';
      modal.info.textContent = friendly;
      Toasts.push('warn', friendly);
      return;
    }
    if (!r.ok) {
      const msg = (js && (js.mensagem || js.message || js.error)) || `Falha (HTTP ${r.status})`;
      throw new Error(msg);
    }
    if (js && js.error) throw new Error(js.error);
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

// --- Toggle de exibição da barra de filtros (.controls) via botão externo ---
function initControlsToggle() {
  const btn = document.getElementById('controlsToggle');
  const controls = document.querySelector('.controls');
  if (!btn || !controls) return;
  const STORAGE_KEY = 'glpiControlsCollapsed.v1';
  let collapsed = false;
  try { collapsed = localStorage.getItem(STORAGE_KEY) === '1'; } catch { }
  function applyState() {
    if (collapsed) {
      controls.classList.add('collapsed');
      btn.setAttribute('aria-pressed', 'true');
      // Mostra seta para cima indicando que pode expandir
      btn.textContent = '˅';
    } else {
      controls.classList.remove('collapsed');
      btn.setAttribute('aria-pressed', 'false');
      // Mostra seta para baixo indicando que pode recolher
      btn.textContent = '˄';
    }
  }
  applyState();
  btn.addEventListener('click', () => {
    collapsed = !collapsed;
    try { localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0'); } catch { }
    applyState();
  });
}
window.addEventListener('DOMContentLoaded', initControlsToggle);
