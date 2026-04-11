#!/usr/bin/env python3
"""快速功能测试脚本"""

import sys
sys.path.insert(0, '.')

from app.services.knowledge_base import search_kb

print('=' * 60)
print('FAISS 向量检索快速测试')
print('=' * 60)

test_queries = [
    '函数求导的规则',
    '二次方程解法',
    '圆的周长公式',
    '物理中的加速度定义'
]

passed = 0
failed = 0

for i, query in enumerate(test_queries, 1):
    print(f'\n【测试 {i}】查询: "{query}"')
    try:
        # 使用测试用户 ID
        results = search_kb(user_id="test_user", query=query, top_k=2)
        if results and len(results) > 0:
            print(f'  ✓ 返回 {len(results)} 个结果:')
            # 处理实际的结果格式
            for j, result in enumerate(results, 1):
                if isinstance(result, dict):
                    title = result.get('title', '无标题')[:50]
                    score = result.get('score', 0)
                    print(f'    {j}. {title}... (分值: {score:.3f})')
                else:
                    print(f'    {j}. {str(result)[:50]}...')
                if j >= 2:
                    break
            passed += 1
        else:
            print(f'  ✗ 无返回结果')
            failed += 1
    except Exception as e:
        import traceback
        print(f'  ✗ 错误: {str(e)[:60]}')
        print(f'    详情: {traceback.format_exc()[:200]}')
        failed += 1

print('\n' + '=' * 60)
print(f'测试统计: {passed} 通过 / {failed} 失败')
if failed == 0:
    print('✅ 所有测试通过!')
else:
    print(f'⚠️ 有 {failed} 个测试失败')
print('=' * 60)
