import { ApiError, request } from './api.js';
import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';

// All dates here are in the browser's time zone, like the rest of the app.
const DAY_MS = 24 * 60 * 60 * 1000;
const HOUR_PX = 44;
const MONTH_LANES = 3;
const VIEW_ROLES = new Set(['Admin', 'Manager']);
const RESPONSE_LABELS = { pending: 'Invited', declined: 'Declined' };

const body = document.querySelector('[data-testid="calendar-body"]');
const title = document.querySelector('[data-testid="calendar-title"]');
const summary = document.querySelector('[data-testid="calendar-summary"]');
const errorNode = document.querySelector('[data-testid="calendar-error"]');
const viewButtons = [...document.querySelectorAll('[data-view]')];
const filtersForm = document.querySelector('[data-testid="calendar-filters"]');
const scopeField = document.querySelector('[data-testid="filter-scope-field"]');
const filters = {
  show: document.querySelector('#filter-show'),
  role: document.querySelector('#filter-role'),
  scope: document.querySelector('#filter-scope'),
  cancelled: document.querySelector('#filter-cancelled'),
};

const state = { view: 'month', cursor: startOfDay(new Date()), items: [] };
let loadToken = 0;

// ---------- dates ----------

function pad(value) {
  return String(value).padStart(2, '0');
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

// Calendar arithmetic, safe across daylight-saving changes.
function addDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

function startOfWeek(date) {
  return addDays(startOfDay(date), -((date.getDay() + 6) % 7)); // weeks start on Monday
}

function dateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function parseDateKey(key) {
  const [year, month, day] = key.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function dayIndex(from, date) {
  return Math.round((startOfDay(date) - from) / DAY_MS);
}

function visibleRange() {
  if (state.view === 'week') {
    const from = startOfWeek(state.cursor);
    return { from, days: 7 };
  }
  const first = new Date(state.cursor.getFullYear(), state.cursor.getMonth(), 1);
  const last = new Date(state.cursor.getFullYear(), state.cursor.getMonth() + 1, 0);
  const from = startOfWeek(first);
  const to = addDays(startOfWeek(last), 7);
  return { from, days: dayIndex(from, to) };
}

const formatters = {
  time: new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }),
  monthTitle: new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }),
  dayShort: new Intl.DateTimeFormat(undefined, { weekday: 'short' }),
  dayMonth: new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }),
  full: new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' }),
  dateLong: new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }),
};

function periodTitle(from, days) {
  if (state.view === 'month') {
    return formatters.monthTitle.format(state.cursor);
  }
  const last = addDays(from, days - 1);
  return `${formatters.dayMonth.format(from)} – ${formatters.dateLong.format(last)}`;
}

// ---------- meeting items ----------

function isScheduled(item) {
  return Boolean(item.start && item.end);
}

// First and last visible day an item covers, as Date objects at local midnight.
function itemDays(item) {
  if (isScheduled(item)) {
    const start = new Date(item.start);
    const lastMoment = new Date(new Date(item.end).getTime() - 1);
    return { first: startOfDay(start), last: startOfDay(lastMoment) };
  }
  return { first: parseDateKey(item.earliestDate), last: parseDateKey(item.latestDate) };
}

function describe(item) {
  const parts = [item.name];
  if (item.status === 'cancelled') {
    parts.push('cancelled');
  }
  if (isScheduled(item)) {
    const start = new Date(item.start);
    parts.push(`${formatters.full.format(start)}, ${formatters.time.format(start)} – ${formatters.time.format(new Date(item.end))}`);
    if (item.forced) {
      parts.push('scheduled even though some participants are unavailable');
    }
  } else {
    parts.push(`being planned, ${item.durationMinutes} minutes, between ${formatters.dateLong.format(parseDateKey(item.earliestDate))} and ${formatters.dateLong.format(parseDateKey(item.latestDate))}`);
  }
  parts.push(`${item.acceptedCount} of ${item.participantCount} accepted`);
  if (item.creatorName) {
    parts.push(`created by ${item.creatorName}`);
  }
  if (item.myResponse) {
    parts.push(`your reply: ${item.myResponse === 'pending' ? 'not replied' : item.myResponse}`);
  } else {
    parts.push('you are not a participant');
  }
  return parts.join('. ');
}

