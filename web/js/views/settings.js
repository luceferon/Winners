/* Раздел «Настройки»: источники, уведомления и объекты отображения. */

import { api } from '../api.js';
import {
  $, h, clear, fmtMoney, fmtNum, notifyError, emptyState,
  iconBtn, openModal, confirmDialog, toast,
} from '../util.js';
import { store, loadSettings, loadSources, notifyDataChanged } from '../store.js';

const state = { sort: 'name' };

// --- декларативные поля -----------------------------------------------------
const BLOCKS = {
  display: {
    save: 'Сохранить уведомления и отображение',
    fields: [
      { key: 'notifications_enabled', type: 'switch', label: 'Уведомления о результатах ставок' },
      { key: 'notify_on_settle', type: 'switch', label: 'Сообщать о рассчитанных ставках' },
      { key: 'currency', type: 'options', label: 'Валюта', options: [['RUB', 'Рубль ₽'], ['USD', 'Доллар $'], ['EUR', 'Евро €'], ['KZT', 'Тенге ₸']] },
      { key: 'default_range', type: 'options', label: 'Период статистики по умолчанию', options: [['7d', '7 дней'], ['30d', '30 дней'], ['90d', '90 дней'], ['365d', 'Год'], ['all', 'Всё время']] },
      { key: 'theme', type: 'options', label: 'Тема оформления', options: [['dark', 'Тёмная'], ['light', 'Светлая']] },
      { key: 'stats_show_roi', type: 'switch', label: 'Показывать ROI в сводке' },
      { key: 'compact_tables', type: 'switch', label: 'Компактные таблицы' },
    ],
  },
  bankroll: {
    save: 'Сохранить лимиты банкролла',
    fields: [
      { key: 'bankroll_goal', type: 'number', label: 'Цель по банкроллу (0 — выключено)', min: 0, step: 100 },
      { key: 'stop_loss_percent', type: 'number', label: 'Stop-loss, % от пика (0 — выключено)', min: 0, max: 100, step: 1 },
      { key: 'max_stake_percent', type: 'number', label: 'Максимум на ставку, % банкролла (0 — выключено)', min: 0, max: 100, step: 1 },
    ],
  },
};

