/* Построение графиков ECharts для раздела статистики. */

import { fmtMoney, fmtNum, fmtPct, fmtCoef } from './util.js';


const echarts = window.echarts;
const registry = new Map();

function css(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function palette() {
  return {
    text: css('--text', '#e6edf6'),
    dim: css('--text-dim', '#9aa8bb'),
    mute: css('--text-mute', '#6b7888'),
    line: css('--border', '#263040'),
    grid: css('--border-soft', '#1e2734'),
    surface: css('--surface', '#161d27'),
    accent: css('--accent', '#4f8cff'),
    accent2: css('--accent-2', '#7c5cff'),
    win: css('--win', '#2fbf71'),
    loss: css('--loss', '#ef5b5b'),
    warn: css('--warn', '#f0a33c'),
    push: css('--push', '#58a6d8'),
    neutral: css('--neutral', '#8b96a7'),
  };
}

const STATUS_COLORS = { pending: 'accent', won: 'win', lost: 'loss', push: 'push', cancelled: 'neutral' };

function baseOption() {
  const c = palette();
  return {
    color: [c.accent, c.win, c.loss, c.warn, c.accent2, c.push, c.neutral],
    textStyle: { color: c.text, fontFamily: 'Segoe UI, Inter, sans-serif', fontSize: 11.5 },
    animationDuration: 420,
    grid: { left: 8, right: 14, top: 28, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.surface,
      borderColor: c.line,
      borderWidth: 1,
      textStyle: { color: c.text, fontSize: 12 },
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(120,140,170,0.09)' } },
    },
  };
}

function axisCommon() {
  const c = palette();
  return {
    axisLine: { lineStyle: { color: c.line } },
    axisTick: { show: false },
    axisLabel: { color: c.mute, fontSize: 11 },
    splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
  };
}

function legendCommon() {
  const c = palette();
  return { textStyle: { color: c.dim, fontSize: 11.5 }, top: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 8 };
}

export function ensureChart(id) {
  const node = document.getElementById(id);
  if (!node) return null;
  let chart = registry.get(id);
  if (!chart || chart.isDisposed()) {
    chart = echarts.init(node, null, { renderer: 'canvas' });
    registry.set(id, chart);
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(() => { if (!chart.isDisposed()) chart.resize(); });
      observer.observe(node);
    }
  }
  return chart;
}

function setOption(id, option) {
  const chart = ensureChart(id);
  if (!chart) return;
  chart.setOption({ ...baseOption(), ...option }, true);
}

function showEmpty(id, message) {
  const chart = ensureChart(id);
  if (!chart) return;
  const c = palette();
  chart.clear();
  chart.setOption({
    backgroundColor: 'transparent',
    title: {
      text: message,
      left: 'center',
      top: 'middle',
      textStyle: { color: c.mute, fontSize: 12, fontWeight: 400 },
    },
  });
}

export function resizeAll() {
  registry.forEach((chart) => { if (!chart.isDisposed()) chart.resize(); });
}

export function disposeAll() {
  registry.forEach((chart) => { if (!chart.isDisposed()) chart.dispose(); });
  registry.clear();
}

// --- отдельные графики ------------------------------------------------------
function timelineOption(timeline, currency) {
  const c = palette();
  const option = baseOption();
  const dates = timeline.map((row) => row.date);
  return {
    ...option,
    legend: { ...legendCommon(), data: ['Профит за день', 'Накопленный итог'] },
    grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: dates,
      ...axisCommon(),
      splitLine: { show: false },
      axisLabel: {
        color: c.mute,
        fontSize: 10.5,
        formatter: (value) => value.slice(5),
        hideOverlap: true,
      },
    },
    yAxis: [
      { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
      { type: 'value', ...axisCommon(), splitLine: { show: false }, axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    ],
    series: [
      {
        name: 'Профит за день',
        type: 'bar',
        data: timeline.map((row) => ({
          value: row.profit,
          itemStyle: { color: row.profit >= 0 ? c.win : c.loss, borderRadius: 3 },
        })),
        barMaxWidth: 18,
      },
      {
        name: 'Накопленный итог',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.2, color: c.accent },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(79,140,255,0.28)' },
              { offset: 1, color: 'rgba(79,140,255,0.02)' },
            ],
          },
        },
        data: timeline.map((row) => row.cumulative_profit),
      },
    ],
    tooltip: {
      ...option.tooltip,
      formatter: (params) => {
        const date = params[0] ? params[0].axisValue : '';
        const lines = params.map((item) => {
          const color = item.color;
          const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px"></span>`;
          return `${dot}${item.seriesName}: <b>${fmtMoney(item.value, currency, { sign: true })}</b>`;
        });
        return `<b>${date}</b><br>${lines.join('<br>')}`;
      },
    },
  };
}

