import { ApiError, request } from './api.js';
import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';
import { formatBytes, formatNumber, formatValue, renderLineChart } from './charts.js';

const LIVE_REFRESH_MS = 5_000;
const AZURE_REFRESH_MS = 60_000;

const errorNode = document.querySelector('[data-testid="monitoring-error"]');
const liveTiles = document.querySelector('#live-tiles');
const liveCharts = document.querySelector('#live-charts');
const liveRoutes = document.querySelector('#live-routes');
const liveUpdated = document.querySelector('#live-updated');
const liveAutoRefresh = document.querySelector('#live-auto-refresh');
const azureContent = document.querySelector('#azure-content');
const azureRange = document.querySelector('#azure-range');
const azureUpdated = document.querySelector('#azure-updated');
// The Azure Monitor section is optional: it only loads if its HTML is on the page.
const azureEnabled = Boolean(azureContent);

let liveTimer = null;
let azureTimer = null;
let lastLive = null;
let lastAzure = null;

function showError(message) {
  errorNode.hidden = !message;
  errorNode.textContent = message || '';
}

function chartSlot(parent, key) {
  let slot = parent.querySelector(`[data-chart="${key}"]`);
  if (!slot) {
    slot = document.createElement('div');
    slot.dataset.chart = key;
    parent.appendChild(slot);
  }
  return slot;
}

function statTile(label, value, detail) {
  const tile = document.createElement('div');
  tile.className = 'stat-tile';
  const name = document.createElement('div');
  name.className = 'stat-label';
  name.textContent = label;
  const figure = document.createElement('div');
  figure.className = 'stat-value';
  figure.textContent = value;
  tile.append(name, figure);
  if (detail) {
    const note = document.createElement('div');
    note.className = 'stat-detail';
    note.textContent = detail;
    tile.appendChild(note);
  }
  return tile;
}

function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

function seriesFrom(samples, key) {
  return samples.map((sample) => ({ t: sample.t, v: sample[key] ?? null }));
}

function buildTable(columns, rows) {
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const column of columns) {
    const cell = document.createElement('th');
    cell.textContent = column.label;
    headRow.appendChild(cell);
  }
  head.appendChild(headRow);
  const body = document.createElement('tbody');
  for (const row of rows) {
    const tableRow = document.createElement('tr');
    for (const column of columns) {
      const cell = document.createElement('td');
      cell.textContent = column.format ? column.format(row[column.key]) : String(row[column.key] ?? '–');
      tableRow.appendChild(cell);
    }
    body.appendChild(tableRow);
  }
  table.append(head, body);
  return table;
}

