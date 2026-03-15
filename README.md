# 坊知工 FZG

面向学习场景的智能学习伴侣，提供问答、知识图谱、诊断、推荐、复习提醒一体化能力。

## 先看结论

- 仓库不包含必须的大型运行包也可以正常部署和运行核心功能。
- 首次部署建议使用“手动启动”方式，不依赖本地路径硬编码脚本。
- Redis、Celery、Neo4j、真实 AI 都是可选增强项，未配置时系统会回退。

---

## 目录

- [1. 运行环境](#1-运行环境)
- [2. 最小可运行部署（推荐）](#2-最小可运行部署推荐)
- [3. 健康检查](#3-健康检查)
- [4. 启用真实 AI（可选）](#4-启用真实-ai可选)
- [5. 启用 Redis + Celery（可选）](#5-启用-redis--celery可选)
- [6. 启用 Neo4j（可选）](#6-启用-neo4j可选)
- [7. 第三方工具下载（按需）](#7-第三方工具下载按需)
- [8. Windows 启停脚本说明](#8-windows-启停脚本说明)
- [9. 常见问题](#9-常见问题)

---

## 1. 运行环境

必需：

- Python 3.10+
- Git

可选：

- Redis（用于异步任务）
- Neo4j（用于图谱持久化）

说明：

- 没有 Redis/Celery，接口会自动回退同步处理。
- 没有 Neo4j，图谱会回退本地存储。
- 没有 AI Key，问答会回退兜底回答。

---

## 2. 最小可运行部署（推荐）

### 2.1 克隆仓库

```powershell
git clone https://github.com/mapleleaves28744/dachuang_fangzhigong.git
cd dachuang_fangzhigong
```

### 2.2 安装后端依赖

```powershell
cd backend
pip install -r requirements.txt
```

### 2.3 创建环境变量

```powershell
copy .env.example .env
```

推荐首次先用最稳妥配置（backend/.env）：

```env
USE_REAL_AI=false
OCR_PROVIDER=mock
USE_NEO4J=false
```

### 2.4 启动后端

在项目根目录执行：

```powershell
python backend/app.py
```

### 2.5 启动前端静态服务

新开一个终端，在项目根目录执行：

```powershell
python -m http.server 5501 --directory frontend
```

### 2.6 打开页面

- 前端首页: http://127.0.0.1:5501/index.html
- 健康检查: http://127.0.0.1:5000/health

---

## 3. 健康检查

执行：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

首次最小部署时，下面这些字段是正常的：

- status: ok
- celery_enabled: false
- neo4j_enabled: false
- ai_key_configured: false（若未配置 Key）

---

## 4. 启用真实 AI（可选）

编辑 backend/.env：

```env
AI_PROVIDER=qwen
USE_REAL_AI=true
QWEN_API_KEY=your-qwen-api-key
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus
```

启动后再次查看 /health，确认 ai_key_configured 为 true。

---

## 5. 启用 Redis + Celery（可选）

### 5.1 安装并启动 Redis

请先在本机安装 Redis，并确保 6379 端口可用。

### 5.2 配置 backend/.env

```env
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

### 5.3 启动 Celery Worker

在 backend 目录执行：

```powershell
celery -A app.celery_client worker -l info -P solo
```

说明：

- 不启用 Celery 也可运行，异步接口会自动回退同步模式。

---

## 6. 启用 Neo4j（可选）

编辑 backend/.env：

```env
USE_NEO4J=true
NEO4J_URI=neo4j+s://<your-instance>.databases.neo4j.io
NEO4J_USERNAME=<your-neo4j-username>
NEO4J_PASSWORD=<your-neo4j-password>
NEO4J_DATABASE=<your-neo4j-database>
```

若不需要 Neo4j，请保持 USE_NEO4J=false 或 auto（未配全参数时自动关闭）。

---

## 7. 第三方工具下载（按需）

为了避免仓库体积过大，项目不强制内置下列安装包。需要时请自行下载并安装：

- Redis: https://redis.io/docs/latest/operate/oss_and_stack/install/
- Neo4j: https://neo4j.com/download/

你也可以使用云服务版本（例如 Neo4j Aura），不需要本地安装包。

---

## 8. Windows 启停脚本说明

仓库提供了：

- backend/start-dev-stack.ps1
- backend/stop-dev-stack.ps1

这些脚本更适合作者本机环境，可能包含路径或本地工具目录假设。首次部署建议优先按本 README 的手动步骤启动。

---

## 9. 常见问题

### 9.1 PowerShell 中文乱码

```powershell
chcp 65001
```

### 9.2 后端能启动但问答不是大模型回答

检查 backend/.env 中：

- USE_REAL_AI=true
- QWEN_API_KEY 已正确填写

并在 /health 确认 ai_key_configured=true。

### 9.3 Celery 未启用

确认 Redis 正常监听 6379，并已启动 worker。

### 9.4 Neo4j 未启用

确认 NEO4J_URI、NEO4J_USERNAME、NEO4J_PASSWORD、NEO4J_DATABASE 配置完整且可连通。

---

## 项目结构

```text
fzg/
├─ backend/
│  ├─ app.py
│  ├─ knowledge_graph.py
│  ├─ cognitive_diagnosis.py
│  ├─ neo4j_store.py
│  ├─ celery_app.py
│  ├─ requirements.txt
│  ├─ .env.example
│  ├─ start-dev-stack.ps1
│  └─ stop-dev-stack.ps1
├─ frontend/
│  ├─ index.html
│  ├─ dashboard.html
│  ├─ knowledge-map.html
│  ├─ css/
│  └─ js/
└─ data/
```
