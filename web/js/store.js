/* Разделяемое состояние приложения. */

import { api } from './api.js';

export const store = {
  settings: {},
  meta: {},
  sources: [],
  options: { sports: [], sources: [], date_min: null, date_max: null, bets_count: 0 },
  currency: 'RUB',
  theme: 'dark',
};

export async function loadSettings() {
  const data = await api.getSettings();
  store.settings = data.values || {};
  store.meta = data.meta || {};
  store.currency = store.settings.currency || 'RUB';
  return data;
}

export async function loadSources(options) {
  store.sources = await api.listSources(options);
  return store.sources;
}

export async function loadOptions() {
  store.options = await api.statsOptions();
  return store.options;
}

export function sourceOptions() {
  return store.sources.filter((source) => source.enabled);
}

/** Оповестить разделы об изменении данных: справочники и счётчики обновляются без перезагрузки страницы. */
export function notifyDataChanged(scope = 'all') {
  window.dispatchEvent(new CustomEvent('winners:data-changed', { detail: { scope } }));
}

/** Наполнить select вида спорта. */
export function fillSportSelect(select, { includeAll = true, value = 'all' } = {}) {
  if (!select) return;
  const sports = store.meta.sports && store.meta.sports.length
    ? store.meta.sports
    : (store.options.sports || []);
  select.replaceChildren();
  if (includeAll) select.append(new Option('Все виды спорта', 'all'));
  sports.forEach((sport) => select.append(new Option(sport, sport)));
  select.value = value;
}

/** Наполнить select источников. */
export function fillSourceSelect(select, { includeAll = true, placeholder = 'Все источники', value = '' } = {}) {
  if (!select) return;
  select.replaceChildren();
  if (includeAll) select.append(new Option(placeholder, '0'));
  else select.append(new Option('— без источника —', ''));
  store.sources.forEach((source) => {
    const label = source.enabled ? source.name : `${source.name} (выкл.)`;
    select.append(new Option(label, String(source.id)));
  });
  select.value = value === '' ? (includeAll ? '0' : '') : String(value);
}