function buildField(field, value) {
  let getter;

  if (field.type === 'switch') {
    const toggle = h('button', {
      class: `switch ${value ? 'is-on' : ''}`,
      type: 'button',
      role: 'switch',
      'aria-checked': value ? 'true' : 'false',
    });
    toggle.addEventListener('click', () => {
      const on = !toggle.classList.contains('is-on');
      toggle.classList.toggle('is-on', on);
      toggle.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    getter = () => toggle.classList.contains('is-on');
    return { node: h('div', { class: 'switch-row' }, [h('span', {}, field.label), toggle]), getter };
  }

  let control;
  if (field.type === 'options') {
    control = h('select', { class: 'input', name: field.key }, field.options.map(([key, label]) => new Option(label, key)));
    control.value = value === undefined || value === null ? '' : String(value);
    if (!control.value && field.options.length) control.value = field.options[0][0];
  } else {
    control = h('input', {
      class: 'input',
      name: field.key,
      type: field.type === 'number' ? 'number' : 'text',
      min: field.min,
      max: field.max,
      step: field.step || (field.type === 'number' ? 1 : null),
      placeholder: field.placeholder || '',
    });
    control.value = value === undefined || value === null || typeof value === 'object'
      ? ''
      : String(value);
  }
  getter = () => {
    if (field.type === 'number') {
      const number = Number(control.value);
      return Number.isNaN(number) ? 0 : number;
    }
    return control.value;
  };

  return { node: h('label', { class: 'field' }, [h('span', {}, field.label), control]), getter };
}

function renderBlock(selector, blockKey) {
  const host = $(selector);
  if (!host) return;
  const block = BLOCKS[blockKey];
  const values = store.settings || {};
  const getters = [];

  clear(host);
  block.fields.forEach((field) => {
    const { node, getter } = buildField(field, values[field.key]);
    getters.push({ key: field.key, get: getter });
    host.append(node);
  });

  const saveBtn = h('button', { class: 'btn primary', type: 'button' }, block.save);
  saveBtn.addEventListener('click', async () => {
    const payload = {};
    getters.forEach(({ key, get }) => { payload[key] = get(); });
    saveBtn.disabled = true;
    try {
      const data = await api.updateSettings(payload);
      store.settings = data.values || {};
      store.meta = data.meta || {};
      store.currency = store.settings.currency || 'RUB';
      toast('Настройки сохранены', `${payloadKeysText(payload)}`, 'ok');
      applyTheme(store.settings.theme);
      notifyDataChanged('settings');
    } catch (error) {
      notifyError(error);
    } finally {
      saveBtn.disabled = false;
    }
  });

  host.append(h('div', { class: 'form-actions' }, [saveBtn]));
}

function payloadKeysText(payload) {
  return `Обновлено параметров: ${Object.keys(payload).length}`;
}

// --- источники --------------------------------------------------------------
function sourceRow(source) {
  const currency = store.currency;
  const profit = Number(source.payout || 0) - Number(source.staked || 0);
  return h('tr', {}, [
    h('td', { class: 'strong' }, [
      source.name,
      source.url ? h('div', { class: 'muted', style: 'font-size:11.5px' }, source.url) : null,
    ]),
    h('td', { class: 'num' },
      source.reliability === null || source.reliability === undefined
        ? '—'
        : `${fmtNum(source.reliability, 1)}%`),
    h('td', { class: 'num' }, fmtNum(source.bets_count)),
    h('td', { class: `num strong ${profit > 0 ? 'pos' : profit < 0 ? 'neg' : ''}` }, fmtMoney(profit, currency, { sign: true })),
    h('td', {}, [h('span', { class: `badge ${source.enabled ? 'won' : 'cancelled'}` }, source.enabled ? 'активен' : 'выключен')]),
    h('td', { class: 'actions' }, [
      iconBtn('edit', 'Изменить источник', () => openSourceModal(source)),
      iconBtn('trash', 'Удалить источник', () => removeSource(source)),
    ]),
  ]);
}

function renderSources() {
  const host = $('#sources-table');
  if (!host) return;
  clear(host);
  const sources = store.sources || [];
  if (!sources.length) {
    host.append(emptyState('Источники не добавлены', 'Нажмите «Добавить источник», чтобы создать первый.'));
    return;
  }
  host.append(h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', {}, 'Источник'),
      h('th', { class: 'num', title: 'Доля выигранных ставок среди выигранных и проигранных' }, 'Надёжность'),
      h('th', { class: 'num' }, 'Ставок'),
      h('th', { class: 'num' }, 'Результат'),
      h('th', {}, 'Статус'),
      h('th', { class: 'num' }, ''),
    ])]),
    h('tbody', {}, sources.map(sourceRow)),
  ]));
}

function openSourceModal(source = null) {
  const isEdit = Boolean(source);
  const data = source || {};

  const name = h('input', { class: 'input', name: 'name', placeholder: 'Например: Букмекерская линия', value: data.name || '' });
  const url = h('input', { class: 'input', name: 'url', placeholder: 'https://…', value: data.url || '' });
  const notes = h('textarea', { class: 'input', name: 'notes', rows: '2', placeholder: 'Заметка' });
  notes.value = data.notes || '';
  const enabled = h('button', {
    class: `switch ${data.enabled === false ? '' : 'is-on'}`,
    type: 'button',
  });
  enabled.addEventListener('click', () => enabled.classList.toggle('is-on'));

  const error = h('em', { class: 'err' });

  const modal = openModal({
    title: isEdit ? `Источник: ${data.name}` : 'Новый источник ставок',
    body: h('form', {
      class: 'form',
      onsubmit: (event) => { event.preventDefault(); save(); },
    }, [
      h('label', { class: 'field' }, [h('span', {}, 'Название *'), name]),
      h('label', { class: 'field' }, [h('span', {}, 'Сайт'), url]),
      h('label', { class: 'field' }, [h('span', {}, 'Комментарий'), notes]),
      h('div', { class: 'switch-row' }, [h('span', {}, 'Источник активен'), enabled]),
      error,
    ]),
    footer: [
      h('button', { class: 'btn ghost', type: 'button', onclick: () => modal.close() }, 'Отмена'),
      h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Сохранить'),
    ],
  });

  async function save() {
    error.textContent = '';
    const payload = {
      name: name.value.trim(),
      url: url.value.trim() || null,
      notes: notes.value.trim() || null,
      enabled: enabled.classList.contains('is-on'),
    };
    if (!payload.name || payload.name.length < 2) {
      error.textContent = 'Укажите название источника (минимум 2 символа)';
      return;
    }

    try {
      if (isEdit) await api.updateSource(data.id, payload);
      else await api.createSource(payload);
      modal.close();
      toast('Сохранено', isEdit ? 'Источник обновлён' : 'Источник добавлен', 'ok');
      await loadSources();
      renderSources();
      notifyDataChanged('sources');
    } catch (err) {
      error.textContent = err.message;
    }
  }
}

