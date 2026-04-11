# Docs Index

本目录用于维护项目说明、部署指南与架构文档。

## 核心文档

- [README.md](../README.md)：项目总览、能力清单、测试入口、总时间线。
- [CHANGELOG_TEMPLATE.md](./CHANGELOG_TEMPLATE.md)：发布说明模板（每次发版复用）。
- [CLOUD_QUICKSTART.md](./CLOUD_QUICKSTART.md)：云服务器一页启动（启动项目说明）。
- [neo4j-quickstart.md](./neo4j-quickstart.md)：Neo4j Aura 连接与排障（云端 Neo4j 说明）。
- [e2e_summary.json](./e2e_summary.json)：最近一次 E2E 回归摘要。
- [智能体改造.md](./智能体改造.md)：智能体方案与演进记录。
- [PAGE_ACCEPTANCE_CHECKLIST.md](./PAGE_ACCEPTANCE_CHECKLIST.md)：页面级功能验收清单，按页面核对前后端是否对齐。

## 常用定位（保留项）

- OCR 说明：见 [README.md](../README.md) 中“OCR 说明（请保留）”。
- 云端 Neo4j 说明：见 [README.md](../README.md) 与 [neo4j-quickstart.md](./neo4j-quickstart.md)。
- 启动项目说明：见 [README.md](../README.md) 与 [CLOUD_QUICKSTART.md](./CLOUD_QUICKSTART.md)。

## 后端契约与实现相关

- [backend/docs/API_CONTRACT.md](../backend/docs/API_CONTRACT.md)：后端 API 契约。
- 关键后端文件：
  - `backend/app/api/agent_routes.py`
  - `backend/app/services/agent_service.py`
  - `backend/app/services/agent_tools.py`
  - `backend/app/services/knowledge_base.py`
  - `backend/app/services/neo4j_store.py`

## 当前实现要点

- 智能体核心接口：`POST /api/agent/ocr-tutor`（支持图片优先、文本回退、流式模式）。
- 知识库接口：`POST /api/agent/kb/ingest`、`POST /api/agent/kb/search`。
- 在线评测：`POST /api/agent/eval`、`POST /api/agent/eval-ab`。
- RAG-Graph：知识库检索返回 `hits` 与 `graph_context`，支持知识路径增强。

## 文档版本时间线（倒序）

### 2026-04-11（当前）

- 新增“智能体工具链最新行为”文档对齐：
  - 学习计划工具已支持落盘（`user_plans`）与 `learning_plan` 事件记录。
  - 错题归因工具支持诊断事件落盘（`diagnosis`）。
  - `steps_log.latency_ms` 为工具真实逐步耗时，不再平均分配。
  - 知识图谱新增非知识点三层过滤（含停用词扩展）。
- 页面验收清单新增图谱“非知识点不得入图”的核对项。

### 2026-04-10

- 文档索引补齐智能体、知识库、评测与 RAG-Graph 路径。
- 明确关键实现文件与测试入口。

### 2026-04（上旬）

- 新增智能体评测与知识库接口说明。

### 2026-03（历史）

- 完成基础部署文档与 Neo4j 快速接入文档。
