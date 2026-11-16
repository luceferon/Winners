/* Раздел «Общая статистика». */

import { api } from '../api.js';
import { $, h, clear, fmtMoney, fmtNum, fmtPct, fmtCoef, notifyError, emptyState, toast } from '../util.js';
import { store, fillSportSelect, fillSourceSelect } from '../store.js';
import { renderStatsCharts, resizeAll } from '../charts.js';

const state = {
  preset: '30d',
  from: '',
  to: '',
  sport: 'all',
  sourceId: '0',
  loaded: false,
  orderApplied: false,
};

function kpiCard({ label, value, sub, tone = '', valueClass = '' }) {
  return h('article', { class: `kpi ${tone}` }, [
    h('div', { class: 'kpi-label' }, label),
    h('div', { class: `kpi-value ${valueClass}` }, value),
    sub ? h('div', { class: 'kpi-sub' }, sub) : null,
  ]);
}

function renderKpis(summary, bankroll) {
  const grid = $('#kpi-grid');
  if (!grid) return;
  const currency = store.currency;
  const counts = summary.counts || {};
  const amounts = summary.amounts || {};
  const metrics = summary.metrics || {};
  const profit = metrics.profit || 0;

  const cards = [
    bankroll
      ? kpiCard({
          label: 'Текущий баланс',
          value: fmtMoney(bankroll.balance || 0, currency),
          sub: `всего с учётом ставок в игре: ${fmtMoney(bankroll.total, currency)}`,
          valueClass: (bankroll.balance || 0) >= 0 ? 'pos' : 'neg',
        })
      : null,
    kpiCard({
      label: 'Всего ставок',
      value: fmtNum(counts.total),
      sub: `завершено: ${fmtNum(counts.settled)}`,
    }),
    kpiCard({
      label: 'Выигрышные',
      value: fmtNum(counts.won),
      sub: `сумма: ${fmtMoney(amounts.won_stake, currency)}`,
      tone: 'tone-win',
      valueClass: 'pos',
    }),
    kpiCard({
      label: 'Проигрышные',
      value: fmtNum(counts.lost),
      sub: `сумма: ${fmtMoney(amounts.lost_stake, currency)}`,
      tone: 'tone-loss',
      valueClass: counts.lost ? 'neg' : '',
    }),
    kpiCard({
      label: 'Активные ставки',
      value: fmtNum(counts.pending),
      sub: `в обороте: ${fmtMoney(amounts.active, currency)}`,
      tone: 'tone-push',
    }),
    kpiCard({
      label: 'Финансовый результат',
      value: fmtMoney(profit, currency, { sign: true }),
      sub: `ROI: ${fmtPct(metrics.roi_percent)} · оборот ${fmtMoney(amounts.staked_total, currency)}`,
      valueClass: profit >= 0 ? 'pos' : 'neg',
    }),
    kpiCard({
      label: 'Проходимость',
      value: fmtPct(metrics.win_rate_percent),
      sub: `прибыль на ставку: ${fmtMoney(metrics.profit_per_bet, currency, { sign: true })}`,
    }),
    kpiCard({
      label: 'Средний коэффициент',
      value: fmtCoef(metrics.avg_coefficient),
      sub: `у выигрышных: ${fmtCoef(metrics.avg_coefficient_won)}`,
    }),
    kpiCard({
      label: 'Средняя ставка',
      value: fmtMoney(metrics.avg_stake, currency),
      sub: `всего ставок: ${fmtNum(counts.total)}`,
    }),
  ];

  clear(grid).append(...cards.filter(Boolean));
}

function groupTable(rows, firstColumn) {
  if (!rows || !rows.length) return emptyState('Нет данных за выбранный период');
  const currency = store.currency;
  const table = h('table', { class: 'data' }, [
    h('thead', {}, [
      h('tr', {}, [
        h('th', {}, firstColumn),
        h('th', { class: 'num' }, 'Ставок'),
        h('th', { class: 'num' }, 'В/П'),
        h('th', { class: 'num' }, 'Проходимость'),
        h('th', { class: 'num' }, 'Оборот'),
        h('th', { class: 'num' }, 'Результат'),
        h('th', { class: 'num' }, 'Ср. кф'),
      ]),
    ]),
    h('tbody', {}, rows.map((row) => h('tr', {}, [
      h('td', { class: 'strong' }, row.name),
      h('td', { class: 'num' }, fmtNum(row.bets)),
      h('td', { class: 'num muted' }, `${row.won} / ${row.lost}`),
      h('td', { class: 'num' }, fmtPct(row.win_rate_percent)),
      h('td', { class: 'num' }, fmtMoney(row.stake, currency)),
      h('td', { class: `num strong ${row.profit >= 0 ? 'pos' : 'neg'}` }, fmtMoney(row.profit, currency, { sign: true })),
      h('td', { class: 'num' }, fmtCoef(row.avg_coefficient)),
    ]))),
  ]);
  return table;
}

