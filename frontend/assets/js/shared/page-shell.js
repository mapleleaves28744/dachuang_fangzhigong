(function () {
  const SIDEBAR_SPACE_SYNC_KEY = 'fangzhigong_space_sync';
  const SIDEBAR_SPACES_COLLAPSED_KEY = 'fangzhigong_sidebar_spaces_collapsed';
  const STREAK_WIDGET_REFRESH_MS = 60000;
  const STREAK_WIDGET_WEEK_GOAL = 2;

  const telemetrySessionState = {
    pageId: '',
    startedAt: 0,
    stayReported: false
  };

  let sidebarSpaceRequestToken = 0;
  let sidebarSpacesCollapsed = readSidebarSpacesCollapsed();
  let sidebarOpenSpaceMenuId = '';
  let sidebarSpacesCache = [];
  let streakWidgetRequestToken = 0;
  let streakWidgetRefreshTimer = 0;
  let streakWidgetSummary = null;

  function getCurrentPageId() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    const last = path.split('/').pop() || 'index.html';
    return String(last).replace(/\.html$/i, '').trim() || 'index';
  }

  function getTelemetryApiBase() {
    return window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
      ? window.ApiUtils.getApiBase()
      : (window.location.origin || '');
  }

  function getTelemetryUserId() {
    return window.UserContext && typeof window.UserContext.getUserId === 'function'
      ? window.UserContext.getUserId()
      : 'default_user';
  }

  function safeJson(value) {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return '{}';
    }
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function postLearningBehavior(payload, preferBeacon) {
    const apiBase = getTelemetryApiBase();
    if (!apiBase) return;

    const body = {
      user_id: getTelemetryUserId(),
      source: 'page_shell',
      ...payload
    };

    const url = `${apiBase}/api/behavior/track`;
    if (preferBeacon && navigator.sendBeacon) {
      try {
        const blob = new Blob([safeJson(body)], { type: 'application/json' });
        navigator.sendBeacon(url, blob);
        return;
      } catch (error) {
        // 回退到 fetch keepalive。
      }
    }

    if (typeof window.fetch !== 'function') return;
    window.fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: safeJson(body),
      keepalive: !!preferBeacon
    }).catch(function () {});
  }

  function normalizeTargetPage(target) {
    const text = String(target || '').trim();
    if (!text) return '';
    const clean = text.split('?')[0].split('#')[0];
    return clean.replace(/^.*\//, '').replace(/\.html$/i, '');
  }

  function isAuthenticatedUser() {
    return !!(
      window.UserContext &&
      typeof window.UserContext.isAuthenticated === 'function' &&
      window.UserContext.isAuthenticated()
    );
  }

  function getSidebarSpaceApi() {
    return window.SpaceCloudStore && typeof window.SpaceCloudStore.listSpaces === 'function'
      ? window.SpaceCloudStore
      : null;
  }

  function getSidebarSpaceBaseLink() {
    return document.querySelector('.global-sidebar a[data-side-link="spaces.html"]');
  }

  function ensureSidebarSpaceSlot() {
    const baseLink = getSidebarSpaceBaseLink();
    if (!baseLink) return null;

    let slot = document.getElementById('globalSidebarSpaces');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'globalSidebarSpaces';
      slot.className = 'global-sidebar-spaces';
      baseLink.insertAdjacentElement('afterend', slot);
    }

    return slot;
  }

  function getCurrentSidebarSpaceId() {
    const params = new URLSearchParams(window.location.search || '');
    return String(params.get('space_id') || '').trim();
  }

  function getCachedSidebarSpace(spaceId) {
    const targetId = String(spaceId || '').trim();
    if (!targetId) return null;
    return sidebarSpacesCache.find(function (space) {
      return space && String(space.id || '').trim() === targetId;
    }) || null;
  }

  function buildSidebarSpaceHref(spaceId, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const url = new URL('spaces.html', window.location.href);
    url.searchParams.delete('space_id');
    url.searchParams.delete('item_id');
    url.searchParams.delete('create_space');

    if (opts.createSpace) {
      url.searchParams.set('create_space', '1');
    } else if (spaceId) {
      url.searchParams.set('space_id', String(spaceId).trim());
    }

    return `${url.pathname}${url.search}`;
  }

  function getSidebarSpaceCount(space) {
    if (!space || typeof space !== 'object') return 0;
    const itemCount = Number(space.itemCount);
    if (Number.isFinite(itemCount) && itemCount >= 0) {
      return Math.round(itemCount);
    }
    return Array.isArray(space.items) ? space.items.length : 0;
  }

  function getSidebarSpaceIconMarkup() {
    return [
      '<span class="global-sidebar-space-icon" aria-hidden="true">',
      '<svg viewBox="0 0 24 24" fill="none">',
      '<path d="M12 3.5 19 7.75v8.5L12 20.5 5 16.25v-8.5L12 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"></path>',
      '<path d="M5 7.75 12 12l7-4.25M12 12v8.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>',
      '</svg>',
      '</span>'
    ].join('');
  }

  function readSidebarSpacesCollapsed() {
    try {
      return window.localStorage.getItem(SIDEBAR_SPACES_COLLAPSED_KEY) === '1';
    } catch (error) {
      return false;
    }
  }

  function isSidebarSpacesRootActive() {
    return getCurrentPageId() === 'spaces' && !getCurrentSidebarSpaceId();
  }

  function buildSidebarSpacesShell(bodyHtml) {
    const collapsedClass = sidebarSpacesCollapsed ? ' is-collapsed' : '';
    const rootActiveClass = isSidebarSpacesRootActive() ? ' active' : '';
    const rootHref = buildSidebarSpaceHref('');
    return `
      <div class="global-sidebar-space-panel${collapsedClass}" data-sidebar-spaces-panel>
        <div class="global-sidebar-space-header">
          <a class="global-sidebar-space-root${rootActiveClass}" href="${esc(rootHref)}">
            <span class="global-sidebar-space-root-mark" aria-hidden="true"></span>
            <span class="global-sidebar-space-root-text">我的空间</span>
          </a>
          <button
            type="button"
            class="global-sidebar-space-toggle${collapsedClass}"
            data-sidebar-space-toggle
            aria-expanded="${sidebarSpacesCollapsed ? 'false' : 'true'}"
            aria-label="${sidebarSpacesCollapsed ? '展开我的空间' : '折叠我的空间'}"
          >
            <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="M2 4.5 6 8l4-3.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
          </button>
        </div>
        <div class="global-sidebar-space-body${collapsedClass}" data-sidebar-space-body${sidebarSpacesCollapsed ? ' hidden' : ''}>
          ${bodyHtml}
        </div>
      </div>
    `;
  }

  function syncSidebarSpacesCollapsedUi() {
    const slot = document.getElementById('globalSidebarSpaces');
    if (!slot) return;

    const panel = slot.querySelector('[data-sidebar-spaces-panel]');
    const body = slot.querySelector('[data-sidebar-space-body]');
    const toggle = slot.querySelector('[data-sidebar-space-toggle]');

    if (panel) {
      panel.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
    }
    if (body) {
      body.hidden = sidebarSpacesCollapsed;
      body.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
    }
    if (toggle) {
      toggle.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
      toggle.setAttribute('aria-expanded', sidebarSpacesCollapsed ? 'false' : 'true');
      toggle.setAttribute('aria-label', sidebarSpacesCollapsed ? '展开我的空间' : '折叠我的空间');
    }
  }

  function setSidebarSpaceBaseLinkHidden(baseLink, shouldHide) {
    if (!baseLink) return;
    const hidden = !!shouldHide;
    baseLink.hidden = hidden;
    baseLink.classList.toggle('is-page-shell-hidden', hidden);
    if (hidden) {
      baseLink.setAttribute('aria-hidden', 'true');
      baseLink.setAttribute('tabindex', '-1');
      return;
    }
    baseLink.removeAttribute('aria-hidden');
    baseLink.removeAttribute('tabindex');
  }

  function setSidebarSpacesCollapsed(nextValue) {
    sidebarSpacesCollapsed = !!nextValue;
    try {
      if (sidebarSpacesCollapsed) {
        window.localStorage.setItem(SIDEBAR_SPACES_COLLAPSED_KEY, '1');
      } else {
        window.localStorage.removeItem(SIDEBAR_SPACES_COLLAPSED_KEY);
      }
    } catch (error) {
      // 忽略本地存储不可用的情况。
    }
    syncSidebarSpacesCollapsedUi();
  }

  function renderSidebarSpacesState(html, hideBaseLink) {
    const baseLink = getSidebarSpaceBaseLink();
    const slot = ensureSidebarSpaceSlot();
    if (!baseLink || !slot) return;

    setSidebarSpaceBaseLinkHidden(baseLink, hideBaseLink);

    if (!html) {
      sidebarSpacesCache = [];
      sidebarOpenSpaceMenuId = '';
      slot.hidden = true;
      slot.innerHTML = '';
      return;
    }

    slot.hidden = false;
    slot.innerHTML = buildSidebarSpacesShell(html);
    syncSidebarSpacesCollapsedUi();
  }

  function renderSidebarSpacesList(spaces) {
    const currentSpaceId = getCurrentSidebarSpaceId();
    const sortedSpaces = Array.isArray(spaces)
      ? spaces.slice().sort(function (left, right) {
          const leftTime = Number((left && (left.updatedAt || left.createdAt)) || 0);
          const rightTime = Number((right && (right.updatedAt || right.createdAt)) || 0);
          return rightTime - leftTime;
        })
      : [];
    sidebarSpacesCache = sortedSpaces.slice();
    if (!getCachedSidebarSpace(sidebarOpenSpaceMenuId)) {
      sidebarOpenSpaceMenuId = '';
    }

    const itemsHtml = sortedSpaces.length
      ? sortedSpaces.map(function (space) {
          const spaceId = String((space && space.id) || '').trim();
          const name = String((space && space.name) || '未命名空间').trim() || '未命名空间';
          const count = getSidebarSpaceCount(space);
          const activeClass = currentSpaceId && currentSpaceId === spaceId ? ' active' : '';
          const menuOpenClass = sidebarOpenSpaceMenuId === spaceId ? ' show' : '';
          return `
            <div class="global-sidebar-space-item-row">
              <a class="global-sidebar-space-item${activeClass}" href="${esc(buildSidebarSpaceHref(spaceId))}">
                <span class="global-sidebar-space-item-main">
                  ${getSidebarSpaceIconMarkup()}
                  <span class="global-sidebar-space-item-text">${esc(name)}</span>
                </span>
              </a>
              <div class="global-sidebar-space-item-side">
                <span class="global-sidebar-space-item-count">(${count})</span>
                <div class="global-sidebar-space-menu-wrap">
                  <button
                    type="button"
                    class="global-sidebar-space-menu-btn"
                    data-sidebar-space-menu-toggle="${esc(spaceId)}"
                    aria-label="空间操作：${esc(name)}"
                    aria-haspopup="menu"
                    aria-expanded="${sidebarOpenSpaceMenuId === spaceId ? 'true' : 'false'}"
                  >
                    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <circle cx="10" cy="4" r="1.6"></circle>
                      <circle cx="10" cy="10" r="1.6"></circle>
                      <circle cx="10" cy="16" r="1.6"></circle>
                    </svg>
                  </button>
                  <div class="global-sidebar-space-menu${menuOpenClass}" data-sidebar-space-menu="${esc(spaceId)}" role="menu">
                    <button type="button" class="global-sidebar-space-menu-item" data-sidebar-space-action="rename" data-sidebar-space-id="${esc(spaceId)}">编辑</button>
                    <button type="button" class="global-sidebar-space-menu-item danger" data-sidebar-space-action="delete" data-sidebar-space-id="${esc(spaceId)}">删除</button>
                  </div>
                </div>
              </div>
            </div>
          `;
        }).join('')
      : '<div class="global-sidebar-space-empty">还没有空间，点击“新空间”开始整理资料。</div>';

    renderSidebarSpacesState(`
      <a class="global-sidebar-space-create" href="${esc(buildSidebarSpaceHref('', { createSpace: true }))}">
        <span class="global-sidebar-space-create-plus" aria-hidden="true">+</span>
        <span>新空间</span>
      </a>
      <div class="global-sidebar-space-items">${itemsHtml}</div>
    `, true);
  }

  async function renameSidebarSpace(spaceId) {
    const api = getSidebarSpaceApi();
    const space = getCachedSidebarSpace(spaceId);
    if (!space || !api || typeof api.updateSpace !== 'function') return;

    const currentName = String(space.name || '新空间').trim() || '新空间';
    const nextName = window.prompt('请输入新的空间名称：', currentName);
    if (nextName === null) return;

    const normalizedName = String(nextName || '').trim() || currentName;
    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesList(sidebarSpacesCache);
    if (normalizedName === currentName) return;

    try {
      await api.updateSpace(getTelemetryUserId(), space.id, { name: normalizedName });
      await refreshSidebarSpaces();
    } catch (error) {
      window.alert(api.withSuggestion
        ? api.withSuggestion('空间重命名失败', error, '请稍后重试')
        : '空间重命名失败，请稍后重试');
      await refreshSidebarSpaces();
    }
  }

  async function deleteSidebarSpace(spaceId) {
    const api = getSidebarSpaceApi();
    const space = getCachedSidebarSpace(spaceId);
    if (!space || !api || typeof api.deleteSpace !== 'function') return;

    const confirmed = window.confirm(`确认删除空间「${space.name || '新空间'}」吗？删除后其中的云端内容也会一起移除。`);
    if (!confirmed) return;

    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesList(sidebarSpacesCache);

    try {
      await api.deleteSpace(getTelemetryUserId(), space.id);
      if (getCurrentPageId() === 'spaces' && getCurrentSidebarSpaceId() === space.id) {
        window.location.href = buildSidebarSpaceHref('');
        return;
      }
      await refreshSidebarSpaces();
    } catch (error) {
      window.alert(api.withSuggestion
        ? api.withSuggestion('删除空间失败', error, '请稍后重试')
        : '删除空间失败，请稍后重试');
      await refreshSidebarSpaces();
    }
  }

  async function refreshSidebarSpaces() {
    const baseLink = getSidebarSpaceBaseLink();
    if (!baseLink) return;

    const api = getSidebarSpaceApi();
    if (!isAuthenticatedUser() || !api) {
      sidebarSpacesCache = [];
      sidebarOpenSpaceMenuId = '';
      renderSidebarSpacesState('', false);
      return;
    }

    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesState(
      '<div class="global-sidebar-space-loading">正在加载空间...</div>',
      true
    );

    const requestToken = ++sidebarSpaceRequestToken;

    try {
      const data = await api.listSpaces(getTelemetryUserId());
      if (requestToken !== sidebarSpaceRequestToken) return;
      renderSidebarSpacesList(Array.isArray(data && data.spaces) ? data.spaces : []);
    } catch (error) {
      if (requestToken !== sidebarSpaceRequestToken) return;
      renderSidebarSpacesState(`
        <a class="global-sidebar-space-create" href="${esc(buildSidebarSpaceHref('', { createSpace: true }))}">
          <span class="global-sidebar-space-create-plus" aria-hidden="true">+</span>
          <span>新空间</span>
        </a>
        <div class="global-sidebar-space-empty">空间加载失败，请稍后刷新重试。</div>
      `, true);
    }
  }

  function bindSidebarSpaceEvents() {
    if (document.body.dataset.pageShellSidebarSpacesBound) return;

    if (window.UserContext && typeof window.UserContext.onAuthChange === 'function') {
      window.UserContext.onAuthChange(function () {
        refreshSidebarSpaces();
      });
    }

    document.addEventListener('click', function (event) {
      const clickTarget = event.target && typeof event.target.closest === 'function'
        ? event.target
        : null;
      const toggle = clickTarget ? clickTarget.closest('[data-sidebar-space-toggle]') : null;
      if (!toggle) return;
      event.preventDefault();
      setSidebarSpacesCollapsed(!sidebarSpacesCollapsed);
    });

    document.addEventListener('click', function (event) {
      const clickTarget = event.target && typeof event.target.closest === 'function'
        ? event.target
        : null;
      if (!clickTarget) return;

      const menuToggle = clickTarget.closest('[data-sidebar-space-menu-toggle]');
      if (menuToggle) {
        event.preventDefault();
        event.stopPropagation();
        const spaceId = String(menuToggle.getAttribute('data-sidebar-space-menu-toggle') || '').trim();
        sidebarOpenSpaceMenuId = sidebarOpenSpaceMenuId === spaceId ? '' : spaceId;
        renderSidebarSpacesList(sidebarSpacesCache);
        return;
      }

      const actionBtn = clickTarget.closest('[data-sidebar-space-action]');
      if (actionBtn) {
        event.preventDefault();
        event.stopPropagation();
        const action = String(actionBtn.getAttribute('data-sidebar-space-action') || '').trim();
        const spaceId = String(actionBtn.getAttribute('data-sidebar-space-id') || '').trim();
        if (!spaceId) return;
        if (action === 'rename') {
          renameSidebarSpace(spaceId);
          return;
        }
        if (action === 'delete') {
          deleteSidebarSpace(spaceId);
          return;
        }
      }

      if (sidebarOpenSpaceMenuId && !clickTarget.closest('[data-sidebar-space-menu], [data-sidebar-space-menu-toggle]')) {
        sidebarOpenSpaceMenuId = '';
        renderSidebarSpacesList(sidebarSpacesCache);
      }
    });

    window.addEventListener('spaces:changed', function (event) {
      const detail = event && event.detail && typeof event.detail === 'object'
        ? event.detail
        : {};
      const changedUserId = String(detail.userId || '').trim();
      if (changedUserId && changedUserId !== getTelemetryUserId()) return;
      if (detail.action === 'delete_space' && getCurrentPageId() === 'spaces' && getCurrentSidebarSpaceId() === String(detail.spaceId || '').trim()) {
        window.location.href = buildSidebarSpaceHref('');
        return;
      }
      refreshSidebarSpaces();
    });

    window.addEventListener('storage', function (event) {
      if (event.key === SIDEBAR_SPACES_COLLAPSED_KEY) {
        sidebarSpacesCollapsed = event.newValue === '1';
        syncSidebarSpacesCollapsedUi();
        return;
      }
      if (event.key !== SIDEBAR_SPACE_SYNC_KEY) return;
      refreshSidebarSpaces();
    });

    document.body.dataset.pageShellSidebarSpacesBound = '1';
  }

  function initLearningTelemetry() {
    if (window.__fangzhigongLearningTelemetryInitialized) return;
    window.__fangzhigongLearningTelemetryInitialized = true;

    const pageId = getCurrentPageId();
    const startedAt = Date.now();
    let stayReported = false;
    telemetrySessionState.pageId = pageId;
    telemetrySessionState.startedAt = startedAt;
    telemetrySessionState.stayReported = false;

    postLearningBehavior({
      behavior_type: 'page_view',
      page: pageId,
      title: document.title || pageId,
      label: 'page_view',
      meta: {
        referrer: document.referrer || ''
      }
    }, false);

    function flushPageStay(reason) {
      if (stayReported) return;
      stayReported = true;
      telemetrySessionState.stayReported = true;
      const durationSeconds = Math.max(0, (Date.now() - startedAt) / 1000);
      postLearningBehavior({
        behavior_type: 'page_stay',
        page: pageId,
        title: document.title || pageId,
        label: String(reason || 'pagehide'),
        duration_seconds: Number(durationSeconds.toFixed(3)),
        meta: {
          referrer: document.referrer || ''
        }
      }, true);
    }

    window.addEventListener('pagehide', function () {
      flushPageStay('pagehide');
    });

    document.addEventListener('click', function (event) {
      const target = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('[data-side-link], [data-track-action], a.back-link, .global-sidebar-space-root, .global-sidebar-space-create, .global-sidebar-space-item')
        : null;
      if (!target) return;

      const sideLink = target.getAttribute('data-side-link') || '';
      const href = target.getAttribute('href') || '';
      const action = target.getAttribute('data-track-action') || '';
      const label = (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);

      postLearningBehavior({
        behavior_type: 'navigation_click',
        page: pageId,
        target: normalizeTargetPage(sideLink || href || action),
        label: label || action || sideLink || href || 'navigation_click',
        title: document.title || pageId
      }, false);
    });
  }

  function markActiveSidebarLink() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    document.querySelectorAll('[data-side-link]').forEach(function (link) {
      const target = String(link.getAttribute('data-side-link') || '');
      if (target && (path.endsWith('/' + target) || path.endsWith(target))) {
        link.classList.add('active');
      }
    });
  }

  function formatLocalDate(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function buildDefaultStreakWeekDays() {
    const labels = ['一', '二', '三', '四', '五', '六', '日'];
    const now = new Date();
    if (Number.isNaN(now.getTime())) {
      return labels.map(function (label) {
        return { label: label, active: false, today: false, date: '' };
      });
    }

    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const weekdayIndex = (today.getDay() + 6) % 7;
    const weekStart = new Date(today);
    weekStart.setDate(today.getDate() - weekdayIndex);

    return labels.map(function (label, offset) {
      const nextDay = new Date(weekStart);
      nextDay.setDate(weekStart.getDate() + offset);
      return {
        label: label,
        active: false,
        today: offset === weekdayIndex,
        date: formatLocalDate(nextDay)
      };
    });
  }

  function normalizeStreakSummary(raw) {
    const base = raw && typeof raw === 'object' ? raw : {};
    const goal = Math.max(1, Number(base.week_goal_days) || STREAK_WIDGET_WEEK_GOAL);
    const weekActiveDays = Math.max(0, Number(base.week_active_days) || 0);
    const currentStreak = Math.max(0, Number(base.current_streak) || 0);
    const progressCurrentRaw = Number(base.progress_current);
    const progressCurrent = Number.isFinite(progressCurrentRaw)
      ? Math.max(0, Math.min(goal, Math.round(progressCurrentRaw)))
      : Math.min(goal, weekActiveDays);
    const fallbackWeekDays = buildDefaultStreakWeekDays();

    const weekDays = Array.isArray(base.week_days) && base.week_days.length === 7
      ? base.week_days.map(function (item, index) {
          const fallback = fallbackWeekDays[index] || {};
          return {
            label: String((item && item.label) || fallback.label || '').trim() || fallback.label || '',
            active: !!(item && item.active),
            today: !!(item && item.today),
            date: String((item && item.date) || fallback.date || '').trim()
          };
        })
      : fallbackWeekDays;

    const progressLabel = String(base.progress_label || `${progressCurrent}/${goal}`).trim() || `${progressCurrent}/${goal}`;
    const status = String(base.status || (progressCurrent >= goal ? 'started' : 'warming')).trim() || 'warming';
    const message = String(base.message || (progressCurrent >= goal
      ? '连续登录已开始，继续保持这个节奏。'
      : `本周登录 ${goal} 天以开始你的连续登录。`)).trim();
    const helper = String(base.helper || (progressCurrent >= goal
      ? (currentStreak > 0 ? `已连续登录 ${currentStreak} 天` : `本周已登录 ${weekActiveDays} 天`)
      : `还差 ${Math.max(0, goal - weekActiveDays)} 天即可点亮连续登录`)).trim();

    return {
      weekLabel: String(base.week_label || '本周').trim() || '本周',
      weekGoalDays: goal,
      weekActiveDays: weekActiveDays,
      progressCurrent: progressCurrent,
      progressLabel: progressLabel,
      currentStreak: currentStreak,
      status: status,
      message: message,
      helper: helper,
      weekDays: weekDays
    };
  }

  function getStreakIconMarkup(extraClassName) {
    const extra = String(extraClassName || '').trim();
    const classAttr = extra ? `global-streak-icon ${extra}` : 'global-streak-icon';
    return `
      <svg class="${classAttr}" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M10.2 1.7c.4 1.5.1 2.8-.8 3.9-.8 1-1.1 1.9-.9 2.8 2.1-.4 3.6-1.9 4.5-4.4 1.8 2 2.6 4 2.6 5.9 0 3.9-2.9 6.8-6.8 6.8S1.9 13.9 1.9 10.3c0-2.1 1-4.2 2.9-6.3.1 2 .8 3.5 2.1 4.5 0-1 .4-2 1.2-3 .9-1.2 1.6-2.5 2.1-3.8Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M10 9.2c1.7 1 2.6 2.1 2.6 3.3 0 1.5-1.2 2.7-2.7 2.7S7.2 14 7.2 12.5c0-.9.5-1.8 1.6-2.8.1.8.5 1.4 1.2 1.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>
    `;
  }

  function ensureStreakWidget() {
    let root = document.getElementById('globalStreakWidget');
    const dock = document.getElementById('globalStreakDock');
    const host = dock || document.body;

    if (root) {
      if (root.parentNode !== host) {
        host.appendChild(root);
      }
      root.classList.toggle('is-inline-anchor', !!dock);
      return root;
    }

    root = document.createElement('div');
    root.id = 'globalStreakWidget';
    root.className = 'global-streak-widget';
    root.innerHTML = `
      <button
        type="button"
        class="global-streak-trigger"
        id="globalStreakTrigger"
        aria-expanded="false"
        aria-controls="globalStreakPopover"
        aria-label="查看连续登录进度"
      >
        ${getStreakIconMarkup()}
        <span class="global-streak-trigger-text">0/2</span>
      </button>
      <div class="global-streak-popover" id="globalStreakPopover" hidden></div>
    `;
    root.classList.toggle('is-inline-anchor', !!dock);
    host.appendChild(root);

    const trigger = document.getElementById('globalStreakTrigger');
    if (trigger && !trigger.dataset.pageShellBound) {
      trigger.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setStreakWidgetOpen(trigger.getAttribute('aria-expanded') !== 'true');
      });
      trigger.dataset.pageShellBound = '1';
    }

    return root;
  }

  function getStreakWidgetConflictAnchor() {
    const selectors = [
      '#authTopSlot',
      '.dashboard-actions',
      '.topbar .links',
      '#spaceUserLabel',
      '.space-reader-topbar'
    ];

    for (let index = 0; index < selectors.length; index += 1) {
      const node = document.querySelector(selectors[index]);
      if (!node) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      if (rect.bottom <= 0 || rect.top >= Math.min(window.innerHeight, 180)) continue;
      return node;
    }

    return null;
  }

  function syncStreakWidgetOffset() {
    const root = document.getElementById('globalStreakWidget');
    if (!root) return;
    if (root.classList.contains('is-inline-anchor')) {
      root.style.top = '';
      return;
    }

    let topOffset = window.innerWidth <= 768 ? 12 : 18;
    const anchor = getStreakWidgetConflictAnchor();
    if (anchor) {
      const rect = anchor.getBoundingClientRect();
      topOffset = Math.max(topOffset, Math.round(rect.bottom + (window.innerWidth <= 768 ? 8 : 12)));
    }

    root.style.top = `${topOffset}px`;
  }

  function setStreakWidgetOpen(nextOpen) {
    const trigger = document.getElementById('globalStreakTrigger');
    const popover = document.getElementById('globalStreakPopover');
    if (!trigger || !popover) return;

    const isOpen = !!nextOpen;
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    popover.hidden = !isOpen;
    syncStreakWidgetOffset();
  }

  function renderStreakWidget(summary) {
    const root = ensureStreakWidget();
    if (!root) return;

    const trigger = document.getElementById('globalStreakTrigger');
    const label = root.querySelector('.global-streak-trigger-text');
    const popover = document.getElementById('globalStreakPopover');
    const normalized = normalizeStreakSummary(summary);
    streakWidgetSummary = normalized;

    if (label) {
      label.textContent = normalized.progressLabel;
    }
    if (trigger) {
      trigger.setAttribute('aria-label', `${normalized.weekLabel}连续登录进度 ${normalized.progressLabel}`);
    }
    if (popover) {
      popover.innerHTML = `
        <div class="global-streak-card-value">
          ${getStreakIconMarkup()}
          <span>${esc(normalized.progressLabel)}</span>
        </div>
        <div class="global-streak-card-title">${esc(normalized.weekLabel)}</div>
        <div class="global-streak-card-copy">
          <div class="global-streak-card-copy-text">${esc(normalized.message)}</div>
          <span class="global-streak-card-badge">${esc(normalized.progressLabel)}</span>
        </div>
        <div class="global-streak-helper">${esc(normalized.helper)}</div>
        <div class="global-streak-week">
          ${normalized.weekDays.map(function (item) {
            const classNames = ['global-streak-day'];
            if (item.active) classNames.push('active');
            if (item.today) classNames.push('today');
            return `
              <div class="${classNames.join(' ')}" title="${esc(item.date)}">
                <span class="global-streak-day-dot" aria-hidden="true"></span>
                <span class="global-streak-day-label">${esc(item.label)}</span>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    syncStreakWidgetOffset();
  }

  async function refreshGlobalStreakWidget() {
    ensureStreakWidget();
    if (!streakWidgetSummary) {
      renderStreakWidget(null);
    }

    const apiBase = getTelemetryApiBase();
    if (!apiBase || typeof window.fetch !== 'function') return;

    const requestToken = ++streakWidgetRequestToken;
    const userId = getTelemetryUserId();
    const url = `${apiBase}/api/dashboard/streak?user_id=${encodeURIComponent(userId)}&_t=${Date.now()}`;

    try {
      const response = await window.fetch(url, { method: 'GET' });
      const payload = window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function'
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();
      if (requestToken !== streakWidgetRequestToken) return;
      renderStreakWidget(payload && payload.streak ? payload.streak : null);
    } catch (error) {
      if (requestToken !== streakWidgetRequestToken) return;
      renderStreakWidget(streakWidgetSummary);
    }
  }

  function initGlobalStreakWidget() {
    ensureStreakWidget();
    syncStreakWidgetOffset();

    if (window.__fangzhigongGlobalStreakWidgetInitialized) {
      return;
    }
    window.__fangzhigongGlobalStreakWidgetInitialized = true;

    document.addEventListener('click', function (event) {
      const root = document.getElementById('globalStreakWidget');
      if (!root) return;
      if (event.target && root.contains(event.target)) return;
      setStreakWidgetOpen(false);
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        setStreakWidgetOpen(false);
      }
    });

    window.addEventListener('resize', syncStreakWidgetOffset);
    window.addEventListener('scroll', syncStreakWidgetOffset, { passive: true });
    window.addEventListener('pageshow', function () {
      syncStreakWidgetOffset();
      refreshGlobalStreakWidget();
    });
    window.addEventListener('focus', refreshGlobalStreakWidget);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        syncStreakWidgetOffset();
        refreshGlobalStreakWidget();
      }
    });

    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        setStreakWidgetOpen(false);
        refreshGlobalStreakWidget();
      });
    }

    if (!streakWidgetRefreshTimer) {
      streakWidgetRefreshTimer = window.setInterval(refreshGlobalStreakWidget, STREAK_WIDGET_REFRESH_MS);
    }

    refreshGlobalStreakWidget();
  }

  function initGlobalSidebar() {
    initGlobalStreakWidget();

    const toggle = document.getElementById('globalSidebarToggle');
    const drawer = document.getElementById('globalSidebar');
    const backdrop = document.getElementById('globalSidebarBackdrop');
    const guestClose = document.getElementById('guestSidebarClose');
    if (!toggle || !drawer || !backdrop) return;

    const syncToggleState = function (isOpen) {
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      toggle.setAttribute('aria-label', isOpen ? '收起侧栏' : '打开侧栏');
    };

    const openDrawer = function () {
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
      syncToggleState(true);
    };

    const closeDrawer = function () {
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
      syncToggleState(false);
    };

    if (!toggle.dataset.pageShellBound) {
      toggle.addEventListener('click', function () {
        if (drawer.classList.contains('open')) {
          closeDrawer();
          return;
        }
        openDrawer();
      });
      toggle.dataset.pageShellBound = '1';
    }

    if (!backdrop.dataset.pageShellBound) {
      backdrop.addEventListener('click', closeDrawer);
      backdrop.dataset.pageShellBound = '1';
    }

    if (guestClose && !guestClose.dataset.pageShellBound) {
      guestClose.addEventListener('click', closeDrawer);
      guestClose.dataset.pageShellBound = '1';
    }

    if (!document.body.dataset.pageShellEscBound) {
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          closeDrawer();
        }
      });
      document.body.dataset.pageShellEscBound = '1';
    }

    markActiveSidebarLink();
    bindSidebarSpaceEvents();
    refreshSidebarSpaces();
    syncToggleState(drawer.classList.contains('open'));
  }

  window.PageShell = {
    closeGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      const toggle = document.getElementById('globalSidebarToggle');
      if (!drawer || !backdrop) return;
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', '打开侧栏');
      }
    },
    openGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      const toggle = document.getElementById('globalSidebarToggle');
      if (!drawer || !backdrop) return;
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-label', '收起侧栏');
      }
    },
    initGlobalSidebar: initGlobalSidebar,
    markActiveSidebarLink: markActiveSidebarLink,
    refreshSidebarSpaces: refreshSidebarSpaces,
    refreshGlobalStreakWidget: refreshGlobalStreakWidget,
    trackLearningAction: function (action, payload) {
      postLearningBehavior({
        behavior_type: String(action || '').trim() || 'action_click',
        page: getCurrentPageId(),
        ...(payload && typeof payload === 'object' ? payload : {})
      }, false);
    },
    getCurrentPageId: getCurrentPageId,
    getLiveStaySeconds: function (pageId) {
      if (!telemetrySessionState.startedAt || telemetrySessionState.stayReported) return 0;
      if (pageId && String(pageId).trim() !== telemetrySessionState.pageId) return 0;
      return Math.max(0, (Date.now() - telemetrySessionState.startedAt) / 1000);
    }
  };

  function initPageShellRuntime() {
    initLearningTelemetry();
    initGlobalStreakWidget();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageShellRuntime, { once: true });
  } else {
    initPageShellRuntime();
  }
})();
