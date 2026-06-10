(function () {
  const API_BASE = window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
    ? window.ApiUtils.getApiBase()
    : (window.location.origin || '');
  const MAX_CHAT_SESSIONS = 20;
  const MAX_MESSAGES_PER_SESSION = 120;
  const MAX_RENDER_MESSAGES = 80;
  const MAX_MESSAGE_TEXT_LENGTH = 12000;
  const STORE_SCOPE_KEY = 'fangzhigong_question_bank_scope_v1';
  const STORE_CONCEPT_KEY = 'fangzhigong_question_bank_concept_v1';
  const WELCOME_MESSAGE = '这里是题库练习页。你可以直接自由提问，也可以先填写要考察的知识点，再点击“题库练习”进入练题模式。AI 题库只作为练习来源存在，不展示题库明细。';

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
  let isWorking = false;
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
    return `fangzhigong_question_bank_sidebar_history_collapsed_${getUserId()}`;
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
      console.warn('保存练习侧栏状态失败:', error);
    }
  }

  function normalizeBankScope(scope) {
    const value = String(scope || '').trim().toLowerCase();
    if (value === 'official') return 'ai';
    if (value === 'all') return 'both';
    if (value === 'ai' || value === 'mine' || value === 'both') return value;
    return 'both';
  }

  function normalizeDrawConcept(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function getScopeLabel(scope) {
    const normalized = normalizeBankScope(scope);
    if (normalized === 'ai') return 'AI题库';
    if (normalized === 'mine') return '我的题库';
    return '全部题库';
  }

  function getDifficultyLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'easy') return '简单';
    if (normalized === 'hard') return '困难';
    return '中等';
  }

  function getQuestionTypeLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'short_answer') return '简答题';
    if (normalized === 'retry') return '错题重练';
    return '单选题';
  }

  function normalizePendingQuestion(question, fallbackScope) {
    if (!question || typeof question !== 'object') return null;
    const id = String(question.id || '').trim();
    const stem = String(question.question || '').trim();
    if (!id || !stem) return null;

    return {
      id: id,
      concept: String(question.concept || '综合').trim() || '综合',
      difficulty: String(question.difficulty || 'medium').trim().toLowerCase() || 'medium',
      question_type: String(question.question_type || 'single_choice').trim().toLowerCase() || 'single_choice',
      question: stem,
      options: Array.isArray(question.options) ? question.options.map(function (item) {
        return String(item || '').trim();
      }).filter(Boolean) : [],
      scope: normalizeBankScope(question.scope || fallbackScope || 'ai')
    };
  }

  function createEmptySession() {
    const ts = Date.now();
    return {
      id: `qb_session_${ts}_${Math.random().toString(36).slice(2, 7)}`,
      title: '新练习',
      updatedAt: ts,
      messages: [],
      pendingQuestion: null
    };
  }

  function normalizeMessageText(text) {
    const content = String(text || '');
    if (content.length <= MAX_MESSAGE_TEXT_LENGTH) return content;
    return `${content.slice(0, MAX_MESSAGE_TEXT_LENGTH)}\n\n[内容过长，已为提升性能自动截断]`;
  }

  function shouldRenderMathText(text) {
    const content = String(text || '');
    if (!content) return false;
    return /(\$\$|\$[^\n$]+\$|\\\(|\\\[)/.test(content);
  }

  function getQuestionBankStoreKey() {
    if (window.ProjectLocalData && typeof window.ProjectLocalData.getQuestionBankChatStoreKey === 'function') {
      return window.ProjectLocalData.getQuestionBankChatStoreKey(getUserId());
    }
    return `fangzhigong_question_bank_sessions_${getUserId()}`;
  }

  function saveSessionsToLocal() {
    try {
      const compactSessions = chatSessions
        .slice(0, MAX_CHAT_SESSIONS)
        .map(function (session) {
          const messages = Array.isArray(session.messages)
            ? session.messages.slice(-MAX_MESSAGES_PER_SESSION).map(function (message) {
                return {
                  text: normalizeMessageText(message && message.text),
                  sender: String((message && message.sender) || 'ai'),
                  options: message && typeof message.options === 'object' ? message.options : {},
                  time: Number((message && message.time) || Date.now())
                };
              })
            : [];

          return {
            id: String(session.id || '').trim(),
            title: String(session.title || '新练习').trim() || '新练习',
            updatedAt: Number(session.updatedAt || Date.now()),
            messages: messages,
            pendingQuestion: normalizePendingQuestion(session.pendingQuestion)
          };
        });

      localStorage.setItem(getQuestionBankStoreKey(), JSON.stringify({
        activeSessionId: activeSessionId,
        sessions: compactSessions
      }));
    } catch (error) {
      console.warn('保存题库问答会话失败:', error);
    }
  }

  function loadSessionsFromLocal() {
    try {
      if (window.ProjectLocalData && typeof window.ProjectLocalData.ensureQuestionBankStoreForUser === 'function') {
        window.ProjectLocalData.ensureQuestionBankStoreForUser(getUserId(), MAX_CHAT_SESSIONS);
      }

      const raw = localStorage.getItem(getQuestionBankStoreKey());
      if (!raw) {
        chatSessions = [];
        activeSessionId = null;
        return;
      }

      const parsed = JSON.parse(raw);
      chatSessions = Array.isArray(parsed && parsed.sessions)
        ? parsed.sessions.map(function (session) {
            return {
              id: String(session.id || '').trim(),
              title: String(session.title || '新练习').trim() || '新练习',
              updatedAt: Number(session.updatedAt || Date.now()),
              messages: Array.isArray(session.messages) ? session.messages.slice(-MAX_MESSAGES_PER_SESSION).map(function (message) {
                return {
                  text: normalizeMessageText((message && message.text) || ''),
                  sender: String((message && message.sender) || 'ai'),
                  options: message && typeof message.options === 'object' ? message.options : {},
                  time: Number((message && message.time) || Date.now())
                };
              }) : [],
              pendingQuestion: normalizePendingQuestion(session.pendingQuestion)
            };
          }).filter(function (session) {
            return !!session.id;
          }).slice(0, MAX_CHAT_SESSIONS)
        : [];
      activeSessionId = parsed && parsed.activeSessionId ? parsed.activeSessionId : null;
    } catch (error) {
      console.warn('读取题库问答会话失败:', error);
      chatSessions = [];
      activeSessionId = null;
    }
  }

  function getActiveSession() {
    return chatSessions.find(function (session) {
      return session.id === activeSessionId;
    }) || null;
  }

  function reorderSession(session) {
    chatSessions = [session].concat(chatSessions.filter(function (item) {
      return item.id !== session.id;
    })).slice(0, MAX_CHAT_SESSIONS);
    activeSessionId = session.id;
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
    if (session.title && session.title !== '新练习') return;

    const raw = String(text || '').trim();
    if (!raw) return;
    session.title = raw.length > 18 ? `${raw.slice(0, 18)}...` : raw;
  }

  function touchSession(session) {
    if (!session) return;
    session.updatedAt = Date.now();
    reorderSession(session);
    saveSessionsToLocal();
    renderSessionList();
    updateQuestionModeUI();
  }

  function setPendingQuestion(question) {
    const session = ensureActiveSession();
    const normalized = normalizePendingQuestion(question, question && question.scope);
    session.pendingQuestion = normalized;
    if (
      normalized &&
      (!session.title || session.title === '新练习')
    ) {
      session.title = `${normalized.concept}练习`;
    }
    touchSession(session);
  }

  function clearPendingQuestion() {
    const session = ensureActiveSession();
    session.pendingQuestion = null;
    touchSession(session);
  }

  function getPendingQuestion() {
    const session = getActiveSession();
    return session && session.pendingQuestion ? session.pendingQuestion : null;
  }

  function getSelectedScope() {
    const select = document.getElementById('questionBankScope');
    return normalizeBankScope(select ? select.value : 'ai');
  }

  function getSelectedConcept() {
    const input = document.getElementById('questionBankConcept');
    return normalizeDrawConcept(input ? input.value : '');
  }

  function saveSelectedScope(scope) {
    try {
      localStorage.setItem(STORE_SCOPE_KEY, normalizeBankScope(scope));
    } catch (error) {
      console.warn('保存题库范围失败:', error);
    }
  }

  function restoreSelectedScope() {
    let scope = 'ai';
    try {
      scope = normalizeBankScope(localStorage.getItem(STORE_SCOPE_KEY) || 'ai');
    } catch (error) {
      scope = 'ai';
    }

    const select = document.getElementById('questionBankScope');
    if (select) {
      select.value = scope;
    }
  }

  function saveSelectedConcept(concept) {
    try {
      localStorage.setItem(STORE_CONCEPT_KEY, normalizeDrawConcept(concept));
    } catch (error) {
      console.warn('保存题库知识点失败:', error);
    }
  }

  function restoreSelectedConcept() {
    let concept = '';
    try {
      concept = normalizeDrawConcept(localStorage.getItem(STORE_CONCEPT_KEY) || '');
    } catch (error) {
      concept = '';
    }

    const input = document.getElementById('questionBankConcept');
    if (input) {
      input.value = concept;
    }
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

  function isTableSeparatorLine(line) {
    return /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line);
  }

  function renderTableSegment(lines) {
    if (lines.length < 2) return '';

    const headerCells = lines[0].replace(/^\||\|$/g, '').split('|').map(function (cell) {
      return formatInline(escapeHtml(cell.trim()));
    });
    const bodyRows = lines.slice(2).map(function (line) {
      return line.replace(/^\||\|$/g, '').split('|').map(function (cell) {
        return formatInline(escapeHtml(cell.trim()));
      });
    }).filter(function (cells) {
      return cells.length && cells.some(function (cell) { return String(cell).trim() !== ''; });
    });

    return `
      <table class="markdown-table">
        <thead><tr>${headerCells.map(function (cell) { return `<th>${cell}</th>`; }).join('')}</tr></thead>
        <tbody>${bodyRows.map(function (cells) {
          return `<tr>${cells.map(function (cell) { return `<td>${cell}</td>`; }).join('')}</tr>`;
        }).join('')}</tbody>
      </table>
    `;
  }

  function renderHeadingSegment(text) {
    const match = text.match(/^(#{1,6})\s+(.+)$/);
    if (!match) return '';
    const level = Math.min(6, Math.max(1, match[1].length));
    return `<h${level}>${formatInline(match[2].trim())}</h${level}>`;
  }

  function renderHeadingAndBodySegment(lines) {
    if (!lines.length) return '';
    const headingHtml = renderHeadingSegment(lines[0]);
    if (!headingHtml || lines.length < 2) return '';

    const bodyHtml = formatSegment(lines.slice(1).join('\n'));
    return `${headingHtml}${bodyHtml}`;
  }

  function formatSegment(segment) {
    const trimmed = segment.trim();
    if (!trimmed) return '';

    const normalized = trimmed.replace(/<br\s*\/??\s*>/gi, '\n');

    const headingHtml = renderHeadingSegment(normalized);
    if (headingHtml) {
      return headingHtml;
    }

    const lines = normalized.split('\n').filter(Boolean);
    const headingAndBodyHtml = renderHeadingAndBodySegment(lines);
    if (headingAndBodyHtml) {
      return headingAndBodyHtml;
    }

    const unordered = lines.every(function (line) { return /^[-*•]\s+/.test(line); });
    const ordered = lines.every(function (line) { return /^\d+\.\s+/.test(line); });

    if (lines.length >= 2 && isTableSeparatorLine(lines[1]) && lines[0].includes('|')) {
      return renderTableSegment(lines);
    }

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

    return `<p>${formatInline(normalized.replace(/\n/g, '<br>'))}</p>`;
  }

  function renderRichText(text) {
    const safe = escapeHtml(text)
      .replace(/\r\n/g, '\n')
      .replace(/&lt;br\s*\/?\s*&gt;/gi, '\n');
    const chunks = safe.split(/```/);
    const html = chunks.map(function (chunk, idx) {
      if (idx % 2 === 1) {
        return `<pre><code>${chunk.trim()}</code></pre>`;
      }

      const mathBlocks = [];
      const withPlaceholders = chunk.replace(/\$\$([\s\S]*?)\$\$/g, function (_, body) {
        const token = `@@QB_MATH_${mathBlocks.length}@@`;
        mathBlocks.push(`<div class="math-block">$$${body.trim()}$$</div>`);
        return token;
      });

      let bodyHtml = withPlaceholders
        .split(/\n\s*\n/)
        .map(formatSegment)
        .join('');

      mathBlocks.forEach(function (blockHtml, index) {
        bodyHtml = bodyHtml.replace(`@@QB_MATH_${index}@@`, blockHtml);
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
      .replace(/＄/g, '$');
  }

  function normalizeAiAnswerText(text) {
    const content = normalizeMathText(String(text || ''));
    const hasGarbledHint = /[?？]{8,}/.test(content) || /�/.test(content);
    if (!hasGarbledHint) return content;
    return [
      '检测到回答可能存在编码异常，建议重发一次问题，或改用更短的中文句子提问。',
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
          { left: '\\[', right: '\\]', display: true }
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
    if (sender === 'ai' && opts.badge) {
      metaItems.push(`<span class="meta-chip">${escapeHtml(opts.badge)}</span>`);
    }
    if (sender === 'ai' && opts.source) {
      metaItems.push(`<span class="meta-chip">来源：${escapeHtml(opts.source)}</span>`);
    }
    if (sender === 'ai' && typeof opts.aiUsed === 'boolean') {
      metaItems.push(`<span class="meta-chip">${opts.aiUsed ? '真实AI回答' : '系统或规则反馈'}</span>`);
    }
    if (sender === 'ai' && opts.error) {
      metaItems.push(`<span class="meta-chip error">${escapeHtml(opts.error)}</span>`);
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
      text: normalizeMessageText(text),
      sender: sender,
      options: options || {},
      time: Date.now()
    };

    session.messages = Array.isArray(session.messages) ? session.messages : [];
    session.messages.push(message);
    if (session.messages.length > MAX_MESSAGES_PER_SESSION) {
      session.messages = session.messages.slice(-MAX_MESSAGES_PER_SESSION);
    }
    session.updatedAt = message.time;
    updateSessionTitle(session, text, sender);
    reorderSession(session);
    saveSessionsToLocal();
  }

  function addMessage(text, sender, options, persist) {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return null;

    const row = createMessageRow(text, sender, options || {});
    chatMessages.appendChild(row);
    if (sender === 'ai' && shouldRenderMathText(text)) {
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

  function scrollChatToLatest() {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;

    let attempts = 0;
    const doScroll = () => {
      // 1. 如果是容器内局部滚动
      chatMessages.scrollTop = chatMessages.scrollHeight;
      
      // 2. 如果因为 css 布局问题变成了全局 / window 级别的滚动，则兜底强制底部元素进入视野
      if (chatMessages.lastElementChild && typeof chatMessages.lastElementChild.scrollIntoView === 'function') {
        chatMessages.lastElementChild.scrollIntoView({ behavior: 'auto', block: 'end' });
      } else {
        window.scrollTo(0, document.body.scrollHeight);
      }
    };
    
    doScroll();
    
    // 持续 1.5 秒尝试滚动到底部，保证包含任何图片、公式等异步撑开高度后的节点都能被定位
    const interval = setInterval(() => {
      doScroll();
      attempts++;
      if (attempts >= 30) {
        clearInterval(interval);
      }
    }, 50);
  }

  function ensureWelcomeMessage() {
    const session = ensureActiveSession();
    if (Array.isArray(session.messages) && session.messages.length > 0) return;
    session.messages = [];
    session.pendingQuestion = null;
    session.updatedAt = Date.now();
    activeSessionId = session.id;
    saveSessionsToLocal();
    addMessage(WELCOME_MESSAGE, 'ai', { badge: '系统引导', aiUsed: true, source: 'system' });
    scrollChatToLatest();
  }

  function renderActiveSessionMessages() {
    const session = ensureActiveSession();
    clearChatDom();
    const messages = Array.isArray(session.messages) ? session.messages : [];
    const startIndex = Math.max(0, messages.length - MAX_RENDER_MESSAGES);

    if (startIndex > 0) {
      addMessage(`历史消息较多，已为流畅度仅展示最近 ${MAX_RENDER_MESSAGES} 条。`, 'ai', {
        badge: '性能优化',
        source: 'system',
        aiUsed: false,
        error: ''
      }, false);
    }

    messages.slice(startIndex).forEach(function (message) {
      addMessage(message.text, message.sender, message.options || {}, false);
    });
    renderSessionList();
    updateQuestionModeUI();
    scrollChatToLatest();
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
      list.innerHTML = '<div class="conversation-empty">暂无练习记录</div>';
      return;
    }

    chatSessions.sort(function (a, b) {
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    });

    list.innerHTML = chatSessions.map(function (session) {
      const activeClass = session.id === activeSessionId ? 'active' : '';
      const menuOpen = openSessionMenuId === session.id ? 'show' : '';
      const menuActive = openSessionMenuId === session.id ? 'active' : '';
      const pendingBadge = session.pendingQuestion
        ? '<span class="conversation-status-pill">答题中</span>'
        : '';
      return `
        <div class="sidebar-conversation-item ${activeClass}" data-session-id="${escapeHtml(session.id)}">
          <button type="button" class="sidebar-conversation-main" data-session-switch="${escapeHtml(session.id)}">
            <div class="sidebar-conversation-title-row">
              <div class="sidebar-conversation-title">${escapeHtml(session.title || '新练习')}</div>
              ${pendingBadge}
            </div>
            <div class="sidebar-conversation-time">${escapeHtml(nowLabel(session.updatedAt))}</div>
          </button>
          <div class="sidebar-conversation-menu-wrap">
            <button
              type="button"
              class="sidebar-conversation-menu-btn ${menuActive}"
              data-session-menu-toggle="${escapeHtml(session.id)}"
              title="打开练习操作"
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
    if (!window.confirm(`确认删除练习“${target.title || '新练习'}”吗？`)) return;

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
      updateQuestionModeUI();
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
    const nextTitle = window.prompt('请输入新的练习名称：', session.title || '新练习');
    if (nextTitle === null) return;

    const trimmed = nextTitle.trim();
    if (!trimmed) return;

    session.title = trimmed.slice(0, 40);
    touchSession(session);
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

    if (!window.confirm('确认清空当前练习的所有消息和待答题状态吗？')) return;

    session.messages = [];
    session.pendingQuestion = null;
    session.updatedAt = Date.now();
    clearChatDom();
    saveSessionsToLocal();
    addMessage('已清空当前练习。你可以重新开始练习，或继续自由提问。', 'ai', {
      badge: '系统提示',
      aiUsed: false,
      source: 'system'
    });
    updateQuestionModeUI();
  }

  function createNewSession() {
    const session = createEmptySession();
    openSessionMenuId = null;
    chatSessions.unshift(session);
    chatSessions = chatSessions.slice(0, MAX_CHAT_SESSIONS);
    activeSessionId = session.id;
    clearChatDom();
    saveSessionsToLocal();
    addMessage(WELCOME_MESSAGE, 'ai', { badge: '系统引导', aiUsed: true, source: 'system' });
    renderSessionList();
    updateQuestionModeUI();
    focusComposer();
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

  function updatePrimaryButtonLabel() {
    const button = document.getElementById('askQuestionBtn');
    if (!button) return;
    if (isWorking) {
      button.textContent = '...';
      return;
    }
    button.textContent = getPendingQuestion() ? '提交' : '发送';
  }

  function setBusy(busy) {
    isWorking = !!busy;
    const button = document.getElementById('askQuestionBtn');
    if (button) {
      button.disabled = isWorking;
    }

    [
      'drawQuestionBtn',
      'questionBankConcept',
      'manageQuestionBankBtn',
      'newChatBtn',
      'submitAnswerBtn',
      'hintQuestionBtn',
      'endQuestionBtn',
      'composerHintBtn',
      'composerEndBtn'
    ].forEach(function (id) {
      const el = document.getElementById(id);
      if (el) {
        el.disabled = isWorking;
      }
    });

    const select = document.getElementById('questionBankScope');
    if (select) {
      select.disabled = isWorking;
    }

    updatePrimaryButtonLabel();
  }

  function focusComposer() {
    const input = document.getElementById('questionInput');
    if (input) {
      input.focus();
    }
  }

  function updateQuestionModeUI() {
    const pending = getPendingQuestion();
    const banner = document.getElementById('questionModeBanner');
    const title = document.getElementById('questionModeTitle');
    const subtitle = document.getElementById('questionModeSubtitle');
    const modeLabel = document.getElementById('composerModeLabel');
    const modeNote = document.getElementById('composerModeNote');
    const hintRow = document.getElementById('composerHintRow');
    const input = document.getElementById('questionInput');

    if (!banner || !title || !subtitle || !modeLabel || !modeNote || !hintRow || !input) {
      updatePrimaryButtonLabel();
      return;
    }

    if (pending) {
      banner.hidden = false;
      hintRow.hidden = false;
      title.textContent = `${pending.concept} · ${getQuestionTypeLabel(pending.question_type)} · ${getDifficultyLabel(pending.difficulty)}`;
      subtitle.textContent = `当前练习题库：${getScopeLabel(pending.scope)}。直接按 Enter 会提交答案；如果只想要思路提示，可以点击“问 AI 提示”。`;
      modeLabel.textContent = '当前模式：答题判定';
      modeNote.textContent = '发送按钮会提交当前题目的答案';
      input.placeholder = '请先回答这道题，或点击“问 AI 提示”获取思路';
    } else {
      banner.hidden = true;
      hintRow.hidden = true;
      title.textContent = '等待练习题';
      subtitle.textContent = '抽到题目后，这里会提示当前作答状态。';
      modeLabel.textContent = '当前模式：自由问答';
      modeNote.textContent = '按 `Enter` 发送，`Shift + Enter` 换行';
      input.placeholder = '输入你的学习问题，或先点击“题库练习”';
    }

    updatePrimaryButtonLabel();
  }

  function updateUserBadge() {
    const badge = document.getElementById('chatUserBadge');
    const label = getUserLabel();
    if (badge) {
      badge.textContent = `当前身份：${label}`;
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

  async function askApi(questionForApi, displayQuestion, metaOptions, extractSource) {
    const question = String(displayQuestion || '').trim();
    if (!question || isWorking) return;

    setBusy(true);
    addMessage(question, 'user');

    const input = document.getElementById('questionInput');
    if (input) {
      input.value = '';
    }
    addTypingMessage();

    try {
      let response = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: questionForApi,
          user_id: getUserId()
        })
      });

      if (response.status === 405) {
        const query = new URLSearchParams({
          question: questionForApi,
          user_id: getUserId()
        });
        response = await fetch(`${API_BASE}/api/ask?${query.toString()}`, {
          method: 'GET'
        });
      }

      const data = await parseApiResponse(response);
      if (extractSource) {
        await autoExtractKnowledge(question, extractSource);
      }

      removeTypingMessage();
      addMessage(normalizeAiAnswerText(data.answer), 'ai', Object.assign({
        source: data.source,
        aiUsed: data.ai_used,
        error: data.error || ''
      }, metaOptions || {}));
    } catch (error) {
      removeTypingMessage();
      addMessage(withSuggestion('抱歉，回答失败', error, '确认后端与AI配置正常后再试'), 'ai', {
        badge: (metaOptions && metaOptions.badge) || '系统提示',
        source: 'system',
        aiUsed: false,
        error: error && error.message ? error.message : 'network_error'
      });
    } finally {
      setBusy(false);
      refreshAiStatus();
      focusComposer();
    }
  }

  async function askFreeQuestion(prefilledQuestion) {
    const input = document.getElementById('questionInput');
    const question = String(prefilledQuestion || (input && input.value) || '').trim();
    if (!question) return;
    await askApi(question, question, { badge: '自由问答' }, 'qa');
  }

  function buildVisibleQuestionPrompt(questionItem) {
    const lines = [
      `【题库练习】知识点：${questionItem.concept || '综合'}｜难度：${getDifficultyLabel(questionItem.difficulty)}｜题型：${getQuestionTypeLabel(questionItem.question_type)}`,
      String(questionItem.question || '').trim()
    ];
    const options = Array.isArray(questionItem.options) ? questionItem.options : [];
    if (options.length) {
      options.forEach(function (option) {
        lines.push(String(option || '').trim());
      });
      lines.push('请直接回复选项字母（如 A）并说明你的理由。');
    } else {
      lines.push('请分步骤作答，我会给出反馈或继续提示。');
    }
    return lines.join('\n');
  }

  function buildHintPrompt(questionItem, userDraft) {
    const promptParts = [
      '你现在是练题辅导老师，请只给启发式提示，不要直接给出完整答案或最终选项。',
      '请优先给出：关键知识点、审题方向、第一步该怎么做。',
      '',
      '当前题目如下：',
      buildVisibleQuestionPrompt(questionItem)
    ];

    if (userDraft) {
      promptParts.push('');
      promptParts.push(`用户当前思路或请求：${userDraft}`);
    } else {
      promptParts.push('');
      promptParts.push('用户当前请求：请给我一个提示，先不要直接公布答案。');
    }

    return promptParts.join('\n');
  }

  async function drawQuestionFromBank() {
    if (isWorking) return;

    const conceptInput = document.getElementById('questionBankConcept');
    const concept = getSelectedConcept();
    if (!concept) {
      addMessage('开始题库练习前，请先填写要考察的知识点，例如“导数”或“牛顿第二定律”。', 'ai', {
        badge: '题库练习',
        source: 'question_bank',
        aiUsed: false,
        error: 'concept_required'
      });
      if (conceptInput) {
        conceptInput.focus();
      }
      return;
    }

    if (conceptInput) {
      conceptInput.value = concept;
    }
    saveSelectedConcept(concept);

    setBusy(true);
    addTypingMessage();

    try {
      const scope = getSelectedScope();
      const response = await fetch(
        `${API_BASE}/api/question_bank/draw?user_id=${encodeURIComponent(getUserId())}&bank_scope=${encodeURIComponent(scope)}&concept=${encodeURIComponent(concept)}`
      );
      const data = await parseApiResponse(response);
      removeTypingMessage();

      const question = normalizePendingQuestion(data.question || {}, scope);
      if (!question) {
        throw new Error('题库没有返回可用练习题');
      }

      setPendingQuestion(question);
      addMessage(buildVisibleQuestionPrompt(question), 'ai', {
        badge: '题库练习',
        source: 'question_bank',
        aiUsed: false,
        error: ''
      });
    } catch (error) {
      removeTypingMessage();
      addMessage(withSuggestion('开始练习失败', error, '确认后端服务运行后重试'), 'ai', {
        badge: '题库练习',
        source: 'question_bank',
        aiUsed: false,
        error: error && error.message ? error.message : 'draw_question_failed'
      });
    } finally {
      setBusy(false);
      focusComposer();
    }
  }

  async function submitPendingAnswer(prefilledAnswer) {
    const pending = getPendingQuestion();
    if (!pending || isWorking) return;

    const input = document.getElementById('questionInput');
    const answer = String(prefilledAnswer || (input && input.value) || '').trim();
    if (!answer) return;

    setBusy(true);
    addMessage(answer, 'user');
    if (input) {
      input.value = '';
    }
    addTypingMessage();

    try {
      const response = await fetch(`${API_BASE}/api/question_bank/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          question_id: pending.id,
          user_answer: answer
        })
      });
      const data = await parseApiResponse(response);
      removeTypingMessage();

      const scorePct = Math.round(Number(data.score || 0) * 100);
      const mastery = data.mastery_assessment || {};
      const advice = data.learning_advice || {};
      const diagnosis = data.diagnosis || {};
      const masteryPct = Math.round(Number(mastery['掌握度'] || 0) * 100);
      const feedbackText = [
        `判题结果：${data.is_correct ? '正确' : '待改进'}（${scorePct}分）`,
        data.feedback || '',
        mastery['知识点'] ? `知识掌握：${mastery['知识点']} · ${masteryPct}%（${mastery['状态'] || '一般'}）` : '',
        diagnosis.error_type ? `错误归因：${diagnosis.error_type}` : '',
        advice['建议'] ? `学习建议：${advice['建议']}` : '',
        Array.isArray(advice['推荐行动']) && advice['推荐行动'].length ? `推荐行动：${advice['推荐行动'].join('、')}` : '',
        !data.is_correct && data.expected_answer ? `参考答案：${data.expected_answer}` : '',
        data.next_action || '你可以继续题库练习，也可以切回自由问答。'
      ].filter(Boolean).join('\n');

      addMessage(feedbackText, 'ai', {
        badge: '判题反馈',
        source: 'question_bank',
        aiUsed: false,
        error: ''
      });
      clearPendingQuestion();
    } catch (error) {
      removeTypingMessage();
      addMessage(withSuggestion('提交答案失败', error, '稍后重试或结束本题'), 'ai', {
        badge: '判题反馈',
        source: 'question_bank',
        aiUsed: false,
        error: error && error.message ? error.message : 'answer_failed'
      });
    } finally {
      setBusy(false);
      refreshAiStatus();
      focusComposer();
    }
  }

  async function askHintForPendingQuestion() {
    const pending = getPendingQuestion();
    if (!pending || isWorking) return;

    const input = document.getElementById('questionInput');
    const userDraft = String((input && input.value) || '').trim();
    const displayQuestion = userDraft
      ? `基于我目前的思路，请给这道题一点提示：${userDraft}`
      : '请给我这道题一个提示，但先不要直接公布答案。';
    const hiddenQuestion = buildHintPrompt(pending, userDraft);

    await askApi(hiddenQuestion, displayQuestion, { badge: 'AI提示' }, '');
  }

  function endCurrentQuestion() {
    const pending = getPendingQuestion();
    if (!pending) return;

    if (!window.confirm('确认结束当前题目吗？结束后不会自动判题。')) return;

    clearPendingQuestion();
    addMessage('已结束当前题目。你可以继续题库练习，或直接切换回自由问答。', 'ai', {
      badge: '系统提示',
      source: 'system',
      aiUsed: false,
      error: ''
    });
    focusComposer();
  }

  function handlePrimaryAction() {
    if (getPendingQuestion()) {
      submitPendingAnswer();
      return;
    }
    askFreeQuestion();
  }

  function setManageStatus(text, isError) {
    const status = document.getElementById('qbManageStatus');
    if (!status) return;
    status.textContent = text || '';
    status.classList.toggle('error', !!isError);
  }

  function renderMyQuestionBankList(items) {
    const counter = document.getElementById('questionBankCounter');
    const summary = document.getElementById('questionBankModalCount');
    const list = document.getElementById('questionBankRecentList');
    const rows = Array.isArray(items) ? items : [];

    if (counter) {
      counter.textContent = `我的题库 ${rows.length} 题`;
    }
    if (summary) {
      summary.textContent = rows.length
        ? `当前共 ${rows.length} 题，预览展示最近 ${Math.min(rows.length, 6)} 题`
        : '你的题库还是空的，可以先手动新增或批量导入';
    }
    if (!list) return;

    if (!rows.length) {
      list.innerHTML = '<div class="question-bank-empty">你的题库还没有题目。新增后就可以在“我的题库”或“全部题库”中开始练习。</div>';
      return;
    }

    list.innerHTML = rows.slice(-6).reverse().map(function (item) {
      return `
        <div class="question-bank-item">
          <div class="question-bank-item-head">
            <div class="question-bank-item-concept">${escapeHtml(item.concept || '综合')}</div>
            <div class="question-bank-item-meta">${escapeHtml(getDifficultyLabel(item.difficulty))} · ${escapeHtml(getQuestionTypeLabel(item.question_type))}</div>
          </div>
          <div class="question-bank-item-question">${escapeHtml(item.question || '')}</div>
        </div>
      `;
    }).join('');
  }

  async function refreshMyQuestionBankList() {
    const response = await fetch(
      `${API_BASE}/api/question_bank/questions?user_id=${encodeURIComponent(getUserId())}&bank_scope=mine`
    );
    const data = await parseApiResponse(response);
    const questions = Array.isArray(data.questions) ? data.questions : [];
    renderMyQuestionBankList(questions);
    return questions;
  }

  function openQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    if (!modal) return;
    modal.classList.add('show');
    refreshMyQuestionBankList().catch(function (error) {
      setManageStatus(withSuggestion('题库加载失败', error, '稍后刷新重试'), true);
    });
  }

  function closeQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    if (modal) {
      modal.classList.remove('show');
    }
  }

  function initQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    const openBtn = document.getElementById('manageQuestionBankBtn');
    const closeBtn = document.getElementById('questionBankModalCloseBtn');
    const refreshBtn = document.getElementById('questionBankModalRefreshBtn');
    const importBtn = document.getElementById('qbImportBtn');
    const importText = document.getElementById('qbImportText');
    const addBtn = document.getElementById('qbAddBtn');
    const conceptEl = document.getElementById('qbConcept');
    const difficultyEl = document.getElementById('qbDifficulty');
    const typeEl = document.getElementById('qbType');
    const questionEl = document.getElementById('qbQuestion');
    const optionsEl = document.getElementById('qbOptions');
    const answerEl = document.getElementById('qbAnswer');
    const analysisEl = document.getElementById('qbAnalysis');

    if (openBtn && !openBtn.dataset.bound) {
      openBtn.addEventListener('click', openQuestionBankModal);
      openBtn.dataset.bound = '1';
    }

    if (closeBtn && !closeBtn.dataset.bound) {
      closeBtn.addEventListener('click', closeQuestionBankModal);
      closeBtn.dataset.bound = '1';
    }

    if (refreshBtn && !refreshBtn.dataset.bound) {
      refreshBtn.addEventListener('click', function () {
        setManageStatus('正在刷新题库...');
        refreshMyQuestionBankList()
          .then(function () {
            setManageStatus('题库已刷新。');
          })
          .catch(function (error) {
            setManageStatus(withSuggestion('题库刷新失败', error, '稍后重试'), true);
          });
      });
      refreshBtn.dataset.bound = '1';
    }

    if (modal && !modal.dataset.bound) {
      modal.addEventListener('click', function (event) {
        if (event.target === modal) {
          closeQuestionBankModal();
        }
      });
      modal.dataset.bound = '1';
    }

    if (typeEl && !typeEl.dataset.bound) {
      const updateOptionsState = function () {
        const isChoice = String(typeEl.value || 'single_choice') === 'single_choice';
        optionsEl.disabled = !isChoice;
        optionsEl.style.opacity = isChoice ? '1' : '0.55';
      };
      typeEl.addEventListener('change', updateOptionsState);
      updateOptionsState();
      typeEl.dataset.bound = '1';
    }

    if (importBtn && importText && !importBtn.dataset.bound) {
      importBtn.addEventListener('click', async function () {
        const text = importText.value.trim();
        if (!text) {
          setManageStatus('请先粘贴要导入的题目内容。', true);
          return;
        }

        importBtn.disabled = true;
        importBtn.textContent = '导入中...';
        setManageStatus('正在导入题目...');
        try {
          const response = await fetch(`${API_BASE}/api/question_bank/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              user_id: getUserId(),
              text: text
            })
          });
          const data = await parseApiResponse(response);
          importText.value = '';
          setManageStatus(`导入成功：新增 ${data.imported_count || 0} 题。`);
          await refreshMyQuestionBankList();
        } catch (error) {
          setManageStatus(withSuggestion('导题失败', error, '检查格式后重试'), true);
        } finally {
          importBtn.disabled = false;
          importBtn.textContent = '粘贴导入';
        }
      });
      importBtn.dataset.bound = '1';
    }

    if (addBtn && !addBtn.dataset.bound) {
      addBtn.addEventListener('click', async function () {
        const concept = conceptEl.value.trim();
        const difficulty = difficultyEl.value;
        const questionType = typeEl.value;
        const question = questionEl.value.trim();
        const answer = answerEl.value.trim();
        const analysis = analysisEl.value.trim();
        const options = optionsEl.value
          .split('\n')
          .map(function (line) { return line.trim(); })
          .filter(Boolean);

        if (!concept || !question || !answer) {
          setManageStatus('请至少填写知识点、题干和标准答案。', true);
          return;
        }
        if (questionType === 'single_choice' && options.length < 2) {
          setManageStatus('单选题至少需要 2 个选项。', true);
          return;
        }

        addBtn.disabled = true;
        addBtn.textContent = '保存中...';
        setManageStatus('正在保存题目...');
        try {
          const response = await fetch(`${API_BASE}/api/question_bank/questions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              user_id: getUserId(),
              concept: concept,
              difficulty: difficulty,
              question_type: questionType,
              question: question,
              options: options,
              answer: answer,
              analysis: analysis,
              is_public: false
            })
          });
          const data = await parseApiResponse(response);
          questionEl.value = '';
          optionsEl.value = '';
          answerEl.value = '';
          analysisEl.value = '';
          setManageStatus(`已加入题库：${(data.question && data.question.id) || '新题目'}`);
          await refreshMyQuestionBankList();
        } catch (error) {
          setManageStatus(withSuggestion('题目保存失败', error, '检查输入后重试'), true);
        } finally {
          addBtn.disabled = false;
          addBtn.textContent = '加入题库';
        }
      });
      addBtn.dataset.bound = '1';
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
    const submitBtn = document.getElementById('submitAnswerBtn');
    const hintBtn = document.getElementById('hintQuestionBtn');
    const endBtn = document.getElementById('endQuestionBtn');
    const composerHintBtn = document.getElementById('composerHintBtn');
    const composerEndBtn = document.getElementById('composerEndBtn');
    const drawBtn = document.getElementById('drawQuestionBtn');
    const scopeSelect = document.getElementById('questionBankScope');
    const conceptInput = document.getElementById('questionBankConcept');

    if (sendButton && !sendButton.dataset.bound) {
      sendButton.addEventListener('click', handlePrimaryAction);
      sendButton.dataset.bound = '1';
    }

    if (submitBtn && !submitBtn.dataset.bound) {
      submitBtn.addEventListener('click', submitPendingAnswer);
      submitBtn.dataset.bound = '1';
    }

    if (hintBtn && !hintBtn.dataset.bound) {
      hintBtn.addEventListener('click', askHintForPendingQuestion);
      hintBtn.dataset.bound = '1';
    }

    if (endBtn && !endBtn.dataset.bound) {
      endBtn.addEventListener('click', endCurrentQuestion);
      endBtn.dataset.bound = '1';
    }

    if (composerHintBtn && !composerHintBtn.dataset.bound) {
      composerHintBtn.addEventListener('click', askHintForPendingQuestion);
      composerHintBtn.dataset.bound = '1';
    }

    if (composerEndBtn && !composerEndBtn.dataset.bound) {
      composerEndBtn.addEventListener('click', endCurrentQuestion);
      composerEndBtn.dataset.bound = '1';
    }

    if (drawBtn && !drawBtn.dataset.bound) {
      drawBtn.addEventListener('click', drawQuestionFromBank);
      drawBtn.dataset.bound = '1';
    }

    if (scopeSelect && !scopeSelect.dataset.bound) {
      scopeSelect.addEventListener('change', function () {
        saveSelectedScope(this.value || 'ai');
      });
      scopeSelect.dataset.bound = '1';
    }

    if (conceptInput && !conceptInput.dataset.bound) {
      conceptInput.addEventListener('input', function () {
        saveSelectedConcept(this.value || '');
      });
      conceptInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          drawQuestionFromBank();
        }
      });
      conceptInput.dataset.bound = '1';
    }

    if (input && !input.dataset.bound) {
      input.addEventListener('keypress', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          handlePrimaryAction();
        }
      });
      input.dataset.bound = '1';
    }

    restoreSelectedConcept();
    restoreSelectedScope();
    updateQuestionModeUI();
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

    if (!document.body.dataset.questionBankSessionMenuBound) {
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
      document.body.dataset.questionBankSessionMenuBound = '1';
    }
  }

  function initReactiveBindings() {
    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        updateUserBadge();
        initConversationUI();
        refreshMyQuestionBankList().catch(function () {});
      });
    }

    window.addEventListener('storage', function (event) {
      if (event.key === getQuestionBankStoreKey()) {
        initConversationUI();
      }
      if (event.key === STORE_SCOPE_KEY) {
        restoreSelectedScope();
      }
      if (event.key === STORE_CONCEPT_KEY) {
        restoreSelectedConcept();
      }
    });
  }

  function init() {
    updateUserBadge();
    initSidebarHistory();
    initConversationUI();
    initComposer();
    initQuestionBankModal();
    initGlobalSidebar();
    initReactiveBindings();
    refreshAiStatus();
    focusComposer();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
