(function () {
  const STORAGE_KEY = 'fangzhigong_user_id';
  const DEFAULT_USER_ID = 'default_user';

  function sanitizeUserId(value) {
    const cleaned = String(value || '').trim().replace(/\s+/g, '_');
    if (!cleaned) return DEFAULT_USER_ID;
    return cleaned.slice(0, 40);
  }

  function getUserId() {
    const url = new URL(window.location.href);
    const urlUser = url.searchParams.get('user_id');
    if (urlUser) {
      const normalized = sanitizeUserId(urlUser);
      localStorage.setItem(STORAGE_KEY, normalized);
      return normalized;
    }

    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return sanitizeUserId(stored);

    localStorage.setItem(STORAGE_KEY, DEFAULT_USER_ID);
    return DEFAULT_USER_ID;
  }

  function setUserId(newUserId) {
    const normalized = sanitizeUserId(newUserId);
    localStorage.setItem(STORAGE_KEY, normalized);
    window.dispatchEvent(new CustomEvent('user:changed', { detail: { userId: normalized } }));
    return normalized;
  }

  function onChange(handler) {
    if (typeof handler !== 'function') return;
    window.addEventListener('user:changed', (e) => handler(e.detail.userId));
    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        handler(sanitizeUserId(e.newValue));
      }
    });
  }

  window.UserContext = {
    getUserId,
    setUserId,
    onChange
  };
})();
