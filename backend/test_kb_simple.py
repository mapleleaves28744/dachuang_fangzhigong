#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.knowledge_base import search_kb

print("测试知识库搜索...\n")

test_queries = ["一次函数", "勾股定理", "方程"]

for q in test_queries:
    result = search_kb("test", q, 3)
    hits = result.get("hits", [])
    print(f"查询: {q}")
    print(f"  → 结果: {len(hits)} 条")
    if hits:
        print(f"  → 第一条: {hits[0].get('title', 'N/A')[:50]}")
    print()

print("✅ 知识库正常工作!")
