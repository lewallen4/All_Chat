/**
 * All_Chat — Post Submission Module
 */

const Post = (() => {

  let _imageFile = null;
  let _activeTab = 'text';

  function renderView() {
    return `
      <div class="submit-container">
        <h2 style="margin-bottom:1.25rem;">Create Post</h2>
        <div class="card-elevated">
          <div class="submit-tabs">
            <button class="submit-tab active" data-tab="text">📝 Text</button>
            <button class="submit-tab" data-tab="image">🖼 Image</button>
            <button class="submit-tab" data-tab="link">🔗 Link</button>
          </div>

          <div id="submitError" class="form-error mb-2" style="display:none"></div>

          <div class="form-group">
            <label for="postChannel">Channel <span style="color:var(--text-muted);font-weight:400">(optional)</span></label>
            <select id="postChannel">
              <option value="">— General feed (no channel) —</option>
            </select>
            <span class="form-hint">Post to a specific channel, or leave blank for the general feed</span>
          </div>
          <div class="form-group">
            <label for="postTitle">Title <span style="color:var(--text-muted);font-weight:400">(optional)</span></label>
            <input type="text" id="postTitle" placeholder="A descriptive title…" maxlength="300" />
          </div>

          <!-- Text tab -->
          <div id="tab-text" class="tab-panel">
            <div class="form-group">
              <label for="postBody">Body</label>
              <textarea id="postBody" placeholder="What's on your mind?" rows="6"></textarea>
            </div>
          </div>

          <!-- Image tab -->
          <div id="tab-image" class="tab-panel hidden">
            <div class="form-group">
              <label>Image</label>
              <div class="media-upload-zone" id="uploadZone">
                <div>Drop an image here, or click to browse</div>
                <div style="font-size:0.75rem;margin-top:0.5rem;color:var(--text-muted)">JPEG, PNG, WebP, GIF · Max 10MB</div>
              </div>
              <input type="file" id="imageInput" accept="image/*" style="display:none" />
              <div class="image-preview-wrap hidden" id="imagePreviewWrap">
                <img id="imagePreview" class="image-preview" alt="Preview" />
                <button class="image-remove" id="imageRemove">✕ Remove</button>
              </div>
            </div>
          </div>

          <!-- Link tab -->
          <div id="tab-link" class="tab-panel hidden">
            <div class="form-group">
              <label for="postLink">URL</label>
              <input type="url" id="postLink" placeholder="https://example.com" />
            </div>
            <div id="linkPreviewBox" style="display:none"></div>
          </div>

          <button class="btn btn-primary w-full btn-lg" id="submitPostBtn">Publish Post</button>
        </div>
      </div>
    `;
  }

  function bindView() {
    // Populate channel selector
    _loadChannelOptions();

    // Tabs
    document.querySelectorAll('.submit-tab').forEach(tab => {
      tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Image upload zone
    const zone       = document.getElementById('uploadZone');
    const fileInput  = document.getElementById('imageInput');

    zone?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', e => handleImageFile(e.target.files[0]));

    zone?.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone?.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone?.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      handleImageFile(e.dataTransfer.files[0]);
    });

    document.getElementById('imageRemove')?.addEventListener('click', clearImage);

    // Link preview fetch on blur
    document.getElementById('postLink')?.addEventListener('blur', fetchLinkPreview);

    // Submit
    document.getElementById('submitPostBtn')?.addEventListener('click', submitPost);
  }

  function switchTab(tab) {
    _activeTab = tab;
    document.querySelectorAll('.submit-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    document.getElementById(`tab-${tab}`)?.classList.remove('hidden');
  }

  function handleImageFile(file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      UI.toast('Image must be under 10MB', 'error');
      return;
    }
    _imageFile = file;
    const reader = new FileReader();
    reader.onload = e => {
      const preview = document.getElementById('imagePreview');
      const wrap    = document.getElementById('imagePreviewWrap');
      const zone    = document.getElementById('uploadZone');
      if (preview) preview.src = e.target.result;
      wrap?.classList.remove('hidden');
      zone?.classList.add('hidden');
    };
    reader.readAsDataURL(file);
  }

  function clearImage() {
    _imageFile = null;
    document.getElementById('imagePreviewWrap')?.classList.add('hidden');
    document.getElementById('uploadZone')?.classList.remove('hidden');
    const fi = document.getElementById('imageInput');
    if (fi) fi.value = '';
  }

  async function fetchLinkPreview() {
    const url = document.getElementById('postLink')?.value.trim();
    if (!url || !url.startsWith('http')) return;
    const box = document.getElementById('linkPreviewBox');
    if (!box) return;
    try {
      const preview = await API.get(`/media/preview?url=${encodeURIComponent(url)}`);
      box.style.display = 'block';
      box.innerHTML = `
        <div class="post-link" style="margin-bottom:0.75rem;cursor:default;">
          <span class="post-link-icon">⊕</span>
          <div>
            <div style="font-weight:600;color:var(--text-primary)">${UI.escapeHtml(preview.title || url)}</div>
            ${preview.description ? `<div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.15rem">${UI.escapeHtml(preview.description)}</div>` : ''}
          </div>
        </div>`;
    } catch {
      box.style.display = 'none';
    }
  }

  async function submitPost() {
    const errEl = document.getElementById('submitError');
    const btn   = document.getElementById('submitPostBtn');
    errEl.style.display = 'none';

    const title   = document.getElementById('postTitle')?.value.trim()  || null;
    const body    = document.getElementById('postBody')?.value.trim()   || null;
    const linkUrl = document.getElementById('postLink')?.value.trim()   || null;

    if (!title && !body && !linkUrl && !_imageFile) {
      errEl.textContent = 'Add at least a title, body, image, or link.';
      errEl.style.display = 'block';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Publishing…';

    try {
      const fd = new FormData();
      const channelSlug = document.getElementById('postChannel')?.value;
      if (channelSlug) fd.append('channel_slug', channelSlug);
      if (title)    fd.append('title', title);
      if (body)     fd.append('body', body);
      if (linkUrl)  fd.append('link_url', linkUrl);
      if (_imageFile) fd.append('image', _imageFile);

      await API.form('/posts', fd);
      UI.toast('Post published!', 'success');
      Router.navigate('/');
    } catch (e) {
      errEl.textContent = e.detail || e.message;
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Publish Post';
    }
  }

  async function _loadChannelOptions() {
    const sel = document.getElementById('postChannel');
    if (!sel) return;
    // Check if URL has ?channel= pre-selection
    const params = new URLSearchParams(window.location.search);
    const preSelected = params.get('channel') || '';
    try {
      const data = await API.get('/channels?page=1');
      (data.channels || []).forEach(ch => {
        const opt = document.createElement('option');
        opt.value = ch.slug;
        opt.textContent = `#${ch.slug} — ${ch.name}`;
        if (ch.slug === preSelected) opt.selected = true;
        sel.appendChild(opt);
      });
    } catch {}
  }

  return { renderView, bindView };
})();