function itemClasses(item) {
  const classes = ['calendar-item', isScheduled(item) ? 'is-scheduled' : 'is-planning'];
  if (item.status === 'cancelled') {
    classes.push('is-cancelled');
  }
  if (item.myResponse === 'declined') {
    classes.push('is-declined');
  }
  if (item.myResponse === 'pending') {
    classes.push('is-pending');
  }
  return classes;
}

// compact: a one-day chip in month view, too narrow for the reply tag; the
// outlined style and the label still say it.
function itemLink(item, { showTime, compact = false }) {
  const link = document.createElement('a');
  link.href = `meeting.html?id=${encodeURIComponent(item.id)}`;
  link.className = itemClasses(item).join(' ');
  link.dataset.testid = 'calendar-item';
  link.title = describe(item);
  link.setAttribute('aria-label', describe(item));

  if (showTime && isScheduled(item)) {
    const time = document.createElement('span');
    time.className = 'calendar-item-time';
    time.textContent = formatters.time.format(new Date(item.start));
    link.appendChild(time);
  }
  const name = document.createElement('span');
  name.className = 'calendar-item-name';
  const prefix = item.status === 'cancelled' ? 'Cancelled: ' : isScheduled(item) ? '' : 'Planning: ';
  name.textContent = `${prefix}${item.name}`;
  link.appendChild(name);

  const badge = RESPONSE_LABELS[item.myResponse];
  if (badge && !compact) {
    const tag = document.createElement('span');
    tag.className = 'calendar-item-badge';
    tag.textContent = badge;
    link.appendChild(tag);
  }
  return link;
}

// Assign each segment to the first lane where it doesn't overlap another.
function packLanes(segments) {
  const lanes = [];
  const ordered = [...segments].sort((a, b) => a.startCol - b.startCol
    || (b.endCol - b.startCol) - (a.endCol - a.startCol)
    || (a.item.start || '').localeCompare(b.item.start || ''));
  for (const segment of ordered) {
    let lane = lanes.findIndex((laneEnd) => laneEnd < segment.startCol);
    if (lane === -1) {
      lane = lanes.length;
      lanes.push(segment.endCol);
    } else {
      lanes[lane] = segment.endCol;
    }
    segment.lane = lane;
  }
  return lanes.length;
}

// Segments of items that fall in the 7 columns starting at `rowStart`.
function rowSegments(items, from, rowStart, { allDayOnly = false } = {}) {
  const segments = [];
  for (const item of items) {
    if (allDayOnly && isScheduled(item)) {
      continue;
    }
    const { first, last } = itemDays(item);
    const startCol = Math.max(dayIndex(from, first) - rowStart, 0);
    const endCol = Math.min(dayIndex(from, last) - rowStart, 6);
    if (endCol < 0 || startCol > 6 || startCol > endCol) {
      continue;
    }
    segments.push({
      item,
      startCol,
      endCol,
      continuesBefore: dayIndex(from, first) - rowStart < 0,
      continuesAfter: dayIndex(from, last) - rowStart > 6,
    });
  }
  return segments;
}

function placeSegment(segment, row, { compact = false } = {}) {
  const singleDay = segment.startCol === segment.endCol;
  const link = itemLink(segment.item, { showTime: singleDay, compact: compact && singleDay });
  link.style.gridColumn = `${segment.startCol + 1} / ${segment.endCol + 2}`;
  link.style.gridRow = String(row);
  link.classList.toggle('continues-before', segment.continuesBefore);
  link.classList.toggle('continues-after', segment.continuesAfter);
  return link;
}

// ---------- month view ----------

