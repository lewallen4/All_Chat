/**
 * All_Chat — Client-Side Router
 * Hash-free SPA routing using the History API.
 * Intercepts data-route links and browser back/forward.
 */

const Router = (() => {
  const routes = {};
  let _current = null;

  function define(path, handler) {
    routes[path] = handler;
  }

  function navigate(path, replace = false) {
    if (replace) {
      window.history.replaceState({}, '', path);
    } else {
      window.history.pushState({}, '', path);
    }
    dispatch(path);
  }

  async function dispatch(fullPath) {
    // Stop message polling if leaving messages
    if (_current !== '/messages') {
      Messages?.stopPolling?.();
    }

    // Reset admin padding override when leaving admin
    const adminMain = document.getElementById('mainContent');
    if (adminMain && _current === '/admin') {
      adminMain.style.padding = '';
    }

    const [path, queryStr] = fullPath.split('?');
    const params = new URLSearchParams(queryStr || '');

    _current = path;
    UI.setActiveSidebarLink(path);

    const main = document.getElementById('mainContent');
    if (!main) return;

    // Match exact routes first
    if (routes[path]) {
      await routes[path](params);
      return;
    }

    // Dynamic routes
    if (path.startsWith('/c/')) {
      const slug = decodeURIComponent(path.slice(3));
      if (slug) {
        await Channels.renderChannelPage(slug);
        return;
      }
    }

    if (path.startsWith('/u/')) {
      const username = decodeURIComponent(path.slice(3));
      if (username) {
        await Profile.renderUserProfile(username);
        return;
      }
    }

    // 404
    main.innerHTML = `
      <div class="empty-state" style="padding:6rem 2rem;">
        <div class="empty-state-icon" style="font-size:4rem;">◻</div>
        <h3>Page not found</h3>
        <p><a href="/" data-route="/">Go to feed</a></p>
      </div>`;
  }

  function init() {
    // Intercept all data-route link clicks (event delegation)
    document.addEventListener('click', e => {
      const link = e.target.closest('[data-route]');
      if (!link) return;
      e.preventDefault();
      const route = link.getAttribute('data-route');
      if (route) navigate(route);
    });

    // Browser back/forward
    window.addEventListener('popstate', () => {
      dispatch(window.location.pathname + window.location.search);
    });

    // Nav search form
    document.getElementById('searchForm')?.addEventListener('submit', e => {
      e.preventDefault();
      const q = document.getElementById('searchInput')?.value.trim();
      if (q) navigate(`/search?q=${encodeURIComponent(q)}`);
    });
  }

  function current() { return _current; }

  return { define, navigate, dispatch, init, current };
})();
