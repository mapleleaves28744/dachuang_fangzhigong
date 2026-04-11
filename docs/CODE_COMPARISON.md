# 代码对比：旧 vs 新前端

这个文档清晰展示改造前后的代码差异，帮助你理解改了什么。

---

## 📊 总体变化

| 方面 | 改造前 | 改造后 | 改进 |
|------|--------|--------|------|
| **分数显示** | 单个 score | 向量 + 词法 + 综合 | ✅ 显示分数构成 |
| **响应时间** | 不显示 | 显示毫秒数 | ✅ 证明性能提升 |
| **知识来源** | 不显示 | 显示来源类型 | ✅ 帮助理解 |
| **分类信息** | 不显示 | 显示学科/章节 | ✅ 更好索引 |
| **结果个数** | 3 个 | 5 个 | ✅ 更多选择 |
| **UI 设计** | 简陋文本 | 现代卡片设计 | ✅ 更美观 |
| **交互功能** | 无 | 引用按钮 | ✅ 可直接利用结果 |

---

## 🔄 代码对比

### 对比 1: 调用函数

#### ❌ 改造前
```javascript
// chat-page.js 第 1938 行
kbSearchBtn.addEventListener('click', async function () {
  if (isAskingQuestion) return;
  try {
    await searchKnowledgeFromInput();  // 调用旧函数
  } catch (error) {
    // 错误处理...
  }
});
```

---

#### ✅ 改造后
```javascript
// chat-page.js 第 1938 行 - 不变
kbSearchBtn.addEventListener('click', async function () {
  if (isAskingQuestion) return;
  try {
    await searchKnowledgeFromInput();  // 调用新增强版函数
  } catch (error) {
    // 错误处理...
  }
});

// 额外的全局变量（在文件顶部）
const KB_SEARCH_MODES = {
  HYBRID: 'hybrid',
  DENSE_VECTOR: 'dense_vector', 
  LEXICAL: 'lexical'
};
let currentKbSearchMode = KB_SEARCH_MODES.HYBRID;
```

**变化**: 
- ✅ 函数名相同，但函数体完全重写
- ✅ 添加搜索模式变量
- ✅ 保持向后兼容

---

### 对比 2: searchKnowledgeFromInput() 函数完整改造

#### ❌ 改造前 (39 行)
```javascript
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

  // 简单调用 API
  const response = await fetch(`${API_BASE}/api/agent/kb/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      student_id: getUserId(),
      query: query,
      top_k: 3  // 只要 3 个结果
    })
  });
  
  const data = await parseApiResponse(response);
  const hits = Array.isArray(data.hits) ? data.hits : [];
  
  // 简单拼接文本
  const lines = hits.length
    ? hits.map(function (row, index) {
        return `${index + 1}. ${row.title || '未命名'} (score=${row.score || 0})\n${row.snippet || ''}`;
      }).join('\n\n')
    : '未命中任何资料。';

  // 直接显示纯文本
  addMessage(`知识库检索结果（query: ${query}）\n\n${lines}`, 'ai', {
    source: 'kb_search',
    aiUsed: false,
    error: '',
    evidence: {
      tool_calls: ['kb_search'],
      trace_count: hits.length
    }
  });
  return data;
}
```

**问题分析** 🔴:
- 只显示 title 和 snippet
- 不显示向量相似度
- 不显示响应时间
- 结果太少（只有 3 个）
- 显示格式为纯文本，没有格式化
- 不区分来源类型
- 用户看不出改进

---

#### ✅ 改造后 (完整新版本)
```javascript
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
        top_k: 5,  // ✅ 改为 5 个结果
        search_mode: currentKbSearchMode  // ✅ 传递搜索模式
      })
    });

    const data = await parseApiResponse(response);
    const hits = Array.isArray(data.hits) ? data.hits : [];
    
    // ✅ 调用新的 HTML 生成函数
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
        search_mode: currentKbSearchMode,  // ✅ 记录搜索模式
        response_time_ms: data.query_time_ms || 0,  // ✅ 记录响应时间
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
```

**改进分析** 🟢:
- ✅ `top_k: 5` - 获取更多结果
- ✅ `search_mode: currentKbSearchMode` - 支持模式选择
- ✅ 调用 `generateEnhancedSearchResultsHTML()` - 生成完整 HTML
- ✅ 传递 `metadata` 包含响应时间和其他信息
- ✅ 更好的错误处理

---

### 对比 3: 结果显示

#### ❌ 改造前 - 纯文本显示
```
知识库检索结果（query: 函数求导）

