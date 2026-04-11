#!/usr/bin/env python3
"""合并chunks并重新训练vectorizer"""

import os
import sys
import json
import pickle

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_CHUNKS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_chunks.jsonl")
_PRO_KB_VECTORIZER_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")
_PRO_KB_MATRIX_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_matrix.npz")
_ADDITIONAL_CHUNKS_FILE = os.path.join(_PRO_KB_DIR, "additional_chunks.jsonl")

print("=" * 70)
print("步骤1: 加载原始chunks")
print("=" * 70)

chunks = []
with open(_PRO_KB_CHUNKS_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        line = str(line or "").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                chunks.append(row)
        except:
            pass

print(f"✅ 加载了 {len(chunks)} 条原始chunks")

print("\n" + "=" * 70)
print("步骤2: 添加额外的数学基础chunks")
print("=" * 70)

if os.path.exists(_ADDITIONAL_CHUNKS_FILE):
    with open(_ADDITIONAL_CHUNKS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = str(line or "").strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    chunks.append(row)
            except Exception as e:
                print(f"   ⚠️  解析失败: {e}")

    print(f"✅ 添加后总共有 {len(chunks)} 条chunks")
else:
    print(f"⚠️  没有找到 {_ADDITIONAL_CHUNKS_FILE}")

print("\n" + "=" * 70)
print("步骤3: 重新训练vectorizer和矩阵")
print("=" * 70)

chunk_texts = []
for chunk in chunks:
    text = chunk.get("text", "")
    if text:
        chunk_texts.append(text)

print(f"有效的chunks文本数: {len(chunk_texts)}")

vectorizer = TfidfVectorizer(max_features=12000, ngram_range=(1, 2), min_df=1)
chunk_matrix = vectorizer.fit_transform(chunk_texts)

print(f"✅ Vectorizer训练完成")
print(f"   词汇表大小: {len(vectorizer.get_feature_names_out())}")
print(f"   矩阵形状: {chunk_matrix.shape}")

# 检查新词汇表中是否包含我们添加的词
test_terms = ['一次函数', '一次', '函数', '勾股定理', '勾股', '定理', '方程']
print(f"\n🔎 检查词汇表中是否包含目标词:")
features = vectorizer.get_feature_names_out()
for term in test_terms:
    if term in features:
        print(f"   ✅ '{term}' 在词汇表中")
    else:
        print(f"   ❌ '{term}' 不在词汇表中")

print("\n" + "=" * 70)
print("步骤4: 保存更新后的artifacts")
print("=" * 70)

# 保存更新后的chunks
with open(_PRO_KB_CHUNKS_FILE, 'w', encoding='utf-8') as f:
    for chunk in chunks:
        f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

# 保存vectorizer
with open(_PRO_KB_VECTORIZER_FILE, 'wb') as f:
    pickle.dump(vectorizer, f)

# 保存矩阵
save_npz(_PRO_KB_MATRIX_FILE, chunk_matrix)

print(f"✅ 已保存 {len(chunks)} 条chunks到 {_PRO_KB_CHUNKS_FILE}")
print(f"✅ 已保存vectorizer到 {_PRO_KB_VECTORIZER_FILE}")
print(f"✅ 已保存矩阵到 {_PRO_KB_MATRIX_FILE}")

print("\n" + "=" * 70)
print("步骤5: 快速测试")
print("=" * 70)

test_queries = ["一次函数", "勾股定理", "方程"]
for query in test_queries:
    q_vec = vectorizer.transform([query])
    if q_vec.nnz > 0:
        sims = cosine_similarity(q_vec, chunk_matrix).ravel()
        import numpy as np
        sims_array = np.array(sims)
        top_idx = np.argmax(sims_array)
        print(f"✅ '{query}' -> 相似度 {sims_array[top_idx]:.4f}, 匹配: {chunks[top_idx].get('knowledge_point', '')}")
    else:
        print(f"❌ '{query}' -> 无法分词")

print("\n" + "=" * 70)
print("✅ 知识库重建完成!")
print("=" * 70)
