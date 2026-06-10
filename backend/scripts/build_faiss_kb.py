import argparse
import json
import os
import pickle

import faiss
import numpy as np
from scipy.sparse import load_npz
from tqdm import tqdm


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRO_KB_DIR = os.path.join(BACKEND_DIR, "data", "pro_kb")
CHUNKS_FILE = os.path.join(PRO_KB_DIR, "pro_kb_chunks.jsonl")
FAISS_INDEX_FILE = os.path.join(PRO_KB_DIR, "pro_kb_faiss.index")
FAISS_META_FILE = os.path.join(PRO_KB_DIR, "pro_kb_faiss_meta.json")
TEXTS_FILE = os.path.join(PRO_KB_DIR, "pro_kb_texts.json")
TFIDF_VECTORIZER_FILE = os.path.join(PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")
TFIDF_MATRIX_FILE = os.path.join(PRO_KB_DIR, "pro_kb_tfidf_matrix.npz")


def load_chunks():
    print(f"[1/4] Reading chunks from {CHUNKS_FILE}...")
    chunks = []
    if not os.path.exists(CHUNKS_FILE):
        raise FileNotFoundError(f"Could not find {CHUNKS_FILE}")

    with open(CHUNKS_FILE, "r", encoding="utf-8") as file_obj:
        for line in tqdm(file_obj, desc="Reading chunks", unit="chunk"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            content = str(data.get("text") or "").strip()
            if not content:
                continue

            chunks.append(
                {
                    "chunk_id": data.get("chunk_id", data.get("card_id", "")),
                    "knowledge_point": data.get("knowledge_point", "公共知识"),
                    "chapter": data.get("chapter", ""),
                    "discipline": data.get("discipline", ""),
                    "chunk_type": data.get("chunk_type", "chunk"),
                    "tags": data.get("tags", []) if isinstance(data.get("tags", []), list) else [],
                    "text": content,
                }
            )

    if not chunks:
        raise RuntimeError("No valid chunks found. Aborting.")

    return chunks


def try_load_sentence_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(model_name, local_files_only=True)
    except TypeError:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return SentenceTransformer(model_name)


def build_embeddings_from_sentence_transformer(chunks, model_name: str):
    print(f"[2/4] Loading embedding model '{model_name}' (local cache only)...")
    model = try_load_sentence_model(model_name)

    print(f"[3/4] Generating sentence-transformer embeddings for {len(chunks)} chunks...")
    texts_to_encode = [item["text"] for item in chunks]
    batch_size = 32
    all_embeddings = []
    for offset in tqdm(range(0, len(texts_to_encode), batch_size), desc="Encoding", unit="batch"):
        batch = texts_to_encode[offset : offset + batch_size]
        embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(embeddings)

    return np.array(all_embeddings).astype("float32"), "sentence_transformer"


def build_embeddings_from_tfidf(chunks):
    print("[2/4] Loading TF-IDF artifacts for FAISS fallback...")
    if not os.path.exists(TFIDF_MATRIX_FILE):
        raise FileNotFoundError(f"Could not find {TFIDF_MATRIX_FILE}")
    if not os.path.exists(TFIDF_VECTORIZER_FILE):
        raise FileNotFoundError(f"Could not find {TFIDF_VECTORIZER_FILE}")

    with open(TFIDF_VECTORIZER_FILE, "rb") as file_obj:
        vectorizer = pickle.load(file_obj)

    matrix = load_npz(TFIDF_MATRIX_FILE)
    if matrix.shape[0] != len(chunks):
        raise RuntimeError(
            f"TF-IDF matrix row count mismatch: expected {len(chunks)}, got {matrix.shape[0]}"
        )

    print(f"[3/4] Converting TF-IDF matrix to dense FAISS vectors ({matrix.shape[0]} x {matrix.shape[1]})...")
    embeddings = matrix.astype("float32").toarray()
    idf = getattr(vectorizer, "idf_", None)
    feature_count = int(len(idf)) if idf is not None else 0
    if feature_count and feature_count != embeddings.shape[1]:
        raise RuntimeError(
            f"TF-IDF vectorizer dimension mismatch: expected {feature_count}, got {embeddings.shape[1]}"
        )

    return embeddings, "tfidf"


def build_faiss_kb(mode: str = "auto", model_name: str = "BAAI/bge-small-zh-v1.5"):
    chunks = load_chunks()

    embeddings = None
    used_mode = ""
    last_error = ""

    if mode in {"auto", "sentence"}:
        try:
            embeddings, used_mode = build_embeddings_from_sentence_transformer(chunks, model_name)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if mode == "sentence":
                raise
            print(f"Sentence-transformer build unavailable, fallback to TF-IDF + FAISS: {last_error}")

    if embeddings is None:
        embeddings, used_mode = build_embeddings_from_tfidf(chunks)

    if embeddings.ndim != 2 or embeddings.shape[0] != len(chunks):
        raise RuntimeError(f"Unexpected embedding shape: {embeddings.shape}")

    dimension = int(embeddings.shape[1])
    print(f"[4/4] Building FAISS index ({used_mode}, dimension={dimension})...")
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    print(f"Saving FAISS index to {FAISS_INDEX_FILE}...")
    faiss.write_index(index, FAISS_INDEX_FILE)

    print(f"Saving text mappings to {TEXTS_FILE}...")
    with open(TEXTS_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(chunks, file_obj, ensure_ascii=False)

    meta = {
        "mode": used_mode,
        "dimension": dimension,
        "chunk_count": len(chunks),
        "model_name": model_name if used_mode == "sentence_transformer" else "",
    }
    with open(FAISS_META_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(meta, file_obj, ensure_ascii=False, indent=2)

    print("✓ Public FAISS knowledge base build complete!")
    print(f"  - Mode: {used_mode}")
    print(f"  - Index: {FAISS_INDEX_FILE}")
    print(f"  - Meta: {FAISS_META_FILE}")
    print(f"  - Texts: {TEXTS_FILE}")
    print(f"  - Chunks: {len(chunks)}")
    print(f"  - Dimension: {dimension}")
    if last_error:
        print(f"  - Sentence model fallback reason: {last_error}")


def main():
    parser = argparse.ArgumentParser(description="Build public FAISS knowledge base.")
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "sentence", "tfidf"],
        help="auto: 先尝试本地句向量模型，失败时回退到 TF-IDF；tfidf: 直接使用本地 TF-IDF 制品",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="BAAI/bge-small-zh-v1.5",
        help="句向量模型名，仅在 mode=auto/sentence 时使用",
    )
    args = parser.parse_args()
    build_faiss_kb(mode=args.mode, model_name=args.model)


if __name__ == "__main__":
    main()
