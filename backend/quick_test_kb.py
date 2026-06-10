#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.services.knowledge_base import search_kb

queries = ['一次函数', '勾股定理', '方程', '二次函数', '三角函数', '因式分解', '反函数']
print('简化测试：单个核心词汇')
print('=' * 50)

for q in queries:
    result = search_kb('test', q, 1)
    hits = result.get('hits', [])
    if hits:
        print(f'✅ {q:12} -> {hits[0].get("title", "N/A")[:40]}')
    else:
        print(f'❌ {q:12} -> 无结果')
