import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';
import { request } from './api.js';
import { utcToLocalString } from './time.js';

const container = document.querySelector('#meetings-container');

function createTextCell(text) {
  const cell = document.createElement('td');
  cell.textContent = text;
  return cell;
}

function createMeetingTable(meetings) {
  const table = document.createElement('table');
  table.dataset.testid = 'meetings-table';

  const head = document.createElement('thead');
  const headingRow = document.createElement('tr');

  ['Name', 'Status', 'Final time', 'Participants', 'Link'].forEach((label) => {
    const header = document.createElement('th');
    header.textContent = label;
    headingRow.appendChild(header);
  });

  head.appendChild(headingRow);
  table.appendChild(head);

  const body = document.createElement('tbody');

  for (const meeting of meetings) {
    const row = document.createElement('tr');
    row.appendChild(createTextCell(meeting.name || 'Untitled meeting'));
    row.appendChild(createTextCell(meeting.status || 'unknown'));

    const finalTimeCell = document.createElement('td');
    const finalSlot = meeting.finalSlot || null;
    if (finalSlot && finalSlot.start && finalSlot.end) {
      finalTimeCell.textContent = `${utcToLocalString(finalSlot.start, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')} – ${utcToLocalString(finalSlot.end, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')}`;
    } else {
      finalTimeCell.textContent = 'Not scheduled';
    }
    row.appendChild(finalTimeCell);

    row.appendChild(createTextCell(String((meeting.participants || []).length)));

    const linkCell = document.createElement('td');
    const link = document.createElement('a');
    link.href = `meeting.html?id=${meeting.id}`;
    link.textContent = 'Open';
    link.dataset.testid = `meeting-link-${meeting.id}`;
    linkCell.appendChild(link);
    row.appendChild(linkCell);

    body.appendChild(row);
  }

  table.appendChild(body);
  return table;
}

async function loadMeetings() {
  const meetings = await request('GET', '/api/meetings');
  container.replaceChildren();

  if (!meetings || meetings.length === 0) {
    const empty = document.createElement('p');
    empty.textContent = 'No meetings yet.';
    container.appendChild(empty);
    return;
  }

  container.appendChild(createMeetingTable(meetings));
}

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();
  try {
    await guardAuthenticatedPage();
    await loadMeetings();
  } catch (error) {
    if (error && error.status === 401) {
      window.location.assign('login.html');
    } else {
      const alertNode = document.createElement('p');
      alertNode.setAttribute('role', 'alert');
      alertNode.textContent = error && error.message ? error.message : 'Unable to load meetings.';
      const container = document.querySelector('#meetings-container');
      if (container) {
        container.replaceChildren(alertNode);
      }
    }
  }
}

init();
