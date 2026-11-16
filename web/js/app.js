/* Точка входа SPA «Winners»: навигация, тема, обновление данных, горячие клавиши. */

import { api } from './api.js';
import { $, $$, fmtDateTime, fmtTime, notifyError, toast } from './util.js';
import { store, loadSettings, loadSources, loadOptions } from './store.js';
import { disposeAll, resizeAll } from './charts.js';
import * as statsView from './views/stats.js';
import * as historyView from './views/history.js';
import * as addView from './views/add.js';
import * as balanceView from './views/balance.js';
import * as settingsView from './views/settings.js';

const VIEWS = {
  stats: {
    title: 'Общая статистика',
    subtitle: 'Сводка по всем ставкам за выбранный период',
    module: statsView,
    needsOptions: true,
  },
  history: {
    title: 'История ставок',
    subtitle: 'Полный список ставок с фильтрацией, поиском и сортировкой',
    module: historyView,
    needsOptions: true,
  },
  add: {
    title: 'Новая ставка',
    subtitle: 'Ручной ввод данных о новой ставке',
    module: addView,
    needsOptions: true,
  },
  balance: {
    title: 'Баланс счёта',
    subtitle: 'Пополнения и выводы средств',
    module: balanceView,
    needsOptions: false,
  },
  settings: {
    title: 'Настройки',
    subtitle: 'Источники ставок и уведомления',
    module: settingsView,
    needsOptions: false,
  },
};

const state = {
  view: 'stats',
  lastSettledAt: null,
  statusTimer: null,
  notifyTimer: null,
};

// --- навигация --------------------------------------------------------------
function setActiveNav(name) {
  $$('#nav .nav-item').forEach((item) => {
    item.classList.toggle('is-active', item.dataset.view === name);
  });
  $$('.views .view').forEach((view) => {
    view.classList.toggle('is-active', view.id === `view-${name}`);
  });
}

async function switchView(name) {
  if (!VIEWS[name]) return;
  state.view = name;
  const config = VIEWS[name];
  setActiveNav(name);

  const title = $('#view-title');
  const subtitle = $('#view-subtitle');
  if (title) title.textContent = config.title;
  if (subtitle) subtitle.textContent = config.subtitle;
  document.title = `Winners — ${config.title}`;

  closeSidebar();
  // Справочники берём из store: данные могли измениться в другом разделе.
  if (config.needsOptions) syncOptionLists();
  await config.module.refresh();
  window.setTimeout(resizeAll, 40);
}

/** Пересобрать справочники фильтров и форм из актуального store. */
function syncOptionLists() {
  statsView.syncFilterOptions();
  historyView.syncFilterOptions();
  addView.syncFormOptions();
}

function openSidebar() {
  const sidebar = $('#sidebar');
  if (sidebar) sidebar.classList.add('is-open');
}

function closeSidebar() {
  const sidebar = $('#sidebar');
  if (sidebar) sidebar.classList.remove('is-open');
}

// --- горячие клавиши --------------------------------------------------------
/** Фокус находится в поле ввода — горячие клавиши нужно игнорировать. */
function isTypingTarget(target) {
  if (!target) return false;
  const tag = (target.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'select' || tag === 'textarea' || target.isContentEditable;
}

function setupHotkeys() {
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeSidebar();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (isTypingTarget(event.target)) return;
    if (document.querySelector('.modal-backdrop')) return;

    if (event.key === 'n') {
      event.preventDefault();
      switchView('add').then(() => {
        const field = $('#bet-event') || $('#bet-sport');
        if (field) field.focus();
      });
    } else if (event.key === '/') {
      event.preventDefault();
      switchView('history').then(() => {
        const search = $('#history-search');
        if (search) search.focus();
      });
    }
  });
}

// --- тема -------------------------------------------------------------------
function applyTheme(theme, { persist = false } = {}) {
  const value = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', value);
  store.theme = value;
  disposeAll();
  window.setTimeout(() => { if (state.view === 'stats') statsView.refresh(); }, 30);
  if (persist) {
    api.updateSettings({ theme: value }).catch(() => {});
  }
}

