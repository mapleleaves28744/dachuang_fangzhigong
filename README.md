# 坊知工 FZG

坊知工是面向教育场景的智能学习伴侣系统，当前版本已包含多模态 OCR、工具调用式智能体、知识库检索、知识图谱增强（RAG-Graph）与 SSE 流式交互能力。

## 系统架构

- 前端：原生 HTML/CSS/JS，多页面结构，支持智能体模式和时间线展示。
- 后端：Flask API + 可选 Celery/Redis，提供问答、评测、知识库、图谱接口。
- 智能体：LangChain Tool Calling（掌握度、图谱、知识库、学习计划、错题归因）。
- 知识增强：文本检索 + Neo4j 关系查询（RAG-Graph）。

## 核心能力

- 多模态题目解析：`POST /api/agent/ocr-tutor`，图片优先，支持文本回退。
- 智能体辅导：调用工具链后输出答案，并返回 `steps_log`、`evidence`、`meta`。
- 流式交互：`stream=true` 时返回 SSE 事件流，支持中间工具调用反馈。
- 知识库能力：
  - 入库：`POST /api/agent/kb/ingest`
  - 检索：`POST /api/agent/kb/search`
  - 检索结果包含 `hits` 与 `graph_context`。
- 在线评测：
  - 单评测：`POST /api/agent/eval`
  - A/B 对比：`POST /api/agent/eval-ab`
- 学习反馈（P2 新增）：`POST /api/agent/learning-feedback`
  - 记录任务完成度、正确率、耗时，并动态更新学生掌握度。
  - 请求体：`{student_id, task_id, task_type, correct_count, total_count, duration_seconds, concept}`

## 🎯 竞赛改进文档

### 性能基准与优化

- **[性能基准对比报告](docs/PERFORMANCE_BENCHMARK.md)**：混合检索(RAG-Graph)相比纯文本精度✅+3.5%，延迟+16.7%（在可接受范围）
- **性能测试脚本**：`backend/scripts/bench_comparison.py` - 对比纯文本/纯图谱/混合检索的性能
- **教育领域测试集**：`backend/scripts/education_testset.json` - 40个中学数学/英语/物理用例

### 商业模式与成本分析  

- **[商业模式报告](docs/BUSINESS_MODEL.md)**：
  - 收入预测：Y1 ¥4.1M (B2B+B2C+渠道)
  - 成本结构：Y1 ¥4.6M（86%人力成本）
  - 盈亏平衡：Year 2 达EBITDA +¥2.7M
  - 融资路线：Seed ¥2.5M → Series A ¥8-10M → IPO 2028

### 前端优化

- **[主仪表盘](frontend/dashboard.html)**（已对齐展示）：
  - 📊 知识点热力图（5级掌握度可视化）
  - 📈 学习进度条动画
  - 🛤️ AI推荐学习路径（Timeline视图）
  - 📉 数据分析图表（Chart.js集成）

## 快速启动

### 1. 安装依赖

```powershell
cd backend
python -m pip install -r requirements.txt
```

### 2. 关键环境变量（示例）

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=your_api_key
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus

AGENT_TIMEOUT_SECONDS=50
AGENT_MAX_RETRIES=1
AGENT_ENABLE_GUARD=true
AGENT_HISTORY_BACKEND=auto
AGENT_REDIS_URL=redis://127.0.0.1:6379/2

USE_NEO4J=auto
NEO4J_URI=neo4j+s://<your-aura>.databases.neo4j.io
NEO4J_USERNAME=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>
```

### 2.1 OCR 说明（请保留）

- 智能体入口为 `POST /api/agent/ocr-tutor`，支持“图片优先 + 文本回退”。
- 默认可使用 `OCR_PROVIDER=mock` 进行本地联调；接入真实 OCR 时建议统一通过 Qwen-VL。
- 当图片 OCR 上游失败，但请求中包含 `question` 或 `ocr_text` 时，后端会自动降级到文本路径，避免直接 502 中断。

推荐 OCR 相关环境变量：

```env
OCR_PROVIDER=mock
# 若使用真实 OCR，可切换并配置上游密钥/地址
# OCR_PROVIDER=qwen_vl
```

### 2.2 云端 Neo4j（Aura）说明（请保留）

- 本项目支持云端 Neo4j Aura，不要求本地安装 Neo4j 服务端。
- 建议 `USE_NEO4J=auto`：当 URI/账号/密码配置齐全并连通时自动启用。
- 本地仅需安装 Python 驱动（`requirements.txt` 已包含 `neo4j` 依赖）。

Aura 推荐配置：

```env
USE_NEO4J=auto
NEO4J_URI=neo4j+s://<your-aura>.databases.neo4j.io
NEO4J_USERNAME=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>
```

说明：

- `neo4j+s://` 是 Aura 常用安全连接方式。
- 若只做本地最小可运行，可临时关闭：`USE_NEO4J=false`。

