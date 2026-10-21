import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';
import { request } from './api.js';
import { formatSlot, utcToLocalString } from './time.js';

const meetingId = new URLSearchParams(window.location.search).get('id');
const detailsContainer = document.querySelector('#meeting-details');
const actionsContainer = document.querySelector('#meeting-actions');
const participantsContainer = document.querySelector('#participants-section');
const slotsContainer = document.querySelector('#slots-section');
const pageError = document.querySelector('[data-testid="page-error"]');
const pageStatus = document.querySelector('[data-testid="meeting-status"]');

function showPageError(message) {
  pageError.hidden = false;
  pageError.textContent = message;
}

function clearPageError() {
  pageError.hidden = true;
  pageError.textContent = '';
}

function renderTextPair(label, value) {
  const wrapper = document.createElement('p');
  const labelNode = document.createElement('strong');
  labelNode.textContent = `${label}: `;
  const valueNode = document.createElement('span');
  valueNode.textContent = value;
  wrapper.appendChild(labelNode);
  wrapper.appendChild(valueNode);
  return wrapper;
}

function getNameByUserId(participants, userId) {
  const participant = participants.find((item) => item.userId === userId || item.id === userId);
  return participant ? participant.name || participant.email || 'Unknown user' : 'Unknown user';
}

function createParticipantRow(participant, meeting, currentUser, isEditor) {
  const row = document.createElement('tr');

  const nameCell = document.createElement('td');
  nameCell.textContent = participant.name || participant.email || 'Unknown user';
  row.appendChild(nameCell);

  const roleCell = document.createElement('td');
  roleCell.textContent = participant.role || 'Unknown';
  row.appendChild(roleCell);

  const responseCell = document.createElement('td');
  responseCell.textContent = participant.response || 'No response';
  row.appendChild(responseCell);

  if (isEditor) {
    const removeCell = document.createElement('td');
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.textContent = 'Remove';
    removeButton.dataset.testid = `participant-remove-${participant.userId || participant.id}`;
    removeButton.addEventListener('click', async () => {
      await request('DELETE', `/api/meetings/${meeting.id}/participants/${participant.userId || participant.id}`);
      await loadMeetingState();
    });
    removeCell.appendChild(removeButton);
    row.appendChild(removeCell);
  }

  return row;
}

function renderParticipants(meeting, currentUser, isEditor, allUsers) {
  participantsContainer.replaceChildren();

  const heading = document.createElement('h2');
  heading.textContent = 'Participants';
  participantsContainer.appendChild(heading);

  const table = document.createElement('table');
  table.dataset.testid = 'participants-table';
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['Name', 'Role', 'Response'].forEach((label) => {
    const header = document.createElement('th');
    header.textContent = label;
    headRow.appendChild(header);
  });
  if (isEditor) {
    const actionHeader = document.createElement('th');
    actionHeader.textContent = 'Action';
    headRow.appendChild(actionHeader);
  }
  head.appendChild(headRow);
  table.appendChild(head);

  const body = document.createElement('tbody');
  for (const participant of meeting.participants || []) {
    body.appendChild(createParticipantRow(participant, meeting, currentUser, isEditor));
  }
  table.appendChild(body);
  participantsContainer.appendChild(table);

  if (isEditor) {
    const addWrapper = document.createElement('div');
    const label = document.createElement('label');
    label.textContent = 'Add participant';

    const select = document.createElement('select');
    select.dataset.testid = 'participant-add-select';
    const placeholder = document.createElement('option');
    placeholder.textContent = 'Select a user';
    placeholder.value = '';
    select.appendChild(placeholder);

    const availableUsers = allUsers.filter((user) => !((meeting.participants || []).some((participant) => participant.userId === user.id)) && user.id !== currentUser.id);
    for (const user of availableUsers) {
      const option = document.createElement('option');
      option.value = user.id;
      option.textContent = `${user.name} (${user.role || 'No role'})`;
      select.appendChild(option);
    }

    const addButton = document.createElement('button');
    addButton.type = 'button';
    addButton.textContent = 'Add';
    addButton.dataset.testid = 'participant-add';
    addButton.addEventListener('click', async () => {
      if (!select.value) {
        return;
      }
      await request('POST', `/api/meetings/${meeting.id}/participants`, { userId: select.value });
      await loadMeetingState();
    });

    label.appendChild(select);
    addWrapper.appendChild(label);
    addWrapper.appendChild(addButton);
    participantsContainer.appendChild(addWrapper);
  }
}