async function removeSource(source) {
  const ok = await confirmDialog({
    title: 'Удалить источник?',
    message: `«${source.name}» будет удалён. Связанные ставки сохранятся, но потеряют привязку к источнику.`,
    confirmText: 'Удалить',
    danger: true,
  });
  if (!ok) return;
  try {
    const result = await api.deleteSource(source.id);
    toast('Удалено', result.message || 'Источник удалён', 'ok');
    await loadSources();
    renderSources();
    notifyDataChanged('sources');
  } catch (error) {
    notifyError(error);
  }
}

// --- тема -------------------------------------------------------------------
function applyTheme(theme) {
  const value = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', value);
  store.theme = value;
  window.dispatchEvent(new CustomEvent('winners:theme', { detail: value }));
}

// --- публичное API раздела --------------------------------------------------
export function init() {
  const addBtn = $('#btn-add-source');
  if (addBtn) addBtn.addEventListener('click', () => openSourceModal(null));

  const sortSelect = $('#sources-sort');
  if (sortSelect) {
    state.sort = sortSelect.value || 'name';
    sortSelect.addEventListener('change', async () => {
      state.sort = sortSelect.value;
      try {
        await loadSources({ sort: state.sort });
        renderSources();
      } catch (error) {
        notifyError(error);
      }
    });
  }

  const demoBtn = $('#btn-load-demo');
  if (demoBtn) {
    demoBtn.addEventListener('click', async () => {
      const ok = await confirmDialog({
        title: 'Загрузить демо-данные?',
        message: 'Демонстрационный набор добавится к текущим данным.',
        confirmText: 'Загрузить',
      });
      if (!ok) return;
      try {
        const result = await api.loadDemo();
        toast('Демо-данные загружены', result.created ? `Ставок: ${result.bets ?? '—'}` : (result.reason || ''), 'ok');
        await loadSettings();
        await loadSources();
        await refresh();
        notifyDataChanged();
      } catch (error) {
        notifyError(error);
      }
    });
  }

  const resetBtn = $('#btn-reset-settings');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      const ok = await confirmDialog({
        title: 'Сбросить настройки?',
        message: 'Все параметры вернутся к значениям по умолчанию.',
        confirmText: 'Сбросить',
      });
      if (!ok) return;
      try {
        await api.resetSettings();
        await loadSettings();
        applyTheme(store.settings.theme);
        toast('Настройки сброшены', 'Параметры возвращены к значениям по умолчанию', 'ok');
        await refresh();
        notifyDataChanged('settings');
      } catch (error) {
        notifyError(error);
      }
    });
  }

  const wipeBtn = $('#btn-wipe');
  if (wipeBtn) {
    wipeBtn.addEventListener('click', async () => {
      const ok = await confirmDialog({
        title: 'Удалить все данные?',
        message: 'Будут удалены все ставки и операции по счёту. Источники сохранятся. Действие необратимо.',
        confirmText: 'Удалить всё',
        danger: true,
      });
      if (!ok) return;
      try {
        const result = await api.wipeData(true);
        toast('Данные удалены',
          `Ставок: ${result.deleted?.bets ?? 0}`,
          'ok');
        await refresh();
        notifyDataChanged();
      } catch (error) {
        notifyError(error);
      }
    });
  }
}

export async function refresh() {
  renderBlock('#settings-display', 'display');
  renderBlock('#settings-bankroll', 'bankroll');

  const sortSelect = $('#sources-sort');
  if (sortSelect) {
    state.sort = sortSelect.value || state.sort;
    sortSelect.value = state.sort;
  }
  try {
    await loadSources({ sort: state.sort });
  } catch (error) {
    notifyError(error);
  }
  renderSources();
}
