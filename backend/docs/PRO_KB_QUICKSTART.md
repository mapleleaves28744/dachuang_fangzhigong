# 专业向量知识库快速生成（2小时内可跑通）

本方案面向当前项目，提供一键生成流程：

- 1000个知识点实体（可改为 800~1200）
- 每条卡片3段切片（总计约 2500~4000）
- 单片约 200~300 token（估算）
- TF-IDF 向量索引（可直接做 RAG 召回）
- 轻量图谱骨架（不依赖 Neo4j 运维，关系边约 1800~2500）

## 1. 一键生成

在 `backend` 目录执行：

```powershell
c:/Users/28744/Desktop/fangwen/.venv/Scripts/python.exe scripts/build_professional_vector_kb.py --count 1000
```

## 2. 产出文件

输出目录：`backend/data/pro_kb/`

- `pro_kb_cards.jsonl`：知识卡片（章节结构化）
- `pro_kb_chunks.jsonl`：RAG切片（每卡3片）
- `pro_kb_tfidf_vectorizer.pkl`：向量器
- `pro_kb_tfidf_matrix.npz`：切片向量矩阵
- `pro_kb_graph.json`：轻量图谱骨架
- `pro_kb_summary.json`：统计摘要（含 token 区间与实体/关系规模）

## 3. 图谱实体与关系

实体类型：

- 章节
- 知识点
- 公式
- 题型
- 考点

关系类型：

- 前置依赖
- 章节从属
- 题型同源
- 易混淆关联
- 考点递进

## 4. 接入建议（当前项目）

1. 在 `knowledge_base.py` 增加对 `pro_kb_chunks.jsonl` + `pro_kb_tfidf_*` 的加载与检索函数。
2. 在 `search_kb(...)` 中并联召回：
   - 公共向量召回（本文件产物）
   - 用户私有资料召回（现有逻辑）
   - 图谱上下文增强（现有 graph_context）
3. `agent_tools.py` 保持工具接口不变，通过统一 `search_kb(...)` 获取混合结果。

## 5. 混排检索评测（建议赛前必跑）

在 `backend` 目录执行：

```powershell
c:/Users/28744/Desktop/fangwen/.venv/Scripts/python.exe scripts/eval_hybrid_retrieval.py --top_k 5
```

默认输入样例：`backend/tests/hybrid_retrieval_eval_cases.json`

默认报告输出：`backend/docs/hybrid_retrieval_report.json`

报告包含：

- hit@k
- public/private 命中率
- graph_context 覆盖率
- 关键词覆盖率
- 平均延迟与综合评分

## 6. 图谱可用性专项评测（GraphRAG）

在 `backend` 目录执行：

```powershell
c:/Users/28744/Desktop/fangwen/.venv/Scripts/python.exe scripts/eval_graph_availability.py --top_k 5
```

默认输入样例：`backend/tests/graph_availability_eval_cases.json`

默认报告输出：`backend/docs/graph_availability_report.json`

三项核心指标：

- `graph_connectivity_rate`：图数据库连通性
- `graph_recall_rate`：图谱上下文召回率
- `evidence_consistency_rate`：图谱证据与文本证据一致性

## 7. Neo4j 健康检查（环境排障）

在 `backend` 目录执行：

```powershell
c:/Users/28744/Desktop/fangwen/.venv/Scripts/python.exe scripts/check_neo4j_health.py --force --json
```

连通后建议立刻复测图谱指标：

```powershell
c:/Users/28744/Desktop/fangwen/.venv/Scripts/python.exe scripts/eval_graph_availability.py --top_k 5
```
