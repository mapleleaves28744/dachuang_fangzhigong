# 坊知工 FZG

面向学习场景的智能学习伴侣项目，包含后端 API、前端页面、知识图谱、学习诊断与推荐能力。

快速入口：

- 云服务器一页启动指南：见 `CLOUD_QUICKSTART.md`

## 1. 第一次启动：需要先配置什么环境

### 1.1 必需环境

- Windows 10/11（当前脚本按 Windows 编写）
- Python 3.10+
- `pip`

### 1.2 建议环境（用于“完整功能”）

- Redis（异步任务队列）
- Celery（后台任务执行）
- Neo4j Aura（图谱云存储）
- 可用的 AI Key（例如 Qwen）

重要说明：

- 使用 Neo4j Aura 时，不需要安装本地 Neo4j 服务端。
- 本地只需要安装 Python `neo4j` 驱动（`pip install neo4j`，`requirements.txt` 已包含）。

### 1.3 安装后端依赖

在项目根目录执行：

```powershell
cd backend
python -m pip install -r requirements.txt
```

### 1.4 准备环境变量

在 `backend` 目录创建 `.env`（可从 `.env.example` 复制后修改）。

推荐“完整功能”配置示例：

```env
# AI
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=your_api_key
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus

# OCR
OCR_PROVIDER=mock

# 存储（当前项目建议 sql + sqlite）
STORAGE_BACKEND=sql
DATABASE_URL=sqlite:///data/fzg.db

# 图谱
USE_NEO4J=auto
NEO4J_URI=neo4j+s://<your-aura>.databases.neo4j.io
NEO4J_USERNAME=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>

# 图谱读取/写回策略
GRAPH_PRIMARY=auto
GRAPH_SYNC_MODE=auto
```

说明：

- `USE_NEO4J=auto` 时，配置完整且可连通才启用 Aura。
- 使用 Aura 时，无需本地安装 Neo4j 数据库。
- Redis/Celery 不可用时，后端会回退同步流程，但不是“完整异步功能”。

---

## 2. 如何启动整个项目（完整功能）

### 2.1 一键启动（推荐）

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File backend/start-dev-stack.ps1
```

该脚本会尝试启动：

- Redis（6379）
- Celery Worker
- Backend（5000）
- Frontend（5501）

### 2.2 一键停止

```powershell
powershell -ExecutionPolicy Bypass -File backend/stop-dev-stack.ps1
```

### 2.3 Linux 一键启动（新增）

在项目根目录执行：

```bash
chmod +x start-dev-stack.sh stop-dev-stack.sh
./start-dev-stack.sh
```

默认是“单端口模式”（推荐远程开发）：

- 只依赖后端 `5000` 端口
- 后端会直接托管前端页面（`/index.html`、`/dashboard.html`、`/knowledge-map.html`）
- 适合云服务器 + 本机端口转发场景，避免前后端双端口错配导致“后端离线”

如果你确实需要额外启动前端静态服务 `5501`，可执行：

```bash
START_FRONTEND_5501=true ./start-dev-stack.sh
```

Linux 一键脚本会尝试启动：

- Redis（6379）
- Celery Worker
- Backend（5000）
- Frontend（5501，可选，默认不启动）

停止命令：

```bash
./stop-dev-stack.sh
```

可选：启动后自动自检（健康检查 + 前端页面 + 问答接口）

```bash
chmod +x check-dev-stack.sh
./check-dev-stack.sh
```

### 2.4 手动启动（不使用一键脚本）

如果你的队友不想使用一键脚本，可以按下面步骤手动启动。

步骤 1：进入项目根目录

```powershell
cd fzg
```

步骤 2：安装依赖（首次或依赖更新后执行）

```powershell
cd backend
python -m pip install -r requirements.txt
cd ..
```

步骤 3：准备 `.env`

- 在 `backend` 目录创建 `.env`（可复制 `.env.example` 后修改）。
- 最低可运行建议：`STORAGE_BACKEND=sql`、`DATABASE_URL=sqlite:///data/fzg.db`。
- 想启用完整功能时，再补充 Neo4j Aura、AI Key、Redis/Celery 相关配置。

步骤 4（可选）：启动 Redis（完整异步功能需要）

```powershell
cd backend
tools\redis\redis-server.exe tools\redis\redis.windows.conf --port 6379
```

说明：该命令会占用当前终端。建议新开一个终端窗口运行。

步骤 5（可选）：启动 Celery Worker（完整异步功能需要）

```powershell
cd backend
$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'
$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'
python -m celery -A app.celery_client worker -l info -P solo
```

说明：该命令也会占用当前终端，建议在另一个终端窗口运行。

步骤 6：启动后端 API

```powershell
python backend/app.py
```

步骤 7：启动前端静态服务（再开一个终端）

```powershell
python -m http.server 5501 --directory frontend
```

步骤 8：验证运行状态

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

健康检查判断：

