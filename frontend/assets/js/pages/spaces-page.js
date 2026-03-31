(function () {
  let spaces = [];
  let activeSpaceId = null;
  let activeItemId = null;

  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }

  function getSpaceApi() {
    return window.SpaceCloudStore || null;
  }

  function nowLabel(date) {
    const d = date ? new Date(date) : new Date();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function ensureState() {
    if (!spaces.length) {
      activeSpaceId = null;
      activeItemId = null;
      return;
    }
    if (!spaces.find(function (space) { return space.id === activeSpaceId; })) {
      activeSpaceId = spaces[0].id;
    }
    const activeSpace = getActiveSpace();
    const items = activeSpace && Array.isArray(activeSpace.items) ? activeSpace.items : [];
    if (!items.find(function (item) { return item.id === activeItemId; })) {
      activeItemId = items[0] ? items[0].id : null;
    }
  }

  function getActiveSpace() {
    return spaces.find(function (space) {
      return space.id === activeSpaceId;
    }) || null;
  }

  function getActiveItem() {
    const space = getActiveSpace();
    if (!space || !Array.isArray(space.items)) return null;
    return space.items.find(function (item) {
      return item.id === activeItemId;
    }) || null;
  }

  function replaceSpace(space) {
    if (!space || !space.id) return;
    spaces = [space].concat(spaces.filter(function (item) { return item.id !== space.id; }));
    ensureState();
  }

  async function loadSpaces() {
    const api = getSpaceApi();
    if (!api || typeof api.listSpaces !== 'function') {
      spaces = [];
      activeSpaceId = null;
      activeItemId = null;
      return;
    }

    const data = await api.listSpaces(getUserId());
    spaces = Array.isArray(data.spaces) ? data.spaces : [];
    if (data.activeEntrySpaceId && spaces.find(function (space) { return space.id === data.activeEntrySpaceId; })) {
      activeSpaceId = data.activeEntrySpaceId;
    }
    ensureState();
  }

  function renderSpaceList() {
    const list = document.getElementById('spaceList');
    if (!list) return;
    if (!spaces.length) {
      list.innerHTML = '<div class="hint">当前账号还没有云端空间</div>';
      return;
    }

    const sorted = spaces.slice().sort(function (a, b) {
      return Number(b.createdAt || 0) - Number(a.createdAt || 0);
    });

    list.innerHTML = sorted.map(function (space) {
      const count = Array.isArray(space.items) ? space.items.length : 0;
      const activeClass = space.id === activeSpaceId ? 'active' : '';
      return `<button type="button" class="space-card ${activeClass}" data-space-id="${esc(space.id)}"><div class="space-name">${esc(space.name)}</div><div class="space-meta">${count} 内容</div></button>`;
    }).join('');

    list.querySelectorAll('[data-space-id]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setActiveSpace(this.getAttribute('data-space-id'));
      });
    });
  }

  function renderItemGrid() {
    const grid = document.getElementById('itemGrid');
    const title = document.getElementById('itemPanelTitle');
    if (!grid || !title) return;

    const space = getActiveSpace();
    if (!space) {
      title.textContent = '空间内容';
      grid.innerHTML = '<div class="hint">暂无空间</div>';
      return;
    }

    title.textContent = `${space.name} · 内容`;
    const items = Array.isArray(space.items) ? space.items : [];
    if (!items.length) {
      activeItemId = null;
      grid.innerHTML = '<div class="hint">该空间暂无内容</div>';
      return;
    }

    if (!items.find(function (item) { return item.id === activeItemId; })) {
      activeItemId = items[0].id;
    }

    const api = getSpaceApi();
    grid.innerHTML = items.slice(0, 60).map(function (item) {
      const activeClass = item.id === activeItemId ? 'active' : '';
      const sizeKb = Math.max(1, Math.round((Number(item.size) || 0) / 1024));
      const snippet = api && typeof api.getItemSnippet === 'function'
        ? api.getItemSnippet(item, 68)
        : '点击即可直接预览分析';
      return `<button type="button" class="item-card ${activeClass}" data-item-id="${esc(item.id)}"><div class="item-name">${esc(item.name || '未命名文件')}</div><div class="item-meta">${esc(item.kind || 'document')} · ${sizeKb} KB · ${nowLabel(item.addedAt)}</div><div class="item-snippet">${esc(snippet)}</div></button>`;
    }).join('');

    grid.querySelectorAll('[data-item-id]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setActiveItem(this.getAttribute('data-item-id'));
      });
    });
  }

  function renderViewer() {
    const viewer = document.getElementById('itemViewer');
    if (!viewer) return;

    const item = getActiveItem();
    if (!item) {
      viewer.innerHTML = '<div class="hint">点击内容项查看详情。</div>';
      return;
    }

    const api = getSpaceApi();
    const previewHtml = api && typeof api.buildItemPreviewHtml === 'function'
      ? api.buildItemPreviewHtml(item)
      : '';
    const mime = String(item.mime || '').toLowerCase();
    const type = String(item.kind || 'document');
    const sizeKb = Math.max(1, Math.round((Number(item.size) || 0) / 1024));
    const previewUrl = String(item.previewUrl || '').trim();
    const actionLine = previewUrl
      ? `<span class="hint">已在下方直接预览</span><a class="btn" href="${esc(previewUrl)}" target="_blank" rel="noopener noreferrer">新窗口预览</a>`
      : '<span class="hint">当前条目暂无原始文件，仅显示分析内容</span>';
    const summary = String(item.summary || '').trim();
    const summaryBlock = summary ? `<div class="viewer-summary">${esc(summary)}</div>` : '';
    const body = previewHtml || (item.content ? `<pre>${esc(item.content)}</pre>` : '<div class="hint">暂无可展示内容</div>');

    viewer.innerHTML = `
      <div class="viewer-title">${esc(item.name || '未命名文件')}</div>
      <div class="viewer-meta">${esc(type)} · ${sizeKb} KB · ${nowLabel(item.addedAt)}${mime ? ` · ${esc(mime)}` : ''}</div>
      <div class="viewer-actions">${actionLine}</div>
      ${summaryBlock}
      <div class="viewer-body">${body}</div>
    `;
  }

  function applyQueryDefaultSpace() {
    const params = new URLSearchParams(window.location.search || '');
    const sid = String(params.get('space_id') || '').trim();
    if (!sid) return;
    if (spaces.find(function (space) { return space.id === sid; })) {
      activeSpaceId = sid;
    }
  }

  function render() {
    renderSpaceList();
    renderItemGrid();
    renderViewer();
    syncDeleteButtonState();
  }

  function syncSpaceUserLabel() {
    const label = document.getElementById('spaceUserLabel');
    if (!label) return;
    const userLabel = (window.UserContext && typeof window.UserContext.getUserLabel === 'function')
      ? window.UserContext.getUserLabel()
      : getUserId();
    label.textContent = `用户：${userLabel}`;
  }

  function syncDeleteButtonState() {
    const btn = document.getElementById('deleteSpaceBtn');
    if (!btn) return;
    btn.disabled = !getActiveSpace();
  }

  async function setActiveSpace(spaceId) {
    if (!spaces.find(function (space) { return space.id === spaceId; })) return;
    activeSpaceId = spaceId;
    activeItemId = null;
    ensureState();
    render();
    const active = getActiveItem();
    if (active) {
      await setActiveItem(active.id);
    }
  }

  async function setActiveItem(itemId) {
    activeItemId = itemId;
    renderItemGrid();

    const viewer = document.getElementById('itemViewer');
    if (viewer) {
      viewer.innerHTML = '<div class="hint">正在加载云端预览与分析...</div>';
    }

    const api = getSpaceApi();
    if (!api || typeof api.getItem !== 'function') {
      renderViewer();
      return;
    }

    try {
      const result = await api.getItem(getUserId(), itemId);
      const item = result && result.item ? result.item : null;
      const space = result && result.space ? result.space : null;
      if (space && space.id && item) {
        const targetSpace = spaces.find(function (entry) { return entry.id === space.id; });
        if (targetSpace && Array.isArray(targetSpace.items)) {
          targetSpace.items = [item].concat(targetSpace.items.filter(function (entry) { return entry.id !== item.id; }));
        }
      } else if (item) {
        const activeSpace = getActiveSpace();
        if (activeSpace && Array.isArray(activeSpace.items)) {
          activeSpace.items = [item].concat(activeSpace.items.filter(function (entry) { return entry.id !== item.id; }));
        }
      }
    } catch (error) {
      if (viewer) {
        viewer.innerHTML = `<div class="hint">${esc((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
          ? window.SpaceCloudStore.withSuggestion('预览加载失败', error, '请稍后重试')
          : '预览加载失败，请稍后重试')}</div>`;
      }
      return;
    }

    renderViewer();
    renderItemGrid();
  }

  async function createSpace() {
    const api = getSpaceApi();
    if (!api || typeof api.createSpace !== 'function') return;

    const defaultName = `新空间 ${spaces.length + 1}`;
    const nextName = window.prompt('请输入新空间名称：', defaultName);
    if (nextName === null) return;

    try {
      const result = await api.createSpace(getUserId(), nextName);
      if (!result || !result.space) return;
      replaceSpace(result.space);
      activeSpaceId = result.space.id;
      activeItemId = null;
      render();
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('新建空间失败', error, '请稍后重试')
        : '新建空间失败，请稍后重试');
    }
  }

  async function deleteActiveSpace() {
    const api = getSpaceApi();
    const space = getActiveSpace();
    if (!api || typeof api.deleteSpace !== 'function' || !space) return;

    const confirmed = window.confirm(`确认删除空间「${space.name || '新空间'}」吗？删除后其中的云端内容也会一起移除。`);
    if (!confirmed) return;

    try {
      await api.deleteSpace(getUserId(), space.id);
      spaces = spaces.filter(function (entry) { return entry.id !== space.id; });
      activeSpaceId = null;
      activeItemId = null;
      ensureState();
      render();
    } catch (error) {
      window.alert((window.SpaceCloudStore && window.SpaceCloudStore.withSuggestion)
        ? window.SpaceCloudStore.withSuggestion('删除空间失败', error, '请稍后重试')
        : '删除空间失败，请稍后重试');
    }
  }

  async function hydrateInitialItem() {
    ensureState();
    const active = getActiveItem();
    if (active) {
      await setActiveItem(active.id);
      return;
    }
    render();
  }

  async function init() {
    if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
      window.PageShell.initGlobalSidebar();
    }

    const createBtn = document.getElementById('createSpaceBtn');
    const deleteBtn = document.getElementById('deleteSpaceBtn');
    if (createBtn && !createBtn.dataset.bound) {
      createBtn.addEventListener('click', function () {
        createSpace();
      });
      createBtn.dataset.bound = '1';
    }
    if (deleteBtn && !deleteBtn.dataset.bound) {
      deleteBtn.addEventListener('click', function () {
        deleteActiveSpace();
      });
      deleteBtn.dataset.bound = '1';
    }

    syncSpaceUserLabel();
    await loadSpaces();
    applyQueryDefaultSpace();
    ensureState();
    render();
    await hydrateInitialItem();

    if (window.UserContext) {
      window.UserContext.onChange(async function () {
        syncSpaceUserLabel();
        await loadSpaces();
        applyQueryDefaultSpace();
        ensureState();
        render();
        await hydrateInitialItem();
      });
    }
  }

  init();
})();
