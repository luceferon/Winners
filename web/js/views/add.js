/* Раздел «Новая ставка»: ручной ввод одиночной ставки и экспресса. */

import { api } from '../api.js';
import {
  $, $$, h, clear, fmtCoef, fmtMoney, fmtPct,
  notifyError, emptyState, iconBtn, statusBadge, toast, debounce,
  toLocalInputValue, toIsoOrNull, LEG_STATUS_LABELS, LAST_BET_LABELS,
} from '../util.js';
import { store, notifyDataChanged } from '../store.js';

const state = {
  kind: 'single',
  suggestions: [],
  bankroll: null,
  sizingAmount: 0,
  screenshotToken: null, // тестовая фича: токен скриншота для Telegram
};

// --- валидация формы --------------------------------------------------------
function setFieldError(name, message) {
  const host = document.querySelector(`#bet-form [data-err="${name}"]`);
  if (host) host.textContent = message || '';
  const field = host ? host.closest('.field') : null;
  if (field) field.classList.toggle('is-invalid', Boolean(message));
}

function clearErrors() {
  ['sport', 'source', 'event', 'coefficient', 'stake', 'legs'].forEach((name) => setFieldError(name, ''));
}

function readForm() {
  return {
    sport: $('#bet-sport').value.trim(),
    event_name: $('#bet-event').value.trim(),
    coefficient: $('#bet-coef').value,
    stake: $('#bet-stake').value,
    source_id: $('#bet-source').value,
    prediction: $('#bet-prediction').value.trim(),
    comment: $('#bet-comment').value.trim(),
    created_at: $('#bet-date').value,
  };
}

// --- состав экспресса -------------------------------------------------------
/** Прочитать заполненные строки событий экспресса. */
function readLegs() {
  const host = $('#express-legs');
  if (!host) return [];
  return Array.from(host.querySelectorAll('.leg-row')).map((row) => ({
    event_name: row.querySelector('.leg-event').value.trim(),
    prediction: row.querySelector('.leg-prediction').value.trim(),
    coefficient: Number(row.querySelector('.leg-coef').value),
    status: row.querySelector('.leg-status').value,
  }));
}

/** Одна строка события экспресса: событие, прогноз, коэффициент и результат. */
function legRow(leg = {}) {
  const coefInput = h('input', {
    class: 'input leg-coef', type: 'number', step: '0.01', min: '1.01', placeholder: '1.80',
  });
  coefInput.value = leg.coefficient != null ? String(leg.coefficient) : '';

  const statusSelect = h('select', { class: 'input leg-status' },
    Object.entries(LEG_STATUS_LABELS).map(([value, label]) => new Option(label, value)));
  statusSelect.value = leg.status || 'pending';

  const row = h('div', { class: 'leg-row' }, [
    h('input', { class: 'input leg-event', placeholder: 'Зенит — Спартак', value: leg.event_name || '' }),
    h('input', { class: 'input leg-prediction', placeholder: 'П1', value: leg.prediction || '' }),
    coefInput,
    statusSelect,
    iconBtn('trash', 'Убрать событие', () => { row.remove(); updateTotal(); }),
  ]);
  return row;
}

function addLegRow(leg = {}) {
  const host = $('#express-legs');
  if (!host) return;
  host.append(legRow(leg));
}

/** В экспрессе должно быть минимум два события — добавляем заготовки. */
function ensureLegRows() {
  const host = $('#express-legs');
  if (!host) return;
  while (host.querySelectorAll('.leg-row').length < 2) addLegRow();
}

/** Итоговый коэффициент экспресса: произведение кэфов, возврат считается за 1.00. */
function expressCoefficient() {
  let value = 1;
  for (const leg of readLegs()) {
    if (!leg.coefficient || leg.coefficient <= 1) continue;
    if (leg.status === 'push') continue;
    value *= leg.coefficient;
  }
  return value;
}

