/**
 * All_Chat — API Client
 * Centralized fetch wrapper with:
 *   - Automatic Bearer token attachment
 *   - Transparent token refresh on 401
 *   - JSON / FormData support
 *   - Error normalization
 */

const API = (() => {
  const BASE = '/api';

  function getAccessToken()  { return localStorage.getItem('ac_access'); }
  function getRefreshToken() { return localStorage.getItem('ac_refresh'); }
  function setTokens(access, refresh) {
    localStorage.setItem('ac_access',  access);
    if (refresh) localStorage.setItem('ac_refresh', refresh);
  }
  function clearTokens() {
    localStorage.removeItem('ac_access');
    localStorage.removeItem('ac_refresh');
  }

  let _refreshing = null; // singleton refresh promise

  async function refreshTokens() {
    if (_refreshing) return _refreshing;
    _refreshing = (async () => {
      const rt = getRefreshToken();
      if (!rt) throw new Error('No refresh token');
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) { clearTokens(); throw new Error('Session expired'); }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      return data.access_token;
    })();
    _refreshing.finally(() => { _refreshing = null; });
    return _refreshing;
  }

  async function request(method, path, body = null, isForm = false, retry = true) {
    const token = getAccessToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const opts = { method, headers };

    if (body !== null) {
      if (isForm) {
        opts.body = body; // FormData — browser sets Content-Type
      } else {
        headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
    }

    let res = await fetch(`${BASE}${path}`, opts);

    // Auto-refresh on 401
    if (res.status === 401 && retry) {
      try {
        await refreshTokens();
        return request(method, path, body, isForm, false);
      } catch {
        clearTokens();
        window.dispatchEvent(new CustomEvent('auth:logout'));
        throw new APIError(401, 'Session expired. Please log in again.');
      }
    }

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
      throw new APIError(res.status, detail);
    }

    if (res.status === 204) return null;

    const ct = res.headers.get('Content-Type') || '';
    if (ct.includes('application/json')) return res.json();
    return res.text();
  }

  class APIError extends Error {
    constructor(status, detail) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  }

  return {
    get:    (path)          => request('GET',    path),
    post:   (path, body)    => request('POST',   path, body),
    patch:  (path, body)    => request('PATCH',  path, body),
    put:    (path, body)    => request('PUT',    path, body),
    delete: (path)          => request('DELETE', path),
    form:   (path, formData, method = 'POST') => request(method, path, formData, true),

    setTokens,
    clearTokens,
    getAccessToken,
    getRefreshToken,
    isLoggedIn: () => !!getAccessToken(),

    APIError,
  };
})();
