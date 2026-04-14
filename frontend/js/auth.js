(function () {
  const SESSION_KEY = 'fangzhigong_auth_session_v1';
  const LOCALE_KEY = 'fangzhigong_locale';
  const LEGACY_USER_KEY = 'fangzhigong_user_id';
  const HOME_PATHS = new Set(['/', '/index.html', 'index.html']);
  const RETRYABLE_STATUS = new Set([0, 404, 405, 501]);
  const nativeFetch = window.fetch.bind(window);

  const copy = {
    CN: {
      brand: '坊知工',
      modalLoginTitle: '欢迎回来',
      modalRegisterTitle: '创建账号',
      modalSubtitleLogin: '登录后即可继续使用你的学习空间、问答记录和知识图谱。',
      modalSubtitleRegister: '创建一个项目账号，后续学习数据都会自动绑定到你的身份。',
      tabLogin: '登录',
      tabRegister: '注册',
      labelUsername: '账号',
      labelDisplayName: '昵称',
      labelPassword: '密码',
      usernamePlaceholder: '例如 student_001',
      displayNamePlaceholder: '例如 小坊同学',
      passwordPlaceholder: '请输入至少 6 位密码',
      registerHint: '账号支持 3-32 位字母、数字或 . _ @ -',
      submitLogin: '登录',
      submitRegister: '注册并进入',
      switchToRegister: '还没有账号？立即注册',
      switchToLogin: '已经有账号？直接登录',
      close: '关闭',
      accountLabel: '当前账号',
      logout: '退出登录',
      guestLabel: '未登录预览',
      reopenLogin: '登录',
      sessionExpired: '登录状态已失效，请重新登录。',
      loginFailed: '登录失败，请检查账号和密码。',
      registerFailed: '注册失败，请调整信息后重试。',
      loading: '提交中...',
      defaultName: '同学',
      currentUserPrefix: '当前用户：',
      currentAccountPrefix: '当前账号：',
      userPrefix: '用户：',
      anonymous: '未登录',
    },
    EN: {
      brand: 'Fangzhigong',
      modalLoginTitle: 'Welcome back',
      modalRegisterTitle: 'Create account',
      modalSubtitleLogin: 'Sign in to continue with your learning space, chat history, and knowledge graph.',
      modalSubtitleRegister: 'Create a project account so all your study data stays attached to your identity.',
      tabLogin: 'Login',
      tabRegister: 'Register',
      labelUsername: 'Account',
      labelDisplayName: 'Display name',
      labelPassword: 'Password',
      usernamePlaceholder: 'e.g. student_001',
      displayNamePlaceholder: 'e.g. Alex',
      passwordPlaceholder: 'At least 6 characters',
      registerHint: 'Use 3-32 letters, numbers, or . _ @ -',
      submitLogin: 'Login',
      submitRegister: 'Register',
      switchToRegister: 'No account yet? Create one',
      switchToLogin: 'Already have an account? Sign in',
      close: 'Close',
      accountLabel: 'Signed in as',
      logout: 'Logout',
      guestLabel: 'Preview mode',
      reopenLogin: 'Login',
      sessionExpired: 'Your session has expired. Please sign in again.',
      loginFailed: 'Unable to sign in. Please check your credentials.',
      registerFailed: 'Unable to register. Please revise the information and try again.',
      loading: 'Submitting...',
      defaultName: 'Student',
      currentUserPrefix: 'Current user: ',
      currentAccountPrefix: 'Signed in: ',
      userPrefix: 'User: ',
      anonymous: 'Not signed in',
    }
  };

  const state = {
    session: loadStoredSession(),
    locale: loadStoredLocale(),
    modalMode: 'login',
    modalMessage: '',
    modalMessageType: '',
    ready: false,
  };

  function t(key) {
    const dict = copy[state.locale] || copy.CN;
    return dict[key] || copy.CN[key] || key;
  }

  function loadStoredLocale() {
    const raw = String(localStorage.getItem(LOCALE_KEY) || '').trim().toUpperCase();
    return raw === 'EN' ? 'EN' : 'CN';
  }

  function normalizeLocale(value) {
    return String(value || '').trim().toUpperCase() === 'EN' ? 'EN' : 'CN';
  }

  function loadStoredSession() {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      if (!parsed.token || !parsed.user || !parsed.user.user_id) return null;
      return parsed;
    } catch (error) {
      return null;
    }
  }

  function isAuthenticated() {
    return !!(state.session && state.session.token && state.session.user && state.session.user.user_id);
  }

  function getCurrentUser() {
    return isAuthenticated() ? state.session.user : null;
  }

  function getCurrentUserId() {
    const user = getCurrentUser();
    return user ? String(user.user_id || user.username || '').trim() : '';
  }

  function setLocale(nextLocale, rerender) {
    state.locale = normalizeLocale(nextLocale);
    localStorage.setItem(LOCALE_KEY, state.locale);
    if (rerender !== false) {
      syncLegacyAccountLabels();
      refreshBars();
      rerenderOpenModal();
    }
  }

  function saveSession(authPayload) {
    if (!authPayload || !authPayload.token || !authPayload.user) {
      clearSession();
      return;
    }

    state.session = {
      token: authPayload.token,
      expires_at: authPayload.expires_at || '',
      session_id: authPayload.session_id || '',
      user: {
        user_id: String(authPayload.user.user_id || authPayload.user.username || '').trim(),
        username: String(authPayload.user.username || authPayload.user.user_id || '').trim(),
        display_name: String(authPayload.user.display_name || authPayload.user.username || authPayload.user.user_id || t('defaultName')).trim(),
        locale: normalizeLocale(authPayload.user.locale || state.locale),
      }
    };

    localStorage.setItem(SESSION_KEY, JSON.stringify(state.session));
    localStorage.setItem(LEGACY_USER_KEY, state.session.user.user_id);
    localStorage.setItem(LOCALE_KEY, state.session.user.locale);
    state.locale = state.session.user.locale;
    emitChange();
  }

  function clearSession(options) {
    const opts = options || {};
    state.session = null;
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(LEGACY_USER_KEY);
    if (opts.emit !== false) {
      emitChange();
    }
  }

  function emitChange() {
    window.dispatchEvent(new CustomEvent('auth:changed', {
      detail: {
        authenticated: isAuthenticated(),
        user: getCurrentUser(),
        session: state.session,
      }
    }));

    window.dispatchEvent(new CustomEvent('user:changed', {
      detail: {
        userId: getCurrentUserId() || 'default_user',
      }
    }));

    syncAuthShell();
  }

  function onChange(handler) {
    if (typeof handler !== 'function') return;
    window.addEventListener('auth:changed', function (e) {
      handler(e.detail || {});
    });
  }

  function getApiBase() {
    if (window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function') {
      return window.ApiUtils.getApiBase();
    }
    return `${window.location.protocol}//${window.location.host}`;
  }

  function normalizeBase(base) {
    return String(base || '').trim().replace(/\/+$/, '');
  }

  function candidateApiBases(initialBase) {
    const current = normalizeBase(initialBase);
    const list = [current];
    if (window.ApiUtils && typeof window.ApiUtils.defaultApiBaseCandidates === 'function') {
      list.push.apply(list, window.ApiUtils.defaultApiBaseCandidates());
    }
    return Array.from(new Set(list.map(normalizeBase).filter(Boolean)));
  }

  function toAbsoluteUrl(input) {
    try {
      if (typeof input === 'string') {
        return new URL(input, window.location.href);
      }
      if (input && typeof input.url === 'string') {
        return new URL(input.url, window.location.href);
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  function isApiRequest(urlObj) {
    if (!urlObj) return false;
    if (urlObj.origin === window.location.origin && urlObj.pathname.startsWith('/api/')) {
      return true;
    }
    return candidateApiBases(getApiBase()).some(function (base) {
      return urlObj.href.startsWith(`${normalizeBase(base)}/api/`);
    });
  }

  function buildAuthHeaders(existingHeaders) {
    const headers = new Headers(existingHeaders || {});
    if (isAuthenticated()) {
      headers.set('Authorization', `Bearer ${state.session.token}`);
    }
    return headers;
  }

  async function parseResponse(response) {
    try {
      if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
        return await window.ApiUtils.parseApiResponse(response);
      }

      let data = {};
      try {
        data = await response.json();
      } catch (error) {
        data = {};
      }

      if (!response.ok || data.success === false) {
        const err = new Error(data.error_message || data.message || `请求失败(${response.status})`);
        err.status = response.status;
        err.payload = data;
        throw err;
      }
      return data;
    } catch (error) {
      if (error && typeof error === 'object' && typeof error.status !== 'number') {
        error.status = response && typeof response.status === 'number' ? response.status : 0;
      }
      throw error;
    }
  }

  function shouldRetryWithAlternateBase(error) {
    return RETRYABLE_STATUS.has(Number(error && error.status || 0));
  }

  async function requestJson(path, options) {
    const opts = options || {};
    const headers = buildAuthHeaders(opts.headers);
    if (opts.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    if (/^https?:\/\//i.test(path)) {
      const directResponse = await nativeFetch(path, {
        method: opts.method || 'GET',
        headers,
        body: opts.body,
      });
      return parseResponse(directResponse);
    }

    const bases = candidateApiBases(getApiBase());
    let lastError = null;

    for (let i = 0; i < bases.length; i += 1) {
      const base = bases[i];
      if (!base) continue;

      try {
        const response = await nativeFetch(`${base}${path}`, {
          method: opts.method || 'GET',
          headers,
          body: opts.body,
        });
        const data = await parseResponse(response);
        if (i > 0 && window.ApiUtils && typeof window.ApiUtils.setApiBase === 'function') {
          window.ApiUtils.setApiBase(base);
        }
        Object.defineProperty(data, '__apiBaseUsed', {
          value: base,
          enumerable: false,
          configurable: true,
        });
        return data;
      } catch (error) {
        lastError = error;
        if (!shouldRetryWithAlternateBase(error) || i === bases.length - 1) {
          throw error;
        }
      }
    }

    throw lastError || new Error('请求失败');
  }

  function getCurrentPath() {
    return window.location.pathname || '/';
  }

  function getCurrentPathTail() {
    const path = getCurrentPath();
    if (HOME_PATHS.has(path)) return '/';
    const tail = path.split('/').pop() || '/';
    return tail ? `/${tail}` : '/';
  }

  function isHomePage() {
    return HOME_PATHS.has(getCurrentPath()) || HOME_PATHS.has(getCurrentPathTail());
  }

  function sanitizeNextTarget(raw) {
    const text = String(raw || '').trim();
    if (!text || text.startsWith('//')) return '';
    try {
      const url = new URL(text, window.location.origin);
      if (url.origin !== window.location.origin) return '';
      return `${url.pathname}${url.search}${url.hash}`;
    } catch (error) {
      return '';
    }
  }

  function getNextTarget() {
    const params = new URLSearchParams(window.location.search || '');
    return sanitizeNextTarget(params.get('next'));
  }

  function getCleanCurrentUrl(removeNext) {
    const url = new URL(window.location.href);
    url.searchParams.delete('auth');
    if (removeNext) {
      url.searchParams.delete('next');
    }
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function redirectToLogin() {
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}${window.location.hash}`);
    window.location.replace(`index.html?auth=login&next=${next}`);
  }

  function clearAuthQueryParams(removeNext) {
    if (!isHomePage()) return;
    window.history.replaceState({}, '', getCleanCurrentUrl(removeNext));
  }

  function shouldAutoOpenModal() {
    const params = new URLSearchParams(window.location.search || '');
    return String(params.get('auth') || '').trim().toLowerCase() === 'login';
  }

  function ensureModalHost() {
    let modal = document.getElementById('authModal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'authModal';
    modal.className = 'auth-modal';
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeAuthModal();
    });
    document.body.appendChild(modal);
    return modal;
  }

  function buildModalMarkup() {
    const isLogin = state.modalMode === 'login';
    return `
      <div class="auth-modal-card">
        <div class="auth-modal-head">
          <div>
            <div class="auth-modal-title">${isLogin ? t('modalLoginTitle') : t('modalRegisterTitle')}</div>
            <div class="auth-modal-subtitle">${isLogin ? t('modalSubtitleLogin') : t('modalSubtitleRegister')}</div>
          </div>
          <button type="button" class="auth-modal-close" id="authModalCloseBtn" aria-label="${t('close')}">&times;</button>
        </div>

        <div class="auth-tabs">
          <button type="button" class="auth-tab${isLogin ? ' active' : ''}" data-auth-tab="login">${t('tabLogin')}</button>
          <button type="button" class="auth-tab${!isLogin ? ' active' : ''}" data-auth-tab="register">${t('tabRegister')}</button>
        </div>

        <form class="auth-form" id="authForm">
          <div class="auth-field">
            <label for="authUsernameInput">${t('labelUsername')}</label>
            <input id="authUsernameInput" name="username" type="text" autocomplete="username" placeholder="${t('usernamePlaceholder')}" required>
          </div>

          ${isLogin ? '' : `
            <div class="auth-field">
              <label for="authDisplayNameInput">${t('labelDisplayName')}</label>
              <input id="authDisplayNameInput" name="display_name" type="text" autocomplete="nickname" placeholder="${t('displayNamePlaceholder')}">
            </div>
          `}

          <div class="auth-field">
            <label for="authPasswordInput">${t('labelPassword')}</label>
            <input id="authPasswordInput" name="password" type="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" placeholder="${t('passwordPlaceholder')}" required>
          </div>

          ${isLogin ? '' : `<div class="auth-form-help">${t('registerHint')}</div>`}
          <div class="auth-modal-message${state.modalMessageType ? ` ${state.modalMessageType}` : ''}" id="authModalMessage">${state.modalMessage || ''}</div>
          <button type="submit" class="auth-submit-btn" id="authSubmitBtn">${isLogin ? t('submitLogin') : t('submitRegister')}</button>
        </form>

        <div class="auth-modal-footer">
          <button type="button" class="auth-link-btn" id="authModeSwitchBtn">${isLogin ? t('switchToRegister') : t('switchToLogin')}</button>
        </div>
      </div>
    `;
  }

  function renderModal() {
    const modal = ensureModalHost();
    modal.innerHTML = buildModalMarkup();

    const closeBtn = document.getElementById('authModalCloseBtn');
    const form = document.getElementById('authForm');
    const switchBtn = document.getElementById('authModeSwitchBtn');

    if (closeBtn) {
      closeBtn.addEventListener('click', closeAuthModal);
    }

    document.querySelectorAll('[data-auth-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () {
        openAuthModal(String(this.getAttribute('data-auth-tab') || 'login'));
      });
    });

    if (switchBtn) {
      switchBtn.addEventListener('click', function () {
        openAuthModal(state.modalMode === 'login' ? 'register' : 'login');
      });
    }

    if (form) {
      form.addEventListener('submit', handleAuthSubmit);
    }
  }

  function rerenderOpenModal() {
    const modal = document.getElementById('authModal');
    if (modal && modal.classList.contains('open')) {
      renderModal();
      modal.classList.add('open');
    }
  }

  function setModalMessage(message, type) {
    state.modalMessage = String(message || '');
    state.modalMessageType = String(type || '');
    const el = document.getElementById('authModalMessage');
    if (!el) return;
    el.textContent = state.modalMessage;
    el.className = `auth-modal-message${state.modalMessageType ? ` ${state.modalMessageType}` : ''}`;
  }

  function openAuthModal(mode, message, type) {
    if (isHomePage() && !isAuthenticated()) {
      document.body.classList.add('auth-home-preview');
    }
    state.modalMode = mode === 'register' ? 'register' : 'login';
    state.modalMessage = String(message || '');
    state.modalMessageType = String(type || '');
    renderModal();
    ensureModalHost().classList.add('open');
  }

  function closeAuthModal() {
    const modal = ensureModalHost();
    modal.classList.remove('open');
    state.modalMessage = '';
    state.modalMessageType = '';
    if (!isAuthenticated() && isHomePage()) {
      clearAuthQueryParams(false);
      showLanding(false);
    }
  }

  async function handleAuthSubmit(e) {
    e.preventDefault();
    const submitBtn = document.getElementById('authSubmitBtn');
    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    const displayNameInput = document.getElementById('authDisplayNameInput');

    const username = String(usernameInput && usernameInput.value || '').trim();
    const password = String(passwordInput && passwordInput.value || '').trim();
    const displayName = String(displayNameInput && displayNameInput.value || '').trim();

    if (!username || !password) {
      setModalMessage(t(state.modalMode === 'login' ? 'loginFailed' : 'registerFailed'), 'error');
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = t('loading');
    }

    setModalMessage('', '');

    try {
      const payload = state.modalMode === 'login'
        ? { username, password }
        : { username, password, display_name: displayName, locale: state.locale };
      const endpoint = state.modalMode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const data = await requestJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      const next = getNextTarget();
      saveSession(data.auth || null);
      clearAuthQueryParams(true);
      closeAuthModal();

      if (next && !HOME_PATHS.has(next) && next !== '/index.html') {
        window.location.assign(next);
        return;
      }

      if (isHomePage()) {
        window.location.assign(getCleanCurrentUrl(true));
        return;
      }

      unlockPage();
    } catch (error) {
      setModalMessage(error && error.message ? error.message : t(state.modalMode === 'login' ? 'loginFailed' : 'registerFailed'), 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = state.modalMode === 'login' ? t('submitLogin') : t('submitRegister');
      }
    }
  }

  function ensureAccountBar() {
    if (!isAuthenticated()) return;

    let bar = document.getElementById('authAccountBar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'authAccountBar';
      bar.className = 'auth-account-bar';
      document.body.appendChild(bar);
    }

    const user = getCurrentUser();
    bar.innerHTML = `
      <select class="auth-locale-select" id="authBarLocaleSelect">
        <option value="CN"${state.locale === 'CN' ? ' selected' : ''}>CN</option>
        <option value="EN"${state.locale === 'EN' ? ' selected' : ''}>EN</option>
      </select>
      <div class="auth-account-chip">
        <div class="auth-account-name">${user ? (user.display_name || user.username) : ''}</div>
        <div class="auth-account-id">${t('accountLabel')} · ${user ? user.username : ''}</div>
      </div>
      <button type="button" class="auth-account-btn" id="authLogoutBtn">${t('logout')}</button>
    `;

    const localeSelect = document.getElementById('authBarLocaleSelect');
    const logoutBtn = document.getElementById('authLogoutBtn');

    if (localeSelect) {
      localeSelect.addEventListener('change', function () {
        setLocale(this.value);
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', logout);
    }
  }

  function removeAccountBar() {
    const bar = document.getElementById('authAccountBar');
    if (bar) bar.remove();
  }

  function ensureGuestBar() {
    if (!isHomePage() || isAuthenticated()) return;

    let bar = document.getElementById('authGuestBar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'authGuestBar';
      bar.className = 'auth-guest-bar';
      document.body.appendChild(bar);
    }

    bar.innerHTML = `
      <select class="auth-locale-select" id="authGuestLocaleSelect">
        <option value="CN"${state.locale === 'CN' ? ' selected' : ''}>CN</option>
        <option value="EN"${state.locale === 'EN' ? ' selected' : ''}>EN</option>
      </select>
      <div class="auth-guest-copy">${t('guestLabel')}</div>
      <button type="button" class="auth-account-btn" id="authGuestLoginBtn">${t('reopenLogin')}</button>
    `;

    const localeSelect = document.getElementById('authGuestLocaleSelect');
    const loginBtn = document.getElementById('authGuestLoginBtn');

    if (localeSelect) {
      localeSelect.addEventListener('change', function () {
        setLocale(this.value);
      });
    }

    if (loginBtn) {
      loginBtn.addEventListener('click', function () {
        openAuthModal('login');
      });
    }
  }

  function removeGuestBar() {
    const bar = document.getElementById('authGuestBar');
    if (bar) bar.remove();
  }

  function refreshBars() {
    if (isAuthenticated()) {
      ensureAccountBar();
      removeGuestBar();
      return;
    }
    removeAccountBar();
    if (isHomePage()) {
      ensureGuestBar();
    } else {
      removeGuestBar();
    }
  }

  function syncLegacyAccountLabels() {
    const currentUserLabel = document.getElementById('current-user-label');
    const entryUserName = document.getElementById('entryUserName');
    const dashboardUserLabel = document.getElementById('dashboard-user-label');
    const mapUserLabel = document.getElementById('mapUserLabel');
    const spaceUserLabel = document.getElementById('spaceUserLabel');
    const user = getCurrentUser();

    if (entryUserName) {
      entryUserName.textContent = user ? (user.display_name || user.username || t('defaultName')) : t('defaultName');
    }

    if (currentUserLabel) {
      currentUserLabel.textContent = user
        ? `${t('currentAccountPrefix')}${user.display_name || user.username}（${user.username}）`
        : `${t('currentUserPrefix')}${t('anonymous')}`;
    }

    if (dashboardUserLabel) {
      dashboardUserLabel.textContent = user ? `${t('currentUserPrefix')}${user.username}` : '';
    }

    if (mapUserLabel) {
      mapUserLabel.textContent = user ? `${t('currentUserPrefix')}${user.username}` : `${t('currentUserPrefix')}${t('anonymous')}`;
    }

    if (spaceUserLabel) {
      spaceUserLabel.textContent = user ? `${t('userPrefix')}${user.username}` : `${t('userPrefix')}${t('anonymous')}`;
    }
  }

  function cleanupLegacyShell() {
    const shell = document.getElementById('authShell');
    const corner = document.querySelector('.auth-shell-corner');
    if (shell) shell.remove();
    if (corner) corner.remove();
  }

  function showLanding(autoOpenModal) {
    removeAccountBar();
    cleanupLegacyShell();

    if (isHomePage()) {
      document.body.classList.remove('auth-locked', 'auth-landing-active');
      document.body.classList.add('auth-pending', 'auth-home-preview');
      ensureGuestBar();
      syncLegacyAccountLabels();
      if (autoOpenModal) {
        openAuthModal('login');
      }
      return;
    }

    document.body.classList.add('auth-pending');
  }

  function unlockPage() {
    cleanupLegacyShell();
    document.body.classList.remove('auth-pending', 'auth-home-preview', 'auth-landing-active');
    if (isAuthenticated()) {
      document.body.classList.add('auth-locked');
      ensureAccountBar();
      removeGuestBar();
    } else {
      document.body.classList.remove('auth-locked');
      removeAccountBar();
      if (isHomePage()) {
        ensureGuestBar();
      }
    }
    syncLegacyAccountLabels();
  }

  function syncAuthShell() {
    if (!state.ready) return;

    if (!isAuthenticated()) {
      if (isHomePage()) {
        showLanding(false);
      } else {
        removeAccountBar();
        removeGuestBar();
      }
    } else {
      unlockPage();
    }

    rerenderOpenModal();
  }

  async function restoreSession() {
    if (!isAuthenticated()) return false;

    try {
      const data = await requestJson('/api/auth/me', { method: 'GET' });
      if (!data || !data.auth || !data.auth.user) {
        throw new Error('invalid_auth_state');
      }
      saveSession({
        token: state.session.token,
        expires_at: data.auth.expires_at,
        session_id: data.auth.session_id,
        user: data.auth.user,
      });
      return true;
    } catch (error) {
      clearSession({ emit: false });
      return false;
    }
  }

  async function logout() {
    try {
      await requestJson('/api/auth/logout', {
        method: 'POST',
        body: JSON.stringify({}),
      });
    } catch (error) {
      // Ignore logout API failure and clear local session anyway.
    } finally {
      clearSession();
      if (isHomePage()) {
        showLanding(false);
      } else {
        redirectToLogin();
      }
    }
  }

  window.fetch = function patchedFetch(input, init) {
    const urlObj = toAbsoluteUrl(input);
    const nextInit = init ? Object.assign({}, init) : {};

    if (isApiRequest(urlObj)) {
      nextInit.headers = buildAuthHeaders(nextInit.headers);
    }

    return nativeFetch(input, nextInit).then(function (response) {
      if (!isApiRequest(urlObj)) {
        return response;
      }

      const pathname = urlObj ? (urlObj.pathname || '') : '';
      const isAuthRoute = /^\/api\/auth\/(login|register)$/.test(pathname);
      if (response.status === 401 && !isAuthRoute) {
        clearSession();
        if (isHomePage()) {
          showLanding(false);
          openAuthModal('login', t('sessionExpired'), 'error');
        } else {
          redirectToLogin();
        }
      }
      return response;
    });
  };

  async function init() {
    if (isAuthenticated()) {
      await restoreSession();
    }

    state.ready = true;

    if (isHomePage()) {
      if (isAuthenticated()) {
        clearAuthQueryParams(true);
        unlockPage();
      } else {
        showLanding(shouldAutoOpenModal());
      }
      return;
    }

    if (!isAuthenticated()) {
      redirectToLogin();
      return;
    }

    unlockPage();
  }

  window.AuthService = {
    isAuthenticated,
    getCurrentUser,
    getCurrentUserId,
    getLocale: function () { return state.locale; },
    setLocale,
    openAuthModal,
    closeAuthModal,
    logout,
    onChange,
    restoreSession,
    requireAuth: function () {
      if (!isAuthenticated()) {
        redirectToLogin();
        return false;
      }
      return true;
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