- 最低可运行：`status=ok`。
- 完整功能：`status=ok` 且 `celery_enabled=true`、`neo4j_enabled=true`。

### 2.5 验证是否“完整功能”启动成功

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

重点看：

- `status` 应为 `ok`
- `celery_enabled` 应为 `true`
- `neo4j_enabled` 应为 `true`
- `storage_backend` 应为 `sql`
- `database_scheme` 应为 `sqlite`（或你配置的 MySQL）

补充：

- 你只要看到 `neo4j_enabled=true`，就说明已成功连接 Aura，不需要本地 Neo4j。

### 2.6 前端访问

推荐（云服务器/端口转发）：

- 首页: http://127.0.0.1:5000/index.html
- 仪表盘: http://127.0.0.1:5000/dashboard.html
- 知识图谱页: http://127.0.0.1:5000/knowledge-map.html

可选（本地双端口开发）：

- 首页: http://127.0.0.1:5501/index.html
- 仪表盘: http://127.0.0.1:5501/dashboard.html
- 知识图谱页: http://127.0.0.1:5501/knowledge-map.html

### 2.7 前端显示“后端离线”的处理

如果后端实际在线，但页面仍显示“后端离线”，通常是前端请求地址与当前访问主机不一致导致。

当前版本已支持自动按页面主机推断后端地址，并支持手动覆盖：

- 方式 1（推荐）：在页面 URL 添加 `api_base` 参数
  - 示例：`http://<你的前端地址>:5501/index.html?api_base=http://<你的后端地址>:5000`
- 方式 2：在浏览器本地存储写入 `fangzhigong_api_base`

说明：

- 当你通过远程主机、端口转发或非本机浏览器访问页面时，不要把后端固定写成 `127.0.0.1`。

### 2.8 队友云服务启动指南（推荐）

适用场景：

- 代码在云服务器运行
- 本机（Windows/Mac）通过端口转发查看页面

步骤 1：在云服务器拉取代码并安装依赖

```bash
cd /path/to/dachuang_fangzhigong
cd backend
python3 -m pip install -r requirements.txt
cd ..
```

步骤 2：配置 `backend/.env`

- 必填：`USE_REAL_AI=true`、`AI_PROVIDER=qwen`、`QWEN_API_KEY=...`
- 建议：`STORAGE_BACKEND=sql`、`DATABASE_URL=sqlite:///data/fzg.db`
- 若启用图谱：补齐 Neo4j Aura 配置

步骤 3：启动（单端口模式）

```bash
chmod +x start-dev-stack.sh stop-dev-stack.sh check-dev-stack.sh
./start-dev-stack.sh
```

步骤 4：执行自检

```bash
./check-dev-stack.sh
```

步骤 5：只转发一个端口到本机

- 仅转发云服务器 `5000` 到本机 `5000`（或任意本机端口）
- 浏览器打开：`http://<本机转发端口>/index.html`

步骤 6：如果页面仍显示旧状态

- 强制刷新（Ctrl+F5）
- 或开无痕窗口重新访问

停止命令：

```bash
./stop-dev-stack.sh
```

---

## 3. 项目整体介绍

## 3.1 项目目标

坊知工希望提供一体化学习支持：

- 智能问答
- 学习行为记录
- 知识点抽取与关系构建
- 错题认知诊断
- 学习画像与推荐
- 复习提醒

## 3.2 目录结构

```text
fzg/
  backend/    # Flask API、任务调度、数据存储、图谱同步
  frontend/   # 页面与前端脚本
  data/       # 本地数据文件（历史/导出）
```

## 3.3 后端核心模块

- `backend/app.py`：主 API 服务与业务编排入口
- `backend/database.py`：JSON/SQL 双存储抽象
- `backend/neo4j_store.py`：Neo4j Aura 读写
- `backend/cognitive_diagnosis.py`：错题诊断
- `backend/learning_profile.py`：学习画像与推荐
- `backend/scripts/sync_local_state_to_neo4j_aura.py`：以本地数据为准同步 Aura

## 3.4 关键能力说明

- 问答后可触发知识抽取与图谱同步
- 图谱同步支持异步任务（Celery）与同步回退
- 删除知识点支持同步到 Aura，并有重试与日志机制
- 推荐基于画像、掌握度与诊断证据生成

---

## 4. 常见问题

### 4.1 启动后 `neo4j_enabled=false`

- 检查 `.env` 里的 Neo4j 连接信息是否正确
- 检查网络是否可访问 Aura
- 检查 Python 环境是否安装 `neo4j` 包
- 不需要下载安装本地 Neo4j 服务端

### 4.2 启动后 `celery_enabled=false`

- 检查 Redis 是否启动并监听 6379
- 检查 worker 进程是否运行

### 4.3 Aura 数据比本地多

执行一次本地权威同步：

```powershell
cd backend
python scripts/sync_local_state_to_neo4j_aura.py
```

该脚本会删除 Aura 中本地不存在的用户图谱数据，并按本地状态重建。
