import json
import os
import pickle
import tempfile
import unittest
from unittest.mock import patch

try:
    import faiss
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    import app.services.knowledge_base as kb

    _IMPORT_ERROR = ""
except Exception as exc:
    faiss = None
    np = None
    TfidfVectorizer = None
    kb = None
    _IMPORT_ERROR = str(exc)


@unittest.skipIf(kb is None, f"knowledge_base unavailable: {_IMPORT_ERROR}")
class TestPublicVectorTfidfFallback(unittest.TestCase):
    def test_search_public_chunks_uses_tfidf_encoder_when_sentence_model_missing(self):
        chunks = [
            {
                "chunk_id": "public_1",
                "knowledge_point": "导数",
                "chapter": "导数与微分",
                "discipline": "高等数学",
                "chunk_type": "core",
                "tags": ["导数", "切线斜率"],
                "text": "导数的几何意义是函数图像在某点处切线的斜率。",
            },
            {
                "chunk_id": "public_2",
                "knowledge_point": "积分",
                "chapter": "积分学",
                "discipline": "高等数学",
                "chunk_type": "core",
                "tags": ["积分", "面积"],
                "text": "定积分体现的是累加思想，常用于表示面积和总量。",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            faiss_file = os.path.join(tmpdir, "pro_kb_faiss.index")
            texts_file = os.path.join(tmpdir, "pro_kb_texts.json")
            vectorizer_file = os.path.join(tmpdir, "pro_kb_tfidf_vectorizer.pkl")

            texts = [item["text"] for item in chunks]
            vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
            matrix = vectorizer.fit_transform(texts).astype("float32").toarray()
            index = faiss.IndexFlatL2(matrix.shape[1])
            index.add(np.array(matrix).astype("float32"))

            faiss.write_index(index, faiss_file)
            with open(texts_file, "w", encoding="utf-8") as file_obj:
                json.dump(chunks, file_obj, ensure_ascii=False)
            with open(vectorizer_file, "wb") as file_obj:
                pickle.dump(vectorizer, file_obj)

            original_public_kb = dict(kb._PUBLIC_KB)
            original_faiss_index = kb._FAISS_INDEX
            original_embedding_model = kb._EMBEDDING_MODEL
            original_public_vectorizer = kb._PUBLIC_QUERY_TFIDF_VECTORIZER
            original_faiss_module = kb._FAISS_MODULE
            original_numpy_module = kb._NUMPY_MODULE

            try:
                kb._PUBLIC_KB.clear()
                kb._PUBLIC_KB.update(
                    {
                        "loaded": False,
                        "enabled": False,
                        "chunks": [],
                        "error": "",
                        "query_mode": "",
                        "query_error": "",
                    }
                )
                kb._FAISS_INDEX = None
                kb._EMBEDDING_MODEL = None
                kb._PUBLIC_QUERY_TFIDF_VECTORIZER = None
                kb._FAISS_MODULE = None
                kb._NUMPY_MODULE = None

                with patch.object(kb, "_PRO_KB_FAISS_FILE", faiss_file), patch.object(
                    kb, "_PRO_KB_TEXTS_FILE", texts_file
                ), patch.object(
                    kb, "_PRO_KB_TFIDF_VECTORIZER_FILE", vectorizer_file
                ), patch.object(
                    kb,
                    "get_kb_readiness_report",
                    return_value={"public_vector": {"ready": True}, "errors": [], "warnings": []},
                ), patch.object(
                    kb, "_load_public_local_embedding_model", return_value=(None, "offline")
                ):
                    rows = kb._search_public_chunks("导数 切线斜率", top_k=2)

                self.assertGreaterEqual(len(rows), 1)
                self.assertEqual(rows[0].get("doc_id"), "public_1")
                self.assertEqual(rows[0].get("encoder_mode"), "tfidf")
            finally:
                kb._PUBLIC_KB.clear()
                kb._PUBLIC_KB.update(original_public_kb)
                kb._FAISS_INDEX = original_faiss_index
                kb._EMBEDDING_MODEL = original_embedding_model
                kb._PUBLIC_QUERY_TFIDF_VECTORIZER = original_public_vectorizer
                kb._FAISS_MODULE = original_faiss_module
                kb._NUMPY_MODULE = original_numpy_module


if __name__ == "__main__":
    unittest.main()