function drawdownOption(timeline, currency) {
  const c = palette();
  const option = baseOption();
  const dates = timeline.map((row) => row.date);
  return {
    ...option,
    legend: { ...legendCommon(), data: ['Накопленный итог', 'Просадка от пика'] },
    grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: dates,
      ...axisCommon(),
      splitLine: { show: false },
      axisLabel: { color: c.mute, fontSize: 10.5, formatter: (value) => value.slice(5), hideOverlap: true },
    },
    yAxis: { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    series: [
      {
        name: 'Просадка от пика',
        type: 'line',
        symbol: 'none',
        lineStyle: { width: 0 },
        areaStyle: { color: 'rgba(239,91,91,0.18)' },
        itemStyle: { color: c.loss },
        data: timeline.map((row) => row.drawdown ?? 0),
      },
      {
        name: 'Накопленный итог',
        type: 'line',
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.2, color: c.accent },
        data: timeline.map((row) => row.cumulative_profit),
      },
    ],
    tooltip: {
      ...option.tooltip,
      formatter: (params) => {
        const date = params[0] ? params[0].axisValue : '';
        const lines = params.map((item) => {
          const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${item.color};margin-right:6px"></span>`;
          return `${dot}${item.seriesName}: <b>${fmtMoney(item.value, currency, { sign: true })}</b>`;
        });
        return `<b>${date}</b><br>${lines.join('<br>')}`;
      },
    },
  };
}

function statusOption(byStatus, currency) {
  const c = palette();
  const rows = byStatus.filter((row) => row.bets > 0);
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: c.surface,
      borderColor: c.line,
      textStyle: { color: c.text, fontSize: 12 },
      formatter: (item) => `<b>${item.name}</b><br>${fmtNum(item.value)} ставок · ${fmtMoney(item.data.stake, currency)}`,
    },
    legend: { ...legendCommon(), bottom: 0, top: 'auto', orient: 'horizontal' },
    series: [
      {
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: c.surface, borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 15, fontWeight: 600, color: c.text, formatter: '{b}\n{c}' } },
        color: rows.map((row) => c[STATUS_COLORS[row.status] || 'neutral']),
        data: rows.map((row) => ({ name: row.name, value: row.bets, stake: row.stake })),
      },
    ],
  };
}

function amountsOption(amounts, currency) {
  const c = palette();
  const rows = [
    { name: 'Активные', value: amounts.active, color: c.accent },
    { name: 'Выигрышные', value: amounts.won_stake, color: c.win },
    { name: 'Проигрышные', value: amounts.lost_stake, color: c.loss },
    { name: 'Возврат', value: amounts.push_stake, color: c.push },
    { name: 'Отменённые', value: amounts.cancelled_stake, color: c.neutral },
  ];
  return {
    grid: { left: 8, right: 24, top: 12, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: c.surface,
      borderColor: c.line,
      textStyle: { color: c.text, fontSize: 12 },
      formatter: (params) => `<b>${params[0].name}</b><br>${fmtMoney(params[0].value, currency)}`,
    },
    xAxis: { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    yAxis: { type: 'category', data: rows.map((row) => row.name), ...axisCommon(), splitLine: { show: false } },
    series: [
      {
        type: 'bar',
        data: rows.map((row) => ({ value: row.value, itemStyle: { color: row.color, borderRadius: [0, 4, 4, 0] } })),
        barMaxWidth: 20,
        label: { show: true, position: 'right', color: c.dim, fontSize: 10.5, formatter: (item) => fmtNum(item.value) },
      },
    ],
  };
}

function winrateOption(metrics, currency) {
  const c = palette();
  return {
    graphic: [
      {
        type: 'text',
        left: 'center',
        bottom: 6,
        style: {
          text: `Средний кф ${fmtCoef(metrics.avg_coefficient)} · выигрышных ${fmtCoef(metrics.avg_coefficient_won)}`,
          fill: c.mute,
          fontSize: 11,
          fontFamily: 'Segoe UI, Inter, sans-serif',
        },
      },
      {
        type: 'text',
        left: 'center',
        bottom: 24,
        style: {
          text: `ROI ${fmtPct(metrics.roi_percent)} · результат ${fmtMoney(metrics.profit, currency, { sign: true })}`,
          fill: metrics.profit >= 0 ? c.win : c.loss,
          fontSize: 12.5,
          fontWeight: 600,
          fontFamily: 'Segoe UI, Inter, sans-serif',
        },
      },
    ],
    series: [
      {
        type: 'gauge',
        startAngle: 205,
        endAngle: -25,
        min: 0,
        max: 100,
        radius: '82%',
        center: ['50%', '52%'],
        progress: { show: true, width: 16, roundCap: true, itemStyle: { color: c.accent } },
        axisLine: { lineStyle: { width: 16, color: [[1, c.grid]] } },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, '-4%'],
          fontSize: 30,
          fontWeight: 650,
          color: c.text,
          formatter: (value) => `${value.toFixed(1)}%`,
        },
        title: { show: false },
        data: [{ value: Number(metrics.win_rate_percent || 0) }],
      },
    ],
  };
}

