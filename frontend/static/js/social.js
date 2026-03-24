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
    // SVG bell — inherits currentColor so it matches the font color
    const bellSvg = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>`;
    bell.innerHTML = `
      <button class="btn-icon" id="notifBell" title="Notifications" aria-label="Notifications">
        ${bellSvg}
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

      // Compose box at top
      if (Auth.isLoggedIn()) {
        const me = Auth.getUser();
        const compose = document.createElement('div');
        compose.className = 'comment-compose';
        compose.innerHTML = `
          ${UI.avatarEl(me, 32)}
          <div style="flex:1;">
            <textarea id="newCommentBody-${postId}" placeholder="Write a comment…"
              rows="2" style="width:100%;"></textarea>
            <div style="margin-top:0.4rem;text-align:right;">
              <button class="btn btn-primary btn-sm" id="submitComment-${postId}">Post Comment</button>
            </div>
          </div>`;
        container.appendChild(compose);

        document.getElementById(`submitComment-${postId}`)?.addEventListener('click', async () => {
          const textarea = document.getElementById(`newCommentBody-${postId}`);
          const body = textarea?.value.trim();
          if (!body) return;
          const btn = document.getElementById(`submitComment-${postId}`);
          btn.disabled = true; btn.textContent = 'Posting…';
          try {
            const c = await API.post('/social/comments', { post_id: parseInt(postId), body });
            textarea.value = '';
            const listEl = document.getElementById(`commentList-${postId}`);
            if (listEl) listEl.prepend(buildCommentTree(c, postId, 0));
            // Update count
            const countEl = document.getElementById(`commentCount-${postId}`);
            if (countEl) countEl.textContent = parseInt(countEl.textContent || 0) + 1;
            UI.toast('Comment posted!', 'success');
          } catch (e) { UI.toast(e.detail || 'Failed', 'error'); }
          finally { btn.disabled = false; btn.textContent = 'Post Comment'; }
        });
      }

      // Comment list
      const listEl = document.createElement('div');
      listEl.id = `commentList-${postId}`;
      container.appendChild(listEl);

      if (comments.length === 0) {
        listEl.innerHTML = `<p style="color:var(--text-muted);font-size:0.875rem;padding:1rem 0">No comments yet. Be the first!</p>`;
      } else {
        comments.forEach(c => listEl.appendChild(buildCommentTree(c, postId, 0)));
      }

    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger);font-size:0.875rem">${UI.escapeHtml(e.detail || e.message)}</p>`;
    }
  }

  // Build a comment node at a given depth (max 3 levels: 0, 1, 2)
  function buildCommentTree(comment, postId, depth) {
    const el = document.createElement('div');
    el.className = 'comment-item';
    el.dataset.commentId = comment.id;

    const isDeleted = comment.is_deleted;
    const canDelete = !isDeleted && Auth.isLoggedIn() &&
                      (Auth.getUser()?.username === comment.author?.username || Auth.getUser()?.is_admin);
    const canReply  = Auth.isLoggedIn() && !isDeleted && depth < 2;
    const upClass   = comment.user_vote === 1  ? 'upvoted'   : '';
    const downClass = comment.user_vote === -1 ? 'downvoted' : '';
    const score     = (comment.upvotes || 0) - (comment.downvotes || 0);

    el.innerHTML = `
      <div style="flex-shrink:0;margin-top:2px;">
        ${isDeleted ? '<div style="width:28px;height:28px;border-radius:50%;background:var(--bg-elevated);"></div>'
          : UI.avatarEl(comment.author, 28)}
      </div>
      <div class="comment-body-wrap">
        <div class="comment-meta">
          ${isDeleted
            ? '<span style="color:var(--text-muted);font-style:italic;">deleted</span>'
            : `<a class="comment-author" href="/u/${UI.escapeAttr(comment.author.username)}"
                data-route="/u/${UI.escapeAttr(comment.author.username)}">
                ${UI.escapeHtml(comment.author.username)}</a>`}
          <span class="comment-time">${UI.relativeTime(comment.created_at)}</span>
          ${canDelete ? `<button class="btn-icon" style="margin-left:auto;font-size:0.7rem;color:var(--text-muted);"
              data-action="delete-comment" data-cid="${comment.id}">🗑</button>` : ''}
        </div>
        <div class="comment-bubble ${isDeleted ? 'deleted' : ''}">
          ${isDeleted ? '[deleted]' : UI.escapeHtml(comment.body)}
        </div>
        ${!isDeleted ? `
        <div class="comment-actions">
          <button class="comment-vote-btn ${upClass}" data-action="vote-comment"
            data-cid="${comment.id}" data-val="1" id="cvUp-${comment.id}">
            ▲ <span id="cvScore-${comment.id}">${score >= 0 ? '+' + score : score}</span>
          </button>
          <button class="comment-vote-btn ${downClass}" data-action="vote-comment"
            data-cid="${comment.id}" data-val="-1" id="cvDown-${comment.id}">▼</button>
          ${canReply
            ? `<button class="reply-toggle-btn" data-action="toggle-reply"
                data-cid="${comment.id}">↩ Reply</button>`
            : ''}
        </div>
        <div id="replyForm-${comment.id}" style="display:none;" class="reply-form">
          ${UI.avatarEl(Auth.getUser() || {username:'?'}, 24)}
          <div style="flex:1;">
            <textarea id="replyText-${comment.id}" placeholder="Write a reply…" rows="2"></textarea>
            <div style="margin-top:0.3rem;display:flex;gap:0.4rem;">
              <button class="btn btn-primary btn-sm" data-action="submit-reply"
                data-cid="${comment.id}" data-postid="${postId}">Reply</button>
              <button class="btn btn-ghost btn-sm" data-action="cancel-reply"
                data-cid="${comment.id}">Cancel</button>
            </div>
          </div>
        </div>` : ''}
        <div id="replies-${comment.id}" class="replies-container" ${(!comment.replies?.length) ? 'style="display:none"' : ''}></div>
      </div>`;

    // Bind events
    el.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const cid    = btn.dataset.cid;

        if (action === 'delete-comment') {
          if (!confirm('Delete this comment?')) return;
          API.delete(`/social/comments/${cid}`).then(() => {
            el.remove();
            UI.toast('Comment deleted', 'success');
          }).catch(e => UI.toast(e.detail || 'Failed', 'error'));
        }

        if (action === 'vote-comment') {
          if (!Auth.isLoggedIn()) { UI.toast('Log in to vote', 'info'); return; }
          API.post(`/social/comments/${cid}/vote?value=${btn.dataset.val}`)
            .then(res => {
              const scoreEl = document.getElementById(`cvScore-${cid}`);
              const upBtn   = document.getElementById(`cvUp-${cid}`);
              const downBtn = document.getElementById(`cvDown-${cid}`);
              if (scoreEl) {
                const s = (res.upvotes || 0) - (res.downvotes || 0);
                scoreEl.textContent = s >= 0 ? '+' + s : s;
              }
              upBtn?.classList.toggle('upvoted',   res.user_vote === 1);
              downBtn?.classList.toggle('downvoted', res.user_vote === -1);
              upBtn?.classList.toggle('upvoted',   false);
              downBtn?.classList.toggle('downvoted', false);
              if (res.user_vote === 1)  upBtn?.classList.add('upvoted');
              if (res.user_vote === -1) downBtn?.classList.add('downvoted');
            }).catch(e => UI.toast(e.detail || 'Vote failed', 'error'));
        }

        if (action === 'toggle-reply') {
          const form = document.getElementById(`replyForm-${cid}`);
          if (form) {
            const open = form.style.display === 'none';
            form.style.display = open ? 'flex' : 'none';
            if (open) document.getElementById(`replyText-${cid}`)?.focus();
          }
        }

        if (action === 'cancel-reply') {
          const form = document.getElementById(`replyForm-${cid}`);
          if (form) form.style.display = 'none';
          const ta = document.getElementById(`replyText-${cid}`);
          if (ta) ta.value = '';
        }

        if (action === 'submit-reply') {
          const body = document.getElementById(`replyText-${cid}`)?.value.trim();
          if (!body) return;
          btn.disabled = true; btn.textContent = 'Posting…';
          API.post('/social/comments', {
            post_id:   parseInt(btn.dataset.postid),
            body,
            parent_id: parseInt(cid),
          }).then(reply => {
            const repliesEl = document.getElementById(`replies-${cid}`);
            if (repliesEl) {
              repliesEl.style.display = '';
              repliesEl.appendChild(buildCommentTree(reply, postId, depth + 1));
            }
            const form = document.getElementById(`replyForm-${cid}`);
            if (form) form.style.display = 'none';
            const ta = document.getElementById(`replyText-${cid}`);
            if (ta) ta.value = '';
            UI.toast('Reply posted!', 'success');
          }).catch(e => UI.toast(e.detail || 'Failed', 'error'))
            .finally(() => { btn.disabled = false; btn.textContent = 'Reply'; });
        }
      });
    });

    // Render existing replies
    if (comment.replies?.length > 0 && depth < 2) {
      const repliesEl = el.querySelector(`#replies-${comment.id}`);
      if (repliesEl) {
        comment.replies.forEach(r => repliesEl.appendChild(buildCommentTree(r, postId, depth + 1)));
      }
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
