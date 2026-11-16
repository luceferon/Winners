/* Раздел «История ставок». */

import { api } from '../api.js';
import {
  $, $$, h, clear, fmtCoef, fmtMoney, fmtDateTime, notifyError,
  emptyState, debounce, iconBtn, statusBadge,
  openModal, confirmDialog, toast, STATUS_LABELS, LEG_STATUS_LABELS, LAST_BET_LABELS,
} from '../util.js';
import { store, fillSportSelect, fillSourceSelect, notifyDataChanged, loadSources } from '../store.js';

const state = {
  status: 'all',
  search: '',
  sport: 'all',
  sourceId: '0',
  from: '',
  to: '',
  sort: 'created_at',
  order: 'desc',
  limit: 50,
  offset: 0,
  total: 0,
  loading: false,
  selected: new Set(),
  pageIds: [],
  restored: false,
};

const BET_CHIPS = [
  { value: 'all', label: 'Все' },
  { value: 'pending', label: 'Текущие' },
  { value: 'won', label: 'Выигрышные' },
  { value: 'lost', label: 'Проигрышные' },
  { value: 'push', label: 'Возврат' },
];

const BET_SORTS = [
  { value: 'created_at', label: 'По дате' },
  { value: 'event_name', label: 'По событию' },
  { value: 'coefficient', label: 'По коэффициенту' },
  { value: 'stake', label: 'По сумме' },
  { value: 'status', label: 'По статусу' },
  { value: 'settled_at', label: 'По дате расчёта' },
];

// --- рендер фильтров --------------------------------------------------------
function renderChips() {
  const host = $('#status-chips');
  if (!host) return;
  clear(host).append(...BET_CHIPS.map((chip) => h('button', {
    class: `chip ${state.status === chip.value ? 'is-active' : ''}`,
    type: 'button',
    dataset: { status: chip.value },
  }, chip.label)));
}

function renderSortOptions() {
  const select = $('#history-sort');
  if (!select) return;
  clear(select).append(...BET_SORTS.map((item) => new Option(item.label, item.value)));
  if (!BET_SORTS.some((item) => item.value === state.sort)) state.sort = BET_SORTS[0].value;
  select.value = state.sort;
}

// --- таблица ставок ---------------------------------------------------------
/** Строка события внутри экспресса. */
function legLine(leg) {
  return h('div', { class: 'leg-line' }, [
    h('span', { class: `badge ${leg.status}` }, LEG_STATUS_LABELS[leg.status] || leg.status),
    h('span', { class: 'leg-name', title: leg.event_name }, leg.event_name),
    leg.prediction ? h('span', {}, leg.prediction) : null,
    h('span', { class: 'leg-coef' }, fmtCoef(leg.coefficient)),
  ]);
}

function betRow(bet) {
  const currency = store.currency;
  const isExpress = bet.kind === 'express';
  const legs = bet.legs || [];
  const source = bet.source_name || '—';

  const actions = isExpress
    ? [
      iconBtn('check', 'Результаты событий', () => openLegsModal(bet)),
      iconBtn('copy', 'Дублировать ставку', () => duplicateBet(bet)),
      iconBtn('trash', 'Удалить ставку', () => removeBet(bet)),
    ]
    : [
      iconBtn('check', 'Изменить результат', () => openResultModal(bet)),
      iconBtn('copy', 'Дублировать ставку', () => duplicateBet(bet)),
      iconBtn('trash', 'Удалить ставку', () => removeBet(bet)),
    ];

  return h('tr', {}, [
    h('td', { class: 'check' }, [rowCheckbox(bet)]),
    h('td', { class: 'cell-event' }, [
      h('strong', {}, bet.event_name),
      h('span', {}, [
        isExpress ? `экспресс · ${legs.length} событий` : bet.sport,
        ` · ${fmtDateTime(bet.created_at)}`,
        !isExpress && bet.prediction ? ` · прогноз: ${bet.prediction}` : '',
      ]),
      isExpress && legs.length ? h('div', { class: 'legs-inline' }, legs.map(legLine)) : null,
    ]),
    h('td', { class: 'num' }, fmtCoef(bet.coefficient)),
    h('td', { class: 'num strong' }, fmtMoney(bet.stake, currency)),
    h('td', {}, [statusBadge(bet)]),
    h('td', { class: `num strong ${bet.profit > 0 ? 'pos' : bet.profit < 0 ? 'neg' : ''}` },
      bet.status === 'pending' ? `≈ ${fmtMoney(bet.potential_payout, currency)}` : fmtMoney(bet.profit, currency, { sign: true })),
    h('td', { class: 'muted' }, source),
    h('td', { class: 'num muted' }, bet.settled_at ? fmtDateTime(bet.settled_at) : '—'),
    h('td', { class: 'actions' }, actions),
  ]);
}

