const fs = require('fs');
const content = fs.readFileSync('frontend/assets/js/pages/chat-page.js', 'utf8');

// evaluate the functions from chat-page.js
const INTERNAL_ANSWER_LINE_RE = /(?:`?tool_[a-z0-9_]+`?|agent_scratchpad|return_intermediate_steps|kb_retry_triggered|preferred_kb_tool|prompt injection)/i;

function normalizeAnswerHeading(line) {
    return String(line || '')
      .trim()
      .replace(/^[#>*\-\d.)\s]+/, '')
      .trim()
      .split(/[：:]/, 1)[0]
      .trim()
      .replace(/^[:：]+|[:：]+$/g, '')
      .toLowerCase();
}

const PRIVATE_ANSWER_HEADINGS = new Set([
    '分析', '思考', '思路', '推理', '推理过程', '内部分析',
    '内部推理', '解题分析', '路径判断', '证据链', '工具调用',
    '调用记录', '中间过程', 'analysis', 'reasoning', 'thinking', 'scratchpad'
]);

const PUBLIC_ANSWER_HEADINGS = new Set([
    '讲解', '解答', '答案', '结论', '建议', '练习', '互动',
    '学习计划', '练习题', '复习建议', '下一步', '知识点', '易错点'
]);

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
    
    // fallback
    return rawLines.map(r => String(r || '').replace(/\s+$/g, '')).filter(r => !shouldHideAnswerLine(r.trim())).join('\n');
}

const input = `
# 分析

根据知识库：学生 ddl 在「连续与可导的关系」上掌握度为 0.35（<0.4），属**知识性薄弱**

---

## 讲解

### ✅ 定义回顾
  「根据知识库：函数连续性」
`;

console.log("----");
console.log(sanitizeUserVisibleAnswer(input));
console.log("----");

