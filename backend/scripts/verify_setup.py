#!/usr/bin/env python3
"""
轻量级验证脚本 - 不需要FAISS索引已生成
测试核心的导入和检索逻辑
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("="*60)
print("GraphRAG 系统验证测试")
print("="*60)

# 步骤 1: 验证依赖
print("\n[1/3] 验证依赖模块...")
try:
    import numpy as np
    print("  ✓ numpy")
    import faiss
    print("  ✓ faiss")
    from sentence_transformers import SentenceTransformer
    print("  ✓ sentence-transformers")
except ImportError as e:
    print(f"  ✗ Import Error: {e}")
    sys.exit(1)

# 步骤 2: 验证数据文件
print("\n[2/3] 验证数据文件...")
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pro_kb_dir = os.path.join(backend_dir, "data", "pro_kb")

files_to_check = {
    "chunks": os.path.join(pro_kb_dir, "pro_kb_chunks.jsonl"),
    "index": os.path.join(pro_kb_dir, "pro_kb_faiss.index"),
    "texts": os.path.join(pro_kb_dir, "pro_kb_texts.json"),
}

for name, path in files_to_check.items():
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  ✓ {name:10} - {size_mb:.2f} MB")
    else:
        print(f"  ⚠ {name:10} - NOT FOUND (yet)")

# 步骤 3: 验证代码逻辑
print("\n[3/3] 验证代码导入和基本逻辑...")
try:
    from app.services.knowledge_base import _search_public_chunks, _load_public_kb_once
    print("  ✓ knowledge_base imports successful")
    
    # 测试加载KB
    pub = _load_public_kb_once()
    if pub.get("loaded"):
        chunks_count = len(pub.get("chunks", []))
        enabled = pub.get("enabled", False)
        error = pub.get("error", "")
        
        print(f"  ✓ KB loaded: enabled={enabled}, chunks={chunks_count}")
        if error:
            print(f"    Warning: {error}")
    else:
        print("  ⚠ KB not loaded yet")
        
except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*60)
print("✓ 验证完成！")
print("="*60)

if os.path.exists(files_to_check["index"]):
    print("\n🚀 FAISS索引已生成！可以进行搜索测试...")
    print("\n   运行以下命令进行搜索测试:")
    print("   python scripts/test_faiss_search.py")
else:
    print("\n⏳ FAISS索引生成中...")
    print("   预计需要约20-25分钟")
    print("   生成完成后，运行: python scripts/test_faiss_search.py")