function betsTable(items) {
  if (!items.length) return emptyState('Ставки не найдены', 'Измените фильтры или добавьте новую ставку.');
  state.pageIds = items.map((bet) => bet.id);

  const all = h('input', { type: 'checkbox', class: 'check-all', id: 'history-check-all' });
  all.addEventListener('change', () => {
    items.forEach((bet) => {
      if (all.checked) state.selected.add(bet.id);
      else state.selected.delete(bet.id);
    });
    refreshRowChecks();
    updateBulkBar();
  });

  return h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', { class: 'check' }, [all]),
      h('th', {}, 'Событие'),
      h('th', { class: 'num' }, 'Коэф.'),
      h('th', { class: 'num' }, 'Сумма'),
      h('th', {}, 'Статус'),
      h('th', { class: 'num' }, 'Результат'),
      h('th', {}, 'Источник'),
      h('th', { class: 'num' }, 'Расчёт'),
      h('th', { class: 'num' }, ''),
    ])]),
    h('tbody', {}, items.map(betRow)),
  ]);
}

// --- выделение строк и массовые операции ------------------------------------
function rowCheckbox(bet) {
  const box = h('input', { type: 'checkbox', class: 'row-check' });
  box.dataset.id = String(bet.id);
  box.checked = state.selected.has(bet.id);
  box.addEventListener('change', () => {
    if (box.checked) state.selected.add(bet.id);
    else state.selected.delete(bet.id);
    updateBulkBar();
    syncCheckAll();
  });
  return box;
}

function refreshRowChecks() {
  $$('#history-table .row-check').forEach((box) => {
    box.checked = state.selected.has(Number(box.dataset.id));
  });
}

function syncCheckAll() {
  const all = $('#history-check-all');
  if (!all) return;
  const page = state.pageIds;
  const checked = page.filter((id) => state.selected.has(id)).length;
  all.checked = page.length > 0 && checked === page.length;
  all.indeterminate = checked > 0 && checked < page.length;
}

function updateBulkBar() {
  const bar = $('#history-bulk');
  const count = $('#history-bulk-count');
  if (!bar) return;
  const size = state.selected.size;
  bar.classList.toggle('hidden', size === 0);
  if (count) count.textContent = `Выбрано: ${size}`;
}

function clearSelection() {
  state.selected.clear();
  refreshRowChecks();
  syncCheckAll();
  updateBulkBar();
}

function selectedIds() {
  return Array.from(state.selected);
}

async function duplicateBet(bet) {
  try {
    const copy = await api.duplicateBet(bet.id);
    toast('Ставка продублирована', `${copy.event_name} — ${fmtMoney(copy.stake, store.currency)}`, 'ok');
    await refresh();
    notifyDataChanged('bets');
  } catch (error) {
    notifyError(error);
  }
}

async function applyBulkStatus() {
  const ids = selectedIds();
  if (!ids.length) return;
  const select = $('#history-bulk-status');
  const status = select ? select.value : 'pending';
  try {
    const result = await api.bulkBets({ ids, action: 'status', status });
    const skipped = result.skipped ? ` · пропущено экспрессов: ${result.skipped}` : '';
    toast('Статус обновлён', `Изменено ставок: ${result.affected}${skipped}`, 'ok');
    clearSelection();
    await refresh();
    notifyDataChanged('bets');
  } catch (error) {
    notifyError(error);
  }
}

async function bulkDelete() {
  const ids = selectedIds();
  if (!ids.length) return;
  const ok = await confirmDialog({
    title: 'Удалить выбранные ставки?',
    message: `Будет удалено ставок: ${ids.length}. Действие необратимо.`,
    confirmText: 'Удалить',
    danger: true,
  });
  if (!ok) return;
  try {
    const result = await api.bulkBets({ ids, action: 'delete' });
    toast('Удалено', `Удалено ставок: ${result.affected}`, 'ok');
    clearSelection();
    await refresh();
    notifyDataChanged('bets');
  } catch (error) {
    notifyError(error);
  }
}

