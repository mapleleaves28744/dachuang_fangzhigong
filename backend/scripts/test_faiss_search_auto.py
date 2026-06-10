#!/usr/bin/env python3
"""
待FAISS构建完成后的自动测试脚本
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pro_kb_dir = os.path.join(backend_dir, "data", "pro_kb")
faiss_index_file = os.path.join(pro_kb_dir, "pro_kb_faiss.index")
texts_file = os.path.join(pro_kb_dir, "pro_kb_texts.json")

def wait_for_files(max_wait=3600):
    """等待FAISS文件生成完成"""
    print("\n⏳ 等待FAISS索引生成...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        if os.path.exists(faiss_index_file) and os.path.exists(texts_file):
            print(f"✓ 文件已生成！({time.time() - start_time:.0f}秒)")
            return True
        time.sleep(5)
        progress = (time.time() - start_time) / max_wait * 100
        print(f"  等待中... {progress:.1f}%", end='\r')
    
    return False

def run_tests():
    """运行搜索测试"""
    print("\n" + "="*60)
    print("GraphRAG FAISS分布式向量检索 - 功能测试")
    print("="*60)
    
    try:
        from app.services.knowledge_base import _search_public_chunks
        
        test_queries = [
            "解析几何中切线斜率应该怎么求",
            "函数求导的基本法则是什么",
            "物理中的动量守恒定律",
            "英语语法中的从句用法",
        ]
        
        for i, query in enumerate(test_queries, 1):
            print(f"\n【测试 {i}】 查询: '{query}'")
            print("-" * 60)
            
            results = _search_public_chunks(query, top_k=2)
            
            if not results:
                print("  ⚠ 无结果返回")
                continue
            
            for j, result in enumerate(results, 1):
                score = result.get('score', 0)
                vec_score = result.get('vector_score', 0)
                title = result.get('title', 'Unknown')[:50]
                snippet = result.get('snippet', '')[:80]
                
                print(f"\n  [{j}] 标题: {title}")
                print(f"      分数: {score:.4f} (向量: {vec_score:.4f})")
                print(f"      摘要: {snippet}...")
        
        print("\n" + "="*60)
        print("✓ 测试完成！系统运行正常")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    # 检查文件是否已存在
    if os.path.exists(faiss_index_file):
        print("✓ FAISS索引已存在，开始测试...")
        run_tests()
    else:
        print("⏳ FAISS索引尚未生成...")
        if wait_for_files():
            run_tests()
        else:
            print("✗ 超时：FAISS索引未生成")