function renderMeetingDetails(meeting, allUsers) {
  detailsContainer.replaceChildren();
  pageStatus.textContent = meeting.status || 'unknown';

  const creatorName = (allUsers || []).find((user) => user.id === meeting.creatorId)?.name || meeting.creatorName || meeting.creatorId || 'Unknown';

  detailsContainer.appendChild(renderTextPair('Name', meeting.name || 'Untitled meeting'));
  detailsContainer.appendChild(renderTextPair('Status', meeting.status || 'unknown'));
  detailsContainer.appendChild(renderTextPair('Date range', `${meeting.earliestDate || '—'} to ${meeting.latestDate || '—'}`));
  detailsContainer.appendChild(renderTextPair('Duration', `${meeting.durationMinutes || 0} minutes`));
  detailsContainer.appendChild(renderTextPair('Creator', creatorName));

  if (meeting.finalSlot && meeting.finalSlot.start && meeting.finalSlot.end) {
    const finalTime = document.createElement('p');
    finalTime.dataset.testid = 'final-time';
    finalTime.textContent = `Final time: ${formatSlot(meeting.finalSlot.start, meeting.finalSlot.end, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')}`;
    detailsContainer.appendChild(finalTime);
  }
}

function renderActions(meeting, currentUser, isEditor) {
  actionsContainer.replaceChildren();

  if (isParticipant(meeting, currentUser) && meeting.status === 'scheduling') {
    const acceptButton = document.createElement('button');
    acceptButton.type = 'button';
    acceptButton.textContent = 'Accept';
    acceptButton.dataset.testid = 'respond-accept';
    acceptButton.addEventListener('click', async () => {
      await request('POST', `/api/meetings/${meeting.id}/respond`, { response: 'accepted' });
      await loadMeetingState();
    });

    const declineButton = document.createElement('button');
    declineButton.type = 'button';
    declineButton.textContent = 'Decline';
    declineButton.dataset.testid = 'respond-decline';
    declineButton.addEventListener('click', async () => {
      await request('POST', `/api/meetings/${meeting.id}/respond`, { response: 'declined' });
      await loadMeetingState();
    });

    actionsContainer.appendChild(acceptButton);
    actionsContainer.appendChild(declineButton);
  }

  if (isEditor && meeting.status !== 'cancelled') {
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.textContent = 'Cancel meeting';
    cancelButton.dataset.testid = 'meeting-cancel';
    cancelButton.addEventListener('click', async () => {
      if (!window.confirm('Cancel this meeting?')) {
        return;
      }
      await request('POST', `/api/meetings/${meeting.id}/cancel`);
      await loadMeetingState();
    });
    actionsContainer.appendChild(cancelButton);
  }
}

function isParticipant(meeting, currentUser) {
  return Boolean((meeting.participants || []).find((participant) => participant.userId === currentUser.id || participant.id === currentUser.id));
}

