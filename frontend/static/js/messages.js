/**
 * All_Chat — Messages Module
 * E2E encrypted DM UI. All crypto is client-side.
 */

const Messages = (() => {
  let _activeConv  = null;
  let _pollTimer   = null;

  function renderView() {
    return `
      <div class="messages-layout">
        <div class="conversations-list">
          <div class="conv-header">Messages</div>
          <div id="convList">
            <div class="view-loading" style="padding:2rem"><div class="spinner"></div></div>
          </div>
          <div style="padding:0.75rem">
            <button class="btn btn-ghost w-full btn-sm" id="newMsgBtn">✉ New message</button>
          </div>
        </div>
        <div class="chat-pane" id="chatPane">
          <div class="empty-state">
            <div class="empty-state-icon">✉</div>
            <h3>Select a conversation</h3>
            <p>Messages are end-to-end encrypted</p>
          </div>
        </div>
      </div>
    `;
  }

  async function bindView() {
    await CryptoE2E.registerPublicKey().catch(() => {});
    await loadConversations();

    document.getElementById('newMsgBtn')?.addEventListener('click', () => {
      UI.openModal(`
        <h3 style="margin-bottom:1rem">New Message</h3>
        <div class="form-group">
          <label for="newMsgUser">Username</label>
          <input type="text" id="newMsgUser" placeholder="their_username" autocomplete="off" />
        </div>
        <button class="btn btn-primary w-full" id="newMsgGo">Start Conversation</button>
      `);
      document.getElementById('newMsgGo')?.addEventListener('click', () => {
        const username = document.getElementById('newMsgUser')?.value.trim();
        if (!username) return;
        UI.closeModal();
        openConversation(username);
      });
    });
  }

  async function loadConversations() {
    const list = document.getElementById('convList');
    if (!list) return;
    try {
      const convs = await API.get('/messages/conversations');
      list.innerHTML = '';
      if (convs.length === 0) {
        list.innerHTML = `<div style="padding:1rem;font-size:0.85rem;color:var(--text-muted);text-align:center">No conversations yet</div>`;
        return;
      }
      convs.forEach(c => {
        const el = document.createElement('div');
        el.className = `conv-item ${_activeConv === c.user.username ? 'active' : ''}`;
        el.innerHTML = `
          <div style="flex:1;min-width:0">
            <div class="flex items-center justify-between">
              <div class="conv-name">${UI.escapeHtml(c.user.display_name || c.user.username)}</div>
              ${c.unread_count > 0 ? `<span class="badge">${c.unread_count}</span>` : ''}
            </div>
            <div class="conv-time">${UI.relativeTime(c.last_message_at)}</div>
          </div>`;
        el.addEventListener('click', () => openConversation(c.user.username));
        list.appendChild(el);
      });
    } catch (e) {
      list.innerHTML = `<div style="padding:1rem;color:var(--danger);font-size:0.85rem">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  async function openConversation(username) {
    _activeConv = username;
    // Mark active in sidebar
    document.querySelectorAll('.conv-item').forEach(el => {
      el.classList.toggle('active', el.querySelector('.conv-name')?.textContent === username);
    });

    const pane = document.getElementById('chatPane');
    if (!pane) return;
    pane.innerHTML = `
      <div class="chat-header">
        ${UI.avatarEl({ username }, 32)}
        <span style="font-weight:700">${UI.escapeHtml(username)}</span>
        <a href="/u/${UI.escapeAttr(username)}" data-route="/u/${UI.escapeAttr(username)}"
           style="margin-left:auto;font-size:0.8rem;color:var(--text-muted)">View profile →</a>
      </div>
      <div class="chat-messages" id="chatMessages">
        <div class="view-loading" style="padding:2rem"><div class="spinner"></div></div>
      </div>
      <div class="e2e-notice">🔒 End-to-end encrypted · Only you and ${UI.escapeHtml(username)} can read these messages</div>
      <div class="chat-input-wrap">
        <textarea class="chat-input" id="chatInput" placeholder="Write a message…" rows="1"></textarea>
        <button class="btn btn-primary" id="sendMsgBtn">Send</button>
      </div>
    `;

    // Auto-resize textarea
    const input = document.getElementById('chatInput');
    input?.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    input?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    document.getElementById('sendMsgBtn')?.addEventListener('click', sendMessage);

    await loadMessages(username);
    startPolling(username);
  }

  async function loadMessages(username) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    try {
      const messages = await API.get(`/messages/${encodeURIComponent(username)}`);
      container.innerHTML = '';
      const currentUser = Auth.getUser();

      for (const msg of messages) {
        const isSent = msg.sender.username === currentUser.username;
        const el = document.createElement('div');
        el.className = `msg-bubble ${isSent ? 'sent' : 'received'} decrypting`;
        el.innerHTML = `<em style="font-size:0.8rem;opacity:0.6">Decrypting…</em>`;
        container.appendChild(el);

        // Async decrypt
        decryptAndShow(el, msg, isSent);
      }

      scrollToBottom(container);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);padding:1rem;font-size:0.875rem">${UI.escapeHtml(e.detail || e.message)}</div>`;
    }
  }

  async function decryptAndShow(el, msg, isSent) {
    try {
      const plain = await CryptoE2E.decryptMessage(
        msg.kyber_ciphertext,
        msg.aes_ciphertext,
        msg.aes_nonce,
      );
      el.classList.remove('decrypting');
      el.innerHTML = `${UI.escapeHtml(plain)}<div class="msg-time">${UI.relativeTime(msg.created_at)}</div>`;
    } catch {
      el.classList.remove('decrypting');
      el.innerHTML = `<em style="opacity:0.5;font-size:0.8rem">⚠ Could not decrypt</em>`;
    }
  }

  async function sendMessage() {
    const input  = document.getElementById('chatInput');
    const btn    = document.getElementById('sendMsgBtn');
    const plain  = input?.value.trim();
    if (!plain || !_activeConv) return;

    btn.disabled = true;

    try {
      // Fetch recipient's public key
      const recipient = await API.get(`/users/${encodeURIComponent(_activeConv)}`);
      if (!recipient.pq_public_key) {
        UI.toast("Recipient hasn't set up encryption keys yet.", 'error');
        return;
      }

      // Encrypt
      const payload = await CryptoE2E.encryptMessage(plain, recipient.pq_public_key);

      await API.post('/messages', {
        recipient_username: _activeConv,
        ...payload,
      });

      // Optimistic UI
      const container = document.getElementById('chatMessages');
      if (container) {
        const el = document.createElement('div');
        el.className = 'msg-bubble sent';
        el.innerHTML = `${UI.escapeHtml(plain)}<div class="msg-time">just now</div>`;
        container.appendChild(el);
        scrollToBottom(container);
      }

      input.value = '';
      input.style.height = 'auto';
    } catch (e) {
      UI.toast(e.detail || 'Message failed to send', 'error');
    } finally {
      btn.disabled = false;
    }
  }

  function scrollToBottom(el) {
    setTimeout(() => { el.scrollTop = el.scrollHeight; }, 50);
  }

  function startPolling(username) {
    stopPolling();
    _pollTimer = setInterval(async () => {
      if (_activeConv === username) await loadMessages(username);
    }, 15000);
  }

  function stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  return { renderView, bindView, stopPolling };
})();