// --- сохранение фильтров ----------------------------------------------------
function snapshotFilters() {
  return {
    status: state.status,
    sport: state.sport,
    sourceId: state.sourceId,
    search: state.search,
    from: state.from,
    to: state.to,
    sort: state.sort,
    order: state.order,
    limit: state.limit,
  };
}

async function saveFilters() {
  try {
    const data = await api.updateSettings({ history_filters: snapshotFilters() });
    store.settings = data.values || store.settings;
  } catch {
    /* сохранение фильтров не критично */
  }
}

const persistFilters = debounce(() => { saveFilters(); }, 700);

function restoreFilters() {
  if (state.restored) return;
  state.restored = true;
  const saved = store.settings && store.settings.history_filters;
  if (!saved || typeof saved !== 'object') return;

  if (typeof saved.status === 'string') state.status = saved.status;
  if (typeof saved.sport === 'string') state.sport = saved.sport;
  if (saved.sourceId !== undefined && saved.sourceId !== null) state.sourceId = String(saved.sourceId);
  if (typeof saved.search === 'string') state.search = saved.search;
  if (typeof saved.from === 'string') state.from = saved.from;
  if (typeof saved.to === 'string') state.to = saved.to;
  if (typeof saved.sort === 'string') state.sort = saved.sort;
  if (saved.order === 'asc' || saved.order === 'desc') state.order = saved.order;
  if (Number(saved.limit) > 0) state.limit = Number(saved.limit);

  const search = $('#history-search');
  if (search) search.value = state.search;
  const from = $('#history-from');
  if (from) from.value = state.from;
  const to = $('#history-to');
  if (to) to.value = state.to;
  const limit = $('#history-limit');
  if (limit) limit.value = String(state.limit);
  const order = $('#history-order');
  if (order) {
    order.dataset.order = state.order;
    order.textContent = state.order === 'desc' ? '↓ убыв.' : '↑ возр.';
  }
  renderChips();
  renderSortOptions();
}

// --- действия ---------------------------------------------------------------
async function removeBet(bet) {
  const ok = await confirmDialog({
    title: 'Удалить ставку?',
    message: `«${bet.event_name}» на сумму ${fmtMoney(bet.stake, store.currency)} будет удалена безвозвратно.`,
    confirmText: 'Удалить',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteBet(bet.id);
    toast('Удалено', `Ставка #${bet.id} удалена`, 'ok');
    await refresh();
    notifyDataChanged('bets');
  } catch (error) {
    notifyError(error);
  }
}

function openResultModal(bet) {
  const statusSelect = h('select', { class: 'input' },
    Object.entries(STATUS_LABELS).map(([value, label]) => new Option(label, value)));
  statusSelect.value = bet.status === 'pending' ? 'won' : bet.status;

  const payoutInput = h('input', {
    class: 'input', type: 'number', step: '0.01', min: '0',
    placeholder: 'автоматически',
  });
  payoutInput.value = bet.status === 'pending' ? '' : String(bet.payout ?? '');

  const commentInput = h('textarea', { class: 'input', rows: '2', placeholder: 'Комментарий к результату' });
  commentInput.value = bet.comment || '';

  const hint = h('p', { class: 'hint' },
    `Коэффициент ${fmtCoef(bet.coefficient)} · ставка ${fmtMoney(bet.stake, store.currency)}. `
    + 'Оставьте поле выплаты пустым для автоматического расчёта.');

  const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Сохранить результат');

  const modal = openModal({
    title: `Ручная корректировка ставки #${bet.id}`,
    body: h('div', { class: 'form' }, [
      h('label', { class: 'field' }, [h('span', {}, 'Результат'), statusSelect]),
      h('label', { class: 'field' }, [h('span', {}, 'Выплата'), payoutInput]),
      h('label', { class: 'field' }, [h('span', {}, 'Комментарий'), commentInput]),
      hint,
    ]),
    footer: [
      h('button', { class: 'btn ghost', type: 'button', onclick: () => modal.close() }, 'Отмена'),
      saveBtn,
    ],
  });

  saveBtn.addEventListener('click', async () => {
    const payload = { status: statusSelect.value };
    if (payoutInput.value !== '') payload.payout = Number(payoutInput.value);
    if (commentInput.value.trim()) payload.comment = commentInput.value.trim();
    try {
      await api.setResult(bet.id, payload);
      modal.close();
      toast('Сохранено', `Результат ставки #${bet.id} обновлён`, 'ok');
      await refresh();
      notifyDataChanged('bets');
    } catch (error) {
      notifyError(error);
    }
  });
}

/** Отметить результат каждого события экспресса и увидеть итог. */
function openLegsModal(bet) {
  let current = bet;
  const body = h('div', { class: 'form' });

  const summary = (data) => h('div', { class: 'report-box' }, [
    h('div', { class: 'item' }, [h('span', {}, 'Коэффициент'), h('b', {}, fmtCoef(data.coefficient))]),
    h('div', { class: 'item' }, [h('span', {}, 'Сумма'), h('b', {}, fmtMoney(data.stake, store.currency))]),
    h('div', { class: 'item' }, [
      h('span', {}, 'Выплата'),
      h('b', {}, data.status === 'pending' ? '—' : fmtMoney(data.payout, store.currency)),
    ]),
    h('div', { class: 'item' }, [h('span', {}, 'Итог'), h('span', {}, statusBadge(data))]),
  ]);

  const render = () => {
    clear(body);
    body.append(summary(current));

    (current.legs || []).forEach((leg) => {
      const select = h('select', { class: 'input' },
        Object.entries(LEG_STATUS_LABELS).map(([value, label]) => new Option(label, value)));
      select.value = leg.status || 'pending';
      select.addEventListener('change', async () => {
        try {
          current = await api.setLegResult(current.id, leg.id, { status: select.value });
          toast('Сохранено', `${leg.event_name}: ${LEG_STATUS_LABELS[select.value] || select.value}`, 'ok');
          render();
          await refresh();
          notifyDataChanged('bets');
        } catch (error) {
          notifyError(error);
        }
      });

      body.append(h('div', { class: 'leg-edit-row' }, [
        h('div', { class: 'leg-edit-main' }, [
          h('strong', {}, leg.event_name),
          h('span', {}, `${leg.prediction || 'прогноз не указан'} · кф ${fmtCoef(leg.coefficient)}`),
        ]),
        select,
      ]));
    });

    body.append(h('em', { class: 'hint' },
      'Проигрыш любого события — экспресс проигран. Возврат по событию учитывается как коэффициент 1.00.'));
  };

  render();

  const modal = openModal({
    title: `Результаты экспресса #${bet.id}`,
    body,
    footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => modal.close() }, 'Закрыть')],
  });
}

