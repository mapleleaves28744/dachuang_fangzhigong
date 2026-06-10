#!/usr/bin/env python3
"""诊断知识库搜索为什么返回0结果"""

import os
import sys
import json
import pickle

# 添加backend目录到path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity

# 定义路径
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_CHUNKS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_chunks.jsonl")
_PRO_KB_VECTORIZER_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")
_PRO_KB_MATRIX_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_matrix.npz")

print("=" * 60)
print("知识库诊断")
print("=" * 60)

print(f"\n1️⃣ 检查文件是否存在")
print(f"   chunks file: {os.path.exists(_PRO_KB_CHUNKS_FILE)} ({_PRO_KB_CHUNKS_FILE})")
print(f"   vectorizer: {os.path.exists(_PRO_KB_VECTORIZER_FILE)}")
print(f"   matrix: {os.path.exists(_PRO_KB_MATRIX_FILE)}")

print(f"\n2️⃣ 加载chunks文件")
chunks = []
try:
    with open(_PRO_KB_CHUNKS_FILE, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            line = str(line or "").strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    text = row.get("text", "")
                    if text:
                        chunks.append(row)
            except Exception as e:
                if i < 3:
                    print(f"   ⚠️  第{i}行解析失败: {e}")
    print(f"   ✅ 加载了 {len(chunks)} 条chunks")
    if chunks:
        print(f"   📝 样本chunk字段: {list(chunks[0].keys())}")
except Exception as e:
    print(f"   ❌ 加载chunks失败: {e}")
    exit(1)

print(f"\n3️⃣ 加载TF-IDF vectorizer")
try:
    with open(_PRO_KB_VECTORIZER_FILE, 'rb') as f:
        vectorizer = pickle.load(f)
    print(f"   ✅ Vectorizer加载成功")
    print(f"   词汇量: {len(vectorizer.get_feature_names_out())}")
except Exception as e:
    print(f"   ❌ 加载vectorizer失败: {e}")
    exit(1)

print(f"\n4️⃣ 加载TF-IDF矩阵")
try:
    matrix = load_npz(_PRO_KB_MATRIX_FILE)
    print(f"   ✅ 矩阵加载成功")
    print(f"   矩阵形状: {matrix.shape}")
    print(f"   chunks数量: {len(chunks)}")
    if matrix.shape[0] != len(chunks):
        print(f"   ⚠️  矩阵行数({matrix.shape[0]}) 与 chunks数量({len(chunks)}) 不匹配!")
except Exception as e:
    print(f"   ❌ 加载矩阵失败: {e}")
    exit(1)

print(f"\n5️⃣ 测试查询转换")
test_query = "一次函数"
try:
    print(f"   测试查询: '{test_query}'")
    q_vec = vectorizer.transform([test_query])
    print(f"   ✅ 查询向量化成功")
    print(f"   查询向量形状: {q_vec.shape}")
    print(f"   查询向量非零元素: {q_vec.nnz}")
    
    if q_vec.nnz == 0:
        print(f"   ⚠️  查询向量全为0! 查询可能不在词汇表中")
    
except Exception as e:
    print(f"   ❌ 向量化查询失败: {e}")
    exit(1)

print(f"\n6️⃣ 计算相似度")
try:
    sims = cosine_similarity(q_vec, matrix).ravel()
    print(f"   ✅ 计算相似度成功")
    print(f"   相似度向量长度: {len(sims)}")
    
    # 统计信息
    import numpy as np
    sims_array = np.array(sims)
    print(f"   最大相似度: {sims_array.max():.6f}")
    print(f"   最小相似度: {sims_array.min():.6f}")
    print(f"   平均相似度: {sims_array.mean():.6f}")
    print(f"   > 0的相似度数: {np.sum(sims_array > 0)}")
    print(f"   == 0的相似度数: {np.sum(sims_array == 0)}")
    
    # 显示top 5
    top_indices = np.argsort(-sims)[:5]
    print(f"\n   📊 Top 5结果:")
    for rank, idx in enumerate(top_indices):
        score = sims[idx]
        chunk = chunks[idx]
        chunk_text = chunk.get("text", "")[:100]
        chunk_title = chunk.get("knowledge_point", "")
        print(f"      #{rank+1}: score={score:.6f}, title='{chunk_title}', text='{chunk_text}...'")
    
except Exception as e:
    print(f"   ❌ 计算相似度失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print(f"\n7️⃣ 检查查询与矩阵兼容性")
try:
    # 尝试用矩阵中的某个向量测试
    if matrix.shape[0] > 0:
        first_row = matrix[0]
        print(f"   第一个矩阵行的非零元素: {first_row.nnz}")
        print(f"   第一个矩阵行的形状: {first_row.shape}")
except Exception as e:
    print(f"   ⚠️  检查失败: {e}")

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