function renderTables(summary) {
  const sportsHost = $('#table-sports');
  const sourcesHost = $('#table-sources');
  if (sportsHost) clear(sportsHost).append(groupTable(summary.by_sport, 'Вид спорта'));
  if (sourcesHost) clear(sourcesHost).append(groupTable(summary.by_source, 'Источник'));
}

/** Карточки серий побед/поражений и максимальной просадки. */
function renderStreaks(summary) {
  const host = $('#stats-streaks');
  if (!host) return;
  const currency = store.currency;
  const streaks = summary.streaks || {};
  const drawdown = summary.drawdown || {};
  const current = Number(streaks.current_streak || 0);
  const currentKind = streaks.current_streak_kind;
  const currentValue = currentKind === 'won'
    ? `${current} побед`
    : currentKind === 'lost'
      ? `${Math.abs(current)} поражений`
      : '—';
  const currentSub = currentKind === 'won'
    ? 'серия продолжается'
    : currentKind === 'lost'
      ? 'серия продолжается'
      : 'нет данных';

  clear(host).append(...[
    kpiCard({
      label: 'Макс. серия побед',
      value: fmtNum(streaks.max_win_streak),
      sub: 'подряд выигрышных ставок',
      tone: 'tone-win',
      valueClass: streaks.max_win_streak ? 'pos' : '',
    }),
    kpiCard({
      label: 'Макс. серия поражений',
      value: fmtNum(streaks.max_lose_streak),
      sub: 'подряд проигрышных ставок',
      tone: 'tone-loss',
      valueClass: streaks.max_lose_streak ? 'neg' : '',
    }),
    kpiCard({
      label: 'Текущая серия',
      value: currentValue,
      sub: currentSub,
      tone: 'tone-push',
    }),
    kpiCard({
      label: 'Макс. просадка',
      value: fmtMoney(drawdown.max_drawdown, currency, { sign: true }),
      sub: `пик профита: ${fmtMoney(drawdown.peak_profit, currency, { sign: true })}`,
      tone: 'tone-warn',
      valueClass: (drawdown.max_drawdown || 0) < 0 ? 'neg' : '',
    }),
  ]);
}

/** Таблица «Отчёт по месяцам». */
function renderMonths(summary) {
  const host = $('#table-months');
  if (!host) return;
  const rows = summary.by_month || [];
  clear(host);
  if (!rows.length) {
    host.append(emptyState('Нет данных за выбранный период'));
    return;
  }
  const currency = store.currency;
  host.append(h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', {}, 'Месяц'),
      h('th', { class: 'num' }, 'Ставок'),
      h('th', { class: 'num' }, 'В/П'),
      h('th', { class: 'num' }, 'Проходимость'),
      h('th', { class: 'num' }, 'Оборот'),
      h('th', { class: 'num' }, 'Результат'),
      h('th', { class: 'num' }, 'ROI'),
    ])]),
    h('tbody', {}, rows.map((row) => h('tr', {}, [
      h('td', { class: 'strong' }, row.name),
      h('td', { class: 'num' }, fmtNum(row.bets)),
      h('td', { class: 'num muted' }, `${row.won} / ${row.lost}`),
      h('td', { class: 'num' }, fmtPct(row.win_rate_percent)),
      h('td', { class: 'num' }, fmtMoney(row.stake, currency)),
      h('td', { class: `num strong ${row.profit >= 0 ? 'pos' : 'neg'}` }, fmtMoney(row.profit, currency, { sign: true })),
      h('td', { class: `num ${row.roi_percent >= 0 ? 'pos' : 'neg'}` }, fmtPct(row.roi_percent)),
    ]))),
  ]));
}

const COMPARE_ROWS = [
  { key: 'profit', label: 'Финансовый результат', higherBetter: true, fmt: (v) => fmtMoney(v, store.currency, { sign: true }) },
  { key: 'roi_percent', label: 'ROI', higherBetter: true, fmt: (v) => fmtPct(v) },
  { key: 'win_rate_percent', label: 'Проходимость', higherBetter: true, fmt: (v) => fmtPct(v) },
  { key: 'avg_coefficient', label: 'Средний коэффициент', higherBetter: true, fmt: (v) => fmtCoef(v) },
  { key: 'turnover', label: 'Оборот', higherBetter: true, fmt: (v) => fmtMoney(v, store.currency) },
  { key: 'max_drawdown', label: 'Макс. просадка', higherBetter: false, fmt: (v) => fmtMoney(v, store.currency, { sign: true }) },
  { key: 'total', label: 'Всего ставок', higherBetter: true, fmt: (v) => fmtNum(v) },
  { key: 'won', label: 'Выигрышных', higherBetter: true, fmt: (v) => fmtNum(v) },
  { key: 'lost', label: 'Проигрышных', higherBetter: false, fmt: (v) => fmtNum(v) },
];

