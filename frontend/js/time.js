function resolveTimeZone(timeZone) {
  if (timeZone) {
    return timeZone;
  }

  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function getOffsetMinutes(date, timeZone) {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  const parts = formatter.formatToParts(date);
  const values = {};

  for (const part of parts) {
    if (part.type !== 'literal') {
      values[part.type] = part.value;
    }
  }

  const localEpochMs = Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    Number(values.hour),
    Number(values.minute),
    Number(values.second),
  );

  return (localEpochMs - date.getTime()) / 60000;
}

export function utcToLocalString(iso, timeZone = resolveTimeZone()) {
  const date = new Date(iso);

  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid ISO timestamp: ${iso}`);
  }

  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function localInputToUtcIso(datetimeLocalValue, timeZone = resolveTimeZone()) {
  if (!datetimeLocalValue) {
    return null;
  }

  const match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})$/.exec(datetimeLocalValue);
  if (!match) {
    return null;
  }

  const [, year, month, day, hour, minute] = match;
  const naiveEpochMs = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );

  const offsetMinutes = getOffsetMinutes(new Date(naiveEpochMs), timeZone);
  const utcMs = naiveEpochMs - offsetMinutes * 60_000;

  return new Date(utcMs).toISOString();
}

export function formatSlot(startIso, endIso, timeZone = resolveTimeZone()) {
  return `${utcToLocalString(startIso, timeZone)} – ${utcToLocalString(endIso, timeZone)}`;
}
