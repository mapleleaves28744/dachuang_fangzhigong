(function () {
  const GUEST_USER_STORAGE_KEY = 'fangzhigong_user_id';
  const AUTH_STORAGE_KEY = 'fangzhigong_auth_state';
  const LOCALE_STORAGE_KEY = 'fangzhigong_locale';
  const DEFAULT_USER_ID = 'default_user';
  const GUEST_USER_PREFIX = 'guest_';
  const DEFAULT_LOCALE = 'CN';

  function sanitizeUserId(value) {
    const cleaned = String(value || '').trim().replace(/\s+/g, '_');
    if (!cleaned) return DEFAULT_USER_ID;
    return cleaned.slice(0, 40);
  }

  function normalizeLocale(value) {
    return String(value || '').trim().toUpperCase() === 'EN' ? 'EN' : 'CN';
  }

  function normalizeDisplayName(value, fallback) {
    const text = String(value || '').trim();
    const backup = String(fallback || '同学').trim() || '同学';
    return (text || backup).slice(0, 24);
  }

  function safeParse(text) {
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (error) {
      return null;
    }
  }

  function getSessionValue(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function setSessionValue(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
      return true;
    } catch (error) {
      return false;
    }
  }

  function removeSessionValue(key) {
    try {
      window.sessionStorage.removeItem(key);
    } catch (error) {
      // 忽略会话存储不可用的场景，避免阻塞页面使用。
    }
  }

  function getStoredAuthText() {
    const sessionText = getSessionValue(AUTH_STORAGE_KEY);
    if (sessionText !== null) return sessionText;

    const legacyText = localStorage.getItem(AUTH_STORAGE_KEY);
    if (legacyText === null) return null;

    // 把旧版持久登录态迁入会话存储，这样当前会话不中断，关闭页面后仍会自动退出。
    if (setSessionValue(AUTH_STORAGE_KEY, legacyText)) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
    return legacyText;
  }

  function setStoredAuthText(value) {
    const text = String(value || '');
    if (setSessionValue(AUTH_STORAGE_KEY, text)) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      return text;
    }
    localStorage.setItem(AUTH_STORAGE_KEY, text);
    return text;
  }

  function clearStoredAuthText() {
    removeSessionValue(AUTH_STORAGE_KEY);
    localStorage.removeItem(AUTH_STORAGE_KEY);
  }

  function isExpired(expiresAt) {
    const raw = String(expiresAt || '').trim();
    if (!raw) return false;
    const time = Date.parse(raw);
    if (!Number.isFinite(time)) return false;
    return time <= Date.now();
  }

  function getPreferredLocale() {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored) return normalizeLocale(stored);
    localStorage.setItem(LOCALE_STORAGE_KEY, DEFAULT_LOCALE);
    return DEFAULT_LOCALE;
  }

  function persistLocale(locale) {
    const normalized = normalizeLocale(locale);
    localStorage.setItem(LOCALE_STORAGE_KEY, normalized);
    return normalized;
  }

  function normalizeAuthState(raw) {
    if (!raw || typeof raw !== 'object') return null;

    const token = String(raw.token || '').trim();
    const user = raw.user && typeof raw.user === 'object' ? raw.user : null;
    const username = String((user && (user.username || user.user_id)) || '').trim();
    if (!token || !username) return null;

    return {
      authenticated: true,
      token,
      expires_at: String(raw.expires_at || '').trim(),
      session_id: String(raw.session_id || '').trim(),
      user: {
        user_id: sanitizeUserId(user.user_id || username),
        username,
        display_name: normalizeDisplayName(user.display_name, username),
        locale: normalizeLocale(user.locale || getPreferredLocale()),
        created_at: String(user.created_at || '').trim(),
        updated_at: String(user.updated_at || '').trim(),
        last_login_at: String(user.last_login_at || '').trim()
      }
    };
  }

  function getAuthState() {
    const parsed = safeParse(getStoredAuthText());
    const normalized = normalizeAuthState(parsed);
    if (!normalized) {
      clearStoredAuthText();
      return null;
    }
    if (isExpired(normalized.expires_at)) {
      clearStoredAuthText();
      return null;
    }
    return normalized;
  }

  function getAuthSnapshot() {
    const auth = getAuthState();
    if (!auth) {
      return {
        authenticated: false,
        token: '',
        expires_at: '',
        session_id: '',
        user: null
      };
    }
    return {
      authenticated: true,
      token: auth.token,
      expires_at: auth.expires_at,
      session_id: auth.session_id,
      user: { ...auth.user }
    };
  }

  function randomGuestSegment() {
    try {
      if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
        const bytes = new Uint8Array(8);
        window.crypto.getRandomValues(bytes);
        return Array.from(bytes).map(function (value) {
          return value.toString(16).padStart(2, '0');
        }).join('');
      }
    } catch (error) {
      // 忽略随机源不可用场景，回退到时间戳方案。
    }

    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`.slice(0, 16);
  }

  function generateGuestUserId() {
    return sanitizeUserId(`${GUEST_USER_PREFIX}${randomGuestSegment()}`);
  }

  function isGeneratedGuestUserId(value) {
    return new RegExp(`^${GUEST_USER_PREFIX}[a-z0-9]{8,40}$`).test(String(value || '').trim());
  }

  function ensureGuestUserId(value) {
    const normalized = sanitizeUserId(value);
    if (normalized && normalized !== DEFAULT_USER_ID) {
      localStorage.setItem(GUEST_USER_STORAGE_KEY, normalized);
      return normalized;
    }

    const generated = generateGuestUserId();
    localStorage.setItem(GUEST_USER_STORAGE_KEY, generated);
    return generated;
  }

  function getGuestUserId() {
    const url = new URL(window.location.href);
    const urlUser = url.searchParams.get('user_id');
    if (urlUser) {
      return ensureGuestUserId(urlUser);
    }

    const stored = localStorage.getItem(GUEST_USER_STORAGE_KEY);
    return ensureGuestUserId(stored);
  }

  function getUserId() {
    const auth = getAuthState();
    if (auth && auth.user) {
      return auth.user.user_id || auth.user.username || DEFAULT_USER_ID;
    }
    return getGuestUserId();
  }

  function getDisplayName() {
    const auth = getAuthState();
    if (auth && auth.user) {
      return normalizeDisplayName(auth.user.display_name, auth.user.username);
    }
    const guestUserId = getGuestUserId();
    return guestUserId === DEFAULT_USER_ID || isGeneratedGuestUserId(guestUserId) ? '同学' : guestUserId;
  }

  function getUserLabel() {
    const auth = getAuthState();
    if (auth && auth.user) {
      const displayName = normalizeDisplayName(auth.user.display_name, auth.user.username);
      const userId = auth.user.user_id || auth.user.username || DEFAULT_USER_ID;
      if (displayName && displayName !== userId) {
        return `${displayName}（${userId}）`;
      }
      return userId;
    }
    const guestUserId = getGuestUserId();
    return guestUserId === DEFAULT_USER_ID || isGeneratedGuestUserId(guestUserId) ? '访客' : guestUserId;
  }

  function getLocale() {
    const auth = getAuthState();
    if (auth && auth.user) return normalizeLocale(auth.user.locale);
    return getPreferredLocale();
  }

  function dispatchContextChange(reason) {
    const detail = {
      reason: String(reason || '').trim(),
      userId: getUserId(),
      displayName: getDisplayName(),
      label: getUserLabel(),
      locale: getLocale(),
      auth: getAuthSnapshot()
    };
    window.dispatchEvent(new CustomEvent('user:changed', { detail }));
    window.dispatchEvent(new CustomEvent('auth:changed', { detail }));
  }

  function setUserId(newUserId) {
    if (isAuthenticated()) {
      return getUserId();
    }
    const normalized = ensureGuestUserId(newUserId);
    dispatchContextChange('guest_user_changed');
    return normalized;
  }

  function resetGuestUserId() {
    const nextGuestId = generateGuestUserId();
    localStorage.setItem(GUEST_USER_STORAGE_KEY, nextGuestId);
    if (!isAuthenticated()) {
      dispatchContextChange('guest_user_reset');
    }
    return nextGuestId;
  }

  function setLocale(locale) {
    const normalized = normalizeLocale(locale);
    const auth = getAuthState();
    if (auth && auth.user) {
      auth.user.locale = normalized;
      setStoredAuthText(JSON.stringify(auth));
    } else {
      persistLocale(normalized);
    }
    dispatchContextChange('locale_changed');
    return normalized;
  }

  function setAuth(authPayload) {
    const current = getAuthState();
    const payload = authPayload && typeof authPayload === 'object'
      ? { ...authPayload }
      : null;
    if (!payload) return null;

    if (current) {
      if (!payload.token) payload.token = current.token;
      if (!payload.expires_at) payload.expires_at = current.expires_at;
      if (!payload.session_id) payload.session_id = current.session_id;
      if (payload.user && typeof payload.user === 'object' && current.user) {
        payload.user = { ...current.user, ...payload.user };
      } else if (!payload.user && current.user) {
        payload.user = { ...current.user };
      }
    }

    const normalized = normalizeAuthState(payload);
    if (!normalized) return null;
    persistLocale(normalized.user.locale);
    setStoredAuthText(JSON.stringify(normalized));
    dispatchContextChange('login');
    return getAuthSnapshot();
  }

  function clearAuth(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const hadAuth = !!getAuthState();
    clearStoredAuthText();
    if (hadAuth || opts.force) {
      dispatchContextChange(opts.reason || 'logout');
    }
  }

  function isAuthenticated() {
    return !!getAuthState();
  }

  function getAuthHeaderValue() {
    const auth = getAuthState();
    if (!auth || !auth.token) return '';
    return `Bearer ${auth.token}`;
  }

  function onChange(handler) {
    if (typeof handler !== 'function') return;
    window.addEventListener('user:changed', function (e) {
      handler(e.detail && e.detail.userId ? e.detail.userId : getUserId(), e.detail || {});
    });
    window.addEventListener('storage', function (e) {
      if ([GUEST_USER_STORAGE_KEY, AUTH_STORAGE_KEY, LOCALE_STORAGE_KEY].includes(e.key)) {
        handler(getUserId(), {
          reason: 'storage',
          userId: getUserId(),
          displayName: getDisplayName(),
          label: getUserLabel(),
          locale: getLocale(),
          auth: getAuthSnapshot()
        });
      }
    });
  }

  function onAuthChange(handler) {
    if (typeof handler !== 'function') return;
    window.addEventListener('auth:changed', function (e) {
      handler((e.detail && e.detail.auth) || getAuthSnapshot(), e.detail || {});
    });
    window.addEventListener('storage', function (e) {
      if (e.key === AUTH_STORAGE_KEY || e.key === LOCALE_STORAGE_KEY) {
        handler(getAuthSnapshot(), {
          reason: 'storage',
          userId: getUserId(),
          displayName: getDisplayName(),
          label: getUserLabel(),
          locale: getLocale(),
          auth: getAuthSnapshot()
        });
      }
    });
  }

  window.UserContext = {
    getUserId,
    getGuestUserId,
    setUserId,
    resetGuestUserId,
    getDisplayName,
    getUserLabel,
    getLocale,
    setLocale,
    isAuthenticated,
    getAuthState: getAuthSnapshot,
    getAuthHeaderValue,
    setAuth,
    clearAuth,
    onChange,
    onAuthChange
  };
})();
