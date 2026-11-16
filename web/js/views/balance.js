/* Раздел «Баланс»: пополнения/выводы и текущие средства. */

import { api } from '../api.js';
import {
  $, h, clear, fmtMoney, fmtNum, fmtPct, fmtDate, toLocalInputValue, toIsoOrNull,
  notifyError, emptyState, iconBtn, openModal, confirmDialog, toast, CASH_FLOW_LABELS,
} from '../util.js';
import { store, notifyDataChanged } from '../store.js';
import { renderBalanceChart, resizeAll } from '../charts.js';

const state = { loaded: false };

function kpiCard({ label, value, sub, tone = '', valueClass = '' }) {
  return h('article', { class: `kpi ${tone}` }, [
    h('div', { class: 'kpi-label' }, label),
    h('div', { class: `kpi-value ${valueClass}` }, value),
    sub ? h('div', { class: 'kpi-sub' }, sub) : null,
  ]);
}

function renderKpis(summary) {
  const grid = $('#balance-kpis');
  if (!grid) return;
  const currency = summary.currency || store.currency;
  const balance = summary.balance || 0;
  clear(grid).append(...[
    kpiCard({
      label: 'Текущий баланс',
      value: fmtMoney(balance, currency),
      sub: `всего с учётом ставок в игре: ${fmtMoney(summary.total, currency)}`,
      tone: 'tone-win',
      valueClass: balance >= 0 ? 'pos' : 'neg',
    }),
    kpiCard({
      label: 'Пополнено',
      value: fmtMoney(summary.deposits, currency),
      sub: 'за всё время',
      valueClass: 'pos',
    }),
    kpiCard({
      label: 'Выведено',
      value: fmtMoney(summary.withdrawals, currency),
      sub: 'за всё время',
      valueClass: 'neg',
    }),
    kpiCard({
      label: 'В игре',
      value: fmtMoney(summary.in_play, currency),
      sub: `оборот: ${fmtMoney(summary.staked, currency)}`,
      tone: 'tone-push',
    }),
    kpiCard({
      label: 'Результат ставок',
      value: fmtMoney(summary.profit, currency, { sign: true }),
      sub: `возвращено: ${fmtMoney(summary.returned, currency)}`,
      valueClass: (summary.profit || 0) >= 0 ? 'pos' : 'neg',
    }),
    kpiCard({
      label: 'Yield',
      value: fmtPct(summary.yield_percent),
      sub: 'доходность на оборот рассчитанных ставок',
      valueClass: (summary.yield_percent || 0) >= 0 ? 'pos' : 'neg',
    }),
    kpiCard({
      label: 'ROI на банкролл',
      value: fmtPct(summary.roi_percent),
      sub: `средний банкролл: ${fmtMoney(summary.avg_balance, currency)}`,
      valueClass: (summary.roi_percent || 0) >= 0 ? 'pos' : 'neg',
    }),
  ]);
}

/** Панель «Цели и лимиты»: прогресс к цели, stop-loss и максимальная ставка. */
function renderLimits(limits) {
  const host = $('#balance-limits');
  if (!host) return;
  clear(host);
  const currency = store.currency;
  const data = limits || {};
  const goal = Number(data.bankroll_goal || 0);
  const stopLoss = Number(data.stop_loss_percent || 0);
  const maxStake = Number(data.max_stake_percent || 0);

  if (!goal && !stopLoss && !maxStake) {
    host.append(emptyState(
      'Лимиты не заданы',
      'Укажите цель по банкроллу, stop-loss и максимальный размер ставки в разделе «Настройки».',
    ));
    return;
  }

  const row = (label, value, hint) => h('tr', {}, [
    h('td', { class: 'strong' }, label),
    h('td', { class: 'num' }, value),
    h('td', { class: 'muted' }, hint),
  ]);

  const body = [];
  if (goal) {
    body.push(row(
      'Цель по банкроллу',
      fmtMoney(goal, currency),
      `прогресс ${fmtPct(data.goal_progress_percent)}`,
    ));
  }
  if (stopLoss) {
    body.push(row(
      'Stop-loss',
      `${fmtPct(stopLoss)} от пика`,
      `уровень: ${fmtMoney(data.stop_loss_level, currency)}`,
    ));
  }
  if (maxStake) {
    body.push(row(
      'Макс. размер ставки',
      `${fmtPct(maxStake)} банкролла`,
      `не более ${fmtMoney(data.max_stake_amount, currency)}`,
    ));
  }

  host.append(h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', {}, 'Параметр'),
      h('th', { class: 'num' }, 'Значение'),
      h('th', {}, 'Детали'),
    ])]),
    h('tbody', {}, body),
  ]));
}

function operationRow(flow) {
  const currency = store.currency;
  const isDeposit = flow.kind === 'deposit';
  return h('tr', {}, [
    h('td', {}, fmtDate(flow.occurred_at)),
    h('td', {}, h('span', { class: `badge ${flow.kind}` }, CASH_FLOW_LABELS[flow.kind] || flow.kind)),
    h('td', { class: `num strong ${isDeposit ? 'pos' : 'neg'}` },
      `${isDeposit ? '+' : '−'}${fmtMoney(flow.amount, currency)}`),
    h('td', { class: 'muted' }, flow.note || '—'),
    h('td', { class: 'actions' }, [
      iconBtn('edit', 'Изменить операцию', () => openFlowModal(flow)),
      iconBtn('trash', 'Удалить операцию', () => removeFlow(flow)),
    ]),
  ]);
}

