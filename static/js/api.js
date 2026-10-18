// Fetch wrapper: JSON everywhere, one error type, session-expiry redirects.

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
  }
}

export async function api(path, opts = {}) {
  const init = {
    ...opts,
    headers: {
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
      ...(opts.headers || {}),
    },
  };
  const res = await fetch(path, init);
  // Session gone/expired → back to the login view (unless we're already there).
  if (res.status === 401 && !location.hash.startsWith("#/login")) {
    location.hash = "#/login";
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON (e.g. markdown report) */ }
  if (!res.ok) throw new ApiError(res.status, body?.detail || res.statusText);
  return body;
}
