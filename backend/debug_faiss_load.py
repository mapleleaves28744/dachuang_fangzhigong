#!/usr/bin/env python3
"""调试 FAISS 加载路径"""

import os
import sys

# 模拟代码中的路径计算
# knowledge_base.py 位置: c:\Users\28744\Desktop\fangwen\fzg\backend\app\services\knowledge_base.py
# __file__ = knowledge_base.py
# dirname(__file__) = backend/app/services
# dirname(dirname(__file__)) = backend/app
# dirname(dirname(dirname(__file__))) = backend

# 实际的位置
knowledge_base_py = r"c:\Users\28744\Desktop\fangwen\fzg\backend\app\services\knowledge_base.py"

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(knowledge_base_py))))
pro_kb_dir = os.path.join(backend_dir, "data", "pro_kb")

faiss_file = os.path.join(pro_kb_dir, "pro_kb_faiss.index")
texts_file = os.path.join(pro_kb_dir, "pro_kb_texts.json")

print("=" * 70)
print("路径调试信息")
print("=" * 70)
print(f"Knowledge_base.py: {knowledge_base_py}")
print(f"Backend dir: {backend_dir}")
print(f"Pro KB dir: {pro_kb_dir}")
print()
print(f"FAISS file: {faiss_file}")
print(f"  exists: {os.path.exists(faiss_file)}")
print(f"  size: {os.path.getsize(faiss_file) / (1024*1024):.1f} MB" if os.path.exists(faiss_file) else "  N/A")
print()
print(f"Texts file: {texts_file}")
print(f"  exists: {os.path.exists(texts_file)}")
print(f"  size: {os.path.getsize(texts_file) / (1024*1024):.1f} MB" if os.path.exists(texts_file) else "  N/A")
print()

# 直接测试加载
print("=" * 70)
print("测试直接加载 FAISS")
print("=" * 70)

sys.path.insert(0, r"c:\Users\28744\Desktop\fangwen\fzg\backend")

try:
    import faiss
    import json
    
    print("✓ 导入 faiss 和 json 成功")
    
    # 加载索引
    print("\n加载 FAISS 索引...")
    index = faiss.read_index(faiss_file)
    print(f"✓ FAISS 索引加载成功")
    print(f"  索引类型: {type(index)}")
    print(f"  索引大小: {index.ntotal}")
    
    # 加载文本
    print("\n加载文本映射...")
    with open(texts_file, "r", encoding="utf-8") as f:
        texts = json.load(f)
    print(f"✓ 文本映射加载成功")
    print(f"  文本数量: {len(texts)}")
    if texts:
        print(f"  第一条: {texts[0].keys() if isinstance(texts[0], dict) else type(texts[0])}")
    
    # 测试搜索
    print("\n测试搜索...")
    from sentence_transformers import SentenceTransformer
    
    print("  加载 BGE 模型...")
    model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
    print(f"  ✓ 模型加载成功")
    
    query = "函数求导"
    print(f"\n  测试查询: '{query}'")
    query_vector = model.encode([query])
    import numpy as np
    query_vector = np.array(query_vector).astype('float32')
    
    distances, indices = index.search(query_vector, 3)
    print(f"  ✓ 搜索成功")
    print(f"    返回索引: {indices[0]}")
    print(f"    距离: {distances[0]}")
    
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        if idx < len(texts):
            text_item = texts[idx]
            if isinstance(text_item, dict):
                title = text_item.get("knowledge_point", "无标题")[:50]
            else:
                title = str(text_item)[:50]
            print(f"    {i+1}. {title}")
    
except Exception as e:
    import traceback
    print(f"✗ 错误: {e}")
    print(traceback.format_exc())

print("\n" + "=" * 70)