// --- статус связи с сервером ------------------------------------------------
function renderStatus(health) {
  const dot = $('#server-dot');
  const text = $('#server-status-text');
  const hint = $('#server-status-hint');
  const version = $('#app-version');
  const freshness = $('#freshness');

  const counts = health.counts || {};

  if (dot && text && hint) {
    dot.classList.remove('is-on', 'is-warn', 'is-off');
    dot.classList.add('is-on');
    text.textContent = 'Сервер доступен';
    hint.textContent = `Активных ставок: ${counts.active ?? 0}`;
  }

  if (version) version.textContent = `Winners v${health.version} · ставок: ${counts.bets ?? 0}`;
  if (freshness) {
    freshness.textContent = `Ставок ${counts.bets ?? 0} · активных ${counts.active ?? 0} · ${fmtTime(new Date())}`;
  }
}

async function refreshStatus() {
  try {
    const health = await api.health();
    renderStatus(health);
  } catch (error) {
    const dot = $('#server-dot');
    const text = $('#server-status-text');
    if (dot) { dot.classList.remove('is-on', 'is-warn'); dot.classList.add('is-off'); }
    if (text) text.textContent = 'Нет связи с сервером';
  }
}

// --- уведомления о результатах ---------------------------------------------
async function checkSettlements() {
  if (!store.settings.notifications_enabled || !store.settings.notify_on_settle) return;
  try {
    const data = await api.settlementsFeed({
      since: state.lastSettledAt ? state.lastSettledAt.toISOString() : null,
      limit: 10,
    });
    const items = data.items || [];
    if (!state.lastSettledAt) {
      state.lastSettledAt = new Date();
      return;
    }
    if (!items.length) return;

    state.lastSettledAt = new Date();
    const newest = items[0];
    toast('Ставка рассчитана',
      `${newest.event_name}: ${newest.status === 'won' ? 'выигрыш' : newest.status === 'lost' ? 'проигрыш' : 'возврат'}`
      + (items.length > 1 ? ` · ещё ${items.length - 1}` : ''),
      newest.status === 'won' ? 'ok' : newest.status === 'lost' ? 'warn' : 'info', 7000);
    await refreshStatus();
  } catch {
    /* уведомления не критичны — молча пропускаем */
  }
}

// --- обновление -------------------------------------------------------------
export async function refreshAll() {
  try {
    await loadSettings();
    await Promise.all([loadSources(), loadOptions()]);
  } catch (error) {
    notifyError(error);
    return;
  }

  applyTheme(store.settings.theme || 'dark');

  syncOptionLists();

  await refreshStatus();
  await VIEWS[state.view].module.refresh();
  window.setTimeout(resizeAll, 60);
}

// --- запуск -----------------------------------------------------------------
async function boot() {
  const nav = $('#nav');
  if (nav) {
    nav.addEventListener('click', (event) => {
      const item = event.target.closest('.nav-item');
      if (item && item.dataset.view && item.dataset.view !== state.view) {
        switchView(item.dataset.view);
      }
    });
  }

  const menuToggle = $('#menu-toggle');
  if (menuToggle) menuToggle.addEventListener('click', openSidebar);

  document.addEventListener('click', (event) => {
    const sidebar = $('#sidebar');
    if (!sidebar || !sidebar.classList.contains('is-open')) return;
    if (sidebar.contains(event.target) || (menuToggle && menuToggle.contains(event.target))) return;
    closeSidebar();
  });

  const refreshBtn = $('#btn-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    await refreshAll();
    refreshBtn.disabled = false;
    toast('Данные обновлены', fmtDateTime(new Date(), { withSeconds: true }), 'info', 2500);
  });

  const themeBtn = $('#btn-theme');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const next = store.theme === 'light' ? 'dark' : 'light';
    applyTheme(next, { persist: true });
    toast('Тема изменена', next === 'light' ? 'Светлая тема' : 'Тёмная тема', 'info', 2200);
  });

  window.addEventListener('resize', () => resizeAll());
  window.addEventListener('winners:theme', () => disposeAll());
  // Изменения в любом разделе обновляют справочники других вкладок и счётчики без перезагрузки.
  window.addEventListener('winners:data-changed', async () => {
    try {
      await loadSources();
    } catch (error) {
      notifyError(error);
    }
    syncOptionLists();
    await refreshStatus();
  });

  statsView.init();
  historyView.init();
  addView.init();
  balanceView.init();
  settingsView.init();

  setupHotkeys();

  await refreshAll();
  state.lastSettledAt = new Date();

  state.statusTimer = window.setInterval(refreshStatus, 20000);
  state.notifyTimer = window.setInterval(checkSettlements, 45000);

  window.addEventListener('beforeunload', () => {
    window.clearInterval(state.statusTimer);
    window.clearInterval(state.notifyTimer);
  });
}

document.addEventListener('DOMContentLoaded', boot);
