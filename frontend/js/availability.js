import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';
import { localInputToUtcIso, utcToLocalString } from './time.js';
import { request } from './api.js';

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const saveButton = document.querySelector('[data-testid="avail-save"]');
const saveStatus = document.querySelector('[data-testid="avail-status"]');
const form = document.querySelector('#unavailability-form');
const onceFields = document.querySelector('#unavail-once-fields');
const recurringFields = document.querySelector('#unavail-recurring-fields');
const formError = document.querySelector('[data-testid="form-error"]');
const unavailList = document.querySelector('[data-testid="unavail-list"]');

function showError(message) {
  formError.hidden = false;
  formError.textContent = message;
}

function clearError() {
  formError.hidden = true;
  formError.textContent = '';
}

function getTimeZone() {
  return document.body.dataset.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

function setAvailabilityCheckboxState(item) {
  for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
    const enabled = document.querySelector(`[data-testid="avail-day-${dayIndex}-enabled"]`);
    const start = document.querySelector(`[data-testid="avail-day-${dayIndex}-start"]`);
    const end = document.querySelector(`[data-testid="avail-day-${dayIndex}-end"]`);

    const current = item.find((entry) => entry.dayOfWeek === dayIndex);
    enabled.checked = Boolean(current);
    start.value = current ? current.start : '';
    end.value = current ? current.end : '';
  }
}

function renderAvailability(payload) {
  const availability = payload.availability || [];
  setAvailabilityCheckboxState(availability);
  document.body.dataset.timezone = payload.timezone || getTimeZone();
}

function renderUnavailability(items, timezone) {
  unavailList.replaceChildren();

  if (!items.length) {
    const message = document.createElement('li');
    message.textContent = 'No unavailability added yet.';
    unavailList.appendChild(message);
    return;
  }

  for (const item of items) {
    const row = document.createElement('li');

    const label = document.createElement('span');
    label.textContent = item.label;
    row.appendChild(label);

    const details = document.createElement('span');
    details.textContent = ` — ${formatUnavailability(item, timezone)}`;
    row.appendChild(details);

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.textContent = 'Remove';
    removeButton.dataset.testid = `unavail-remove-${item.id}`;
    removeButton.addEventListener('click', async () => {
      await request('DELETE', `/api/me/unavailability/${item.id}`);
      await loadUnavailability();
    });

    row.appendChild(removeButton);
    unavailList.appendChild(row);
  }
}

function formatUnavailability(item, timezone) {
  if (item.type === 'once') {
    return `${utcToLocalString(item.start, timezone)} to ${utcToLocalString(item.end, timezone)}`;
  }

  const days = (item.daysOfWeek || []).map((day) => DAY_NAMES[Number(day)]).join(', ');
  return `${days} ${item.startTime}–${item.endTime}`;
}

async function loadAvailability() {
  const payload = await request('GET', '/api/me/availability');
  renderAvailability(payload);
}

async function loadUnavailability() {
  const payload = await request('GET', '/api/me/availability');
  renderUnavailability(payload.unavailability || [], payload.timezone || getTimeZone());
}

async function saveAvailability() {
  const timezone = getTimeZone();
  const nextAvailability = [];

  saveButton.disabled = true;

  try {
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const enabled = document.querySelector(`[data-testid="avail-day-${dayIndex}-enabled"]`);
      const start = document.querySelector(`[data-testid="avail-day-${dayIndex}-start"]`);
      const end = document.querySelector(`[data-testid="avail-day-${dayIndex}-end"]`);

      if (!enabled.checked) {
        continue;
      }

      if (!start.value || !end.value) {
        throw new Error('Each enabled day needs a start and end time.');
      }

      if (end.value <= start.value) {
        throw new Error(`End time for ${DAY_NAMES[dayIndex]} must be after the start time.`);
      }

      nextAvailability.push({
        dayOfWeek: dayIndex,
        start: start.value,
        end: end.value,
      });
    }

    await request('PUT', '/api/me/availability', { availability: nextAvailability });
    saveStatus.textContent = 'Saved';
    document.body.dataset.timezone = timezone;
  } finally {
    saveButton.disabled = false;
  }
}

function bindTypeSwitching() {
  const radioButtons = document.querySelectorAll('input[name="unavail-type"]');
  radioButtons.forEach((radio) => {
    radio.addEventListener('change', () => {
      const selected = radio.value;
      onceFields.hidden = selected !== 'once';
      recurringFields.hidden = selected !== 'recurring';
    });
  });
}

async function addUnavailability(event) {
  event.preventDefault();
  clearError();

  const submit = document.querySelector('[data-testid="unavail-add"]');
  submit.disabled = true;

  try {
    const formData = new FormData(form);
    const label = String(formData.get('label') || '').trim();
    const type = formData.get('unavail-type');
    const timezone = getTimeZone();

    if (!label) {
      showError('Label is required.');
      return;
    }

    if (type === 'once') {
      const startValue = String(formData.get('once-start') || '');
      const endValue = String(formData.get('once-end') || '');

      if (!startValue || !endValue) {
        showError('One-off unavailability needs a start and end time.');
        return;
      }

      const start = localInputToUtcIso(startValue, timezone);
      const end = localInputToUtcIso(endValue, timezone);

      if (!start || !end || new Date(end) <= new Date(start)) {
        showError('One-off end time must be later than the start time.');
        return;
      }

      await request('POST', '/api/me/unavailability', {
        label,
        type: 'once',
        start,
        end,
      });
    } else {
      const selectedDays = formData.getAll('recurring-day').map((value) => Number(value));
      const startTime = String(formData.get('recurring-start') || '');
      const endTime = String(formData.get('recurring-end') || '');
      const recurUntil = String(formData.get('recurring-until') || '');

      if (!selectedDays.length || !startTime || !endTime) {
        showError('Recurring unavailability needs at least one day and a time range.');
        return;
      }

      if (endTime <= startTime) {
        showError('Recurring end time must be later than the start time.');
        return;
      }

      await request('POST', '/api/me/unavailability', {
        label,
        type: 'recurring',
        daysOfWeek: selectedDays,
        startTime,
        endTime,
        recurUntil: recurUntil || null,
      });
    }

    form.reset();
    onceFields.hidden = false;
    recurringFields.hidden = true;
    await loadUnavailability();
    clearError();
  } finally {
    submit.disabled = false;
  }
}

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();
  bindTypeSwitching();

  try {
    await guardAuthenticatedPage();
    const payload = await request('GET', '/api/me/availability');
    renderAvailability(payload);
    await loadUnavailability();

    saveButton.addEventListener('click', async () => {
      clearError();
      try {
        await saveAvailability();
      } catch (error) {
        showError(error.message || 'Unable to save availability.');
      }
    });

    form.addEventListener('submit', async (event) => {
      try {
        await addUnavailability(event);
      } catch (error) {
        showError(error.message || 'Unable to add unavailability.');
      }
    });
  } catch (error) {
    if (error && error.status === 401) {
      window.location.assign('login.html');
    } else {
      showError(error && error.message ? error.message : 'Unable to load availability.');
    }
  }
}

init();
