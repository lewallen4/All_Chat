/**
 * All_Chat — Feed Module
 * Feed rendering, sorting controls, voting, pagination.
 */

const Feed = (() => {
  let _sort   = 'new';
  let _period = 'all';
  let _page   = 1;
  let _hasMore = false;
  let _loading = false;

  // ── Render Feed View ───────────────────────────────────────────

  let _watchedOnly = false;

  function renderView() {
    return `
      <div class="feed-controls">
        <div class="sort-tabs">
          <button class="sort-tab ${_sort==='new'?'active':''}" data-sort="new">New</button>
          <button class="sort-tab ${_sort==='top'?'active':''}" data-sort="top">Top</button>
          <button class="sort-tab ${_sort==='hot'?'active':''}" data-sort="hot">Hot</button>
        </div>
        <select class="period-select ${_sort==='new'?'hidden':''}" id="periodSelect">
          <option value="24h"  ${_period==='24h'?'selected':''}>24 hours</option>
          <option value="week" ${_period==='week'?'selected':''}>This week</option>
          <option value="month"${_period==='month'?'selected':''}>This month</option>
          <option value="year" ${_period==='year'?'selected':''}>This year</option>
          <option value="all"  ${_period==='all'?'selected':''}>All time</option>
        </select>
        ${Auth.isLoggedIn() ? `
          <div class="feed-watch-toggle">
            <button class="feed-watch-btn ${!_watchedOnly?'active':''}" id="feedAllBtn">All</button>
            <button class="feed-watch-btn ${_watchedOnly?'active':''}"  id="feedWatchedBtn">⊹ Watched</button>
          </div>
          <a href="/submit" data-route="/submit" class="btn btn-primary btn-sm">✚ Post</a>
        ` : ''}
      </div>
      <div class="feed-list" id="feedList">
        <div class="view-loading"><div class="spinner"></div></div>
      </div>
      <button class="load-more-btn hidden" id="loadMoreBtn">Load more posts</button>
    `;
  }

  function bindView() {
    // Sort tabs
    document.querySelectorAll('.sort-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        _sort = btn.dataset.sort;
        _page = 1;
        document.querySelectorAll('.sort-tab').forEach(b => b.classList.toggle('active', b.dataset.sort === _sort));
        const periodSel = document.getElementById('periodSelect');
        if (periodSel) periodSel.classList.toggle('hidden', _sort === 'new');
        loadFeed(true);
      });
    });

    // Period select
    document.getElementById('periodSelect')?.addEventListener('change', e => {
      _period = e.target.value;
      _page   = 1;
      loadFeed(true);
    });

    // Load more
    document.getElementById('loadMoreBtn')?.addEventListener('click', () => {
      if (_hasMore && !_loading) { _page++; loadFeed(false); }
    });

    // Watched toggle
    document.getElementById('feedAllBtn')?.addEventListener('click', () => {
      _watchedOnly = false; _page = 1;
      document.getElementById('feedAllBtn')?.classList.add('active');
      document.getElementById('feedWatchedBtn')?.classList.remove('active');
      loadFeed(true);
    });
    document.getElementById('feedWatchedBtn')?.addEventListener('click', () => {
      _watchedOnly = true; _page = 1;
      document.getElementById('feedWatchedBtn')?.classList.add('active');
      document.getElementById('feedAllBtn')?.classList.remove('active');
      loadFeed(true);
    });

    loadFeed(true);
  }

  // ── Load Feed ──────────────────────────────────────────────────

  async function loadFeed(replace = true) {
    _loading = true;
    const list    = document.getElementById('feedList');
    const moreBtn = document.getElementById('loadMoreBtn');

    if (!list) return;
    if (replace) list.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';

    try {
      let data;
      if (_watchedOnly && Auth.isLoggedIn()) {
        const params = new URLSearchParams({ sort: _sort, period: _period, page: _page });
        data = await API.get(`/channels/watched/feed?${params}`);
      } else {
        const params = new URLSearchParams({ sort: _sort, period: _period, page: _page });
        data = await API.get(`/feed?${params}`);
      }

      if (replace) list.innerHTML = '';

      if (data.posts.length === 0 && replace) {
        list.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">⊡</div>
            <h3>Nothing here yet</h3>
            <p>Be the first to post something!</p>
          </div>`;
      } else {
        data.posts.forEach(post => {
          list.appendChild(createPostCard(post));
        });
      }

      _hasMore = data.has_more;
      if (moreBtn) moreBtn.classList.toggle('hidden', !_hasMore);

    } catch (e) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">⚠</div>
        <h3>Couldn't load feed</h3>
        <p>${UI.escapeHtml(e.detail || e.message)}</p>
      </div>`;
    } finally {
      _loading = false;
    }
  }

  // ── Post Card ──────────────────────────────────────────────────

  function createPostCard(post) {
    const el = document.createElement('div');
    el.className = 'post-card';
    el.dataset.postId = post.id;

    const score    = post.upvotes - post.downvotes;
    const scoreClass = score > 0 ? 'positive' : score < 0 ? 'negative' : '';
    const upClass   = post.user_vote ===  1 ? 'upvoted'   : '';
    const downClass = post.user_vote === -1 ? 'downvoted' : '';

    let contentHtml = '';

    // Channel tag
    if (post.channel_id && post.channel) {
      contentHtml += `<a class="channel-tag" href="/c/${UI.escapeAttr(post.channel.slug)}"
        data-route="/c/${UI.escapeAttr(post.channel.slug)}">
        <span class="channel-tag-icon">⬡</span>${UI.escapeHtml(post.channel.name)}
      </a>`;
    }

    // Pinned indicator
    if (post.is_pinned) {
      contentHtml += `<div class="pin-indicator">📌 Pinned</div>`;
    }

    if (post.title) {
      contentHtml += `<div class="post-title" data-post-id="${post.id}">${UI.escapeHtml(post.title)}</div>`;
    }
    if (post.body) {
      contentHtml += `<div class="post-text truncated">${post.body}</div>`;
    }
    if (post.image_path) {
      contentHtml += `<img class="post-image" src="${UI.escapeAttr(post.image_path)}" alt="Post image"
                        loading="lazy" onerror="this.style.display='none'" />`;
    }
    if (post.link_url) {
      contentHtml += `
        <a class="post-link" href="${UI.escapeAttr(post.link_url)}" target="_blank" rel="noopener noreferrer">
          <span class="post-link-icon">⊕</span>
          ${UI.escapeHtml(post.link_title || post.link_url)}
        </a>`;
    }

    const author    = post.author;
    const initial   = (author.display_name || author.username || '?')[0].toUpperCase();
    const authorAvatar = author.avatar_path
      ? `<img src="${UI.escapeAttr(author.avatar_path)}" style="width:18px;height:18px;border-radius:50%;object-fit:cover;" alt="" />`
      : `<span style="color:var(--accent);font-weight:700;font-size:0.85rem;">${UI.escapeHtml(initial)}</span>`;

    el.innerHTML = `
      <div class="post-votes">
        <button class="vote-btn ${upClass}" data-post-id="${post.id}" data-value="1" title="Upvote" aria-label="Upvote">▲</button>
        <span class="vote-score ${scoreClass}" id="score-${post.id}">${score}</span>
        <button class="vote-btn ${downClass}" data-post-id="${post.id}" data-value="-1" title="Downvote" aria-label="Downvote">▼</button>
      </div>
      <div class="post-body">
        <div class="post-meta">
          ${authorAvatar}
          <a class="post-author" href="/u/${UI.escapeAttr(author.username)}" data-route="/u/${UI.escapeAttr(author.username)}">
            ${UI.escapeHtml(author.username)}
          </a>
          <span class="post-time">${UI.relativeTime(post.created_at)}</span>
        </div>
        ${contentHtml}
        <div class="post-actions">
          <button class="btn-icon comment-toggle-btn" data-post-id="${post.id}"
            title="Comments" style="font-size:0.8rem;color:var(--text-muted);gap:0.25rem;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            Comments
          </button>
          ${Auth.isLoggedIn()
            ? `<button class="btn-icon bookmark-btn" data-post-id="${post.id}" title="Bookmark" aria-label="Bookmark">⊹</button>`
            : ''}
          ${Auth.isLoggedIn() && Auth.getUser()?.username === author.username
            ? `<button class="btn-icon delete-post-btn" data-post-id="${post.id}" title="Delete post" aria-label="Delete post">🗑</button>`
            : ''}
        </div>
      </div>
    `;

    // Comment toggle button
    el.querySelector('.comment-toggle-btn')?.addEventListener('click', () => {
      _toggleComments(post.id, el);
    });

    // Bookmark
    el.querySelector('.bookmark-btn')?.addEventListener('click', (e) => {
      Social.toggleBookmark(post.id, e.currentTarget);
    });

    // Click title to expand comments inline
    el.querySelector('.post-title')?.addEventListener('click', () => {
      _toggleComments(post.id, el);
    });

    // Vote buttons
    el.querySelectorAll('.vote-btn').forEach(btn => {
      btn.addEventListener('click', () => castVote(btn.dataset.postId, parseInt(btn.dataset.value)));
    });

    // Delete
    el.querySelector('.delete-post-btn')?.addEventListener('click', () => deletePost(post.id, el));

    return el;
  }

  // ── Vote ───────────────────────────────────────────────────────

  async function castVote(postId, value) {
    if (!Auth.isLoggedIn()) {
      UI.toast('Log in to vote', 'info');
      Router.navigate('/login');
      return;
    }
    try {
      const res = await API.post('/votes', { post_id: parseInt(postId), value });
      // Update score display
      const scoreEl = document.getElementById(`score-${postId}`);
      if (scoreEl) {
        const diff = res.upvotes - res.downvotes;
        scoreEl.textContent = diff;
        scoreEl.className = `vote-score ${diff > 0 ? 'positive' : diff < 0 ? 'negative' : ''}`;
      }
      // Update vote button states for this post
      const card = document.querySelector(`.post-card[data-post-id="${postId}"]`);
      if (card) {
        card.querySelectorAll('.vote-btn').forEach(btn => {
          btn.classList.remove('upvoted', 'downvoted');
          if (res.user_vote === 1  && btn.dataset.value === '1')  btn.classList.add('upvoted');
          if (res.user_vote === -1 && btn.dataset.value === '-1') btn.classList.add('downvoted');
        });
      }
    } catch (e) {
      UI.toast(e.detail || 'Vote failed', 'error');
    }
  }

  // ── Delete ─────────────────────────────────────────────────────

  async function deletePost(postId, cardEl) {
    if (!confirm('Delete this post?')) return;
    try {
      await API.delete(`/posts/${postId}`);
      cardEl.style.opacity = '0';
      cardEl.style.transform = 'scale(0.96)';
      cardEl.style.transition = 'all 0.2s ease';
      setTimeout(() => cardEl.remove(), 200);
      UI.toast('Post deleted', 'success');
    } catch (e) {
      UI.toast(e.detail || 'Delete failed', 'error');
    }
  }

  function _toggleComments(postId, cardEl) {
    // Check if comments already open
    const existing = cardEl.querySelector('.post-comments-section');
    if (existing) { existing.remove(); return; }

    const section = document.createElement('div');
    section.className = 'post-comments-section';
    section.style.cssText = 'padding:1rem 1.25rem 0.5rem;border-top:1px solid var(--border-subtle);';
    const countEl = document.createElement('div');
    countEl.style.cssText = 'font-size:0.8rem;font-weight:700;color:var(--text-muted);margin-bottom:0.75rem;';
    countEl.innerHTML = `<span id="commentCount-${postId}">0</span> comments`;
    const commentsEl = document.createElement('div');
    commentsEl.id = `comments-${postId}`;
    section.appendChild(countEl);
    section.appendChild(commentsEl);
    cardEl.querySelector('.post-body').appendChild(section);

    Social.renderComments(postId, `comments-${postId}`);
  }

  return { renderView, bindView, createPostCard, castVote };
})();
