import { bindLogoutButton, buildAuthenticatedNav, guardAuthenticatedPage } from './auth.js';
import { request } from './api.js';

const roles = ['Admin', 'Manager', 'Senior Staff', 'Staff', 'Junior Staff'];
const inviteUserList = document.querySelector('#invite-users-list');
const includeRoleList = document.querySelector('#include-role-list');
const excludeRoleList = document.querySelector('#exclude-role-list');
const excludeUserList = document.querySelector('#exclude-users-list');
const form = document.querySelector('#meeting-form');
const formError = document.querySelector('[data-testid="form-error"]');
const submitButton = document.querySelector('[data-testid="meeting-create"]');

function showError(message) {
  formError.hidden = false;
  formError.textContent = message;
}

function clearError() {
  formError.hidden = true;
  formError.textContent = '';
}

function slugifyRole(role) {
  return role.toLowerCase().replace(/\s+/g, '-');
}

function createCheckbox(labelText, name, value, testId) {
  const label = document.createElement('label');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.name = name;
  checkbox.value = value;
  checkbox.dataset.testid = testId;
  checkbox.checked = false;

  const text = document.createElement('span');
  text.textContent = labelText;

  label.appendChild(checkbox);
  label.appendChild(text);
  return label;
}

async function loadUsers() {
  const users = await request('GET', '/api/users');

  inviteUserList.replaceChildren();
  excludeUserList.replaceChildren();

  for (const user of users) {
    const inviteLabel = createCheckbox(`${user.name} (${user.role || 'No role'})`, 'includeUserIds', user.id, `invite-user-${user.id}`);
    inviteUserList.appendChild(inviteLabel);

    const excludeLabel = createCheckbox(`${user.name} (${user.role || 'No role'})`, 'excludeUserIds', user.id, `exclude-user-${user.id}`);
    excludeUserList.appendChild(excludeLabel);
  }
}

function loadRoleCheckboxes() {
  includeRoleList.replaceChildren();
  excludeRoleList.replaceChildren();

  for (const role of roles) {
    const includeLabel = createCheckbox(`Invite role ${role}`, 'includeRoles', role, `include-role-${slugifyRole(role)}`);
    includeRoleList.appendChild(includeLabel);

    const excludeLabel = createCheckbox(`Exclude role ${role}`, 'excludeRoles', role, `exclude-role-${slugifyRole(role)}`);
    excludeRoleList.appendChild(excludeLabel);
  }
}

async function submitMeeting(event) {
  event.preventDefault();
  clearError();

  const formData = new FormData(form);
  const name = String(formData.get('name') || '').trim();
  const durationMinutes = Number(formData.get('duration'));
  const earliestDate = String(formData.get('earliestDate') || '');
  const latestDate = String(formData.get('latestDate') || '');

  if (!name) {
    showError('Meeting name is required.');
    return;
  }

  if (!Number.isFinite(durationMinutes) || durationMinutes <= 0) {
    showError('Duration must be greater than 0 minutes.');
    return;
  }

  if (!earliestDate || !latestDate) {
    showError('Earliest and latest dates are required.');
    return;
  }

  if (latestDate < earliestDate) {
    showError('Latest date must be on or after the earliest date.');
    return;
  }

  const payload = {
    name,
    durationMinutes,
    earliestDate,
    latestDate,
    includeRoles: formData.getAll('includeRoles'),
    excludeRoles: formData.getAll('excludeRoles'),
    includeUserIds: formData.getAll('includeUserIds'),
    excludeUserIds: formData.getAll('excludeUserIds'),
  };

  submitButton.disabled = true;

  try {
    const result = await request('POST', '/api/meetings', payload);
    window.location.assign(`meeting.html?id=${result.id}`);
  } catch (error) {
    showError(error.message || 'Unable to create meeting.');
  } finally {
    submitButton.disabled = false;
  }
}

async function init() {
  buildAuthenticatedNav();
  bindLogoutButton();

  try {
    await guardAuthenticatedPage();
    loadRoleCheckboxes();
    await loadUsers();
    form.addEventListener('submit', submitMeeting);
  } catch (error) {
    if (error && error.status === 401) {
      window.location.assign('login.html');
    } else if (error && error.message) {
      showError(error.message);
    }
  }
}

init();
