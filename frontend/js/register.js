import { request } from './api.js';

const form = document.querySelector('form');
const nameInput = document.querySelector('[data-testid="register-name"]');
const emailInput = document.querySelector('[data-testid="register-email"]');
const passwordInput = document.querySelector('[data-testid="register-password"]');
const roleInput = document.querySelector('[data-testid="register-role"]');
const timezoneInput = document.querySelector('[data-testid="register-timezone"]');
const submitButton = document.querySelector('[data-testid="register-submit"]');
const errorBox = document.querySelector('[data-testid="form-error"]');

function showError(message) {
  if (!errorBox) {
    return;
  }

  errorBox.hidden = false;
  errorBox.textContent = message;
}

function clearError() {
  if (!errorBox) {
    return;
  }

  errorBox.hidden = true;
  errorBox.textContent = '';
}

if (timezoneInput && !timezoneInput.value) {
  timezoneInput.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearError();

  const payload = {
    name: nameInput.value.trim(),
    email: emailInput.value.trim(),
    password: passwordInput.value,
    role: roleInput.value || null,
    timezone: timezoneInput.value,
  };

  submitButton.disabled = true;

  try {
    const user = await request('POST', '/api/auth/register', payload);
    if (user && user.id) {
      window.location.assign('availability.html');
    }
  } catch (error) {
    showError(error.message || 'Unable to register.');
  } finally {
    submitButton.disabled = false;
  }
});
