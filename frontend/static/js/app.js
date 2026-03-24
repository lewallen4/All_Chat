/**
 * All_Chat — App Bootstrap
 * Registers routes, initializes auth state, starts the router.
 */

(async () => {
  // ── Init UI primitives ─────────────────────────────────────────
  UI.initTheme();
  UI.initModal();

  // ── Load current user (if token exists) ───────────────────────
  await Auth.loadUser();
  UI.updateNavAuth();

  // Register public key for E2E if logged in
  if (Auth.isLoggedIn()) {
    CryptoE2E.registerPublicKey().catch(() => {});
    pollUnreadCount();
    setInterval(pollUnreadCount, 30000);
    Social.renderNotifBell();
    updateAdminLink();
  }

  function updateAdminLink() {
    const isAdmin = !!Auth.getUser()?.is_admin;
    document.querySelectorAll('.admin-only').forEach(el => {
      el.classList.toggle('hidden', !isAdmin);
    });
  }

  // ── Auth event listeners ───────────────────────────────────────
  window.addEventListener('auth:login', () => {
    UI.updateNavAuth();
    updateAdminLink();
    CryptoE2E.registerPublicKey().catch(() => {});
    pollUnreadCount();
    Social.renderNotifBell();
  });

  window.addEventListener('auth:logout', () => {
    UI.updateNavAuth();
  });

  // ── Define Routes ──────────────────────────────────────────────

  Router.define('/', async () => {
    const main = document.getElementById('mainContent');
    main.innerHTML = Feed.renderView();
    Feed.bindView();
  });

  Router.define('/login', async () => {
    if (Auth.isLoggedIn()) { Router.navigate('/'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = Auth.renderLoginForm();
    Auth.bindLoginForm();
  });

  Router.define('/register', async () => {
    if (Auth.isLoggedIn()) { Router.navigate('/'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = Auth.renderRegisterForm();
    Auth.bindRegisterForm();
  });

  Router.define('/forgot-password', async () => {
    const main = document.getElementById('mainContent');
    main.innerHTML = Auth.renderForgotForm();
    Auth.bindForgotForm();
  });

  Router.define('/reset-password', async (params) => {
    const token = params.get('token');
    const main  = document.getElementById('mainContent');
    if (!token) { Router.navigate('/'); return; }
    main.innerHTML = `
      <div class="auth-container">
        <div class="auth-header"><h1>Set new password</h1></div>
        <div class="card-elevated">
          <div id="resetMsg" class="mb-2" style="display:none"></div>
          <div class="form-group">
            <label for="resetPw">New Password</label>
            <input type="password" id="resetPw" placeholder="min 10 chars" />
            <span class="form-hint">10+ chars, uppercase, lowercase, digit, special char</span>
          </div>
          <div class="form-group">
            <label for="resetPwConfirm">Confirm Password</label>
            <input type="password" id="resetPwConfirm" placeholder="Confirm new password" />
          </div>
          <button class="btn btn-primary w-full" id="resetBtn">Reset Password</button>
        </div>
      </div>`;
    document.getElementById('resetBtn')?.addEventListener('click', async () => {
      const msg = document.getElementById('resetMsg');
      const pw  = document.getElementById('resetPw').value;
      const pwc = document.getElementById('resetPwConfirm').value;
      if (pw !== pwc) {
        msg.textContent = 'Passwords do not match.'; msg.style.color = 'var(--danger)';
        msg.style.display = 'block'; return;
      }
      try {
        const res = await Auth.resetPassword(token, pw);
        msg.textContent = res.message + ' Redirecting to login…';
        msg.style.color = 'var(--success)'; msg.style.display = 'block';
        setTimeout(() => Router.navigate('/login'), 2000);
      } catch (e) {
        msg.textContent = e.detail || e.message;
        msg.style.color = 'var(--danger)'; msg.style.display = 'block';
      }
    });
  });

  Router.define('/verify-email', async (params) => {
    const token = params.get('token');
    const main  = document.getElementById('mainContent');
    main.innerHTML = `<div class="view-loading"><div class="spinner"></div></div>`;
    if (!token) { Router.navigate('/'); return; }
    try {
      const res = await Auth.verifyEmail(token);
      main.innerHTML = `
        <div class="auth-container">
          <div class="card-elevated" style="text-align:center;padding:2.5rem">
            <div style="font-size:3rem;margin-bottom:1rem">✓</div>
            <h2 style="color:var(--success);margin-bottom:0.75rem">Email Verified!</h2>
            <p style="color:var(--text-secondary);margin-bottom:1.5rem">${UI.escapeHtml(res.message)}</p>
            <a href="/login" data-route="/login" class="btn btn-primary">Log In Now</a>
          </div>
        </div>`;
    } catch (e) {
      main.innerHTML = `
        <div class="auth-container">
          <div class="card-elevated" style="text-align:center;padding:2.5rem">
            <div style="font-size:3rem;margin-bottom:1rem">✕</div>
            <h2 style="color:var(--danger);margin-bottom:0.75rem">Verification Failed</h2>
            <p style="color:var(--text-secondary)">${UI.escapeHtml(e.detail || 'Invalid or expired link.')}</p>
            <a href="/login" data-route="/login" class="btn btn-ghost mt-2">Back to login</a>
          </div>
        </div>`;
    }
  });

  Router.define('/submit', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = Post.renderView();
    Post.bindView();
  });

  Router.define('/messages', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = Messages.renderView();
    await Messages.bindView();
  });

  Router.define('/profile', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    await Profile.renderOwnProfile();
  });

  Router.define('/admin', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    if (!Auth.getUser()?.is_admin) {
      UI.toast('Admin access required.', 'error');
      Router.navigate('/');
      return;
    }
    const main = document.getElementById('mainContent');
    // Admin uses its own full-width layout — hide normal padding
    main.style.padding = '0';
    main.innerHTML = Admin.renderView();
    Admin.bindView();
  });

  Router.define('/channels', async () => {
    const main = document.getElementById('mainContent');
    main.innerHTML = Channels.renderDirectoryView();
    await Channels.bindDirectoryView();
  });

  Router.define('/c/', async (params) => {
    Router.navigate('/channels');
  });

    Router.define('/following', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = `<div style="max-width:720px;margin:0 auto;">
      <h2 style="margin-bottom:1.25rem;font-family:'Syne',sans-serif;">Following Feed</h2>
      <div class="feed-list" id="followingFeedList">
        <div class="view-loading"><div class="spinner"></div></div>
      </div>
    </div>`;
    try {
      const posts = await API.get('/social/following/feed?page=1');
      const list  = document.getElementById('followingFeedList');
      if (!list) return;
      if (posts.length === 0) {
        list.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">✦</div>
          <h3>Nothing here yet</h3>
          <p>Follow some users to see their posts here.</p>
        </div>`;
      } else {
        posts.forEach(p => {
          const card = Feed.createPostCard(p);
          list.appendChild(card);
        });
      }
    } catch (e) {
      document.getElementById('followingFeedList').innerHTML =
        `<p style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  });

  Router.define('/bookmarks', async () => {
    if (!Auth.isLoggedIn()) { Router.navigate('/login'); return; }
    const main = document.getElementById('mainContent');
    main.innerHTML = `<div style="max-width:720px;margin:0 auto;">
      <h2 style="margin-bottom:1.25rem;font-family:'Syne',sans-serif;">Bookmarks</h2>
      <div class="feed-list" id="bookmarkFeedList">
        <div class="view-loading"><div class="spinner"></div></div>
      </div>
    </div>`;
    try {
      const posts = await API.get('/social/bookmarks?page=1');
      const list  = document.getElementById('bookmarkFeedList');
      if (!list) return;
      if (posts.length === 0) {
        list.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">⊹</div>
          <h3>No bookmarks yet</h3>
          <p>Tap the bookmark icon on any post to save it here.</p>
        </div>`;
      } else {
        posts.forEach(p => list.appendChild(Feed.createPostCard(p)));
      }
    } catch (e) {
      document.getElementById('bookmarkFeedList').innerHTML =
        `<p style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  });

  Router.define('/search', async (params) => {
    const q    = params.get('q') || '';
    const main = document.getElementById('mainContent');
    main.innerHTML = Search.renderView(q);
    Search.bindView(q);
    // Sync the nav search input
    const navInput = document.getElementById('searchInput');
    if (navInput) navInput.value = q;
  });

  // ── Init Router ────────────────────────────────────────────────
  Router.init();
  Router.dispatch(window.location.pathname + window.location.search);

  // ── Unread message badge ───────────────────────────────────────
  async function pollUnreadCount() {
    if (!Auth.isLoggedIn()) return;
    try {
      const convs  = await API.get('/messages/conversations');
      const unread = convs.reduce((sum, c) => sum + (c.unread_count || 0), 0);
      const badge  = document.getElementById('msgBadge');
      if (badge) {
        badge.textContent  = unread > 99 ? '99+' : String(unread);
        badge.style.display = unread > 0 ? 'inline-flex' : 'none';
      }
    } catch {}
  }

})();
