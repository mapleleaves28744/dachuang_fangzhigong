(function () {
  const API_BASE = window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
    ? window.ApiUtils.getApiBase()
    : (window.location.origin || '');
  const MAX_CHAT_SESSIONS = 20;
  const WELCOME_MESSAGE = '你好，我是坊知工学习助手。你可以直接提问，我会给出结构化、可执行的学习建议。';
  const TEXT_FILE_EXTENSIONS = ['.txt', '.md', '.markdown', '.json', '.csv', '.tsv', '.log'];
  const MAX_ATTACHMENTS_PER_MESSAGE = 6;
  const ATTACHMENT_TEXT_LIMIT = 24000;
  const ATTACHMENT_PROMPT_PER_FILE_LIMIT = 4200;
  const ATTACHMENT_PROMPT_TOTAL_LIMIT = 16000;
  const ATTACHMENT_KNOWLEDGE_LIMIT = 4000;
  const DEFAULT_ATTACHMENT_QUESTION = '请先总结我上传的资料，提炼关键知识点，并给出下一步学习建议。';
  const AUTO_AGENT_MODE_ENABLED = true;
  const KNOWLEDGE_UPDATED_AT_STORAGE_KEY = 'fangzhigong_knowledge_updated_at';
  const TYPING_RENDER_THROTTLE_MS = 120;
  const PDF_JS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  const PDF_JS_WORKER_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  const PRIVATE_ANSWER_HEADINGS = new Set([
    '分析',
    '思考',
    '思路',
    '推理',
    '推理过程',
    '内部分析',
    '内部推理',
    '解题分析',
    '路径判断',
    '证据链',
    '工具调用',
    '调用记录',
    '中间过程',
    'analysis',
    'reasoning',
    'thinking',
    'scratchpad'
  ]);
  const PUBLIC_ANSWER_HEADINGS = new Set([
    '讲解',
    '解答',
    '答案',
    '结论',
    '建议',
    '练习',
    '总结',
    '步骤',
    '解析',
    '说明',
    '复习建议',
    '下一步',
    '知识点',
    '易错点'
  ]);
  const INTERNAL_ANSWER_LINE_RE = /(?:`?tool_[a-z0-9_]+`?|agent_scratchpad|return_intermediate_steps|kb_retry_triggered|preferred_kb_tool|prompt injection)/i;

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
  let pendingAttachments = [];
  let pdfJsLoader = null;
  let agentModeEnabled = AUTO_AGENT_MODE_ENABLED;
  let typingMessageState = null;
  let streamingAnswerState = null;

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

  function loadAgentModeState() {
    agentModeEnabled = AUTO_AGENT_MODE_ENABLED;
  }

  function getUserLabel() {
    return window.UserContext && typeof window.UserContext.getUserLabel === 'function'
      ? window.UserContext.getUserLabel()
      : '访客';
  }

  function notifyKnowledgeUpdated() {
    try {
      localStorage.setItem(KNOWLEDGE_UPDATED_AT_STORAGE_KEY, String(Date.now()));
    } catch (error) {
      console.warn('写入知识更新标记失败:', error);
    }
    window.dispatchEvent(new Event('knowledge:updated'));
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

  function formatFileSize(bytes) {
    const size = Math.max(0, Number(bytes) || 0);
    if (size >= 1024 * 1024) {
      return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
    }
    if (size >= 1024) {
      return `${Math.max(1, Math.round(size / 1024))} KB`;
    }
    return `${size} B`;
  }

  function isTextLikeUpload(mime, lowerName) {
    if (String(mime || '').startsWith('text/')) return true;
    return TEXT_FILE_EXTENSIONS.some(function (ext) {
      return String(lowerName || '').endsWith(ext);
    });
  }

  function inferAttachmentKind(mime, lowerName) {
    const mimeText = String(mime || '').toLowerCase();
    const fileName = String(lowerName || '').toLowerCase();
    if (mimeText.startsWith('image/')) return 'image';
    if (mimeText.startsWith('audio/')) return 'audio';
    if (mimeText.startsWith('video/')) return 'video';
    if (mimeText.includes('pdf') || fileName.endsWith('.pdf')) return 'pdf';
    if (isTextLikeUpload(mimeText, fileName)) return 'note';
    return 'document';
  }

  function getAttachmentKindLabel(kind) {
    if (kind === 'image') return '图片';
    if (kind === 'pdf') return 'PDF';
    if (kind === 'note') return '文本';
    if (kind === 'audio') return '音频';
    if (kind === 'video') return '视频';
    return '文件';
  }

  function getAttachmentReadHint(kind) {
    if (kind === 'image') return '发送后自动 OCR 识别图片内容';
    if (kind === 'pdf') return '发送后提取 PDF 文本片段';
    if (kind === 'note') return '发送后读取文本内容';
    return '发送后附带文件元信息';
  }

  function buildAttachmentSignature(file) {
    return [
      String(file && file.name || ''),
      Number(file && file.size || 0),
      Number(file && file.lastModified || 0)
    ].join('::');
  }

  function normalizePendingAttachment(file) {
    const mime = String(file && file.type || '').toLowerCase();
    const lowerName = String(file && file.name || '').toLowerCase();
    const kind = inferAttachmentKind(mime, lowerName);
    return {
      id: `attach_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      signature: buildAttachmentSignature(file),
      file: file,
      name: String(file && file.name || '未命名文件'),
      mime: mime,
      size: Number(file && file.size || 0),
      kind: kind
    };
  }

  function summarizePendingAttachmentForMessage(attachment) {
    return {
      name: attachment.name,
      kind: getAttachmentKindLabel(attachment.kind),
      meta: `${attachment.mime || 'unknown'} · ${formatFileSize(attachment.size)}`,
      note: getAttachmentReadHint(attachment.kind)
    };
  }

  function clearPendingAttachments() {
    pendingAttachments = [];
    const fileInput = document.getElementById('composerFileInput');
    if (fileInput) {
      fileInput.value = '';
    }
    renderPendingAttachments();
  }

  function addPendingAttachments(files) {
    const next = pendingAttachments.slice();
    const seen = new Set(next.map(function (item) { return item.signature; }));
    let ignoredCount = 0;

    Array.from(files || []).forEach(function (file) {
      if (!(file instanceof File)) return;
      if (next.length >= MAX_ATTACHMENTS_PER_MESSAGE) {
        ignoredCount += 1;
        return;
      }

      const normalized = normalizePendingAttachment(file);
      if (seen.has(normalized.signature)) {
        ignoredCount += 1;
        return;
      }

      seen.add(normalized.signature);
      next.push(normalized);
    });

    pendingAttachments = next;
    renderPendingAttachments();

    if (ignoredCount > 0) {
      window.alert(`一次最多添加 ${MAX_ATTACHMENTS_PER_MESSAGE} 个附件，重复或超出的文件已忽略。`);
    }
  }

  function removePendingAttachment(attachmentId) {
    pendingAttachments = pendingAttachments.filter(function (item) {
      return item.id !== attachmentId;
    });
    renderPendingAttachments();
  }

  function renderPendingAttachments() {
    const container = document.getElementById('composerAttachments');
    if (!container) return;

    if (!pendingAttachments.length) {
      container.hidden = true;
      container.innerHTML = '';
      return;
    }

    container.hidden = false;
    container.innerHTML = `
      <div class="composer-attachments-head">
        <span>已选择 ${pendingAttachments.length} 个附件，直接发送会先让 AI 读取资料。</span>
        <button type="button" class="composer-attachments-clear" data-clear-attachments>清空</button>
      </div>
      <div class="composer-attachment-list">
        ${pendingAttachments.map(function (attachment) {
          return `
            <div class="composer-attachment-item">
              <div class="composer-attachment-main">
                <div class="composer-attachment-name">${escapeHtml(attachment.name)}</div>
                <div class="composer-attachment-meta">${escapeHtml(getAttachmentKindLabel(attachment.kind))} · ${escapeHtml(attachment.mime || 'unknown')} · ${escapeHtml(formatFileSize(attachment.size))}</div>
                <div class="composer-attachment-meta">${escapeHtml(getAttachmentReadHint(attachment.kind))}</div>
              </div>
              <button type="button" class="composer-attachment-remove" data-remove-attachment="${escapeHtml(attachment.id)}" aria-label="移除附件">×</button>
            </div>
          `;
        }).join('')}
      </div>
    `;

    container.querySelectorAll('[data-remove-attachment]').forEach(function (button) {
      button.addEventListener('click', function () {
        removePendingAttachment(this.getAttribute('data-remove-attachment'));
      });
    });

    const clearButton = container.querySelector('[data-clear-attachments]');
    if (clearButton) {
      clearButton.addEventListener('click', clearPendingAttachments);
    }
  }

  function sanitizeAttachmentText(text) {
    return String(text || '')
      .replace(/\u0000/g, '')
      .replace(/\r\n/g, '\n')
      .trim();
  }

  function truncateAttachmentText(text, limit) {
    const normalized = sanitizeAttachmentText(text);
    const maxLen = Math.max(1, Number(limit) || 0);
    if (!maxLen || normalized.length <= maxLen) return normalized;
    return `${normalized.slice(0, maxLen)}\n...(内容已截断)`;
  }

  async function readFileAsText(file) {
    if (!file || typeof file.text !== 'function') return '';
    return truncateAttachmentText(await file.text(), ATTACHMENT_TEXT_LIMIT);
  }

  async function ensurePdfJs() {
    if (window.pdfjsLib) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDF_JS_WORKER_URL;
      return window.pdfjsLib;
    }

    if (pdfJsLoader) {
      return pdfJsLoader;
    }

    pdfJsLoader = new Promise(function (resolve, reject) {
      const script = document.createElement('script');
      script.src = PDF_JS_URL;
      script.async = true;
      script.onload = function () {
        if (!window.pdfjsLib) {
          pdfJsLoader = null;
          reject(new Error('PDF 解析库加载失败'));
          return;
        }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDF_JS_WORKER_URL;
        resolve(window.pdfjsLib);
      };
      script.onerror = function () {
        pdfJsLoader = null;
        reject(new Error('PDF 解析库加载失败'));
      };
      document.head.appendChild(script);
    });

    return pdfJsLoader;
  }

  async function readPdfAsText(file) {
    if (!file) return '';

    const pdfjsLib = await ensurePdfJs();
    const buffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
    const fragments = [];

    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const text = content.items.map(function (item) {
        return String(item && item.str || '').trim();
      }).filter(Boolean).join(' ');

      if (text) {
        fragments.push(`[第${pageNumber}页] ${text}`);
      }

      if (fragments.join('\n').length >= ATTACHMENT_TEXT_LIMIT) {
        break;
      }
    }

    return truncateAttachmentText(fragments.join('\n'), ATTACHMENT_TEXT_LIMIT);
  }

  async function uploadImageForAttachment(file) {
    const formData = new FormData();
    formData.append('image', file);
    formData.append('user_id', getUserId());

    const response = await fetch(`${API_BASE}/api/upload_image`, {
      method: 'POST',
      body: formData
    });
    const data = await parseApiResponse(response);
    return {
      ocrText: truncateAttachmentText(data.ocr_text || '', ATTACHMENT_TEXT_LIMIT),
      detectedConcepts: Array.isArray(data.detected_concepts) ? data.detected_concepts : [],
      graphSync: data.graph_sync || null
    };
  }

  function buildAttachmentMetadataBlock(attachment) {
    return [
      `文件名：${attachment.name}`,
      `类型：${getAttachmentKindLabel(attachment.kind)}`,
      `MIME：${attachment.mime || 'unknown'}`,
      `大小：${formatFileSize(attachment.size)}`
    ].join('\n');
  }

  function buildPromptTextFromPreparedAttachments(question, attachments) {
    const normalizedQuestion = String(question || '').trim() || DEFAULT_ATTACHMENT_QUESTION;
    if (!attachments.length) {
      return normalizedQuestion;
    }

    const attachmentBlocks = attachments.map(function (attachment, index) {
      const lines = [
        `资料${index + 1}`,
        attachment.metadataBlock
      ];

      if (attachment.promptText) {
        lines.push('提取内容：');
        lines.push(attachment.promptText);
      } else {
        lines.push('说明：当前未能提取正文，以下回答仅能参考文件元信息。');
      }

      return lines.join('\n');
    });

    return [
      '以下是我刚上传的学习资料，请优先根据资料内容回答。',
      '如果资料里的信息不足，请明确告诉我还需要补充什么。',
      '',
      attachmentBlocks.join('\n\n'),
      '',
      `我的问题：${normalizedQuestion}`
    ].join('\n');
  }

  function buildDisplayQuestion(question, attachments) {
    const normalizedQuestion = String(question || '').trim();
    if (normalizedQuestion) return normalizedQuestion;
    if (attachments.length === 1) {
      return `请先帮我分析这个文件：${attachments[0].name}`;
    }
    return DEFAULT_ATTACHMENT_QUESTION;
  }

  function buildKnowledgeSeedText(question, attachments) {
    const parts = [];
    const normalizedQuestion = String(question || '').trim();
    if (normalizedQuestion) {
      parts.push(normalizedQuestion);
    }

    attachments.forEach(function (attachment) {
      if (attachment.knowledgeText && !attachment.graphSync) {
        parts.push(attachment.knowledgeText);
      }
    });

    return truncateAttachmentText(parts.join('\n\n'), ATTACHMENT_KNOWLEDGE_LIMIT);
  }

  async function prepareAttachmentsForQuestion(attachments) {
    const preparedAttachments = [];
    const warnings = [];
    let remainingPromptChars = ATTACHMENT_PROMPT_TOTAL_LIMIT;

    for (const attachment of attachments) {
      const prepared = {
        name: attachment.name,
        kind: attachment.kind,
        mime: attachment.mime,
        size: attachment.size,
        metadataBlock: buildAttachmentMetadataBlock(attachment),
        promptText: '',
        knowledgeText: '',
        graphSync: null
      };

      try {
        if (attachment.kind === 'image') {
          const imageData = await uploadImageForAttachment(attachment.file);
          const conceptText = imageData.detectedConcepts.length
            ? `识别到的知识点：${imageData.detectedConcepts.join('、')}`
            : '识别到的知识点：暂无';
          const imageText = imageData.ocrText || '图片中未提取到可用文字。';
          prepared.promptText = `${conceptText}\n${imageText}`;
          prepared.knowledgeText = imageData.ocrText;
          prepared.graphSync = imageData.graphSync;
        } else if (attachment.kind === 'pdf') {
          const pdfText = await readPdfAsText(attachment.file);
          if (pdfText) {
            prepared.promptText = pdfText;
            prepared.knowledgeText = pdfText;
          } else {
            warnings.push(`《${attachment.name}》暂未提取到 PDF 正文，已回退为文件元信息。`);
          }
        } else if (attachment.kind === 'note') {
          const textContent = await readFileAsText(attachment.file);
          if (textContent) {
            prepared.promptText = textContent;
            prepared.knowledgeText = textContent;
          } else {
            warnings.push(`《${attachment.name}》暂未读取到文本内容，已回退为文件元信息。`);
          }
        }
      } catch (error) {
        warnings.push(`《${attachment.name}》读取失败：${error && error.message ? error.message : '未知错误'}，已回退为文件元信息。`);
      }

      if (prepared.promptText && remainingPromptChars > 0) {
        const nextLimit = Math.min(ATTACHMENT_PROMPT_PER_FILE_LIMIT, remainingPromptChars);
        prepared.promptText = truncateAttachmentText(prepared.promptText, nextLimit);
        remainingPromptChars -= prepared.promptText.length;
      } else {
        prepared.promptText = '';
      }

      preparedAttachments.push(prepared);
    }

    return {
      attachments: preparedAttachments,
      warnings: warnings
    };
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

    const normalized = trimmed.replace(/<br\s*\/?\s*>/gi, '\n');

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
    const content = sanitizeUserVisibleAnswer(normalizeMathText(String(text || '')));
    const hasGarbledHint = /[?？]{8,}/.test(content) || /�/.test(content);
    if (!hasGarbledHint) return content;

    return [
      '检测到回答可能存在编码异常，建议你重发一次问题，或改用更短的中文句子提问。',
      '',
      '原始返回：',
      content
    ].join('\n');
  }

  function normalizeAnswerHeading(line) {
    return String(line || '')
      .trim()
      .replace(/^[#>*\-\d.)\s]+/, '')
      .trim()
      .split(/[：:]/, 1)[0]
      .trim()
      .replace(/^[:：]+|[:：]+$/g, '')
      .trim()
      .toLowerCase();
  }

  function isPrivateAnswerHeading(line) {
    return PRIVATE_ANSWER_HEADINGS.has(normalizeAnswerHeading(line));
  }

  function isPublicAnswerHeading(line) {
    return PUBLIC_ANSWER_HEADINGS.has(normalizeAnswerHeading(line));
  }

  function shouldHideAnswerLine(line) {
    const text = String(line || '').trim();
    if (!text) return false;
    if (INTERNAL_ANSWER_LINE_RE.test(text)) return true;
    return isPrivateAnswerHeading(text);
  }

  function sanitizeUserVisibleAnswer(text) {
    const normalized = String(text || '')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .replace(/<\/?(analysis|reasoning|thinking|scratchpad)>/gi, '')
      .trim();
    if (!normalized) return '';

    const rawLines = normalized.split('\n');
    const cleanedLines = [];
    let skippingPrivateBlock = false;

    rawLines.forEach(function (rawLine) {
      const line = String(rawLine || '').replace(/\s+$/g, '');
      const stripped = line.trim();

      if (isPrivateAnswerHeading(stripped)) {
        skippingPrivateBlock = true;
        return;
      }

      if (isPublicAnswerHeading(stripped)) {
        skippingPrivateBlock = false;
        cleanedLines.push(line);
        return;
      }

      if (skippingPrivateBlock) {
        return;
      }

      if (shouldHideAnswerLine(stripped)) {
        return;
      }

      cleanedLines.push(line);
    });

    const cleaned = cleanedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    if (cleaned) return cleaned;

    const fallback = rawLines.filter(function (line) {
      return !shouldHideAnswerLine(line);
    }).join('\n').replace(/\n{3,}/g, '\n\n').trim();

    return fallback || normalized;
  }

  function createTypingMessageState() {
    return {
      lastRenderAt: 0,
      timerId: null
    };
  }

  function createStreamingAnswerState() {
    return {
      answerText: '',
      row: null,
      textNode: null
    };
  }

  function ensureTypingMessageState() {
    if (!typingMessageState) {
      typingMessageState = createTypingMessageState();
    }
    return typingMessageState;
  }

  function ensureStreamingAnswerState() {
    if (!streamingAnswerState) {
      streamingAnswerState = createStreamingAnswerState();
    }
    return streamingAnswerState;
  }

  function resetTypingMessageState() {
    if (typingMessageState && typingMessageState.timerId) {
      window.clearInterval(typingMessageState.timerId);
    }
    typingMessageState = null;
  }

  function resetStreamingAnswerState() {
    streamingAnswerState = null;
  }

  function buildTypingMessageMarkup() {
    const state = typingMessageState || {};
    const statusText = String(state.statusText || '').trim();
    return `
      <div class="typing-dots" aria-label="AI 正在生成回答"><span></span><span></span><span></span></div>
      ${statusText ? `<div class="typing-status">${escapeHtml(statusText)}</div>` : ''}
    `;
  }

  function renderTypingMessage(force) {
    const typingRow = document.getElementById('typingRow');
    if (!typingRow) return;
    if (typingRow.classList.contains('streaming-answer-row')) return;

    const bubble = typingRow.querySelector('.message-bubble');
    if (!bubble) return;

    const state = ensureTypingMessageState();
    const now = Date.now();
    if (!force && now - state.lastRenderAt < TYPING_RENDER_THROTTLE_MS) {
      return;
    }

    bubble.innerHTML = buildTypingMessageMarkup();
    state.lastRenderAt = now;

    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  function startTypingMessageTicker() {
    const state = ensureTypingMessageState();
    if (state.timerId) return;

    state.timerId = window.setInterval(function () {
      renderTypingMessage(true);
    }, 1000);
  }

  function noteTypingMessageToken(fragment) {
    const token = String(fragment || '');
    if (!token) return;

    let state = ensureStreamingAnswerState();
    state.answerText += token;

    if (!state.row) {
      resetTypingMessageState();
      const typingRow = document.getElementById('typingRow');
      if (!typingRow) return;

      typingRow.classList.add('streaming-answer-row');
      const bubble = typingRow.querySelector('.message-bubble');
      if (!bubble) return;

      bubble.innerHTML = `
        <div class="message-text streaming-answer"></div>
      `;
      state.row = typingRow;
      state.textNode = bubble.querySelector('.message-text');
    }

    if (state.textNode) {
      state.textNode.textContent = state.answerText;
    }

    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  function finalizeStreamingAnswerMessage(answerText, options) {
    const finalText = normalizeAiAnswerText(String(answerText || ''));
    const row = document.getElementById('typingRow');
    const messageOptions = options || {};

    if (!row || !row.parentNode) {
      resetStreamingAnswerState();
      return addMessage(finalText, 'ai', messageOptions);
    }

    const finalRow = createMessageRow(finalText, 'ai', messageOptions);
    row.parentNode.replaceChild(finalRow, row);
    renderMathInContainer(finalRow);
    appendMessageToSession(finalText, 'ai', messageOptions);
    renderSessionList();
    scrollChatToLatest();
    resetStreamingAnswerState();
    return finalRow;
  }

  function summarizeStreamingToolOutput(output) {
    const text = String(output || '').replace(/\s+/g, ' ').trim();
    if (!text) return '执行完成';
    if (text.length <= 72) return text;
    return `${text.slice(0, 72)}...`;
  }

  async function readStreamEvents(response, onEvent) {
    if (!response.ok) {
      return parseApiResponse(response);
    }

    const contentType = String(response.headers.get('content-type') || '').toLowerCase();
    if (contentType.indexOf('text/event-stream') < 0) {
      return parseApiResponse(response);
    }

    const reader = response.body && response.body.getReader ? response.body.getReader() : null;
    if (!reader) {
      throw new Error('浏览器不支持流式读取，无法启用实时模式');
    }

    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalPayload = null;
    let streamError = null;

    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      events.forEach(function (rawEvent) {
        const lines = String(rawEvent || '').split('\n');
        const dataLines = lines
          .filter(function (line) {
            return line.startsWith('data:');
          })
          .map(function (line) {
            return line.slice(5).trim();
          });

        if (!dataLines.length) return;
        const payloadText = dataLines.join('\n');
        let evt;
        try {
          evt = JSON.parse(payloadText);
        } catch (error) {
          return;
        }

        if (typeof onEvent === 'function') {
          onEvent(evt);
        }

        if (evt && evt.type === 'final' && evt.payload) {
          finalPayload = evt.payload;
        }
        if (evt && evt.type === 'error' && !streamError) {
          streamError = new Error(String(evt.content || 'stream_error'));
        }
      });
    }

    if (streamError) {
      throw streamError;
    }
    if (!finalPayload) {
      throw new Error('流式会话已结束，但未收到最终结果。');
    }
    return finalPayload;
  }

  function createAgentStreamEventHandler(streamEvents, options) {
    const opts = options || {};
    const startText = String(opts.startText || '智能体已启动，正在分析问题...');
    const toolEndText = String(opts.toolEndText || '工具调用完成，正在整理答案...');

    return function (evt) {
      if (!evt || typeof evt !== 'object') return;

      if (evt.type === 'start') {
        setTypingMessageText(startText);
        return;
      }

      if (evt.type === 'tool_start') {
        const toolName = String(evt.tool || '工具');
        streamEvents.push({
          tool_name: toolName,
          status: 'running',
          tool_output_summary: '执行中'
        });
        setTypingMessageText(`正在调用 ${toolName}...`);
        return;
      }

      if (evt.type === 'tool_end') {
        const toolName = String(evt.tool || '工具');
        for (let idx = streamEvents.length - 1; idx >= 0; idx -= 1) {
          const item = streamEvents[idx];
          if (item && item.tool_name === toolName && item.status === 'running') {
            item.status = 'success';
            item.tool_output_summary = summarizeStreamingToolOutput(evt.output);
            break;
          }
        }
        setTypingMessageText(toolEndText);
        return;
      }

      if (evt.type === 'token') {
        noteTypingMessageToken(evt.content);
        return;
      }

      if (evt.type === 'retry') {
        setTypingMessageText(`首轮未命中 ${String(evt.tool || '知识库工具')}，正在强制重试...`);
        return;
      }

      if (evt.type === 'error') {
        setTypingMessageText('智能体运行异常，准备降级提示...');
      }
    };
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

  function renderMessageAttachments(attachments) {
    if (!Array.isArray(attachments) || !attachments.length) return '';

    return `
      <div class="message-attachments">
        ${attachments.map(function (attachment) {
          const kind = escapeHtml(String(attachment.kind || '文件'));
          const name = escapeHtml(String(attachment.name || '未命名文件'));
          const meta = escapeHtml(String(attachment.meta || ''));
          const note = escapeHtml(String(attachment.note || ''));
          return `
            <div class="message-attachment-card">
              <div class="message-attachment-top">
                <div class="message-attachment-name">${name}</div>
                <div class="message-attachment-tag">${kind}</div>
              </div>
              ${meta ? `<div class="message-attachment-meta">${meta}</div>` : ''}
              ${note ? `<div class="message-attachment-note">${note}</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function summarizeWorkflowStep(step, index) {
    if (!step || typeof step !== 'object') {
      return {
        title: `步骤 ${index + 1}`,
        detail: '无可用明细',
        status: 'unknown'
      };
    }

    const toolName = String(step.tool_name || step.tool || `step_${index + 1}`);
    const status = String(step.status || 'success');
    const latency = Number(step.latency_ms || 0);
    const summary = String(step.tool_output_summary || '').trim();
    return {
      title: toolName,
      detail: `${summary || '已执行'}${latency > 0 ? ` · ${latency}ms` : ''}`,
      status: status
    };
  }

  function renderWorkflowTimeline(steps) {
    const list = Array.isArray(steps) ? steps : [];
    if (!list.length) return '';

    return `
      <div class="message-workflow">
        <div class="message-workflow-title">智能体执行时间线</div>
        <div class="message-workflow-list">
          ${list.map(function (item, index) {
            const step = summarizeWorkflowStep(item, index);
            const statusClass = step.status === 'failed' ? 'failed' : (step.status === 'success' ? 'success' : 'unknown');
            return `
              <div class="message-workflow-item ${statusClass}">
                <div class="message-workflow-index">${index + 1}</div>
                <div class="message-workflow-main">
                  <div class="message-workflow-step">${escapeHtml(step.title)}</div>
                  <div class="message-workflow-detail">${escapeHtml(step.detail)}</div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  async function askTutorAgentWithImage(imageFile, question, sessionId) {
    const formData = new FormData();
    formData.append('image', imageFile);
    formData.append('student_id', getUserId());
    formData.append('session_id', sessionId || `session_${Date.now()}`);
    formData.append('question', String(question || '').trim());

    const response = await fetch(`${API_BASE}/api/agent/ocr-tutor`, {
      method: 'POST',
      body: formData
    });
    return parseApiResponse(response);
  }

  async function askTutorAgentWithText(question, sessionId) {
    const response = await fetch(`${API_BASE}/api/agent/ocr-tutor`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: getUserId(),
        session_id: sessionId || `session_${Date.now()}`,
        ocr_text: String(question || '').trim(),
        question: String(question || '').trim()
      })
    });
    return parseApiResponse(response);
  }

  async function askTutorAgentStream(options) {
    const opts = options || {};
    const sessionId = opts.sessionId || `session_${Date.now()}`;
    const question = String(opts.question || '').trim();
    const onEvent = typeof opts.onEvent === 'function' ? opts.onEvent : function () {};
    const imageFile = opts.imageFile || null;

    let response;
    if (imageFile) {
      const formData = new FormData();
      formData.append('image', imageFile);
      formData.append('student_id', getUserId());
      formData.append('session_id', sessionId);
      formData.append('question', question);
      formData.append('ocr_text', question);
      formData.append('stream', 'true');
      response = await fetch(`${API_BASE}/api/agent/ocr-tutor`, {
        method: 'POST',
        body: formData
      });
    } else {
      response = await fetch(`${API_BASE}/api/agent/ocr-tutor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_id: getUserId(),
          session_id: sessionId,
          ocr_text: question,
          question: question,
          stream: true
        })
      });
    }

    return readStreamEvents(response, onEvent);
  }

  async function requestDefaultQaAnswer(question) {
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

    return parseApiResponse(response);
  }

  async function requestDefaultQaAnswerStream(question, options) {
    const opts = options || {};
    const onEvent = typeof opts.onEvent === 'function' ? opts.onEvent : function () {};

    let response = await fetch(`${API_BASE}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        user_id: getUserId(),
        stream: true
      })
    });

    if (response.status === 405) {
      const query = new URLSearchParams({
        question: question,
        user_id: getUserId(),
        stream: 'true'
      });
      response = await fetch(`${API_BASE}/api/ask?${query.toString()}`, {
        method: 'GET'
      });
    }

    return readStreamEvents(response, onEvent);
  }

  async function ingestKnowledgeFromInput() {
    const input = document.getElementById('questionInput');
    const raw = String(input && input.value || '').trim();
    if (!raw) {
      addMessage('请先在输入框写下要入库的知识内容，再点击“存入知识库”。', 'ai', {
        source: 'kb_ingest',
        aiUsed: false,
        error: ''
      });
      return;
    }

    const title = raw.length > 24 ? `${raw.slice(0, 24)}...` : raw;
    const response = await fetch(`${API_BASE}/api/agent/kb/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: getUserId(),
        title: title,
        content: raw,
        source: 'chat_page'
      })
    });
    const data = await parseApiResponse(response);
    const item = data && typeof data.item === 'object' ? data.item : {};
    const graphSync = data.graph_sync || item.graph_sync || null;
    addMessage(generateKbIngestResultHTML(item, graphSync, raw), 'ai', {
      source: 'kb_ingest',
      aiUsed: false,
      renderAsHtml: true,
      error: '',
      graphSync: graphSync,
      evidence: {
        tool_calls: graphSync && graphSync.enabled ? ['kb_ingest', 'sync_kb_note_graph'] : ['kb_ingest'],
        trace_count: 1,
        has_graph: Boolean(graphSync && graphSync.enabled)
      }
    });
    notifyKnowledgeUpdated();
    return data;
  }

  const KB_SEARCH_MODES = {
    HYBRID: 'hybrid',
    DENSE_VECTOR: 'dense_vector',
    LEXICAL: 'lexical'
  };
  let currentKbSearchMode = KB_SEARCH_MODES.HYBRID;

  async function searchKnowledgeFromInput() {
    const input = document.getElementById('questionInput');
    const query = String(input && input.value || '').trim();
    
    if (!query) {
      addMessage('请先输入检索问题，再点击"检索知识库"。', 'ai', {
        source: 'kb_search',
        aiUsed: false,
        error: ''
      });
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/api/agent/kb/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_id: getUserId(),
          query: query,
          top_k: 5,
          search_mode: currentKbSearchMode
        })
      });

      const data = await parseApiResponse(response);
      const hits = Array.isArray(data.hits) ? data.hits : [];
      
      const resultHtml = generateEnhancedSearchResultsHTML(query, hits, data);

      addMessage(resultHtml, 'ai', {
        source: 'kb_search',
        aiUsed: false,
        renderAsHtml: true,
        error: '',
        evidence: {
          tool_calls: ['kb_search'],
          trace_count: hits.length,
          has_graph: Boolean(Array.isArray(data.graph_context) && data.graph_context.length)
        },
        meta: {
          search_mode: currentKbSearchMode,
          response_time_ms: data.query_time_ms || 0,
          results_count: hits.length
        }
      });

      return data;

    } catch (error) {
      addMessage(
        '知识库检索失败: ' + (error && error.message || 'Unknown error'),
        'ai',
        {
          source: 'kb_search',
          aiUsed: false,
          error: error && error.message ? error.message : ''
        }
      );
    }
  }

  function formatKbModeLabel(mode) {
    return mode === 'dense_vector' ? '🔍 向量搜索'
      : mode === 'lexical' ? '📝 词法搜索'
      : '⚡ 混合搜索';
  }

  function formatKbPercent(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return '';
    return `${Math.round(num * 100)}%`;
  }

  function renderKbPills(items, options) {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!list.length) return '';

    const opts = options || {};
    const background = opts.background || '#eef5ff';
    const color = opts.color || '#1146a6';
    return list.map(function (item) {
      return `<span style="display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:999px;background:${background};color:${color};font-size:11px;font-weight:700;">${escapeHtmlForKB(item)}</span>`;
    }).join('');
  }

  function generateKbIngestResultHTML(item, graphSync, rawContent) {
    const record = item && typeof item === 'object' ? item : {};
    const sync = graphSync && typeof graphSync === 'object' ? graphSync : {};
    const title = String(record.title || '知识笔记').trim() || '知识笔记';
    const topics = Array.isArray(record.topics) && record.topics.length
      ? record.topics
      : (Array.isArray(sync.concepts) ? sync.concepts : []);
    const tags = Array.isArray(record.tags) ? record.tags : [];
    const snippetSource = String(record.content || rawContent || '').trim();
    const snippet = snippetSource ? `${snippetSource.slice(0, 180)}${snippetSource.length > 180 ? '...' : ''}` : '';
    const syncEnabled = typeof sync.enabled === 'boolean' ? sync.enabled : false;
    const syncMode = String(sync.mode || (syncEnabled ? 'sync' : 'disabled'));
    const syncStatus = !syncEnabled ? '未启用图谱同步'
      : syncMode === 'async' ? '已提交异步图谱同步'
      : sync.synced ? '图谱同步完成'
      : '图谱同步未确认';
    const syncTone = !syncEnabled ? '#6b7280' : (sync.synced ? '#047857' : '#b45309');
    const mentionsCount = Number(sync.mentions_count || topics.length || 0);

    return `
      <div class="kb-enhanced-result" style="display:flex;flex-direction:column;gap:12px;">
        <div style="padding:14px;border:1px solid #dbe7f5;border-radius:14px;background:linear-gradient(180deg,#f8fbff,#ffffff);">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;">
            <div>
              <div style="font-size:15px;font-weight:800;color:#0f63d8;">知识库已写入</div>
              <div style="margin-top:4px;font-size:13px;color:#334155;">${escapeHtmlForKB(title)}</div>
            </div>
            <div style="padding:6px 10px;border-radius:999px;background:#eef8f3;color:${syncTone};font-size:12px;font-weight:800;">
              ${escapeHtmlForKB(syncStatus)}
            </div>
          </div>
          ${snippet ? `<div style="margin-top:10px;padding:10px 12px;border-radius:12px;background:#f8fafc;color:#475569;font-size:12px;line-height:1.7;">${escapeHtmlForKB(snippet)}</div>` : ''}
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:12px;">
            <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
              <div style="font-size:11px;color:#64748b;">图谱模式</div>
              <div style="margin-top:4px;font-size:14px;font-weight:800;color:#0f172a;">${escapeHtmlForKB(syncMode)}</div>
            </div>
            <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
              <div style="font-size:11px;color:#64748b;">关联概念数</div>
              <div style="margin-top:4px;font-size:14px;font-weight:800;color:#0f172a;">${escapeHtmlForKB(String(mentionsCount))}</div>
            </div>
            <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
              <div style="font-size:11px;color:#64748b;">文档 ID</div>
              <div style="margin-top:4px;font-size:13px;font-weight:700;color:#0f172a;word-break:break-all;">${escapeHtmlForKB(String(sync.document_id || record.id || '--'))}</div>
            </div>
          </div>
          ${topics.length ? `<div style="margin-top:12px;"><div style="font-size:12px;color:#64748b;margin-bottom:8px;">本次提取到的概念</div><div style="display:flex;flex-wrap:wrap;gap:8px;">${renderKbPills(topics, { background: '#e6f4ea', color: '#166534' })}</div></div>` : ''}
          ${tags.length ? `<div style="margin-top:12px;"><div style="font-size:12px;color:#64748b;margin-bottom:8px;">标签</div><div style="display:flex;flex-wrap:wrap;gap:8px;">${renderKbPills(tags, { background: '#eef2ff', color: '#3730a3' })}</div></div>` : ''}
        </div>
      </div>
    `;
  }

  function generateGraphContextPanelHTML(graphContext, compact) {
    const rows = Array.isArray(graphContext) ? graphContext.filter(function (item) {
      return item && typeof item === 'object';
    }) : [];
    if (!rows.length) return '';

    const displayRows = rows.slice(0, compact ? 3 : 5);
    return `
      <div style="margin-top:${compact ? 10 : 14}px;padding:12px;border-radius:14px;border:1px solid #dbe7f5;background:linear-gradient(180deg,#f7fbff,#ffffff);">
        <div style="font-size:13px;font-weight:800;color:#0f63d8;margin-bottom:10px;">图谱增强上下文</div>
        <div style="display:flex;flex-direction:column;gap:10px;">
          ${displayRows.map(function (ctx) {
            const relations = Array.isArray(ctx.relations) ? ctx.relations.slice(0, 4) : [];
            const relationText = relations.length
              ? relations.map(function (rel) {
                  return `${escapeHtmlForKB(String(ctx.concept || '概念'))} -${escapeHtmlForKB(String(rel.relation || '相关'))}-> ${escapeHtmlForKB(String(rel.neighbor || '邻居概念'))}`;
                }).join('<br>')
              : '暂无显式关系';
            const similarity = formatKbPercent(ctx.similarity_to_query);
            return `
              <div style="padding:10px 12px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0;">
                <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;">
                  <div style="font-size:13px;font-weight:700;color:#0f172a;">${escapeHtmlForKB(String(ctx.concept || '图谱概念'))}</div>
                  ${similarity ? `<div style="font-size:11px;color:#0f766e;font-weight:800;">相似度 ${similarity}</div>` : ''}
                </div>
                <div style="margin-top:6px;font-size:12px;color:#475569;">命中文档：${escapeHtmlForKB(String(ctx.doc_title || ctx.doc_id || '未挂接文档'))}</div>
                <div style="margin-top:6px;font-size:12px;line-height:1.7;color:#334155;">${relationText}</div>
              </div>
            `;
          }).join('')}
        </div>
        ${rows.length > displayRows.length ? `<div style="margin-top:10px;font-size:12px;color:#64748b;">其余 ${rows.length - displayRows.length} 条图谱上下文已折叠，可通过更具体的问题缩小范围。</div>` : ''}
      </div>
    `;
  }

  function generateEnhancedSearchResultsHTML(query, hits, metadata) {
    const rows = Array.isArray(hits) ? hits : [];
    const graphContext = Array.isArray(metadata && metadata.graph_context) ? metadata.graph_context : [];
    const queryConcepts = Array.isArray(metadata && metadata.graph_query_concepts) ? metadata.graph_query_concepts : [];
    const graphContributionRate = Number(metadata && metadata.graph_contribution_rate || 0);
    const responseTime = metadata && metadata.query_time_ms ? `${metadata.query_time_ms}ms` : '计算中...';
    const modeLabel = formatKbModeLabel((metadata && metadata.search_mode) || currentKbSearchMode);
    const graphContributionLabel = graphContributionRate > 0 ? `${Math.round(graphContributionRate * 100)}%` : '0%';

    if (!rows.length) {
      return `<div class="kb-enhanced-result" style="padding: 12px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
        <div style="color: #856404;">未找到与 "<strong>${escapeHtmlForKB(query)}</strong>" 相关的知识</div>
        <div style="color: #856404; font-size: 12px; margin-top: 6px;">建议：尝试换个关键词或更长的表述</div>
        ${generateGraphContextPanelHTML(graphContext, true)}
      </div>`;
    }

    let resultHtml = `
      <div class="kb-enhanced-result">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #e0e0e0;">
          <div style="font-weight: bold; color: #1976D2; font-size: 14px;">
            ${modeLabel}
          </div>
          <div style="display: flex; gap: 16px; align-items: center;">
            <span style="color: #666; font-size: 12px;">找到 ${rows.length} 个结果</span>
            <span style="color: #2E7D32; font-size: 12px; font-weight: bold;">响应: ${responseTime}</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px;">
          <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
            <div style="font-size:11px;color:#64748b;">图谱贡献率</div>
            <div style="margin-top:4px;font-size:16px;font-weight:800;color:#0f172a;">${escapeHtmlForKB(graphContributionLabel)}</div>
          </div>
          <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
            <div style="font-size:11px;color:#64748b;">命中概念种子</div>
            <div style="margin-top:4px;font-size:16px;font-weight:800;color:#0f172a;">${escapeHtmlForKB(String(queryConcepts.length))}</div>
          </div>
          <div style="padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dce9f8;">
            <div style="font-size:11px;color:#64748b;">图谱上下文条数</div>
            <div style="margin-top:4px;font-size:16px;font-weight:800;color:#0f172a;">${escapeHtmlForKB(String(graphContext.length))}</div>
          </div>
        </div>
        ${queryConcepts.length ? `<div style="margin-bottom:12px;"><div style="font-size:12px;color:#64748b;margin-bottom:8px;">本次检索在图谱中优先展开的概念</div><div style="display:flex;flex-wrap:wrap;gap:8px;">${renderKbPills(queryConcepts, { background: '#e0f2fe', color: '#075985' })}</div></div>` : ''}
        <div style="display: flex; flex-direction: column; gap: 12px;">
    `;

    rows.forEach((hit, index) => {
      resultHtml += generateSearchResultItemHTML(hit, index + 1);
    });

    resultHtml += `
        </div>
        ${generateGraphContextPanelHTML(graphContext, false)}
        <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #e0e0e0; text-align: center; color: #999; font-size: 12px;">
          本次结果已经把文本检索与图谱证据合并展示，能更直观看到“命中了什么内容”和“为什么命中”。
        </div>
      </div>
    `;

    return resultHtml;
  }

  function generateSearchResultItemHTML(hit, index) {
    const sourceType = String(hit.source_type || hit.channel || hit.source || '').toLowerCase();
    const sourceLabel = sourceType.indexOf('vector') >= 0 ? '向量'
      : sourceType.indexOf('graph') >= 0 ? '图谱'
      : sourceType.indexOf('private') >= 0 ? '私有'
      : sourceType.indexOf('lexical') >= 0 ? '词法'
      : '混合';

    const vectorPercent = formatKbPercent(hit.vector_score);
    const lexicalPercent = formatKbPercent(hit.lexical_score || hit.text_score);
    const graphPercent = formatKbPercent(hit.graph_score);
    const hybridPercent = formatKbPercent(hit.hybrid_score != null ? hit.hybrid_score : hit.score);
    const matchedConcepts = Array.isArray(hit.matched_concepts) ? hit.matched_concepts.filter(Boolean) : [];
    const graphRelations = Array.isArray(hit.graph_relations) ? hit.graph_relations.filter(function (item) {
      return item && item.neighbor;
    }) : [];
    const tags = Array.isArray(hit.tags) ? hit.tags.filter(Boolean) : [];

    let scoreHtml = '';
    if (vectorPercent) {
      scoreHtml += `<span style="background: #E3F2FD; color: #1976D2; padding: 2px 6px; border-radius: 3px; font-size: 11px;">向量: ${vectorPercent}</span>`;
    }
    if (lexicalPercent) {
      scoreHtml += `<span style="background: #FFF3E0; color: #F57C00; padding: 2px 6px; border-radius: 3px; font-size: 11px;">词法: ${lexicalPercent}</span>`;
    }
    if (graphPercent) {
      scoreHtml += `<span style="background: #ECFDF5; color: #047857; padding: 2px 6px; border-radius: 3px; font-size: 11px;">图谱: ${graphPercent}</span>`;
    }
    scoreHtml += `<span style="background: #E8F5E9; color: #2E7D32; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: bold;">综合: ${hybridPercent || '0%'}</span>`;

    let metadataHtml = `<span style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #999;">源: ${sourceLabel}</span>`;

    if (hit.discipline) {
      metadataHtml += `<span style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #999;">${hit.discipline}</span>`;
    }

    if (hit.chapter) {
      metadataHtml += `<span style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #999;">${hit.chapter}</span>`;
    }

    if (hit.subject_route) {
      metadataHtml += `<span style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #999;">${hit.subject_route}</span>`;
    }

    const snippetRaw = hit.snippet || hit.content || '（无内容预览）';
    const snippet = String(snippetRaw || '').slice(0, 420);
    const title = hit.title || '知识片段';
    const graphRelationHtml = graphRelations.length
      ? graphRelations.slice(0, 4).map(function (relation) {
          return `<div style="font-size:12px;line-height:1.6;color:#334155;">${escapeHtmlForKB(title)} -${escapeHtmlForKB(String(relation.relation || '相关'))}-> ${escapeHtmlForKB(String(relation.neighbor || '邻居概念'))}</div>`;
        }).join('')
      : '';

    return `
      <div style="padding: 12px; background: white; border: 1px solid #e0e0e0; border-radius: 4px; transition: all 0.2s;">
        <div style="display: flex; gap: 10px; align-items: flex-start;">
          <div style="min-width: 30px; height: 30px; background: #4CAF50; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; flex-shrink: 0;">
            ${index}
          </div>
          <div style="flex: 1;">
            <div style="font-weight: bold; color: #1976D2; margin-bottom: 6px;">
              ${escapeHtmlForKB(title)}
            </div>
            <div style="display: flex; gap: 8px; margin: 6px 0; flex-wrap: wrap;">
              ${scoreHtml}
            </div>
            <div style="display: flex; gap: 6px; margin: 6px 0; flex-wrap: wrap; font-size: 11px;">
              ${metadataHtml}
            </div>
            ${(hit.chapter || hit.discipline) ? `<div style="color:#5f738c;font-size:11px;margin:2px 0 6px;">定位：${escapeHtmlForKB(hit.discipline || '未标注')} / ${escapeHtmlForKB(hit.chapter || '未标注')}</div>` : ''}
            <div style="color: #666; font-size: 12px; line-height: 1.45; margin: 8px 0; padding: 6px; background: #fafafa; border-radius: 3px; max-height: 110px; overflow: hidden;">
              ${escapeHtmlForKB(snippet)}
            </div>
            ${matchedConcepts.length ? `<div style="margin:8px 0 0;"><div style="font-size:12px;color:#64748b;margin-bottom:6px;">命中的图谱概念</div><div style="display:flex;flex-wrap:wrap;gap:8px;">${renderKbPills(matchedConcepts, { background: '#e6f4ea', color: '#166534' })}</div></div>` : ''}
            ${graphRelationHtml ? `<div style="margin-top:10px;padding:10px 12px;border-radius:12px;background:#f8fbff;border:1px solid #dbe7f5;"><div style="font-size:12px;color:#64748b;margin-bottom:6px;">关联关系</div>${graphRelationHtml}</div>` : ''}
            ${tags.length ? `<div style="margin-top:10px;"><div style="display:flex;flex-wrap:wrap;gap:8px;">${renderKbPills(tags.slice(0, 6), { background: '#fef3c7', color: '#92400e' })}</div></div>` : ''}
            <button onclick="insertKBResultToInput('${escapeJsString(title)}')" 
                    style="background: #4CAF50; color: white; border: none; padding: 6px 12px; border-radius: 3px; cursor: pointer; font-size: 12px; transition: background 0.2s; margin-top: 8px;">
              引用这个答案
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function escapeHtmlForKB(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return String(text || '').replace(/[&<>"']/g, m => map[m]);
  }

  function escapeJsString(str) {
    return String(str || '')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '\\"')
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r');
  }

  function insertKBResultToInput(title) {
    const input = document.getElementById('questionInput');
    if (input) {
      const currentValue = input.value.trim();
      const newValue = currentValue + (currentValue ? '\n\n' : '') + '📚 来自知识库: ' + title;
      input.value = newValue;
      input.focus();
    }
  }
  window.insertKBResultToInput = insertKBResultToInput;

  function switchKBSearchMode(mode) {
    if (KB_SEARCH_MODES[mode] || Object.values(KB_SEARCH_MODES).includes(mode)) {
      currentKbSearchMode = mode;
    }
  }
  window.switchKBSearchMode = switchKBSearchMode;

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
    } else if (opts.renderAsHtml) {
      textDiv.innerHTML = String(text || '');
    } else {
      textDiv.innerHTML = renderRichText(text);
    }
    bubble.appendChild(textDiv);

    if (Array.isArray(opts.attachments) && opts.attachments.length) {
      const attachmentWrap = document.createElement('div');
      attachmentWrap.innerHTML = renderMessageAttachments(opts.attachments);
      if (attachmentWrap.firstElementChild) {
        bubble.appendChild(attachmentWrap.firstElementChild);
      }
    }

    if (sender === 'ai' && Array.isArray(opts.workflowSteps) && opts.workflowSteps.length) {
      const workflowWrap = document.createElement('div');
      workflowWrap.innerHTML = renderWorkflowTimeline(opts.workflowSteps);
      if (workflowWrap.firstElementChild) {
        bubble.appendChild(workflowWrap.firstElementChild);
      }
    }

    const metaItems = [];
    const showMeta = sender === 'ai' && opts.showMeta === true;
    if (showMeta && opts.source) {
      metaItems.push(`<span class="meta-chip">来源：${escapeHtml(opts.source)}</span>`);
    }
    if (showMeta && typeof opts.aiUsed === 'boolean') {
      metaItems.push(`<span class="meta-chip">${opts.aiUsed ? '真实AI回答' : '回退回答'}</span>`);
    }
    if (showMeta && opts.error) {
      metaItems.push(`<span class="meta-chip error">${escapeHtml(opts.error)}</span>`);
    }
    if (showMeta && opts.evidence && typeof opts.evidence === 'object') {
      if (Array.isArray(opts.evidence.tool_calls) && opts.evidence.tool_calls.length) {
        metaItems.push(`<span class="meta-chip">工具链：${escapeHtml(opts.evidence.tool_calls.join(' -> '))}</span>`);
      }
      if (typeof opts.evidence.trace_count === 'number') {
        metaItems.push(`<span class="meta-chip">轨迹步数：${escapeHtml(String(opts.evidence.trace_count))}</span>`);
      }
      if (typeof opts.evidence.has_kb === 'boolean') {
        metaItems.push(`<span class="meta-chip">知识库：${opts.evidence.has_kb ? '已命中' : '未命中'}</span>`);
      }
    }
    if (showMeta && opts.meta && typeof opts.meta === 'object') {
      if (opts.meta.kb_routing_required) {
        metaItems.push('<span class="meta-chip">路由：要求知识库</span>');
      }
      if (opts.meta.kb_retry_triggered) {
        metaItems.push('<span class="meta-chip">补偿：已触发重试</span>');
      }
    }
    if (showMeta && opts.graphSync && typeof opts.graphSync === 'object') {
      const mode = opts.graphSync.mode || 'unknown';
      const status = opts.graphSync.enabled === false
        ? '未启用'
        : (opts.graphSync.synced ? '已同步' : (opts.graphSync.mode === 'async' ? '排队中' : '待同步'));
      const taskType = opts.graphSync.task_type ? ` / ${opts.graphSync.task_type}` : '';
      metaItems.push(`<span class="meta-chip">图谱同步：${escapeHtml(mode)} / ${escapeHtml(status)}${escapeHtml(taskType)}</span>`);
      if (typeof opts.graphSync.mentions_count === 'number') {
        metaItems.push(`<span class="meta-chip">关联概念：${escapeHtml(String(opts.graphSync.mentions_count))}</span>`);
      }
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

  function shouldHideTechnicalMessage(sender, options) {
    const opts = options || {};
    if (sender !== 'ai') return false;
    if (opts.source === 'agent_workflow') return true;
    return Array.isArray(opts.workflowSteps) && opts.workflowSteps.length > 0;
  }

  function addMessage(text, sender, options, persist) {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return null;
    if (shouldHideTechnicalMessage(sender, options)) return null;

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
    session.updatedAt = Date.now();
    activeSessionId = session.id;
    saveSessionsToLocal();
    addMessage(WELCOME_MESSAGE, 'ai', { source: 'system', aiUsed: true, error: '' });
    scrollChatToLatest();
  }

  function renderActiveSessionMessages() {
    const session = ensureActiveSession();
    clearChatDom();
    (session.messages || []).forEach(function (message) {
      addMessage(message.text, message.sender, message.options || {}, false);
    });
    renderSessionList();
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
    clearPendingAttachments();
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
      clearPendingAttachments();
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
    clearPendingAttachments();
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
    clearPendingAttachments();
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

    removeTypingMessage();
    typingMessageState = createTypingMessageState();

    const row = document.createElement('div');
    row.className = 'message-row assistant';
    row.id = 'typingRow';
    row.innerHTML = `
      <div class="avatar">AI</div>
      <div class="message-bubble"></div>
    `;
    chatMessages.appendChild(row);
    startTypingMessageTicker();
    renderTypingMessage(true);
  }

  function setTypingMessageText(text) {
    const typingRow = document.getElementById('typingRow');
    if (typingRow && typingRow.classList.contains('streaming-answer-row')) {
      return;
    }

    const state = ensureTypingMessageState();
    state.statusText = String(text || '正在分析中...');
    renderTypingMessage(true);
  }

  function removeTypingMessage() {
    resetTypingMessageState();
    resetStreamingAnswerState();
    const typingRow = document.getElementById('typingRow');
    if (typingRow && typingRow.parentNode) {
      typingRow.parentNode.removeChild(typingRow);
    }
  }

  function setComposerBusy(busy) {
    const button = document.getElementById('askQuestionBtn');
    if (button) {
      button.disabled = !!busy;
      button.textContent = busy ? '...' : '↑';
    }

    const newChatButton = document.getElementById('newChatBtn');
    if (newChatButton) {
      newChatButton.disabled = !!busy;
    }

    const attachButton = document.getElementById('composerAttachBtn');
    if (attachButton) {
      attachButton.disabled = !!busy;
    }

    const fileInput = document.getElementById('composerFileInput');
    if (fileInput) {
      fileInput.disabled = !!busy;
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

  function renderAdviceHint(data, sourceTag) {
    const diagnosis = data && typeof data.diagnosis === 'object' ? data.diagnosis : {};
    const advice = data && typeof data.learning_advice === 'object' ? data.learning_advice : {};
    const lines = [];

    if (diagnosis && diagnosis.error_type) {
      lines.push(`诊断结论：${diagnosis.error_type}`);
    }
    if (advice && advice.建议) {
      lines.push(`学习建议：${advice.建议}`);
    } else if (diagnosis && diagnosis.recommendation) {
      lines.push(`学习建议：${diagnosis.recommendation}`);
    }

    if (!lines.length) return;
    addMessage(lines.join('\n'), 'ai', {
      source: sourceTag || 'diagnosis_hint',
      aiUsed: true,
      error: ''
    });
  }

  async function askQuestion(prefilledQuestion) {
    if (isAskingQuestion) return;

    const input = document.getElementById('questionInput');
    if (!input) return;

    const question = String(prefilledQuestion || input.value || '').trim();
    const attachmentsToSend = pendingAttachments.slice();
    if (!question && !attachmentsToSend.length) return;

    isAskingQuestion = true;
    setComposerBusy(true);

    const displayQuestion = buildDisplayQuestion(question, attachmentsToSend);
    const messageOptions = attachmentsToSend.length
      ? { attachments: attachmentsToSend.map(summarizePendingAttachmentForMessage) }
      : {};

    addMessage(displayQuestion, 'user', messageOptions);
    input.value = '';
    clearPendingAttachments();
    addTypingMessage();

    try {
      const imageAttachment = attachmentsToSend.find(function (item) {
        return item && item.kind === 'image';
      });

      if (imageAttachment) {
        const session = ensureActiveSession();
        const streamEvents = [];
        const agentData = await askTutorAgentStream({
          imageFile: imageAttachment.file,
          question: question || DEFAULT_ATTACHMENT_QUESTION,
          sessionId: session ? session.id : '',
          onEvent: createAgentStreamEventHandler(streamEvents, {
            startText: '智能体已启动，正在读取题目...',
            toolEndText: '工具调用完成，正在整理答案...'
          })
        });

        finalizeStreamingAnswerMessage(agentData.answer || '', {
          source: 'agent_ocr_tutor',
          aiUsed: true,
          error: '',
          evidence: agentData.evidence || null,
          meta: agentData.meta || null
        });

        const ignoredCount = attachmentsToSend.filter(function (item) {
          return item && item.kind !== 'image';
        }).length;
        if (ignoredCount > 0) {
          addMessage(`本次智能体通道优先处理了图片题目，另有 ${ignoredCount} 个非图片附件未参与 OCR。`, 'ai', {
            source: 'agent_notice',
            aiUsed: false,
            error: ''
          });
        }
        return;
      }

      const attachmentResult = attachmentsToSend.length
        ? await prepareAttachmentsForQuestion(attachmentsToSend)
        : { attachments: [], warnings: [] };
      const questionForApi = buildPromptTextFromPreparedAttachments(question, attachmentResult.attachments);

      if (agentModeEnabled) {
        const session = ensureActiveSession();
        const streamEvents = [];
        try {
          const agentData = await askTutorAgentStream({
            question: questionForApi,
            sessionId: session ? session.id : '',
            onEvent: createAgentStreamEventHandler(streamEvents, {
              startText: '正在自动分析问题，并判断是否需要检索知识库...',
              toolEndText: '工具调用完成，正在整合证据...'
            })
          });

          finalizeStreamingAnswerMessage(agentData.answer || '', {
            source: 'agent_text_tutor',
            aiUsed: true,
            error: '',
            graphSync: (agentData.knowledge_extract && agentData.knowledge_extract.graph_sync) || null,
            evidence: agentData.evidence || null,
            meta: agentData.meta || null
          });
          renderAdviceHint(agentData, 'agent_diagnosis_hint');

          if (attachmentResult.warnings.length) {
            addMessage(`附件处理提醒：\n${attachmentResult.warnings.map(function (item, index) {
              return `${index + 1}. ${item}`;
            }).join('\n')}`, 'ai', {
              source: 'attachment',
              aiUsed: false,
              error: ''
            });
          }
          return;
        } catch (agentError) {
          console.warn('智能体自动路由失败，准备回退普通问答:', agentError);
          removeTypingMessage();
          addTypingMessage();
          setTypingMessageText('智能体通道暂不可用，正在自动切换普通问答...');
        }
      }

      const data = await requestDefaultQaAnswerStream(questionForApi, {
        onEvent: createAgentStreamEventHandler([], {
          startText: '正在生成回答...',
          toolEndText: '正在整理答案...'
        })
      });
      const knowledgeSeed = buildKnowledgeSeedText(question, attachmentResult.attachments);
      let extractData = data.knowledge_extract || {};
      if (!extractData || typeof extractData !== 'object' || !Object.keys(extractData).length) {
        extractData = knowledgeSeed
          ? await autoExtractKnowledge(knowledgeSeed, attachmentsToSend.length ? 'chat_attachment' : 'qa')
          : {};
      }
      const attachmentGraphSync = attachmentResult.attachments.find(function (attachment) {
        return attachment.graphSync;
      });

      finalizeStreamingAnswerMessage(data.answer, {
        source: data.source,
        aiUsed: data.ai_used,
        error: data.error,
        graphSync: extractData.graph_sync || (attachmentGraphSync ? attachmentGraphSync.graphSync : null),
        evidence: data.evidence || null
      });
      renderAdviceHint(data, 'qa_diagnosis_hint');

      if (attachmentResult.warnings.length) {
        addMessage(`附件处理提醒：\n${attachmentResult.warnings.map(function (item, index) {
          return `${index + 1}. ${item}`;
        }).join('\n')}`, 'ai', {
          source: 'attachment',
          aiUsed: false,
          error: ''
        });
      }
    } catch (error) {
      removeTypingMessage();
      if (attachmentsToSend.length && !pendingAttachments.length) {
        pendingAttachments = attachmentsToSend;
        renderPendingAttachments();
      }
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

  function initAttachmentComposer() {
    const attachButton = document.getElementById('composerAttachBtn');
    const fileInput = document.getElementById('composerFileInput');
    if (!attachButton || !fileInput) return;

    if (!attachButton.dataset.bound) {
      attachButton.addEventListener('click', function () {
        fileInput.click();
      });
      attachButton.dataset.bound = '1';
    }

    if (!fileInput.dataset.bound) {
      fileInput.addEventListener('change', function () {
        addPendingAttachments(this.files);
        this.value = '';
      });
      fileInput.dataset.bound = '1';
    }

    renderPendingAttachments();
  }

  function initAgentExperienceControls() {
    loadAgentModeState();
    const kbSaveBtn = document.getElementById('kbSaveBtn');
    const kbSearchBtn = document.getElementById('kbSearchBtn');

    if (kbSaveBtn && !kbSaveBtn.dataset.bound) {
      kbSaveBtn.addEventListener('click', async function () {
        if (isAskingQuestion) return;
        try {
          await ingestKnowledgeFromInput();
        } catch (error) {
          addMessage(withSuggestion('知识库写入失败', error, '确认后端可用并重试'), 'ai', {
            source: 'kb_ingest',
            aiUsed: false,
            error: error && error.message ? error.message : 'kb_ingest_error'
          });
        }
      });
      kbSaveBtn.dataset.bound = '1';
    }

    if (kbSearchBtn && !kbSearchBtn.dataset.bound) {
      kbSearchBtn.addEventListener('click', async function () {
        if (isAskingQuestion) return;
        try {
          await searchKnowledgeFromInput();
        } catch (error) {
          addMessage(withSuggestion('知识库检索失败', error, '确认后端可用并重试'), 'ai', {
            source: 'kb_search',
            aiUsed: false,
            error: error && error.message ? error.message : 'kb_search_error'
          });
        }
      });
      kbSearchBtn.dataset.bound = '1';
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
        clearPendingAttachments();
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
    initAttachmentComposer();
    initAgentExperienceControls();
    initTaskModal();
    initGlobalSidebar();
    initReactiveBindings();
    refreshAiStatus();
    applyStartupQuestion();
    focusComposer();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
