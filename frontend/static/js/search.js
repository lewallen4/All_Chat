/**
 * All_Chat — Search Module
 * Full-text search results view for posts and users.
 */

const Search = (() => {
  let _query    = '';
  let _debounce = null;

  function renderView(initialQuery = '') {
    _query = initialQuery;
    return `
      <div style="max-width:720px;margin:0 auto;">
        <div style="margin-bottom:1.5rem;">
          <div class="nav-search" style="max-width:100%;">
            <span class="search-icon">⌕</span>
            <input type="search" id="searchPageInput"
              value="${UI.escapeAttr(initialQuery)}"
              placeholder="Search posts and people…"
              maxlength="100"
              autocomplete="off"
              style="font-size:1rem;padding:0.7rem 1rem 0.7rem 2.5rem;border-radius:12px;" />
          </div>
        </div>
        <div id="searchResults">
          ${initialQuery ? '' : renderEmptyPrompt()}
        </div>
      </div>
    `;
  }

  function bindView(initialQuery = '') {
    const input = document.getElementById('searchPageInput');
    if (!input) return;

    input.addEventListener('input', () => {
      clearTimeout(_debounce);
      _debounce = setTimeout(() => runSearch(input.value.trim()), 350);
    });

    input.focus();
    if (initialQuery) runSearch(initialQuery);
  }

  function renderEmptyPrompt() {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">⌕</div>
        <h3>Search All_Chat</h3>
        <p>Find posts, people, and conversations</p>
      </div>`;
  }

  async function runSearch(query) {
    _query = query;
    const container = document.getElementById('searchResults');
    if (!container) return;

    if (!query || query.length < 2) {
      container.innerHTML = renderEmptyPrompt();
      return;
    }

    container.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';

    try {
      const res = await API.get(`/search?q=${encodeURIComponent(query)}&page=1`);
      container.innerHTML = '';

      // ── Users ──────────────────────────────────────────────────
      if (res.users.length > 0) {
        const section = document.createElement('div');
        section.innerHTML = `
          <div class="search-section-title">People · ${res.total_users}</div>
          <div id="userResults"></div>
        `;
        container.appendChild(section);

        const userList = section.querySelector('#userResults');
        res.users.forEach(user => {
          const el = document.createElement('a');
          el.className = 'user-card';
          el.href = `/u/${encodeURIComponent(user.username)}`;
          el.setAttribute('data-route', `/u/${user.username}`);
          const initial = (user.display_name || user.username)[0].toUpperCase();
          el.innerHTML = `
            ${UI.avatarEl(user, 40)}
            <div>
              <div class="user-card-name">${UI.escapeHtml(user.username)}</div>
              ${user.display_name
                ? `<div class="user-card-sub">${UI.escapeHtml(user.display_name)}</div>` : ''}
              <div class="user-card-sub">Joined ${new Date(user.created_at).toLocaleDateString('en-US',{month:'short',year:'numeric'})}</div>
            </div>
          `;
          userList.appendChild(el);
        });
      }

      // ── Posts ──────────────────────────────────────────────────
      if (res.posts.length > 0) {
        const section = document.createElement('div');
        section.innerHTML = `<div class="search-section-title">Posts · ${res.total_posts}</div>`;
        const feedList = document.createElement('div');
        feedList.className = 'feed-list';

        res.posts.forEach(post => {
          feedList.appendChild(Feed.createPostCard(post));
        });

        section.appendChild(feedList);
        container.appendChild(section);

        // Wire up vote buttons
        feedList.querySelectorAll('.vote-btn').forEach(btn => {
          btn.addEventListener('click', () => Feed.castVote(btn.dataset.postId, parseInt(btn.dataset.value)));
        });

      } else if (res.users.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">◻</div>
            <h3>No results for "${UI.escapeHtml(query)}"</h3>
            <p>Try different keywords or check your spelling</p>
          </div>`;
      } else if (res.posts.length === 0) {
        const noPost = document.createElement('div');
        noPost.innerHTML = `
          <div class="search-section-title">Posts · 0</div>
          <p style="color:var(--text-muted);font-size:0.875rem;padding:0.5rem 0">No posts matched your query.</p>`;
        container.appendChild(noPost);
      }

    } catch (e) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">⚠</div>
          <h3>Search failed</h3>
          <p>${UI.escapeHtml(e.detail || e.message)}</p>
        </div>`;
    }
  }

  // Called from the nav search bar
  function navigateSearch(query) {
    Router.navigate(`/search?q=${encodeURIComponent(query)}`);
  }

  return { renderView, bindView, navigateSearch, runSearch };
})();