function validate(data) {
  clearErrors();
  let ok = true;

  if (data.sport.length < 2) { setFieldError('sport', 'Выберите вид спорта из списка'); ok = false; }

  if (state.kind === 'express') {
    const legs = readLegs();
    if (legs.length < 2) {
      setFieldError('legs', 'В экспрессе должно быть не меньше двух событий');
      ok = false;
    }
    legs.forEach((leg, index) => {
      if (leg.event_name.length < 3) {
        setFieldError('legs', `Событие №${index + 1}: укажите название (минимум 3 символа)`);
        ok = false;
      } else if (!leg.coefficient || Number.isNaN(leg.coefficient) || leg.coefficient <= 1) {
        setFieldError('legs', `Событие №${index + 1}: коэффициент должен быть больше 1.00`);
        ok = false;
      }
    });
  } else {
    if (data.event_name.length < 3) { setFieldError('event', 'Укажите название события (минимум 3 символа)'); ok = false; }
    const coefficient = Number(data.coefficient);
    if (!data.coefficient || Number.isNaN(coefficient) || coefficient <= 1) {
      setFieldError('coefficient', 'Коэффициент должен быть больше 1.00');
      ok = false;
    }
  }

  const stake = Number(data.stake);
  if (!data.stake || Number.isNaN(stake) || stake <= 0) {
    setFieldError('stake', 'Сумма ставки должна быть больше 0');
    ok = false;
  }

  return ok;
}

function updateTotal() {
  const host = $('#bet-total');
  if (!host) return;
  const stake = Number($('#bet-stake').value) || 0;

  if (state.kind === 'express') {
    const legs = readLegs();
    if (!legs.length) { host.textContent = ''; return; }
    const coefficient = expressCoefficient();
    if (legs.some((leg) => leg.status === 'lost')) {
      host.textContent = 'Экспресс проигран: выплата 0';
      return;
    }
    const parts = [`Коэф. экспресса: ${fmtCoef(coefficient)}`];
    if (stake > 0) {
      const payout = coefficient * stake;
      parts.push(`выплата ${fmtMoney(payout, store.currency)}`);
      parts.push(`прибыль ${fmtMoney(payout - stake, store.currency, { sign: true })}`);
    }
    host.textContent = parts.join(' · ');
    return;
  }

  const coefficient = Number($('#bet-coef').value);
  if (!coefficient || !stake || coefficient <= 1 || stake <= 0) {
    host.textContent = '';
    return;
  }
  host.textContent = `Потенциальная выплата: ${fmtMoney(coefficient * stake, store.currency)} (прибыль ${fmtMoney(coefficient * stake - stake, store.currency, { sign: true })})`;
}

// --- подсказка о последней ставке источника --------------------------------
/** Показать результат и сумму последней ставки выбранного источника. */
function renderSourceLast() {
  const hint = $('#bet-source-last');
  if (!hint) return;
  const select = $('#bet-source');
  const id = select ? Number(select.value) : 0;
  const source = id ? store.sources.find((item) => item.id === id) : null;
  if (!source || !source.last_status) {
    hint.textContent = '';
    return;
  }
  const label = LAST_BET_LABELS[source.last_status] || source.last_status;
  const stake = source.last_stake != null ? ` · ${fmtMoney(source.last_stake, store.currency)}` : '';
  hint.textContent = `Последняя ставка: ${label}${stake}`;
}

// --- автодополнение событий ------------------------------------------------
/** Наполнить datalist подсказками из ранее введённых событий. */
function renderEventOptions(items) {
  const list = $('#event-list');
  if (!list) return;
  clear(list).append(...items.map((item) => new Option(item.event_name, item.event_name)));
}

/** Запросить подсказки по частичному названию (с задержкой, чтобы не дёргать API). */
const fetchSuggestions = debounce(async (query) => {
  try {
    const data = await api.suggestBets({ q: query, limit: 8 });
    state.suggestions = data.items || [];
    renderEventOptions(state.suggestions);
  } catch {
    /* подсказки не критичны — молча пропускаем */
  }
}, 250);

