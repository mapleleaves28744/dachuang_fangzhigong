import os
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# 设定路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pro_kb_dir = os.path.join(backend_dir, "data", "pro_kb")
chunks_file = os.path.join(pro_kb_dir, "pro_kb_chunks.jsonl")
faiss_index_file = os.path.join(pro_kb_dir, "pro_kb_faiss.index")
texts_file = os.path.join(pro_kb_dir, "pro_kb_texts.json")

def build_faiss_kb():
    print(f"[1/4] Loading embedding model 'BAAI/bge-small-zh-v1.5'...")
    try:
        model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
    except Exception as e:
        print(f"Error loading model: {e}")
        return
    
    print(f"[2/4] Reading chunks from {chunks_file}...")
    chunks = []
    if not os.path.exists(chunks_file):
        print(f"Error: Could not find {chunks_file}")
        return

    # 第一遍：读取所有chunk
    with open(chunks_file, "r", encoding="utf-8") as f:
        for line in tqdm(f, desc="Reading chunks", unit=" chunk"):
            line = line.strip()
            if not line: 
                continue
            try:
                data = json.loads(line)
                content = data.get("text", "")
                if not content: 
                    continue
                
                chunks.append({
                    "chunk_id": data.get("chunk_id", data.get("card_id", "")),
                    "knowledge_point": data.get("knowledge_point", "公共知识"),
                    "chapter": data.get("chapter", ""),
                    "discipline": data.get("discipline", ""),
                    "text": content,
                })
            except Exception as e:
                pass

    if not chunks:
        print("No valid chunks found. Aborting.")
        return

    print(f"[3/4] Generating embeddings for {len(chunks)} chunks (this may take several minutes)...")
    texts_to_encode = [c["text"] for c in chunks]
    
    # 批量编码以提高效率
    batch_size = 32
    all_embeddings = []
    for i in tqdm(range(0, len(texts_to_encode), batch_size), desc="Encoding", unit=" batch"):
        batch = texts_to_encode[i:i+batch_size]
        embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(embeddings)
    
    embeddings = np.array(all_embeddings).astype('float32')
    
    dimension = embeddings.shape[1]
    print(f"Embeddings generated with dimension {dimension}. Building FAISS index...")
    
    # 建立 FAISS 索引
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    
    print(f"[4/4] Saving FAISS index to {faiss_index_file}...")
    faiss.write_index(index, faiss_index_file)
    
    print(f"Saving text mappings to {texts_file}...")
    with open(texts_file, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)
        
    print("✓ GraphRAG dense vector knowledge base build complete!")
    print(f"  - Index: {faiss_index_file}")
    print(f"  - Texts: {texts_file}")
    print(f"  - Chunks: {len(chunks)}")
    print(f"  - Dimension: {dimension}")

if __name__ == "__main__":
    build_faiss_kb()
