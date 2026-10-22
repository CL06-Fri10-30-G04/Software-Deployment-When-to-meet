// Small dependency-free line charts for the monitoring page.
// Each chart: hairline grid, 2px lines, crosshair tooltip listing every series,
// a legend for two or more series, and a table view so no value is hover-only.

const SVG_NS = 'http://www.w3.org/2000/svg';
const HEIGHT = 180;
const MARGIN = { top: 12, right: 16, bottom: 26, left: 56 };

// Categorical slots in fixed order; a series keeps its slot across refreshes.
export const SERIES_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];

const units = {
  percent: (value) => `${formatNumber(value)}%`,
  ms: (value) => `${formatNumber(value)} ms`,
  bytes: (value) => formatBytes(value),
  bytesPerSecond: (value) => `${formatBytes(value)}/s`,
  count: (value) => formatNumber(value),
};

export function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '–';
  }
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (absolute >= 10_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  if (absolute >= 100 || Number.isInteger(value)) {
    return Math.round(value).toLocaleString();
  }
  return value.toFixed(absolute >= 10 ? 1 : 2);
}

export function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '–';
  }
  const steps = ['B', 'KB', 'MB', 'GB', 'TB'];
  let scaled = value;
  let index = 0;
  while (Math.abs(scaled) >= 1024 && index < steps.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  const digits = index === 0 || scaled >= 100 ? 0 : 1;
  return `${scaled.toFixed(digits)} ${steps[index]}`;
}

export function formatValue(value, unit) {
  return (units[unit] || units.count)(value);
}

// Byte axes round in binary units so ticks read 256 KB, not 262.1 KB.
function niceAxisMax(value, unit) {
  if (unit !== 'bytes' && unit !== 'bytesPerSecond') {
    return niceMax(value);
  }
  let scale = 1;
  while (value / scale >= 1024) {
    scale *= 1024;
  }
  return niceMax(value / scale) * scale;
}

function niceMax(value) {
  if (!(value > 0)) {
    return 1;
  }
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (value <= step * magnitude) {
      return step * magnitude;
    }
  }
  return 10 * magnitude;
}

