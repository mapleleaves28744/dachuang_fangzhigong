#!/usr/bin/env python3
import os
import sys

knowledge_base_py = r"c:\Users\28744\Desktop\fangwen\fzg\backend\app\services\knowledge_base.py"
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(knowledge_base_py))))
pro_kb_dir = os.path.join(backend_dir, "data", "pro_kb")
faiss_file = os.path.join(pro_kb_dir, "pro_kb_faiss.index")
texts_file = os.path.join(pro_kb_dir, "pro_kb_texts.json")

print("=" * 60)
print("FAISS Load Test")
print("=" * 60)
print("FAISS file exists:", os.path.exists(faiss_file))
print("Texts file exists:", os.path.exists(texts_file))

sys.path.insert(0, r"c:\Users\28744\Desktop\fangwen\fzg\backend")

try:
    import faiss
    import json
    from sentence_transformers import SentenceTransformer
    import numpy as np
    
    print("\nLoading FAISS index...")
    index = faiss.read_index(faiss_file)
    print("FAISS loaded:", index.ntotal, "vectors")
    
    print("Loading texts...")
    with open(texts_file, "r", encoding="utf-8") as f:
        texts = json.load(f)
    print("Texts loaded:", len(texts), "items")
    
    print("\nLoading BGE model...")
    model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
    
    print("\nTesting search...")
    query = "function derivative"
    query_vector = model.encode([query])
    query_vector = np.array(query_vector).astype('float32')
    
    distances, indices = index.search(query_vector, 3)
    print("Search successful!")
    print("Results:", indices[0])
    
except Exception as e:
    print("ERROR:", str(e))
    import traceback
    traceback.print_exc()
