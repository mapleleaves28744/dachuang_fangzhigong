(function () {
  const DEFAULT_LOCALE = 'CN';
  const THEME_STORAGE_KEY = 'fangzhigong_theme_pref';
  const CHAT_MODE_STORAGE_KEY = 'fangzhigong_chat_mode_pref';
  let currentMode = 'login';
  let modalBound = false;
  let menuBound = false;
  let settingsBound = false;
  let activeSettingsTab = 'account';
  let settingsMessage = '';
  let activeMenuAnchorId = '';
  let isDeletingAccount = false;

  function getApiBase() {
    if (window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function') {
      return window.ApiUtils.getApiBase();
    }
    return window.location.origin || '';
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeStorageGet(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      // 忽略只读存储或隐私模式错误，保持页面可继续使用。
    }
    return value;
  }

  function formatExpireText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDateText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: '2-digit'
    });
  }

  function formatDateTimeText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function getThemePreference() {
    const raw = String(safeStorageGet(THEME_STORAGE_KEY, 'light') || '').trim().toLowerCase();
    return raw === 'dark' ? 'dark' : 'light';
  }

  function setThemePreference(value) {
    const normalized = String(value || '').trim().toLowerCase() === 'dark' ? 'dark' : 'light';
    safeStorageSet(THEME_STORAGE_KEY, normalized);
    applyPreferences();
    return normalized;
  }

  function getChatModePreference() {
    const raw = String(safeStorageGet(CHAT_MODE_STORAGE_KEY, 'auto') || '').trim().toLowerCase();
    return raw === 'focus' ? 'focus' : 'auto';
  }

  function setChatModePreference(value) {
    const normalized = String(value || '').trim().toLowerCase() === 'focus' ? 'focus' : 'auto';
    safeStorageSet(CHAT_MODE_STORAGE_KEY, normalized);
    applyPreferences();
    return normalized;
  }

  function applyPreferences() {
    document.documentElement.setAttribute('data-fangzhigong-theme', getThemePreference());
    document.documentElement.setAttribute('data-fangzhigong-chat-mode', getChatModePreference());
  }

  function getContext() {
    const auth = window.UserContext && typeof window.UserContext.getAuthState === 'function'
      ? window.UserContext.getAuthState()
      : { authenticated: false, user: null };
    const locale = window.UserContext && typeof window.UserContext.getLocale === 'function'
      ? window.UserContext.getLocale()
      : DEFAULT_LOCALE;

    return {
      api: getApiBase(),
      auth,
      locale,
      userId: window.UserContext && typeof window.UserContext.getUserId === 'function'
        ? window.UserContext.getUserId()
        : 'default_user',
      displayName: window.UserContext && typeof window.UserContext.getDisplayName === 'function'
        ? window.UserContext.getDisplayName()
        : '同学',
      userLabel: window.UserContext && typeof window.UserContext.getUserLabel === 'function'
        ? window.UserContext.getUserLabel()
        : '访客',
      theme: getThemePreference(),
      chatMode: getChatModePreference()
    };
  }

  function getAuthenticatedDisplayName(ctx) {
    const auth = ctx && ctx.auth;
    if (auth && auth.authenticated && auth.user) {
      return auth.user.display_name || auth.user.username || ctx.displayName || '同学';
    }
    return '登录';
  }

  function isHomePage() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    const last = path.split('/').pop() || 'index.html';
    return !last || last === 'index.html';
  }

  function normalizeSettingsTab(tab) {
    if (tab === 'personalization') return 'personalization';
    if (tab === 'data-control') return 'data-control';
    return 'account';
  }

  function getMenuAnchorById(id) {
    return id ? document.getElementById(id) : null;
  }

  function ensureTopSlot() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return null;
    let slot = document.getElementById('authTopSlot');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'authTopSlot';
      slot.className = 'auth-top-slot';
      navbar.appendChild(slot);
    }
    return slot;
  }

  function ensureSidebarSlot() {
    const sidebar = document.getElementById('globalSidebar');
    if (!sidebar) return null;
    let slot = document.getElementById('globalSidebarAuth');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'globalSidebarAuth';
      slot.className = 'global-sidebar-auth';
      sidebar.appendChild(slot);
    }
    return slot;
  }

  function ensureModal() {
    let modal = document.getElementById('authModal');
    if (modal) return modal;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-modal" id="authModal" aria-hidden="true">
        <div class="auth-modal-panel" role="dialog" aria-modal="true" aria-labelledby="authModalBrand">
          <button type="button" class="auth-modal-close" id="authModalClose" aria-label="关闭登录面板">×</button>
          <div class="auth-modal-brand" id="authModalBrand">坊知工账号</div>
          <div class="auth-modal-subtitle" id="authModalSubtitle">登录后即可同步你的空间、图谱和学习计划。</div>

          <div class="auth-tabs" id="authTabs">
            <button type="button" class="auth-tab active" data-auth-mode="login">登录</button>
            <button type="button" class="auth-tab" data-auth-mode="register">注册</button>
          </div>

          <form class="auth-form" id="authForm">
            <label class="auth-field">
              <span>账号</span>
              <input id="authUsernameInput" type="text" placeholder="3-32 位字母、数字或 . _ @ -" autocomplete="username">
            </label>

            <label class="auth-field auth-register-only" id="authDisplayNameField" hidden>
              <span>昵称</span>
              <input id="authDisplayNameInput" type="text" placeholder="用于页面展示，如 小杭" autocomplete="nickname">
            </label>

            <label class="auth-field">
              <span>密码</span>
              <input id="authPasswordInput" type="password" placeholder="至少 6 位" autocomplete="current-password">
            </label>

            <div class="auth-actions">
              <button type="submit" class="auth-submit-btn" id="authSubmitBtn">登录</button>
              <button type="button" class="auth-secondary-btn" id="authSwitchModeBtn">没有账号？去注册</button>
            </div>
            <div class="auth-error" id="authErrorText"></div>
            <div class="auth-tip" id="authTipText">账号支持 3-32 位字母、数字以及 . _ @ - 。</div>
          </form>
        </div>
      </div>
    `);

    return document.getElementById('authModal');
  }

  function ensureMenu() {
    let menu = document.getElementById('authUserMenu');
    if (menu) return menu;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-user-menu" id="authUserMenu" hidden>
        <div class="auth-user-menu-card" role="menu" aria-label="账号菜单">
          <button type="button" class="auth-user-menu-item" data-auth-menu-action="settings">
            ${getIconMarkup('settings')}
            <span>设置</span>
          </button>
          <button type="button" class="auth-user-menu-item danger" data-auth-menu-action="logout">
            ${getIconMarkup('logout')}
            <span>退出登录</span>
          </button>
        </div>
      </div>
    `);

    return document.getElementById('authUserMenu');
  }

  function ensureSettingsModal() {
    let modal = document.getElementById('authSettingsModal');
    if (modal) return modal;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-settings-modal" id="authSettingsModal" aria-hidden="true">
        <div class="auth-settings-panel" role="dialog" aria-modal="true" aria-labelledby="authSettingsTitle">
          <div class="auth-settings-sidebar">
            <button type="button" class="auth-settings-close" id="authSettingsCloseBtn" aria-label="关闭设置面板">×</button>
            <div class="auth-settings-title" id="authSettingsTitle">设置</div>
            <div class="auth-settings-nav" id="authSettingsNav"></div>
          </div>
          <div class="auth-settings-content">
            <div class="auth-settings-body" id="authSettingsBody"></div>
            <div class="auth-settings-note" id="authSettingsNote"></div>
          </div>
        </div>
      </div>
    `);

    return document.getElementById('authSettingsModal');
  }

  function getIconMarkup(name) {
    switch (name) {
      case 'settings':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3.2"></circle>
            <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.76l.06.06a1.92 1.92 0 1 1-2.72 2.72l-.06-.06A1.6 1.6 0 0 0 15 19.4a1.6 1.6 0 0 0-.96 1.46V21a1.92 1.92 0 1 1-3.84 0v-.14A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.76.32l-.06.06a1.92 1.92 0 1 1-2.72-2.72l.06-.06A1.6 1.6 0 0 0 4.6 15a1.6 1.6 0 0 0-1.46-.96H3a1.92 1.92 0 1 1 0-3.84h.14A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.32-1.76l-.06-.06a1.92 1.92 0 1 1 2.72-2.72l.06.06A1.6 1.6 0 0 0 9 4.6a1.6 1.6 0 0 0 .96-1.46V3a1.92 1.92 0 1 1 3.84 0v.14A1.6 1.6 0 0 0 15 4.6a1.6 1.6 0 0 0 1.76-.32l.06-.06a1.92 1.92 0 1 1 2.72 2.72l-.06.06A1.6 1.6 0 0 0 19.4 9c0 .4.15.78.42 1.07.28.28.66.43 1.07.43H21a1.92 1.92 0 1 1 0 3.84h-.11A1.6 1.6 0 0 0 19.4 15Z"></path>
          </svg>
        `;
      case 'logout':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <path d="M16 17l5-5-5-5"></path>
            <path d="M21 12H9"></path>
          </svg>
        `;
      case 'account':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 21a8 8 0 0 0-16 0"></path>
            <circle cx="12" cy="8" r="4"></circle>
          </svg>
        `;
      case 'personalization':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0 0 6"></path>
            <path d="M5.6 5.6a3 3 0 0 0 4.24 4.24"></path>
            <path d="M3 12a3 3 0 0 0 6 0"></path>
            <path d="M5.6 18.4a3 3 0 0 0 4.24-4.24"></path>
            <path d="M12 21a3 3 0 0 0 0-6"></path>
            <path d="M18.4 18.4a3 3 0 0 0-4.24-4.24"></path>
            <path d="M21 12a3 3 0 0 0-6 0"></path>
            <path d="M18.4 5.6a3 3 0 0 0-4.24 4.24"></path>
          </svg>
        `;
      case 'data':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <ellipse cx="12" cy="5" rx="7" ry="3"></ellipse>
            <path d="M5 5v14c0 1.66 3.13 3 7 3s7-1.34 7-3V5"></path>
            <path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3"></path>
          </svg>
        `;
      default:
        return '';
    }
  }

  function getDefaultTipText() {
    return currentMode === 'register'
      ? '注册后会自动登录到当前项目。'
      : '登录后即可在所有页面共用同一账号。';
  }

  function setFeedback(type, message) {
    const errorEl = document.getElementById('authErrorText');
    const tipEl = document.getElementById('authTipText');
    const nextMessage = String(message || '').trim();

    if (errorEl) {
      errorEl.textContent = type === 'error' ? nextMessage : '';
    }

    if (tipEl) {
      tipEl.textContent = type === 'error' ? '' : (nextMessage || getDefaultTipText());
      tipEl.classList.toggle('is-success', type === 'success');
    }
  }

  function updateModeUI() {
    const tabs = document.querySelectorAll('[data-auth-mode]');
    const displayNameField = document.getElementById('authDisplayNameField');
    const submitBtn = document.getElementById('authSubmitBtn');
    const switchBtn = document.getElementById('authSwitchModeBtn');
    const subtitle = document.getElementById('authModalSubtitle');

    tabs.forEach(function (tab) {
      tab.classList.toggle('active', tab.getAttribute('data-auth-mode') === currentMode);
    });

    if (displayNameField) displayNameField.hidden = currentMode !== 'register';
    if (submitBtn) submitBtn.textContent = currentMode === 'register' ? '注册并登录' : '登录';
    if (switchBtn) switchBtn.textContent = currentMode === 'register' ? '已有账号？去登录' : '没有账号？去注册';

    if (subtitle) {
      subtitle.textContent = currentMode === 'register'
        ? '注册后会自动建立会话，并把学习数据绑定到你的账号。'
        : '登录后即可同步你的空间、图谱和学习计划。';
    }
  }

  function renderTopSlot() {
    const slot = ensureTopSlot();
    if (!slot) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const label = esc(getAuthenticatedDisplayName(ctx));
    const buttonClass = auth && auth.authenticated ? 'auth-top-button is-authenticated' : 'auth-top-button';
    const buttonAttrs = auth && auth.authenticated ? 'aria-haspopup="menu" aria-expanded="false"' : '';

    slot.innerHTML = `
      <button type="button" class="${buttonClass}" id="authTopActionBtn" ${buttonAttrs}>${label}</button>
    `;

    const actionBtn = document.getElementById('authTopActionBtn');

    if (actionBtn) {
      actionBtn.addEventListener('click', function () {
        if (auth && auth.authenticated) {
          openQuickMenu(this);
        } else {
          openModal('login');
        }
      });
    }
  }

  function renderSidebarSlot() {
    const slot = ensureSidebarSlot();
    if (!slot) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const label = esc(getAuthenticatedDisplayName(ctx));
    const buttonClass = auth && auth.authenticated ? 'auth-sidebar-button is-authenticated' : 'auth-sidebar-button';
    const buttonAttrs = auth && auth.authenticated ? 'aria-haspopup="menu" aria-expanded="false"' : '';

    slot.innerHTML = `
      <button type="button" class="${buttonClass}" id="authSidebarActionBtn" ${buttonAttrs}>${label}</button>
    `;

    const btn = document.getElementById('authSidebarActionBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        if (auth && auth.authenticated) {
          openQuickMenu(this);
        } else {
          openModal('login');
        }
      });
    }
  }

  function renderStatusCard() {
    const body = document.getElementById('authStatusCard');
    const actions = document.getElementById('authStatusCardActions');
    if (!body || !actions) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const isLoggedIn = !!(auth && auth.authenticated && auth.user);

    body.innerHTML = isLoggedIn
      ? `
        <div class="auth-status-card">
          <div class="auth-status-badge is-authenticated">已登录</div>
          <div class="auth-status-title">${esc(auth.user.display_name || auth.user.username || '同学')}</div>
          <div class="auth-status-meta">账号：${esc(auth.user.username || ctx.userId)}<br>会话有效期：${esc(formatExpireText(auth.expires_at))}</div>
        </div>
      `
      : `
        <div class="auth-status-card">
          <div class="auth-status-badge is-guest">访客模式</div>
          <div class="auth-status-title">未登录</div>
          <div class="auth-status-meta">当前仍可继续浏览，但学习空间、图谱和计划会以本地访客身份保存。登录后会自动绑定到账号。</div>
        </div>
      `;

    actions.innerHTML = isLoggedIn
      ? `
        <button type="button" class="auth-mini-btn" id="authCardOpenBtn">打开设置</button>
        <button type="button" class="auth-mini-btn secondary" id="authCardLogoutBtn">退出登录</button>
      `
      : `
        <button type="button" class="auth-mini-btn secondary" id="authCardLoginBtn">打开登录面板</button>
      `;

    const openBtn = document.getElementById('authCardOpenBtn');
    const logoutBtn = document.getElementById('authCardLogoutBtn');
    const loginBtn = document.getElementById('authCardLoginBtn');

    if (openBtn) {
      openBtn.addEventListener('click', function () {
        openSettingsModal('account');
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', handleLogout);
    }

    if (loginBtn) {
      loginBtn.addEventListener('click', function () {
        openModal('login');
      });
    }
  }

  function getProfileCompletion(ctx) {
    const auth = ctx && ctx.auth;
    if (!(auth && auth.authenticated && auth.user)) return 0;

    let score = 60;
    if (String(auth.user.display_name || '').trim()) score += 20;
    if (String(auth.user.created_at || '').trim()) score += 20;
    return Math.min(100, score);
  }

  function buildSettingsNav() {
    const items = [
      { key: 'account', label: '账户', icon: 'account' },
      { key: 'personalization', label: '个性化', icon: 'personalization' },
      { key: 'data-control', label: '数据控制', icon: 'data' }
    ];

    return items.map(function (item) {
      const active = item.key === activeSettingsTab ? 'active' : '';
      return `
        <button type="button" class="auth-settings-nav-btn ${active}" data-settings-tab="${item.key}">
          ${getIconMarkup(item.icon)}
          <span>${item.label}</span>
        </button>
      `;
    }).join('');
  }

  function buildAccountSettings(ctx) {
    const auth = ctx.auth;
    const user = auth && auth.user ? auth.user : {};
    const displayName = user.display_name || user.username || ctx.displayName || '同学';
    const username = user.username || ctx.userId || 'default_user';
    const accountLabel = username.includes('@') ? '电子邮件' : '账号';
    const completion = getProfileCompletion(ctx);
    const heroText = completion >= 100
      ? '账号资料已准备完成，可继续获取个性化内容。'
      : '补全账号资料后，系统会更稳定地展示个性化内容。';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-hero">
          <div class="auth-settings-hero-icon"><span>${completion}%</span></div>
          <div class="auth-settings-hero-copy">
            <div class="auth-settings-hero-title">完整简介</div>
            <div class="auth-settings-hero-text">${esc(heroText)}</div>
          </div>
          <button type="button" class="auth-settings-hero-btn">完整</button>
        </div>

        <div class="auth-settings-list">
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">名称</div>
            <div class="auth-settings-row-value">${esc(displayName)}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">${accountLabel}</div>
            <div class="auth-settings-row-value">${esc(username)}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">创建日期</div>
            <div class="auth-settings-row-value">${esc(formatDateText(user.created_at))}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">最近登录</div>
            <div class="auth-settings-row-value">${esc(formatDateTimeText(user.last_login_at || auth.expires_at))}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">会话有效期</div>
            <div class="auth-settings-row-value">${esc(formatExpireText(auth.expires_at))}</div>
          </div>
        </div>
      </section>
    `;
  }

  function buildPersonalizationSettings(ctx) {
    const theme = ctx.theme || 'light';
    const chatMode = ctx.chatMode || 'auto';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-list">
          <div class="auth-settings-row auth-settings-row-select">
            <div class="auth-settings-row-label">主题</div>
            <select class="auth-settings-select" id="authSettingsThemeSelect" aria-label="主题">
              <option value="light" ${theme === 'light' ? 'selected' : ''}>灯光</option>
            </select>
          </div>
          <div class="auth-settings-row auth-settings-row-select">
            <div class="auth-settings-row-label">聊天模式</div>
            <select class="auth-settings-select" id="authSettingsChatModeSelect" aria-label="聊天模式">
              <option value="auto" ${chatMode === 'auto' ? 'selected' : ''}>Auto</option>
              <option value="focus" ${chatMode === 'focus' ? 'selected' : ''}>专注</option>
            </select>
          </div>
        </div>
      </section>
    `;
  }

  function buildDataControlSettings(ctx) {
    const auth = ctx && ctx.auth;
    const user = auth && auth.user ? auth.user : {};
    const username = user.username || (ctx && ctx.userId) || '当前账号';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-danger">
          <div class="auth-settings-danger-row">
            <div>
              <div class="auth-settings-danger-title">删除账户</div>
              <div class="auth-settings-danger-copy">删除后会清空账号 ${esc(username)} 的学习计划、知识图谱和登录会话，且无法恢复。</div>
            </div>
            <button type="button" class="auth-settings-delete-btn" id="authSettingsDeleteBtn" ${isDeletingAccount ? 'disabled' : ''}>${isDeletingAccount ? '删除中...' : '删除'}</button>
          </div>
        </div>
      </section>
    `;
  }

  function getSettingsNoteText() {
    if (settingsMessage) return settingsMessage;
    if (activeSettingsTab === 'personalization') {
      return '主题和聊天模式偏好会保存在当前浏览器。';
    }
    if (activeSettingsTab === 'data-control') {
      return '删除账户后会立即清空当前账号数据，并退出登录。';
    }
    return '账号信息会跟随当前登录态自动刷新。';
  }

  function renderSettingsModal() {
    const modal = ensureSettingsModal();
    const nav = document.getElementById('authSettingsNav');
    const body = document.getElementById('authSettingsBody');
    const note = document.getElementById('authSettingsNote');
    const ctx = getContext();
    const auth = ctx.auth;

    if (!(auth && auth.authenticated && auth.user)) {
      closeSettingsModal();
      openModal('login');
      return;
    }

    if (nav) nav.innerHTML = buildSettingsNav();

    if (body) {
      if (activeSettingsTab === 'personalization') {
        body.innerHTML = buildPersonalizationSettings(ctx);
      } else if (activeSettingsTab === 'data-control') {
        body.innerHTML = buildDataControlSettings(ctx);
      } else {
        body.innerHTML = buildAccountSettings(ctx);
      }
    }

    if (note) note.textContent = getSettingsNoteText();
    modal.setAttribute('aria-hidden', 'false');
  }

  function openModal(mode) {
    const auth = getContext().auth;
    if (auth && auth.authenticated) {
      openSettingsModal('account');
      return;
    }

    const modal = ensureModal();
    currentMode = mode === 'register' ? 'register' : 'login';
    updateModeUI();
    setFeedback('tip', getDefaultTipText());
    closeQuickMenu();
    closeSettingsModal();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    const input = document.getElementById('authUsernameInput');
    if (input) {
      setTimeout(function () {
        input.focus();
      }, 20);
    }
  }

  function closeModal() {
    const modal = document.getElementById('authModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
  }

  function positionUserMenu(anchor) {
    const menu = ensureMenu();
    if (!anchor || menu.hidden) return;

    const rect = anchor.getBoundingClientRect();
    const width = menu.offsetWidth || 248;
    const height = menu.offsetHeight || 150;
    let left = rect.right - width;
    let top = rect.bottom + 12;

    if (left < 12) left = 12;
    if (left + width > window.innerWidth - 12) {
      left = window.innerWidth - width - 12;
    }
    if (top + height > window.innerHeight - 12) {
      top = rect.top - height - 12;
    }
    if (top < 12) top = 12;

    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function openQuickMenu(anchor) {
    const ctx = getContext();
    if (!(ctx.auth && ctx.auth.authenticated)) {
      openModal('login');
      return;
    }

    const menu = ensureMenu();
    const nextAnchorId = anchor && anchor.id ? anchor.id : '';
    const sameAnchorOpen = !menu.hidden && activeMenuAnchorId === nextAnchorId;
    closeQuickMenu();
    if (sameAnchorOpen) return;

    activeMenuAnchorId = nextAnchorId;
    menu.hidden = false;
    menu.classList.add('show');
    positionUserMenu(anchor);
    if (anchor) anchor.setAttribute('aria-expanded', 'true');
  }

  function closeQuickMenu() {
    const menu = document.getElementById('authUserMenu');
    if (!menu) return;

    const anchor = getMenuAnchorById(activeMenuAnchorId);
    if (anchor) anchor.setAttribute('aria-expanded', 'false');

    activeMenuAnchorId = '';
    menu.hidden = true;
    menu.classList.remove('show');
    menu.style.left = '';
    menu.style.top = '';
  }

  function openSettingsModal(tab) {
    const ctx = getContext();
    if (!(ctx.auth && ctx.auth.authenticated)) {
      openModal('login');
      return;
    }

    activeSettingsTab = normalizeSettingsTab(tab);
    settingsMessage = '';
    closeQuickMenu();
    closeModal();
    const modal = ensureSettingsModal();
    renderSettingsModal();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeSettingsModal() {
    const modal = document.getElementById('authSettingsModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
  }

  function isSettingsModalOpen() {
    const modal = document.getElementById('authSettingsModal');
    return !!(modal && modal.classList.contains('show'));
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    if (!window.UserContext) return;

    const auth = getContext().auth;
    if (auth && auth.authenticated) {
      openSettingsModal('account');
      return;
    }

    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    const displayNameInput = document.getElementById('authDisplayNameInput');
    const submitBtn = document.getElementById('authSubmitBtn');

    const username = String((usernameInput && usernameInput.value) || '').trim();
    const password = String((passwordInput && passwordInput.value) || '').trim();
    const displayName = String((displayNameInput && displayNameInput.value) || '').trim();
    const guestUserId = window.UserContext && typeof window.UserContext.getGuestUserId === 'function'
      ? window.UserContext.getGuestUserId()
      : 'default_user';

    if (!username || !password) {
      setFeedback('error', '请输入账号和密码。');
      return;
    }

    if (currentMode === 'register' && password.length < 6) {
      setFeedback('error', '注册密码至少需要 6 位。');
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = currentMode === 'register' ? '注册中...' : '登录中...';
    }

    setFeedback('tip', currentMode === 'register' ? '正在创建账号...' : '正在验证登录信息...');

    try {
      const endpoint = currentMode === 'register' ? '/api/auth/register' : '/api/auth/login';
      const payload = {
        username,
        password,
        guest_user_id: guestUserId
      };
      if (currentMode === 'register') {
        payload.display_name = displayName;
      }

      const response = await fetch(`${getApiBase()}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      const nextUserId = data && data.auth && data.auth.user
        ? (data.auth.user.user_id || data.auth.user.username || username)
        : username;

      if (window.ProjectLocalData && typeof window.ProjectLocalData.migrateGuestLocalData === 'function') {
        try {
          window.ProjectLocalData.migrateGuestLocalData(guestUserId, nextUserId, { maxChatSessions: 20 });
        } catch (migrationError) {
          // 本地数据迁移失败不阻塞登录，只保留账号会话。
        }
      }

      if (data && data.auth && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth(data.auth);
      }

      if (displayNameInput) displayNameInput.value = '';
      if (passwordInput) passwordInput.value = '';

      const binding = data && data.binding && typeof data.binding === 'object' ? data.binding : null;
      const successMessage = binding && binding.migrated
        ? `${currentMode === 'register' ? '注册成功' : '登录成功'}，访客数据已绑定到账号。`
        : (currentMode === 'register' ? '注册成功，已自动登录。' : '登录成功，正在同步页面账号...');
      setFeedback('success', successMessage);
      currentMode = 'login';
      renderAll();

      setTimeout(function () {
        closeModal();
      }, 420);
    } catch (error) {
      const message = error && error.message ? error.message : '登录失败，请稍后重试';
      setFeedback('error', message);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = currentMode === 'register' ? '注册并登录' : '登录';
      }
    }
  }

  function syncPageAuthState(ctx) {
    const auth = ctx && ctx.auth;
    const isAuthenticated = !!(auth && auth.authenticated);
    const guestHomeLayout = isHomePage() && !isAuthenticated;

    document.body.classList.toggle('guest-home-layout', guestHomeLayout);

    if (!guestHomeLayout) return;

    document.body.classList.remove('sidebar-open');
    const drawer = document.getElementById('globalSidebar');
    const backdrop = document.getElementById('globalSidebarBackdrop');
    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('show');
  }

  async function handleLogout() {
    closeQuickMenu();
    closeSettingsModal();

    try {
      const response = await fetch(`${getApiBase()}/api/auth/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });

      if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
        await window.ApiUtils.parseApiResponse(response);
      }
    } catch (error) {
      // 无论后端是否可达，都清理本地会话，避免卡在假登录状态。
    } finally {
      if (window.UserContext && typeof window.UserContext.clearAuth === 'function') {
        window.UserContext.clearAuth({ reason: 'logout', force: true });
      }
      currentMode = 'login';
      settingsMessage = '';
      renderAll();
      closeModal();
    }
  }

  async function handleDeleteAccount() {
    if (isDeletingAccount) return;

    const ctx = getContext();
    const auth = ctx.auth;
    if (!(auth && auth.authenticated && auth.user)) {
      closeSettingsModal();
      openModal('login');
      return;
    }

    const username = auth.user.username || ctx.userId || '当前账号';
    const label = auth.user.display_name || username;
    const confirmed = window.confirm(`确认删除账户“${label}”吗？\n删除后将清空该账号的学习计划、知识图谱和登录会话，且无法恢复。`);
    if (!confirmed) return;

    isDeletingAccount = true;
    settingsMessage = '正在删除账户...';
    renderSettingsModal();

    try {
      const response = await fetch(`${getApiBase()}/api/auth/account`, {
        method: 'DELETE',
        headers: {
          'Accept': 'application/json'
        }
      });

      if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
        await window.ApiUtils.parseApiResponse(response);
      } else {
        await response.json();
      }

      if (window.UserContext && typeof window.UserContext.clearAuth === 'function') {
        window.UserContext.clearAuth({ reason: 'account_deleted', force: true });
      }
      currentMode = 'login';
      settingsMessage = '';
      closeQuickMenu();
      closeSettingsModal();
      closeModal();
      renderAll();
      window.alert(`账户 ${username} 已删除，当前已退出登录。`);
    } catch (error) {
      settingsMessage = error && error.message ? error.message : '删除账户失败，请稍后重试。';
      renderSettingsModal();
    } finally {
      isDeletingAccount = false;
      if (isSettingsModalOpen()) {
        renderSettingsModal();
      }
    }
  }

  async function syncSessionSilently() {
    if (!window.UserContext || typeof window.UserContext.isAuthenticated !== 'function') return;
    if (!window.UserContext.isAuthenticated()) return;

    try {
      const response = await fetch(`${getApiBase()}/api/auth/me`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        }
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      if (data && data.auth && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth(data.auth);
      }
    } catch (error) {
      if (
        error &&
        error.code === 'AUTH_REQUIRED' &&
        window.UserContext &&
        typeof window.UserContext.clearAuth === 'function'
      ) {
        window.UserContext.clearAuth({ reason: 'expired' });
      }
    }
  }

  function bindModalEvents() {
    if (modalBound) return;

    const modal = ensureModal();
    const form = document.getElementById('authForm');
    const closeBtn = document.getElementById('authModalClose');
    const switchBtn = document.getElementById('authSwitchModeBtn');
    const tabs = document.querySelectorAll('[data-auth-mode]');

    if (form) {
      form.addEventListener('submit', handleAuthSubmit);
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }

    if (switchBtn) {
      switchBtn.addEventListener('click', function () {
        currentMode = currentMode === 'register' ? 'login' : 'register';
        setFeedback('tip', getDefaultTipText());
        updateModeUI();
      });
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        currentMode = this.getAttribute('data-auth-mode') === 'register' ? 'register' : 'login';
        setFeedback('tip', getDefaultTipText());
        updateModeUI();
      });
    });

    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeModal();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeQuickMenu();
        closeSettingsModal();
        closeModal();
      }
    });

    modalBound = true;
  }

  function bindMenuEvents() {
    if (menuBound) return;

    const menu = ensureMenu();

    menu.addEventListener('click', function (event) {
      const button = event.target.closest('[data-auth-menu-action]');
      if (!button) return;

      const action = button.getAttribute('data-auth-menu-action');
      if (action === 'settings') {
        closeQuickMenu();
        openSettingsModal('account');
        return;
      }

      if (action === 'logout') {
        closeQuickMenu();
        handleLogout();
      }
    });

    document.addEventListener('click', function (event) {
      const menuEl = document.getElementById('authUserMenu');
      if (!menuEl || menuEl.hidden) return;

      const clickedAnchor = event.target.closest('#authTopActionBtn, #authSidebarActionBtn');
      if (clickedAnchor) return;
      if (!menuEl.contains(event.target)) {
        closeQuickMenu();
      }
    });

    window.addEventListener('resize', function () {
      const anchor = getMenuAnchorById(activeMenuAnchorId);
      if (anchor) {
        positionUserMenu(anchor);
      } else {
        closeQuickMenu();
      }
    });

    window.addEventListener('scroll', function () {
      closeQuickMenu();
    }, true);

    menuBound = true;
  }

  function bindSettingsEvents() {
    if (settingsBound) return;

    const modal = ensureSettingsModal();

    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeSettingsModal();
        return;
      }

      const closeBtn = event.target.closest('#authSettingsCloseBtn');
      if (closeBtn) {
        closeSettingsModal();
        return;
      }

      const tabBtn = event.target.closest('[data-settings-tab]');
      if (tabBtn) {
        activeSettingsTab = normalizeSettingsTab(tabBtn.getAttribute('data-settings-tab'));
        settingsMessage = '';
        renderSettingsModal();
        return;
      }

      const deleteBtn = event.target.closest('#authSettingsDeleteBtn');
      if (deleteBtn) {
        handleDeleteAccount();
      }
    });

    modal.addEventListener('change', function (event) {
      const target = event.target;
      if (!target) return;

      if (target.id === 'authSettingsThemeSelect') {
        setThemePreference(target.value || 'light');
        settingsMessage = '主题偏好已保存。';
        renderSettingsModal();
        return;
      }

      if (target.id === 'authSettingsChatModeSelect') {
        setChatModePreference(target.value || 'auto');
        settingsMessage = '聊天模式偏好已保存。';
        renderSettingsModal();
      }
    });

    settingsBound = true;
  }

  function renderAll() {
    const ctx = getContext();
    closeQuickMenu();
    syncPageAuthState(ctx);
    renderTopSlot();
    renderSidebarSlot();
    renderStatusCard();
    updateModeUI();

    if (isSettingsModalOpen()) {
      renderSettingsModal();
    }
  }

  function init() {
    applyPreferences();
    ensureTopSlot();
    ensureSidebarSlot();
    ensureModal();
    ensureMenu();
    ensureSettingsModal();
    bindModalEvents();
    bindMenuEvents();
    bindSettingsEvents();
    renderAll();
    syncSessionSilently();

    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        renderAll();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
