import test from 'node:test';
import assert from 'node:assert/strict';

import { formatSlot, localInputToUtcIso, utcToLocalString } from '../../../frontend/js/time.js';

const melbourneTimeZone = 'Australia/Melbourne';

test('utcToLocalString converts UTC timestamps into the supplied timezone', () => {
  const iso = '2024-01-15T12:30:00Z';
  const expected = new Intl.DateTimeFormat(undefined, {
    timeZone: melbourneTimeZone,
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));

  assert.equal(utcToLocalString(iso, melbourneTimeZone), expected);
});

test('localInputToUtcIso converts a wall-clock timestamp for a timezone to UTC', () => {
  assert.equal(
    localInputToUtcIso('2024-01-15T23:30', melbourneTimeZone),
    '2024-01-15T12:30:00.000Z',
  );
});

test('formatSlot joins the start and end times in the viewer timezone', () => {
  const start = '2024-01-15T12:30:00Z';
  const end = '2024-01-15T13:00:00Z';

  const expected = `${utcToLocalString(start, melbourneTimeZone)} – ${utcToLocalString(end, melbourneTimeZone)}`;
  assert.equal(formatSlot(start, end, melbourneTimeZone), expected);
});

test('DST changes are handled correctly for Australia/Melbourne', () => {
  assert.equal(
    localInputToUtcIso('2024-10-06T03:30', melbourneTimeZone),
    '2024-10-05T16:30:00.000Z',
  );
  assert.equal(
    localInputToUtcIso('2024-04-07T09:00', melbourneTimeZone),
    '2024-04-06T23:00:00.000Z',
  );
});