function dayButton(date, monthIndex) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'calendar-day-number';
  if (date.getMonth() !== monthIndex) {
    button.classList.add('is-outside');
  }
  if (dateKey(date) === dateKey(new Date())) {
    button.classList.add('is-today');
    button.setAttribute('aria-current', 'date');
  }
  button.textContent = String(date.getDate());
  button.setAttribute('aria-label', `${formatters.full.format(date)}, show week`);
  button.addEventListener('click', () => {
    state.view = 'week';
    state.cursor = date;
    refresh();
  });
  return button;
}

function renderMonth(from, days) {
  const grid = document.createElement('div');
  grid.className = 'calendar-month';

  const head = document.createElement('div');
  head.className = 'calendar-weekdays';
  for (let col = 0; col < 7; col += 1) {
    const name = document.createElement('div');
    name.textContent = formatters.dayShort.format(addDays(from, col));
    head.appendChild(name);
  }
  grid.appendChild(head);

  for (let rowStart = 0; rowStart < days; rowStart += 7) {
    const week = document.createElement('div');
    week.className = 'calendar-week';
    const segments = rowSegments(state.items, from, rowStart);
    packLanes(segments);

    const hiddenPerDay = new Array(7).fill(0);
    for (const segment of segments) {
      if (segment.lane >= MONTH_LANES) {
        for (let col = segment.startCol; col <= segment.endCol; col += 1) {
          hiddenPerDay[col] += 1;
        }
      }
    }

    for (let col = 0; col < 7; col += 1) {
      const date = addDays(from, rowStart + col);
      const cell = document.createElement('div');
      cell.className = col === 0 ? 'calendar-day is-first' : 'calendar-day';
      if (date.getMonth() !== state.cursor.getMonth()) {
        cell.classList.add('is-outside');
      }
      cell.style.gridColumn = String(col + 1);
      week.appendChild(cell);

      const number = dayButton(date, state.cursor.getMonth());
      number.style.gridColumn = String(col + 1);
      week.appendChild(number);

      if (hiddenPerDay[col] > 0) {
        const more = document.createElement('button');
        more.type = 'button';
        more.className = 'calendar-more';
        more.textContent = `+${hiddenPerDay[col]} more`;
        more.style.gridColumn = String(col + 1);
        more.style.gridRow = String(MONTH_LANES + 2);
        more.setAttribute('aria-label', `${hiddenPerDay[col]} more on ${formatters.full.format(date)}, show week`);
        more.addEventListener('click', () => {
          state.view = 'week';
          state.cursor = date;
          refresh();
        });
        week.appendChild(more);
      }
    }

    for (const segment of segments) {
      if (segment.lane < MONTH_LANES) {
        week.appendChild(placeSegment(segment, segment.lane + 2, { compact: true }));
      }
    }
    grid.appendChild(week);
  }
  return grid;
}

// ---------- week view ----------

// Split each scheduled meeting into per-day pieces, then lay out overlapping
// pieces side by side.
function dayPieces(items, from) {
  const perDay = Array.from({ length: 7 }, () => []);
  for (const item of items) {
    if (!isScheduled(item)) {
      continue;
    }
    const start = new Date(item.start);
    const end = new Date(item.end);
    for (let col = 0; col < 7; col += 1) {
      const dayStart = addDays(from, col);
      const dayEnd = addDays(from, col + 1);
      if (start < dayEnd && end > dayStart) {
        const pieceStart = start > dayStart ? start : dayStart;
        const pieceEnd = end < dayEnd ? end : dayEnd;
        perDay[col].push({
          item,
          top: (pieceStart - dayStart) / 3_600_000,
          bottom: (pieceEnd - dayStart) / 3_600_000,
        });
      }
    }
  }
  for (const pieces of perDay) {
    pieces.sort((a, b) => a.top - b.top || b.bottom - a.bottom);
    let cluster = [];
    let clusterEnd = -1;
    const finishCluster = () => {
      const columns = [];
      for (const piece of cluster) {
        let column = columns.findIndex((columnEnd) => columnEnd <= piece.top);
        if (column === -1) {
          column = columns.length;
          columns.push(piece.bottom);
        } else {
          columns[column] = piece.bottom;
        }
        piece.column = column;
      }
      for (const piece of cluster) {
        piece.columns = columns.length;
      }
    };
    for (const piece of pieces) {
      if (piece.top >= clusterEnd && cluster.length) {
        finishCluster();
        cluster = [];
      }
      cluster.push(piece);
      clusterEnd = Math.max(clusterEnd, piece.bottom);
    }
    if (cluster.length) {
      finishCluster();
    }
  }
  return perDay;
}

