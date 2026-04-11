#!/usr/bin/env python3
"""详细功能测试脚本 - 显示实际搜索结果"""

import sys
import json
sys.path.insert(0, '.')

from app.services.knowledge_base import search_kb

print('=' * 70)
print('FAISS 向量检索系统 - 详细功能测试')
print('=' * 70)

test_queries = [
    '函数求导的规则',
    '二次方程解法',
    '圆的周长公式',
    '物理中的加速度定义'
]

test_results = []

for i, query in enumerate(test_queries, 1):
    print(f'\n【测试 {i}】查询: "{query}"')
    print('-' * 70)
    
    try:
        # 调用搜索接口
        result = search_kb(user_id="test_user", query=query, top_k=5)
        
        if result and isinstance(result, dict):
            print(f'  查询状态: {result.get("query", "未知")}')
            print(f'  总文档数: {result.get("total_docs", 0)}')
            
            # 提取并显示知识项
            chunks = result.get("chunks", [])
            print(f'  返回结果数: {len(chunks)}')
            
            if chunks:
                print(f'\n  Top 3 相关结果:')
                for j, chunk in enumerate(chunks[:3], 1):
                    print(f'\n    {j}. 标题: {chunk.get("title", "无标题")[:60]}')
                    print(f'       章节: {chunk.get("chapter", "未分类")}')
                    print(f'       学科: {chunk.get("discipline", "未知")}')
                    print(f'       摘要: {chunk.get("content", "无内容")[:60]}...')
                    print(f'       相关度: {chunk.get("score", 0):.3f}')
                
                test_results.append({
                    'query': query,
                    'status': 'PASS',
                    'result_count': len(chunks),
                    'top_score': chunks[0].get('score', 0) if chunks else 0
                })
            else:
                print(f'  ⚠️ 无返回结果')
                test_results.append({
                    'query': query,
                    'status': 'FAIL',
                    'result_count': 0,
                    'top_score': 0
                })
        else:
            print(f'  ✗ 返回格式异常: {type(result)}')
            test_results.append({
                'query': query,
                'status': 'ERROR',
                'result_count': 0,
                'top_score': 0
            })
            
    except Exception as e:
        print(f'  ✗ 异常错误: {str(e)[:80]}')
        test_results.append({
            'query': query,
            'status': 'ERROR',
            'result_count': 0,
            'top_score': 0
        })

# 输出测试统计
print('\n' + '=' * 70)
print('📊 测试统计')
print('=' * 70)

pass_count = sum(1 for r in test_results if r['status'] == 'PASS')
fail_count = sum(1 for r in test_results if r['status'] != 'PASS')
avg_score = sum(r['top_score'] for r in test_results) / len(test_results) if test_results else 0

print(f'\n  总测试数: {len(test_results)}')
print(f'  通过: {pass_count} ✅')
print(f'  失败: {fail_count}')
print(f'  平均相关度分值: {avg_score:.3f}')

print('\n  详细结果:')
for r in test_results:
    status_icon = '✅' if r['status'] == 'PASS' else '❌'
    print(f'    {status_icon} "{r["query"][:30]}" -> {r["result_count"]} 个结果 (最高分: {r["top_score"]:.3f})')

print('\n' + '=' * 70)
if fail_count == 0:
    print('✨ 所有测试通过 - 系统已准备就绪!')
else:
    print(f'⚠️ 有 {fail_count} 个测试需要关注')
print('=' * 70)
