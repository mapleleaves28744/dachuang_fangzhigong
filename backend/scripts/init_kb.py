#!/usr/bin/env python3
"""
知识库初始化和加载脚本
目标：确保pro_kb被正确加载到内存
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# 初始化知识库
print("正在初始化知识库...")

try:
    from app.services import knowledge_base
    
    # 强制加载公开知识库
    print("\n1️⃣  加载公开知识库...")
    kb_state = knowledge_base._load_public_kb_once()
    
    print(f"   - 加载结果: {kb_state.get('loaded')}")
    print(f"   - 启用状态: {kb_state.get('enabled')}")
    print(f"   - 数据块数: {len(kb_state.get('chunks', []))}")
    matrix = kb_state.get('matrix')
    print(f"   - 矢量化: {'已完成' if matrix is not None else '未完成'}")
    print(f"   - 错误信息: {kb_state.get('error', '无')}")
    
    if not kb_state.get('enabled'):
        print(f"\n   ⚠️  警告: 公开知识库未启用")
        print(f"   原因: {kb_state.get('error')}")
    else:
        print(f"\n   ✅ 公开知识库已启用")
    
    # 测试搜索
    print("\n2️⃣  测试知识库检索...")
    
    test_queries = [
        "一次函数",
        "勾股定理",
        "方程组",
    ]
    
    for query in test_queries:
        print(f"\n   查询: '{query}'")
        try:
            result = knowledge_base.search_kb(
                user_id="init_test",
                query=query,
                top_k=3
            )
            
            hits = result.get("hits", [])
            print(f"   - 结果数: {len(hits)}")
            if hits:
                print(f"   - 第一条: {hits[0].get('title', 'N/A')[:50]}...")
            else:
                print(f"   - 无结果")
                
        except Exception as e:
            print(f"   - 错误: {e}")
    
    print("\n✅ 知识库初始化完成")

except Exception as e:
    print(f"❌ 初始化失败: {e}")
    import traceback
    traceback.print_exc()