function renderSlots(meeting, participants) {
  slotsContainer.replaceChildren();

  const heading = document.createElement('h2');
  heading.textContent = 'Candidate slots';
  slotsContainer.appendChild(heading);

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'Find times';
  button.dataset.testid = 'find-slots';
  button.addEventListener('click', async () => {
    await request('POST', `/api/meetings/${meeting.id}/find-slots`);
    await loadMeetingState();
  });
  slotsContainer.appendChild(button);

  const slotRows = meeting.candidateSlots || [];
  if (!slotRows.length) {
    const note = document.createElement('p');
    note.textContent = 'No candidate slots found yet.';
    slotsContainer.appendChild(note);
    return;
  }

  const table = document.createElement('table');
  table.dataset.testid = 'slots-table';
  const head = document.createElement('thead');
  const row = document.createElement('tr');
  ['Time', 'Availability', 'Available', 'Unavailable'].forEach((label) => {
    const header = document.createElement('th');
    header.textContent = label;
    row.appendChild(header);
  });
  if (meeting.status !== 'scheduled' && meeting.status !== 'cancelled') {
    const actionHeader = document.createElement('th');
    actionHeader.textContent = 'Action';
    row.appendChild(actionHeader);
  }
  head.appendChild(row);
  table.appendChild(head);

  const body = document.createElement('tbody');
  for (let index = 0; index < slotRows.length; index += 1) {
    const slot = slotRows[index];
    const slotRow = document.createElement('tr');

    const timeCell = document.createElement('td');
    timeCell.textContent = formatSlot(slot.start, slot.end, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
    slotRow.appendChild(timeCell);

    const availabilityCell = document.createElement('td');
    const total = slot.availableUserIds ? slot.availableUserIds.length + (slot.unavailableUserIds || []).length : 0;
    availabilityCell.textContent = `${slot.availableUserIds ? slot.availableUserIds.length : 0} of ${total || (meeting.participants || []).length} available`;
    slotRow.appendChild(availabilityCell);

    const availableCell = document.createElement('td');
    const availableNames = (slot.availableUserIds || []).map((userId) => getNameByUserId(participants, userId)).join(', ');
    availableCell.textContent = availableNames || 'No one';
    slotRow.appendChild(availableCell);

    const unavailableCell = document.createElement('td');
    const unavailableNames = (slot.unavailableUserIds || []).map((userId) => getNameByUserId(participants, userId)).join(', ');
    unavailableCell.textContent = unavailableNames || 'None';
    slotRow.appendChild(unavailableCell);

    if (meeting.status !== 'scheduled' && meeting.status !== 'cancelled') {
      const actionCell = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Select this time';
      button.dataset.testid = `slot-select-${index}`;
      button.addEventListener('click', async () => {
        clearPageError();
        try {
          await request('POST', `/api/meetings/${meeting.id}/finalise`, {
            slot: { start: slot.start, end: slot.end },
            force: false,
          });
          await loadMeetingState();
        } catch (error) {
          if (error && error.code === 'participants_unavailable') {
            showPageError(`${error.message || 'Some participants are unavailable.'}`);
            const scheduleAnywayButton = document.createElement('button');
            scheduleAnywayButton.type = 'button';
            scheduleAnywayButton.textContent = 'Schedule anyway';
            scheduleAnywayButton.dataset.testid = 'force-schedule';
            scheduleAnywayButton.addEventListener('click', async () => {
              try {
                const confirmedMeeting = await request('POST', `/api/meetings/${meeting.id}/finalise`, {
                  slot: { start: slot.start, end: slot.end },
                  force: true,
                });

                const unavailableNames = (slot.unavailableUserIds || []).map((userId) => getNameByUserId(participants, userId)).join(', ');
                const forcedNotice = document.createElement('p');
                forcedNotice.textContent = `Scheduled with unavailable participants: ${unavailableNames || 'Unknown users'}`;
                slotsContainer.appendChild(forcedNotice);

                if (confirmedMeeting && confirmedMeeting.finalSlot) {
                  await loadMeetingState();
                }
              } catch (forceError) {
                showPageError(forceError.message || 'Unable to finalise the meeting.');
              }
            });
            slotsContainer.appendChild(scheduleAnywayButton);
          } else {
            showPageError(error.message || 'Unable to finalise the meeting.');
          }
        }
      });
      actionCell.appendChild(button);
      slotRow.appendChild(actionCell);
    }

    body.appendChild(slotRow);
  }

  table.appendChild(body);
  slotsContainer.appendChild(table);
}

async function loadMeetingState() {
  clearPageError();
  const [meeting, currentUser, allUsers] = await Promise.all([
    request('GET', `/api/meetings/${meetingId}`),
    request('GET', '/api/auth/me'),
    request('GET', '/api/users'),
  ]);

  const isEditor = meeting.creatorId === currentUser.id || currentUser.role === 'Admin' || currentUser.role === 'Manager';
  renderMeetingDetails(meeting, allUsers);
  renderActions(meeting, currentUser, isEditor);
  renderParticipants(meeting, currentUser, isEditor, allUsers);
  renderSlots(meeting, meeting.participants || []);

  const finalValue = meeting.finalSlot ? document.querySelector('[data-testid="final-time"]') : null;
  if (finalValue && meeting.status === 'scheduled') {
    finalValue.textContent = `Final time: ${formatSlot(meeting.finalSlot.start, meeting.finalSlot.end, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')}`;
  }
}

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();

  try {
    await guardAuthenticatedPage();
    if (!meetingId) {
      showPageError('Meeting id is required.');
      return;
    }

    await loadMeetingState();
  } catch (error) {
    if (error && error.status === 401) {
      window.location.assign('login.html');
    } else {
      showPageError(error.message || 'Unable to load meeting.');
    }
  }
}

init();