/** При выборе события подставить коэффициент, прогноз и источник из похожей ставки. */
function applyEventSuggestion() {
  const input = $('#bet-event');
  if (!input) return;
  const name = input.value.trim();
  if (!name) return;
  const match = state.suggestions.find((item) => item.event_name === name);
  if (!match) return;

  if (match.sport) {
    const sport = $('#bet-sport');
    if (sport) { ensureSportOption(sport, match.sport); sport.value = match.sport; }
  }
  const coef = $('#bet-coef');
  if (coef && match.coefficient) coef.value = String(match.coefficient);
  const prediction = $('#bet-prediction');
  if (prediction && match.prediction) prediction.value = match.prediction;
  const source = $('#bet-source');
  if (source && match.source_id) source.value = String(match.source_id);

  renderSourceLast();
  handleFormChange();
}

// --- калькулятор размера ставки --------------------------------------------
const SIZING_MODES = {
  manual: { param: false },
  flat: { param: true, label: '% банкролла', placeholder: '2' },
  kelly: { param: true, label: 'Оценка вероятности, %', placeholder: '40' },
};

/** Коэффициент для расчёта: у одиночной — из поля, у экспресса — произведение. */
function currentCoefficient() {
  return state.kind === 'express' ? expressCoefficient() : Number($('#bet-coef').value) || 0;
}

/** Показать/скрыть поле параметра и пересчитать сумму по выбранному режиму. */
function updateSizingMode() {
  const mode = $('#sizing-mode') ? $('#sizing-mode').value : 'manual';
  const config = SIZING_MODES[mode] || SIZING_MODES.manual;
  const field = $('#sizing-param-field');
  const label = $('#sizing-param-label');
  const param = $('#sizing-param');
  if (field) field.classList.toggle('hidden', !config.param);
  if (label && config.label) label.textContent = config.label;
  if (param && config.placeholder) param.placeholder = config.placeholder;
  renderSizing();
}

/** Пересчитать рекомендуемую сумму от текущего банкролла и коэффициента. */
function renderSizing() {
  const bankrollEl = $('#sizing-bankroll');
  const resultEl = $('#sizing-result');
  const hintEl = $('#sizing-hint');
  if (!bankrollEl || !resultEl) return;

  const balance = state.bankroll ? Number(state.bankroll.balance) || 0 : 0;
  bankrollEl.textContent = fmtMoney(balance, store.currency);

  const mode = $('#sizing-mode') ? $('#sizing-mode').value : 'manual';
  const param = Number($('#sizing-param') ? $('#sizing-param').value : 0);
  const coefficient = currentCoefficient();

  const setResult = (amount, hint = '') => {
    state.sizingAmount = amount > 0 ? Math.round(amount * 100) / 100 : 0;
    resultEl.textContent = state.sizingAmount ? fmtMoney(state.sizingAmount, store.currency) : '—';
    if (hintEl) hintEl.textContent = hint;
  };

  if (mode === 'manual') {
    setResult(0, 'Введите сумму вручную или выберите режим расчёта.');
    return;
  }
  if (!balance) {
    setResult(0, 'Банкролл равен нулю — добавьте пополнение на вкладке «Баланс».');
    return;
  }
  if (!coefficient || coefficient <= 1) {
    setResult(0, 'Укажите коэффициент больше 1.00 для расчёта.');
    return;
  }

  let amount = 0;
  let hint = '';
  if (mode === 'flat') {
    if (!param) { setResult(0, 'Укажите процент банкролла.'); return; }
    amount = (balance * param) / 100;
    hint = `${fmtPct(param)} от банкролла ${fmtMoney(balance, store.currency)}.`;
  } else if (mode === 'kelly') {
    if (!param) { setResult(0, 'Укажите оценку вероятности прохода в процентах.'); return; }
    const probability = Math.min(Math.max(param, 0), 100) / 100;
    const b = coefficient - 1;
    const fraction = (b * probability - (1 - probability)) / b;
    if (fraction <= 0) {
      setResult(0, 'По Kelly ставка не рекомендуется: вероятность ниже безубыточной.');
      return;
    }
    amount = balance * fraction;
    hint = `Kelly: доля банкролла ${fmtPct(fraction * 100)} при кф ${fmtCoef(coefficient)} и вероятности ${fmtPct(param)}.`;
  }

  const limits = state.bankroll && state.bankroll.limits ? state.bankroll.limits : {};
  if (limits.max_stake_percent && amount > (limits.max_stake_amount || 0)) {
    hint += ` Внимание: превышен лимит максимальной ставки ${fmtPct(limits.max_stake_percent)} (${fmtMoney(limits.max_stake_amount, store.currency)}).`;
  }
  setResult(amount, hint);
}

