(function () {
  const DEFAULT_USER_ID = 'default_user';
  const LEGACY_CHAT_STORE_KEY = 'fangzhigong_chat_sessions_v1';

  function sanitizeUserId(value) {
    const cleaned = String(value || '').trim().replace(/\s+/g, '_');
    if (!cleaned) return DEFAULT_USER_ID;
    return cleaned.slice(0, 40);
  }

  function safeClone(value, fallback) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return JSON.parse(JSON.stringify(fallback));
    }
  }

  function safeRead(key) {
    try {
      const raw = localStorage.getItem(String(key || ''));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (error) {
      return null;
    }
  }

  function safeWrite(key, payload) {
    try {
      localStorage.setItem(String(key || ''), JSON.stringify(payload));
      return true;
    } catch (error) {
      return false;
    }
  }

  function getEntrySpaceStoreKey(userId) {
    return `fangzhigong_entry_spaces_${sanitizeUserId(userId)}`;
  }

  function getChatStoreKey(userId) {
    return `fangzhigong_chat_sessions_${sanitizeUserId(userId)}`;
  }

  function getQuestionBankChatStoreKey(userId) {
    return `fangzhigong_question_bank_sessions_${sanitizeUserId(userId)}`;
  }

  function stableKey(item) {
    try {
      return JSON.stringify(item || {}, Object.keys(item || {}).sort());
    } catch (error) {
      return String((item && item.id) || Math.random());
    }
  }

  function mergeListById(existingList, incomingList, prefix) {
    const merged = [];
    const ids = new Set();
    const signatures = new Set();

    function pushItem(item) {
      if (!item || typeof item !== 'object') return;
      const payload = safeClone(item, {});
      const signature = stableKey(payload);
      if (signatures.has(signature)) return;

      let itemId = String(payload.id || '').trim();
      if (!itemId || ids.has(itemId)) {
        itemId = `${prefix}${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
        payload.id = itemId;
      }

      merged.push(payload);
      ids.add(itemId);
      signatures.add(stableKey(payload));
    }

    (Array.isArray(existingList) ? existingList : []).forEach(pushItem);
    (Array.isArray(incomingList) ? incomingList : []).forEach(pushItem);

    return merged;
  }

  function mergeEntrySpaceStorePayload(existingPayload, incomingPayload) {
    const current = existingPayload && typeof existingPayload === 'object' ? existingPayload : {};
    const incoming = incomingPayload && typeof incomingPayload === 'object' ? incomingPayload : {};
    const spaces = mergeListById(current.spaces, incoming.spaces, 'space_');
    const activeIds = new Set(spaces.map(function (item) { return String(item.id || '').trim(); }).filter(Boolean));
    const activeEntrySpaceId = activeIds.has(String(current.activeEntrySpaceId || '').trim())
      ? String(current.activeEntrySpaceId || '').trim()
      : (activeIds.has(String(incoming.activeEntrySpaceId || '').trim())
        ? String(incoming.activeEntrySpaceId || '').trim()
        : (spaces[0] && String(spaces[0].id || '').trim()) || '');

    return {
      activeEntrySpaceId: activeEntrySpaceId,
      spaces: spaces
    };
  }

  function normalizeChatSession(session) {
    if (!session || typeof session !== 'object') return null;
    const payload = safeClone(session, {});
    payload.id = String(payload.id || '').trim();
    if (!payload.id) return null;
    payload.title = String(payload.title || '新对话').trim() || '新对话';
    payload.updatedAt = Number(payload.updatedAt || Date.now());
    payload.messages = Array.isArray(payload.messages) ? payload.messages : [];
    return payload;
  }

  function mergeChatStorePayload(existingPayload, incomingPayload, maxSessions) {
    const limit = Math.max(1, Number(maxSessions || 20));
    const current = existingPayload && typeof existingPayload === 'object' ? existingPayload : {};
    const incoming = incomingPayload && typeof incomingPayload === 'object' ? incomingPayload : {};
    const sessions = mergeListById(
      (Array.isArray(current.sessions) ? current.sessions : []).map(normalizeChatSession).filter(Boolean),
      (Array.isArray(incoming.sessions) ? incoming.sessions : []).map(normalizeChatSession).filter(Boolean),
      'session_'
    ).sort(function (a, b) {
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    }).slice(0, limit);

    const sessionIds = new Set(sessions.map(function (item) { return String(item.id || '').trim(); }).filter(Boolean));
    const activeSessionId = sessionIds.has(String(current.activeSessionId || '').trim())
      ? String(current.activeSessionId || '').trim()
      : (sessionIds.has(String(incoming.activeSessionId || '').trim())
        ? String(incoming.activeSessionId || '').trim()
        : (sessions[0] && String(sessions[0].id || '').trim()) || '');

    return {
      activeSessionId: activeSessionId,
      sessions: sessions
    };
  }

  function ensureChatStoreForUser(userId, maxSessions) {
    const targetUserId = sanitizeUserId(userId);
    const targetKey = getChatStoreKey(targetUserId);
    const existing = safeRead(targetKey);
    if (existing && Array.isArray(existing.sessions)) {
      return existing;
    }

    const legacy = safeRead(LEGACY_CHAT_STORE_KEY);
    if (!legacy || !Array.isArray(legacy.sessions)) {
      return existing;
    }

    const merged = mergeChatStorePayload(existing, legacy, maxSessions);
    safeWrite(targetKey, merged);
    return merged;
  }

  function ensureQuestionBankStoreForUser(userId, maxSessions) {
    const targetUserId = sanitizeUserId(userId);
    const targetKey = getQuestionBankChatStoreKey(targetUserId);
    const existing = safeRead(targetKey);
    if (existing && Array.isArray(existing.sessions)) {
      return existing;
    }

    const merged = mergeChatStorePayload(existing, { sessions: [], activeSessionId: '' }, maxSessions);
    safeWrite(targetKey, merged);
    return merged;
  }

  function migrateGuestLocalData(fromUserId, toUserId, options) {
    const sourceUserId = sanitizeUserId(fromUserId);
    const targetUserId = sanitizeUserId(toUserId);
    const opts = options && typeof options === 'object' ? options : {};
    const includeChat = opts.includeChat !== false;
    const maxChatSessions = Math.max(1, Number(opts.maxChatSessions || 20));
    const summary = {
      migrated: false,
      spaces: 0,
      sessions: 0,
      fromUserId: sourceUserId,
      toUserId: targetUserId
    };

    if (!sourceUserId || !targetUserId || sourceUserId === targetUserId) {
      return summary;
    }

    const sourceSpaceKey = getEntrySpaceStoreKey(sourceUserId);
    const targetSpaceKey = getEntrySpaceStoreKey(targetUserId);
    const sourceSpacePayload = safeRead(sourceSpaceKey);
    const targetSpacePayload = safeRead(targetSpaceKey);
    if (sourceSpacePayload && Array.isArray(sourceSpacePayload.spaces) && sourceSpacePayload.spaces.length > 0) {
      const mergedSpaces = mergeEntrySpaceStorePayload(targetSpacePayload, sourceSpacePayload);
      safeWrite(targetSpaceKey, mergedSpaces);
      summary.spaces = Math.max(0, mergedSpaces.spaces.length - ((targetSpacePayload && Array.isArray(targetSpacePayload.spaces)) ? targetSpacePayload.spaces.length : 0));
    }

    if (includeChat) {
      const sourceChatPayload = safeRead(getChatStoreKey(sourceUserId))
        || (sourceUserId === DEFAULT_USER_ID ? safeRead(LEGACY_CHAT_STORE_KEY) : null);
      const targetChatPayload = safeRead(getChatStoreKey(targetUserId));
      if (sourceChatPayload && Array.isArray(sourceChatPayload.sessions) && sourceChatPayload.sessions.length > 0) {
        const mergedChat = mergeChatStorePayload(targetChatPayload, sourceChatPayload, maxChatSessions);
        safeWrite(getChatStoreKey(targetUserId), mergedChat);
        summary.sessions = Math.max(0, mergedChat.sessions.length - ((targetChatPayload && Array.isArray(targetChatPayload.sessions)) ? targetChatPayload.sessions.length : 0));
      }
    }

    summary.migrated = summary.spaces > 0 || summary.sessions > 0;
    return summary;
  }

  window.ProjectLocalData = {
    LEGACY_CHAT_STORE_KEY: LEGACY_CHAT_STORE_KEY,
    getEntrySpaceStoreKey: getEntrySpaceStoreKey,
    getChatStoreKey: getChatStoreKey,
    getQuestionBankChatStoreKey: getQuestionBankChatStoreKey,
    ensureChatStoreForUser: ensureChatStoreForUser,
    ensureQuestionBankStoreForUser: ensureQuestionBankStoreForUser,
    migrateGuestLocalData: migrateGuestLocalData
  };
})();