function renderTable(flows) {
  const host = $('#balance-table');
  if (!host) return;
  clear(host);
  if (!flows.length) {
    host.append(emptyState('Операций пока нет', 'Добавьте пополнение или вывод средств.'));
    return;
  }
  host.append(h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', {}, 'Дата'),
      h('th', {}, 'Тип'),
      h('th', { class: 'num' }, 'Сумма'),
      h('th', {}, 'Комментарий'),
      h('th', { class: 'num' }, ''),
    ])]),
    h('tbody', {}, flows.map(operationRow)),
  ]));
}

function openFlowModal(flow) {
  const kind = h('select', { class: 'input' }, [
    new Option(CASH_FLOW_LABELS.deposit, 'deposit'),
    new Option(CASH_FLOW_LABELS.withdrawal, 'withdrawal'),
  ]);
  kind.value = flow.kind;
  const amount = h('input', { class: 'input', type: 'number', step: '0.01', min: '0.01' });
  amount.value = String(flow.amount);
  const date = h('input', { class: 'input', type: 'datetime-local' });
  date.value = toLocalInputValue(flow.occurred_at);
  const note = h('input', { class: 'input', placeholder: 'Комментарий' });
  note.value = flow.note || '';
  const error = h('em', { class: 'err' });

  const modal = openModal({
    title: 'Операция по счёту',
    body: h('form', { class: 'form', onsubmit: (event) => { event.preventDefault(); save(); } }, [
      h('label', { class: 'field' }, [h('span', {}, 'Тип операции'), kind]),
      h('label', { class: 'field' }, [h('span', {}, 'Сумма *'), amount]),
      h('label', { class: 'field' }, [h('span', {}, 'Дата'), date]),
      h('label', { class: 'field' }, [h('span', {}, 'Комментарий'), note]),
      error,
    ]),
    footer: [
      h('button', { class: 'btn ghost', type: 'button', onclick: () => modal.close() }, 'Отмена'),
      h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Сохранить'),
    ],
  });

  async function save() {
    error.textContent = '';
    const value = Number(amount.value);
    if (!value || value <= 0) {
      error.textContent = 'Укажите сумму больше нуля';
      return;
    }
    try {
      await api.updateCashFlow(flow.id, {
        kind: kind.value,
        amount: value,
        occurred_at: toIsoOrNull(date.value),
        note: note.value.trim() || null,
      });
      modal.close();
      toast('Операция обновлена', '', 'ok');
      await refresh();
      notifyDataChanged('bankroll');
    } catch (err) {
      error.textContent = err.message;
    }
  }
}

async function removeFlow(flow) {
  const ok = await confirmDialog({
    title: 'Удалить операцию?',
    message: `${CASH_FLOW_LABELS[flow.kind] || flow.kind} на сумму ${fmtMoney(flow.amount, store.currency)} будет удалена.`,
    confirmText: 'Удалить',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteCashFlow(flow.id);
    toast('Операция удалена', '', 'ok');
    await refresh();
    notifyDataChanged('bankroll');
  } catch (error) {
    notifyError(error);
  }
}

async function submitOperation() {
  const kind = $('#flow-kind');
  const amount = $('#flow-amount');
  const date = $('#flow-date');
  const note = $('#flow-note');
  const errNode = $('[data-err="flow-amount"]');
  if (errNode) errNode.textContent = '';

  const value = Number(amount.value);
  if (!value || value <= 0) {
    if (errNode) errNode.textContent = 'Укажите сумму больше нуля';
    return;
  }
  try {
    await api.createCashFlow({
      kind: kind.value,
      amount: value,
      occurred_at: toIsoOrNull(date.value),
      note: note.value.trim() || null,
    });
    toast('Операция добавлена', CASH_FLOW_LABELS[kind.value] || '', 'ok');
    amount.value = '';
    note.value = '';
    date.value = toLocalInputValue(new Date());
    await refresh();
    notifyDataChanged('bankroll');
  } catch (error) {
    notifyError(error);
  }
}

export function init() {
  const operationForm = $('#balance-operation-form');
  if (operationForm) {
    operationForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      await submitOperation();
    });
  }
  const date = $('#flow-date');
  if (date) date.value = toLocalInputValue(new Date());
}

export async function refresh() {
  const grid = $('#balance-kpis');
  if (grid && !state.loaded) {
    clear(grid).append(...Array.from({ length: 7 }, () => h('div', { class: 'skeleton' })));
  }
  try {
    const [summary, operations, curve] = await Promise.all([
      api.bankrollSummary(),
      api.listCashFlows({ limit: 200 }),
      api.bankrollCurve().catch(() => ({ points: [] })),
    ]);
    state.loaded = true;
    store.currency = summary.currency || store.currency;
    renderKpis(summary);
    renderLimits(summary.limits);
    renderTable(operations.items || []);
    renderBalanceChart(curve.points || [], store.currency);
    window.setTimeout(resizeAll, 30);
  } catch (error) {
    notifyError(error);
  }
}
