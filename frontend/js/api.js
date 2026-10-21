export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.message = message;
  }
}

async function readResponsePayload(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function request(method, path, body) {
  const headers = {
    Accept: 'application/json',
  };

  const init = {
    method,
    credentials: 'same-origin',
    headers,
  };

  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  const response = await fetch(path, init);
  const payload = await readResponsePayload(response);

  if (!response.ok) {
    const errorCode = payload && typeof payload === 'object' && payload.error ? payload.error : 'request_failed';
    const errorMessage = payload && typeof payload === 'object' && payload.message ? payload.message : response.statusText || 'Request failed';

    if (response.status === 401) {
      window.location.assign('login.html');
    }

    throw new ApiError(response.status, errorCode, errorMessage);
  }

  return payload;
}
