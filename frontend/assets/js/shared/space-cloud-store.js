(function () {
  function getApiBase() {
    if (window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function') {
      return window.ApiUtils.getApiBase();
    }
    return '';
  }

  function parseResponse(response) {
    if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
      return window.ApiUtils.parseApiResponse(response);
    }
    return response.json();
  }

  function withSuggestion(prefix, error, suggestion) {
    if (window.ApiUtils && typeof window.ApiUtils.withSuggestion === 'function') {
      return window.ApiUtils.withSuggestion(prefix, error, suggestion);
    }
    const reason = error && error.message ? error.message : '未知错误';
    return `${prefix}：${reason}。建议：${suggestion || '请稍后重试'}`;
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  }

  function normalizeItem(item) {
    if (!item || typeof item !== 'object') return null;
    const itemId = String(item.id || '').trim();
    if (!itemId) return null;
    return {
      id: itemId,
      name: String(item.name || '未命名文件'),
      kind: String(item.kind || 'document'),
      mime: String(item.mime || ''),
      size: Math.max(0, normalizeNumber(item.size, 0)),
      source: String(item.source || ''),
      content: String(item.content || ''),
      summary: String(item.summary || ''),
      addedAt: normalizeNumber(item.addedAt || item.added_at, Date.now()),
      updatedAt: normalizeNumber(item.updatedAt || item.updated_at || item.addedAt || item.added_at, Date.now()),
      previewUrl: String(item.previewUrl || item.preview_url || ''),
      previewAvailable: !!(item.previewAvailable || item.preview_available || item.previewUrl || item.preview_url || item.content)
    };
  }

  function normalizeSpace(space) {
    if (!space || typeof space !== 'object') return null;
    const spaceId = String(space.id || '').trim();
    if (!spaceId) return null;
    return {
      id: spaceId,
      name: String(space.name || '新空间'),
      createdAt: normalizeNumber(space.createdAt || space.created_at, Date.now()),
      updatedAt: normalizeNumber(space.updatedAt || space.updated_at || space.createdAt || space.created_at, Date.now()),
      itemCount: Math.max(0, normalizeNumber(space.itemCount || space.item_count, 0)),
      items: Array.isArray(space.items) ? space.items.map(normalizeItem).filter(Boolean) : []
    };
  }

  async function request(path, options) {
    const response = await fetch(`${getApiBase()}${path}`, options || {});
    return parseResponse(response);
  }

  async function listSpaces(userId) {
    const data = await request(`/api/spaces?user_id=${encodeURIComponent(userId)}`);
    return {
      spaces: Array.isArray(data.spaces) ? data.spaces.map(normalizeSpace).filter(Boolean) : [],
      activeEntrySpaceId: String(data.activeEntrySpaceId || data.active_entry_space_id || ''),
      storage: data.storage || {}
    };
  }

  async function createSpace(userId, name) {
    const data = await request('/api/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        name: String(name || '')
      })
    });
    return {
      data,
      space: normalizeSpace(data.space)
    };
  }

  async function deleteSpace(userId, spaceId) {
    return request(`/api/spaces/${encodeURIComponent(spaceId)}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE'
    });
  }

  async function addItems(userId, spaceId, items) {
    const data = await request(`/api/spaces/${encodeURIComponent(spaceId)}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        items: Array.isArray(items) ? items : []
      })
    });
    return {
      data,
      space: normalizeSpace(data.space),
      items: Array.isArray(data.items) ? data.items.map(normalizeItem).filter(Boolean) : []
    };
  }

  async function getItem(userId, itemId) {
    const data = await request(`/api/spaces/items/${encodeURIComponent(itemId)}?user_id=${encodeURIComponent(userId)}`);
    return {
      data,
      item: normalizeItem(data.item),
      space: normalizeSpace(data.space)
    };
  }

  async function updateItem(userId, itemId, payload) {
    const data = await request(`/api/spaces/items/${encodeURIComponent(itemId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        ...(payload || {})
      })
    });
    return {
      data,
      item: normalizeItem(data.item)
    };
  }

  function getItemSnippet(item, limit) {
    const maxLen = Math.max(12, Number(limit || 56));
    const raw = String((item && (item.content || item.summary)) || '').replace(/\s+/g, ' ').trim();
    if (!raw) return '点击即可直接预览分析';
    return raw.length > maxLen ? `${raw.slice(0, maxLen)}...` : raw;
  }

  function buildItemPreviewHtml(item) {
    if (!item || typeof item !== 'object') return '';

    const mime = String(item.mime || '').toLowerCase();
    const type = String(item.kind || 'document').toLowerCase();
    const previewUrl = String(item.previewUrl || '').trim();

    if ((type === 'audio' || mime.startsWith('audio/')) && previewUrl) {
      return `<audio controls src="${esc(previewUrl)}"></audio>`;
    }
    if ((type === 'video' || mime.startsWith('video/')) && previewUrl) {
      return `<video controls src="${esc(previewUrl)}"></video>`;
    }
    if (mime.startsWith('image/') && previewUrl) {
      return `<img alt="预览" src="${esc(previewUrl)}">`;
    }
    if ((type === 'pdf' || mime.includes('pdf')) && previewUrl) {
      return `<iframe title="PDF预览" src="${esc(previewUrl)}"></iframe>`;
    }
    if (item.content) {
      return `<pre>${esc(item.content)}</pre>`;
    }
    if (previewUrl) {
      return `<iframe title="文件预览" src="${esc(previewUrl)}"></iframe>`;
    }
    return '';
  }

  window.SpaceCloudStore = {
    withSuggestion,
    normalizeItem,
    normalizeSpace,
    listSpaces,
    createSpace,
    deleteSpace,
    addItems,
    getItem,
    updateItem,
    getItemSnippet,
    buildItemPreviewHtml
  };
})();
