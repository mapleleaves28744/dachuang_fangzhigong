/**
 * 增强的知识库搜索结果显示组件
 * 用途: 让前端能够充分展示 FAISS Dense Vector 改造的效果
 * 
 * 需要在 chat-page.js 中集成
 */

// ============================================================
// 1. 搜索模式定义
// ============================================================
const SEARCH_MODES = {
  DENSE_VECTOR: 'dense_vector',      // 仅向量 (FAISS)
  HYBRID: 'hybrid',                   // 混合 (向量+词法+图) 
  LEXICAL: 'lexical',                 // 仅词法 (TF-IDF)
};

let currentSearchMode = SEARCH_MODES.HYBRID;  // 默认混合模式


// ============================================================
// 2. 增强的知识库搜索函数
// ============================================================

async function searchKnowledgeEnhanced() {
  const input = document.getElementById('questionInput');
  const query = String(input && input.value || '').trim();
  
  if (!query) {
    addMessage('请先输入检索问题，再点击"检索知识库"。', 'ai', {
      source: 'kb_search',
      aiUsed: false
    });
    return;
  }

  try {
    // 调用后端搜索
    const response = await fetch(`${API_BASE}/api/agent/kb/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: getUserId(),
        query: query,
        top_k: 5,
        search_mode: currentSearchMode,  // 传递搜索模式
      })
    });

    const data = await parseApiResponse(response);
    const hits = Array.isArray(data.hits) ? data.hits : [];

    // 渲染增强版结果
    const displayHtml = renderEnhancedSearchResults(query, hits, data);
    
    addMessage(displayHtml, 'ai', {
      source: 'kb_search_enhanced',
      aiUsed: false,
      error: '',
      metadata: {
        search_mode: currentSearchMode,
        results_count: hits.length,
        query_time_ms: data.query_time_ms || 0,
        hits: hits
      }
    });

  } catch (error) {
    addMessage(`知识库搜索失败: ${error.message}`, 'ai', {
      source: 'kb_search',
      aiUsed: false,
      error: error.message
    });
  }
}


// ============================================================
// 3. 渲染增强版搜索结果
// ============================================================

function renderEnhancedSearchResults(query, hits, metadata) {
  if (!hits || hits.length === 0) {
    return `<div class="kb-search-empty">
             <p>未找到与"${escapeHtml(query)}"相关的知识</p>
             <p style="font-size: 12px; color: #999;">建议: 尝试换个关键词重新搜索</p>
           </div>`;
  }

  const modeLabel = {
    dense_vector: '🔍 向量搜索',
    hybrid: '⚡ 混合搜索',
    lexical: '📝 词法搜索'
  }[currentSearchMode] || '搜索';

  const perfInfo = metadata.query_time_ms ? 
    `<span style="color: #666; font-size: 12px;">响应: ${metadata.query_time_ms}ms</span>` : '';

  let html = `
    <div class="kb-search-results">
      <div class="kb-search-header">
        <span class="kb-search-mode">${modeLabel}</span>
        <span class="kb-search-count">找到 ${hits.length} 个结果</span>
        ${perfInfo}
      </div>
      <div class="kb-search-items">
  `;

  hits.forEach((hit, index) => {
    html += renderEnhancedSearchItem(hit, index + 1);
  });

  html += `
      </div>
      <div class="kb-search-footer">
        <p style="font-size: 12px; color: #999;">
          💡 这是使用高效的向量检索技术获取的结果，能够理解语义相似性。
        </p>
      </div>
    </div>
  `;

  return html;
}


// ============================================================
// 4. 渲染单个搜索结果项
// ============================================================

function renderEnhancedSearchItem(hit, index) {
  const sourceLabel = hit.source_type === 'vector' ? '向量' :
                      hit.source_type === 'graph' ? '图谱' :
                      hit.source_type === 'private' ? '私有' : '混合';

  const scoreInfo = `
    <div class="kb-item-scores">
      ${hit.vector_score ? `<span class="score-vector">向量: ${(hit.vector_score * 100).toFixed(0)}%</span>` : ''}
      ${hit.lexical_score ? `<span class="score-lexical">词法: ${(hit.lexical_score * 100).toFixed(0)}%</span>` : ''}
      <span class="score-hybrid">综合: ${(hit.score * 100).toFixed(0)}%</span>
    </div>
  `;

  const metadata = `
    <div class="kb-item-metadata">
      <span class="meta-source">${sourceLabel}</span>
      ${hit.discipline ? `<span class="meta-discipline">${hit.discipline}</span>` : ''}
      ${hit.chapter ? `<span class="meta-chapter">${hit.chapter}</span>` : ''}
    </div>
  `;

  return `
    <div class="kb-search-item" data-index="${index}">
      <div class="kb-item-index">${index}</div>
      <div class="kb-item-content">
        <div class="kb-item-title">${escapeHtml(hit.title || '知识片段')}</div>
        ${scoreInfo}
        ${metadata}
        <div class="kb-item-snippet">${escapeHtml(hit.snippet || hit.content || '')}</div>
        <button class="kb-item-action" onclick="insertSearchResultToInput('${escapeHtml(hit.title)}')">
          引用这个答案
        </button>
      </div>
    </div>
  `;
}


// ============================================================
// 5. 搜索模式切换UI
// ============================================================

function createSearchModeSelector() {
  const html = `
    <div class="kb-search-mode-selector">
      <label>
        <input type="radio" name="search_mode" value="dense_vector" 
               ${currentSearchMode === SEARCH_MODES.DENSE_VECTOR ? 'checked' : ''}>
        <span>🔍 向量搜索 - 语义理解</span>
      </label>
      <label>
        <input type="radio" name="search_mode" value="hybrid" 
               ${currentSearchMode === SEARCH_MODES.HYBRID ? 'checked' : ''}>
        <span>⚡ 混合搜索 - 最佳平衡 (推荐)</span>
      </label>
      <label>
        <input type="radio" name="search_mode" value="lexical" 
               ${currentSearchMode === SEARCH_MODES.LEXICAL ? 'checked' : ''}>
        <span>📝 词法搜索 - 精确匹配</span>
      </label>
    </div>
  `;
  
  return html;
}


// ============================================================
// 6. 集成到前端的样式
// ============================================================

const SEARCH_STYLES = `
<style>
  /* 知识库搜索结果容器 */
  .kb-search-results {
    background: #f9f9f9;
    border-left: 4px solid #4CAF50;
    padding: 12px;
    border-radius: 4px;
    margin: 8px 0;
  }

  /* 搜索头部 */
  .kb-search-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e0e0e0;
  }

  .kb-search-mode {
    font-weight: bold;
    color: #1976D2;
    font-size: 14px;
  }

  .kb-search-count {
    color: #666;
    font-size: 12px;
  }

  /* 搜索项 */
  .kb-search-item {
    display: flex;
    gap: 10px;
    padding: 12px;
    margin: 8px 0;
    background: white;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    transition: all 0.2s;
  }

  .kb-search-item:hover {
    border-color: #4CAF50;
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.1);
  }

  .kb-item-index {
    min-width: 30px;
    height: 30px;
    background: #4CAF50;
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    font-size: 14px;
  }

  .kb-item-content {
    flex: 1;
  }

  .kb-item-title {
    font-weight: bold;
    color: #1976D2;
    margin-bottom: 6px;
  }

  /* 分数显示 */
  .kb-item-scores {
    display: flex;
    gap: 8px;
    margin: 6px 0;
    font-size: 12px;
  }

  .score-vector {
    background: #E3F2FD;
    color: #1976D2;
    padding: 2px 6px;
    border-radius: 3px;
  }

  .score-lexical {
    background: #FFF3E0;
    color: #F57C00;
    padding: 2px 6px;
    border-radius: 3px;
  }

  .score-hybrid {
    background: #E8F5E9;
    color: #2E7D32;
    padding: 2px 6px;
    border-radius: 3px;
    font-weight: bold;
  }

  /* 元数据 */
  .kb-item-metadata {
    display: flex;
    gap: 6px;
    font-size: 11px;
    color: #999;
    margin: 6px 0;
  }

  .meta-source,
  .meta-discipline,
  .meta-chapter {
    background: #f5f5f5;
    padding: 2px 6px;
    border-radius: 3px;
  }

  /* 摘要 */
  .kb-item-snippet {
    color: #666;
    font-size: 13px;
    line-height: 1.4;
    margin: 8px 0;
    padding: 6px;
    background: #fafafa;
    border-radius: 3px;
    max-height: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* 操作按钮 */
  .kb-item-action {
    background: #4CAF50;
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 3px;
    cursor: pointer;
    font-size: 12px;
    transition: background 0.2s;
  }

  .kb-item-action:hover {
    background: #45a049;
  }

  /* 空状态 */
  .kb-search-empty {
    text-align: center;
    padding: 20px;
    color: #999;
  }

  /* 底部信息 */
  .kb-search-footer {
    margin-top: 12px;
    padding-top: 8px;
    border-top: 1px solid #e0e0e0;
    text-align: center;
  }

  /* 搜索模式选择器 */
  .kb-search-mode-selector {
    display: flex;
    gap: 16px;
    padding: 12px;
    background: #f5f5f5;
    border-radius: 4px;
    margin: 8px 0;
  }

  .kb-search-mode-selector label {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    font-size: 13px;
  }

  .kb-search-mode-selector input[type="radio"] {
    cursor: pointer;
  }
</style>
`;


// ============================================================
// 7. 集成到现有代码
// ============================================================

/*
在 chat-page.js 中找到这一行:
  kbSearchBtn.addEventListener('click', async function () {
    if (isAskingQuestion) return;
    try {
      await searchKnowledgeFromInput();

修改为:
  kbSearchBtn.addEventListener('click', async function () {
    if (isAskingQuestion) return;
    try {
      await searchKnowledgeEnhanced();  // ← 改为调用新函数
*/


// ============================================================
// 8. 辅助函数
// ============================================================

function insertSearchResultToInput(title) {
  const input = document.getElementById('questionInput');
  if (input) {
    input.value = (input.value + '\n\n来自知识库: ' + title).trim();
    input.focus();
  }
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return String(text || '').replace(/[&<>"']/g, m => map[m]);
}
