(function () {
  const DEFAULT_LOCALE = 'CN';
  let currentMode = 'login';
  let modalBound = false;

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

  function getContext() {
    const api = getApiBase();
    const auth = window.UserContext && typeof window.UserContext.getAuthState === 'function'
      ? window.UserContext.getAuthState()
      : { authenticated: false, user: null };
    const locale = window.UserContext && typeof window.UserContext.getLocale === 'function'
      ? window.UserContext.getLocale()
      : DEFAULT_LOCALE;

    return {
      api,
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
        : '访客'
    };
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

            <label class="auth-field auth-register-only" id="authModalLocaleField" hidden>
              <span>界面语言</span>
              <select id="authModalLocaleSelect">
                <option value="CN">CN</option>
                <option value="EN">EN</option>
              </select>
            </label>

            <div class="auth-actions">
              <button type="submit" class="auth-submit-btn" id="authSubmitBtn">登录</button>
              <button type="button" class="auth-secondary-btn" id="authSwitchModeBtn">没有账号？去注册</button>
            </div>
            <div class="auth-error" id="authErrorText"></div>
            <div class="auth-tip" id="authTipText">账号支持 3-32 位字母、数字以及 `. _ @ -`。</div>
          </form>

          <div class="auth-account-view" id="authAccountView" hidden>
            <div class="auth-account-card">
              <div class="auth-account-name" id="authAccountName">同学</div>
              <div class="auth-account-id" id="authAccountId">@default_user</div>
              <div class="auth-account-grid">
                <div class="auth-account-item">
                  <div class="auth-account-label">界面语言</div>
                  <div class="auth-account-value" id="authAccountLocale">CN</div>
                </div>
                <div class="auth-account-item">
                  <div class="auth-account-label">会话有效期</div>
                  <div class="auth-account-value" id="authAccountExpire">未提供</div>
                </div>
              </div>
            </div>
            <div class="auth-actions">
              <button type="button" class="auth-secondary-btn" id="authCloseAccountBtn">继续使用</button>
              <button type="button" class="auth-danger-btn" id="authLogoutBtn">退出登录</button>
            </div>
            <div class="auth-success" id="authAccountHint">当前账号已在本浏览器保持登录。</div>
          </div>
        </div>
      </div>
    `);

    return document.getElementById('authModal');
  }

  function setFeedback(type, message) {
    const errorEl = document.getElementById('authErrorText');
    const tipEl = document.getElementById('authTipText');
    const accountHint = document.getElementById('authAccountHint');
    if (errorEl) errorEl.textContent = type === 'error' ? String(message || '') : '';
    if (tipEl) tipEl.textContent = type === 'tip' ? String(message || '') : (type === 'success' ? String(message || '') : '账号支持 3-32 位字母、数字以及 `. _ @ -`。');
    if (accountHint && type === 'success') {
      accountHint.textContent = String(message || '');
    }
  }

  function updateModeUI() {
    const auth = getContext().auth;
    const mode = auth && auth.authenticated ? 'account' : currentMode;
    const tabs = document.querySelectorAll('[data-auth-mode]');
    const form = document.getElementById('authForm');
    const accountView = document.getElementById('authAccountView');
    const displayNameField = document.getElementById('authDisplayNameField');
    const localeField = document.getElementById('authModalLocaleField');
    const submitBtn = document.getElementById('authSubmitBtn');
    const switchBtn = document.getElementById('authSwitchModeBtn');
    const subtitle = document.getElementById('authModalSubtitle');

    tabs.forEach(function (tab) {
      tab.classList.toggle('active', tab.getAttribute('data-auth-mode') === currentMode);
      tab.disabled = mode === 'account';
    });

    if (form) form.hidden = mode === 'account';
    if (accountView) accountView.hidden = mode !== 'account';

    if (displayNameField) displayNameField.hidden = currentMode !== 'register';
    if (localeField) localeField.hidden = currentMode !== 'register';

    if (submitBtn) {
      submitBtn.textContent = currentMode === 'register' ? '注册并登录' : '登录';
    }

    if (switchBtn) {
      switchBtn.textContent = currentMode === 'register' ? '已有账号？去登录' : '没有账号？去注册';
    }

    if (subtitle) {
      if (mode === 'account') {
        subtitle.textContent = '当前账号已在项目中生效，后续页面会自动读取登录身份。';
      } else if (currentMode === 'register') {
        subtitle.textContent = '注册后会自动建立会话，并把学习数据绑定到你的账号。';
      } else {
        subtitle.textContent = '登录后即可同步你的空间、图谱和学习计划。';
      }
    }
  }

  function renderTopSlot() {
    const slot = ensureTopSlot();
    if (!slot) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const topLabel = auth && auth.authenticated
      ? esc(auth.user.display_name || auth.user.username || '账号中心')
      : '登录';
    const buttonClass = auth && auth.authenticated ? 'auth-top-button is-authenticated' : 'auth-top-button';

    slot.innerHTML = `
      <label class="auth-locale-pill" title="界面语言偏好">
        <select class="auth-locale-select" id="authTopLocaleSelect" aria-label="选择界面语言">
          <option value="CN" ${ctx.locale === 'CN' ? 'selected' : ''}>CN</option>
          <option value="EN" ${ctx.locale === 'EN' ? 'selected' : ''}>EN</option>
        </select>
      </label>
      <button type="button" class="${buttonClass}" id="authTopActionBtn">${topLabel}</button>
    `;

    const localeSelect = document.getElementById('authTopLocaleSelect');
    const actionBtn = document.getElementById('authTopActionBtn');
    if (localeSelect) {
      localeSelect.addEventListener('change', function () {
        if (window.UserContext && typeof window.UserContext.setLocale === 'function') {
          window.UserContext.setLocale(this.value || DEFAULT_LOCALE);
        }
      });
    }
    if (actionBtn) {
      actionBtn.addEventListener('click', function () {
        openModal(auth && auth.authenticated ? 'account' : 'login');
      });
    }
  }

  function renderSidebarSlot() {
    const slot = ensureSidebarSlot();
    if (!slot) return;

    const auth = getContext().auth;
    const label = auth && auth.authenticated ? '账号中心' : '登录';
    const buttonClass = auth && auth.authenticated ? 'auth-sidebar-button is-authenticated' : 'auth-sidebar-button';

    slot.innerHTML = `<button type="button" class="${buttonClass}" id="authSidebarActionBtn">${label}</button>`;

    const btn = document.getElementById('authSidebarActionBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        openModal(auth && auth.authenticated ? 'account' : 'login');
      });
    }
  }

  function renderStatusCard() {
    const body = document.getElementById('authStatusCard');
    const actions = document.getElementById('authStatusCardActions');
    if (!body || !actions) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const isLoggedIn = !!(auth && auth.authenticated);

    body.innerHTML = isLoggedIn
      ? `
        <div class="auth-status-card">
          <div class="auth-status-badge is-authenticated">已登录</div>
          <div class="auth-status-title">${esc(auth.user.display_name || auth.user.username || '同学')}</div>
          <div class="auth-status-meta">账号：${esc(auth.user.username || ctx.userId)}<br>语言：${esc(auth.user.locale || ctx.locale)}<br>会话有效期：${esc(formatExpireText(auth.expires_at))}</div>
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
        <button type="button" class="auth-mini-btn" id="authCardOpenBtn">查看账号</button>
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
        openModal('account');
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

  function fillAccountView() {
    const ctx = getContext();
    const auth = ctx.auth;
    if (!(auth && auth.authenticated)) return;

    const nameEl = document.getElementById('authAccountName');
    const idEl = document.getElementById('authAccountId');
    const localeEl = document.getElementById('authAccountLocale');
    const expireEl = document.getElementById('authAccountExpire');
    const localeSelect = document.getElementById('authModalLocaleSelect');
    const topLocale = document.getElementById('authTopLocaleSelect');

    if (nameEl) nameEl.textContent = auth.user.display_name || auth.user.username || '同学';
    if (idEl) idEl.textContent = `@${auth.user.username || ctx.userId}`;
    if (localeEl) localeEl.textContent = auth.user.locale || ctx.locale;
    if (expireEl) expireEl.textContent = formatExpireText(auth.expires_at);
    if (localeSelect) localeSelect.value = auth.user.locale || ctx.locale;
    if (topLocale) topLocale.value = auth.user.locale || ctx.locale;
  }

  function renderAll() {
    renderTopSlot();
    renderSidebarSlot();
    renderStatusCard();
    updateModeUI();
    fillAccountView();
  }

  function openModal(mode) {
    const modal = ensureModal();
    const auth = getContext().auth;
    currentMode = auth && auth.authenticated ? 'account' : (mode === 'register' ? 'register' : 'login');
    updateModeUI();
    fillAccountView();
    setFeedback('tip', currentMode === 'register' ? '注册后会自动登录到当前项目。' : '登录后即可在所有页面共用同一账号。');
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    const inputId = currentMode === 'register' ? 'authUsernameInput' : 'authUsernameInput';
    const input = document.getElementById(inputId);
    if (input && currentMode !== 'account') {
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

  async function handleAuthSubmit(event) {
    event.preventDefault();
    if (!window.UserContext) return;

    const auth = getContext().auth;
    if (auth && auth.authenticated) {
      openModal('account');
      return;
    }

    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    const displayNameInput = document.getElementById('authDisplayNameInput');
    const localeSelect = document.getElementById('authModalLocaleSelect');
    const submitBtn = document.getElementById('authSubmitBtn');

    const username = String((usernameInput && usernameInput.value) || '').trim();
    const password = String((passwordInput && passwordInput.value) || '').trim();
    const displayName = String((displayNameInput && displayNameInput.value) || '').trim();
    const locale = String((localeSelect && localeSelect.value) || getContext().locale || DEFAULT_LOCALE).trim().toUpperCase();

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
        password
      };
      if (currentMode === 'register') {
        payload.display_name = displayName;
        payload.locale = locale;
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

      if (data && data.auth && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth(data.auth);
      }

      if (displayNameInput) displayNameInput.value = '';
      if (passwordInput) passwordInput.value = '';
      setFeedback('success', currentMode === 'register' ? '注册成功，已自动登录。' : '登录成功，正在同步页面账号...');
      currentMode = 'account';
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

  async function handleLogout() {
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
      renderAll();
      closeModal();
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
    const closeAccountBtn = document.getElementById('authCloseAccountBtn');
    const logoutBtn = document.getElementById('authLogoutBtn');
    const localeSelect = document.getElementById('authModalLocaleSelect');
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
        setFeedback('tip', currentMode === 'register' ? '注册后会自动登录到当前项目。' : '登录后即可在所有页面共用同一账号。');
        updateModeUI();
      });
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        currentMode = this.getAttribute('data-auth-mode') === 'register' ? 'register' : 'login';
        setFeedback('tip', currentMode === 'register' ? '注册后会自动登录到当前项目。' : '登录后即可在所有页面共用同一账号。');
        updateModeUI();
      });
    });

    if (closeAccountBtn) {
      closeAccountBtn.addEventListener('click', closeModal);
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', handleLogout);
    }

    if (localeSelect) {
      localeSelect.addEventListener('change', function () {
        if (window.UserContext && typeof window.UserContext.setLocale === 'function') {
          window.UserContext.setLocale(this.value || DEFAULT_LOCALE);
        }
      });
    }

    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeModal();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeModal();
      }
    });

    modalBound = true;
  }

  function init() {
    ensureTopSlot();
    ensureSidebarSlot();
    ensureModal();
    bindModalEvents();
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