/** Подставить рассчитанную сумму в поле «Сумма ставки». */
function applySizing() {
  if (!state.sizingAmount || state.sizingAmount <= 0) {
    toast('Нет расчёта', 'Заполните коэффициент и параметры калькулятора', 'warn');
    return;
  }
  const stake = $('#bet-stake');
  if (!stake) return;
  stake.value = String(state.sizingAmount);
  updateTotal();
  toast('Сумма подставлена', fmtMoney(state.sizingAmount, store.currency), 'ok', 2600);
}

/** Согласованное обновление итога и калькулятора при изменении формы. */
function handleFormChange() {
  updateTotal();
  renderSizing();
}

// --- распознавание ставки со скриншота -------------------------------------
/** Взять картинку из буфера браузера (если доступ и разрешение есть). */
async function clipboardImageBlob() {
  if (!navigator.clipboard || !navigator.clipboard.read) return null;
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find((value) => value.startsWith('image/'));
      if (type) return await item.getType(type);
    }
  } catch {
    /* нет прав или буфер пуст — распознаем картинку на стороне сервера */
  }
  return null;
}

/** Заполнить поля формы распознанными данными. */
function applyRecognized(data) {
  if (data.kind === 'express' && Array.isArray(data.legs) && data.legs.length) {
    applyExpressRecognized(data);
    return;
  }

  setKind('single');
  const event = $('#bet-event');
  if (event && data.event_name) event.value = data.event_name;
  const prediction = $('#bet-prediction');
  if (prediction && data.prediction) prediction.value = data.prediction;
  const coef = $('#bet-coef');
  if (coef && data.coefficient != null) coef.value = String(data.coefficient);
  const stake = $('#bet-stake');
  if (stake && data.stake != null) stake.value = String(data.stake);
  handleFormChange();
}

/** Заполнить форму распознанным экспрессом: строки событий и сумма ставки. */
function applyExpressRecognized(data) {
  setKind('express');
  const host = $('#express-legs');
  if (host) clear(host);
  data.legs.forEach((leg) => addLegRow({
    event_name: leg.event_name || '',
    prediction: leg.prediction || '',
    coefficient: leg.coefficient != null ? leg.coefficient : undefined,
  }));
  const stake = $('#bet-stake');
  if (stake && data.stake != null) stake.value = String(data.stake);
  handleFormChange();
}

/** Кнопка «Вставить ставку»: распознать скриншот и заполнить форму. */
async function pasteBetFromImage(event) {
  const button = event && event.currentTarget ? event.currentTarget : $('#btn-paste-bet');
  if (button) { button.disabled = true; button.textContent = 'Распознавание…'; }
  try {
    const blob = await clipboardImageBlob();
    const data = await api.recognizeBet(blob);
    const recognized = data.kind === 'express'
      ? Array.isArray(data.legs) && data.legs.length > 0
      : ['event_name', 'prediction', 'coefficient', 'stake']
        .some((key) => data[key] != null && data[key] !== '');
    if (!recognized) {
      toast('Не удалось распознать', 'На скриншоте не найдены поля ставки', 'warn');
      return;
    }
    applyRecognized(data);
    // тестовая фича: сохраняем токен скриншота, чтобы отправить фото в Telegram
    state.screenshotToken = data.screenshot_token || null;
    if (data.kind === 'express') {
      toast('Экспресс распознан', `${data.legs.length} событий`, 'ok', 2600);
    } else {
      const coef = data.coefficient != null ? ` @ ${fmtCoef(data.coefficient)}` : '';
      toast('Ставка распознана', `${data.event_name || 'без названия'}${coef}`, 'ok', 2600);
    }
  } catch (error) {
    notifyError(error);
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Вставить ставку'; }
  }
}

