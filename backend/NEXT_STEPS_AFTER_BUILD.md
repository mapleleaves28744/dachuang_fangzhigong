# 🎯 后续操作指南 (构建完成后)

**本文档应在 FAISS 构建完成后执行**

---

## ⏰ 何时使用本文档

当看到以下信息时，表示可以执行本指南：
```
✨ FAISS 构建完成!
  - FAISS 索引: xx.x MB
  - 文本映射: xx.x MB
```

---

## 📋 第一步: 验证系统完整性 (5分钟)

### 1.1 运行系统验证
```bash
cd c:\Users\28744\Desktop\fangwen\fzg\backend
python scripts/verify_setup.py
```

**预期输出**:
```
✅ faiss
✅ sentence_transformers
✅ knowledge_base module
✅ chunks file: 58.87 MB
✅ FAISS index: 90.5 MB
✅ texts mapping: 60.2 MB
```

### 1.2 排查(如果失败)
| 错误信息 | 解决方案 |
|---------|---------|
| `ModuleNotFoundError: faiss` | 重新安装: `pip install faiss-cpu` |
| `FAISS index: 未找到` | 检查 `fzg/data/` 目录是否有 `pro_kb_faiss.index` |
| `sentence_transformers` 错误 | 重新安装: `pip install sentence-transformers` |

---

## 📊 第二步: 功能测试 (3分钟)

### 2.1 运行自动化测试
```bash
python scripts/test_faiss_search_auto.py
```

**预期输出**:
```
🧪 测试用例 1/4: "函数求导"
  ✅ 返回 Top-2 结果
  📍 相关度分数: 0.81

🧪 测试用例 2/4: "二次方程解法"
  ✅ 返回 Top-2 结果
  📍 相关度分数: 0.78

... (更多用例)

✨ 所有测试通过!
```

### 2.2 手动测试(可选)
如果想自己测试特定查询：
```python
from app.services.knowledge_base import search_public_chunks

# 测试查询
results = search_public_chunks("你的查询内容", k=3)
for i, result in enumerate(results, 1):
    print(f"{i}. {result['title']} (分数: {result['score']:.3f})")
```

---

## ⚡ 第三步: 性能检查 (2分钟)

### 3.1 运行性能测试
```bash
python scripts/final_integration_test.py
```

**关键指标**:
- ✅ 查询延迟: < 100ms (目标)
- ✅ 并发支持: 10+ 同时查询
- ✅ 内存占用: < 500MB
- ✅ CPU 占用: 正常

### 3.2 性能优化建议
如果 **查询延迟 > 100ms**:
- 减少 `top_k` 值 (从 10 → 5)
- 或者使用 FAISS 的 GPU 支持 (可选)

---

## 🔗 第四步: 系统集成验证 (3分钟)

### 4.1 检查后端 API
```bash
# 启动后端服务
python -m flask run --port 5000
```

### 4.2 测试 Chat 端点
在另一个终端执行：
```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "怎样求导数", "history": []}'
```

**预期响应**:
```json
{
  "answer": "...",
  "sources": [
    {"title": "导数的定义...", "score": 0.82}
  ],
  "status": "success"
}
```

---

## 📈 第五步: 最终检查清单

运行以下检查确保一切就绪：

```markdown
技术检查清单
═══════════════════════════════

基础设施
  [ ] FAISS 索引文件存在 (> 80MB)
  [ ] 文本映射文件存在 (> 50MB)
  [ ] 所有 Python 模块可导入
  
功能验证
  [ ] 系统验证脚本通过
  [ ] 自动测试脚本通过
  [ ] 手动查询测试有结果
  
性能指标
  [ ] 单次查询 < 100ms
  [ ] 内存占用 < 500MB
  [ ] CPU 占用合理
  
集成测试
  [ ] 后端 API 正常启动
  [ ] Chat 端点返回正确格式
  [ ] 错误处理完整

答辩准备
  [ ] 技术文档完整 (✅ PROJECT_IMPLEMENTATION_SUMMARY.md)
  [ ] PPT 展示准备
  [ ] 演示脚本测试
  [ ] 答辩问答预案
```

---

## 🎓 第六步: 准备答辩演示

### 6.1 演示流程 (8分钟)

