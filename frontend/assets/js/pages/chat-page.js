(function () {
  const API_BASE = window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
    ? window.ApiUtils.getApiBase()
    : (window.location.origin || '');
  const MAX_CHAT_SESSIONS = 20;
  const WELCOME_MESSAGE = '你好，我是坊知工学习助手。你可以直接提问，我会给出结构化、可执行的学习建议。';

  const parseApiResponse = window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function'
    ? window.ApiUtils.parseApiResponse
    : async function (response) {
        const data = await response.json();
        if (!response.ok || data.success === false) {
          throw new Error((data && (data.error_message || data.message)) || ('请求失败(' + response.status + ')'));
        }
        return data;
      };

  const withSuggestion = window.ApiUtils && typeof window.ApiUtils.withSuggestion === 'function'
    ? window.ApiUtils.withSuggestion
    : function (prefix, error, suggestion) {
        const reason = (error && error.message) ? error.message : '未知错误';
        return prefix + '：' + reason + '。建议：' + (suggestion || '请稍后重试');
      };

  let chatSessions = [];
  let activeSessionId = null;
  let taskModalTaskId = null;
  let taskModalAutoTimer = null;
  let taskModalAutoEnabled = false;
  let isAskingQuestion = false;
  let openSessionMenuId = null;
  let sidebarHistoryCollapsed = false;

  function nowLabel(date) {
    const d = date instanceof Date ? date : new Date(date || Date.now());
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  }

  function getUserId() {
    return window.UserContext && typeof window.UserContext.getUserId === 'function'
      ? window.UserContext.getUserId()
      : 'default_user';
  }

  function getUserLabel() {
    return window.UserContext && typeof window.UserContext.getUserLabel === 'function'
      ? window.UserContext.getUserLabel()
      : '访客';
  }

  function getSidebarHistoryStateKey() {
    return `fangzhigong_chat_sidebar_history_collapsed_${getUserId()}`;
  }

  function restoreSidebarHistoryState() {
    try {
      sidebarHistoryCollapsed = localStorage.getItem(getSidebarHistoryStateKey()) === '1';
    } catch (error) {
      sidebarHistoryCollapsed = false;
    }
  }

  function saveSidebarHistoryState() {
    try {
      localStorage.setItem(getSidebarHistoryStateKey(), sidebarHistoryCollapsed ? '1' : '0');
    } catch (error) {
      console.warn('保存聊天侧栏状态失败:', error);
    }
  }

  function createEmptySession() {
    const ts = Date.now();
    return {
      id: `session_${ts}_${Math.random().toString(36).slice(2, 7)}`,
      title: '新对话',
      updatedAt: ts,
      messages: []
    };
  }

  function getChatStoreKey() {
    if (window.ProjectLocalData && typeof window.ProjectLocalData.getChatStoreKey === 'function') {
      return window.ProjectLocalData.getChatStoreKey(getUserId());
    }
    return 'fangzhigong_chat_sessions_v1';
  }

  function saveSessionsToLocal() {
    try {
      localStorage.setItem(getChatStoreKey(), JSON.stringify({
        activeSessionId: activeSessionId,
        sessions: chatSessions.slice(0, MAX_CHAT_SESSIONS)
      }));
    } catch (error) {
      console.warn('保存会话失败:', error);
    }
  }

  function loadSessionsFromLocal() {
    try {
      if (window.ProjectLocalData && typeof window.ProjectLocalData.ensureChatStoreForUser === 'function') {
        window.ProjectLocalData.ensureChatStoreForUser(getUserId(), MAX_CHAT_SESSIONS);
      }

      const raw = localStorage.getItem(getChatStoreKey());
      if (!raw) {
        chatSessions = [];
        activeSessionId = null;
        return;
      }

      const parsed = JSON.parse(raw);
      chatSessions = Array.isArray(parsed && parsed.sessions)
        ? parsed.sessions.map(function (session) {
            return {
              id: session.id,
              title: session.title || '新对话',
              updatedAt: Number(session.updatedAt || Date.now()),
              messages: Array.isArray(session.messages) ? session.messages : []
            };
          }).filter(function (session) {
            return !!session.id;
          }).slice(0, MAX_CHAT_SESSIONS)
        : [];
      activeSessionId = parsed && parsed.activeSessionId ? parsed.activeSessionId : null;
    } catch (error) {
      console.warn('读取会话失败:', error);
      chatSessions = [];
      activeSessionId = null;
    }
  }

  function getActiveSession() {
    return chatSessions.find(function (session) {
      return session.id === activeSessionId;
    }) || null;
  }

  function ensureActiveSession() {
    if (!chatSessions.length) {
      const session = createEmptySession();
      chatSessions = [session];
      activeSessionId = session.id;
      return session;
    }

    if (!getActiveSession()) {
      activeSessionId = chatSessions[0].id;
    }

    return getActiveSession();
  }

  function updateSessionTitle(session, text, sender) {
    if (!session || sender !== 'user') return;
    if (session.title && session.title !== '新对话') return;

    const raw = String(text || '').trim();
    if (!raw) return;
    session.title = raw.length > 20 ? `${raw.slice(0, 20)}...` : raw;
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatInline(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }

  function formatSegment(segment) {
    const trimmed = segment.trim();
    if (!trimmed) return '';

    const lines = trimmed.split('\n').filter(Boolean);
    const unordered = lines.every(function (line) { return /^[-*•]\s+/.test(line); });
    const ordered = lines.every(function (line) { return /^\d+\.\s+/.test(line); });

    if (unordered) {
      return `<ul>${lines.map(function (line) {
        return `<li>${formatInline(line.replace(/^[-*•]\s+/, ''))}</li>`;
      }).join('')}</ul>`;
    }

    if (ordered) {
      return `<ol>${lines.map(function (line) {
        return `<li>${formatInline(line.replace(/^\d+\.\s+/, ''))}</li>`;
      }).join('')}</ol>`;
    }

    return `<p>${formatInline(trimmed.replace(/\n/g, '<br>'))}</p>`;
  }

  function renderRichText(text) {
    const safe = escapeHtml(text).replace(/\r\n/g, '\n');
    const chunks = safe.split(/```/);
    const html = chunks.map(function (chunk, idx) {
      if (idx % 2 === 1) {
        return `<pre><code>${chunk.trim()}</code></pre>`;
      }

      const mathBlocks = [];
      const withPlaceholders = chunk.replace(/\$\$([\s\S]*?)\$\$/g, function (_, body) {
        const token = `@@MATH_BLOCK_${mathBlocks.length}@@`;
        mathBlocks.push(`<div class="math-block">$$${body.trim()}$$</div>`);
        return token;
      });

      let bodyHtml = withPlaceholders
        .split(/\n\s*\n/)
        .map(formatSegment)
        .join('');

      mathBlocks.forEach(function (blockHtml, i) {
        bodyHtml = bodyHtml.replace(`@@MATH_BLOCK_${i}@@`, blockHtml);
      });

      return bodyHtml;
    }).join('');

    return html || '<p>(空响应)</p>';
  }

  function normalizeMathText(text) {
    return String(text || '')
      .replace(/```(?:math|latex|tex)\s*([\s\S]*?)```/gi, function (_, body) {
        return `$$\n${body.trim()}\n$$`;
      })
      .replace(/\\\[\s*([\s\S]*?)\s*\\\]/g, function (_, body) {
        return `$$\n${body.trim()}\n$$`;
      })
      .replace(/\\\(\s*([\s\S]*?)\s*\\\)/g, function (_, body) {
        return `$${body.trim()}$`;
      })
      .replace(/\\\\\(/g, '\\(')
      .replace(/\\\\\)/g, '\\)')
      .replace(/\\\\\[/g, '\\[')
      .replace(/\\\\\]/g, '\\]')
      .replace(/\\\\([a-zA-Z]+)/g, '\\$1')
      .replace(/\\\$\\\$/g, '$$')
      .replace(/\\\$/g, '$')
      .replace(/＄/g, '$')
      .replace(/（\\/g, '(\\')
      .replace(/\\）/g, '\\)');
  }

  function normalizeAiAnswerText(text) {
    const content = normalizeMathText(String(text || ''));
    const hasGarbledHint = /[?？]{8,}/.test(content) || /�/.test(content);
    if (!hasGarbledHint) return content;

    return [
      '检测到回答可能存在编码异常，建议你重发一次问题，或改用更短的中文句子提问。',
      '',
      '原始返回：',
      content
    ].join('\n');
  }

  function renderMathInContainer(container) {
    if (!container || typeof renderMathInElement !== 'function') return;
    try {
      renderMathInElement(container, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
          { left: '\\(', right: '\\)', display: false },
          { left: '\\[', right: '\\]', display: true },
          { left: '\\begin{equation}', right: '\\end{equation}', display: true },
          { left: '\\begin{align}', right: '\\end{align}', display: true },
          { left: '\\begin{aligned}', right: '\\end{aligned}', display: true }
        ],
        throwOnError: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      });
    } catch (error) {
      console.warn('公式渲染失败:', error);
    }
  }

  function createMessageRow(text, sender, options) {
    const opts = options || {};
    const row = document.createElement('div');
    row.className = `message-row ${sender === 'user' ? 'user' : 'assistant'}`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = sender === 'user' ? '我' : 'AI';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    const textDiv = document.createElement('div');
    textDiv.className = 'message-text';
    if (sender === 'user') {
      textDiv.innerHTML = `<p>${escapeHtml(text)}</p>`;
    } else {
      textDiv.innerHTML = renderRichText(text);
    }
    bubble.appendChild(textDiv);

    const metaItems = [];
    if (sender === 'ai' && opts.source) {
      metaItems.push(`<span class="meta-chip">来源：${escapeHtml(opts.source)}</span>`);
    }
    if (sender === 'ai' && typeof opts.aiUsed === 'boolean') {
      metaItems.push(`<span class="meta-chip">${opts.aiUsed ? '真实AI回答' : '回退回答'}</span>`);
    }
    if (sender === 'ai' && opts.error) {
      metaItems.push(`<span class="meta-chip error">${escapeHtml(opts.error)}</span>`);
    }
    if (sender === 'ai' && opts.graphSync && typeof opts.graphSync === 'object') {
      const mode = opts.graphSync.mode || 'unknown';
      const status = opts.graphSync.synced ? '已同步' : '待同步';
      const taskType = opts.graphSync.task_type ? ` / ${opts.graphSync.task_type}` : '';
      metaItems.push(`<span class="meta-chip">图谱同步：${escapeHtml(mode)} / ${escapeHtml(status)}${escapeHtml(taskType)}</span>`);
      if (opts.graphSync.task_id) {
        const taskHref = `${API_BASE}/api/tasks/${encodeURIComponent(String(opts.graphSync.task_id))}`;
        metaItems.push(`<a class="meta-chip link" href="${taskHref}" target="_blank" rel="noopener noreferrer">查看任务</a>`);
        metaItems.push(`<button type="button" class="meta-chip button" data-task-status-id="${escapeHtml(String(opts.graphSync.task_id))}">就地查询状态</button>`);
      }
    }

    if (metaItems.length > 0) {
      const metaDiv = document.createElement('div');
      metaDiv.className = 'message-meta';
      metaDiv.innerHTML = metaItems.join('');
      bubble.appendChild(metaDiv);
    }

    if (sender === 'user') {
      row.appendChild(bubble);
      row.appendChild(avatar);
    } else {
      row.appendChild(avatar);
      row.appendChild(bubble);
    }

    return row;
  }

  function appendMessageToSession(text, sender, options) {
    const session = ensureActiveSession();
    const message = {
      text: String(text || ''),
      sender: sender,
      options: options || {},
      time: Date.now()
    };

    session.messages = Array.isArray(session.messages) ? session.messages : [];
    session.messages.push(message);
    session.updatedAt = message.time;
    updateSessionTitle(session, text, sender);
    chatSessions = [session].concat(chatSessions.filter(function (item) {
      return item.id !== session.id;
    })).slice(0, MAX_CHAT_SESSIONS);
    activeSessionId = session.id;
    saveSessionsToLocal();
  }

  function addMessage(text, sender, options, persist) {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return null;

    const row = createMessageRow(text, sender, options || {});
    chatMessages.appendChild(row);

    row.querySelectorAll('[data-task-status-id]').forEach(function (button) {
      button.addEventListener('click', async function () {
        const taskId = this.getAttribute('data-task-status-id');
        if (!taskId) return;

        try {
          const response = await fetch(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}`);
          const data = await response.json();
          openTaskStatusModal(taskId, data);
        } catch (error) {
          openTaskStatusModal(taskId, {
            state: 'FAILED_TO_FETCH',
            error: '任务状态查询失败，请稍后再试。'
          });
        }
      });
    });

    if (sender === 'ai') {
      renderMathInContainer(row);
    }

    chatMessages.scrollTop = chatMessages.scrollHeight;

    if (persist !== false) {
      appendMessageToSession(text, sender, options || {});
      renderSessionList();
    }

    return row;
  }

  function clearChatDom() {
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
      chatMessages.innerHTML = '';
    }
  }

  function ensureWelcomeMessage() {
    const session = ensureActiveSession();
    if (Array.isArray(session.messages) && session.messages.length > 0) return;
    session.messages = [];
    session.updatedAt = Date.now();
    activeSessionId = session.id;
    saveSessionsToLocal();
    addMessage(WELCOME_MESSAGE, 'ai', { source: 'system', aiUsed: true, error: '' });
  }

  function renderActiveSessionMessages() {
    const session = ensureActiveSession();
    clearChatDom();
    (session.messages || []).forEach(function (message) {
      addMessage(message.text, message.sender, message.options || {}, false);
    });
    renderSessionList();
  }

  function renderSessionList() {
    const list = document.getElementById('conversationList');
    const section = document.getElementById('sidebarHistorySection');
    const toggle = document.getElementById('sidebarHistoryToggle');
    const count = document.getElementById('sidebarHistoryCount');

    if (section) {
      section.classList.toggle('collapsed', sidebarHistoryCollapsed);
    }
    if (toggle) {
      toggle.setAttribute('aria-expanded', String(!sidebarHistoryCollapsed));
    }
    if (count) {
      count.textContent = `${chatSessions.length} 条`;
    }
    if (!list) return;

    if (!chatSessions.length) {
      list.innerHTML = '<div class="conversation-empty">暂无对话</div>';
      return;
    }

    chatSessions.sort(function (a, b) {
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    });

    list.innerHTML = chatSessions.map(function (session) {
      const activeClass = session.id === activeSessionId ? 'active' : '';
      const menuOpen = openSessionMenuId === session.id ? 'show' : '';
      const menuActive = openSessionMenuId === session.id ? 'active' : '';
      return `
        <div class="sidebar-conversation-item ${activeClass}" data-session-id="${escapeHtml(session.id)}">
          <button type="button" class="sidebar-conversation-main" data-session-switch="${escapeHtml(session.id)}">
            <div class="sidebar-conversation-title-row">
              <div class="sidebar-conversation-title">${escapeHtml(session.title || '新对话')}</div>
            </div>
            <div class="sidebar-conversation-time">${escapeHtml(nowLabel(session.updatedAt))}</div>
          </button>
          <div class="sidebar-conversation-menu-wrap">
            <button
              type="button"
              class="sidebar-conversation-menu-btn ${menuActive}"
              data-session-menu-toggle="${escapeHtml(session.id)}"
              title="打开对话操作"
              aria-expanded="${openSessionMenuId === session.id ? 'true' : 'false'}"
            >...</button>
            <div class="sidebar-conversation-menu ${menuOpen}">
              <button type="button" class="sidebar-conversation-menu-item" data-session-rename="${escapeHtml(session.id)}">重命名</button>
              <button type="button" class="sidebar-conversation-menu-item danger" data-session-delete="${escapeHtml(session.id)}">删除</button>
            </div>
          </div>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-session-switch]').forEach(function (button) {
      button.addEventListener('click', function () {
        switchSession(this.getAttribute('data-session-switch'));
      });
    });

    list.querySelectorAll('[data-session-delete]').forEach(function (button) {
      button.addEventListener('click', function () {
        deleteSession(this.getAttribute('data-session-delete'));
      });
    });

    list.querySelectorAll('[data-session-menu-toggle]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        const sessionId = this.getAttribute('data-session-menu-toggle');
        openSessionMenuId = openSessionMenuId === sessionId ? null : sessionId;
        renderSessionList();
      });
    });

    list.querySelectorAll('[data-session-rename]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        renameSession(this.getAttribute('data-session-rename'));
      });
    });
  }

  function switchSession(sessionId) {
    if (!sessionId || !chatSessions.find(function (session) { return session.id === sessionId; })) return;
    openSessionMenuId = null;
    activeSessionId = sessionId;
    renderActiveSessionMessages();
    saveSessionsToLocal();
    if (window.PageShell && typeof window.PageShell.closeGlobalSidebar === 'function') {
      window.PageShell.closeGlobalSidebar();
    }
  }

  function deleteSession(sessionId) {
    if (!sessionId) return;

    const target = chatSessions.find(function (session) {
      return session.id === sessionId;
    });
    if (!target) return;

    openSessionMenuId = null;
    if (!window.confirm(`确认删除对话“${target.title || '新对话'}”吗？`)) return;

    chatSessions = chatSessions.filter(function (session) {
      return session.id !== sessionId;
    });

    if (!chatSessions.length) {
      const nextSession = createEmptySession();
      chatSessions = [nextSession];
      activeSessionId = nextSession.id;
      clearChatDom();
      saveSessionsToLocal();
      ensureWelcomeMessage();
      renderSessionList();
      return;
    }

    if (activeSessionId === sessionId) {
      activeSessionId = chatSessions[0].id;
    }

    renderActiveSessionMessages();
    saveSessionsToLocal();
  }

  function renameSession(sessionId) {
    const session = chatSessions.find(function (item) {
      return item.id === sessionId;
    }) || getActiveSession();
    if (!session) return;

    openSessionMenuId = null;
    const nextTitle = window.prompt('请输入新的会话名称：', session.title || '新对话');
    if (nextTitle === null) return;

    const trimmed = nextTitle.trim();
    if (!trimmed) return;

    session.title = trimmed.slice(0, 40);
    session.updatedAt = Date.now();
    chatSessions = [session].concat(chatSessions.filter(function (item) {
      return item.id !== session.id;
    })).slice(0, MAX_CHAT_SESSIONS);
    activeSessionId = session.id;
    renderSessionList();
    saveSessionsToLocal();
  }

  function toggleSidebarHistory() {
    sidebarHistoryCollapsed = !sidebarHistoryCollapsed;
    saveSidebarHistoryState();
    renderSessionList();
  }

  function closeSessionMenu() {
    if (!openSessionMenuId) return;
    openSessionMenuId = null;
    renderSessionList();
  }

  function clearActiveSessionMessages() {
    const session = getActiveSession();
    if (!session) return;

    if (!window.confirm('确认清空当前对话的所有消息吗？')) return;

    session.messages = [];
    session.updatedAt = Date.now();
    clearChatDom();
    saveSessionsToLocal();
    addMessage('已清空当前对话。你可以继续提新问题。', 'ai', {
      source: 'system',
      aiUsed: true,
      error: ''
    });
  }

  function createNewSession() {
    const session = createEmptySession();
    openSessionMenuId = null;
    chatSessions.unshift(session);
    chatSessions = chatSessions.slice(0, MAX_CHAT_SESSIONS);
    activeSessionId = session.id;
    clearChatDom();
    saveSessionsToLocal();
    addMessage(WELCOME_MESSAGE, 'ai', { source: 'system', aiUsed: true, error: '' });
    renderSessionList();
    focusComposer();
  }

  function openTaskStatusModal(taskId, payload) {
    const modal = document.getElementById('taskStatusModal');
    const body = document.getElementById('taskModalBody');
    if (!modal || !body) return;

    taskModalTaskId = taskId;
    const data = payload || {};
    const state = data.state || 'UNKNOWN';
    const taskType = (data.task_meta && data.task_meta.task_type) || 'unknown';
    const resultText = data.result ? escapeHtml(JSON.stringify(data.result, null, 2)) : '';
    const errorText = data.error ? escapeHtml(String(data.error)) : '';

    body.innerHTML = `
      <div><strong>Task ID:</strong> ${escapeHtml(String(taskId || ''))}</div>
      <div><strong>任务类型:</strong> ${escapeHtml(taskType)}</div>
      <div><strong>状态:</strong><span class="task-status-pill">${escapeHtml(state)}</span></div>
      <div style="margin-top:8px;"><strong>创建时间:</strong> ${escapeHtml((data.task_meta && data.task_meta.created_at) || '--')}</div>
      <div style="margin-top:8px;"><strong>用户:</strong> ${escapeHtml((data.task_meta && data.task_meta.user_id) || '--')}</div>
      ${errorText ? `<div style="margin-top:8px; color:#b91c1c;"><strong>错误:</strong> ${errorText}</div>` : ''}
      ${resultText ? `<div style="margin-top:8px;"><strong>结果:</strong><pre style="background:#0f172a;color:#e2e8f0;border-radius:8px;padding:8px;overflow:auto;">${resultText}</pre></div>` : ''}
    `;

    modal.classList.add('show');
  }

  async function refreshTaskStatusModal() {
    if (!taskModalTaskId) return;

    try {
      const response = await fetch(`${API_BASE}/api/tasks/${encodeURIComponent(taskModalTaskId)}`);
      const data = await response.json();
      openTaskStatusModal(taskModalTaskId, data);

      const terminalStates = ['SUCCESS', 'FAILURE', 'REVOKED'];
      if (terminalStates.includes(String(data.state || '').toUpperCase())) {
        stopTaskStatusAutoRefresh();
      }
    } catch (error) {
      openTaskStatusModal(taskModalTaskId, {
        state: 'FAILED_TO_FETCH',
        error: '任务状态查询失败，请稍后再试。'
      });
      stopTaskStatusAutoRefresh();
    }
  }

  function startTaskStatusAutoRefresh() {
    stopTaskStatusAutoRefresh();
    taskModalAutoEnabled = true;
    updateTaskModalAutoButton();
    taskModalAutoTimer = setInterval(refreshTaskStatusModal, 1000);
  }

  function stopTaskStatusAutoRefresh() {
    taskModalAutoEnabled = false;
    updateTaskModalAutoButton();
    if (taskModalAutoTimer) {
      clearInterval(taskModalAutoTimer);
      taskModalAutoTimer = null;
    }
  }

  function toggleTaskStatusAutoRefresh() {
    if (taskModalAutoEnabled) {
      stopTaskStatusAutoRefresh();
    } else {
      startTaskStatusAutoRefresh();
    }
  }

  function updateTaskModalAutoButton() {
    const autoButton = document.getElementById('taskModalAutoBtn');
    if (autoButton) {
      autoButton.textContent = `自动刷新：${taskModalAutoEnabled ? '开' : '关'}`;
    }
  }

  function closeTaskStatusModal() {
    const modal = document.getElementById('taskStatusModal');
    if (modal) {
      modal.classList.remove('show');
    }
    taskModalTaskId = null;
    stopTaskStatusAutoRefresh();
  }

  function addTypingMessage() {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;

    const row = document.createElement('div');
    row.className = 'message-row assistant';
    row.id = 'typingRow';
    row.innerHTML = `
      <div class="avatar">AI</div>
      <div class="message-bubble">
        <div class="typing-dots"><span></span><span></span><span></span></div>
      </div>
    `;
    chatMessages.appendChild(row);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function removeTypingMessage() {
    const typingRow = document.getElementById('typingRow');
    if (typingRow && typingRow.parentNode) {
      typingRow.parentNode.removeChild(typingRow);
    }
  }

  function setComposerBusy(busy) {
    const button = document.getElementById('askQuestionBtn');
    if (!button) return;
    button.disabled = !!busy;
    button.textContent = busy ? '...' : '↑';

    const newChatButton = document.getElementById('newChatBtn');
    if (newChatButton) {
      newChatButton.disabled = !!busy;
    }
  }

  function focusComposer() {
    const input = document.getElementById('questionInput');
    if (input) {
      input.focus();
    }
  }

  async function refreshAiStatus() {
    const dot = document.getElementById('aiStatusDot');
    const text = document.getElementById('aiStatusText');
    if (!dot || !text) return;

    try {
      const response = await fetch(`${API_BASE}/health`);
      const data = await response.json();
      const online = !!(data.ai_enabled && data.ai_key_configured);
      dot.className = `status-dot ${online ? 'online' : 'offline'}`;
      text.textContent = online ? `AI在线 · ${data.provider || 'qwen'}` : 'AI未配置或不可用';
    } catch (error) {
      dot.className = 'status-dot offline';
      text.textContent = '后端离线';
    }
  }

  async function autoExtractKnowledge(text, source) {
    if (!text) return {};

    try {
      const response = await fetch(`${API_BASE}/api/knowledge_graph/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          text: text,
          source: source
        })
      });
      return await response.json();
    } catch (error) {
      console.warn('知识抽取触发失败:', error);
      return {};
    }
  }

  async function askQuestion(prefilledQuestion) {
    if (isAskingQuestion) return;

    const input = document.getElementById('questionInput');
    if (!input) return;

    const question = String(prefilledQuestion || input.value || '').trim();
    if (!question) return;

    isAskingQuestion = true;
    setComposerBusy(true);

    addMessage(question, 'user');
    input.value = '';
    addTypingMessage();

    try {
      let response = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question,
          user_id: getUserId()
        })
      });

      if (response.status === 405) {
        const query = new URLSearchParams({
          question: question,
          user_id: getUserId()
        });
        response = await fetch(`${API_BASE}/api/ask?${query.toString()}`, {
          method: 'GET'
        });
      }

      const data = await parseApiResponse(response);
      const extractData = await autoExtractKnowledge(question, 'qa');

      removeTypingMessage();
      addMessage(normalizeAiAnswerText(data.answer), 'ai', {
        source: data.source,
        aiUsed: data.ai_used,
        error: data.error,
        graphSync: extractData.graph_sync || null
      });
    } catch (error) {
      removeTypingMessage();
      addMessage(withSuggestion('抱歉，问答失败', error, '确认后端与AI配置正常后再试'), 'ai', {
        source: 'system',
        aiUsed: false,
        error: error && error.message ? error.message : 'network_error'
      });
    } finally {
      isAskingQuestion = false;
      setComposerBusy(false);
      refreshAiStatus();
      focusComposer();
    }
  }

  function updateUserBadge() {
    const badge = document.getElementById('chatUserBadge');
    const label = getUserLabel();
    if (badge) {
      badge.textContent = `当前身份：${label}`;
    }
  }

  function initConversationUI() {
    restoreSidebarHistoryState();
    loadSessionsFromLocal();
    ensureActiveSession();

    const active = getActiveSession();
    if (active && (!active.messages || active.messages.length === 0)) {
      clearChatDom();
      ensureWelcomeMessage();
    } else {
      renderActiveSessionMessages();
    }

    const newButton = document.getElementById('newChatBtn');
    if (newButton && !newButton.dataset.bound) {
      newButton.addEventListener('click', createNewSession);
      newButton.dataset.bound = '1';
    }
  }

  function initComposer() {
    const input = document.getElementById('questionInput');
    const sendButton = document.getElementById('askQuestionBtn');
    if (!input || !sendButton) return;

    if (!sendButton.dataset.bound) {
      sendButton.addEventListener('click', function () {
        askQuestion();
      });
      sendButton.dataset.bound = '1';
    }

    if (!input.dataset.bound) {
      input.addEventListener('keypress', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          askQuestion();
        }
      });
      input.dataset.bound = '1';
    }
  }

  function initTaskModal() {
    const modal = document.getElementById('taskStatusModal');
    const closeButton = document.getElementById('taskModalCloseBtn');
    const refreshButton = document.getElementById('taskModalRefreshBtn');
    const autoButton = document.getElementById('taskModalAutoBtn');

    if (closeButton && !closeButton.dataset.bound) {
      closeButton.addEventListener('click', closeTaskStatusModal);
      closeButton.dataset.bound = '1';
    }

    if (refreshButton && !refreshButton.dataset.bound) {
      refreshButton.addEventListener('click', refreshTaskStatusModal);
      refreshButton.dataset.bound = '1';
    }

    if (autoButton && !autoButton.dataset.bound) {
      autoButton.addEventListener('click', toggleTaskStatusAutoRefresh);
      autoButton.dataset.bound = '1';
    }

    if (modal && !modal.dataset.bound) {
      modal.addEventListener('click', function (event) {
        if (event.target === modal) {
          closeTaskStatusModal();
        }
      });
      modal.dataset.bound = '1';
    }

    updateTaskModalAutoButton();
  }

  function initGlobalSidebar() {
    if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
      window.PageShell.initGlobalSidebar();
    }
  }

  function initSidebarHistory() {
    const toggle = document.getElementById('sidebarHistoryToggle');
    if (toggle && !toggle.dataset.bound) {
      toggle.addEventListener('click', toggleSidebarHistory);
      toggle.dataset.bound = '1';
    }

    if (!document.body.dataset.chatSessionMenuBound) {
      document.addEventListener('click', function (event) {
        if (!event.target.closest('.sidebar-conversation-menu-wrap')) {
          closeSessionMenu();
        }
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          closeSessionMenu();
        }
      });
      document.body.dataset.chatSessionMenuBound = '1';
    }
  }

  function applyStartupQuestion() {
    const params = new URLSearchParams(window.location.search || '');
    const startupQuestion = String(params.get('q') || '').trim();
    if (!startupQuestion) return;

    askQuestion(startupQuestion);
    params.delete('q');
    const next = params.toString();
    window.history.replaceState({}, '', next ? `${window.location.pathname}?${next}` : window.location.pathname);
  }

  function initReactiveBindings() {
    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        updateUserBadge();
        initConversationUI();
      });
    }

    window.addEventListener('storage', function (event) {
      if (event.key === getChatStoreKey()) {
        initConversationUI();
      }
    });
  }

  function init() {
    updateUserBadge();
    initSidebarHistory();
    initConversationUI();
    initComposer();
    initTaskModal();
    initGlobalSidebar();
    initReactiveBindings();
    refreshAiStatus();
    applyStartupQuestion();
    focusComposer();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
