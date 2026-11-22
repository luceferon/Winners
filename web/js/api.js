/* Обёртка над REST API приложения. */

const JSON_HEADERS = { 'Content-Type': 'application/json' };

function buildQuery(params) {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    search.append(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function request(path, { method = 'GET', body, params } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers = { ...JSON_HEADERS };
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path + buildQuery(params), options);
  } catch (error) {
    throw new Error('Сервер недоступен. Проверьте, что приложение запущено.');
  }

  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }

  if (!response.ok) {
    const detail = data && typeof data === 'object' ? data.detail : data;
    throw new Error(formatError(detail) || `Ошибка запроса (${response.status})`);
  }
  return data;
}

function formatError(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
  }
  return detail.message || JSON.stringify(detail);
}

function todayStamp() {
  const date = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Скачать файл с сервера (экспорт CSV) и отдать его браузеру. */
async function download(path, params, filename) {
  let response;
  try {
    response = await fetch(path + buildQuery(params));
  } catch (error) {
    throw new Error('Сервер недоступен. Проверьте, что приложение запущено.');
  }
  if (!response.ok) {
    let detail = null;
    try { detail = (await response.json()).detail; } catch { /* тело может быть не JSON */ }
    throw new Error(formatError(detail) || `Ошибка экспорта (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  // --- статистика
  statsSummary: (params) => request('/api/stats/summary', { params }),
  statsOptions: () => request('/api/stats/options'),
  statsCompare: (params) => request('/api/stats/compare', { params }),
  exportStats: (params) => download('/api/stats/export', params, `winners-stats-${todayStamp()}.csv`),

  // --- ставки
  listBets: (params) => request('/api/bets', { params }),
  getBet: (id) => request(`/api/bets/${id}`),
  createBet: (payload) => request('/api/bets', { method: 'POST', body: payload }),
  updateBet: (id, payload) => request(`/api/bets/${id}`, { method: 'PUT', body: payload }),
  deleteBet: (id) => request(`/api/bets/${id}`, { method: 'DELETE' }),
  setResult: (id, payload) => request(`/api/bets/${id}/result`, { method: 'PATCH', body: payload }),
  setLegResult: (id, legId, payload) => request(`/api/bets/${id}/legs/${legId}/result`, { method: 'PATCH', body: payload }),
  duplicateBet: (id) => request(`/api/bets/${id}/duplicate`, { method: 'POST' }),
  bulkBets: (payload) => request('/api/bets/bulk', { method: 'POST', body: payload }),
  suggestBets: (params) => request('/api/bets/suggest', { params }),
  settlementsFeed: (params) => request('/api/bets/settlements/feed', { params }),
  exportBets: (params) => download('/api/bets/export', params, `winners-bets-${todayStamp()}.csv`),

  // --- источники
  listSources: (params) => request('/api/sources', { params }),
  createSource: (payload) => request('/api/sources', { method: 'POST', body: payload }),
  updateSource: (id, payload) => request(`/api/sources/${id}`, { method: 'PUT', body: payload }),
  deleteSource: (id) => request(`/api/sources/${id}`, { method: 'DELETE' }),

  // --- настройки
  getSettings: () => request('/api/settings'),
  updateSettings: (values) => request('/api/settings', { method: 'PUT', body: { values } }),
  resetSettings: () => request('/api/settings/reset', { method: 'POST' }),
  testTelegram: () => request('/api/settings/telegram/test', { method: 'POST' }),

  // --- баланс (банкролл)
  bankrollSummary: () => request('/api/bankroll/summary'),
  bankrollCurve: () => request('/api/bankroll/curve'),
  listCashFlows: (params) => request('/api/bankroll/operations', { params }),
  createCashFlow: (payload) => request('/api/bankroll/operations', { method: 'POST', body: payload }),
  updateCashFlow: (id, payload) => request(`/api/bankroll/operations/${id}`, { method: 'PUT', body: payload }),
  deleteCashFlow: (id) => request(`/api/bankroll/operations/${id}`, { method: 'DELETE' }),

  // --- система
  health: () => request('/api/health'),
  loadDemo: () => request('/api/system/demo', { method: 'POST' }),
  wipeData: (keepSources = false) => request('/api/system/data', { method: 'DELETE', params: { keep_sources: keepSources } }),
};