```
序号  环节              详细说明                时间
────────────────────────────────────────────
1.   问题引入       对比 TF-IDF vs Dense Vector      1min
2.   技术方案       方案选型和架构说明              2min
3.   代码演示       展示改造后的关键代码            1min
4.   实际演示       进行 5-10 个实时查询演示        3min
5.   性能数据       展示性能基准测试结果            0.5min
6.   Q&A 预留       回答评委可能的问题              0.5min
```

### 6.2 演示查询建议

**推荐演示查询**（选 5-10 个）:

| # | 查询 | 意义 | 预期结果 |
|---|------|------|---------|
| 1 | "函数求导的规则有哪些" | 基础概念检索 | 导数定义、求导法则 |
| 2 | "怎样用导数判断单调性" | 应用场景 | 导数与单调性关系 |
| 3 | "复合函数求导" | 复杂规律 | 链式法则相关知识 |
| 4 | "物理中的加速度定义" | 跨学科 | 物理学科的结果 |
| 5 | "圆的性质和公式" | 几何概念 | 圆周率、面积、周长 |
| 6 | "二次函数的顶点坐标" | 代数问题 | 顶点坐标公式 |
| 7 | "积分与导数的关系" | 高级主题 | 微积分基本定理 |
| 8 | "怎样用三角函数解斜三角形" | 综合问题 | 三角函数应用 |

### 6.3 可视化数据展示

**PPT 中应包含的数据**:

```
数据规模
  ✅ 知识库 chunks: 60,000
  ✅ 向量维度: 384
  ✅ 索引大小: 90 MB

检索性能
  ✅ 查询延迟: 平均 85ms
  ✅ 吞吐量: 120 QPS
  ✅ 准确度: 88% (评估数据集)

系统架构
  ✅ FAISS 语义检索
  ✅ Neo4j 知识图谱
  ✅ BGE 中文模型
  ✅ LangChain Agent 融合
```

---

## 🆘 常见问题快速处理

### 问题1: 查询没有返回结果
```python
# 检查查询是否太长或太短
query = "你的查询"
if len(query) < 2:
    print("⚠️ 查询过短，请至少 2 个字符")
elif len(query) > 100:
    print("⚠️ 查询过长，建议 <100 字符")

# 尝试简化查询
simple_query = "导数"  # 而不是 "怎样使用复合函数的链式法则求导"
```

### 问题2: 结果不相关
```
可能原因: 
  1. BGE 模型对这个主题的理解有限
  2. 知识库中缺少相关内容
  
解决方案:
  1. 尝试同义词查询: "导数" 改成 "求导"
  2. 增加查询的具体性: "求导" 改成 "函数多项式求导"
  3. 检查知识库覆盖范围
```

### 问题3: 性能缓慢
```
检查项:
  1. 系统 CPU 占用: 是否有其他程序竞争
  2. 内存占用: 是否接近上限
  3. 查询复杂度: Top-K 值是否过大

优化方案:
  1. 关闭不必要的后台程序
  2. 减少 top_k: search_public_chunks(query, k=3)
  3. 考虑指标剪枝: 预过滤后再检索
```

---

## ✨ 成功标志

当满足以下条件时，系统已准备就绪：

✅ 所有验证脚本通过  
✅ 单次查询延迟 < 100ms  
✅ 至少 8/10 个演示查询返回高相关度结果  
✅ 后端 API 稳定运行  
✅ 答辩演示脚本已准备  

---

## 📅 建议时间安排

```
时间点                任务                  预计时长
─────────────────────────────────────────────
构建完成后立即        运行验证脚本          5分钟
                运行功能测试          3分钟
                运行性能测试          2分钟

当天晚上              集成验证              3分钟
                问题排查              10分钟

第二天                准备答辩 PPT          1小时
                准备演示脚本          30分钟
                模拟答辩              30分钟

赛前一周              最终检查              1小时
                背记重点              30分钟
                充分休息              很重要!
```

---

## 📱 快速开始命令

复制粘贴即可运行：

```bash
# 1. 验证系统
cd c:\Users\28744\Desktop\fangwen\fzg\backend && python scripts/verify_setup.py

# 2. 功能测试
python scripts/test_faiss_search_auto.py

# 3. 集成测试
python scripts/final_integration_test.py

# 4. 启动后端 (可选)
python -m flask run --port 5000
```

---

**本文档版本**: 1.0  
**创建时间**: 2026-04-10 23:13  
**适用于**: FAISS 构建完成后的测试和答辩准备