// --- активные ставки --------------------------------------------------------
function activeItem(bet) {
  const currency = store.currency;
  const isExpress = bet.kind === 'express';
  const legs = bet.legs || [];
  const subtitle = [
    isExpress ? `экспресс · ${legs.length} событий` : bet.sport,
    bet.prediction ? `прогноз: ${bet.prediction}` : 'прогноз не указан',
    bet.source_name || 'без источника',
  ].join(' · ');

  const detail = isExpress
    ? `не рассчитано: ${legs.filter((leg) => leg.status === 'pending').length} из ${legs.length}`
    : 'результат ожидается';

  return h('div', { class: 'active-item' }, [
    h('div', { class: 'active-main' }, [
      h('strong', { title: bet.event_name }, bet.event_name),
      h('span', {}, subtitle),
      h('span', {}, detail),
    ]),
    h('div', { class: 'active-side' }, [
      h('strong', {}, `≈ ${fmtMoney(bet.potential_payout, currency)}`),
      h('span', {}, `кф ${fmtCoef(bet.coefficient)} · ${fmtMoney(bet.stake, currency)}`),
    ]),
    h('div', {}, [statusBadge(bet)]),
  ]);
}

async function refreshActive() {
  const host = $('#active-list');
  if (!host) return;
  try {
    const pending = await api.listBets({
      status: 'pending',
      limit: 100,
      sort: 'created_at',
      order: 'desc',
    });
    const items = pending.items || [];

    clear(host);
    if (!items.length) {
      host.append(emptyState('Активных ставок нет', 'Добавьте ставку, чтобы следить за ней.'));
      return;
    }
    host.append(...items.map(activeItem));
  } catch (error) {
    notifyError(error);
  }
}

// --- отправка формы ---------------------------------------------------------
async function submitForm(event) {
  event.preventDefault();
  const data = readForm();
  if (!validate(data)) {
    toast('Проверьте форму', 'Некоторые поля заполнены неверно', 'warn');
    return;
  }

  const payload = {
    kind: state.kind,
    sport: data.sport,
    stake: Number(data.stake),
    comment: data.comment || null,
    created_at: toIsoOrNull(data.created_at),
  };
  // тестовая фича: токен скриншота для отправки фото в Telegram
  if (state.screenshotToken) payload.screenshot_token = state.screenshotToken;
  if (state.kind === 'express') {
    payload.legs = readLegs().map((leg) => ({
      event_name: leg.event_name,
      prediction: leg.prediction || null,
      coefficient: leg.coefficient,
      status: leg.status,
    }));
  } else {
    payload.event_name = data.event_name;
    payload.coefficient = Number(data.coefficient);
    payload.prediction = data.prediction || null;
  }
  if (data.source_id && data.source_id !== '') payload.source_id = Number(data.source_id);

  const submit = $('#bet-submit');
  if (submit) { submit.disabled = true; submit.textContent = 'Сохранение…'; }

  try {
    const bet = await api.createBet(payload);
    toast(state.kind === 'express' ? 'Экспресс добавлен' : 'Ставка добавлена',
      `${bet.event_name} — ${fmtMoney(bet.stake, store.currency)} @ ${fmtCoef(bet.coefficient)}`, 'ok');
    const form = $('#bet-form');
    if (form) form.reset();
    clearFormExtras();
    state.screenshotToken = null;
    await refreshActive();
    notifyDataChanged('bets');
  } catch (error) {
    notifyError(error);
  } finally {
    if (submit) { submit.disabled = false; submit.textContent = 'Сохранить ставку'; }
  }
}

/** Переключить вид ставки: одиночная или экспресс. */
function setKind(kind) {
  state.kind = kind === 'express' ? 'express' : 'single';

  $$('#bet-kind-switch .chip').forEach((chip) => {
    chip.classList.toggle('is-active', chip.dataset.kind === state.kind);
  });

  const single = $('#single-fields');
  if (single) single.classList.toggle('hidden', state.kind !== 'single');
  const express = $('#express-fields');
  if (express) express.classList.toggle('hidden', state.kind !== 'express');
  const coefField = $('#bet-coef-field');
  if (coefField) coefField.classList.toggle('hidden', state.kind === 'express');
  const predictionField = $('#bet-prediction-field');
  if (predictionField) predictionField.classList.toggle('hidden', state.kind === 'express');

  if (state.kind === 'express') ensureLegRows();
  clearErrors();
  updateTotal();
  renderSizing();
}

