/**
 * 🔧 前端改造代码片段
 * 
 * 这个文件包含了从旧前端改进到新前端的所有代码改动
 * 你可以复制这些代码片段直接应用到你的项目中
 */


// ============================================================
// 改动 1：在 chat-page.js 最开始添加（与其他全局变量一起）
// ============================================================

// 搜索模式（添加到其他全局变量之后）
const KB_SEARCH_MODES = {
  HYBRID: 'hybrid',
  DENSE_VECTOR: 'dense_vector',
  LEXICAL: 'lexical'
};

let currentKbSearchMode = KB_SEARCH_MODES.HYBRID;  // 默认混合模式


// ============================================================
// 改动 2：添加新的搜索函数（替换或覆盖旧的 searchKnowledgeFromInput）
// ============================================================

/**
 * 改进的知识库搜索函数
 * 特点：
 * - 显示向量、词法、综合分数
 * - 显示来源和分类信息
 * - 显示响应时间
 * - 支持搜索模式选择
 */
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
    // 调用后端 API
    const response = await fetch(`${API_BASE}/api/agent/kb/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_id: getUserId(),
        query: query,
        top_k: 5,  // 从 3 改为 5，充分展示向量搜索的优势
        search_mode: currentKbSearchMode
      })
    });

    const data = await parseApiResponse(response);
    const hits = Array.isArray(data.hits) ? data.hits : [];
    
    // 生成改进的结果显示 HTML
    const resultHtml = generateEnhancedSearchResultsHTML(query, hits, data);

    addMessage(resultHtml, 'ai', {
      source: 'kb_search',
      aiUsed: false,
      error: '',
      evidence: {
        tool_calls: ['kb_search'],
        trace_count: hits.length
      },
      metadata: {
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


// ============================================================
// 改动 3：生成改进版搜索结果 HTML 的函数
// ============================================================

/**
 * 生成带有向量分数、分类等信息的搜索结果 HTML
 */
function generateEnhancedSearchResultsHTML(query, hits, metadata) {
  if (!hits || hits.length === 0) {
    return `<div class="kb-enhanced-result" style="padding: 12px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
      <div style="color: #856404;">未找到与 "<strong>${escapeHtmlForKB(query)}</strong>" 相关的知识</div>
      <div style="color: #856404; font-size: 12px; margin-top: 6px;">建议：尝试换个关键词或更长的表述</div>
    </div>`;
  }

  const modeLabel = currentKbSearchMode === 'dense_vector' ? '🔍 向量搜索' :
                    currentKbSearchMode === 'lexical' ? '📝 词法搜索' :
                    '⚡ 混合搜索';

  const responseTime = metadata.query_time_ms ? `${metadata.query_time_ms}ms` : '计算中...';

  let resultHtml = `
    <div class="kb-enhanced-result">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #e0e0e0;">
        <div style="font-weight: bold; color: #1976D2; font-size: 14px;">
          ${modeLabel}
        </div>
        <div style="display: flex; gap: 16px; align-items: center;">
          <span style="color: #666; font-size: 12px;">找到 ${hits.length} 个结果</span>
          <span style="color: #2E7D32; font-size: 12px; font-weight: bold;">响应: ${responseTime}</span>
        </div>
      </div>
      <div style="display: flex; flex-direction: column; gap: 12px;">
  `;

  // 生成每个搜索结果项
  hits.forEach((hit, index) => {
    resultHtml += generateSearchResultItemHTML(hit, index + 1);
  });

  resultHtml += `
      </div>
      <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #e0e0e0; text-align: center; color: #999; font-size: 12px;">
        💡 这是使用高效的向量检索技术获取的结果，能够理解语义相似性。
      </div>
    </div>
  `;

  return resultHtml;
}


// ============================================================
// 改动 4：生成单个搜索结果项的 HTML
// ============================================================

/**
 * 生成单个搜索结果项，包含分数、分类等信息
 */
function generateSearchResultItemHTML(hit, index) {
  // 确定来源标签
  const sourceLabel = hit.source_type === 'vector' ? '向量' :
                      hit.source_type === 'graph' ? '图谱' :
                      hit.source_type === 'private' ? '私有' :
                      hit.source_type === 'lexical' ? '词法' : '混合';

  // 计算百分比
  const vectorPercent = hit.vector_score ? Math.round(hit.vector_score * 100) : null;
  const lexicalPercent = hit.lexical_score ? Math.round(hit.lexical_score * 100) : null;
  const hybridPercent = Math.round((hit.score || 0) * 100);

  // 分数显示 HTML
  let scoreHtml = '';
  if (vectorPercent) {
    scoreHtml += `<span style="background: #E3F2FD; color: #1976D2; padding: 2px 6px; border-radius: 3px; font-size: 11px;">向量: ${vectorPercent}%</span>`;
  }
  if (lexicalPercent) {
    scoreHtml += `<span style="background: #FFF3E0; color: #F57C00; padding: 2px 6px; border-radius: 3px; font-size: 11px;">词法: ${lexicalPercent}%</span>`;
  }
  scoreHtml += `<span style="background: #E8F5E9; color: #2E7D32; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: bold;">综合: ${hybridPercent}%</span>`;

  // 来源和分类信息
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

  // 组合成完整 HTML
  const snippet = hit.snippet || hit.content || '（无内容预览）';
  const title = hit.title || '知识片段';

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
          <div style="color: #666; font-size: 12px; line-height: 1.4; margin: 8px 0; padding: 6px; background: #fafafa; border-radius: 3px; max-height: 60px; overflow: hidden;">
            ${escapeHtmlForKB(snippet)}
          </div>
          <button onclick="insertKBResultToInput('${escapeJsString(title)}')" 
                  style="background: #4CAF50; color: white; border: none; padding: 6px 12px; border-radius: 3px; cursor: pointer; font-size: 12px; transition: background 0.2s;">
            引用这个答案
          </button>
        </div>
      </div>
    </div>
  `;
}


