(function () {
  const TEXT_FILE_EXTENSIONS = [
    '.txt',
    '.md',
    '.markdown',
    '.json',
    '.csv',
    '.tsv',
    '.log'
  ];
  let spaces = [];
  let activeSpaceId = null;
  let openItemMenuId = null;
  let openItemMovePickerId = null;
  let isSpaceMoreMenuOpen = false;
  let editingSpaceField = '';
  let editingSpaceDraft = '';
  let previewItemId = '';
  let propertiesItemId = '';
  let contentMode = 'upload';

  let entryMediaRecorder = null;
  let entryMediaStream = null;
  let entryRecordChunks = [];
  let entryRecordedBlob = null;
  let entryRecordedMime = '';
  let entryRecordedAudioUrl = '';
  let pdfJsLoader = null;
  let previewRenderToken = 0;

  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }

  function getUserDisplayName() {
    if (window.UserContext && typeof window.UserContext.getDisplayName === 'function') {
      return window.UserContext.getDisplayName();
    }
    return getUserId();
  }

  function getUserLabel() {
    if (window.UserContext && typeof window.UserContext.getUserLabel === 'function') {
      return window.UserContext.getUserLabel();
    }
    return getUserId();
  }

  function getSpaceApi() {
    return window.SpaceCloudStore || null;
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function nowLabel(date) {
    const d = date ? new Date(date) : new Date();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  }

  function relativeTimeLabel(value) {
    const time = Number(value || 0);
    if (!time) return '--';
    const delta = Math.max(0, Date.now() - time);
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;

    if (delta < minute) return '刚刚';
    if (delta < hour) return `${Math.max(1, Math.round(delta / minute))} 分钟前`;
    if (delta < day) return `${Math.max(1, Math.round(delta / hour))} 小时前`;
    return `${Math.max(1, Math.round(delta / day))} 天前`;
  }

  function getActiveSpace() {
    return spaces.find(function (space) {
      return space.id === activeSpaceId;
    }) || null;
  }

  function getItemById(space, itemId) {
    const items = space && Array.isArray(space.items) ? space.items : [];
    return items.find(function (item) {
      return item.id === itemId;
    }) || null;
  }

  function getActivePreviewItem() {
    return getItemById(getActiveSpace(), previewItemId);
  }

  function getActivePropertiesItem() {
    return getItemById(getActiveSpace(), propertiesItemId);
  }

  function formatFileSize(bytes) {
    const value = Math.max(0, Number(bytes) || 0);
    if (value >= 1024 * 1024) {
      return `${(value / (1024 * 1024)).toFixed(value >= 20 * 1024 * 1024 ? 0 : 1)} MB`;
    }
    if (value >= 1024) {
      return `${Math.max(1, Math.round(value / 1024))} KB`;
    }
    return `${value} B`;
  }

  function formatDateTimeLabel(value) {
    const time = Number(value || 0);
    if (!time) return '--';
    return new Date(time).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function syncModalBodyState() {
    const hasOpenModal = ['contentModal', 'itemPropertiesModal'].some(function (id) {
      const element = document.getElementById(id);
      return !!(element && element.classList.contains('show'));
    });
    document.body.classList.toggle('space-modal-open', hasOpenModal);
  }

  function ensureState() {
    if (!spaces.length) {
      clearPreviewSelection();
      activeSpaceId = null;
      openItemMenuId = null;
      openItemMovePickerId = null;
      previewItemId = '';
      propertiesItemId = '';
      return;
    }

    if (!spaces.find(function (space) { return space.id === activeSpaceId; })) {
      activeSpaceId = spaces[0].id;
    }

    const activeSpace = getActiveSpace();
    const items = activeSpace && Array.isArray(activeSpace.items) ? activeSpace.items : [];

    if (openItemMenuId && !items.find(function (item) { return item.id === openItemMenuId; })) {
      openItemMenuId = null;
      openItemMovePickerId = null;
    }

    if (previewItemId && !items.find(function (item) { return item.id === previewItemId; })) {
      clearPreviewSelection();
    }

    if (propertiesItemId && !items.find(function (item) { return item.id === propertiesItemId; })) {
      closePropertiesModal();
    }
  }

  function replaceSpace(space) {
    if (!space || !space.id) return;
    spaces = [space].concat(spaces.filter(function (item) {
      return item.id !== space.id;
    }));
    ensureState();
  }

  function removeSpace(spaceId) {
    spaces = spaces.filter(function (space) {
      return space.id !== spaceId;
    });
    ensureState();
  }

  function applyQueryDefaultSpace() {
    const params = new URLSearchParams(window.location.search || '');
    const sid = String(params.get('space_id') || '').trim();
    if (!sid) return;
    if (spaces.find(function (space) { return space.id === sid; })) {
      activeSpaceId = sid;
    }
  }

  function applyQueryPreviewItem() {
    const params = new URLSearchParams(window.location.search || '');
    previewItemId = String(params.get('item_id') || '').trim();
  }

  function hasCreateSpaceQuery() {
    const params = new URLSearchParams(window.location.search || '');
    const raw = String(params.get('create_space') || '').trim().toLowerCase();
    return raw === '1' || raw === 'true' || raw === 'yes';
  }

  function clearCreateSpaceQuery() {
    const url = new URL(window.location.href);
    url.searchParams.delete('create_space');
    if (window.history && typeof window.history.replaceState === 'function') {
      window.history.replaceState({}, '', `${url.pathname}${url.search}`);
    }
  }

  function buildSpacesPageUrl(spaceId, itemId) {
    const url = new URL(window.location.href);
    url.searchParams.delete('space_id');
    url.searchParams.delete('item_id');
    if (spaceId) {
      url.searchParams.set('space_id', spaceId);
    }
    if (itemId) {
      url.searchParams.set('item_id', itemId);
    }
    return `${url.pathname}${url.search}`;
  }

  function syncSpacesPageUrl() {
    if (!window.history || typeof window.history.replaceState !== 'function') return;
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    const nextUrl = buildSpacesPageUrl(activeSpaceId || '', previewItemId || '');
    if (currentUrl === nextUrl) return;
    window.history.replaceState({}, '', nextUrl);
  }

  function clearPreviewSelection() {
    if (!previewItemId) return;
    previewItemId = '';
    if (window.history && typeof window.history.replaceState === 'function') {
      window.history.replaceState({}, '', buildSpacesPageUrl(activeSpaceId || ''));
    }
  }

  function navigateToPreviewPage(itemId) {
    const activeSpace = getActiveSpace();
    const targetItem = getItemById(activeSpace, itemId);
    if (!activeSpace || !targetItem) return;
    window.location.href = buildSpacesPageUrl(activeSpace.id, itemId);
  }

  function exitPreviewPage() {
    window.location.href = buildSpacesPageUrl(activeSpaceId || '');
  }

  async function loadSpaces() {
    const api = getSpaceApi();
    if (!api || typeof api.listSpaces !== 'function') {
      spaces = [];
      activeSpaceId = null;
      return;
    }

    const data = await api.listSpaces(getUserId());
    spaces = Array.isArray(data.spaces) ? data.spaces : [];
    if (data.activeEntrySpaceId && spaces.find(function (space) { return space.id === data.activeEntrySpaceId; })) {
      activeSpaceId = data.activeEntrySpaceId;
    }
    applyQueryDefaultSpace();
    applyQueryPreviewItem();
    ensureState();
  }

  function getSpaceTitle() {
    const space = getActiveSpace();
    return space ? String(space.name || '未命名空间') : '我的空间';
  }

  function syncDocumentTitle() {
    const previewItem = getActivePreviewItem();
    if (previewItem) {
      const itemName = String(previewItem.name || '文档预览').trim() || '文档预览';
      document.title = `${itemName} - ${getSpaceTitle()}`;
      return;
    }
    document.title = getActiveSpace()
      ? `${getSpaceTitle()} - 空间`
      : '我的空间';
  }

  function syncHeader() {
    const topSpaceName = document.getElementById('topSpaceName');
    const userLabel = document.getElementById('spaceUserLabel');
    const activeSpace = getActiveSpace();

    if (topSpaceName) {
      topSpaceName.textContent = activeSpace ? (activeSpace.name || '未命名空间') : '我的空间';
    }
    if (userLabel) {
      userLabel.textContent = `用户：${getUserLabel()}`;
    }
    syncDocumentTitle();
  }

  function renderEditableField(type, value, placeholder) {
    const isEditing = editingSpaceField === type;
    const safeValue = String(value || '');
    if (isEditing) {
      const maxLength = type === 'name' ? 40 : 120;
      const inputClass = type === 'name' ? 'space-name-input' : 'space-description-input';
      const tag = type === 'name' ? 'input' : 'textarea';
      const extra = type === 'name'
        ? `type="text" value="${esc(editingSpaceDraft)}"`
        : '';
      const body = tag === 'input'
        ? `<input id="spaceFieldEditor" class="${inputClass}" data-space-field="${type}" maxlength="${maxLength}" spellcheck="false" ${extra}>`
        : `<textarea id="spaceFieldEditor" class="${inputClass}" data-space-field="${type}" maxlength="${maxLength}" spellcheck="false">${esc(editingSpaceDraft)}</textarea>`;
      return `<div class="editable-shell is-editing">${body}<div class="editable-hint">按 Enter 保存，Esc 取消</div></div>`;
    }

    const emptyClass = safeValue ? '' : ' is-empty';
    const text = safeValue || placeholder;
    return `<div class="editable-shell"><button type="button" class="editable-trigger${emptyClass}" data-space-field-start="${type}" title="双击修改">${esc(text)}</button></div>`;
  }

  function renderHero() {
    const hero = document.getElementById('spaceHero');
    const titleWrap = document.getElementById('spaceTitleWrap');
    const descriptionWrap = document.getElementById('spaceDescriptionWrap');
    const addBtn = document.getElementById('addContentBtn');
    const moreBtn = document.getElementById('spaceMoreBtn');
    const activeSpace = getActiveSpace();
    const emptyState = document.getElementById('spaceEmptyState');
    const table = document.getElementById('spaceTable');

    if (!hero || !titleWrap || !descriptionWrap || !emptyState || !table) return;

    if (!activeSpace) {
      hero.hidden = true;
      table.hidden = true;
      emptyState.hidden = false;
      if (addBtn) addBtn.disabled = true;
      if (moreBtn) moreBtn.disabled = true;
      return;
    }

    hero.hidden = false;
    table.hidden = false;
    emptyState.hidden = true;
    if (addBtn) addBtn.disabled = false;
    if (moreBtn) moreBtn.disabled = false;

    titleWrap.innerHTML = renderEditableField('name', activeSpace.name || '', '未命名空间');
    descriptionWrap.innerHTML = renderEditableField('description', activeSpace.description || '', '无说明');

    titleWrap.querySelectorAll('[data-space-field-start]').forEach(function (btn) {
      btn.addEventListener('dblclick', function () {
        startEditingSpaceField('name');
      });
    });

    descriptionWrap.querySelectorAll('[data-space-field-start]').forEach(function (btn) {
      btn.addEventListener('dblclick', function () {
        startEditingSpaceField('description');
      });
    });

    bindSpaceFieldEditor();
  }

  function getItemKindLabel(item) {
    const kind = String((item && item.kind) || 'document').toLowerCase();
    if (kind === 'folder') return '文件夹';
    if (kind === 'note') return '笔记';
    if (kind === 'link') return '链接';
    if (kind === 'image') return '图片';
    if (kind === 'audio') return '音频';
    if (kind === 'video') return '视频';
    if (kind === 'pdf') return 'PDF';
    return '文件';
  }

  function getItemIconHtml(item) {
    const kind = String((item && item.kind) || 'document').toLowerCase();
    if (kind === 'folder') {
      return '<svg viewBox="0 0 24 24" fill="none"><path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h4l2 2h6A2.5 2.5 0 0 1 20.5 9.5v7A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5v-9Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';
    }
    if (kind === 'link') {
      return '<svg viewBox="0 0 24 24" fill="none"><path d="M10 13.5 14 9.5M8.25 15.25l-1.75 1.75a3.18 3.18 0 1 1-4.5-4.5l3.25-3.25a3.18 3.18 0 0 1 4.5 0M15.75 8.75l1.75-1.75a3.18 3.18 0 1 1 4.5 4.5l-3.25 3.25a3.18 3.18 0 0 1-4.5 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
    if (kind === 'image') {
      return '<svg viewBox="0 0 24 24" fill="none"><rect x="3.5" y="5" width="17" height="14" rx="2.5" stroke="currentColor" stroke-width="1.8"/><path d="m7 15 3-3 2.25 2.25L15.5 11l2.5 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="8.5" cy="9" r="1.25" fill="currentColor"/></svg>';
    }
    if (kind === 'audio') {
      return '<svg viewBox="0 0 24 24" fill="none"><path d="M12 4v16M8 8v8M16 8v8M4.5 10.5v3M19.5 10.5v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    }
    if (kind === 'video') {
      return '<svg viewBox="0 0 24 24" fill="none"><rect x="3.5" y="5.5" width="12" height="13" rx="2.5" stroke="currentColor" stroke-width="1.8"/><path d="m15.5 10 5-2.5v9L15.5 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
    if (kind === 'pdf') {
      return '<svg viewBox="0 0 24 24" fill="none"><path d="M7 3.5h7l4 4v13A1.5 1.5 0 0 1 16.5 22h-9A1.5 1.5 0 0 1 6 20.5v-15A2 2 0 0 1 8 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3.5v4h4" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" fill="none"><path d="M7 3.5h7l4 4v13A1.5 1.5 0 0 1 16.5 22h-9A1.5 1.5 0 0 1 6 20.5v-15A2 2 0 0 1 8 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3.5v4h4M9 13h6M9 16h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  function renderItemList() {
    const list = document.getElementById('spaceItemList');
    const count = document.getElementById('spaceItemCount');
    const activeSpace = getActiveSpace();
    if (!list || !count) return;

    if (!activeSpace) {
      count.textContent = '0';
      list.innerHTML = '';
      return;
    }

    const items = Array.isArray(activeSpace.items) ? activeSpace.items.slice() : [];
    count.textContent = String(items.length);

    if (!items.length) {
      list.innerHTML = `
        <div class="space-list-empty">
          <div class="space-list-empty-title">这个空间还没有内容</div>
          <div class="space-list-empty-subtitle">点击右上角“添加内容”，或使用更多菜单创建文件夹。</div>
        </div>
      `;
      return;
    }

    list.innerHTML = items.map(function (item) {
      const moveOpen = openItemMovePickerId === item.id ? ' is-open' : '';
      const menuOpen = openItemMenuId === item.id ? ' is-open' : '';
      const otherSpaces = spaces.filter(function (space) { return space.id !== activeSpace.id; });
      const moveListHtml = otherSpaces.length
        ? otherSpaces.map(function (space) {
            return `<button type="button" class="item-move-target" data-item-move-target="${esc(space.id)}" data-item-id="${esc(item.id)}">${esc(space.name || '未命名空间')}</button>`;
          }).join('')
        : '<div class="item-move-empty">暂无其他空间</div>';

      return `
        <div class="space-row${menuOpen}" data-space-row="${esc(item.id)}">
          <button type="button" class="space-row-main" data-item-open="${esc(item.id)}">
            <span class="space-row-main-left">
              <span class="space-row-icon">${getItemIconHtml(item)}</span>
              <span class="space-row-name">${esc(item.name || '未命名文件')}</span>
            </span>
            <span class="space-row-main-right">
              <span class="space-row-added">${esc(relativeTimeLabel(item.addedAt))}</span>
            </span>
          </button>
          <div class="space-row-actions">
            <button
              type="button"
              class="space-row-menu-btn"
              data-item-menu-toggle="${esc(item.id)}"
              aria-label="文件操作"
              aria-haspopup="menu"
              aria-expanded="${openItemMenuId === item.id ? 'true' : 'false'}"
            >
              <span></span><span></span><span></span>
            </button>
            <div class="item-menu${menuOpen}" data-item-menu="${esc(item.id)}" role="menu">
              <button type="button" class="item-menu-btn" data-item-action="properties" data-item-id="${esc(item.id)}">
                <span class="item-menu-icon"><svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.6"/><path d="M10 8v4M10 6.25h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>
                <span>属性</span>
              </button>
              <button type="button" class="item-menu-btn" data-item-action="rename" data-item-id="${esc(item.id)}">
                <span class="item-menu-icon"><svg viewBox="0 0 20 20" fill="none"><path d="m4 14 8.5-8.5 3 3L7 17H4v-3Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="m11.75 5.25 1.5-1.5a1.77 1.77 0 1 1 2.5 2.5l-1.5 1.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
                <span>Rename</span>
              </button>
              <button type="button" class="item-menu-btn has-arrow" data-item-action="move-toggle" data-item-id="${esc(item.id)}">
                <span class="item-menu-icon"><svg viewBox="0 0 20 20" fill="none"><path d="M9 3.5 4.5 8 9 12.5M5 8h8.75a2.75 2.75 0 1 1 0 5.5H12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
                <span>移动到空间</span>
                <span class="item-menu-arrow">›</span>
              </button>
              <div class="item-move-panel${moveOpen}">
                ${moveListHtml}
              </div>
              <button type="button" class="item-menu-btn danger" data-item-action="delete" data-item-id="${esc(item.id)}">
                <span class="item-menu-icon"><svg viewBox="0 0 20 20" fill="none"><path d="M4.75 6h10.5M8 6V4.75A1.25 1.25 0 0 1 9.25 3.5h1.5A1.25 1.25 0 0 1 12 4.75V6M6.5 6l.6 8.05A1.5 1.5 0 0 0 8.6 15.5h2.8a1.5 1.5 0 0 0 1.5-1.45L13.5 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-item-open]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        navigateToPreviewPage(this.getAttribute('data-item-open'));
      });
    });

    list.querySelectorAll('[data-item-menu-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        const itemId = this.getAttribute('data-item-menu-toggle');
        const isSame = openItemMenuId === itemId;
        openItemMenuId = isSame ? null : itemId;
        openItemMovePickerId = null;
        renderItemList();
      });
    });

    list.querySelectorAll('[data-item-action]').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        const itemId = this.getAttribute('data-item-id');
        const action = this.getAttribute('data-item-action');
        if (action === 'properties') {
          openPropertiesModal(itemId);
          return;
        }
        if (action === 'rename') {
          renameItem(itemId);
          return;
        }
        if (action === 'move-toggle') {
          openItemMovePickerId = openItemMovePickerId === itemId ? null : itemId;
          renderItemList();
          return;
        }
        if (action === 'delete') {
          deleteItem(itemId);
        }
      });
    });

    list.querySelectorAll('[data-item-move-target]').forEach(function (btn) {
      btn.addEventListener('click', function (event) {
        event.stopPropagation();
        moveItemToSpace(
          this.getAttribute('data-item-id'),
          this.getAttribute('data-item-move-target')
        );
      });
    });
  }

  function renderSpaceMoreMenu() {
    const menu = document.getElementById('spaceMoreMenu');
    const btn = document.getElementById('spaceMoreBtn');
    const activeSpace = getActiveSpace();
    if (!menu || !btn) return;
    menu.classList.toggle('show', isSpaceMoreMenuOpen && !!activeSpace);
    btn.setAttribute('aria-expanded', isSpaceMoreMenuOpen ? 'true' : 'false');
  }

  function renderPreviewModal() {
    const page = document.getElementById('spacePage');
    const reader = document.getElementById('spaceReader');
    const title = document.getElementById('spaceReaderFileName');
    const body = document.getElementById('spaceReaderBody');
    const backBtn = document.getElementById('spaceReaderBackBtn');
    const item = getActivePreviewItem();
    const activeSpace = getActiveSpace();
    if (page) page.hidden = !!item;
    if (reader) reader.hidden = !item;
    document.body.classList.toggle('space-reader-mode', !!item);
    if (!item) {
      previewRenderToken += 1;
    }
    if (!reader || !title || !body || !item) return;

    const renderToken = ++previewRenderToken;
    title.textContent = item.name || '未命名文件';
    if (backBtn) {
      backBtn.textContent = activeSpace ? `返回 ${activeSpace.name || '空间'}` : '返回空间';
    }

    const previewUrl = getReaderPreviewUrl(item);
    const mime = String(item.mime || '').toLowerCase();
    const kind = String(item.kind || 'document').toLowerCase();

    if (kind === 'folder') {
      body.innerHTML = '<div class="space-reader-document"><div class="space-reader-note">当前为文件夹占位项，可返回空间继续添加真实内容。</div></div>';
      return;
    }

    if ((kind === 'audio' || mime.startsWith('audio/')) && previewUrl) {
      body.innerHTML = `
        <div class="space-reader-document">
          <div class="space-reader-media">
            <audio controls src="${esc(previewUrl)}"></audio>
          </div>
        </div>
      `;
      return;
    }

    if ((kind === 'video' || mime.startsWith('video/')) && previewUrl) {
      body.innerHTML = `
        <div class="space-reader-document">
          <div class="space-reader-media">
            <video controls src="${esc(previewUrl)}"></video>
          </div>
        </div>
      `;
      return;
    }

    if (mime.startsWith('image/') && previewUrl) {
      body.innerHTML = `
        <div class="space-reader-document">
          <div class="space-reader-media">
            <img alt="预览" src="${esc(previewUrl)}">
          </div>
        </div>
      `;
      return;
    }

    if ((kind === 'pdf' || mime.includes('pdf')) && previewUrl) {
      renderPdfDocument(item, body, renderToken);
      return;
    }

    if (item.content) {
      body.innerHTML = `
        <div class="space-reader-document is-text">
          <pre>${esc(item.content)}</pre>
        </div>
      `;
      return;
    }

    if (previewUrl) {
      body.innerHTML = `
        <div class="space-reader-document">
          <iframe class="space-reader-frame" title="文件预览" src="${esc(previewUrl)}"></iframe>
        </div>
      `;
      return;
    }

    body.innerHTML = '<div class="space-reader-document"><div class="space-reader-note">当前内容暂无可预览的文档视图。</div></div>';
  }

  function getReaderPreviewUrl(item) {
    const previewUrl = String(item && item.previewUrl || '').trim();
    if (!previewUrl) return '';
    const isPdf = String(item && item.kind || '').toLowerCase() === 'pdf'
      || String(item && item.mime || '').toLowerCase().includes('pdf');
    if (!isPdf) return previewUrl;
    return `${previewUrl}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`;
  }

  function getRawPreviewUrl(item) {
    return String(item && item.previewUrl || '').trim();
  }

  function buildPdfFallbackHtml(item) {
    const previewUrl = getReaderPreviewUrl(item);
    if (!previewUrl) {
      return '<div class="space-reader-document"><div class="space-reader-note">当前内容暂无可预览的文档视图。</div></div>';
    }
    return `
      <div class="space-reader-document">
        <iframe class="space-reader-frame" title="PDF预览" src="${esc(previewUrl)}"></iframe>
      </div>
    `;
  }

  function ensurePdfJs() {
    if (window.pdfjsLib) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
      return Promise.resolve(window.pdfjsLib);
    }

    if (pdfJsLoader) {
      return pdfJsLoader;
    }

    pdfJsLoader = new Promise(function (resolve, reject) {
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
      script.async = true;
      script.onload = function () {
        if (!window.pdfjsLib) {
          pdfJsLoader = null;
          reject(new Error('PDF.js unavailable'));
          return;
        }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        resolve(window.pdfjsLib);
      };
      script.onerror = function () {
        pdfJsLoader = null;
        reject(new Error('PDF.js load failed'));
      };
      document.head.appendChild(script);
    });

    return pdfJsLoader;
  }

  async function renderPdfDocument(item, host, renderToken) {
    const previewUrl = getRawPreviewUrl(item);
    if (!host || !previewUrl) {
      return;
    }

    host.innerHTML = '<div class="space-reader-document is-pdf"><div class="space-reader-loading">正在加载文档...</div></div>';

    try {
      const pdfjsLib = await ensurePdfJs();
      if (renderToken !== previewRenderToken) return;

      const loadingTask = pdfjsLib.getDocument({ url: previewUrl });
      const pdf = await loadingTask.promise;
      if (renderToken !== previewRenderToken) return;

      host.innerHTML = '<div class="space-reader-document is-pdf"><div class="space-reader-pdf"></div></div>';
      const pagesWrap = host.querySelector('.space-reader-pdf');
      if (!pagesWrap) return;

      const deviceScale = window.devicePixelRatio || 1;

      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        if (renderToken !== previewRenderToken) return;

        const page = await pdf.getPage(pageNumber);
        if (renderToken !== previewRenderToken) return;

        const pageWrap = document.createElement('div');
        pageWrap.className = 'space-reader-pdf-page';
        const canvas = document.createElement('canvas');
        pageWrap.appendChild(canvas);
        pagesWrap.appendChild(pageWrap);

        const baseViewport = page.getViewport({ scale: 1 });
        const availableWidth = Math.max(320, pagesWrap.clientWidth - 32);
        const scale = Math.max(0.8, Math.min(2.6, availableWidth / baseViewport.width));
        const viewport = page.getViewport({ scale: scale });
        const context = canvas.getContext('2d');

        canvas.width = Math.floor(viewport.width * deviceScale);
        canvas.height = Math.floor(viewport.height * deviceScale);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        await page.render({
          canvasContext: context,
          viewport: viewport,
          transform: deviceScale === 1 ? null : [deviceScale, 0, 0, deviceScale, 0, 0]
        }).promise;
      }
    } catch (error) {
      if (renderToken !== previewRenderToken) return;
      host.innerHTML = buildPdfFallbackHtml(item);
    }
  }

  function replaceItemInActiveSpace(nextItem) {
    const activeSpace = getActiveSpace();
    if (!activeSpace || !Array.isArray(activeSpace.items) || !nextItem || !nextItem.id) return;
    activeSpace.items = [nextItem].concat(activeSpace.items.filter(function (item) {
      return item.id !== nextItem.id;
    }));
  }

  async function loadItemIntoActiveSpace(itemId) {
    const api = getSpaceApi();
    if (!itemId || !api || typeof api.getItem !== 'function') return null;
    try {
      const result = await api.getItem(getUserId(), itemId);
      if (result && result.item) {
        replaceItemInActiveSpace(result.item);
        return result.item;
      }
    } catch (error) {
      // use cached item
    }
    return null;
  }

  function renderPropertiesModal() {
    const modal = document.getElementById('itemPropertiesModal');
    const title = document.getElementById('itemPropertiesTitle');
    const meta = document.getElementById('itemPropertiesMeta');
    const grid = document.getElementById('itemPropertiesGrid');
    const summary = document.getElementById('itemPropertiesSummary');
    const item = getActivePropertiesItem();
    const activeSpace = getActiveSpace();
    if (!modal || !title || !meta || !grid || !summary || !item) return;

    title.textContent = item.name || '未命名文件';
    meta.textContent = `${activeSpace ? (activeSpace.name || '当前空间') : '当前空间'} · ${getItemKindLabel(item)}`;

    const rows = [
      { label: '类型', value: getItemKindLabel(item) },
      { label: 'MIME', value: String(item.mime || '').trim() || '--' },
      { label: '大小', value: formatFileSize(item.size) },
      { label: '来源', value: String(item.source || '').trim() || '--' },
      { label: '添加时间', value: formatDateTimeLabel(item.addedAt) },
      { label: '更新时间', value: formatDateTimeLabel(item.updatedAt || item.addedAt) }
    ];

    grid.innerHTML = rows.map(function (row) {
      return `
        <div class="item-properties-row">
          <div class="item-properties-label">${esc(row.label)}</div>
          <div class="item-properties-value">${esc(row.value)}</div>
        </div>
      `;
    }).join('');

    const summaryText = String(item.summary || '').trim();
    summary.hidden = !summaryText;
    summary.textContent = summaryText;

    modal.classList.add('show');
    syncModalBodyState();
  }

  function closePropertiesModal() {
    const modal = document.getElementById('itemPropertiesModal');
    if (modal) modal.classList.remove('show');
    propertiesItemId = '';
    syncModalBodyState();
  }

  async function openPropertiesModal(itemId) {
    const api = getSpaceApi();
    const activeSpace = getActiveSpace();
    if (!activeSpace) return;
    const currentItem = getItemById(activeSpace, itemId);
    if (!currentItem) return;

    openItemMenuId = null;
    openItemMovePickerId = null;
    renderItemList();
    clearPreviewSelection();
    propertiesItemId = itemId;

    if (!api || typeof api.getItem !== 'function') {
      renderPropertiesModal();
      return;
    }

    await loadItemIntoActiveSpace(itemId);
    renderPropertiesModal();
  }

  function render() {
    syncSpacesPageUrl();
    syncHeader();
    renderHero();
    renderItemList();
    renderSpaceMoreMenu();
    if (previewItemId) {
      renderPreviewModal();
    } else {
      const page = document.getElementById('spacePage');
      const reader = document.getElementById('spaceReader');
      if (page) page.hidden = false;
      if (reader) reader.hidden = true;
      document.body.classList.remove('space-reader-mode');
    }
    if (propertiesItemId) {
      renderPropertiesModal();
    }
  }

  function focusSpaceFieldEditor() {
    const editor = document.getElementById('spaceFieldEditor');
    if (!editor) return;
    editor.focus();
    if (typeof editor.select === 'function') {
      editor.select();
    }
  }

  function startEditingSpaceField(field) {
    const activeSpace = getActiveSpace();
    if (!activeSpace) return;
    editingSpaceField = field;
    editingSpaceDraft = field === 'name'
      ? String(activeSpace.name || '')
      : String(activeSpace.description || '');
    renderHero();
    window.requestAnimationFrame(focusSpaceFieldEditor);
  }

  function cancelEditingSpaceField() {
    editingSpaceField = '';
    editingSpaceDraft = '';
    renderHero();
  }

  async function submitEditingSpaceField(field, rawValue) {
    const activeSpace = getActiveSpace();
    const api = getSpaceApi();
    if (!activeSpace || !api || typeof api.updateSpace !== 'function') {
      cancelEditingSpaceField();
      return;
    }

    const payload = {};
    if (field === 'name') {
      payload.name = String(rawValue || '').trim() || activeSpace.name || '未命名空间';
    } else {
      payload.description = String(rawValue || '').trim();
    }

    try {
      const result = await api.updateSpace(getUserId(), activeSpace.id, payload);
      if (result && result.space) {
        replaceSpace(result.space);
      }
      editingSpaceField = '';
      editingSpaceDraft = '';
      render();
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('空间信息保存失败', error, '请稍后重试')
        : '空间信息保存失败，请稍后重试');
      window.requestAnimationFrame(focusSpaceFieldEditor);
    }
  }

  function bindSpaceFieldEditor() {
    const editor = document.getElementById('spaceFieldEditor');
    if (!editor) return;

    editor.addEventListener('input', function () {
      editingSpaceDraft = this.value;
    });

    editor.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelEditingSpaceField();
        return;
      }
      if (event.key === 'Enter' && editingSpaceField === 'name') {
        event.preventDefault();
        submitEditingSpaceField(editingSpaceField, this.value);
      }
      if (event.key === 'Enter' && editingSpaceField === 'description' && !event.shiftKey) {
        event.preventDefault();
        submitEditingSpaceField(editingSpaceField, this.value);
      }
    });

    editor.addEventListener('blur', function () {
      submitEditingSpaceField(editingSpaceField, this.value);
    });
  }

  function isTextLikeUpload(mime, lowerName) {
    if (String(mime || '').startsWith('text/')) return true;
    return TEXT_FILE_EXTENSIONS.some(function (ext) {
      return String(lowerName || '').endsWith(ext);
    });
  }

  function inferUploadKind(mime, lowerName) {
    const mimeText = String(mime || '').toLowerCase();
    const fileName = String(lowerName || '').toLowerCase();
    if (mimeText.startsWith('image/')) return 'image';
    if (mimeText.startsWith('audio/')) return 'audio';
    if (mimeText.startsWith('video/')) return 'video';
    if (mimeText.includes('pdf') || fileName.endsWith('.pdf')) return 'pdf';
    if (fileName.endsWith('.url') || mimeText.indexOf('uri-list') >= 0) return 'link';
    if (isTextLikeUpload(mimeText, fileName)) return 'note';
    return 'document';
  }

  async function readFileAsText(file) {
    if (!file || typeof file.text !== 'function') return '';
    const text = await file.text();
    return String(text || '').replace(/\u0000/g, '').slice(0, 120000);
  }

  async function readFileAsDataUrl(file) {
    if (!file) return '';
    return await new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        resolve(String(reader.result || ''));
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function setContentMode(mode) {
    contentMode = mode;
    const modal = document.getElementById('contentModal');
    if (!modal) return;

    modal.querySelectorAll('[data-content-mode-select]').forEach(function (btn) {
      const active = btn.getAttribute('data-content-mode-select') === mode;
      btn.classList.toggle('active', active);
    });

    const uploadWrap = document.getElementById('contentUploadFields');
    const textWrap = document.getElementById('contentTextFields');
    const recordWrap = document.getElementById('contentRecordFields');
    const textarea = document.getElementById('contentModalText');
    const titleInput = document.getElementById('contentModalTitle');
    const submitBtn = document.getElementById('contentModalSubmitBtn');

    if (uploadWrap) uploadWrap.hidden = mode !== 'upload';
    if (textWrap) textWrap.hidden = mode === 'upload';
    if (recordWrap) recordWrap.hidden = mode !== 'record';

    if (titleInput) {
      if (mode === 'link') {
        titleInput.placeholder = '标题（可选，例如：线代公开课）';
      } else if (mode === 'paste') {
        titleInput.placeholder = '标题（可选，例如：函数笔记）';
      } else if (mode === 'record') {
        titleInput.placeholder = '标题（可选，例如：高数第 3 讲）';
      } else {
        titleInput.placeholder = '标题（可选）';
      }
    }

    if (textarea) {
      if (mode === 'link') {
        textarea.placeholder = '粘贴链接地址，可换行输入多个';
      } else if (mode === 'paste') {
        textarea.placeholder = '粘贴学习文本、资料摘要或题目内容';
      } else if (mode === 'record') {
        textarea.placeholder = '可补充课堂记录、讲座要点或文字摘要';
      } else {
        textarea.placeholder = '';
      }
    }

    if (submitBtn) {
      submitBtn.textContent = mode === 'upload' ? '开始上传' : '保存到当前空间';
    }
  }

  function resetContentModalState() {
    const result = document.getElementById('contentModalResult');
    const title = document.getElementById('contentModalTitle');
    const text = document.getElementById('contentModalText');
    const fileInput = document.getElementById('contentModalFile');
    if (result) result.textContent = '';
    if (title) title.value = '';
    if (text) text.value = '';
    if (fileInput) fileInput.value = '';
    resetRecordState();
    setContentMode('upload');
  }

  function openContentModal(mode) {
    const modal = document.getElementById('contentModal');
    const headline = document.getElementById('contentModalHeadline');
    if (!modal) return;
    if (headline) {
      headline.textContent = `是时候学习了，${getUserDisplayName() || '同学'}`;
    }
    modal.classList.add('show');
    syncModalBodyState();
    resetContentModalState();
    setContentMode(mode || 'upload');
  }

  function closeContentModal() {
    const modal = document.getElementById('contentModal');
    if (entryMediaRecorder && entryMediaRecorder.state === 'recording') {
      entryMediaRecorder.stop();
    }
    stopRecordStreamTracks();
    resetRecordState();
    if (modal) modal.classList.remove('show');
    syncModalBodyState();
  }

  function resetRecordState() {
    const audioEl = document.getElementById('contentRecordAudio');
    const statusEl = document.getElementById('contentRecordStatus');
    const toggleBtn = document.getElementById('contentRecordToggleBtn');

    entryRecordChunks = [];
    entryRecordedBlob = null;
    entryRecordedMime = '';
    if (entryRecordedAudioUrl) {
      URL.revokeObjectURL(entryRecordedAudioUrl);
      entryRecordedAudioUrl = '';
    }

    if (audioEl) {
      audioEl.pause();
      audioEl.removeAttribute('src');
      audioEl.style.display = 'none';
    }
    if (statusEl) statusEl.textContent = '未录音';
    if (toggleBtn) toggleBtn.textContent = '开始录音';
  }

  function stopRecordStreamTracks() {
    if (entryMediaStream) {
      entryMediaStream.getTracks().forEach(function (track) {
        track.stop();
      });
      entryMediaStream = null;
    }
  }

  async function toggleRecording() {
    const statusEl = document.getElementById('contentRecordStatus');
    const toggleBtn = document.getElementById('contentRecordToggleBtn');
    const audioEl = document.getElementById('contentRecordAudio');

    if (!statusEl || !toggleBtn || !audioEl) return;

    if (entryMediaRecorder && entryMediaRecorder.state === 'recording') {
      entryMediaRecorder.stop();
      toggleBtn.textContent = '开始录音';
      statusEl.textContent = '录音已停止，正在生成音频...';
      return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
      statusEl.textContent = '当前浏览器不支持录音';
      return;
    }

    try {
      resetRecordState();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      entryMediaStream = stream;
      entryMediaRecorder = new MediaRecorder(stream);
      entryRecordChunks = [];

      entryMediaRecorder.ondataavailable = function (event) {
        if (event.data && event.data.size > 0) {
          entryRecordChunks.push(event.data);
        }
      };

      entryMediaRecorder.onstop = function () {
        if (!entryRecordChunks.length) {
          statusEl.textContent = '未捕获到音频，请重试';
          stopRecordStreamTracks();
          return;
        }

        entryRecordedMime = entryMediaRecorder.mimeType || 'audio/webm';
        entryRecordedBlob = new Blob(entryRecordChunks, { type: entryRecordedMime });
        entryRecordedAudioUrl = URL.createObjectURL(entryRecordedBlob);
        audioEl.src = entryRecordedAudioUrl;
        audioEl.style.display = 'block';
        statusEl.textContent = `已录音 ${Math.max(1, Math.round(entryRecordedBlob.size / 1024))} KB`;
        stopRecordStreamTracks();
      };

      entryMediaRecorder.start();
      toggleBtn.textContent = '停止录音';
      statusEl.textContent = '录音中...';
    } catch (error) {
      statusEl.textContent = (window.ApiUtils && window.ApiUtils.withSuggestion)
        ? window.ApiUtils.withSuggestion('无法开始录音', error, '请检查麦克风权限')
        : '无法开始录音，请检查麦克风权限';
      stopRecordStreamTracks();
    }
  }

  async function appendItemsToActiveSpace(items) {
    const api = getSpaceApi();
    const activeSpace = getActiveSpace();
    if (!api || typeof api.addItems !== 'function' || !activeSpace) {
      return { ok: false, message: '未找到当前空间，请刷新后重试。' };
    }

    try {
      const saved = await api.addItems(getUserId(), activeSpace.id, items);
      if (saved && saved.space) {
        replaceSpace(saved.space);
        render();
      }
      return {
        ok: true,
        space: saved && saved.space ? saved.space : null,
        items: saved && Array.isArray(saved.items) ? saved.items : []
      };
    } catch (error) {
      return {
        ok: false,
        message: (window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
          ? window.SpaceCloudStore.withSuggestion('保存失败', error, '请稍后重试')
          : '保存失败，请稍后重试'
      };
    }
  }

  async function submitContentModal() {
    const result = document.getElementById('contentModalResult');
    const submitBtn = document.getElementById('contentModalSubmitBtn');
    const titleInput = document.getElementById('contentModalTitle');
    const textInput = document.getElementById('contentModalText');
    const fileInput = document.getElementById('contentModalFile');
    if (!result || !submitBtn || !titleInput || !textInput || !fileInput) return;

    const activeSpace = getActiveSpace();
    if (!activeSpace) {
      result.textContent = '请先创建空间。';
      return;
    }

    submitBtn.disabled = true;
    const rawLabel = submitBtn.textContent;
    submitBtn.textContent = '处理中...';

    try {
      if (contentMode === 'upload') {
        const files = Array.from(fileInput.files || []);
        if (!files.length) {
          result.textContent = '请先选择文件。';
          return;
        }

        const uploadItems = [];
        for (const file of files) {
          const mime = String(file.type || '').toLowerCase();
          const lowerName = String(file.name || '').toLowerCase();
          const kind = inferUploadKind(mime, lowerName);
          let fileDataUrl = '';
          let textContent = '';

          try {
            fileDataUrl = await readFileAsDataUrl(file);
          } catch (error) {
            fileDataUrl = '';
          }

          if (kind === 'note') {
            try {
              textContent = await readFileAsText(file);
            } catch (error) {
              textContent = '';
            }
          }

          uploadItems.push({
            name: file.name,
            kind: kind,
            mime: mime,
            size: file.size,
            source: 'space_detail_upload',
            content: textContent,
            summary: [
              `文件名: ${file.name || 'unknown'}`,
              `MIME: ${mime || 'unknown'}`,
              `大小: ${Math.max(1, Math.round((Number(file.size) || 0) / 1024))} KB`
            ].join('\n'),
            audioDataUrl: kind === 'audio' ? fileDataUrl : '',
            fileDataUrl: fileDataUrl
          });
        }

        const uploadResult = await appendItemsToActiveSpace(uploadItems);
        if (!uploadResult.ok) {
          result.textContent = uploadResult.message;
          return;
        }

        result.textContent = `已添加到「${activeSpace.name || '当前空间'}」。`;
        setTimeout(closeContentModal, 320);
        return;
      }

      const title = String(titleInput.value || '').trim();
      const text = String(textInput.value || '').trim();

      if (contentMode === 'link') {
        if (!text) {
          result.textContent = '请输入链接后再提交。';
          return;
        }
        const linkResult = await appendItemsToActiveSpace([{
          name: title || '学习链接',
          kind: 'link',
          mime: 'text/uri-list',
          size: text.length,
          source: 'space_detail_link',
          content: text,
          summary: '链接内容已保存，可直接用于后续学习与问答。'
        }]);
        if (!linkResult.ok) {
          result.textContent = linkResult.message;
          return;
        }
        result.textContent = `链接已保存到「${activeSpace.name || '当前空间'}」。`;
        setTimeout(closeContentModal, 320);
        return;
      }

      if (contentMode === 'paste') {
        if (!text) {
          result.textContent = '请输入内容后再提交。';
          return;
        }
        const noteResult = await appendItemsToActiveSpace([{
          name: title || '学习文本',
          kind: 'note',
          mime: 'text/plain',
          size: text.length,
          source: 'space_detail_paste',
          content: text,
          summary: '粘贴文本已保存，可用于后续问答和练习。'
        }]);
        if (!noteResult.ok) {
          result.textContent = noteResult.message;
          return;
        }
        result.textContent = `文本已保存到「${activeSpace.name || '当前空间'}」。`;
        setTimeout(closeContentModal, 320);
        return;
      }

      if (!text && !entryRecordedBlob) {
        result.textContent = '请录音或输入讲座记录后再提交。';
        return;
      }

      const recordItems = [];
      if (entryRecordedBlob) {
        let audioDataUrl = '';
        try {
          audioDataUrl = await new Promise(function (resolve, reject) {
            const reader = new FileReader();
            reader.onload = function () {
              resolve(String(reader.result || ''));
            };
            reader.onerror = reject;
            reader.readAsDataURL(entryRecordedBlob);
          });
        } catch (error) {
          audioDataUrl = '';
        }

        recordItems.push({
          name: `${title || '课堂录音'}.webm`,
          kind: 'audio',
          mime: entryRecordedMime || 'audio/webm',
          size: Number(entryRecordedBlob.size) || 0,
          source: 'space_detail_record',
          content: text,
          summary: '课堂录音已保存。',
          audioDataUrl: audioDataUrl
        });
      } else {
        recordItems.push({
          name: title || '课堂记录',
          kind: 'note',
          mime: 'text/plain',
          size: text.length,
          source: 'space_detail_record_note',
          content: text,
          summary: '课堂记录文本已保存。'
        });
      }

      const recordResult = await appendItemsToActiveSpace(recordItems);
      if (!recordResult.ok) {
        result.textContent = recordResult.message;
        return;
      }
      result.textContent = `记录已保存到「${activeSpace.name || '当前空间'}」。`;
      setTimeout(closeContentModal, 320);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = rawLabel;
    }
  }

  function applySpaceMutationResult(result) {
    if (result && result.sourceSpace) {
      replaceSpace(result.sourceSpace);
    }
    if (result && result.space) {
      replaceSpace(result.space);
    }
    ensureState();
    render();
  }

  async function renameItem(itemId) {
    const activeSpace = getActiveSpace();
    const item = getItemById(activeSpace, itemId);
    const api = getSpaceApi();
    if (!item || !api || typeof api.updateItem !== 'function') return;

    const nextName = window.prompt('请输入新的文件名称：', item.name || '未命名文件');
    if (nextName === null) return;

    try {
      const result = await api.updateItem(getUserId(), itemId, {
        name: String(nextName || '').trim() || item.name || '未命名文件'
      });
      openItemMenuId = null;
      openItemMovePickerId = null;
      applySpaceMutationResult(result);
      if (previewItemId === itemId) {
        renderPreviewModal();
      }
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('重命名失败', error, '请稍后重试')
        : '重命名失败，请稍后重试');
    }
  }

  async function moveItemToSpace(itemId, targetSpaceId) {
    const api = getSpaceApi();
    if (!api || typeof api.moveItem !== 'function') return;

    try {
      const result = await api.moveItem(getUserId(), itemId, targetSpaceId);
      openItemMenuId = null;
      openItemMovePickerId = null;
      if (previewItemId === itemId) {
        clearPreviewSelection();
      }
      applySpaceMutationResult(result);
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('移动失败', error, '请稍后重试')
        : '移动失败，请稍后重试');
    }
  }

  async function deleteItem(itemId) {
    const api = getSpaceApi();
    const activeSpace = getActiveSpace();
    const item = getItemById(activeSpace, itemId);
    if (!api || typeof api.deleteItem !== 'function' || !item) return;

    const confirmed = window.confirm(`确认删除「${item.name || '未命名文件'}」吗？`);
    if (!confirmed) return;

    try {
      const result = await api.deleteItem(getUserId(), itemId);
      openItemMenuId = null;
      openItemMovePickerId = null;
      if (previewItemId === itemId) {
        clearPreviewSelection();
      }
      if (result && result.space) {
        replaceSpace(result.space);
      }
      ensureState();
      render();
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('删除失败', error, '请稍后重试')
        : '删除失败，请稍后重试');
    }
  }

  async function createFolderInActiveSpace() {
    const activeSpace = getActiveSpace();
    if (!activeSpace) return;
    const nextName = window.prompt('请输入文件夹名称：', '新建文件夹');
    if (nextName === null) return;

    const result = await appendItemsToActiveSpace([{
      name: String(nextName || '').trim() || '新建文件夹',
      kind: 'folder',
      mime: 'inode/directory',
      size: 0,
      source: 'space_detail_folder',
      content: '',
      summary: '文件夹占位项'
    }]);

    if (!result.ok) {
      window.alert(result.message);
      return;
    }

    isSpaceMoreMenuOpen = false;
    render();
  }

  async function createSpace() {
    const api = getSpaceApi();
    if (!api || typeof api.createSpace !== 'function') return;

    const nextName = window.prompt('请输入空间名称：', `新空间 ${spaces.length + 1}`);
    if (nextName === null) return;

    try {
      const result = await api.createSpace(getUserId(), nextName);
      if (result && result.space) {
        replaceSpace(result.space);
        activeSpaceId = result.space.id;
        if (window.history && typeof window.history.replaceState === 'function') {
          window.history.replaceState({}, '', buildSpacesPageUrl(result.space.id));
        }
        render();
      }
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('创建空间失败', error, '请稍后重试')
        : '创建空间失败，请稍后重试');
    }
  }

  async function refreshSpaces() {
    try {
      await loadSpaces();
      if (previewItemId) {
        await loadItemIntoActiveSpace(previewItemId);
      }
      render();
    } catch (error) {
      render();
    }
  }

  function bindShellActions() {
    const addBtn = document.getElementById('addContentBtn');
    const moreBtn = document.getElementById('spaceMoreBtn');
    const newFolderBtn = document.getElementById('createFolderBtn');
    const emptyCreateBtn = document.getElementById('createSpaceFromEmptyBtn');
    const readerBackBtn = document.getElementById('spaceReaderBackBtn');
    const propertiesCloseBtn = document.getElementById('itemPropertiesCloseBtn');
    const contentCloseBtn = document.getElementById('contentModalCloseBtn');
    const contentCancelBtn = document.getElementById('contentModalCancelBtn');
    const contentSubmitBtn = document.getElementById('contentModalSubmitBtn');
    const contentModal = document.getElementById('contentModal');
    const propertiesModal = document.getElementById('itemPropertiesModal');
    const recordToggleBtn = document.getElementById('contentRecordToggleBtn');
    const recordResetBtn = document.getElementById('contentRecordResetBtn');

    if (addBtn && !addBtn.dataset.bound) {
      addBtn.addEventListener('click', function () {
        openContentModal('upload');
      });
      addBtn.dataset.bound = '1';
    }

    if (moreBtn && !moreBtn.dataset.bound) {
      moreBtn.addEventListener('click', function (event) {
        event.stopPropagation();
        isSpaceMoreMenuOpen = !isSpaceMoreMenuOpen;
        renderSpaceMoreMenu();
      });
      moreBtn.dataset.bound = '1';
    }

    if (newFolderBtn && !newFolderBtn.dataset.bound) {
      newFolderBtn.addEventListener('click', function () {
        createFolderInActiveSpace();
      });
      newFolderBtn.dataset.bound = '1';
    }

    if (emptyCreateBtn && !emptyCreateBtn.dataset.bound) {
      emptyCreateBtn.addEventListener('click', function () {
        createSpace();
      });
      emptyCreateBtn.dataset.bound = '1';
    }

    document.querySelectorAll('[data-content-mode-select]').forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.addEventListener('click', function () {
        setContentMode(this.getAttribute('data-content-mode-select'));
      });
      btn.dataset.bound = '1';
    });

    if (contentCloseBtn && !contentCloseBtn.dataset.bound) {
      contentCloseBtn.addEventListener('click', closeContentModal);
      contentCloseBtn.dataset.bound = '1';
    }

    if (contentCancelBtn && !contentCancelBtn.dataset.bound) {
      contentCancelBtn.addEventListener('click', closeContentModal);
      contentCancelBtn.dataset.bound = '1';
    }

    if (contentSubmitBtn && !contentSubmitBtn.dataset.bound) {
      contentSubmitBtn.addEventListener('click', submitContentModal);
      contentSubmitBtn.dataset.bound = '1';
    }

    if (recordToggleBtn && !recordToggleBtn.dataset.bound) {
      recordToggleBtn.addEventListener('click', toggleRecording);
      recordToggleBtn.dataset.bound = '1';
    }

    if (recordResetBtn && !recordResetBtn.dataset.bound) {
      recordResetBtn.addEventListener('click', function () {
        if (entryMediaRecorder && entryMediaRecorder.state === 'recording') {
          entryMediaRecorder.stop();
        }
        stopRecordStreamTracks();
        resetRecordState();
      });
      recordResetBtn.dataset.bound = '1';
    }

    if (readerBackBtn && !readerBackBtn.dataset.bound) {
      readerBackBtn.addEventListener('click', exitPreviewPage);
      readerBackBtn.dataset.bound = '1';
    }

    if (propertiesCloseBtn && !propertiesCloseBtn.dataset.bound) {
      propertiesCloseBtn.addEventListener('click', closePropertiesModal);
      propertiesCloseBtn.dataset.bound = '1';
    }

    if (contentModal && !contentModal.dataset.bound) {
      contentModal.addEventListener('click', function (event) {
        if (event.target === contentModal) {
          closeContentModal();
        }
      });
      contentModal.dataset.bound = '1';
    }

    if (propertiesModal && !propertiesModal.dataset.bound) {
      propertiesModal.addEventListener('click', function (event) {
        if (event.target === propertiesModal) {
          closePropertiesModal();
        }
      });
      propertiesModal.dataset.bound = '1';
    }
  }

  function bindGlobalListeners() {
    if (document.body.dataset.spacePageBound) return;

    document.addEventListener('click', function (event) {
      if (!event.target.closest('[data-item-menu], [data-item-menu-toggle]')) {
        openItemMenuId = null;
        openItemMovePickerId = null;
        renderItemList();
      }
      if (!event.target.closest('.space-more-wrap')) {
        isSpaceMoreMenuOpen = false;
        renderSpaceMoreMenu();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        if (editingSpaceField) {
          cancelEditingSpaceField();
        }
        if (previewItemId) {
          exitPreviewPage();
          return;
        }
        if (document.getElementById('contentModal').classList.contains('show')) {
          closeContentModal();
        }
        if (document.getElementById('itemPropertiesModal').classList.contains('show')) {
          closePropertiesModal();
        }
        openItemMenuId = null;
        openItemMovePickerId = null;
        isSpaceMoreMenuOpen = false;
        renderItemList();
        renderSpaceMoreMenu();
      }
    });

    window.addEventListener('storage', function (event) {
      if (event.key === 'fangzhigong_space_sync') {
        refreshSpaces();
      }
    });

    window.addEventListener('spaces:changed', function (event) {
      const detail = event && event.detail && typeof event.detail === 'object'
        ? event.detail
        : {};
      const changedUserId = String(detail.userId || '').trim();
      if (changedUserId && changedUserId !== getUserId()) return;
      refreshSpaces();
    });

    window.addEventListener('focus', function () {
      refreshSpaces();
    });

    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        refreshSpaces();
      }
    });

    document.body.dataset.spacePageBound = '1';
  }

  async function init() {
    const shouldCreateSpaceFromQuery = hasCreateSpaceQuery();
    if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
      window.PageShell.initGlobalSidebar();
    }

    bindShellActions();
    bindGlobalListeners();
    syncHeader();

    try {
      await loadSpaces();
      if (previewItemId) {
        await loadItemIntoActiveSpace(previewItemId);
      }
    } catch (error) {
      spaces = [];
    }

    render();

    if (shouldCreateSpaceFromQuery) {
      clearCreateSpaceQuery();
      await createSpace();
    }

    if (window.UserContext) {
      window.UserContext.onChange(function () {
        refreshSpaces();
        syncHeader();
      });
    }
  }

  init();
})();
