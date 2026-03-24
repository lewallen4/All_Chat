/**
 * All_Chat — Channels Module
 *
 * LeadPermission bitmask (mirrors backend):
 *   CAN_BAN             = 1
 *   CAN_MANAGE_POSTS    = 2
 *   CAN_MANAGE_COMMENTS = 4
 *   CAN_MANAGE_LEADS    = 8
 *   CAN_EDIT_CHANNEL    = 16
 *   CAN_PIN_POSTS       = 32
 *   ALL                 = 63
 */

const Channels = (() => {

  const PERMS = {
    CAN_BAN:             1,
    CAN_MANAGE_POSTS:    2,
    CAN_MANAGE_COMMENTS: 4,
    CAN_MANAGE_LEADS:    8,
    CAN_EDIT_CHANNEL:    16,
    CAN_PIN_POSTS:       32,
  };
  const PERM_LABELS = {
    CAN_BAN:             'Ban & Unban Members',
    CAN_MANAGE_POSTS:    'Remove & Restore Posts',
    CAN_MANAGE_COMMENTS: 'Remove Comments',
    CAN_MANAGE_LEADS:    'Manage Leads',
    CAN_EDIT_CHANNEL:    'Edit Channel Info',
    CAN_PIN_POSTS:       'Pin & Unpin Posts',
  };

  function hasPerm(permissions, perm) {
    return (permissions & perm) !== 0;
  }

  // ── Channel Directory ──────────────────────────────────────────

  function renderDirectoryView() {
    return `
      <div style="max-width:900px;margin:0 auto;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem;flex-wrap:wrap;gap:0.75rem;">
          <h2 style="font-family:'Syne',sans-serif;font-size:1.4rem;font-weight:800;">Channels</h2>
          <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;">
            ${Auth.isLoggedIn() ? `
              <div class="channel-dir-filter">
                <button class="channel-dir-btn active" id="dirAllBtn">All</button>
                <button class="channel-dir-btn" id="dirWatchedBtn">⊹ Watched</button>
              </div>` : ''}
            <div class="nav-search" style="max-width:220px;">
              <span class="search-icon">⌕</span>
              <input type="search" id="channelSearchInput" placeholder="Find a channel…" autocomplete="off" />
            </div>
            ${Auth.isLoggedIn()
              ? `<button class="btn btn-primary btn-sm" id="createChannelBtn">✚ Create Channel</button>`
              : ''}
          </div>
        </div>
        <div class="channels-grid" id="channelsGrid">
          <div class="view-loading"><div class="spinner"></div></div>
        </div>
        <button class="load-more-btn hidden" id="channelLoadMore">Load more</button>
      </div>`;
  }

  async function bindDirectoryView() {
    let page = 1, q = '', watchedOnly = false;
    let debounce;

    document.getElementById('channelSearchInput')?.addEventListener('input', e => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { q = e.target.value.trim(); page = 1; fetchChannels(true); }, 300);
    });
    document.getElementById('channelLoadMore')?.addEventListener('click', () => { page++; fetchChannels(false); });
    document.getElementById('createChannelBtn')?.addEventListener('click', showCreateModal);

    document.getElementById('dirAllBtn')?.addEventListener('click', () => {
      watchedOnly = false; page = 1;
      document.getElementById('dirAllBtn')?.classList.add('active');
      document.getElementById('dirWatchedBtn')?.classList.remove('active');
      fetchChannels(true);
    });
    document.getElementById('dirWatchedBtn')?.addEventListener('click', async () => {
      watchedOnly = true; page = 1;
      document.getElementById('dirWatchedBtn')?.classList.add('active');
      document.getElementById('dirAllBtn')?.classList.remove('active');
      fetchChannels(true);
    });

    async function fetchChannels(replace) {
      const grid = document.getElementById('channelsGrid');
      if (!grid) return;
      if (replace) grid.innerHTML = '<div class="view-loading" style="grid-column:1/-1"><div class="spinner" style="margin:auto"></div></div>';
      try {
        let data;
        if (watchedOnly && Auth.isLoggedIn()) {
          // Get watched channel IDs then filter
          const allData = await API.get(`/channels?page=1&q=${encodeURIComponent(q)}`);
          // Filter to watched ones client-side (small list)
          const watchStatuses = await Promise.all(
            allData.channels.map(ch =>
              API.get(`/channels/${ch.slug}/watch/status`)
                .then(s => s.watching ? ch : null)
                .catch(() => null)
            )
          );
          data = {
            channels: watchStatuses.filter(Boolean),
            total: watchStatuses.filter(Boolean).length,
            has_more: false,
          };
        } else {
          data = await API.get(`/channels?page=${page}&q=${encodeURIComponent(q)}`);
        }
        if (replace) grid.innerHTML = '';
        if (!data.channels.length && replace) {
          grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
            <div class="empty-state-icon">⬡</div>
            <h3>No channels yet</h3>
            <p>${Auth.isLoggedIn() ? 'Be the first to create one!' : 'Log in to create a channel.'}</p>
          </div>`;
          return;
        }
        data.channels.forEach(ch => grid.appendChild(buildChannelCard(ch)));
        const btn = document.getElementById('channelLoadMore');
        if (btn) btn.classList.toggle('hidden', !data.has_more);
      } catch (e) {
        if (replace) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</div>`;
      }
    }

    fetchChannels(true);
  }

  function buildChannelCard(ch) {
    const el = document.createElement('a');
    el.className = 'channel-card';
    el.href = `/c/${ch.slug}`;
    el.setAttribute('data-route', `/c/${ch.slug}`);
    const initial = ch.name[0].toUpperCase();
    el.innerHTML = `
      ${ch.banner_path
        ? `<img class="channel-card-banner" src="${UI.escapeAttr(ch.banner_path)}" alt="" loading="lazy" />`
        : `<div class="channel-card-banner"></div>`}
      <div class="channel-card-body">
        <div class="channel-card-avatar">
          ${ch.avatar_path
            ? `<img src="${UI.escapeAttr(ch.avatar_path)}" style="width:100%;height:100%;border-radius:6px;object-fit:cover;" alt="" />`
            : UI.escapeHtml(initial)}
        </div>
        <div style="flex:1;min-width:0;">
          <div class="channel-card-name">${UI.escapeHtml(ch.name)}</div>
          <div class="channel-card-slug">#${UI.escapeHtml(ch.slug)}</div>
          ${ch.description ? `<div class="channel-card-desc">${UI.escapeHtml(ch.description)}</div>` : ''}
        </div>
      </div>
      <div class="channel-card-footer">
        <span> ${ch.member_count.toLocaleString()} members</span>
        <span> ${ch.post_count.toLocaleString()} posts</span>
        ${ch.is_private ? '<span class="channel-pill pill-private">🔒 Private</span>' : ''}
        ${ch.is_locked  ? '<span class="channel-pill pill-locked">🔐 Locked</span>'  : ''}
        ${ch.viewer_role ? roleBadge(ch.viewer_role, ch.viewer_title) : ''}
      </div>`;
    return el;
  }

  // ── Channel Page ───────────────────────────────────────────────

  async function renderChannelPage(slug) {
    const main = document.getElementById('mainContent');
    main.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';

    try {
      const ch = await API.get(`/channels/${slug}`);
      const isLead  = ch.viewer_role === 'chief_lead' || ch.viewer_role === 'lead';
      const isAdmin = Auth.getUser()?.is_admin;
      const canEdit = isAdmin || (isLead && hasPerm(ch.viewer_permissions, PERMS.CAN_EDIT_CHANNEL));
      const canBan  = isAdmin || (isLead && hasPerm(ch.viewer_permissions, PERMS.CAN_BAN));
      const isMember = !!ch.viewer_role && ch.viewer_role !== 'banned';

      main.innerHTML = `
        <div style="max-width:840px;margin:0 auto;">
          ${buildChannelHeader(ch, isMember, isLead, isAdmin)}

          ${(isLead || isAdmin) ? buildLeadPanel(ch) : ''}

          <div class="channel-tabs">
            <button class="channel-tab-btn active" data-tab="posts">Posts</button>
            <button class="channel-tab-btn" data-tab="members">Members</button>
            ${ch.rules ? `<button class="channel-tab-btn" data-tab="rules">Rules</button>` : ''}
          </div>

          <div id="channelTabContent"></div>
        </div>`;

      bindChannelPage(ch, isMember, isLead, isAdmin);

    } catch (e) {
      main.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">⬡</div>
        <h3>${e.status === 404 ? 'Channel not found' : 'Error loading channel'}</h3>
        <p>${UI.escapeHtml(e.detail || e.message)}</p>
      </div>`;
    }
  }

  function buildChannelHeader(ch, isMember, isLead, isAdmin) {
    const initial = ch.name[0].toUpperCase();
    const myRole  = ch.viewer_role;
    const myTitle = ch.viewer_title;

    return `
      <div class="channel-header">
        ${ch.banner_path
          ? `<img class="channel-banner" src="${UI.escapeAttr(ch.banner_path)}" alt="" />`
          : `<div class="channel-banner-placeholder"></div>`}
        <div class="channel-header-body">
          <div class="channel-avatar-wrap">
            ${ch.avatar_path
              ? `<img class="channel-avatar" src="${UI.escapeAttr(ch.avatar_path)}" alt="" />`
              : `<div class="channel-avatar-placeholder">${UI.escapeHtml(initial)}</div>`}
          </div>
          <div class="channel-meta">
            <div class="channel-name">
              ${UI.escapeHtml(ch.name)}
              <span class="channel-slug-label">#${UI.escapeHtml(ch.slug)}</span>
              ${ch.is_private  ? '<span class="channel-pill pill-private">🔒 Private</span>'  : ''}
              ${ch.is_locked   ? '<span class="channel-pill pill-locked">🔐 Locked</span>'   : ''}
              ${ch.is_archived ? '<span class="channel-pill pill-archived">Archived</span>'   : ''}
            </div>
            <div class="channel-stats">
              <span><span class="channel-stat-value">${ch.member_count.toLocaleString()}</span> members</span>
              <span><span class="channel-stat-value">${ch.post_count.toLocaleString()}</span> posts</span>
              <span>Created ${UI.relativeTime(ch.created_at)}</span>
            </div>
            ${ch.description ? `<div class="channel-desc">${UI.escapeHtml(ch.description)}</div>` : ''}
            ${myRole ? `<div style="margin-top:0.5rem;">${roleBadge(myRole, myTitle)}</div>` : ''}
          </div>
          <div class="channel-header-actions" id="channelActions"></div>
        </div>
      </div>`;
  }

  function buildLeadPanel(ch) {
    const canManagePosts    = Auth.getUser()?.is_admin || hasPerm(ch.viewer_permissions || 0, PERMS.CAN_MANAGE_POSTS);
    const canManageLeads    = Auth.getUser()?.is_admin || ch.viewer_role === 'chief_lead' || hasPerm(ch.viewer_permissions || 0, PERMS.CAN_MANAGE_LEADS);
    const canBan            = Auth.getUser()?.is_admin || hasPerm(ch.viewer_permissions || 0, PERMS.CAN_BAN);
    const canEdit           = Auth.getUser()?.is_admin || hasPerm(ch.viewer_permissions || 0, PERMS.CAN_EDIT_CHANNEL);
    const isChief           = ch.viewer_role === 'chief_lead' || Auth.getUser()?.is_admin;

    const actions = [];
    if (canEdit)        actions.push(`<button class="btn btn-ghost btn-sm" id="editChannelBtn">✏ Edit</button>`);
    if (canManageLeads) actions.push(`<button class="btn btn-ghost btn-sm" id="manageLeadsBtn">👑 Leads</button>`);
    if (canBan)         actions.push(`<button class="btn btn-ghost btn-sm" id="banMemberBtn">🚫 Ban User</button>`);
    if (isChief)        actions.push(`<button class="btn btn-ghost btn-sm" id="transferChiefBtn">⇄ Transfer Chief</button>`);

    return `
      <div class="lead-panel">
        <div class="lead-panel-title">Lead Controls</div>
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
          ${actions.join('')}
        </div>
      </div>`;
  }

  function bindChannelPage(ch, isMember, isLead, isAdmin) {
    const slug = ch.slug;

    // Watch button (separate from membership)
    const actionsEl = document.getElementById('channelActions');
    if (actionsEl && Auth.isLoggedIn()) {
      _renderWatchBtn(ch.slug, actionsEl);
    }

    if (actionsEl) {
      if (isMember && ch.viewer_role !== 'chief_lead') {
        const leaveBtn = document.createElement('button');
        leaveBtn.className = 'btn btn-ghost btn-sm';
        leaveBtn.textContent = 'Leave';
        leaveBtn.addEventListener('click', async () => {
          if (!confirm(`Leave #${slug}?`)) return;
          try { await API.post(`/channels/${slug}/leave`); Router.navigate('/channels'); }
          catch (e) { UI.toast(e.detail || e.message, 'error'); }
        });
        actionsEl.appendChild(leaveBtn);
      } else if (!isMember && !ch.is_private) {
        const joinBtn = document.createElement('button');
        joinBtn.className = 'btn btn-primary btn-sm';
        joinBtn.textContent = '+ Join';
        joinBtn.addEventListener('click', async () => {
          try {
            await API.post(`/channels/${slug}/join`);
            UI.toast(`Joined #${slug}!`, 'success');
            Router.navigate(`/c/${slug}`);
          } catch (e) { UI.toast(e.detail || e.message, 'error'); }
        });
        actionsEl.appendChild(joinBtn);
      }

      if (Auth.isLoggedIn() && (isMember || isAdmin)) {
        const postBtn = document.createElement('a');
        postBtn.className = 'btn btn-primary btn-sm';
        postBtn.textContent = '✚ Post';
        postBtn.href = `/submit?channel=${slug}`;
        postBtn.setAttribute('data-route', `/submit?channel=${slug}`);
        actionsEl.appendChild(postBtn);
      }
    }

    // Tabs
    document.querySelectorAll('.channel-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.channel-tab-btn').forEach(b => b.classList.toggle('active', b === btn));
        loadTab(btn.dataset.tab, ch);
      });
    });
    loadTab('posts', ch);

    // Lead panel buttons
    document.getElementById('editChannelBtn')?.addEventListener('click', () => showEditChannelModal(ch));
    document.getElementById('manageLeadsBtn')?.addEventListener('click', () => showManageLeadsModal(ch));
    document.getElementById('banMemberBtn')?.addEventListener('click',   () => showBanModal(ch));
    document.getElementById('transferChiefBtn')?.addEventListener('click', () => showTransferChiefModal(ch));
  }

  function loadTab(tab, ch) {
    const container = document.getElementById('channelTabContent');
    if (!container) return;
    if (tab === 'posts')   loadChannelPosts(ch, container);
    if (tab === 'members') loadChannelMembers(ch, container);
    if (tab === 'rules') {
      container.innerHTML = `<div class="card" style="font-size:0.9rem;line-height:1.7;">
        ${ch.rules ? UI.renderMarkdown(ch.rules) : '<p style="color:var(--text-muted)">No rules set.</p>'}
      </div>`;
    }
  }

  async function loadChannelPosts(ch, container) {
    container.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';
    try {
      const data = await API.get(`/channels/${ch.slug}/posts?sort=new&period=all&page=1`);
      container.innerHTML = '';

      if (!data.posts.length) {
        container.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">📭</div>
          <h3>No posts yet</h3>
          ${Auth.isLoggedIn() ? `<p><a href="/submit?channel=${ch.slug}" data-route="/submit?channel=${ch.slug}">Be the first to post!</a></p>` : ''}
        </div>`;
        return;
      }

      const list = document.createElement('div');
      list.className = 'feed-list';
      data.posts.forEach(p => {
        const card = Feed.createPostCard(p);

        // Add pin indicator if pinned
        if (p.is_pinned) {
          const pinEl = document.createElement('div');
          pinEl.className = 'pin-indicator';
          pinEl.innerHTML = '📌 Pinned';
          pinEl.style.cssText = 'padding:0.25rem 1rem;font-size:0.72rem;color:var(--gold);font-weight:700;';
          card.insertBefore(pinEl, card.firstChild);
        }

        // Lead moderation actions
        const isLead  = ch.viewer_role === 'chief_lead' || ch.viewer_role === 'lead';
        const isAdmin = Auth.getUser()?.is_admin;
        const canManagePosts = isAdmin || (isLead && hasPerm(ch.viewer_permissions || 0, PERMS.CAN_MANAGE_POSTS));
        const canPin  = isAdmin || (isLead && hasPerm(ch.viewer_permissions || 0, PERMS.CAN_PIN_POSTS));

        if (canManagePosts || canPin) {
          const actionsEl = card.querySelector('.post-actions');
          if (actionsEl) {
            if (canPin) {
              const pinBtn = document.createElement('button');
              pinBtn.className = 'btn-icon';
              pinBtn.title = p.is_pinned ? 'Unpin' : 'Pin post';
              pinBtn.textContent = '📌';
              pinBtn.addEventListener('click', async () => {
                try {
                  const r = await API.post(`/channels/${ch.slug}/posts/${p.id}/pin`);
                  UI.toast(r.message, 'success');
                  loadChannelPosts(ch, container);
                } catch (e) { UI.toast(e.detail || e.message, 'error'); }
              });
              actionsEl.appendChild(pinBtn);
            }
            if (canManagePosts && !p.removed_by_lead) {
              const rmBtn = document.createElement('button');
              rmBtn.className = 'btn-icon';
              rmBtn.title = 'Remove post';
              rmBtn.innerHTML = '🛡✕';
              rmBtn.style.color = 'var(--danger)';
              rmBtn.addEventListener('click', async () => {
                if (!confirm('Remove this post from the channel?')) return;
                try {
                  const r = await API.post(`/channels/${ch.slug}/posts/${p.id}/remove`);
                  UI.toast(r.message, 'success');
                  loadChannelPosts(ch, container);
                } catch (e) { UI.toast(e.detail || e.message, 'error'); }
              });
              actionsEl.appendChild(rmBtn);
            }
          }
        }

        list.appendChild(card);
      });
      container.appendChild(list);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠</div><p>${UI.escapeHtml(e.detail || e.message)}</p></div>`;
    }
  }

  async function loadChannelMembers(ch, container) {
    container.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';
    try {
      const data = await API.get(`/channels/${ch.slug}/members?page=1`);
      container.innerHTML = `<div class="card">
        <div style="font-family:'Syne',sans-serif;font-weight:700;margin-bottom:0.85rem;font-size:0.9rem;">
          ${data.total} Members
        </div>
        <div id="membersList"></div>
      </div>`;
      const list = document.getElementById('membersList');
      data.members.forEach(m => {
        const row = document.createElement('div');
        row.className = 'member-row';
        row.innerHTML = `
          ${UI.avatarEl(m.user, 36)}
          <div class="member-info">
            <div class="member-name">
              <a href="/u/${UI.escapeAttr(m.user.username)}" data-route="/u/${UI.escapeAttr(m.user.username)}"
                style="color:var(--text-primary);text-decoration:none;">${UI.escapeHtml(m.user.username)}</a>
              ${roleBadge(m.role, m.title)}
            </div>
            ${m.title ? `<div class="member-title">${UI.escapeHtml(m.title)}</div>` : ''}
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted)">Joined ${UI.relativeTime(m.joined_at)}</div>`;
        list.appendChild(row);
      });
    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger)">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  }

  // ── Lead Panel Modals ──────────────────────────────────────────

  function showEditChannelModal(ch) {
    UI.openModal(`
      <h3 style="margin-bottom:1rem;">Edit #${UI.escapeHtml(ch.slug)}</h3>
      <div id="editChErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>Display Name</label>
        <input type="text" id="editChName" value="${UI.escapeAttr(ch.name)}" maxlength="80" />
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea id="editChDesc" rows="3" maxlength="2000">${UI.escapeHtml(ch.description || '')}</textarea>
      </div>
      <div class="form-group">
        <label>Rules <span style="color:var(--text-muted);font-weight:400">(Markdown)</span></label>
        <textarea id="editChRules" rows="4" maxlength="5000">${UI.escapeHtml(ch.rules || '')}</textarea>
      </div>
      <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;font-size:0.875rem;cursor:pointer;font-weight:400;">
        <input type="checkbox" id="editChPrivate" ${ch.is_private ? 'checked' : ''} />
        Private channel (invite-only)
      </label>
      <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.25rem;font-size:0.875rem;cursor:pointer;font-weight:400;">
        <input type="checkbox" id="editChLocked" ${ch.is_locked ? 'checked' : ''} />
        Lock channel (no new posts)
      </label>
      <div style="border-top:1px solid var(--border);margin:1rem 0;padding-top:1rem;">
        <div style="font-size:0.8rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;
          letter-spacing:0.05em;margin-bottom:0.75rem;">Media</div>
        <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
          <div>
            <label style="display:block;font-size:0.8rem;margin-bottom:0.3rem;">
              Channel Avatar <span style="color:var(--text-muted);font-weight:400">(max 200×200px, 5MB)</span>
            </label>
            <input type="file" id="editChAvatar" accept="image/jpeg,image/png,image/webp"
              style="font-size:0.8rem;" />
          </div>
          <div>
            <label style="display:block;font-size:0.8rem;margin-bottom:0.3rem;">
              Banner Image <span style="color:var(--text-muted);font-weight:400">(500×100px landscape, 5MB)</span>
            </label>
            <input type="file" id="editChBanner" accept="image/jpeg,image/png,image/webp"
              style="font-size:0.8rem;" />
          </div>
        </div>
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-primary" id="editChSave">Save Changes</button>
      </div>`);

    document.getElementById('editChSave')?.addEventListener('click', async () => {
      const err = document.getElementById('editChErr');
      const btn = document.getElementById('editChSave');
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Saving…';
      try {
        await API.patch(`/channels/${ch.slug}`, {
          name:       document.getElementById('editChName').value.trim(),
          description: document.getElementById('editChDesc').value.trim() || null,
          rules:       document.getElementById('editChRules').value.trim() || null,
          is_private:  document.getElementById('editChPrivate').checked,
          is_locked:   document.getElementById('editChLocked').checked,
        });
        UI.toast('Channel updated!', 'success');
        UI.closeModal();
        Router.navigate(`/c/${ch.slug}`);
      } catch (e) {
        err.textContent = e.detail || e.message; err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Save Changes';
      }
    });
  }

  function showManageLeadsModal(ch) {
    UI.openModal(`
      <h3 style="margin-bottom:1rem;">Manage Leads — #${UI.escapeHtml(ch.slug)}</h3>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1.25rem;">
        Promote a member to Lead, update their permissions, or demote them.
      </p>
      <div id="leadMgmtErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>Username</label>
        <input type="text" id="leadUsername" placeholder="their_username" autocomplete="off" />
      </div>
      <div class="form-group">
        <label>Role</label>
        <select id="leadRole">
          <option value="lead">Lead</option>
          <option value="member">Member (demote)</option>
        </select>
      </div>
      <div class="form-group" id="leadPermsGroup">
        <label style="margin-bottom:0.6rem;display:block;">Permissions</label>
        <div class="perm-grid">
          ${Object.entries(PERM_LABELS).map(([key, label]) => `
            <label class="perm-toggle ${key === 'CAN_BAN' || key === 'CAN_MANAGE_POSTS' || key === 'CAN_MANAGE_COMMENTS' ? 'active' : ''}"
              data-perm="${PERMS[key]}">
              <input type="checkbox" ${key === 'CAN_BAN' || key === 'CAN_MANAGE_POSTS' || key === 'CAN_MANAGE_COMMENTS' ? 'checked' : ''}
                data-perm="${PERMS[key]}" />
              ${label}
            </label>`).join('')}
        </div>
      </div>
      <div class="form-group">
        <label>Custom Title <span style="color:var(--text-muted);font-weight:400">(optional)</span></label>
        <input type="text" id="leadTitle" placeholder="e.g. Moderator, News Bot" maxlength="64" />
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-primary" id="setLeadBtn">Apply</button>
      </div>`);

    // Toggle perm visual state
    document.querySelectorAll('.perm-toggle').forEach(label => {
      label.addEventListener('click', () => {
        const cb = label.querySelector('input');
        cb.checked = !cb.checked;
        label.classList.toggle('active', cb.checked);
      });
    });

    // Hide perms when demoting
    document.getElementById('leadRole')?.addEventListener('change', e => {
      document.getElementById('leadPermsGroup').style.display = e.target.value === 'lead' ? '' : 'none';
    });

    document.getElementById('setLeadBtn')?.addEventListener('click', async () => {
      const err = document.getElementById('leadMgmtErr');
      const btn = document.getElementById('setLeadBtn');
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Applying…';

      const role = document.getElementById('leadRole').value;
      let permissions = 0;
      if (role === 'lead') {
        document.querySelectorAll('.perm-toggle input:checked').forEach(cb => {
          permissions |= parseInt(cb.dataset.perm);
        });
      }

      try {
        const r = await API.post(`/channels/${ch.slug}/leads/set`, {
          username:    document.getElementById('leadUsername').value.trim(),
          role,
          permissions,
          title:       document.getElementById('leadTitle').value.trim() || null,
        });
        UI.toast(r.message, 'success');
        UI.closeModal();
        Router.navigate(`/c/${ch.slug}`);
      } catch (e) {
        err.textContent = e.detail || e.message; err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Apply';
      }
    });
  }

  function showBanModal(ch) {
    UI.openModal(`
      <h3 style="margin-bottom:1rem;">Ban Member from #${UI.escapeHtml(ch.slug)}</h3>
      <div id="banErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>Username</label>
        <input type="text" id="banUsername" placeholder="their_username" autocomplete="off" />
      </div>
      <div class="form-group">
        <label>Reason <span style="color:var(--text-muted);font-weight:400">(optional, shown to user)</span></label>
        <input type="text" id="banReason" placeholder="e.g. Repeated spam" maxlength="200" />
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-danger" id="doBanBtn">Ban User</button>
      </div>`);

    document.getElementById('doBanBtn')?.addEventListener('click', async () => {
      const err = document.getElementById('banErr');
      const btn = document.getElementById('doBanBtn');
      const username = document.getElementById('banUsername').value.trim();
      if (!username) { err.textContent = 'Enter a username.'; err.style.display = 'block'; return; }
      if (!confirm(`Ban @${username} from #${ch.slug}?`)) return;
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Banning…';
      try {
        const r = await API.post(`/channels/${ch.slug}/ban`, {
          username,
          reason: document.getElementById('banReason').value.trim() || null,
        });
        UI.toast(r.message, 'success');
        UI.closeModal();
      } catch (e) {
        err.textContent = e.detail || e.message; err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Ban User';
      }
    });
  }

  function showTransferChiefModal(ch) {
    UI.openModal(`
      <h3 style="margin-bottom:0.5rem;">Transfer Chief Lead</h3>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1.25rem;">
        Transfer your Chief Lead role to another member. You will become a regular Lead.
      </p>
      <div id="transferErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>New Chief Lead's Username</label>
        <input type="text" id="transferUsername" placeholder="their_username" autocomplete="off" />
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-danger" id="doTransferBtn">Transfer</button>
      </div>`);

    document.getElementById('doTransferBtn')?.addEventListener('click', async () => {
      const username = document.getElementById('transferUsername').value.trim();
      if (!confirm(`Transfer Chief Lead of #${ch.slug} to @${username}? This cannot be undone.`)) return;
      const err = document.getElementById('transferErr');
      const btn = document.getElementById('doTransferBtn');
      err.style.display = 'none'; btn.disabled = true;
      try {
        const r = await API.post(`/channels/${ch.slug}/leads/transfer-chief?username=${encodeURIComponent(username)}`);
        UI.toast(r.message, 'success');
        UI.closeModal();
        Router.navigate(`/c/${ch.slug}`);
      } catch (e) {
        err.textContent = e.detail || e.message; err.style.display = 'block';
        btn.disabled = false;
      }
    });
  }

  // ── Create Channel Modal ───────────────────────────────────────

  function showCreateModal() {
    UI.openModal(`
      <h3 style="margin-bottom:1rem;">Create a Channel</h3>
      <div id="createChErr" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label>Slug <span style="color:var(--text-muted);font-weight:400">(URL name, permanent)</span></label>
        <input type="text" id="createChSlug" placeholder="my-channel" maxlength="64"
          style="font-family:'JetBrains Mono',monospace;" />
        <span class="form-hint">Lowercase, letters, numbers, hyphens. e.g. gaming-news</span>
      </div>
      <div class="form-group">
        <label>Display Name</label>
        <input type="text" id="createChName" placeholder="Gaming News" maxlength="80" />
      </div>
      <div class="form-group">
        <label>Description <span style="color:var(--text-muted);font-weight:400">(optional)</span></label>
        <textarea id="createChDesc" rows="2" maxlength="2000" placeholder="What's this channel about?"></textarea>
      </div>
      <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.25rem;font-size:0.875rem;cursor:pointer;font-weight:400;">
        <input type="checkbox" id="createChPrivate" />
        Make private (members only)
      </label>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="UI.closeModal()">Cancel</button>
        <button class="btn btn-primary" id="doCreateCh">Create Channel</button>
      </div>`);

    // Auto-fill slug from name
    document.getElementById('createChName')?.addEventListener('input', e => {
      const slug = document.getElementById('createChSlug');
      if (!slug._manuallyEdited) {
        slug.value = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64);
      }
    });
    document.getElementById('createChSlug')?.addEventListener('input', e => {
      e.target._manuallyEdited = true;
    });

    document.getElementById('doCreateCh')?.addEventListener('click', async () => {
      const err = document.getElementById('createChErr');
      const btn = document.getElementById('doCreateCh');
      err.style.display = 'none'; btn.disabled = true; btn.textContent = 'Creating…';
      try {
        const ch = await API.post('/channels', {
          slug:        document.getElementById('createChSlug').value.trim(),
          name:        document.getElementById('createChName').value.trim(),
          description: document.getElementById('createChDesc').value.trim() || null,
          is_private:  document.getElementById('createChPrivate').checked,
        });
        UI.toast(`Channel #${ch.slug} created!`, 'success');
        UI.closeModal();
        Router.navigate(`/c/${ch.slug}`);
      } catch (e) {
        err.textContent = e.detail || e.message; err.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Create Channel';
      }
    });
  }

  // ── Role badge helper ──────────────────────────────────────────

  function roleBadge(role, title) {
    if (!role || role === 'member') return '';
    const labels = {
      chief_lead: '👑 Chief Lead',
      lead:       '🛡 Lead',
    };
    const cls = { chief_lead: 'role-chief-lead', lead: 'role-lead' };
    if (role === 'chief_lead' || role === 'lead') {
      const label = title ? `🛡 ${title}` : labels[role];
      return `<span class="role-badge ${cls[role]}">${UI.escapeHtml(label)}</span>`;
    }
    return '';
  }

  function adminBadge() {
    return `<span class="role-badge role-admin">⚡ Admin</span>`;
  }

  async function _renderWatchBtn(slug, container) {
    try {
      const status  = await API.get(`/channels/${encodeURIComponent(slug)}/watch/status`);
      const btn     = document.createElement('button');
      btn.className = `btn-watch ${status.watching ? 'watching' : ''}`;
      btn.innerHTML = status.watching ? '⊹ Watching' : '⊹ Watch';
      btn.title     = status.watching ? 'Click to unwatch' : 'Watch this channel';
      btn.addEventListener('click', async () => {
        try {
          if (status.watching) {
            await API.delete(`/channels/${slug}/watch`);
            status.watching   = false;
            btn.className     = 'btn-watch';
            btn.innerHTML     = '⊹ Watch';
            UI.toast(`Unwatched #${slug}`, 'info');
          } else {
            await API.post(`/channels/${slug}/watch`);
            status.watching   = true;
            btn.className     = 'btn-watch watching';
            btn.innerHTML     = '⊹ Watching';
            UI.toast(`Now watching #${slug}!`, 'success');
          }
        } catch (e) { UI.toast(e.detail || e.message, 'error'); }
      });
      container.prepend(btn);
    } catch {}
  }

  return {
    renderDirectoryView,
    bindDirectoryView,
    renderChannelPage,
    buildChannelCard,
    roleBadge,
    adminBadge,
    PERMS,
  };
})();