// ============================================================
// 改动 5：添加辅助函数
// ============================================================

/**
 * 转义 HTML，防止 XSS 攻击
 */
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

/**
 * 转义 JavaScript 字符串
 */
function escapeJsString(str) {
  return String(str || '')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r');
}

/**
 * 将知识库结果插入到输入框
 */
function insertKBResultToInput(title) {
  const input = document.getElementById('questionInput');
  if (input) {
    const currentValue = input.value.trim();
    const newValue = currentValue + '\n\n📚 来自知识库: ' + title;
    input.value = newValue;
    input.focus();
    // 滚动到输入框
    input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

/**
 * 切换搜索模式
 */
function switchKBSearchMode(mode) {
  if (KB_SEARCH_MODES[mode] || Object.values(KB_SEARCH_MODES).includes(mode)) {
    currentKbSearchMode = mode;
    console.log('Knowledge Base search mode switched to:', mode);
  }
}


// ============================================================
// 改动 6：（可选）添加搜索模式选择器
// ============================================================

/**
 * 创建搜索模式选择器 HTML
 * 如果要添加到 UI 中，可以调用这个函数
 */
function createKBSearchModeSelector() {
  return `
    <div style="display: flex; gap: 12px; margin: 8px 0; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 13px;">
      <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
        <input type="radio" name="kb_search_mode" value="dense_vector" 
               ${currentKbSearchMode === KB_SEARCH_MODES.DENSE_VECTOR ? 'checked' : ''}
               onchange="switchKBSearchMode('dense_vector')">
        <span>🔍 向量搜索</span>
      </label>
      <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
        <input type="radio" name="kb_search_mode" value="hybrid" 
               ${currentKbSearchMode === KB_SEARCH_MODES.HYBRID ? 'checked' : ''}
               onchange="switchKBSearchMode('hybrid')">
        <span>⚡ 混合搜索 (推荐)</span>
      </label>
      <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
        <input type="radio" name="kb_search_mode" value="lexical" 
               ${currentKbSearchMode === KB_SEARCH_MODES.LEXICAL ? 'checked' : ''}
               onchange="switchKBSearchMode('lexical')">
        <span>📝 词法搜索</span>
      </label>
    </div>
  `;
}


// ============================================================
// 说明：集成步骤
// ============================================================

/*

【步骤 1】在 chat-page.js 顶部（与其他全局变量一起）添加：

  const KB_SEARCH_MODES = {
    HYBRID: 'hybrid',
    DENSE_VECTOR: 'dense_vector',
    LEXICAL: 'lexical'
  };
  let currentKbSearchMode = KB_SEARCH_MODES.HYBRID;


【步骤 2】找到现有的 searchKnowledgeFromInput 函数（大约在第 939 行）并替换为上面提供的新函数


【步骤 3】在 chat-page.js 中添加其他辅助函数：
  - generateEnhancedSearchResultsHTML()
  - generateSearchResultItemHTML()
  - escapeHtmlForKB()
  - escapeJsString()
  - insertKBResultToInput()
  - switchKBSearchMode()
  - createKBSearchModeSelector()


【步骤 4】（可选）如果要添加搜索模式选择器到 UI，在适当位置调用：
  document.getElementById('someContainer').innerHTML = createKBSearchModeSelector();


【步骤 5】测试！
  - 输入查询词
  - 点击"检索知识库"
  - 确认看到分数、分类、响应时间等信息


完成！🎉

*/
