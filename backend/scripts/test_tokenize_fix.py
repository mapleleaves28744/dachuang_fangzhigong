#!/usr/bin/env python3
"""测试自定义tokenizer是否能解决问题"""

import os
import sys
import json
import pickle
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer

# 定义路径和tokenizer
_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9_]+")
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_CHUNKS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_chunks.jsonl")
_PRO_KB_VECTORIZER_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")
_PRO_KB_MATRIX_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_matrix.npz")

def _tokenize(text: str):
    """中文友好的tokenizer"""
    raw = str(text or "")
    tokens = [t.lower() for t in _TOKEN_PATTERN.findall(raw)]
    
    # 对连续中文片段补充 2-gram
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
    for chunk in cjk_chunks:
        chars = list(chunk)
        if len(chars) == 2:
            tokens.append("".join(chars))
            continue
        for i in range(len(chars) - 1):
            tokens.append("".join(chars[i:i + 2]))
    
    return [t for t in tokens if t]

print("=" * 60)
print("测试修复：自定义tokenizer")
print("=" * 60)

# 加载基础数据
print("\n1️⃣ 加载chunks和vectorizer")
chunks = []
with open(_PRO_KB_CHUNKS_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        line = str(line or "").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("text"):
                chunks.append(row)
        except:
            pass

with open(_PRO_KB_VECTORIZER_FILE, 'rb') as f:
    vectorizer = pickle.load(f)

matrix = load_npz(_PRO_KB_MATRIX_FILE)
print(f"   ✅ 加载了 {len(chunks)} chunks")

# 测试第一种方案：直接用_tokenize结果作为查询
print("\n2️⃣ 测试方案A：手动tokenize查询并转换")
test_queries = ["一次函数", "勾股定理", "方程"]

for query in test_queries:
    print(f"\n   查询: '{query}'")
    
    # 用tokenizer.transform (会失败)
    try:
        q_vec = vectorizer.transform([query])
        print(f"   原始transform: {q_vec.nnz} 非零元素 → 无法分词，相似度全0")
    except Exception as e:
        print(f"   transform异常: {e}")
    
    # 用自定义tokenizer
    tokens = _tokenize(query)
    print(f"   _tokenize结果: {tokens}")
    
    if not tokens:
        print(f"   ⚠️  自定义tokenize也为空!")
        continue
    
    # 将tokens作为文本重新转换
    token_text = " ".join(tokens)
    print(f"   token_text: '{token_text}'")
    
    try:
        q_vec = vectorizer.transform([token_text])
        print(f"   transform后: {q_vec.nnz} 非零元素")
        
        if q_vec.nnz > 0:
            sims = cosine_similarity(q_vec, matrix).ravel()
            import numpy as np
            sims_array = np.array(sims)
            top_idx = np.argmax(sims_array)
            print(f"   ✅ 最高相似度: {sims_array[top_idx]:.6f}")
            print(f"   ✅ 匹配的知识点: {chunks[top_idx].get('knowledge_point', '')}")
        else:
            print(f"   ❌ token_text仍然无法分词")
    except Exception as e:
        print(f"   异常: {e}")

print("\n" + "=" * 60)
