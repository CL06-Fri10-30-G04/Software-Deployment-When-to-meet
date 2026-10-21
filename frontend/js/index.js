import { requireSessionUser } from './auth.js';

async function redirectBasedOnSession() {
  try {
    await requireSessionUser();
    window.location.assign('meetings.html');
  } catch {
    window.location.assign('login.html');
  }
}

redirectBasedOnSession();
