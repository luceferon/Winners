/* Общие утилиты: DOM, форматирование, уведомления, модальные окна. */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/** Создать элемент: h('div', {class: 'x'}, [child, 'текст']). */
export function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// --- форматирование ---------------------------------------------------------
const CURRENCY_SIGNS = { RUB: '₽', USD: '$', EUR: '€', KZT: '₸', BYN: 'Br', UAH: '₴' };

export function currencySign(code) {
  return CURRENCY_SIGNS[code] || code || '';
}

export function fmtMoney(value, currency = 'RUB', { sign = false } = {}) {
  const number = Number(value || 0);
  const body = Math.abs(number).toLocaleString('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  const prefix = sign && number > 0 ? '+' : number < 0 ? '−' : '';
  return `${prefix}${body} ${currencySign(currency)}`.trim();
}

export function fmtNum(value, digits = 0) {
  return Number(value || 0).toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPct(value, digits = 1) {
  return `${Number(value || 0).toFixed(digits)}%`;
}

export function fmtCoef(value) {
  const number = Number(value || 0);
  return number ? number.toFixed(2) : '—';
}

function parseDate(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function fmtDate(value) {
  const date = parseDate(value);
  if (!date) return '—';
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function fmtDateTime(value, { withSeconds = false } = {}) {
  const date = parseDate(value);
  if (!date) return '—';
  const options = {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  };
  if (withSeconds) options.second = '2-digit';
  return date.toLocaleString('ru-RU', options);
}

export function fmtTime(value) {
  const date = parseDate(value);
  if (!date) return '—';
  return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

/** «5 минут назад», «2 дня назад». */
export function fmtAgo(value) {
  const date = parseDate(value);
  if (!date) return '—';
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return 'только что';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} дн назад`;
  return fmtDate(date);
}

/** Локальное время → строка для input[type=datetime-local]. */
export function toLocalInputValue(value) {
  const date = parseDate(value) || new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function toIsoOrNull(localValue) {
  if (!localValue) return null;
  const date = new Date(localValue);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function todayIso() {
  const date = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// --- справочники ------------------------------------------------------------
export const STATUS_LABELS = {
  pending: 'Активная',
  won: 'Выигрышная',
  lost: 'Проигрышная',
  push: 'Возврат',
  cancelled: 'Отменена',
};

/** Статусы отдельного события экспресса (ноги). */
export const LEG_STATUS_LABELS = {
  pending: 'Ожидается',
  won: 'Зашла',
  lost: 'Не зашла',
  push: 'Возврат',
};

/** Короткие метки статусов для бейджа «последняя ставка источника». */
export const LAST_BET_LABELS = {
  pending: 'активна',
  won: 'зашла',
  lost: 'не зашла',
  push: 'возврат',
  cancelled: 'отменена',
};

export const EVENT_STATUS_LABELS = {
  scheduled: 'Предстоящее',
  live: 'В игре',
  finished: 'Завершено',
  cancelled: 'Отменено',
};

/** Типы операций по счёту (баланс). */
export const CASH_FLOW_LABELS = {
  deposit: 'Пополнение',
  withdrawal: 'Вывод',
};

function needLabels(labels, kind) {
  return labels[kind] || kind || '—';
}

/** Бейдж статуса ставки. */
export function statusBadge(bet) {
  const status = bet.status || 'pending';
  return h('span', { class: `badge ${status}` }, needLabels(STATUS_LABELS, status));
}

export function eventBadge(event) {
  const status = (event && event.status) || 'scheduled';
  return h('span', { class: `badge event-${status}` }, needLabels(EVENT_STATUS_LABELS, status));
}

export function statusLabel(status) {
  return needLabels(STATUS_LABELS, status);
}

// --- уведомления ------------------------------------------------------------
export function toast(title, message = '', kind = 'info', timeout = 4200) {
  const host = $('#toasts');
  if (!host) return;
  const node = h('div', { class: `toast ${kind}` }, [
    h('div', {}, [h('strong', {}, title), message ? h('span', {}, message) : null]),
  ]);
  host.append(node);
  window.setTimeout(() => {
    node.style.transition = 'opacity .2s, transform .2s';
    node.style.opacity = '0';
    node.style.transform = 'translateX(16px)';
    window.setTimeout(() => node.remove(), 220);
  }, timeout);
}

export function notifyError(error) {
  const message = error && error.message ? error.message : 'Неизвестная ошибка';
  toast('Ошибка', message, 'err', 6000);
}

// --- модальные окна ---------------------------------------------------------
export function openModal({ title, body, footer, onClose }) {
  const backdrop = h('div', { class: 'modal-backdrop' });
  const close = () => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
    if (onClose) onClose();
  };
  const onKey = (event) => { if (event.key === 'Escape') close(); };

  const modal = h('div', { class: 'modal' }, [
    h('div', { class: 'modal-head' }, [
      h('h3', {}, title),
      h('button', { class: 'icon-btn mini', type: 'button', title: 'Закрыть', onclick: close }, '✕'),
    ]),
    h('div', { class: 'modal-body' }, body || []),
    footer ? h('div', { class: 'modal-foot' }, footer) : null,
  ]);
  backdrop.append(modal);
  backdrop.addEventListener('mousedown', (event) => { if (event.target === backdrop) close(); });
  document.addEventListener('keydown', onKey);
  document.body.append(backdrop);
  return { close, root: modal };
}

/** Подтверждение действия собственным модальным окном. */
export function confirmDialog({ title, message, confirmText = 'Подтвердить', danger = false }) {
  return new Promise((resolve) => {
    // resolve(true) вызывается до handle.close(): закрытие окна вызывает onClose → resolve(false),
    // а повторный resolve игнорируется, поэтому порядок важен.
    const confirmBtn = h('button', {
      class: `btn ${danger ? 'danger' : 'primary'}`,
      type: 'button',
      onclick: () => { resolve(true); handle.close(); },
    }, confirmText);

    const handle = openModal({
      title,
      body: h('p', { class: 'hint' }, message),
      footer: [
        h('button', { class: 'btn ghost', type: 'button', onclick: () => { handle.close(); resolve(false); } }, 'Отмена'),
        confirmBtn,
      ],
      onClose: () => resolve(false),
    });
    confirmBtn.focus();
  });
}

// --- прочее -----------------------------------------------------------------
export function debounce(fn, delay = 320) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

export function skeletonRows(count = 4) {
  return Array.from({ length: count }, () => h('div', { class: 'skeleton' }));
}

export function emptyState(title, hint = '') {
  return h('div', { class: 'empty' }, [
    h('strong', {}, title),
    hint ? h('span', {}, hint) : null,
  ]);
}

// --- иконки -----------------------------------------------------------------
const ICONS = {
  check: 'M20 6 9 17l-5-5',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  edit: 'M4 20h4l10-10-4-4L4 16v4zM14 6l4 4',
  link: 'M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1',
  info: 'M12 16v-5M12 8h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',
  plus: 'M12 5v14M5 12h14',
  copy: 'M9 9h10v10H9zM15 5H5v10',
};

/** SVG-иконка из набора (namespace-safe). */
export function iconSvg(name, viewBox = '0 0 24 24') {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', viewBox);
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', ICONS[name] || ICONS.info);
  svg.append(path);
  return svg;
}

/** Компактная кнопка с иконкой. */
export function iconBtn(name, title, onClick, extraClass = 'mini') {
  return h('button', {
    class: `icon-btn ${extraClass}`,
    type: 'button',
    title,
    onclick: onClick,
  }, [iconSvg(name)]);
}
