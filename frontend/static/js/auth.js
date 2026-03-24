/**
 * All_Chat — Auth Module
 * Login, register, logout, current user state.
 */

const Auth = (() => {
  let _user = null;

  async function loadUser() {
    if (!API.isLoggedIn()) { _user = null; return null; }
    try {
      _user = await API.get('/users/me');
      return _user;
    } catch {
      API.clearTokens();
      _user = null;
      return null;
    }
  }

  function getUser() { return _user; }
  function isLoggedIn() { return !!_user; }

  function setUser(u) { _user = u; }

  async function login(identifier, password) {
    const data = await API.post('/auth/login', { username: identifier, password });
    API.setTokens(data.access_token, data.refresh_token);
    await loadUser();
    window.dispatchEvent(new CustomEvent('auth:login', { detail: _user }));
    return _user;
  }

  async function register(username, email, password) {
    return API.post('/auth/register', { username, email, password });
  }

  async function logout() {
    API.clearTokens();
    _user = null;
    window.dispatchEvent(new CustomEvent('auth:logout'));
  }

  async function forgotPassword(email) {
    return API.post('/auth/forgot-password', { email });
  }

  async function resetPassword(token, new_password) {
    return API.post('/auth/reset-password', { token, new_password });
  }

  async function verifyEmail(token) {
    return API.post('/auth/verify-email', { token });
  }

  // ── Views ──────────────────────────────────────────────────────

  function renderLoginForm() {
    return `
      <div class="auth-container">
        <div class="auth-header">
          <h1>Welcome back</h1>
          <p>Log in to your All_Chat account</p>
        </div>
        <div class="card-elevated">
          <div id="authError" class="form-error mb-2" style="display:none"></div>
          <div class="form-group">
            <label for="loginId">Username or Email</label>
            <input type="text" id="loginId" placeholder="you@example.com" autocomplete="username" />
          </div>
          <div class="form-group">
            <label for="loginPw">Password</label>
            <input type="password" id="loginPw" placeholder="••••••••••" autocomplete="current-password" />
          </div>
          <button class="btn btn-primary w-full btn-lg" id="loginBtn">Log In</button>
          <div style="text-align:right; margin-top:0.75rem;">
            <a href="/forgot-password" data-route="/forgot-password" style="font-size:0.85rem; color:var(--text-muted)">
              Forgot password?
            </a>
          </div>
        </div>
        <div class="auth-switch">
          Don't have an account? <a href="/register" data-route="/register">Sign up</a>
        </div>
      </div>
    `;
  }

  function renderRegisterForm() {
    return `
      <div class="auth-container">
        <div class="auth-header">
          <h1>Create account</h1>
          <p>Join the conversation on All_Chat</p>
        </div>
        <div class="card-elevated">
          <div id="authError" class="form-error mb-2" style="display:none"></div>
          <div class="form-group">
            <label for="regUser">Username</label>
            <input type="text" id="regUser" placeholder="your_handle" maxlength="32" autocomplete="username" />
            <span class="form-hint">3–32 chars, letters/numbers/underscores only</span>
          </div>
          <div class="form-group">
            <label for="regEmail">Email</label>
            <input type="email" id="regEmail" placeholder="you@example.com" autocomplete="email" />
          </div>
          <div class="form-group">
            <label for="regPw">Password</label>
            <input type="password" id="regPw" placeholder="min 10 chars" autocomplete="new-password" />
            <span class="form-hint">10+ chars, uppercase, lowercase, digit, special char</span>
          </div>
          <div class="form-group">
            <label for="regPwConfirm">Confirm Password</label>
            <input type="password" id="regPwConfirm" placeholder="••••••••••" autocomplete="new-password" />
          </div>
          <button class="btn btn-primary w-full btn-lg" id="registerBtn">Create Account</button>
        </div>
        <div class="auth-switch">
          Already have an account? <a href="/login" data-route="/login">Log in</a>
        </div>
      </div>
    `;
  }

  function renderForgotForm() {
    return `
      <div class="auth-container">
        <div class="auth-header">
          <h1>Reset password</h1>
          <p>We'll send a reset link to your email</p>
        </div>
        <div class="card-elevated">
          <div id="authMsg" class="mb-2" style="display:none"></div>
          <div class="form-group">
            <label for="forgotEmail">Email Address</label>
            <input type="email" id="forgotEmail" placeholder="you@example.com" />
          </div>
          <button class="btn btn-primary w-full" id="forgotBtn">Send Reset Link</button>
        </div>
        <div class="auth-switch"><a href="/login" data-route="/login">Back to login</a></div>
      </div>
    `;
  }

  function bindLoginForm() {
    const btn   = document.getElementById('loginBtn');
    const idEl  = document.getElementById('loginId');
    const pwEl  = document.getElementById('loginPw');
    const errEl = document.getElementById('authError');
    if (!btn) return;

    const submit = async () => {
      errEl.style.display = 'none';
      btn.disabled = true;
      btn.textContent = 'Logging in…';
      try {
        await login(idEl.value.trim(), pwEl.value);
        Router.navigate('/');
      } catch (e) {
        errEl.textContent = e.detail || e.message;
        errEl.style.display = 'block';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Log In';
      }
    };
    btn.addEventListener('click', submit);
    [idEl, pwEl].forEach(el => el.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); }));
  }

  function bindRegisterForm() {
    const btn    = document.getElementById('registerBtn');
    const errEl  = document.getElementById('authError');
    if (!btn) return;

    btn.addEventListener('click', async () => {
      errEl.style.display = 'none';
      const username = document.getElementById('regUser').value.trim();
      const email    = document.getElementById('regEmail').value.trim();
      const pw       = document.getElementById('regPw').value;
      const pwc      = document.getElementById('regPwConfirm').value;
      if (pw !== pwc) {
        errEl.textContent = 'Passwords do not match.';
        errEl.style.display = 'block';
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Creating account…';
      try {
        await register(username, email, pw);
        UI.toast('Account created! Check your email to verify.', 'success');
        Router.navigate('/login');
      } catch (e) {
        errEl.textContent = e.detail || e.message;
        errEl.style.display = 'block';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Create Account';
      }
    });
  }

  function bindForgotForm() {
    const btn = document.getElementById('forgotBtn');
    const msg = document.getElementById('authMsg');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await forgotPassword(document.getElementById('forgotEmail').value.trim());
        msg.textContent = res.message;
        msg.style.color = 'var(--success)';
        msg.style.display = 'block';
      } catch (e) {
        msg.textContent = e.detail || e.message;
        msg.style.color = 'var(--danger)';
        msg.style.display = 'block';
      } finally {
        btn.disabled = false;
      }
    });
  }

  return {
    loadUser, getUser, isLoggedIn, setUser, login, register, logout,
    forgotPassword, resetPassword, verifyEmail,
    renderLoginForm, renderRegisterForm, renderForgotForm,
    bindLoginForm, bindRegisterForm, bindForgotForm,
  };
})();

// Handle logout events globally
window.addEventListener('auth:logout', () => {
  UI?.updateNavAuth?.();
  Router?.navigate?.('/');
});
