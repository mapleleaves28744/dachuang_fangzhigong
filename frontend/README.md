# Frontend 文档

前端采用多页面 + 模块化脚本结构，页面入口在 `frontend/` 根目录，页面逻辑在 `frontend/assets/js/pages/`，共享能力在 `frontend/assets/js/shared/`。

## 页面索引

- `index.html`：主页入口。
- `chat.html`：智能体聊天页（默认自动路由到智能体与知识库，无需手动切换模式）。
- `dashboard.html`：学习与系统指标看板。
- `knowledge-map.html`：知识图谱可视化。
- `question-bank.html`：题库相关页面。
- `spaces.html`：学习空间资料管理。
- `test-report-dashboard.html`：测试/回归结果展示。

## 目录约定

- `assets/css/shared/`：跨页面复用样式。
- `assets/css/pages/`：页面私有样式。
- `assets/js/shared/`：用户上下文、API 工具、壳层逻辑。
- `assets/js/pages/`：页面业务逻辑。

## 与后端通信约定

- 普通接口：`fetch + JSON`。
- 多模态上传：`FormData`（图片文件 + 文本字段）。
- 智能体流式：SSE（`text/event-stream`），用于展示中间步骤与工具调用反馈。

## 智能体页面行为（chat）

- 文本问题默认发送到 `/api/agent/ocr-tutor`，由后端自动决定是否调用知识库、图谱与其他工具。
- 当智能体通道异常时，前端会自动回退到 `/api/ask`，避免要求用户手动切换模式。
- 图片优先走 OCR；OCR 失败但有文本时，后端会自动降级到文本路径。
- 支持展示 `steps_log` 工作流时间线与证据信息。

## 前端版本时间线（倒序）

### 2026-04-10（当前）

- 对齐智能体流式路径与后端契约。
- 强化智能体工作流展示与错误降级体验。

### 2026-04（上旬）

- 聊天页收起手动模式开关，默认自动智能体路由并保留工具轨迹展示。
- 新增测试报告看板、知识图谱页和学习空间页增强。

### 2026-03（历史）

- 多页面布局与基础共享模块建立。

## 开发建议

- 新增页面时，HTML 放 `frontend/` 根目录，逻辑放 `assets/js/pages/`。
- 跨页面复用能力统一收敛到 `assets/js/shared/`。
- 避免新增泛名文件（如 `main.js`、`style.css`），优先按页面命名。
