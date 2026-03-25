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

    // Handle 2FA required
    if (data.requires_2fa) {
      return { requires_2fa: true, temp_token: data.temp_token };
    }

    API.setTokens(data.access_token, data.refresh_token);
    await loadUser();
    window.dispatchEvent(new CustomEvent('auth:login', { detail: _user }));
    return _user;
  }

  async function loginWith2FA(temp_token, code) {
    const data = await API.post('/2fa/login', { temp_token, code });
    API.setTokens(data.access_token, data.refresh_token);
    await loadUser();
    window.dispatchEvent(new CustomEvent('auth:login', { detail: _user }));
    return _user;
  }

  async function register(username, email, password) {
    return API.post('/auth/register', { username, email, password });
  }

  async function logout() {
    // Revoke refresh token server-side before clearing locally
    await API.logoutFromServer();
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
        const result = await login(idEl.value.trim(), pwEl.value);
        if (result && result.requires_2fa) {
          // Show 2FA prompt
          _show2FAPrompt(result.temp_token, errEl);
          return;
        }
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

  function _show2FAPrompt(temp_token, errEl) {
    const container = document.querySelector('.auth-container .card-elevated');
    if (!container) return;
    container.innerHTML = `
      <div style="text-align:center;margin-bottom:1rem;">
        <div style="font-size:2rem;margin-bottom:0.5rem;">🔐</div>
        <div style="font-weight:700;font-size:1rem;">Two-Factor Authentication</div>
        <div style="color:var(--text-muted);font-size:0.875rem;margin-top:0.25rem;">
          Enter the 6-digit code from your authenticator app
        </div>
      </div>
      <div id="totpError" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <input type="text" id="totpCode" placeholder="000000" maxlength="10"
          autocomplete="one-time-code" inputmode="numeric"
          style="text-align:center;font-size:1.5rem;letter-spacing:0.3em;font-family:'JetBrains Mono',monospace;" />
        <span class="form-hint" style="text-align:center;display:block;">
          Or enter a backup code (10 characters)
        </span>
      </div>
      <button class="btn btn-primary w-full btn-lg" id="totpSubmitBtn">Verify</button>
    `;

    const totpInput = document.getElementById('totpCode');
    const totpBtn   = document.getElementById('totpSubmitBtn');
    const totpErr   = document.getElementById('totpError');
    totpInput?.focus();

    const verifyTOTP = async () => {
      const code = totpInput.value.trim();
      if (!code) return;
      totpBtn.disabled = true;
      totpBtn.textContent = 'Verifying…';
      totpErr.style.display = 'none';
      try {
        await loginWith2FA(temp_token, code);
        Router.navigate('/');
      } catch (e) {
        totpErr.textContent = e.detail || 'Invalid code. Try again.';
        totpErr.style.display = 'block';
        totpInput.value = '';
        totpInput.focus();
      } finally {
        totpBtn.disabled = false;
        totpBtn.textContent = 'Verify';
      }
    };

    totpBtn?.addEventListener('click', verifyTOTP);
    totpInput?.addEventListener('keydown', e => { if (e.key === 'Enter') verifyTOTP(); });
  }

  // ── 2FA Settings ──────────────────────────────────────────────────────────

  function render2FASection(user) {
    const enabled = user?.totp_enabled;
    return `
      <div class="card" style="margin-top:1.5rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
          <div>
            <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;">
              Two-Factor Authentication
            </div>
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.2rem;">
              ${enabled
                ? '🔐 Enabled — your account is protected'
                : '⚠ Disabled — your account uses password only'}
            </div>
          </div>
          <span class="role-badge ${enabled ? 'role-lead' : 'role-admin'}" style="font-size:0.75rem;">
            ${enabled ? 'ON' : 'OFF'}
          </span>
        </div>
        ${enabled
          ? `<div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
               <button class="btn btn-ghost btn-sm" id="regenBackupBtn">↺ New Backup Codes</button>
               <button class="btn btn-danger btn-sm" id="disable2FABtn">Disable 2FA</button>
             </div>`
          : `<button class="btn btn-primary btn-sm" id="enable2FABtn">Enable 2FA</button>`
        }
      </div>`;
  }

  async function bind2FASection() {
    document.getElementById('enable2FABtn')?.addEventListener('click', _showSetupModal);
    document.getElementById('disable2FABtn')?.addEventListener('click', _showDisableModal);
    document.getElementById('regenBackupBtn')?.addEventListener('click', _showRegenModal);
  }

  async function _showSetupModal() {
    UI.openModal(`
      <h3 style="margin-bottom:0.5rem;">Set Up Two-Factor Authentication</h3>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1rem;">
        Scan this QR code with your authenticator app (Google Authenticator, Aegis, Bitwarden, etc.)
        then enter the 6-digit code to confirm.
      </p>
      <div id="setupBody" style="text-align:center;">
        <div class="spinner" style="margin:2rem auto;"></div>
      </div>`);

    try {
      const data = await API.post('/2fa/setup');
      document.getElementById('setupBody').innerHTML = `
        <img src="${data.qr_code}" alt="QR Code" style="width:200px;height:200px;border-radius:8px;border:2px solid var(--border);" />
        <div style="margin:0.75rem 0;font-size:0.8rem;color:var(--text-muted);">
          Can't scan? Enter manually: <code style="font-family:'JetBrains Mono',monospace;font-size:0.85rem;">${UI.escapeHtml(data.secret)}</code>
        </div>
        <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;padding:0.75rem;margin-bottom:1rem;text-align:left;">
          <div style="font-size:0.78rem;font-weight:700;color:var(--warning);margin-bottom:0.5rem;">
            ⚠ Save your backup codes — shown only once
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;line-height:1.8;">
            ${data.backup_codes.map(c => UI.escapeHtml(c)).join('<br>')}
          </div>
        </div>
        <div class="form-group" style="text-align:left;">
          <label>Verification Code</label>
          <input type="text" id="setupTOTPCode" placeholder="000000" maxlength="6"
            inputmode="numeric" autocomplete="one-time-code"
            style="text-align:center;font-size:1.2rem;letter-spacing:0.2em;font-family:'JetBrains Mono',monospace;" />
        </div>
        <div id="setupErr" class="form-error" style="display:none;margin-bottom:0.5rem;"></div>
        <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
          <button class="btn btn-ghost" data-action="close-modal">Cancel</button>
          <button class="btn btn-primary" id="confirmSetupBtn">Confirm & Enable</button>
        </div>`;

      document.getElementById('setupTOTPCode')?.focus();
      document.getElementById('confirmSetupBtn')?.addEventListener('click', async () => {
        const code = document.getElementById('setupTOTPCode').value.trim();
        const err  = document.getElementById('setupErr');
        const btn  = document.getElementById('confirmSetupBtn');
        err.style.display = 'none';
        btn.disabled = true; btn.textContent = 'Verifying…';
        try {
          await API.post('/2fa/verify-setup', { code });
          UI.closeModal();
          UI.toast('Two-factor authentication enabled!', 'success');
          Router.navigate('/settings');
        } catch (e) {
          err.textContent = e.detail || 'Invalid code.';
          err.style.display = 'block';
          btn.disabled = false; btn.textContent = 'Confirm & Enable';
        }
      });
    } catch (e) {
      document.getElementById('setupBody').innerHTML =
        `<p style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  }

  function _showDisableModal() {
    UI.openModal(`
      <h3 style="margin-bottom:0.5rem;">Disable Two-Factor Authentication</h3>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1rem;">
        This will remove 2FA from your account. Enter your password and a 2FA code to confirm.
      </p>
      <div id="disableErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>Password</label>
        <input type="password" id="disablePw" autocomplete="current-password" />
      </div>
      <div class="form-group">
        <label>2FA Code</label>
        <input type="text" id="disableCode" placeholder="000000" maxlength="6"
          inputmode="numeric" style="font-family:'JetBrains Mono',monospace;letter-spacing:0.2em;" />
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" data-action="close-modal">Cancel</button>
        <button class="btn btn-danger" id="confirmDisableBtn">Disable 2FA</button>
      </div>`);

    document.getElementById('confirmDisableBtn')?.addEventListener('click', async () => {
      const err = document.getElementById('disableErr');
      const btn = document.getElementById('confirmDisableBtn');
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Disabling…';
      try {
        await API.post('/2fa/disable', {
          password: document.getElementById('disablePw').value,
          code:     document.getElementById('disableCode').value.trim(),
        });
        UI.closeModal();
        UI.toast('Two-factor authentication disabled.', 'info');
        Router.navigate('/settings');
      } catch (e) {
        err.textContent = e.detail || e.message;
        err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Disable 2FA';
      }
    });
  }

  function _showRegenModal() {
    UI.openModal(`
      <h3 style="margin-bottom:0.5rem;">Regenerate Backup Codes</h3>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1rem;">
        Your old backup codes will be invalidated. Enter a 2FA code to confirm.
      </p>
      <div id="regenErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>2FA Code</label>
        <input type="text" id="regenCode" placeholder="000000" maxlength="6"
          inputmode="numeric" style="font-family:'JetBrains Mono',monospace;letter-spacing:0.2em;" />
      </div>
      <div id="regenResult" style="display:none;margin-bottom:1rem;"></div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" data-action="close-modal">Close</button>
        <button class="btn btn-primary" id="confirmRegenBtn">Generate New Codes</button>
      </div>`);

    document.getElementById('confirmRegenBtn')?.addEventListener('click', async () => {
      const err = document.getElementById('regenErr');
      const btn = document.getElementById('confirmRegenBtn');
      const res = document.getElementById('regenResult');
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Generating…';
      try {
        const data = await API.post('/2fa/regenerate-backup-codes', {
          code: document.getElementById('regenCode').value.trim(),
        });
        res.innerHTML = `
          <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;padding:0.75rem;">
            <div style="font-size:0.78rem;font-weight:700;color:var(--warning);margin-bottom:0.5rem;">
              ⚠ New backup codes — save these now
            </div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;line-height:1.8;">
              ${data.backup_codes.map(c => UI.escapeHtml(c)).join('<br>')}
            </div>
          </div>`;
        res.style.display = 'block';
        btn.style.display = 'none';
        document.getElementById('regenCode').style.display = 'none';
      } catch (e) {
        err.textContent = e.detail || e.message;
        err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Generate New Codes';
      }
    });
  }

  return {
    loadUser, getUser, isLoggedIn, setUser,
    login, loginWith2FA, register, logout,
    forgotPassword, resetPassword, verifyEmail,
    renderLoginForm, renderRegisterForm, renderForgotForm,
    bindLoginForm, bindRegisterForm, bindForgotForm,
    render2FASection, bind2FASection,
  };
})();

// Handle logout events globally
window.addEventListener('auth:logout', () => {
  UI?.updateNavAuth?.();
  Router?.navigate?.('/');
});