/** Таблица сравнения текущего периода с предыдущим. */
function renderCompare(compare) {
  const host = $('#stats-compare');
  const rangeLabel = $('#stats-compare-range');
  if (!host) return;
  clear(host);
  if (!compare || !compare.current) {
    if (rangeLabel) rangeLabel.textContent = 'Нет данных для сравнения';
    host.append(emptyState('Нет данных'));
    return;
  }

  const { current, previous, delta, range } = compare;
  if (rangeLabel) {
    rangeLabel.textContent = range && range.has_previous
      ? `${range.from} — ${range.to} против ${range.previous_from} — ${range.previous_to}`
      : 'Предыдущий период недоступен (нет границ периода)';
  }

  host.append(h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', {}, 'Показатель'),
      h('th', { class: 'num' }, 'Текущий'),
      h('th', { class: 'num' }, 'Предыдущий'),
      h('th', { class: 'num' }, 'Разница'),
    ])]),
    h('tbody', {}, COMPARE_ROWS.map((row) => {
      const curr = current[row.key] ?? 0;
      const prev = previous ? previous[row.key] ?? 0 : null;
      const diff = delta ? delta[row.key] ?? 0 : null;
      let diffTone = '';
      if (diff !== null && diff !== 0) {
        diffTone = (diff > 0) === row.higherBetter ? 'pos' : 'neg';
      }
      return h('tr', {}, [
        h('td', { class: 'strong' }, row.label),
        h('td', { class: 'num strong' }, row.fmt(curr)),
        h('td', { class: 'num muted' }, prev === null ? '—' : row.fmt(prev)),
        h('td', { class: `num ${diffTone}` }, diff === null ? '—' : row.fmt(diff)),
      ]);
    })),
  ]));
}

/** Параметры сводки по текущим фильтрам (общие для загрузки и экспорта). */
function currentParams() {
  return {
    preset: state.preset,
    date_from: state.preset === 'custom' ? state.from || null : null,
    date_to: state.preset === 'custom' ? state.to || null : null,
    sport: state.sport && state.sport !== 'all' ? state.sport : null,
    source_id: state.sourceId && state.sourceId !== '0' ? Number(state.sourceId) : null,
  };
}

// --- перетаскивание панелей -------------------------------------------------
const PANELS_CONTAINER = '#stats-panels';

/** Текущий порядок панелей (массив data-panel). */
function currentPanelOrder() {
  const container = $(PANELS_CONTAINER);
  if (!container) return [];
  return Array.from(container.children)
    .filter((el) => el.dataset && el.dataset.panel)
    .map((el) => el.dataset.panel);
}

/** Применить сохранённый порядок панелей из настроек. */
function applySavedOrder() {
  if (state.orderApplied) return;
  const container = $(PANELS_CONTAINER);
  if (!container) return;
  const saved = Array.isArray(store.settings.stats_panel_order) ? store.settings.stats_panel_order : [];
  if (!saved.length) { state.orderApplied = true; return; }

  const panels = {};
  Array.from(container.children).forEach((el) => {
    if (el.dataset && el.dataset.panel) panels[el.dataset.panel] = el;
  });

  const ordered = saved.map((id) => panels[id]).filter(Boolean);
  const remaining = Object.values(panels).filter((el) => !saved.includes(el.dataset.panel));

  [...ordered, ...remaining].forEach((el) => container.appendChild(el));
  state.orderApplied = true;
}

/** Сохранить текущий порядок панелей в настройках. */
function savePanelOrder() {
  const order = currentPanelOrder();
  store.settings.stats_panel_order = order;
  api.updateSettings({ stats_panel_order: order }).catch(() => {
    /* сохранение не критично — при следующей перетаскивании повторим */
  });
}

