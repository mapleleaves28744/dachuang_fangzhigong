# Cloud Quickstart（队友一页版）

适用场景：

- 代码运行在云服务器
- 你在本机（Windows/Mac）通过端口转发访问页面

## 1. 云服务器准备

```bash
cd /path/to/dachuang_fangzhigong
cd backend
python3 -m pip install -r requirements.txt
cd ..
```

## 2. 配置环境变量

编辑 backend/.env，最少确保：

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=你的密钥
STORAGE_BACKEND=sql
DATABASE_URL=sqlite:///data/fzg.db
```

如果你要开启图谱云存储，再补 Neo4j Aura 参数。

## 3. 启动项目（推荐单端口）

```bash
chmod +x start-dev-stack.sh stop-dev-stack.sh check-dev-stack.sh
./start-dev-stack.sh
```

默认是单端口模式：前端由后端托管，只依赖 5000。

## 4. 自检（必须）

```bash
./check-dev-stack.sh
```

看到 All checks passed 才算启动成功。

## 5. 本机端口转发

只转发一个端口：

- 云服务器 5000 -> 本机 5000（或本机任意端口）

浏览器打开：

- http://127.0.0.1:5000/index.html
- http://127.0.0.1:5000/dashboard.html
- http://127.0.0.1:5000/knowledge-map.html

## 6. 常见问题

1. 页面显示“后端离线”
- 先 Ctrl+F5 强刷
- 再开无痕窗口访问
- 确认你访问的是 5000 端口地址，不是 5501

2. 问答失败
- 先执行 ./check-dev-stack.sh
- 再看 backend/.env 的 AI 配置是否完整
- 检查 QWEN_API_KEY 是否有效

3. 启动失败
- 看日志目录 .logs/
- 重点查看 .logs/backend.log 和 .logs/celery.log

## 7. 停止项目

```bash
./stop-dev-stack.sh
```

## 8. 可选：启动 5501 静态前端

只有本地双端口调试才需要：

```bash
START_FRONTEND_5501=true ./start-dev-stack.sh
```