// --- статусы последних ставок по источникам --------------------------------
/** Панель над таблицей: источник и результат его последней ставки. */
export function renderSourceStatus() {
  const host = $('#source-status');
  if (!host) return;
  clear(host);
  const items = store.sources.filter((source) => source.last_status);
  if (!items.length) return;
  host.append(...items.map((source) => h('span', {
    class: `item ${source.enabled ? '' : 'is-off'}`,
    title: `${source.name}: последняя ставка`,
  }, [
    h('span', { class: 'name' }, source.name),
    h('span', { class: `badge ${source.last_status} badge-mini` },
      LAST_BET_LABELS[source.last_status] || source.last_status),
  ])));
}

// --- выборка данных ---------------------------------------------------------
function currentFilters() {
  return {
    status: state.status === 'all' ? null : state.status,
    sport: state.sport === 'all' ? null : state.sport,
    source_id: state.sourceId !== '0' ? Number(state.sourceId) : null,
    search: state.search || null,
    date_from: state.from || null,
    date_to: state.to || null,
    sort: state.sort,
    order: state.order,
    limit: state.limit,
    offset: state.offset,
  };
}

export async function refresh() {
  if (state.loading) return;
  state.loading = true;
  const host = $('#history-table');
  const countLabel = $('#history-count');
  if (host) clear(host).append(h('div', { class: 'skeleton' }));

  try {
    const filters = currentFilters();
    const data = await api.listBets(filters);
    const items = data.items || [];
    const total = data.total || 0;
    // Статусы последних ставок перечитываем с сервера, чтобы бейдж источников был свежим.
    try { await loadSources(); } catch { /* бейдж не критичен для таблицы */ }
    if (host) clear(host).append(betsTable(items));
    renderSourceStatus();
    syncCheckAll();
    updateBulkBar();

    state.total = total;
    if (countLabel) {
      const from = total === 0 ? 0 : state.offset + 1;
      const to = Math.min(state.offset + state.limit, total);
      countLabel.textContent = `Показано ${from}–${to} из ${total}`;
    }
    const pageLabel = $('#history-page');
    if (pageLabel) pageLabel.textContent = String(Math.floor(state.offset / state.limit) + 1);
    const prev = $('#history-prev');
    const next = $('#history-next');
    if (prev) prev.disabled = state.offset <= 0;
    if (next) next.disabled = state.offset + state.limit >= total;
  } catch (error) {
    if (host) clear(host).append(emptyState('Не удалось загрузить данные'));
    notifyError(error);
  } finally {
    state.loading = false;
  }
}