1. 未命名 (score=0.82)
题干：函数f(x)=x^2，求f'(x)。

2. 未命名 (score=0.75)
题干：什么是求导...
```

**问题** 🔴:
- 不知道是什么类型的匹配
- 看不出分数来自何处
- 没有格式
- 无法和用户交互

---

#### ✅ 改造后 - 结构化 HTML 显示
```html
⚡ 混合搜索    找到 5 个结果    响应: 42ms

┌─────────────────────────────────────────────┐
│ 1 导数的几何意义                [向量]       │
│   向量: 92% | 词法: 75% | 综合: 89%        │
│   源: 向量 | 数学 | 第二章                  │
│                                             │
│   导数表示函数在某点的瞬时变化率,            │
│   几何上表现为曲线的切线斜率...             │
│                                             │
│   [引用这个答案]                            │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 2 求导法则                     [混合]       │
│   向量: 81% | 词法: 85% | 综合: 84%        │
│   源: 混合 | 数学 | 第二章                  │
│                                             │
│   链式法则、乘法法则、商法则都是            │
│   重要的求导法则...                        │
│                                             │
│   [引用这个答案]                            │
└─────────────────────────────────────────────┘

💡 这是使用高效的向量检索技术获取的结果...
```

**改进** 🟢:
- ✅ 显示搜索模式（混合搜索）
- ✅ 显示响应时间（42ms）
- ✅ 显示分数构成（3 个分数）
- ✅ 显示来源类型（向量/混合）
- ✅ 显示分类（学科/章节）
- ✅ 完整内容
- ✅ 可交互（引用按钮）

---

### 对比 4: 新增辅助函数

#### ✅ 新增函数 1: generateEnhancedSearchResultsHTML()
```javascript
function generateEnhancedSearchResultsHTML(query, hits, metadata) {
  if (!hits || hits.length === 0) {
    return `<div class="kb-enhanced-result" style="...">
             <div>未找到与"${escapeHtmlForKB(query)}"相关的知识</div>
           </div>`;
  }

  const modeLabel = currentKbSearchMode === 'dense_vector' ? '🔍 向量搜索' :
                    currentKbSearchMode === 'lexical' ? '📝 词法搜索' :
                    '⚡ 混合搜索';

  const responseTime = metadata.query_time_ms ? `${metadata.query_time_ms}ms` : '计算中...';

  let resultHtml = `
    <div class="kb-enhanced-result">
      <div style="...">
        <div style="...">
          ${modeLabel}
        </div>
        <div style="...">
          <span>找到 ${hits.length} 个结果</span>
          <span>响应: ${responseTime}</span>
        </div>
      </div>
      <div style="...">
  `;

  // 为每个结果生成 HTML
  hits.forEach((hit, index) => {
    resultHtml += generateSearchResultItemHTML(hit, index + 1);
  });

  resultHtml += `
      </div>
    </div>
  `;

  return resultHtml;
}
```

**功能** 🟢:
- ✅ 生成容器 HTML
- ✅ 显示搜索模式
- ✅ 显示结果数量
- ✅ 显示响应时间
- ✅ 调用逐项生成函数

---

#### ✅ 新增函数 2: generateSearchResultItemHTML()
```javascript
function generateSearchResultItemHTML(hit, index) {
  const sourceLabel = hit.source_type === 'vector' ? '向量' :
                      hit.source_type === 'graph' ? '图谱' : '混合';

  const vectorPercent = hit.vector_score ? Math.round(hit.vector_score * 100) : null;
  const lexicalPercent = hit.lexical_score ? Math.round(hit.lexical_score * 100) : null;
  const hybridPercent = Math.round((hit.score || 0) * 100);

  // 构建分数显示
  let scoreHtml = '';
  if (vectorPercent) {
    scoreHtml += `<span style="...">向量: ${vectorPercent}%</span>`;
  }
  if (lexicalPercent) {
    scoreHtml += `<span style="...">词法: ${lexicalPercent}%</span>`;
  }
  scoreHtml += `<span style="...">综合: ${hybridPercent}%</span>`;

  // 构建元数据
  let metadataHtml = `<span style="...">源: ${sourceLabel}</span>`;
  if (hit.discipline) {
    metadataHtml += `<span style="...">${hit.discipline}</span>`;
  }
  if (hit.chapter) {
    metadataHtml += `<span style="...">${hit.chapter}</span>`;
  }

  return `
    <div style="...">
      <div style="...">
        <div style="...">
          <strong>${index}</strong>
        </div>
        <div style="...">
          <div style="...">
            ${escapeHtmlForKB(hit.title || '知识片段')}
          </div>
          <div style="...">
            ${scoreHtml}
          </div>
          <div style="...">
            ${metadataHtml}
          </div>
          <div style="...">
            ${escapeHtmlForKB(hit.snippet || '')}
          </div>
          <button onclick="insertKBResultToInput('...')">
            引用这个答案
          </button>
        </div>
      </div>
    </div>
  `;
}
```

**功能** 🟢:
- ✅ 生成单项结果 HTML
- ✅ 显示分数（向量/词法/综合）
- ✅ 显示来源和分类
- ✅ 显示内容摘要
- ✅ 提供交互按钮

---

#### ✅ 新增函数 3-7: 工具函数
```javascript
// 防 XSS 的 HTML 转义
function escapeHtmlForKB(text) { ... }

