#!/usr/bin/env python3
"""深入分析vectorizer的tokenizer问题"""

import os
import sys
import json
import pickle
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_CHUNKS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_chunks.jsonl")
_PRO_KB_VECTORIZER_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")

print("=" * 70)
print("分析Vectorizer的词汇表和tokenizer")
print("=" * 70)

# 加载chunks
chunks = []
with open(_PRO_KB_CHUNKS_FILE, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        line = str(line or "").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("text"):
                chunks.append(row)
                if len(chunks) == 1:
                    print(f"\n📄 第一个chunk的text字段(前300字符):")
                    print(row.get("text", "")[:300])
        except:
            pass

print(f"\n✅ 加载了 {len(chunks)} 条chunks\n")

# 加载vectorizer
with open(_PRO_KB_VECTORIZER_FILE, 'rb') as f:
    vectorizer = pickle.load(f)

print(f"Vectorizer配置:")
print(f"  - max_features: {vectorizer.max_features}")
print(f"  - ngram_range: {vectorizer.ngram_range}")
print(f"  - min_df: {vectorizer.min_df}")
print(f"  - lowercase: {vectorizer.lowercase}")
print(f"  - token_pattern: {vectorizer.token_pattern}")
print(f"  - analyzer: {vectorizer.analyzer}")
print(f"  - tokenizer: {vectorizer.tokenizer}")

features = vectorizer.get_feature_names_out()
print(f"\n词汇表大小: {len(features)}")

# 查看词汇表中的样本
print(f"\n📝 词汇表中的前20个token:")
for i, feat in enumerate(features[:20]):
    print(f"  {i+1:3d}. '{feat}'")

# 查看是否包含中文
chinese_count = 0
for feat in features:
    if any('\u4e00' <= c <= '\u9fff' for c in feat):
        chinese_count += 1

print(f"\n🔍 中文token统计:")
print(f"  - 总词汇: {len(features)}")
print(f"  - 包含中文的token: {chinese_count}")
print(f"  - 纯中文token的比例: {100*chinese_count/len(features):.1f}%")

# 查看是否有特定的词
test_terms = ['一次', '函数', '勾股', '定理', '方程']
print(f"\n🔎 查找特定中文词:")
for term in test_terms:
    if term in features:
        idx = list(features).index(term)
        print(f"  ✅ '{term}' 在词汇表中 (位置 {idx})")
    else:
        print(f"  ❌ '{term}' 不在词汇表中")

# 测试一个真实的chunk text如何被tokenize
print(f"\n🧪 下面测试vectorizer如何tokenize真实的chunk text:")
if chunks:
    sample_text = chunks[0].get("text", "")[:200]
    print(f"   样本文本: {sample_text}")
    
    # 手动调用vectorizer的tokenizer
    try:
        # 获取分析器
        analyzer = vectorizer.build_analyzer()
        tokens = analyzer(sample_text)
        print(f"\n   Analyzer得到的tokens: {list(tokens)[:20]}")
    except Exception as e:
        print(f"   错误: {e}")
