/**
 * All_Chat — Admin Dashboard
 * Full client-side admin panel:
 *   Overview (stats + health)
 *   Users (list, search, filter, ban/unban/promote/demote/delete)
 *   Posts (list, search, delete, restore)
 *   Comments (list, search, delete)
 *   Audit Log
 */

const Admin = (() => {

  let _section = 'overview';
  let _state   = {};  // per-section state (page, query, filter)

  // ── Entry point ───────────────────────────────────────────────

  function renderView() {
    return `
      <div class="admin-layout">
        <aside class="admin-sidebar">
          <div class="admin-sidebar-title">Dashboard</div>
          <button class="admin-nav-item active" data-section="overview">
            <span class="nav-icon">◈</span> Overview
          </button>

          <div class="admin-sidebar-title">Moderation</div>
          <button class="admin-nav-item" data-section="users">
            <span class="nav-icon">👥</span> Users
          </button>
          <button class="admin-nav-item" data-section="posts">
            <span class="nav-icon">📋</span> Posts
          </button>
          <button class="admin-nav-item" data-section="comments">
            <span class="nav-icon">💬</span> Comments
          </button>

          <div class="admin-sidebar-title">System</div>
          <button class="admin-nav-item" data-section="audit">
            <span class="nav-icon">📜</span> Audit Log
          </button>

          <div style="margin-top:auto;padding:0.75rem 0.85rem;border-top:1px solid var(--border-subtle);">
            <a href="/" data-route="/" style="font-size:0.8rem;color:var(--text-muted);">
              ← Back to site
            </a>
          </div>
        </aside>
        <div class="admin-main" id="adminMain">
          <div class="view-loading"><div class="spinner"></div></div>
        </div>
      </div>
    `;
  }

  function bindView() {
    document.querySelectorAll('.admin-nav-item[data-section]').forEach(btn => {
      btn.addEventListener('click', () => switchSection(btn.dataset.section));
    });
    switchSection('overview');
  }

  function switchSection(section) {
    _section = section;
    _state[section] = _state[section] || { page: 1, q: '', filter: 'all', showDeleted: false };
    document.querySelectorAll('.admin-nav-item[data-section]').forEach(b => {
      b.classList.toggle('active', b.dataset.section === section);
    });
    const main = document.getElementById('adminMain');
    if (!main) return;
    main.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';
    const loaders = {
      overview: loadOverview,
      users:    loadUsers,
      posts:    loadPosts,
      comments: loadComments,
      audit:    loadAudit,
    };
    (loaders[section] || loadOverview)();
  }

  // ── Overview ──────────────────────────────────────────────────

  async function loadOverview() {
    const main = document.getElementById('adminMain');
    try {
      const [stats, health] = await Promise.all([
        API.get('/admin/stats'),
        API.get('/admin/health'),
      ]);

      const dbOk    = health.database === 'ok';
      const redisOk = health.redis    === 'ok';

      main.innerHTML = `
        <div class="admin-page-title"><span class="title-icon">◈</span> Overview</div>

        <div class="health-grid">
          ${healthCard('Database',   dbOk ? 'ok' : 'error',   health.database,   dbOk ? 'ok' : 'error')}
          ${healthCard('Redis',      redisOk ? 'ok' : 'error', health.redis,      redisOk ? 'ok' : 'error')}
          ${healthCard('Disk Free',  'ok', `${health.disk_free_gb} GB free`,       'ok')}
          ${healthCard('Media',      'ok', `${health.media_size_mb} MB used`,      'ok')}
          ${healthCard('Server',     'ok', health.uptime_info,                     'ok')}
        </div>

        <div class="stats-grid">
          ${statCard('Total Users',   stats.total_users,   `${stats.active_users} active`, 'accent')}
          ${statCard('New Today',     stats.new_users_24h, `${stats.new_users_7d} this week`, 'success')}
          ${statCard('Verified',      stats.verified_users,'email confirmed', '')}
          ${statCard('Total Posts',   stats.total_posts,   `${stats.new_posts_24h} today`, 'gold')}
          ${statCard('Active Posts',  stats.active_posts,  `${stats.total_posts - stats.active_posts} deleted`, '')}
          ${statCard('Votes Cast',    stats.total_votes,   'all time', '')}
          ${statCard('Comments',      stats.total_comments,'all time', '')}
          ${statCard('DMs Sent',      stats.total_messages,'encrypted', 'accent')}
          ${statCard('Follows',       stats.total_follows, '', '')}
          ${statCard('Bookmarks',     stats.total_bookmarks,'', '')}
          ${statCard('Media Size',    stats.media_size_mb + ' MB', stats.db_version, '')}
        </div>
      `;
    } catch (e) {
      main.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">⚠</div>
        <h3>Failed to load stats</h3>
        <p>${UI.escapeHtml(e.detail || e.message)}</p>
      </div>`;
    }
  }

  function statCard(label, value, sub, cls) {
    return `<div class="stat-card ${cls}">
      <div class="stat-label">${UI.escapeHtml(label)}</div>
      <div class="stat-value">${UI.escapeHtml(String(value))}</div>
      ${sub ? `<div class="stat-sub">${UI.escapeHtml(sub)}</div>` : ''}
    </div>`;
  }

  function healthCard(label, status, value, type) {
    const cls = type === 'ok' ? 'health-ok' : type === 'error' ? 'health-error' : 'health-warning';
    return `<div class="health-card">
      <div class="health-indicator ${cls}"></div>
      <div>
        <div class="health-label">${UI.escapeHtml(label)}</div>
        <div class="health-value">${UI.escapeHtml(value)}</div>
      </div>
    </div>`;
  }

  // ── Users ─────────────────────────────────────────────────────

  async function loadUsers() {
    const s    = _state.users;
    const main = document.getElementById('adminMain');
    main.innerHTML = `
      <div class="admin-page-title"><span class="title-icon">👥</span> User Management</div>
      <div class="admin-table-wrap">
        <div class="admin-table-toolbar">
          <div class="admin-search">
            <span class="admin-search-icon">⌕</span>
            <input type="search" id="userSearchInput" placeholder="Search username or email…"
              value="${UI.escapeAttr(s.q)}" autocomplete="off" />
          </div>
          <select class="filter-select" id="userFilterSelect">
            <option value="all"        ${s.filter==='all'?'selected':''}>All users</option>
            <option value="active"     ${s.filter==='active'?'selected':''}>Active</option>
            <option value="banned"     ${s.filter==='banned'?'selected':''}>Banned</option>
            <option value="unverified" ${s.filter==='unverified'?'selected':''}>Unverified</option>
            <option value="admin"      ${s.filter==='admin'?'selected':''}>Admins</option>
          </select>
        </div>
        <div id="usersTableBody"><div class="view-loading" style="padding:2rem"><div class="spinner" style="margin:auto"></div></div></div>
        <div class="admin-pagination" id="usersPagination"></div>
      </div>
    `;

    let debounce;
    document.getElementById('userSearchInput')?.addEventListener('input', e => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        s.q = e.target.value.trim(); s.page = 1; fetchUsers();
      }, 350);
    });
    document.getElementById('userFilterSelect')?.addEventListener('change', e => {
      s.filter = e.target.value; s.page = 1; fetchUsers();
    });

    fetchUsers();
  }

  async function fetchUsers() {
    const s   = _state.users;
    const body = document.getElementById('usersTableBody');
    const pag  = document.getElementById('usersPagination');
    if (!body) return;

    body.innerHTML = '<div class="view-loading" style="padding:1.5rem"><div class="spinner" style="margin:auto"></div></div>';

    try {
      const params = new URLSearchParams({ page: s.page, q: s.q, filter: s.filter });
      const data   = await API.get(`/admin/users?${params}`);

      if (!data.users.length) {
        body.innerHTML = '<div class="admin-empty">No users found.</div>';
        if (pag) pag.innerHTML = '';
        return;
      }

      body.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Email</th>
              <th>Status</th>
              <th>Posts</th>
              <th>Joined</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="usersRows"></tbody>
        </table>`;

      const tbody = document.getElementById('usersRows');
      data.users.forEach(u => {
        const tr = document.createElement('tr');
        const statusPills = [
          u.is_admin      ? '<span class="status-pill pill-admin">admin</span>'       : '',
          !u.is_active    ? '<span class="status-pill pill-banned">banned</span>'     : '<span class="status-pill pill-active">active</span>',
          !u.email_verified ? '<span class="status-pill pill-unverified">unverified</span>' : '',
        ].filter(Boolean).join(' ');

        tr.innerHTML = `
          <td>
            <div style="display:flex;align-items:center;gap:0.6rem;">
              ${u.avatar_path
                ? `<img src="${UI.escapeAttr(u.avatar_path)}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;" />`
                : `<div style="width:28px;height:28px;border-radius:50%;background:var(--accent-soft);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:0.75rem;color:var(--accent);">${UI.escapeHtml((u.username||'?')[0].toUpperCase())}</div>`}
              <div>
                <div style="font-weight:600">${UI.escapeHtml(u.username)}</div>
                ${u.display_name ? `<div style="font-size:0.75rem;color:var(--text-muted)">${UI.escapeHtml(u.display_name)}</div>` : ''}
              </div>
            </div>
          </td>
          <td class="td-mono">${UI.escapeHtml(u.email)}</td>
          <td>${statusPills}</td>
          <td class="td-mono">${u.post_count}</td>
          <td class="td-mono">${new Date(u.created_at).toLocaleDateString()}</td>
          <td>
            <div class="action-group">
              <a href="/u/${UI.escapeAttr(u.username)}" data-route="/u/${UI.escapeAttr(u.username)}"
                class="btn-action accent">View</a>
              ${!u.email_verified
                ? `<button class="btn-action success" data-action="verify" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Verify</button>` : ''}
              ${u.is_active
                ? `<button class="btn-action danger" data-action="ban" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Ban</button>`
                : `<button class="btn-action success" data-action="unban" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Unban</button>`}
              ${!u.is_admin
                ? `<button class="btn-action accent" data-action="promote" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Promote</button>`
                : `<button class="btn-action" data-action="demote" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Demote</button>`}
              <button class="btn-action danger" data-action="delete" data-uid="${u.id}" data-name="${UI.escapeAttr(u.username)}">Delete</button>
            </div>
          </td>`;
        tbody.appendChild(tr);
      });

      // Bind action buttons
      tbody.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', () => handleUserAction(btn.dataset.action, btn.dataset.uid, btn.dataset.name));
      });

      // Pagination
      renderPagination(pag, s.page, data.has_more, data.total, () => { s.page--; fetchUsers(); }, () => { s.page++; fetchUsers(); });

    } catch (e) {
      body.innerHTML = `<div class="admin-empty" style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  async function handleUserAction(action, userId, username) {
    const confirmMsgs = {
      ban:     `Ban @${username}? They won't be able to log in.`,
      delete:  `PERMANENTLY delete @${username} and all their content? This cannot be undone.`,
      promote: `Promote @${username} to admin?`,
      demote:  `Demote @${username} from admin?`,
    };
    if (confirmMsgs[action] && !confirm(confirmMsgs[action])) return;

    const endpoints = {
      ban:     ['/admin/users/' + userId + '/ban',          'POST'],
      unban:   ['/admin/users/' + userId + '/unban',        'POST'],
      promote: ['/admin/users/' + userId + '/promote',      'POST'],
      demote:  ['/admin/users/' + userId + '/demote',       'POST'],
      verify:  ['/admin/users/' + userId + '/verify-email', 'POST'],
      delete:  ['/admin/users/' + userId,                   'DELETE'],
    };

    const [path, method] = endpoints[action] || [];
    if (!path) return;

    try {
      const res = method === 'DELETE' ? await API.delete(path) : await API.post(path, {});
      UI.toast(res.message, 'success');
      fetchUsers();
    } catch (e) {
      UI.toast(e.detail || e.message, 'error');
    }
  }

  // ── Posts ─────────────────────────────────────────────────────

  async function loadPosts() {
    const s    = _state.posts;
    const main = document.getElementById('adminMain');
    main.innerHTML = `
      <div class="admin-page-title"><span class="title-icon">📋</span> Post Moderation</div>
      <div class="admin-table-wrap">
        <div class="admin-table-toolbar">
          <div class="admin-search">
            <span class="admin-search-icon">⌕</span>
            <input type="search" id="postSearchInput" placeholder="Search title or body…"
              value="${UI.escapeAttr(s.q)}" autocomplete="off" />
          </div>
          <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.8rem;color:var(--text-secondary);cursor:pointer;">
            <input type="checkbox" id="showDeletedChk" ${s.showDeleted ? 'checked' : ''} />
            Show deleted
          </label>
        </div>
        <div id="postsTableBody"><div class="view-loading" style="padding:2rem"><div class="spinner" style="margin:auto"></div></div></div>
        <div class="admin-pagination" id="postsPagination"></div>
      </div>
    `;

    let debounce;
    document.getElementById('postSearchInput')?.addEventListener('input', e => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { s.q = e.target.value.trim(); s.page = 1; fetchPosts(); }, 350);
    });
    document.getElementById('showDeletedChk')?.addEventListener('change', e => {
      s.showDeleted = e.target.checked; s.page = 1; fetchPosts();
    });

    fetchPosts();
  }

  async function fetchPosts() {
    const s    = _state.posts;
    const body = document.getElementById('postsTableBody');
    const pag  = document.getElementById('postsPagination');
    if (!body) return;

    body.innerHTML = '<div class="view-loading" style="padding:1.5rem"><div class="spinner" style="margin:auto"></div></div>';

    try {
      const params = new URLSearchParams({ page: s.page, q: s.q, show_deleted: s.showDeleted });
      const data   = await API.get(`/admin/posts?${params}`);

      if (!data.posts.length) {
        body.innerHTML = '<div class="admin-empty">No posts found.</div>';
        if (pag) pag.innerHTML = '';
        return;
      }

      body.innerHTML = `
        <table>
          <thead>
            <tr><th>Author</th><th>Title / Body</th><th>Score</th><th>Status</th><th>Date</th><th>Actions</th></tr>
          </thead>
          <tbody id="postsRows"></tbody>
        </table>`;

      const tbody = document.getElementById('postsRows');
      data.posts.forEach(p => {
        const tr = document.createElement('tr');
        const preview = p.title || (p.body ? p.body.substring(0, 80) + '…' : p.link_url || '[image]');
        tr.innerHTML = `
          <td style="font-weight:600;white-space:nowrap">${UI.escapeHtml(p.author_username)}</td>
          <td class="td-truncate">${UI.escapeHtml(preview)}</td>
          <td class="td-mono">▲${p.upvotes} ▼${p.downvotes}</td>
          <td>${p.is_deleted
            ? '<span class="status-pill pill-deleted">deleted</span>'
            : '<span class="status-pill pill-live">live</span>'}</td>
          <td class="td-mono">${new Date(p.created_at).toLocaleDateString()}</td>
          <td>
            <div class="action-group">
              ${!p.is_deleted
                ? `<button class="btn-action danger" data-action="delete" data-pid="${p.id}">Delete</button>`
                : `<button class="btn-action success" data-action="restore" data-pid="${p.id}">Restore</button>`}
            </div>
          </td>`;
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const pid    = btn.dataset.pid;
          const action = btn.dataset.action;
          if (action === 'delete' && !confirm('Delete this post?')) return;
          try {
            const res = action === 'delete'
              ? await API.delete(`/admin/posts/${pid}`)
              : await API.post(`/admin/posts/${pid}/restore`, {});
            UI.toast(res.message, 'success');
            fetchPosts();
          } catch (e) { UI.toast(e.detail || e.message, 'error'); }
        });
      });

      renderPagination(pag, s.page, data.has_more, data.total, () => { s.page--; fetchPosts(); }, () => { s.page++; fetchPosts(); });

    } catch (e) {
      body.innerHTML = `<div class="admin-empty" style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  // ── Comments ──────────────────────────────────────────────────

  async function loadComments() {
    const s    = _state.comments;
    const main = document.getElementById('adminMain');
    main.innerHTML = `
      <div class="admin-page-title"><span class="title-icon">💬</span> Comment Moderation</div>
      <div class="admin-table-wrap">
        <div class="admin-table-toolbar">
          <div class="admin-search">
            <span class="admin-search-icon">⌕</span>
            <input type="search" id="commentSearchInput" placeholder="Search comment body…"
              value="${UI.escapeAttr(s.q)}" autocomplete="off" />
          </div>
          <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.8rem;color:var(--text-secondary);cursor:pointer;">
            <input type="checkbox" id="showDeletedCmtChk" ${s.showDeleted ? 'checked' : ''} />
            Show deleted
          </label>
        </div>
        <div id="commentsTableBody"><div class="view-loading" style="padding:2rem"><div class="spinner" style="margin:auto"></div></div></div>
        <div class="admin-pagination" id="commentsPagination"></div>
      </div>
    `;

    let debounce;
    document.getElementById('commentSearchInput')?.addEventListener('input', e => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { s.q = e.target.value.trim(); s.page = 1; fetchComments(); }, 350);
    });
    document.getElementById('showDeletedCmtChk')?.addEventListener('change', e => {
      s.showDeleted = e.target.checked; s.page = 1; fetchComments();
    });

    fetchComments();
  }

  async function fetchComments() {
    const s    = _state.comments;
    const body = document.getElementById('commentsTableBody');
    const pag  = document.getElementById('commentsPagination');
    if (!body) return;

    body.innerHTML = '<div class="view-loading" style="padding:1.5rem"><div class="spinner" style="margin:auto"></div></div>';

    try {
      const params = new URLSearchParams({ page: s.page, q: s.q, show_deleted: s.showDeleted });
      const data   = await API.get(`/admin/comments?${params}`);

      if (!data.comments.length) {
        body.innerHTML = '<div class="admin-empty">No comments found.</div>';
        if (pag) pag.innerHTML = '';
        return;
      }

      body.innerHTML = `
        <table>
          <thead>
            <tr><th>Author</th><th>Comment</th><th>Post ID</th><th>Status</th><th>Date</th><th>Actions</th></tr>
          </thead>
          <tbody id="commentsRows"></tbody>
        </table>`;

      const tbody = document.getElementById('commentsRows');
      data.comments.forEach(c => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="font-weight:600;white-space:nowrap">${UI.escapeHtml(c.author_username)}</td>
          <td class="td-truncate">${UI.escapeHtml(c.body)}</td>
          <td class="td-mono">${c.post_id}</td>
          <td>${c.is_deleted
            ? '<span class="status-pill pill-deleted">removed</span>'
            : '<span class="status-pill pill-live">visible</span>'}</td>
          <td class="td-mono">${new Date(c.created_at).toLocaleDateString()}</td>
          <td>
            <div class="action-group">
              ${!c.is_deleted
                ? `<button class="btn-action danger" data-cid="${c.id}">Remove</button>`
                : '<span style="color:var(--text-muted);font-size:0.75rem">removed</span>'}
            </div>
          </td>`;
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('[data-cid]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('Remove this comment?')) return;
          try {
            const res = await API.delete(`/admin/comments/${btn.dataset.cid}`);
            UI.toast(res.message, 'success');
            fetchComments();
          } catch (e) { UI.toast(e.detail || e.message, 'error'); }
        });
      });

      renderPagination(pag, s.page, data.has_more, data.total, () => { s.page--; fetchComments(); }, () => { s.page++; fetchComments(); });

    } catch (e) {
      body.innerHTML = `<div class="admin-empty" style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  // ── Audit Log ─────────────────────────────────────────────────

  async function loadAudit() {
    const s    = _state.audit;
    const main = document.getElementById('adminMain');
    main.innerHTML = `
      <div class="admin-page-title"><span class="title-icon">📜</span> Audit Log</div>
      <div class="admin-table-wrap">
        <div id="auditBody"><div class="view-loading" style="padding:2rem"><div class="spinner" style="margin:auto"></div></div></div>
        <div class="admin-pagination" id="auditPagination"></div>
      </div>
    `;
    fetchAudit();
  }

  async function fetchAudit() {
    const s    = _state.audit;
    const body = document.getElementById('auditBody');
    const pag  = document.getElementById('auditPagination');
    if (!body) return;

    body.innerHTML = '<div class="view-loading" style="padding:1.5rem"><div class="spinner" style="margin:auto"></div></div>';

    try {
      const data = await API.get(`/admin/audit?page=${s.page}`);

      if (!data.entries.length) {
        body.innerHTML = '<div class="admin-empty">No audit entries yet. Admin actions will appear here.</div>';
        if (pag) pag.innerHTML = '';
        return;
      }

      body.innerHTML = `
        <div style="padding:0.5rem 1rem;background:var(--bg-elevated);border-bottom:1px solid var(--border);
          font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-muted);
          display:grid;grid-template-columns:160px 100px 140px 1fr auto;gap:0.75rem;">
          <span>Time</span><span>Admin</span><span>Action</span><span>Target</span><span>Detail</span>
        </div>
        <div id="auditRows"></div>`;

      const rows = document.getElementById('auditRows');
      data.entries.forEach(e => {
        const el = document.createElement('div');
        el.className = 'audit-entry';
        el.innerHTML = `
          <span class="audit-time">${new Date(e.timestamp).toLocaleString()}</span>
          <span class="audit-admin">${UI.escapeHtml(e.admin)}</span>
          <span class="audit-action action-${e.action}">${UI.escapeHtml(e.action)}</span>
          <span class="audit-target">${UI.escapeHtml(e.target)}</span>
          <span class="audit-detail">${UI.escapeHtml(e.detail || '')}</span>
        `;
        rows.appendChild(el);
      });

      renderPagination(pag, s.page, data.has_more, data.total, () => { s.page--; fetchAudit(); }, () => { s.page++; fetchAudit(); });

    } catch (e) {
      body.innerHTML = `<div class="admin-empty" style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  // ── Pagination helper ─────────────────────────────────────────

  function renderPagination(container, page, hasMore, total, prevFn, nextFn) {
    if (!container) return;
    container.innerHTML = `
      <button id="pgPrev" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
      <span>Page ${page} · ${total} total</span>
      <button id="pgNext" ${!hasMore ? 'disabled' : ''}>Next →</button>
    `;
    container.querySelector('#pgPrev')?.addEventListener('click', prevFn);
    container.querySelector('#pgNext')?.addEventListener('click', nextFn);
  }

  return { renderView, bindView };
})();