### 3. 启动开发栈

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/start-dev-stack.ps1
```

一键停止：

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/stop-dev-stack.ps1
```

Linux 启动（可选）：

```bash
chmod +x scripts/start-dev-stack.sh scripts/stop-dev-stack.sh
./scripts/start-dev-stack.sh
```

Linux 停止：

```bash
./scripts/stop-dev-stack.sh
```

### 3.1 手动启动说明（请保留）

不使用一键脚本时，可按以下顺序手动启动：

1. 安装依赖

```powershell
cd backend
python -m pip install -r requirements.txt
```

1. 启动后端

```powershell
python -m app.server
```

1. 启动前端静态服务（新终端）

```powershell
python -m http.server 5501 --directory frontend
```

1. 健康检查

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

1. 可选：启动 Redis/Celery（完整异步功能）

```powershell
cd backend
tools\redis\redis-server.exe tools\redis\redis.windows.conf --port 6379
```

```powershell
cd backend
$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'
$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'
python -m celery -A app.server:celery_client worker -l info -P solo
```

### 4. 健康检查

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

## 智能体模式常见问题排查

### 现象 1：页面提示“流式会话已结束，但未收到最终结果”

可能原因：

- 后端 SSE 流中断，仅返回 `error` 事件。
- Redis 不可达导致会话历史初始化失败。
- AI Key 无效或模型上游不可用。

建议排查顺序：

1. 检查后端健康状态

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

1. 若本机未启动 Redis，先强制使用内存会话历史

```env
AGENT_HISTORY_BACKEND=memory
```

1. 校验 AI 相关配置

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=<有效密钥>
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus
```

1. 修改环境变量后重启后端

```powershell
python -m app.server
```

说明：当前版本已增强流式兜底逻辑，当智能体运行异常时会返回可展示的 `final` 负载，减少前端“无最终结果”的误报。

## 测试与验收

在 `backend` 目录执行：

```powershell
python -m unittest tests.test_agent_ocr_tutor_contract -v
python -m unittest tests.test_agent_kb_contract -v
python -m unittest tests.test_knowledge_base_graphrag -v
```

## 版本迭代时间线（倒序）

### 2026-04-11（当前）

- 工具执行时间线改为真实逐步耗时统计，修复步骤耗时同值问题。
- 学习计划工具升级为“生成即落盘”：写入 `user_plans` 并记录 `learning_plan` 事件。
- 错题归因工具支持诊断事件落盘，干预看板可直接消费。
- 图谱新增非知识点三层过滤与停用词扩展，阻止“自学/零基础”等状态词入图。

### 2026-04-10

- 智能体接口支持 SSE 流式返回（`stream=true`）。
- `ocr-tutor` 增加 OCR 失败文本降级，避免直接中断。
- 知识库升级为 RAG-Graph 输出：`hits + graph_context`。
- 新增 GraphRAG 测试：`tests/test_knowledge_base_graphrag.py`。
- 修复 A/B 评测入参校验顺序，保证契约一致性。
- 流式事件处理增强：前端不再吞掉 `error` 事件，能展示真实异常原因。
- 会话历史回退增强：Redis 不可达时自动回退内存会话历史。
- 流式兜底增强：智能体运行异常时也返回 `final` 负载，避免会话结束无最终结果。

### 2026-04（上旬）

- 新增知识库入库与检索接口（`/api/agent/kb/ingest`、`/api/agent/kb/search`）。
- 新增在线评测接口（`/api/agent/eval`、`/api/agent/eval-ab`）。
- 智能体支持结构化步骤日志：`steps_log`。

### 2026-03（历史）

- 基础问答、学习画像、知识图谱可视化、学习空间等核心页面与接口完成首版落地。

## 文档导航

- 前端说明：[frontend/README.md](frontend/README.md)
- 文档索引：[docs/README.md](docs/README.md)
- 发布说明模板：[docs/CHANGELOG_TEMPLATE.md](docs/CHANGELOG_TEMPLATE.md)
- 云端启动：[docs/CLOUD_QUICKSTART.md](docs/CLOUD_QUICKSTART.md)
- Neo4j 快速接入：[docs/neo4j-quickstart.md](docs/neo4j-quickstart.md)
