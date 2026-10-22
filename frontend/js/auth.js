import { ApiError, request } from './api.js';

function showPageAlert(message) {
  const alert = document.querySelector('[role="alert"]');
  if (!alert) {
    return;
  }

  alert.hidden = false;
  alert.textContent = message;
}

export function buildAuthenticatedNav() {
  let nav = document.querySelector('#app-nav');
  if (!nav) {
    nav = document.createElement('nav');
    nav.id = 'app-nav';
    const firstMain = document.querySelector('main');
    if (firstMain) {
      document.body.insertBefore(nav, firstMain);
    } else {
      document.body.appendChild(nav);
    }
  }

  nav.replaceChildren();

  const links = [
    { label: 'Availability', href: 'availability.html' },
    { label: 'Meetings', href: 'meetings.html' },
    { label: 'New meeting', href: 'meeting-new.html' },
  ];

  for (const link of links) {
    const anchor = document.createElement('a');
    anchor.href = link.href;
    anchor.textContent = link.label;
    nav.appendChild(anchor);
  }

  const logoutButton = document.createElement('button');
  logoutButton.type = 'button';
  logoutButton.dataset.testid = 'logout';
  logoutButton.textContent = 'Logout';
  logoutButton.addEventListener('click', async (event) => {
    event.preventDefault();
    try {
      await logout();
    } catch {
      window.location.assign('login.html');
    }
  });
  nav.appendChild(logoutButton);

  return nav;
}

// Links only Admins see. The server checks the role again; this only hides them.
const ADMIN_LINKS = [{ label: 'Monitoring', href: 'monitoring.html' }];

export function addRoleNavLinks(user) {
  const nav = document.querySelector('#app-nav');
  if (!nav || !user || user.role !== 'Admin' || nav.querySelector('[data-admin-link]')) {
    return;
  }

  const logoutButton = nav.querySelector('[data-testid="logout"]');
  for (const link of ADMIN_LINKS) {
    const anchor = document.createElement('a');
    anchor.href = link.href;
    anchor.textContent = link.label;
    anchor.dataset.adminLink = 'true';
    nav.insertBefore(anchor, logoutButton);
  }
  nav.style.setProperty('--nav-links', String(nav.querySelectorAll('a').length));
}

export async function requireSessionUser() {
  try {
    const user = await request('GET', '/api/auth/me');
    addRoleNavLinks(user);
    return user;
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) {
        window.location.assign('login.html');
      } else {
        showPageAlert(error.message || 'Unable to load the current session.');
      }
    }

    throw error;
  }
}

export async function guardAuthenticatedPage() {
  try {
    return await requireSessionUser();
  } catch (error) {
    throw error;
  }
}

export async function logout() {
  await request('POST', '/api/auth/logout');
  window.location.assign('login.html');
}

export function bindLogoutButton(button = document.querySelector('[data-testid="logout"]')) {
  if (!button) {
    return;
  }

  button.addEventListener('click', async (event) => {
    event.preventDefault();
    button.disabled = true;

    try {
      await logout();
    } finally {
      button.disabled = false;
    }
  });
}