/** Инициализировать drag-and-drop для панелей статистики. */
function initDragAndDrop() {
  const container = $(PANELS_CONTAINER);
  if (!container) return;

  let dragged = null;
  // Флаг: mousedown произошёл на заголовке панели (а не на графике/таблице/кнопке).
  let grabFromHead = false;

  container.querySelectorAll('[data-panel]').forEach((panel) => {
    panel.setAttribute('draggable', 'true');
  });

  // Запоминаем, начато ли перетаскивание с заголовка.
  container.addEventListener('mousedown', (event) => {
    if (event.target.closest('button, a, input, select, textarea')) {
      grabFromHead = false;
      return;
    }
    grabFromHead = !!event.target.closest('.panel-head');
  });

  container.addEventListener('dragstart', (event) => {
    const panel = event.target.closest('[data-panel]');
    if (!panel || !container.contains(panel) || !grabFromHead) {
      event.preventDefault();
      return;
    }
    dragged = panel;
    panel.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', panel.dataset.panel);
    }
  });

  container.addEventListener('dragover', (event) => {
    if (!dragged) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    const target = event.target.closest('[data-panel]');
    if (!target || target === dragged) return;

    const rect = target.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const midX = rect.left + rect.width / 2;
    // Если курсор заметно выше/ниже центра — вставляем по вертикали,
    // иначе ориентируемся по горизонтали (внутри ряда).
    const insertAfter = Math.abs(event.clientY - midY) > 8
      ? event.clientY > midY
      : event.clientX > midX;

    if (insertAfter) {
      if (target.nextElementSibling !== dragged) target.after(dragged);
    } else if (target.previousElementSibling !== dragged) {
      target.before(dragged);
    }
  });

  const endDrag = () => {
    grabFromHead = false;
    if (dragged) {
      dragged.classList.remove('is-dragging');
      dragged = null;
      savePanelOrder();
      window.setTimeout(resizeAll, 30);
    }
  };
  container.addEventListener('dragend', endDrag);
  container.addEventListener('drop', (event) => {
    event.preventDefault();
    endDrag();
  });
}

export async function refresh() {
  applySavedOrder();
  const grid = $('#kpi-grid');
  if (grid && !state.loaded) {
    clear(grid).append(...Array.from({ length: 9 }, () => h('div', { class: 'skeleton' })));
  }

  const params = currentParams();

  try {
    const [summary, bankroll, compare] = await Promise.all([
      api.statsSummary(params),
      api.bankrollSummary().catch(() => null),
      api.statsCompare(params).catch(() => null),
    ]);
    state.loaded = true;
    renderKpis(summary, bankroll);
    renderStreaks(summary);
    renderStatsCharts(summary, store.currency);
    renderTables(summary);
    renderMonths(summary);
    renderCompare(compare);
    window.setTimeout(resizeAll, 30);
  } catch (error) {
    notifyError(error);
  }
}

function syncFiltersFromInputs() {
  const from = $('#stats-from');
  const to = $('#stats-to');
  state.from = from ? from.value : '';
  state.to = to ? to.value : '';
  if (state.from || state.to) state.preset = 'custom';
}

function markActiveChip() {
  document.querySelectorAll('#range-chips .chip').forEach((chip) => {
    chip.classList.toggle('is-active', chip.dataset.range === state.preset);
  });
}

export function init() {
  initDragAndDrop();

  const chips = $('#range-chips');
  if (chips) {
    chips.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      state.preset = chip.dataset.range;
      if (state.preset !== 'custom') {
        state.from = '';
        state.to = '';
        const from = $('#stats-from');
        const to = $('#stats-to');
        if (from) from.value = '';
        if (to) to.value = '';
      }
      markActiveChip();
      refresh();
    });
  }

  const applyBtn = $('#stats-apply');
  if (applyBtn) {
    applyBtn.addEventListener('click', () => {
      syncFiltersFromInputs();
      if (!state.from && !state.to && state.preset === 'custom') state.preset = '30d';
      markActiveChip();
      refresh();
    });
  }

  const sport = $('#stats-sport');
  if (sport) sport.addEventListener('change', () => { state.sport = sport.value; refresh(); });
  const source = $('#stats-source');
  if (source) source.addEventListener('change', () => { state.sourceId = source.value; refresh(); });

  ['#stats-from', '#stats-to'].forEach((selector) => {
    const input = $(selector);
    if (input) input.addEventListener('change', () => { syncFiltersFromInputs(); markActiveChip(); refresh(); });
  });

  const exportBtn = $('#stats-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      exportBtn.disabled = true;
      try {
        await api.exportStats(currentParams());
        toast('Экспорт готов', 'Файл CSV сохранён', 'ok');
      } catch (error) {
        notifyError(error);
      } finally {
        exportBtn.disabled = false;
      }
    });
  }
}

/** Обновить справочники фильтров из store. */
export function syncFilterOptions() {
  fillSportSelect($('#stats-sport'), { value: state.sport });
  fillSourceSelect($('#stats-source'), { value: state.sourceId });
  const options = store.options || {};
  const from = $('#stats-from');
  const to = $('#stats-to');
  if (from && options.date_min) from.min = options.date_min;
  if (to && options.date_max) to.max = options.date_max;
}