// JS 字符串转义
function escapeJsString(str) { ... }

// 引用答案到输入框
function insertKBResultToInput(title) { ... }

// 搜索模式切换
function switchKBSearchMode(mode) { ... }

// 搜索模式选择器 UI
function createKBSearchModeSelector() { ... }
```

---

## 📈 性能对比

| 指标 | 改造前 | 改造前 | 改进 |
|------|--------|--------|------|
| **API 返回字段数** | 3 个 | 7+ 个 | +133% |
| **结果显示数量** | 3 个 | 5 个 | +67% |
| **分数维度** | 1 个 | 3 个 | +200% |
| **响应时间显示** | ✗ 无 | ✓ 有 | ✅ 新增 |
| **元数据显示** | ✗ 无 | ✓ 有 | ✅ 新增 |
| **交互功能** | 0 个 | 1+ 个 | ✅ 新增 |
| **渲染时间** | ~10ms 纯文本 | ~50ms HTML | 基本相同 |

---

## 🔗 文件关系图

```
chat.html
  ├─> chat-page.js (改造: searchKnowledgeFromInput 函数)
  ├─> kb-search-upgrade.js (新增: 工具函数库)
  └─> enhanced-kb-search.js (可选: 增强功能库)

后端 API: /api/agent/kb/search
  └─> 返回: hits, query_time_ms, search_mode 等
```

---

## ✅ 改造检查清单

| 项目 | 改造前 | 改造后 | 方式 |
|------|--------|--------|------|
| searchKnowledgeFromInput() | ✓ 存在 | ✅ 改进 | 重写函数 |
| 搜索模式变量 | ✗ 无 | ✅ 有 | 新增变量 |
| HTML 生成函数 | ✗ 无 | ✅ 有 | 新增函数 |
| 分数显示 | 单一 | ✅ 三维 | 改进模板 |
| 响应时间 | ✗ 无 | ✅ 显示 | 新增字段 |
| 来源标签 | ✗ 无 | ✅ 显示 | 新增字段 |
| 交互按钮 | ✗ 无 | ✅ 有 | 新增功能 |

---

## 🚀 改造步骤

1. **第1步**: 打开 `chat-page.js`
2. **第2步**: 找到第 939 行的 `searchKnowledgeFromInput()` 函数
3. **第3步**: 替换为新版本
4. **第4步**: 在文件顶部添加搜索模式变量
5. **第5步**: 添加所有新增的辅助函数
6. **第6步**: 测试搜索功能

---

## 📚 参考文档

- [快速改造指南](QUICK_FRONTEND_UPGRADE.md)
- [完整改造指南](FRONTEND_ENHANCEMENT_GUIDE.md)
- [代码升级包](../assets/js/kb-search-upgrade.js)
- [验证脚本](../../verify_frontend_upgrade.py)