function renderWeek(from) {
  const wrapper = document.createElement('div');
  wrapper.className = 'calendar-weekview';

  const head = document.createElement('div');
  head.className = 'calendar-weekview-head';
  head.appendChild(document.createElement('div'));
  for (let col = 0; col < 7; col += 1) {
    const date = addDays(from, col);
    const label = document.createElement('div');
    label.className = 'calendar-weekview-day';
    if (dateKey(date) === dateKey(new Date())) {
      label.classList.add('is-today');
      label.setAttribute('aria-current', 'date');
    }
    const weekday = document.createElement('span');
    weekday.textContent = formatters.dayShort.format(date);
    const number = document.createElement('strong');
    number.textContent = String(date.getDate());
    label.append(weekday, number);
    head.appendChild(label);
  }
  wrapper.appendChild(head);

  const allDay = document.createElement('div');
  allDay.className = 'calendar-allday';
  const allDayLabel = document.createElement('div');
  allDayLabel.className = 'calendar-gutter-label';
  allDayLabel.textContent = 'Planning';
  allDay.appendChild(allDayLabel);
  const allDayGrid = document.createElement('div');
  allDayGrid.className = 'calendar-allday-grid';
  const segments = rowSegments(state.items, from, 0, { allDayOnly: true });
  packLanes(segments);
  for (const segment of segments) {
    allDayGrid.appendChild(placeSegment(segment, segment.lane + 1));
  }
  if (!segments.length) {
    allDayGrid.classList.add('is-empty');
  }
  allDay.appendChild(allDayGrid);
  wrapper.appendChild(allDay);

  const scroller = document.createElement('div');
  scroller.className = 'calendar-timegrid-scroll';
  const grid = document.createElement('div');
  grid.className = 'calendar-timegrid';
  grid.style.setProperty('--hour-px', `${HOUR_PX}px`);

  const gutter = document.createElement('div');
  gutter.className = 'calendar-hours';
  for (let hour = 0; hour < 24; hour += 1) {
    const label = document.createElement('div');
    label.textContent = hour === 0 ? '' : formatters.time.format(new Date(2000, 0, 1, hour));
    gutter.appendChild(label);
  }
  grid.appendChild(gutter);

  const perDay = dayPieces(state.items, from);
  let earliest = 24;
  perDay.forEach((pieces, col) => {
    const column = document.createElement('div');
    column.className = 'calendar-timegrid-day';
    const date = addDays(from, col);
    if (dateKey(date) === dateKey(new Date())) {
      const now = new Date();
      const line = document.createElement('div');
      line.className = 'calendar-now';
      line.style.top = `${((now - date) / 3_600_000) * HOUR_PX}px`;
      line.setAttribute('aria-hidden', 'true');
      column.appendChild(line);
    }
    for (const piece of pieces) {
      earliest = Math.min(earliest, piece.top);
      const height = Math.max((piece.bottom - piece.top) * HOUR_PX - 2, 20);
      // Under ~45 minutes there's room for one line only: time and name side by side.
      const short = height < 34;
      const link = itemLink(piece.item, { showTime: true, compact: short });
      link.classList.add('is-timed');
      link.classList.toggle('is-short', short);
      link.style.top = `${piece.top * HOUR_PX}px`;
      link.style.height = `${height}px`;
      link.style.left = `calc(${(100 / piece.columns) * piece.column}% + 2px)`;
      link.style.width = `calc(${100 / piece.columns}% - 4px)`;
      column.appendChild(link);
    }
    grid.appendChild(column);
  });
  scroller.appendChild(grid);
  wrapper.appendChild(scroller);

  // Start the view at 8am, or earlier if a meeting starts before then.
  requestAnimationFrame(() => {
    scroller.scrollTop = Math.max(Math.min(earliest, 8) - 0.5, 0) * HOUR_PX;
  });
  return wrapper;
}