function sportsOption(rows, currency) {
  const c = palette();
  const data = rows.slice(0, 10).slice().reverse();
  return {
    grid: { left: 8, right: 30, top: 12, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: c.surface,
      borderColor: c.line,
      textStyle: { color: c.text, fontSize: 12 },
      formatter: (params) => {
        const row = data[params[0].dataIndex];
        return `<b>${row.name}</b><br>Результат: <b>${fmtMoney(row.profit, currency, { sign: true })}</b>`
          + `<br>Ставок: ${row.bets} · проходимость ${fmtPct(row.win_rate_percent)}`;
      },
    },
    xAxis: { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    yAxis: { type: 'category', data: data.map((row) => row.name), ...axisCommon(), splitLine: { show: false }, axisLabel: { color: c.dim, fontSize: 11 } },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        data: data.map((row) => ({
          value: row.profit,
          itemStyle: { color: row.profit >= 0 ? c.win : c.loss, borderRadius: row.profit >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] },
        })),
      },
    ],
  };
}

function sourcesOption(rows) {
  const c = palette();
  const data = rows.slice(0, 10).slice().reverse();
  const option = baseOption();
  return {
    ...option,
    legend: { ...legendCommon(), data: ['Результат', 'Проходимость'] },
    tooltip: {
      ...option.tooltip,
      formatter: (params) => {
        const row = data[params[0].dataIndex];
        return `<b>${row.name}</b><br>Результат: <b>${fmtNum(row.profit)}</b>`
          + `<br>Ставок: ${row.bets} · проходимость ${fmtPct(row.win_rate_percent)}`;
      },
    },
    xAxis: { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    yAxis: { type: 'category', data: data.map((row) => row.name), ...axisCommon(), splitLine: { show: false }, axisLabel: { color: c.dim, fontSize: 11 } },
    series: [
      {
        name: 'Результат',
        type: 'bar',
        barMaxWidth: 16,
        data: data.map((row) => ({
          value: row.profit,
          itemStyle: { color: row.profit >= 0 ? c.win : c.loss, borderRadius: 4 },
        })),
      },
      {
        name: 'Проходимость',
        type: 'line',
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2, color: c.accent },
        itemStyle: { color: c.accent },
        data: data.map((row) => row.win_rate_percent),
      },
    ],
  };
}

function coefficientsOption(rows) {
  const c = palette();
  const option = baseOption();
  return {
    ...option,
    legend: { ...legendCommon(), data: ['Количество ставок', 'Проходимость'] },
    xAxis: { type: 'category', data: rows.map((row) => row.name), ...axisCommon(), splitLine: { show: false } },
    yAxis: [
      { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
      { type: 'value', max: 100, ...axisCommon(), splitLine: { show: false }, axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => `${v}%` } },
    ],
    series: [
      { name: 'Количество ставок', type: 'bar', barMaxWidth: 34, itemStyle: { color: c.accent, borderRadius: [4, 4, 0, 0] }, data: rows.map((row) => row.bets) },
      {
        name: 'Проходимость',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbolSize: 7,
        lineStyle: { width: 2.2, color: c.warn },
        itemStyle: { color: c.warn },
        data: rows.map((row) => row.win_rate_percent),
      },
    ],
    tooltip: {
      ...option.tooltip,
      formatter: (params) => {
        const row = rows[params[0].dataIndex];
        return `<b>Коэффициент ${row.name}</b><br>Ставок: ${row.bets} (${row.won} / ${row.lost})`
          + `<br>Проходимость: <b>${fmtPct(row.win_rate_percent)}</b>`;
      },
    },
  };
}

