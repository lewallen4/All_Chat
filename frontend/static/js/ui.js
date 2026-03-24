/**
 * All_Chat — UI Utilities
 * Toast notifications, modal, nav auth area, theme, time formatting.
 */

const UI = (() => {

  // ── Toasts ─────────────────────────────────────────────────────

  function toast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    el.innerHTML = `<span>${icons[type] || ''}</span> ${escapeHtml(message)}`;
    container.appendChild(el);

    setTimeout(() => {
      el.classList.add('removing');
      el.addEventListener('animationend', () => el.remove());
    }, duration);
  }

  // ── Modal ──────────────────────────────────────────────────────

  function openModal(contentHtml) {
    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');
    if (!overlay || !content) return;
    content.innerHTML = contentHtml;
    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    const overlay = document.getElementById('modalOverlay');
    if (!overlay) return;
    overlay.classList.add('hidden');
    document.body.style.overflow = '';
  }

  function initModal() {
    document.getElementById('modalClose')?.addEventListener('click', closeModal);
    document.getElementById('modalOverlay')?.addEventListener('click', e => {
      if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeModal();
    });
  }

  // ── Nav Auth Area ──────────────────────────────────────────────

  function updateNavAuth() {
    const area = document.getElementById('navAuthArea');
    if (!area) return;

    const user = Auth.getUser();

    if (user) {
      const initial = (user.display_name || user.username || '?')[0].toUpperCase();
      const avatarEl = user.avatar_path
        ? `<img class="nav-avatar-sm" src="${escapeAttr(user.avatar_path)}" alt="" />`
        : `<div class="nav-avatar-placeholder-sm">${escapeHtml(initial)}</div>`;

      area.innerHTML = `
        <div class="nav-user-menu">
          <a href="/profile" data-route="/profile" class="flex items-center gap-1" style="text-decoration:none">
            ${avatarEl}
            <span class="nav-username">${escapeHtml(user.username)}</span>
          </a>
          <button class="btn btn-ghost btn-sm" id="logoutBtn">Log out</button>
        </div>
      `;
      document.getElementById('logoutBtn')?.addEventListener('click', async () => {
        await Auth.logout();
        updateNavAuth();
        updateSidebarAuth();
      });
    } else {
      area.innerHTML = `
        <a href="/login"    data-route="/login"    class="btn btn-ghost btn-sm">Log in</a>
        <a href="/register" data-route="/register" class="btn btn-primary btn-sm">Sign up</a>
      `;
    }

    updateSidebarAuth();
  }

  function updateSidebarAuth() {
    const isLoggedIn = Auth.isLoggedIn();
    document.querySelectorAll('.auth-only').forEach(el => {
      el.classList.toggle('hidden', !isLoggedIn);
    });
  }

  // ── Active Sidebar Link ────────────────────────────────────────

  function setActiveSidebarLink(path) {
    document.querySelectorAll('.snav-item').forEach(link => {
      const route = link.getAttribute('data-route');
      link.classList.toggle('active', route === path);
    });
  }

  // ── Theme ──────────────────────────────────────────────────────

  function initTheme() {
    const stored = localStorage.getItem('ac_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', stored);
    updateThemeIcon(stored);

    document.getElementById('themeToggle')?.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next    = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('ac_theme', next);
      updateThemeIcon(next);
    });
  }

  function updateThemeIcon(theme) {
    const icon = document.querySelector('.theme-icon');
    if (icon) icon.textContent = theme === 'dark' ? '☀' : '◐';
  }

  // ── Time Formatting ────────────────────────────────────────────

  function relativeTime(dateString) {
    const now  = Date.now();
    const then = new Date(dateString).getTime();
    const diff = Math.floor((now - then) / 1000);

    if (diff < 60)     return `${diff}s ago`;
    if (diff < 3600)   return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)  return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;

    return new Date(dateString).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // ── HTML escaping ──────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;')
      .replace(/'/g,  '&#039;');
  }

  function escapeAttr(str) { return escapeHtml(str); }

  // ── Markdown rendering (via marked if available, else plain) ───

  function renderMarkdown(md) {
    if (!md) return '';
    if (typeof marked !== 'undefined') {
      return marked.parse(escapeHtml(md));
    }
    // Minimal fallback: escape and preserve line breaks
    return escapeHtml(md).replace(/\n/g, '<br>');
  }

  // ── Avatar helper ──────────────────────────────────────────────

  function avatarEl(user, size = 36) {
    const initial = (user.display_name || user.username || '?')[0].toUpperCase();
    if (user.avatar_path) {
      return `<img src="${escapeAttr(user.avatar_path)}" alt=""
               style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;border:2px solid var(--border);" />`;
    }
    return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:var(--accent-soft);
               border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;
               font-family:'Syne',sans-serif;font-weight:800;font-size:${Math.floor(size*0.4)}px;
               color:var(--accent);flex-shrink:0;">${escapeHtml(initial)}</div>`;
  }

  return {
    toast, openModal, closeModal, initModal,
    updateNavAuth, updateSidebarAuth, setActiveSidebarLink,
    initTheme, relativeTime,
    escapeHtml, escapeAttr, renderMarkdown, avatarEl,
  };
})();
