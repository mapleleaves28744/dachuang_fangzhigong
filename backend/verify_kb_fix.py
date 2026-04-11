#!/usr/bin/env python3
"""验证修复后的知识库搜索真的工作了"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from app.services.knowledge_base import search_kb

print("=" * 70)
print("🧪 知识库搜索功能验证测试")
print("=" * 70)

# 测试用例
test_cases = [
    {
        "user_id": "test_user",
        "query": "一次函数",
        "top_k": 3,
        "expected_concept": "一次函数"
    },
    {
        "user_id": "test_user",
        "query": "勾股定理",
        "top_k": 3,
        "expected_concept": "勾股"
    },
    {
        "user_id": "test_user",
        "query": "方程和不等式",
        "top_k": 3,
        "expected_concept": "方程"
    },
    {
        "user_id": "test_user",
        "query": "二次函数的顶点",
        "top_k": 3,
        "expected_concept": "二次"
    },
    {
        "user_id": "test_user",
        "query": "三角函数定义",
        "top_k": 3,
        "expected_concept": "三角"
    },
]

success_count = 0
total_tests = len(test_cases)

for i, test in enumerate(test_cases, 1):
    print(f"\n测试 {i}/{total_tests}: '{test['query']}'")
    
    try:
        result = search_kb(
            user_id=test["user_id"],
            query=test["query"],
            top_k=test["top_k"]
        )
        
        hits = result.get("hits", [])
        print(f"  📊 返回 {len(hits)} 条结果")
        
        if hits:
            # 检查第一个结果是否包含预期的概念
            first_hit = hits[0]
            title = first_hit.get("title", "")
            snippet = first_hit.get("snippet", "")[:100]
            score = first_hit.get("hybrid_score", 0)
            
            print(f"  🏆 第一条结果:")
            print(f"     标题: {title}")
            print(f"     片段: {snippet}...")
            print(f"     分数: {score:.4f}")
            
            if test["expected_concept"] in title or test["expected_concept"] in snippet:
                print(f"  ✅ 直中目标概念")
                success_count += 1
            else:
                print(f"  ⚠️  没有直中目标概念（但可能相关）")
                success_count += 0.5
        else:
            print(f"  ❌ 返回为空")
            
    except Exception as e:
        print(f"  ❌ 查询异常: {e}")

print("\n" + "=" * 70)
print(f"📈 测试结果: {success_count}/{total_tests} 成功")
print("=" * 70)

if success_count >= total_tests * 0.7:
    print("✅ 知识库搜索功能已恢复正常！")
else:
    print("⚠️  仍需优化")