// ---------- page state ----------

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('view') === 'week' || params.get('view') === 'month') {
    state.view = params.get('view');
  }
  const date = params.get('date');
  if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
    state.cursor = parseDateKey(date);
  }
  for (const [name, input] of Object.entries(filters)) {
    const value = params.get(name);
    if (value === null) {
      continue;
    }
    if (input.type === 'checkbox') {
      input.checked = value === 'true';
    } else if ([...input.options].some((option) => option.value === value)) {
      input.value = value;
    }
  }
}

function writeUrl() {
  const params = new URLSearchParams({ view: state.view, date: dateKey(state.cursor) });
  for (const [name, input] of Object.entries(filters)) {
    if (input.type === 'checkbox') {
      if (input.checked) {
        params.set(name, 'true');
      }
    } else if (input.value && input.value !== input.options[0].value) {
      params.set(name, input.value);
    }
  }
  window.history.replaceState(null, '', `${window.location.pathname}?${params}`);
}

function showError(message) {
  errorNode.hidden = !message;
  errorNode.textContent = message || '';
}

function render() {
  const { from, days } = visibleRange();
  title.textContent = periodTitle(from, days);
  viewButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.view === state.view)));
  body.replaceChildren(state.view === 'week' ? renderWeek(from) : renderMonth(from, days));

  const count = state.items.length;
  const period = state.view === 'week' ? 'this week' : 'this month view';
  summary.textContent = count
    ? `${count} meeting${count === 1 ? '' : 's'} ${period}.`
    : `No meetings match these filters ${period}.`;
}

async function refresh() {
  writeUrl();
  const { from, days } = visibleRange();
  const params = new URLSearchParams({
    start: from.toISOString(),
    end: addDays(from, days).toISOString(),
    show: filters.show.value,
    scope: scopeField.hidden ? 'mine' : filters.scope.value,
    cancelled: String(filters.cancelled.checked),
  });
  if (filters.role.value) {
    params.set('role', filters.role.value);
  }

  const token = ++loadToken;
  body.classList.add('is-loading');
  try {
    const result = await request('GET', `/api/calendar?${params}`);
    if (token !== loadToken) {
      return; // a newer request replaced this one
    }
    state.items = result.items;
    showError('');
  } catch (error) {
    if (token !== loadToken) {
      return;
    }
    if (error instanceof ApiError && error.status === 401) {
      window.location.assign('login.html');
      return;
    }
    state.items = [];
    showError(error.message || 'Unable to load the calendar.');
  } finally {
    if (token === loadToken) {
      body.classList.remove('is-loading');
    }
  }
  render();
}

function move(step) {
  state.cursor = state.view === 'week'
    ? addDays(state.cursor, 7 * step)
    : new Date(state.cursor.getFullYear(), state.cursor.getMonth() + step, 1);
  refresh();
}

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();
  let user;
  try {
    user = await guardAuthenticatedPage();
  } catch {
    return;
  }

  scopeField.hidden = !VIEW_ROLES.has(user.role);
  readUrl();

  viewButtons.forEach((button) => button.addEventListener('click', () => {
    state.view = button.dataset.view;
    refresh();
  }));
  document.querySelector('[data-testid="calendar-prev"]').addEventListener('click', () => move(-1));
  document.querySelector('[data-testid="calendar-next"]').addEventListener('click', () => move(1));
  document.querySelector('[data-testid="calendar-today"]').addEventListener('click', () => {
    state.cursor = startOfDay(new Date());
    refresh();
  });
  filtersForm.addEventListener('change', refresh);
  filtersForm.addEventListener('submit', (event) => event.preventDefault());

  await refresh();
}

init();
