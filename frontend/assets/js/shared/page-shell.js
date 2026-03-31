(function () {
  const telemetrySessionState = {
    pageId: '',
    startedAt: 0,
    stayReported: false
  };

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
        ? event.target.closest('[data-side-link], [data-track-action], a.back-link')
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

  function initGlobalSidebar() {
    const toggle = document.getElementById('globalSidebarToggle');
    const drawer = document.getElementById('globalSidebar');
    const backdrop = document.getElementById('globalSidebarBackdrop');
    if (!toggle || !drawer || !backdrop) return;

    const openDrawer = function () {
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
    };

    const closeDrawer = function () {
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
    };

    if (!toggle.dataset.pageShellBound) {
      toggle.addEventListener('click', openDrawer);
      toggle.dataset.pageShellBound = '1';
    }

    if (!backdrop.dataset.pageShellBound) {
      backdrop.addEventListener('click', closeDrawer);
      backdrop.dataset.pageShellBound = '1';
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
  }

  window.PageShell = {
    closeGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      if (!drawer || !backdrop) return;
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
    },
    openGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      if (!drawer || !backdrop) return;
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
    },
    initGlobalSidebar: initGlobalSidebar,
    markActiveSidebarLink: markActiveSidebarLink,
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLearningTelemetry, { once: true });
  } else {
    initLearningTelemetry();
  }
})();