function clearFormExtras() {
  clearErrors();
  const legs = $('#express-legs');
  if (legs) clear(legs);
  const total = $('#bet-total');
  if (total) total.textContent = '';
  const date = $('#bet-date');
  if (date) date.value = toLocalInputValue(new Date());
  renderSourceLast();
  setKind('single');
  renderSizing();
}

export function init() {
  const form = $('#bet-form');
  if (form) {
    form.addEventListener('submit', submitForm);
    form.addEventListener('reset', () => window.setTimeout(clearFormExtras, 0));
    ['#bet-coef', '#bet-stake'].forEach((selector) => {
      const input = $(selector);
      if (input) input.addEventListener('input', handleFormChange);
    });
  }

  const kindSwitch = $('#bet-kind-switch');
  if (kindSwitch) {
    kindSwitch.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (chip) setKind(chip.dataset.kind);
    });
  }

  const sourceSelect = $('#bet-source');
  if (sourceSelect) sourceSelect.addEventListener('change', renderSourceLast);

  const eventInput = $('#bet-event');
  if (eventInput) {
    eventInput.addEventListener('input', () => fetchSuggestions(eventInput.value.trim()));
    eventInput.addEventListener('change', applyEventSuggestion);
    eventInput.addEventListener('focus', () => {
      if (!state.suggestions.length) fetchSuggestions(eventInput.value.trim());
    });
  }

  const addLegBtn = $('#btn-add-leg');
  if (addLegBtn) addLegBtn.addEventListener('click', () => { addLegRow(); handleFormChange(); });

  const pasteBtn = $('#btn-paste-bet');
  if (pasteBtn) pasteBtn.addEventListener('click', pasteBetFromImage);

  const legsHost = $('#express-legs');
  if (legsHost) {
    legsHost.addEventListener('input', handleFormChange);
    legsHost.addEventListener('change', handleFormChange);
  }

  const sizingMode = $('#sizing-mode');
  if (sizingMode) sizingMode.addEventListener('change', updateSizingMode);

  const sizingParam = $('#sizing-param');
  if (sizingParam) sizingParam.addEventListener('input', renderSizing);

  const sizingApply = $('#sizing-apply');
  if (sizingApply) sizingApply.addEventListener('click', applySizing);

  updateSizingMode();
  clearFormExtras();
}

export async function refresh() {
  try {
    state.bankroll = await api.bankrollSummary();
  } catch {
    state.bankroll = null;
  }
  renderSizing();
  await refreshActive();
}

/** Виды спорта: справочник из meta с резервом из статистики. */
function sportList() {
  if (store.meta.sports && store.meta.sports.length) return store.meta.sports;
  return store.options.sports || [];
}

/** Гарантировать наличие вида спорта в списке (например, при редактировании). */
function ensureSportOption(select, sport) {
  if (!select || !sport) return;
  if (!Array.from(select.options).some((option) => option.value === sport)) {
    select.append(new Option(sport, sport));
  }
}

/** Заполнить справочники формы из store. */
export function syncFormOptions() {
  const sportSelect = $('#bet-sport');
  if (sportSelect) {
    const current = sportSelect.value;
    sportSelect.replaceChildren(new Option('— выберите вид спорта —', ''));
    sportList().forEach((sport) => sportSelect.append(new Option(sport, sport)));
    if (current) ensureSportOption(sportSelect, current);
    sportSelect.value = current || '';
  }

  const select = $('#bet-source');
  if (select) {
    const current = select.value;
    select.replaceChildren(new Option('— без источника —', ''));
    store.sources.forEach((source) => {
      const label = source.enabled ? source.name : `${source.name} (выкл.)`;
      select.append(new Option(label, String(source.id)));
    });
    if (current) select.value = current;
  }

  renderSourceLast();
}