function renderLive(data) {
  lastLive = data;
  const { system, requests } = data;
  const latest = system.latest || {};
  const overall = requests.overall;

  const diskTotal = (latest.diskReadBytesPerSec ?? 0) + (latest.diskWriteBytesPerSec ?? 0);
  liveTiles.replaceChildren(
    statTile('CPU', `${formatNumber(latest.cpuPercent)}%`, `of ${system.cpuLimitCores} cores`),
    statTile('Memory', formatBytes(latest.memoryBytes), `${formatNumber(latest.memoryPercent)}% of ${formatBytes(system.memoryLimitBytes)}`),
    statTile('Disk I/O', `${formatBytes(diskTotal)}/s`, 'read + write'),
    statTile(
      'Network',
      `${formatBytes(latest.networkInBytesPerSec)}/s in`,
      `${formatBytes(latest.networkOutBytesPerSec)}/s out`,
    ),
    statTile('Request latency p95', overall.p95Ms === null ? '–' : `${formatNumber(overall.p95Ms)} ms`, `avg ${formatValue(overall.avgMs, 'ms')}, last 15 min`),
    statTile('Requests', formatNumber(overall.count), `${formatNumber(overall.perMinute)}/min, ${overall.serverErrors} server errors`),
  );

  // Lay out every slot before drawing, so each chart measures its final width.
  ['cpu', 'memory', 'disk', 'network', 'latency', 'requests'].forEach((key) => chartSlot(liveCharts, key));
  const samples = system.series || [];
  const waiting = 'Collecting samples. The first points appear within a few seconds.';
  renderLineChart(chartSlot(liveCharts, 'cpu'), {
    title: 'CPU usage', unit: 'percent', emptyText: waiting,
    series: [{ label: 'CPU', points: seriesFrom(samples, 'cpuPercent') }],
  });
  renderLineChart(chartSlot(liveCharts, 'memory'), {
    title: 'Memory used', unit: 'bytes', emptyText: waiting,
    series: [{ label: 'Memory', points: seriesFrom(samples, 'memoryBytes') }],
  });
  renderLineChart(chartSlot(liveCharts, 'disk'), {
    title: 'Disk I/O', unit: 'bytesPerSecond', emptyText: waiting,
    series: [
      { label: 'Read', points: seriesFrom(samples, 'diskReadBytesPerSec') },
      { label: 'Write', points: seriesFrom(samples, 'diskWriteBytesPerSec') },
    ],
  });
  renderLineChart(chartSlot(liveCharts, 'network'), {
    title: 'Network traffic', unit: 'bytesPerSecond', emptyText: waiting,
    series: [
      { label: 'In', points: seriesFrom(samples, 'networkInBytesPerSec') },
      { label: 'Out', points: seriesFrom(samples, 'networkOutBytesPerSec') },
    ],
  });
  const minutes = requests.series.filter((bucket) => bucket.count > 0);
  renderLineChart(chartSlot(liveCharts, 'latency'), {
    title: 'Request latency per minute', unit: 'ms', emptyText: 'No requests in the last hour.',
    series: [
      { label: 'Average', points: minutes.map((bucket) => ({ t: bucket.t, v: bucket.avgMs })) },
      { label: 'p95', points: minutes.map((bucket) => ({ t: bucket.t, v: bucket.p95Ms })) },
    ],
  });
  renderLineChart(chartSlot(liveCharts, 'requests'), {
    title: 'Requests per minute', unit: 'count', emptyText: 'No requests in the last hour.',
    series: [{ label: 'Requests', points: requests.series.map((bucket) => ({ t: bucket.t, v: bucket.count })) }],
  });

  if (requests.routes.length === 0) {
    const empty = document.createElement('p');
    empty.textContent = 'No requests in the last 15 minutes.';
    liveRoutes.replaceChildren(empty);
  } else {
    liveRoutes.replaceChildren(buildTable(
      [
        { key: 'method', label: 'Method' },
        { key: 'route', label: 'Route' },
        { key: 'count', label: 'Requests', format: formatNumber },
        { key: 'avgMs', label: 'Avg', format: (value) => formatValue(value, 'ms') },
        { key: 'p95Ms', label: 'p95', format: (value) => formatValue(value, 'ms') },
        { key: 'maxMs', label: 'Max', format: (value) => formatValue(value, 'ms') },
        { key: 'serverErrors', label: 'Server errors', format: formatNumber },
      ],
      requests.routes,
    ));
  }

  liveUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}, server up ${formatDuration(system.uptimeSeconds)}`;
}

function sectionErrors(errors) {
  const entries = Object.entries(errors || {});
  if (entries.length === 0) {
    return null;
  }
  const details = document.createElement('details');
  details.className = 'monitoring-errors';
  const summary = document.createElement('summary');
  summary.textContent = `${entries.length} item${entries.length === 1 ? '' : 's'} could not be loaded`;
  const list = document.createElement('ul');
  for (const [key, message] of entries) {
    const item = document.createElement('li');
    item.textContent = `${key}: ${message}`;
    list.appendChild(item);
  }
  details.append(summary, list);
  return details;
}

function metricSeries(section, keys) {
  return keys.map((key) => {
    const metric = section.metrics[key];
    return { label: metric.label, unit: metric.unit, points: metric.points };
  });
}

function renderAzureGroup(heading, section, charts) {
  const group = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = heading;
  group.appendChild(title);
  const errors = sectionErrors(section.errors);
  if (errors) {
    group.appendChild(errors);
  }
  const grid = document.createElement('div');
  grid.className = 'chart-grid';
  group.appendChild(grid);
  azureContent.appendChild(group);
  const slots = charts.map((chart) => chartSlot(grid, chart.key));
  charts.forEach((chart, index) => {
    renderLineChart(slots[index], { ...chart, emptyText: 'No data for this range.' });
  });
}

function renderAzureNotConfigured(missing) {
  const note = document.createElement('div');
  note.className = 'monitoring-note';
  const text = document.createElement('p');
  text.textContent = 'Azure Monitor is not connected to this app yet, so only the live figures above are shown. '
    + 'Set these environment variables on the Container App to show history for all replicas:';
  const list = document.createElement('ul');
  for (const name of missing) {
    const item = document.createElement('li');
    const code = document.createElement('code');
    code.textContent = name;
    item.appendChild(code);
    list.appendChild(item);
  }
  const more = document.createElement('p');
  more.textContent = 'Setup steps are in docs/monitoring.md, under "Monitoring page".';
  note.append(text, list, more);
  azureContent.replaceChildren(note);
}

function renderAzure(data) {
  lastAzure = data;
  azureContent.replaceChildren();
  if (!data.configured) {
    renderAzureNotConfigured(data.missing || []);
    azureUpdated.textContent = '';
    return;
  }
  if (data.error) {
    const message = document.createElement('p');
    message.setAttribute('role', 'alert');
    message.textContent = `Could not reach Azure Monitor: ${data.error}`;
    azureContent.appendChild(message);
  }

  if (data.containerApp) {
    const metrics = (keys) => metricSeries(data.containerApp, keys);
    renderAzureGroup('Container App', data.containerApp, [
      { key: 'az-cpu', title: 'CPU usage (max)', unit: 'percent', series: metrics(['cpuPercent']) },
      { key: 'az-memory', title: 'Memory usage (max)', unit: 'percent', series: metrics(['memoryPercent']) },
      { key: 'az-network', title: 'Network traffic per interval', unit: 'bytes', series: metrics(['networkIn', 'networkOut']) },
      { key: 'az-requests', title: 'Requests per interval', unit: 'count', series: metrics(['requests']) },
      { key: 'az-response', title: 'Average response time', unit: 'ms', series: metrics(['responseTime']) },
    ]);
  }

  if (data.appInsights) {
    const section = data.appInsights;
    const metrics = (keys) => metricSeries(section, keys);
    const latency = section.latency || [];
    renderAzureGroup('Application Insights', section, [
      {
        key: 'ai-latency', title: 'Request latency percentiles', unit: 'ms',
        series: ['p50', 'p95', 'p99'].map((key) => ({ label: key, points: latency.map((row) => ({ t: row.t, v: row[key] ?? null })) })),
      },
      { key: 'ai-response', title: 'Server response time (avg)', unit: 'ms', series: metrics(['serverResponseTime']) },
      { key: 'ai-io', title: 'Process IO rate (disk I/O)', unit: 'bytesPerSecond', series: metrics(['processIo']) },
      { key: 'ai-cpu', title: 'Process CPU', unit: 'percent', series: metrics(['processCpu']) },
      { key: 'ai-memory', title: 'Process private bytes', unit: 'bytes', series: metrics(['processMemory']) },
      { key: 'ai-dependency', title: 'Cosmos DB call time (avg)', unit: 'ms', series: metrics(['dependencyDuration']) },
    ]);

    const slowest = section.slowestRoutes || [];
    if (slowest.length) {
      const heading = document.createElement('h3');
      heading.textContent = 'Slowest routes';
      const wrapper = document.createElement('div');
      wrapper.className = 'monitoring-table';
      wrapper.appendChild(buildTable(
        [
          { key: 'Name', label: 'Route' },
          { key: 'requests', label: 'Requests', format: formatNumber },
          { key: 'avgMs', label: 'Avg', format: (value) => formatValue(value, 'ms') },
          { key: 'p95Ms', label: 'p95', format: (value) => formatValue(value, 'ms') },
        ],
        slowest,
      ));
      azureContent.append(heading, wrapper);
    }
  }

  azureUpdated.textContent = `Updated ${new Date(data.generatedAt).toLocaleTimeString()}`;
}

function handleRequestError(error, section) {
  if (error instanceof ApiError && error.status === 401) {
    window.location.assign('login.html');
    return;
  }
  if (error instanceof ApiError && error.status === 403) {
    stopTimers();
    showError(error.message || 'Only Admin users can view monitoring.');
    return;
  }
  showError(`${section} figures could not be loaded: ${error.message || 'request failed'}`);
}

async function loadLive() {
  liveCharts.classList.add('is-loading');
  try {
    renderLive(await request('GET', '/api/monitoring/live'));
    showError('');
  } catch (error) {
    handleRequestError(error, 'Live');
  } finally {
    liveCharts.classList.remove('is-loading');
  }
}

async function loadAzure() {
  azureContent.classList.add('is-loading');
  try {
    renderAzure(await request('GET', `/api/monitoring/azure?range=${encodeURIComponent(azureRange.value)}`));
  } catch (error) {
    handleRequestError(error, 'Azure Monitor');
  } finally {
    azureContent.classList.remove('is-loading');
  }
}

function stopTimers() {
  clearInterval(liveTimer);
  clearInterval(azureTimer);
  liveTimer = null;
  azureTimer = null;
}

function startLiveTimer() {
  clearInterval(liveTimer);
  liveTimer = liveAutoRefresh.checked ? setInterval(loadLive, LIVE_REFRESH_MS) : null;
}

function startAzureTimer() {
  clearInterval(azureTimer);
  azureTimer = azureEnabled ? setInterval(loadAzure, AZURE_REFRESH_MS) : null;
}

let resizeFrame = null;
window.addEventListener('resize', () => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    if (lastLive) {
      renderLive(lastLive);
    }
    if (lastAzure) {
      renderAzure(lastAzure);
    }
  });
});

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();
  let user;
  try {
    user = await guardAuthenticatedPage();
  } catch {
    return;
  }
  if (user.role !== 'Admin') {
    showError('Only Admin users can view monitoring.');
    return;
  }

  liveAutoRefresh.addEventListener('change', startLiveTimer);
  if (azureEnabled) {
    azureRange.addEventListener('change', loadAzure);
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopTimers();
    } else {
      loadLive();
      startLiveTimer();
      startAzureTimer();
    }
  });

  await Promise.all([loadLive(), azureEnabled ? loadAzure() : null]);
  startLiveTimer();
  startAzureTimer();
}

init();
