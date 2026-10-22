import { request } from './api.js';

const form = document.querySelector('form');
const emailInput = document.querySelector('[data-testid="login-email"]');
const passwordInput = document.querySelector('[data-testid="login-password"]');
const submitButton = document.querySelector('[data-testid="login-submit"]');
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

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearError();

  const payload = {
    email: emailInput.value.trim(),
    password: passwordInput.value,
  };

  submitButton.disabled = true;

  try {
    const user = await request('POST', '/api/auth/login', payload);
    if (user && user.id) {
      window.location.assign('meetings.html');
    }
  } catch (error) {
    showError(error.message || 'Unable to log in.');
  } finally {
    submitButton.disabled = false;
  }
});