function resetPage() {
  state.offset = 0;
  clearSelection();
}

// --- инициализация ----------------------------------------------------------
export function init() {
  const chips = $('#status-chips');
  if (chips) {
    chips.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      state.status = chip.dataset.status;
      renderChips();
      resetPage();
      persistFilters();
      refresh();
    });
  }

  const search = $('#history-search');
  if (search) {
    search.addEventListener('input', debounce(() => {
      state.search = search.value.trim();
      resetPage();
      persistFilters();
      refresh();
    }));
  }

  const sport = $('#history-sport');
  if (sport) sport.addEventListener('change', () => { state.sport = sport.value; resetPage(); persistFilters(); refresh(); });
  const source = $('#history-source');
  if (source) source.addEventListener('change', () => { state.sourceId = source.value; resetPage(); persistFilters(); refresh(); });
  const from = $('#history-from');
  if (from) from.addEventListener('change', () => { state.from = from.value; resetPage(); persistFilters(); refresh(); });
  const to = $('#history-to');
  if (to) to.addEventListener('change', () => { state.to = to.value; resetPage(); persistFilters(); refresh(); });

  const sort = $('#history-sort');
  if (sort) sort.addEventListener('change', () => { state.sort = sort.value; resetPage(); persistFilters(); refresh(); });

  const order = $('#history-order');
  if (order) {
    order.addEventListener('click', () => {
      state.order = state.order === 'desc' ? 'asc' : 'desc';
      order.dataset.order = state.order;
      order.textContent = state.order === 'desc' ? '↓ убыв.' : '↑ возр.';
      resetPage();
      persistFilters();
      refresh();
    });
  }

  const limit = $('#history-limit');
  if (limit) limit.addEventListener('change', () => { state.limit = Number(limit.value); resetPage(); persistFilters(); refresh(); });

  const prev = $('#history-prev');
  if (prev) prev.addEventListener('click', () => {
    state.offset = Math.max(0, state.offset - state.limit);
    clearSelection();
    refresh();
  });
  const next = $('#history-next');
  if (next) next.addEventListener('click', () => {
    if (state.offset + state.limit < state.total) {
      state.offset += state.limit;
      clearSelection();
      refresh();
    }
  });

  const reset = $('#history-reset');
  if (reset) {
    reset.addEventListener('click', () => {
      state.status = 'all';
      state.search = '';
      state.sport = 'all';
      state.sourceId = '0';
      state.from = '';
      state.to = '';
      state.limit = 50;
      state.offset = 0;
      state.order = 'desc';
      state.sort = 'created_at';
      if (search) search.value = '';
      if (sport) sport.value = 'all';
      if (source) source.value = '0';
      if (from) from.value = '';
      if (to) to.value = '';
      if (limit) limit.value = '50';
      if (order) { order.dataset.order = 'desc'; order.textContent = '↓ убыв.'; }
      renderChips();
      renderSortOptions();
      syncFilterOptions();
      clearSelection();
      persistFilters();
      refresh();
    });
  }

  const exportBtn = $('#history-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      // Экспорт отдаёт всю выборку по фильтрам, поэтому пагинация не передаётся.
      const { limit, offset, ...filters } = currentFilters();
      exportBtn.disabled = true;
      try {
        await api.exportBets(filters);
        toast('Экспорт готов', 'Файл CSV сохранён', 'ok');
      } catch (error) {
        notifyError(error);
      } finally {
        exportBtn.disabled = false;
      }
    });
  }

  const bulkApply = $('#history-bulk-apply');
  if (bulkApply) bulkApply.addEventListener('click', () => applyBulkStatus());
  const bulkDeleteBtn = $('#history-bulk-delete');
  if (bulkDeleteBtn) bulkDeleteBtn.addEventListener('click', () => bulkDelete());
  const bulkClear = $('#history-bulk-clear');
  if (bulkClear) bulkClear.addEventListener('click', () => clearSelection());

  renderChips();
  renderSortOptions();
}

export function syncFilterOptions() {
  restoreFilters();
  fillSportSelect($('#history-sport'), { value: state.sport });
  fillSourceSelect($('#history-source'), { value: state.sourceId });
  renderSourceStatus();
}
