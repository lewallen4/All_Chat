/**
 * All_Chat — Social Module
 * Follow/unfollow, bookmarks, notifications panel, threaded comments.
 */

const Social = (() => {

  // ── Follow Button ──────────────────────────────────────────────

  async function renderFollowBtn(username, containerId) {
    if (!Auth.isLoggedIn()) return;
    const me = Auth.getUser();
    if (me.username === username) return;

    try {
      const status = await API.get(`/social/follow/${encodeURIComponent(username)}/status`);
      const container = document.getElementById(containerId);
      if (!container) return;

      const btn = document.createElement('button');
      btn.className = `btn btn-sm ${status.is_following ? 'btn-ghost' : 'btn-primary'}`;
      btn.dataset.following = status.is_following ? '1' : '0';
      btn.textContent = status.is_following ? '✓ Following' : '+ Follow';
      btn.title = `${status.followers_count} followers`;

      btn.addEventListener('click', async () => {
        const isFollowing = btn.dataset.following === '1';
        try {
          if (isFollowing) {
            await API.delete(`/social/follow/${encodeURIComponent(username)}`);
            btn.dataset.following = '0';
            btn.textContent = '+ Follow';
            btn.className = 'btn btn-sm btn-primary';
            UI.toast(`Unfollowed ${username}`, 'info');
          } else {
            await API.post(`/social/follow/${encodeURIComponent(username)}`);
            btn.dataset.following = '1';
            btn.textContent = '✓ Following';
            btn.className = 'btn btn-sm btn-ghost';
            UI.toast(`Following ${username}!`, 'success');
          }
        } catch (e) {
          UI.toast(e.detail || 'Action failed', 'error');
        }
      });

      container.appendChild(btn);
    } catch {}
  }

  // ── Bookmark Button ────────────────────────────────────────────

  async function toggleBookmark(postId, btn) {
    if (!Auth.isLoggedIn()) { UI.toast('Log in to bookmark', 'info'); return; }
    const isBookmarked = btn.dataset.bookmarked === '1';
    try {
      if (isBookmarked) {
        await API.delete(`/social/bookmarks/${postId}`);
        btn.dataset.bookmarked = '0';
        btn.title = 'Bookmark';
        btn.style.color = '';
        UI.toast('Bookmark removed', 'info');
      } else {
        await API.post(`/social/bookmarks/${postId}`);
        btn.dataset.bookmarked = '1';
        btn.title = 'Remove bookmark';
        btn.style.color = 'var(--gold)';
        UI.toast('Post bookmarked', 'success');
      }
    } catch (e) {
      UI.toast(e.detail || 'Action failed', 'error');
    }
  }

  function createBookmarkBtn(postId) {
    const btn = document.createElement('button');
    btn.className = 'btn-icon';
    btn.innerHTML = '⊹';
    btn.title = 'Bookmark';
    btn.dataset.bookmarked = '0';
    btn.dataset.postId = postId;
    btn.addEventListener('click', () => toggleBookmark(postId, btn));
    return btn;
  }

  // ── Notifications ──────────────────────────────────────────────

  let _notifOpen = false;

  function renderNotifBell() {
    const actionsArea = document.querySelector('.nav-actions');
    if (!actionsArea || !Auth.isLoggedIn()) return;

    const bell = document.createElement('div');
    bell.style.position = 'relative';
    bell.innerHTML = `
      <button class="btn-icon" id="notifBell" title="Notifications" aria-label="Notifications">
        🔔
        <span id="notifDot" style="display:none;position:absolute;top:2px;right:2px;
          width:8px;height:8px;background:var(--accent);border-radius:50%;border:2px solid var(--bg-surface);">
        </span>
      </button>
      <div id="notifPanel" style="display:none;position:absolute;right:0;top:calc(100% + 8px);
        width:320px;background:var(--bg-surface);border:1px solid var(--border);
        border-radius:14px;box-shadow:var(--shadow-lg);z-index:150;overflow:hidden;">
        <div style="padding:0.85rem 1rem;border-bottom:1px solid var(--border);display:flex;
          align-items:center;justify-content:space-between;">
          <span style="font-family:'Syne',sans-serif;font-weight:700;font-size:0.95rem;">Notifications</span>
          <button class="btn-icon btn-sm" id="markAllRead" style="font-size:0.75rem;">Mark all read</button>
        </div>
        <div id="notifList" style="max-height:360px;overflow-y:auto;"></div>
      </div>
    `;

    // Insert before theme toggle
    const themeBtn = document.getElementById('themeToggle');
    actionsArea.insertBefore(bell, themeBtn);

    document.getElementById('notifBell')?.addEventListener('click', (e) => {
      e.stopPropagation();
      _notifOpen = !_notifOpen;
      document.getElementById('notifPanel').style.display = _notifOpen ? 'block' : 'none';
      if (_notifOpen) loadNotifications();
    });

    document.addEventListener('click', () => {
      if (_notifOpen) {
        _notifOpen = false;
        const panel = document.getElementById('notifPanel');
        if (panel) panel.style.display = 'none';
      }
    });

    document.getElementById('notifPanel')?.addEventListener('click', e => e.stopPropagation());

    document.getElementById('markAllRead')?.addEventListener('click', async () => {
      await API.post('/social/notifications/mark-read');
      document.getElementById('notifDot').style.display = 'none';
      loadNotifications();
    });

    pollNotifCount();
    setInterval(pollNotifCount, 30000);
  }

  async function pollNotifCount() {
    if (!Auth.isLoggedIn()) return;
    try {
      const { unread } = await API.get('/social/notifications/count');
      const dot = document.getElementById('notifDot');
      if (dot) dot.style.display = unread > 0 ? 'block' : 'none';
    } catch {}
  }

  async function loadNotifications() {
    const list = document.getElementById('notifList');
    if (!list) return;
    list.innerHTML = '<div style="padding:1.5rem;text-align:center"><div class="spinner" style="margin:auto"></div></div>';
    try {
      const notifs = await API.get('/social/notifications?page=1');
      list.innerHTML = '';
      if (notifs.length === 0) {
        list.innerHTML = '<div style="padding:1.5rem;text-align:center;color:var(--text-muted);font-size:0.875rem">No notifications yet</div>';
        return;
      }
      notifs.forEach(n => {
        const el = document.createElement('div');
        el.style.cssText = `padding:0.75rem 1rem;border-bottom:1px solid var(--border-subtle);
          cursor:pointer;transition:background 0.1s;font-size:0.875rem;
          background:${n.is_read ? 'transparent' : 'var(--accent-soft)'}`;
        el.addEventListener('mouseenter', () => el.style.background = 'var(--bg-hover)');
        el.addEventListener('mouseleave', () => el.style.background = n.is_read ? 'transparent' : 'var(--accent-soft)');
        el.innerHTML = `
          <div style="display:flex;align-items:center;gap:0.5rem;">
            ${n.actor ? UI.avatarEl(n.actor, 28) : '<span style="font-size:1.2rem">🔔</span>'}
            <div style="flex:1;min-width:0;">
              <div style="color:var(--text-primary)">${UI.escapeHtml(n.body || '')}</div>
              <div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.15rem">${UI.relativeTime(n.created_at)}</div>
            </div>
          </div>`;
        if (n.post_id) {
          el.addEventListener('click', () => {
            _notifOpen = false;
            document.getElementById('notifPanel').style.display = 'none';
            Router.navigate(`/post/${n.post_id}`);
          });
        }
        list.appendChild(el);
      });
    } catch {}
  }

  // ── Comments ───────────────────────────────────────────────────

  async function renderComments(postId, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<div class="view-loading" style="padding:1.5rem"><div class="spinner"></div></div>';

    try {
      const comments = await API.get(`/social/comments/${postId}`);
      container.innerHTML = '';

      if (comments.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.875rem;padding:0.75rem 0">No comments yet. Be the first!</p>`;
      } else {
        comments.forEach(c => container.appendChild(buildCommentEl(c, postId)));
      }

      // Add comment form at top
      if (Auth.isLoggedIn()) {
        const form = document.createElement('div');
        form.style.cssText = 'margin-bottom:1.25rem;display:flex;gap:0.5rem;align-items:flex-start;';
        form.innerHTML = `
          ${UI.avatarEl(Auth.getUser(), 32)}
          <div style="flex:1;">
            <textarea id="newCommentBody-${postId}" class="w-full" rows="2"
              placeholder="Add a comment…" style="resize:vertical;min-height:60px;"></textarea>
            <button class="btn btn-primary btn-sm mt-1" id="submitComment-${postId}">Comment</button>
          </div>`;
        container.insertBefore(form, container.firstChild);

        document.getElementById(`submitComment-${postId}`)?.addEventListener('click', async () => {
          const body = document.getElementById(`newCommentBody-${postId}`)?.value.trim();
          if (!body) return;
          try {
            const comment = await API.post('/social/comments', { post_id: parseInt(postId), body });
            document.getElementById(`newCommentBody-${postId}`).value = '';
            // Prepend new comment
            const newEl = buildCommentEl(comment, postId);
            const firstComment = container.querySelector('.comment-item');
            if (firstComment) container.insertBefore(newEl, firstComment);
            else container.appendChild(newEl);
            UI.toast('Comment posted!', 'success');
          } catch (e) {
            UI.toast(e.detail || 'Comment failed', 'error');
          }
        });
      }

    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger);font-size:0.875rem">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  }

  function buildCommentEl(comment, postId, isReply = false) {
    const el = document.createElement('div');
    el.className = 'comment-item';
    el.style.cssText = `display:flex;gap:0.6rem;margin-bottom:0.85rem;
      ${isReply ? 'margin-left:2.5rem;padding-left:0.75rem;border-left:2px solid var(--border);' : ''}`;

    const canDelete = Auth.isLoggedIn() && Auth.getUser()?.username === comment.author.username;

    el.innerHTML = `
      <div style="flex-shrink:0;margin-top:2px">${UI.avatarEl(comment.author, 28)}</div>
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.2rem;">
          <a href="/u/${UI.escapeAttr(comment.author.username)}" data-route="/u/${UI.escapeAttr(comment.author.username)}"
            style="font-weight:600;font-size:0.85rem;color:var(--accent)">
            ${UI.escapeHtml(comment.author.username)}
          </a>
          <span style="font-size:0.75rem;color:var(--text-muted)">${UI.relativeTime(comment.created_at)}</span>
          ${canDelete ? `<button class="btn-icon delete-comment" data-id="${comment.id}" style="font-size:0.7rem;margin-left:auto;opacity:0.5">🗑</button>` : ''}
        </div>
        <div style="font-size:0.875rem;color:var(--text-secondary);line-height:1.55;word-break:break-word;">
          ${UI.escapeHtml(comment.body)}
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;margin-top:0.4rem;">
          <button class="btn-icon" style="font-size:0.75rem;color:var(--text-muted)"
            data-cid="${comment.id}" data-val="1">▲ ${comment.upvotes}</button>
          <button class="btn-icon" style="font-size:0.75rem;color:var(--text-muted)"
            data-cid="${comment.id}" data-val="-1">▼</button>
          ${Auth.isLoggedIn() && !isReply
            ? `<button class="reply-btn btn-icon" style="font-size:0.75rem;color:var(--text-muted)"
                data-cid="${comment.id}">↩ Reply</button>` : ''}
        </div>
        <div class="reply-form-${comment.id}" style="display:none;margin-top:0.5rem;"></div>
        <div class="replies-${comment.id}"></div>
      </div>
    `;

    // Delete
    el.querySelector('.delete-comment')?.addEventListener('click', async () => {
      if (!confirm('Delete this comment?')) return;
      await API.delete(`/social/comments/${comment.id}`);
      el.remove();
      UI.toast('Comment deleted', 'success');
    });

    // Vote
    el.querySelectorAll('[data-cid]').forEach(btn => {
      if (btn.classList.contains('reply-btn')) return;
      btn.addEventListener('click', async () => {
        try {
          await API.post(`/social/comments/${btn.dataset.cid}/vote?value=${btn.dataset.val}`);
        } catch (e) { UI.toast(e.detail || 'Vote failed', 'error'); }
      });
    });

    // Reply
    el.querySelector('.reply-btn')?.addEventListener('click', () => {
      const rf = el.querySelector(`.reply-form-${comment.id}`);
      rf.style.display = rf.style.display === 'none' ? 'block' : 'none';
      if (rf.style.display === 'block' && !rf.innerHTML) {
        rf.innerHTML = `
          <div style="display:flex;gap:0.4rem">
            <textarea style="flex:1;resize:vertical;min-height:52px;" rows="2"
              id="replyBody-${comment.id}" placeholder="Write a reply…"></textarea>
            <button class="btn btn-primary btn-sm" id="sendReply-${comment.id}">Reply</button>
          </div>`;
        document.getElementById(`sendReply-${comment.id}`)?.addEventListener('click', async () => {
          const body = document.getElementById(`replyBody-${comment.id}`)?.value.trim();
          if (!body) return;
          try {
            const reply = await API.post('/social/comments', {
              post_id: parseInt(postId), body, parent_id: comment.id
            });
            const repliesContainer = el.querySelector(`.replies-${comment.id}`);
            repliesContainer?.appendChild(buildCommentEl(reply, postId, true));
            rf.style.display = 'none';
            rf.innerHTML = '';
            UI.toast('Reply posted!', 'success');
          } catch (e) { UI.toast(e.detail || 'Reply failed', 'error'); }
        });
      }
    });

    // Render existing replies
    if (comment.replies?.length > 0) {
      const repliesContainer = el.querySelector(`.replies-${comment.id}`);
      comment.replies.forEach(r => repliesContainer?.appendChild(buildCommentEl(r, postId, true)));
    }

    return el;
  }

  return {
    renderFollowBtn,
    createBookmarkBtn,
    toggleBookmark,
    renderNotifBell,
    pollNotifCount,
    renderComments,
  };
})();
