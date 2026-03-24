/**
 * All_Chat — Profile Module
 * Public profile view, own profile editing, avatar upload.
 */

const Profile = (() => {

  // ── Public Profile View ────────────────────────────────────────

  async function renderUserProfile(username) {
    const main = document.getElementById('mainContent');
    main.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';

    try {
      const [user, feedData] = await Promise.all([
        API.get(`/users/${encodeURIComponent(username)}`),
        API.get(`/feed?sort=new&period=all&page=1`),
      ]);

      // Filter posts by this author from the feed
      // (ideally we'd have /api/users/{username}/posts — add that below)
      let posts = [];
      try {
        const res = await API.get(`/search?q=${encodeURIComponent(username)}&page=1`);
        posts = res.posts.filter(p => p.author.username === username);
      } catch {}

      const joinDate = new Date(user.created_at).toLocaleDateString('en-US', {
        month: 'long', day: 'numeric', year: 'numeric'
      });
      const isOwn = Auth.getUser()?.username === username;

      const bio = user.bio_markdown
        ? `<div class="profile-bio">${UI.renderMarkdown(user.bio_markdown)}</div>`
        : `<p class="text-muted" style="font-size:0.875rem">No bio yet.</p>`;

      main.innerHTML = `
        <div style="max-width:720px;margin:0 auto;">
          <div class="profile-header">
            <div class="avatar-wrap">
              ${user.avatar_path
                ? `<img class="avatar" src="${UI.escapeAttr(user.avatar_path)}" alt="Avatar" />`
                : `<div class="avatar-placeholder">${UI.escapeHtml((user.display_name || user.username)[0].toUpperCase())}</div>`}
            </div>
            <div class="profile-info">
              <div class="profile-username">
              ${UI.escapeHtml(user.username)}
              ${user.is_admin ? Channels.adminBadge() : ''}
            </div>
              ${user.display_name ? `<div class="profile-displayname">${UI.escapeHtml(user.display_name)}</div>` : ''}
              <div class="profile-joined">📅 Joined ${joinDate}</div>
              ${bio}
              <div class="flex gap-1 mt-2" style="flex-wrap:wrap;" id="profileActions">
                ${isOwn
                  ? `<button class="btn btn-ghost btn-sm" id="editProfileBtn">✏ Edit Profile</button>
                     <button class="btn btn-ghost btn-sm" id="changeAvatarBtn">🖼 Change Avatar</button>`
                  : `<button class="btn btn-primary btn-sm" id="dmBtn">✉ Message</button>
                     <span id="followBtnWrap"></span>`
                }
              </div>
            </div>
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
            <h3 style="font-size:1rem;color:var(--text-secondary);">Posts by ${UI.escapeHtml(user.username)}</h3>
          </div>
          <div class="feed-list" id="profilePostsList">
            ${posts.length === 0
              ? `<div class="empty-state">
                   <div class="empty-state-icon">📭</div>
                   <h3>No posts yet</h3>
                   ${isOwn ? '<p>Share something with the world!</p>' : ''}
                 </div>`
              : posts.map(p => Feed.createPostCard(p).outerHTML).join('')
            }
          </div>
        </div>
      `;

      // Bind post vote buttons
      document.querySelectorAll('#profilePostsList .vote-btn').forEach(btn => {
        btn.addEventListener('click', () => Feed.castVote(btn.dataset.postId, parseInt(btn.dataset.value)));
      });

      // Load and display channel roles
      _renderChannelRoles(username);

      // DM button
      document.getElementById('dmBtn')?.addEventListener('click', () => {
        Router.navigate('/messages');
        setTimeout(() => Messages.openConversation?.(username), 100);
      });

      // Follow button
      if (!isOwn) {
        Social.renderFollowBtn(username, 'followBtnWrap');
      }

      // Edit profile
      document.getElementById('editProfileBtn')?.addEventListener('click', showEditModal);
      document.getElementById('changeAvatarBtn')?.addEventListener('click', showAvatarModal);

      // Comments section — append below posts
      const commentsSection = document.createElement('div');
      commentsSection.style.marginTop = '2rem';
      commentsSection.innerHTML = `
        <h3 style="font-family:'Syne',sans-serif;font-size:1rem;color:var(--text-secondary);margin-bottom:1rem;">
          Comments
        </h3>
        <div id="profileComments"></div>
      `;
      main.querySelector('div').appendChild(commentsSection);

    } catch (e) {
      main.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">⚠</div>
        <h3>${e.status === 404 ? 'User not found' : 'Something went wrong'}</h3>
        <p>${UI.escapeHtml(e.detail || e.message)}</p>
      </div>`;
    }
  }

  // ── Own Profile (redirect to /u/username) ─────────────────────

  async function renderOwnProfile() {
    const user = Auth.getUser();
    if (!user) { Router.navigate('/login'); return; }
    await renderUserProfile(user.username);
  }

  // ── Edit Modal ─────────────────────────────────────────────────

  function showEditModal() {
    const user = Auth.getUser();
    UI.openModal(`
      <h3 style="margin-bottom:1.25rem">Edit Profile</h3>
      <div id="editProfileError" class="form-error mb-2" style="display:none"></div>
      <div class="form-group">
        <label for="editDisplayName">Display Name</label>
        <input type="text" id="editDisplayName"
               value="${UI.escapeAttr(user.display_name || '')}"
               maxlength="64" placeholder="Your display name" />
      </div>
      <div class="form-group">
        <label for="editBio">Bio <span style="color:var(--text-muted);font-weight:400">(Markdown supported)</span></label>
        <textarea id="editBio" rows="6" maxlength="5000"
                  placeholder="Tell the world about yourself…">${UI.escapeHtml(user.bio_markdown || '')}</textarea>
        <span class="form-hint">Max 5,000 characters · Markdown formatting supported</span>
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end">
        <button class="btn btn-ghost" id="editCancelBtn">Cancel</button>
        <button class="btn btn-primary" id="editSaveBtn">Save Changes</button>
      </div>
    `);

    document.getElementById('editCancelBtn')?.addEventListener('click', UI.closeModal);
    document.getElementById('editSaveBtn')?.addEventListener('click', async () => {
      const errEl = document.getElementById('editProfileError');
      const btn   = document.getElementById('editSaveBtn');
      errEl.style.display = 'none';
      btn.disabled = true; btn.textContent = 'Saving…';
      try {
        const updated = await API.patch('/users/me/profile', {
          display_name: document.getElementById('editDisplayName').value.trim() || null,
          bio_markdown: document.getElementById('editBio').value.trim() || null,
        });
        Auth.setUser(updated);
        UI.updateNavAuth();
        UI.closeModal();
        UI.toast('Profile updated!', 'success');
        await renderOwnProfile();
      } catch (e) {
        errEl.textContent = e.detail || e.message;
        errEl.style.display = 'block';
      } finally {
        btn.disabled = false; btn.textContent = 'Save Changes';
      }
    });
  }

  // ── Avatar Modal ───────────────────────────────────────────────

  function showAvatarModal() {
    UI.openModal(`
      <h3 style="margin-bottom:1.25rem">Change Avatar</h3>
      <div id="avatarError" class="form-error mb-2" style="display:none"></div>
      <div class="media-upload-zone" id="avatarUploadZone">
        <div>Drop an image or click to browse</div>
        <div style="font-size:0.75rem;margin-top:0.5rem;color:var(--text-muted)">Max 5MB · Will be resized to 100×100px</div>
      </div>
      <input type="file" id="avatarFileInput" accept="image/*" style="display:none" />
      <div id="avatarPreviewWrap" style="display:none;text-align:center;margin:0.75rem 0">
        <img id="avatarPreview" style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid var(--border)" alt="Preview" />
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-top:1rem">
        <button class="btn btn-danger btn-sm" id="removeAvatarBtn">Remove Avatar</button>
        <button class="btn btn-ghost" id="avatarCancelBtn">Cancel</button>
        <button class="btn btn-primary" id="avatarSaveBtn" disabled>Upload</button>
      </div>
    `);

    let _file = null;
    const zone  = document.getElementById('avatarUploadZone');
    const fi    = document.getElementById('avatarFileInput');
    const save  = document.getElementById('avatarSaveBtn');

    zone?.addEventListener('click', () => fi?.click());
    zone?.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone?.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone?.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('dragover'); handleFile(e.dataTransfer.files[0]); });
    fi?.addEventListener('change', e => handleFile(e.target.files[0]));

    function handleFile(file) {
      if (!file) return;
      _file = file;
      const reader = new FileReader();
      reader.onload = e => {
        document.getElementById('avatarPreview').src = e.target.result;
        document.getElementById('avatarPreviewWrap').style.display = 'block';
        save.disabled = false;
      };
      reader.readAsDataURL(file);
    }

    document.getElementById('avatarCancelBtn')?.addEventListener('click', UI.closeModal);

    document.getElementById('removeAvatarBtn')?.addEventListener('click', async () => {
      try {
        await API.delete('/users/me/avatar');
        const user = Auth.getUser();
        if (user) { user.avatar_path = null; Auth.setUser(user); }
        UI.updateNavAuth();
        UI.closeModal();
        UI.toast('Avatar removed', 'success');
        await renderOwnProfile();
      } catch (e) { UI.toast(e.detail || 'Failed to remove avatar', 'error'); }
    });

    save?.addEventListener('click', async () => {
      if (!_file) return;
      const errEl = document.getElementById('avatarError');
      save.disabled = true; save.textContent = 'Uploading…';
      try {
        const fd = new FormData();
        fd.append('file', _file);
        await API.form('/users/me/avatar', fd);
        const updated = await API.get('/users/me');
        Auth.setUser(updated);
        UI.updateNavAuth();
        UI.closeModal();
        UI.toast('Avatar updated!', 'success');
        await renderOwnProfile();
      } catch (e) {
        errEl.textContent = e.detail || e.message;
        errEl.style.display = 'block';
        save.disabled = false; save.textContent = 'Upload';
      }
    });
  }

  async function _renderChannelRoles(username) {
    try {
      const roles = await API.get(`/channels/user/${encodeURIComponent(username)}/roles`);
      if (!roles || roles.length === 0) return;

      // Find bio element and insert roles after it
      const bioEl = document.querySelector('.profile-bio') ||
                    document.querySelector('.profile-joined');
      if (!bioEl) return;

      const rolesWrap = document.createElement('div');
      rolesWrap.style.marginTop = '0.75rem';
      rolesWrap.innerHTML = `
        <div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;
          letter-spacing:0.06em;color:var(--text-muted);margin-bottom:0.4rem;">
          Channel Roles
        </div>
        <div class="profile-roles">
          ${roles.map(r => `
            <a class="profile-role-chip ${r.role === 'chief_lead' ? 'chief' : 'lead'}"
              href="/c/${UI.escapeAttr(r.channel_slug)}"
              data-route="/c/${UI.escapeAttr(r.channel_slug)}">
              ${r.role === 'chief_lead' ? '👑' : '🛡'}
              #${UI.escapeHtml(r.channel_slug)}
              <span class="chip-role">${r.role === 'chief_lead' ? 'Chief Lead' : (r.title || 'Lead')}</span>
            </a>`).join('')}
        </div>`;
      bioEl.parentNode.insertBefore(rolesWrap, bioEl.nextSibling);

    } catch {}
  }

  return { renderUserProfile, renderOwnProfile };
})();