function weekdaysOption(rows) {
  const c = palette();
  const option = baseOption();
  return {
    ...option,
    legend: { ...legendCommon(), data: ['Количество ставок', 'Результат'] },
    xAxis: { type: 'category', data: rows.map((row) => row.name), ...axisCommon(), splitLine: { show: false } },
    yAxis: [
      { type: 'value', ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
      { type: 'value', ...axisCommon(), splitLine: { show: false }, axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    ],
    series: [
      { name: 'Количество ставок', type: 'bar', barMaxWidth: 26, itemStyle: { color: c.accent, borderRadius: [4, 4, 0, 0] }, data: rows.map((row) => row.bets) },
      { name: 'Результат', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 6, lineStyle: { width: 2, color: c.win }, itemStyle: { color: c.win }, data: rows.map((row) => row.profit) },
    ],
  };
}

/** График кривой баланса счёта по дням (раздел «Баланс»). */
function balanceOption(points, currency) {
  const c = palette();
  return {
    ...baseOption(),
    grid: { left: 8, right: 14, top: 20, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((row) => row.date),
      boundaryGap: false,
      ...axisCommon(),
      splitLine: { show: false },
      axisLabel: { color: c.mute, fontSize: 10.5, formatter: (value) => value.slice(5), hideOverlap: true },
    },
    yAxis: { type: 'value', scale: true, ...axisCommon(), axisLabel: { color: c.mute, fontSize: 10.5, formatter: (v) => fmtNum(v) } },
    series: [
      {
        name: 'Баланс',
        type: 'line',
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.4, color: c.win },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(47,191,113,0.28)' },
              { offset: 1, color: 'rgba(47,191,113,0.02)' },
            ],
          },
        },
        data: points.map((row) => row.balance),
      },
    ],
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.surface,
      borderColor: c.line,
      textStyle: { color: c.text, fontSize: 12 },
      formatter: (params) => {
        const row = points[params[0].dataIndex] || {};
        return `<b>${params[0].axisValue}</b><br>Баланс: <b>${fmtMoney(row.balance, currency)}</b>`
          + `<br>Изменение за день: ${fmtMoney(row.delta, currency, { sign: true })}`;
      },
    },
  };
}

/** Отрисовать график кривой баланса. */
export function renderBalanceChart(points, currency = 'RUB') {
  if (!points || !points.length) {
    showEmpty('chart-balance', 'Операций и ставок пока нет');
    return;
  }
  setOption('chart-balance', balanceOption(points, currency));
}

/** Отрисовать все графики раздела статистики. */
export function renderStatsCharts(summary, currency = 'RUB') {
  if (!summary) return;
  const hasBets = summary.counts && summary.counts.total > 0;

  if (!hasBets) {
    ['chart-timeline', 'chart-status', 'chart-amounts', 'chart-winrate', 'chart-sports', 'chart-sources', 'chart-coefficients', 'chart-weekdays', 'chart-drawdown']
      .forEach((id) => showEmpty(id, 'Нет данных за выбранный период'));
    return;
  }

  if (summary.timeline && summary.timeline.length) setOption('chart-timeline', timelineOption(summary.timeline, currency));
  else showEmpty('chart-timeline', 'Нет данных');

  if (summary.timeline && summary.timeline.length) setOption('chart-drawdown', drawdownOption(summary.timeline, currency));
  else showEmpty('chart-drawdown', 'Нет данных');

  setOption('chart-status', statusOption(summary.by_status || [], currency));
  setOption('chart-amounts', amountsOption(summary.amounts, currency));
  setOption('chart-winrate', winrateOption(summary.metrics, currency));

  if ((summary.by_sport || []).length) setOption('chart-sports', sportsOption(summary.by_sport, currency));
  else showEmpty('chart-sports', 'Нет данных');

  if ((summary.by_source || []).length) setOption('chart-sources', sourcesOption(summary.by_source));
  else showEmpty('chart-sources', 'Нет данных');

  setOption('chart-coefficients', coefficientsOption(summary.coefficients || []));
  setOption('chart-weekdays', weekdaysOption(summary.weekdays || []));
}
