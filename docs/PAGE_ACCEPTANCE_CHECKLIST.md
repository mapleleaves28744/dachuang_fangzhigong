# 页面级功能验收清单

本文用于核对前端页面是否真正接入了后端能力，重点检查“页面可见、数据可渲染、交互可用、异常可解释”。

## 验收原则

- 主入口优先：以 [frontend/dashboard.html](../frontend/dashboard.html) 为准，而不是只看增强演示页。
- 数据驱动优先：页面需要从后端 summary、知识库、评测、图谱或任务接口中取数并渲染。
- 失败可解释：接口失败时页面应显示明确提示，不应只出现空白或泛化报错。
- 缓存可见：更新脚本后建议强制刷新浏览器，避免旧 JS 缓存导致误判。

## 页面级验收

### 1. 首页 / 导航页

页面： [frontend/index.html](../frontend/index.html)

验收项：

- 页面可正常打开，无 404、白屏或脚本报错。
- 可以进入“添加内容”“智能问答”“题库练习”“学习仪表盘”“知识图谱”“我的空间”。
- 登录态或用户信息区域显示正常。

通过标准：

- 入口按钮均可点击。
- 跳转后页面地址正确，且页面主体内容可见。

### 2. 智能问答页

页面： [frontend/chat.html](../frontend/chat.html)

验收项：

- 普通文本问答可发送并返回答案。
- 智能体模式可发送并展示工具调用过程或最终答案。
- 智能体执行时间线中，各工具步骤耗时应为“逐步真实耗时”，不应全部相同。
- 上传图片后，OCR 入口可正常工作。
- 流式返回时，页面能区分“最终结果”和“错误结果”。
- 若后端返回 error，页面应展示真实错误，而不是只显示“未收到最终结果”。

通过标准：

- `stream=true` 的请求能返回可展示的最终结果。
- Redis 不可用或模型 API 失败时，页面提示应明确。

### 3. 题库练习页

页面： [frontend/question-bank.html](../frontend/question-bank.html)

验收项：

- 题目列表可加载。
- 题目筛选、作答、提交、查看解析可用。
- 与学习画像或知识点的关联信息能正确展示。

通过标准：

- 页面无空白区块。
- 核心操作至少能跑通一轮。

### 4. 学习仪表盘页

页面： [frontend/dashboard.html](../frontend/dashboard.html)

验收项：

- 主页顶部可见整体掌握度、数据池、图谱规模、干预数量等概览。
- “知识掌握热力图快照”能渲染已有知识点。
- “知识依赖链追溯”能展示前置路径。
- “学习风格强度”条形图可见并能随 summary 更新。
- “推荐资源与补救路径”“今日任务”“复习安排”可从后端数据渲染。
- 新增的能力对齐视图可见：
  - 知识点热力图（5级掌握度可视化）
  - 学习进度条动画
  - AI推荐学习路径（Timeline 视图）
  - 数据分析图表（Chart.js 集成）

通过标准：

- 页面能直接看到上述四项能力，不需要切换到演示页。
- 若数据不足，应显示空态说明，而不是空白区域。

### 5. 知识图谱页

页面： [frontend/knowledge-map.html](../frontend/knowledge-map.html)

验收项：

- 知识节点和关系可视化正常。
- 非知识点词（如“自学”“零基础”“新手”等学习状态词）不应出现在图节点或关系中。
- 可以查看知识点掌握度、依赖链、来源追踪。
- 删除/屏蔽知识点后，仪表盘和图谱能同步刷新。

通过标准：

- 图谱数据来自后端接口，且页面无渲染错误。

### 6. 空间页

页面： [frontend/spaces.html](../frontend/spaces.html)

验收项：

- 空间列表可见。
- 新建、切换、查看空间内容可用。
- 空间内容与仪表盘数据池能对应起来。

通过标准：

- 多空间切换后，关联页面能同步更新数据。

### 7. 测试报告页

页面： [frontend/test-report-dashboard.html](../frontend/test-report-dashboard.html)

验收项：

- 测试报告能打开。
- 数据图表或统计卡片可见。
- 可用于核对最新回归测试结果。

通过标准：

- 报告内容与当前测试状态一致。

## 接口对齐核对点

### 智能体接口

- `POST /api/agent/ocr-tutor`
- `GET /api/agent/metrics`
- `POST /api/agent/eval`
- `POST /api/agent/eval-ab`
- `POST /api/agent/learning-feedback`

### 知识库与图谱接口

- `POST /api/agent/kb/ingest`
- `POST /api/agent/kb/search`
- `DELETE /api/knowledge_graph/node`
- `GET /api/dashboard/summary`
- `GET /api/plans`

## 建议验收顺序

1. 先看 [frontend/dashboard.html](../frontend/dashboard.html)，确认主页面四项能力可见。
2. 再测 [frontend/chat.html](../frontend/chat.html)，确认智能体模式不会只返回泛化错误。
3. 然后核对 [frontend/knowledge-map.html](../frontend/knowledge-map.html) 和 [frontend/spaces.html](../frontend/spaces.html) 的联动。
4. 最后检查 [frontend/test-report-dashboard.html](../frontend/test-report-dashboard.html) 作为回归记录。

## 当前已知状态

- 主页面 [frontend/dashboard.html](../frontend/dashboard.html) 已补上能力对齐视图。
- 智能体模式已修复“error 被前端吞掉”的问题。
- Redis 不可用时，后端会回退内存会话历史。
- 智能体异常时，后端会返回可展示的 final 兜底结果。