function timeLabel(timestamp, spanMs) {
  const date = new Date(timestamp);
  let options = { hour: '2-digit', minute: '2-digit' };
  if (spanMs > 36 * 3600 * 1000) {
    options = { month: 'short', day: 'numeric', hour: '2-digit' };
  } else if (spanMs < 10 * 60 * 1000) {
    options = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
  }
  return date.toLocaleString(undefined, options);
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function buildTable(series, unit) {
  const times = [...new Set(series.flatMap((item) => item.points.map((point) => point.t)))].sort((a, b) => a - b);
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const label of ['Time', ...series.map((item) => item.label)]) {
    const cell = document.createElement('th');
    cell.textContent = label;
    headRow.appendChild(cell);
  }
  head.appendChild(headRow);
  table.appendChild(head);

  const body = document.createElement('tbody');
  const lookups = series.map((item) => new Map(item.points.map((point) => [point.t, point.v])));
  for (const time of times.slice().reverse()) {
    const row = document.createElement('tr');
    const timeCell = document.createElement('td');
    timeCell.textContent = new Date(time).toLocaleString();
    row.appendChild(timeCell);
    for (const lookup of lookups) {
      const cell = document.createElement('td');
      cell.textContent = formatValue(lookup.get(time), unit);
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
  table.appendChild(body);
  return table;
}

/**
 * Render (or re-render) a line chart into `container`.
 * series: [{ label, points: [{ t: epochMs, v: number|null }] }]
 */
export function renderLineChart(container, { title, unit = 'count', series, emptyText = 'No data yet.' }) {
  container.replaceChildren();
  container.classList.add('chart');

  const heading = document.createElement('h3');
  heading.textContent = title;
  container.appendChild(heading);

  const allPoints = series.flatMap((item) => item.points.filter((point) => point.v !== null && point.v !== undefined));
  if (allPoints.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'chart-empty';
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }

  if (series.length > 1) {
    const legend = document.createElement('ul');
    legend.className = 'chart-legend';
    series.forEach((item, index) => {
      const entry = document.createElement('li');
      const key = document.createElement('span');
      key.className = 'chart-key';
      key.style.background = SERIES_COLORS[index];
      entry.append(key, document.createTextNode(item.label));
      legend.appendChild(entry);
    });
    container.appendChild(legend);
  }

  const plot = document.createElement('div');
  plot.className = 'chart-plot';
  container.appendChild(plot);

  const width = Math.max(plot.clientWidth || container.clientWidth || 480, 260);
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const times = allPoints.map((point) => point.t);
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const spanT = Math.max(maxT - minT, 1);
  const maxV = niceAxisMax(Math.max(...allPoints.map((point) => point.v)), unit);

  const x = (t) => MARGIN.left + ((t - minT) / spanT) * innerWidth;
  const y = (v) => MARGIN.top + innerHeight - (v / maxV) * innerHeight;

  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${HEIGHT}`, width, height: HEIGHT, role: 'img' });
  svg.setAttribute('aria-label', `${title} chart`);

  for (let index = 0; index <= 4; index += 1) {
    const value = (maxV / 4) * index;
    const lineY = y(value);
    svg.appendChild(svgElement('line', {
      x1: MARGIN.left, x2: width - MARGIN.right, y1: lineY, y2: lineY,
      class: index === 0 ? 'chart-baseline' : 'chart-gridline',
    }));
    const tick = svgElement('text', { x: MARGIN.left - 8, y: lineY + 4, class: 'chart-tick', 'text-anchor': 'end' });
    tick.textContent = formatValue(value, unit);
    svg.appendChild(tick);
  }

  const tickCount = Math.min(5, Math.max(2, Math.floor(innerWidth / 110)));
  for (let index = 0; index < tickCount; index += 1) {
    const t = minT + (spanT / (tickCount - 1)) * index;
    const anchor = index === 0 ? 'start' : index === tickCount - 1 ? 'end' : 'middle';
    const tick = svgElement('text', { x: x(t), y: HEIGHT - 6, class: 'chart-tick', 'text-anchor': anchor });
    tick.textContent = timeLabel(t, spanT);
    svg.appendChild(tick);
  }

  series.forEach((item, index) => {
    const color = SERIES_COLORS[index];
    // Break the line at missing values instead of drawing through them.
    let path = '';
    let drawing = false;
    const valid = [];
    for (const point of item.points) {
      if (point.v === null || point.v === undefined) {
        drawing = false;
        continue;
      }
      path += `${drawing ? 'L' : 'M'}${x(point.t).toFixed(1)},${y(point.v).toFixed(1)}`;
      drawing = true;
      valid.push(point);
    }
    if (series.length === 1 && valid.length > 1) {
      const area = `${path}L${x(valid[valid.length - 1].t).toFixed(1)},${y(0)}L${x(valid[0].t).toFixed(1)},${y(0)}Z`;
      svg.appendChild(svgElement('path', { d: area, class: 'chart-area', style: `fill: ${color}` }));
    }
    svg.appendChild(svgElement('path', { d: path, class: 'chart-line', style: `stroke: ${color}` }));
    if (valid.length === 1) {
      svg.appendChild(svgElement('circle', {
        cx: x(valid[0].t), cy: y(valid[0].v), r: 4, class: 'chart-dot', style: `fill: ${color}`,
      }));
    }
  });

  const crosshair = svgElement('line', { y1: MARGIN.top, y2: MARGIN.top + innerHeight, class: 'chart-crosshair', visibility: 'hidden' });
  svg.appendChild(crosshair);
  const markers = series.map((_, index) => {
    const marker = svgElement('circle', { r: 4, class: 'chart-dot', style: `fill: ${SERIES_COLORS[index]}`, visibility: 'hidden' });
    svg.appendChild(marker);
    return marker;
  });
  const hitArea = svgElement('rect', {
    x: MARGIN.left, y: MARGIN.top, width: innerWidth, height: innerHeight, class: 'chart-hit', tabindex: 0,
  });
  svg.appendChild(hitArea);
  plot.appendChild(svg);

  const tooltip = document.createElement('div');
  tooltip.className = 'chart-tooltip';
  tooltip.hidden = true;
  plot.appendChild(tooltip);

  const allTimes = [...new Set(allPoints.map((point) => point.t))].sort((a, b) => a - b);
  const lookups = series.map((item) => new Map(item.points.map((point) => [point.t, point.v])));

  function showAt(time) {
    const px = x(time);
    crosshair.setAttribute('x1', px);
    crosshair.setAttribute('x2', px);
    crosshair.setAttribute('visibility', 'visible');
    tooltip.replaceChildren();
    const when = document.createElement('div');
    when.className = 'chart-tooltip-time';
    when.textContent = new Date(time).toLocaleString();
    tooltip.appendChild(when);
    series.forEach((item, index) => {
      const value = lookups[index].get(time);
      const marker = markers[index];
      if (value === null || value === undefined) {
        marker.setAttribute('visibility', 'hidden');
      } else {
        marker.setAttribute('cx', px);
        marker.setAttribute('cy', y(value));
        marker.setAttribute('visibility', 'visible');
      }
      const row = document.createElement('div');
      row.className = 'chart-tooltip-row';
      const key = document.createElement('span');
      key.className = 'chart-tooltip-key';
      key.style.background = SERIES_COLORS[index];
      const strong = document.createElement('strong');
      strong.textContent = formatValue(value, unit);
      const label = document.createElement('span');
      label.textContent = item.label;
      row.append(key, strong, label);
      tooltip.appendChild(row);
    });
    tooltip.hidden = false;
    // Position in rendered pixels; flip to the left of the crosshair near the edge.
    const scale = svg.getBoundingClientRect().width / width || 1;
    const anchor = px * scale;
    const flipped = anchor + 12 + tooltip.offsetWidth > plot.clientWidth;
    tooltip.style.left = `${Math.max(0, flipped ? anchor - tooltip.offsetWidth - 12 : anchor + 12)}px`;
  }

  function hide() {
    crosshair.setAttribute('visibility', 'hidden');
    markers.forEach((marker) => marker.setAttribute('visibility', 'hidden'));
    tooltip.hidden = true;
  }

  function nearestTime(clientX) {
    const box = svg.getBoundingClientRect();
    const scale = width / box.width;
    const target = minT + (((clientX - box.left) * scale - MARGIN.left) / innerWidth) * spanT;
    let best = allTimes[0];
    for (const time of allTimes) {
      if (Math.abs(time - target) < Math.abs(best - target)) {
        best = time;
      }
    }
    return best;
  }

  let focusIndex = allTimes.length - 1;
  hitArea.addEventListener('pointermove', (event) => showAt(nearestTime(event.clientX)));
  hitArea.addEventListener('pointerleave', hide);
  hitArea.addEventListener('focus', () => showAt(allTimes[focusIndex]));
  hitArea.addEventListener('blur', hide);
  hitArea.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      focusIndex = Math.min(allTimes.length - 1, Math.max(0, focusIndex + (event.key === 'ArrowRight' ? 1 : -1)));
      showAt(allTimes[focusIndex]);
    }
  });

  const details = document.createElement('details');
  details.className = 'chart-table';
  const summary = document.createElement('summary');
  summary.textContent = 'Show as table';
  details.append(summary, buildTable(series, unit));
  container.appendChild(details);
}
