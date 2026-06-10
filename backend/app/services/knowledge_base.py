import json
import math
import os
import pickle
import re
import threading
import time
import uuid

from .concept_mapping import extract_text_keywords
from .database import append_user_event, get_user_event_list, get_user_space_payload
from .document_ingest import is_git_lfs_pointer_file, normalize_text_preview, split_text_into_chunks
from .neo4j_store import Neo4jGraphStore
from .topic_guard import filter_learning_topics


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9_]+")
_CACHE = {}
_CACHE_TTL_SECONDS = 45
_PUBLIC_QUERY_CACHE_TTL_SECONDS = 180
_PRIVATE_VECTOR_CACHE_TTL_SECONDS = 180
_GRAPH_SYNC_ASYNC = str(os.getenv("KB_GRAPH_SYNC_ASYNC", "false")).strip().lower() == "true"

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_FAISS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_faiss.index")
_PRO_KB_FAISS_META_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_faiss_meta.json")
_PRO_KB_TEXTS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_texts.json")
_PRO_KB_TFIDF_VECTORIZER_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_tfidf_vectorizer.pkl")
_PUBLIC_VECTOR_ENABLED = str(os.getenv("KB_PUBLIC_VECTOR_ENABLED", "true")).strip().lower() == "true"
_PRIVATE_VECTOR_ENABLED = str(os.getenv("KB_PRIVATE_VECTOR_ENABLED", "true")).strip().lower() == "true"
_PUBLIC_DEMO_FALLBACK_ENABLED = str(os.getenv("KB_PUBLIC_DEMO_FALLBACK_ENABLED", "true")).strip().lower() == "true"
_PUBLIC_VECTOR_MODEL_NAME = os.getenv("KB_PUBLIC_VECTOR_MODEL", "BAAI/bge-small-zh-v1.5").strip() or "BAAI/bge-small-zh-v1.5"

_FAISS_INDEX = None
_EMBEDDING_MODEL = None
_FAISS_MODULE = None
_NUMPY_MODULE = None
_SENTENCE_TRANSFORMER_CLASS = None
_PUBLIC_QUERY_TFIDF_VECTORIZER = None
_NEO4J_STORE = None
_PRIVATE_TFIDF_VECTORIZER_CLASS = None
_PUBLIC_KB = {
    "loaded": False,
    "enabled": False,
    "chunks": [],
    "error": "",
    "query_mode": "",
    "query_error": "",
}
_PUBLIC_DEMO_CHUNKS = [
    {
        "chunk_id": "demo-limit-core",
        "knowledge_point": "极限",
        "chapter": "函数与极限",
        "chunk_type": "core",
        "discipline": "高等数学",
        "tags": ["极限", "定义", "趋势"],
        "text": "极限描述的是当自变量趋近某个值时，函数值接近的稳定趋势。学习时先区分“趋近过程”和“该点取值”这两个概念，再判断左右极限是否相等。",
    },
    {
        "chunk_id": "demo-derivative-geometry",
        "knowledge_point": "导数",
        "chapter": "导数与微分",
        "chunk_type": "core",
        "discipline": "高等数学",
        "tags": ["导数", "切线斜率", "变化率"],
        "text": "导数的本质是瞬时变化率，几何意义是函数图像在某点处切线的斜率。讲解导数时要先回到极限定义，再解释为什么差商极限能刻画局部变化快慢。",
    },
    {
        "chunk_id": "demo-chain-rule",
        "knowledge_point": "链式法则",
        "chapter": "复合函数求导",
        "chunk_type": "steps",
        "discipline": "高等数学",
        "tags": ["链式法则", "复合函数", "求导步骤"],
        "text": "链式法则用于复合函数求导。常见步骤是先识别外层函数和内层函数，再对外层求导并乘以内层导数，最后检查是否遗漏括号和中间变量。",
    },
    {
        "chunk_id": "demo-monotonicity",
        "knowledge_point": "单调性",
        "chapter": "导数应用",
        "chunk_type": "pitfall",
        "discipline": "高等数学",
        "tags": ["单调性", "导数应用", "易错点"],
        "text": "利用导数判断单调性时，不能只看某一个点的导数值，而要观察整个区间内导数符号是否稳定。若导数大于零通常表示函数递增，小于零通常表示递减。",
    },
    {
        "chunk_id": "demo-extreme-value",
        "knowledge_point": "极值",
        "chapter": "导数应用",
        "chunk_type": "core",
        "discipline": "高等数学",
        "tags": ["极值", "驻点", "判别"],
        "text": "极值点的判断不能停留在 f'(x)=0。更可靠的方法是结合一阶导号变或二阶导信息，说明函数在该点附近由增转减还是由减转增。",
    },
    {
        "chunk_id": "demo-integral",
        "knowledge_point": "积分",
        "chapter": "积分学",
        "chunk_type": "core",
        "discipline": "高等数学",
        "tags": ["积分", "面积", "累加思想"],
        "text": "定积分体现的是累加思想，常用于表示面积、位移和总量。教学时可先用小矩形逼近面积，再过渡到黎曼和与积分上限下限的意义。",
    },
]

_CONCEPT_EXTRACTION_STOPWORDS = {
    "知识库",
    "资料",
    "笔记",
    "总结",
    "讲解",
    "解释",
    "是什么",
    "什么意思",
    "为什么",
    "如何",
    "关系",
    "联系",
    "区别",
    "定义",
    "概念",
    "学习路径",
    "路径",
}


def _now_ts():
    return time.time()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_private_user_id(user_id: str) -> str:
    return _normalize_text(user_id)


def _tokenize(text: str):
    return [t.lower() for t in _TOKEN_PATTERN.findall(str(text or "")) if t]


def _char_ngrams(text: str, n: int):
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return []
    if len(compact) <= n:
        return [compact]
    return [compact[idx : idx + n] for idx in range(len(compact) - n + 1)]


def _lexical_units(text: str):
    raw = _normalize_text(text)
    if not raw:
        return []

    tokens = _tokenize(raw)
    units = list(tokens)
    if re.search(r"[\u4e00-\u9fff]", raw):
        units.extend(_char_ngrams(raw, 2))
        units.extend(_char_ngrams(raw, 3))

    deduped = []
    for item in units:
        key = str(item or "").strip().lower()
        if not key or key in deduped:
            continue
        deduped.append(key)
    return deduped


def _score(query: str, text: str):
    q = _normalize_text(query)
    t = _normalize_text(text)
    if not q or not t:
        return 0.0

    q_units = _lexical_units(q)
    t_units = set(_lexical_units(t))
    if not q_units:
        return 0.0

    q_set = set(q_units)
    overlap = len(q_set & t_units)
    substring_hit = 1.0 if q in t else 0.0
    partial_hit = any(len(unit) >= 2 and unit in t for unit in q_units[:24])
    if overlap <= 0 and not substring_hit and not partial_hit:
        return 0.0

    union_count = len(q_set | t_units) or 1
    cover = overlap / max(1, len(q_set))
    jaccard = overlap / union_count
    substring_bonus = 0.22 if substring_hit else (0.12 if partial_hit else 0.0)
    prefix_bonus = 0.06 if t.startswith(q) else 0.0
    length_penalty = 1.0 / max(1.0, math.log(len(t_units) + 3, 3))

    raw_score = (0.5 * cover + 0.3 * jaccard + substring_bonus + prefix_bonus) * (0.72 + 0.28 * length_penalty)
    return round(max(0.0, min(1.0, raw_score)), 4)


def _cache_get(key):
    item = _CACHE.get(key)
    if not item:
        return None
    if _now_ts() > item["expires_at"]:
        _CACHE.pop(key, None)
        return None
    return item["value"]


def _cache_set(key, value, ttl=_CACHE_TTL_SECONDS):
    _CACHE[key] = {
        "expires_at": _now_ts() + max(3, int(ttl or _CACHE_TTL_SECONDS)),
        "value": value,
    }
    return value


def invalidate_user_kb_cache(user_id: str = ""):
    uid = _normalize_text(user_id)
    if not uid:
        return

    removable_prefixes = {"docs", "private_vector_state", "private_vector_search"}
    for key in list(_CACHE.keys()):
        if not isinstance(key, tuple) or len(key) < 2:
            continue
        if key[0] in removable_prefixes and key[1] == uid:
            _CACHE.pop(key, None)


def _inspect_kb_artifact(path: str, artifact_type: str):
    exists = os.path.exists(path)
    size_bytes = os.path.getsize(path) if exists else 0
    lfs_pointer = is_git_lfs_pointer_file(path) if exists else False
    return {
        "path": path,
        "artifact_type": artifact_type,
        "exists": exists,
        "size_bytes": int(size_bytes or 0),
        "size_kb": round(float(size_bytes or 0) / 1024.0, 2),
        "git_lfs_pointer": bool(lfs_pointer),
        "ready": bool(exists and not lfs_pointer and size_bytes > 0),
    }


def _load_public_faiss_meta():
    if not os.path.exists(_PRO_KB_FAISS_META_FILE):
        return {}

    try:
        with open(_PRO_KB_FAISS_META_FILE, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _get_public_demo_chunks():
    return [dict(item) for item in _PUBLIC_DEMO_CHUNKS]


def _load_private_vector_dependencies():
    global _PRIVATE_TFIDF_VECTORIZER_CLASS

    if _PRIVATE_TFIDF_VECTORIZER_CLASS is not None:
        return True, ""

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        _PRIVATE_TFIDF_VECTORIZER_CLASS = TfidfVectorizer
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, ""


def get_kb_readiness_report():
    faiss_artifact = _inspect_kb_artifact(_PRO_KB_FAISS_FILE, "faiss_index")
    texts_artifact = _inspect_kb_artifact(_PRO_KB_TEXTS_FILE, "texts_json")
    vectorizer_artifact = _inspect_kb_artifact(_PRO_KB_TFIDF_VECTORIZER_FILE, "tfidf_vectorizer")
    faiss_meta = _load_public_faiss_meta()
    public_artifacts_ok = faiss_artifact["ready"] and texts_artifact["ready"]
    public_faiss_deps_ready, public_faiss_deps_error = _load_public_faiss_dependencies()
    public_embedding_deps_ready, public_embedding_deps_error = _load_public_embedding_dependency()
    private_deps_ready, private_deps_error = _load_private_vector_dependencies()

    warnings = []
    errors = []
    recommendations = []
    if faiss_artifact["git_lfs_pointer"] or texts_artifact["git_lfs_pointer"]:
        warnings.append("public_kb_artifact_is_git_lfs_pointer")
        recommendations.append("运行 git lfs pull 或补齐真实的 pro_kb 制品文件。")
    if _PUBLIC_VECTOR_ENABLED and not public_artifacts_ok:
        errors.append("public_kb_artifacts_missing_or_invalid")
        if not recommendations:
            recommendations.append("检查 backend/data/pro_kb 下的公共向量库文件是否完整。")
    if _PUBLIC_VECTOR_ENABLED and public_artifacts_ok and not public_faiss_deps_ready:
        errors.append("public_vector_dependencies_unavailable")
        recommendations.append("安装公共向量检索依赖：faiss-cpu。")
    if _PUBLIC_VECTOR_ENABLED and public_artifacts_ok and public_faiss_deps_ready:
        if not public_embedding_deps_ready and not vectorizer_artifact["ready"]:
            errors.append("public_query_encoder_unavailable")
            recommendations.append("补齐 sentence-transformers 依赖，或确保 pro_kb_tfidf_vectorizer.pkl 可用。")
        elif not public_embedding_deps_ready and vectorizer_artifact["ready"]:
            recommendations.append("当前公共检索会回退到 TF-IDF + FAISS 查询模式。")
    if _PRIVATE_VECTOR_ENABLED and not private_deps_ready:
        warnings.append("private_vector_dependencies_unavailable")
        recommendations.append("安装私有资料检索依赖：scikit-learn。")

    public_vector_ready = bool(
        _PUBLIC_VECTOR_ENABLED
        and public_artifacts_ok
        and public_faiss_deps_ready
        and (public_embedding_deps_ready or vectorizer_artifact["ready"])
    )
    private_vector_ready = bool(_PRIVATE_VECTOR_ENABLED and private_deps_ready)
    demo_fallback_ready = bool(_PUBLIC_DEMO_FALLBACK_ENABLED and _get_public_demo_chunks())
    search_ready = bool(public_vector_ready or demo_fallback_ready or private_vector_ready)
    offline_chain_ready = bool(demo_fallback_ready and private_vector_ready)

    status = "ready"
    if not search_ready:
        status = "not_ready"
    elif not public_vector_ready:
        status = "degraded"

    mode = "full"
    if public_vector_ready:
        mode = "full"
    elif demo_fallback_ready and private_vector_ready:
        mode = "demo_fallback"
        recommendations.append("当前处于离线可演示模式，答辩前建议恢复真实公共向量库。")
    elif demo_fallback_ready:
        mode = "demo_public_only"
    elif private_vector_ready:
        mode = "private_only"
    else:
        mode = "unavailable"

    deduped_recommendations = []
    seen_recommendations = set()
    for item in recommendations:
        text = _normalize_text(item)
        if not text or text in seen_recommendations:
            continue
        deduped_recommendations.append(text)
        seen_recommendations.add(text)

    runtime_query_encoder = _normalize_text(faiss_meta.get("mode") or "")
    if runtime_query_encoder not in {"sentence_transformer", "tfidf"}:
        runtime_query_encoder = (
            "sentence_transformer"
            if public_embedding_deps_ready
            else ("tfidf" if vectorizer_artifact["ready"] else "unavailable")
        )

    return {
        "status": status,
        "ready": search_ready,
        "search_ready": search_ready,
        "warnings": warnings,
        "errors": errors,
        "recommended_actions": deduped_recommendations,
        "public_vector": {
            "enabled": _PUBLIC_VECTOR_ENABLED,
            "ready": public_vector_ready,
            "model_name": _PUBLIC_VECTOR_MODEL_NAME,
            "artifacts_ok": public_artifacts_ok,
            "deps_ready": public_faiss_deps_ready,
            "deps_error": public_faiss_deps_error,
            "query_encoder": runtime_query_encoder,
            "query_encoder_ready": bool(public_embedding_deps_ready or vectorizer_artifact["ready"]),
            "query_encoder_error": (
                ""
                if public_embedding_deps_ready or vectorizer_artifact["ready"]
                else _normalize_text(public_embedding_deps_error)
            ),
            "artifacts": {
                "faiss_index": faiss_artifact,
                "texts_json": texts_artifact,
                "tfidf_vectorizer": vectorizer_artifact,
            },
        },
        "private_vector": {
            "enabled": _PRIVATE_VECTOR_ENABLED,
            "ready": private_vector_ready,
            "deps_ready": private_deps_ready,
            "deps_error": private_deps_error,
        },
        "demo_fallback": {
            "enabled": _PUBLIC_DEMO_FALLBACK_ENABLED,
            "ready": demo_fallback_ready,
            "chunks": len(_get_public_demo_chunks()) if _PUBLIC_DEMO_FALLBACK_ENABLED else 0,
        },
        "offline_chain": {
            "ready": offline_chain_ready,
            "public_demo_ready": demo_fallback_ready,
            "private_personalization_ready": private_vector_ready,
        },
        "summary": {
            "mode": mode,
            "public_vector_ready": public_vector_ready,
            "private_vector_ready": private_vector_ready,
            "demo_fallback_ready": demo_fallback_ready,
            "offline_chain_ready": offline_chain_ready,
        },
    }


def _dedupe_hits(rows, top_k: int, max_per_title: int = 1):
    limit = max(1, int(top_k or 3))
    max_same_title = max(1, int(max_per_title or 1))

    deduped = []
    seen_doc = set()
    seen_fp = set()
    title_counter = {}

    def _title_key(title):
        return _normalize_text(title).lower()

    for row in rows:
        doc_id = str(row.get("doc_id") or row.get("source_doc_id") or "").strip()
        title = _normalize_text(row.get("title") or "")
        snippet = _normalize_text(row.get("snippet") or row.get("content") or "")

        if doc_id and doc_id in seen_doc:
            continue

        fp = f"{title}|{snippet[:160]}"
        if fp in seen_fp:
            continue

        tk = _title_key(title)
        current = title_counter.get(tk, 0)
        if tk and current >= max_same_title:
            continue

        deduped.append(row)
        if doc_id:
            seen_doc.add(doc_id)
        seen_fp.add(fp)
        if tk:
            title_counter[tk] = current + 1

        if len(deduped) >= limit:
            return deduped

    for row in rows:
        doc_id = str(row.get("doc_id") or row.get("source_doc_id") or "").strip()
        title = _normalize_text(row.get("title") or "")
        snippet = _normalize_text(row.get("snippet") or row.get("content") or "")

        if doc_id and doc_id in seen_doc:
            continue

        fp = f"{title}|{snippet[:160]}"
        if fp in seen_fp:
            continue

        deduped.append(row)
        if doc_id:
            seen_doc.add(doc_id)
        seen_fp.add(fp)

        if len(deduped) >= limit:
            break

    return deduped


def _get_neo4j_store():
    global _NEO4J_STORE
    if _NEO4J_STORE is None:
        _NEO4J_STORE = Neo4jGraphStore()
    return _NEO4J_STORE


def _load_public_faiss_dependencies():
    global _FAISS_MODULE, _NUMPY_MODULE

    if _FAISS_MODULE is not None and _NUMPY_MODULE is not None:
        return True, ""

    try:
        if _FAISS_MODULE is None:
            import faiss as faiss_module

            _FAISS_MODULE = faiss_module
        if _NUMPY_MODULE is None:
            import numpy as numpy_module

            _NUMPY_MODULE = numpy_module
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, ""


def _load_public_embedding_dependency():
    global _SENTENCE_TRANSFORMER_CLASS

    if _SENTENCE_TRANSFORMER_CLASS is not None:
        return True, ""

    try:
        from sentence_transformers import SentenceTransformer as sentence_transformer_class

        _SENTENCE_TRANSFORMER_CLASS = sentence_transformer_class
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, ""


def _load_public_query_vectorizer():
    global _PUBLIC_QUERY_TFIDF_VECTORIZER

    if _PUBLIC_QUERY_TFIDF_VECTORIZER is not None:
        return True, ""

    try:
        with open(_PRO_KB_TFIDF_VECTORIZER_FILE, "rb") as file_obj:
            _PUBLIC_QUERY_TFIDF_VECTORIZER = pickle.load(file_obj)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, ""


def _get_vectorizer_feature_count(vectorizer):
    if vectorizer is None:
        return 0

    idf = getattr(vectorizer, "idf_", None)
    if idf is not None:
        try:
            return int(len(idf))
        except Exception:
            return 0

    vocabulary = getattr(vectorizer, "vocabulary_", None)
    if isinstance(vocabulary, dict):
        return int(len(vocabulary))

    return 0


def _load_public_local_embedding_model():
    global _EMBEDDING_MODEL

    deps_ready, deps_error = _load_public_embedding_dependency()
    if not deps_ready:
        return None, deps_error

    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL, ""

    try:
        _EMBEDDING_MODEL = _SENTENCE_TRANSFORMER_CLASS(_PUBLIC_VECTOR_MODEL_NAME, local_files_only=True)
    except TypeError:
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            _EMBEDDING_MODEL = _SENTENCE_TRANSFORMER_CLASS(_PUBLIC_VECTOR_MODEL_NAME)
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    return _EMBEDDING_MODEL, ""


def _load_public_kb_once():
    global _FAISS_INDEX, _EMBEDDING_MODEL

    if _PUBLIC_KB.get("loaded"):
        return _PUBLIC_KB

    payload = {
        "loaded": True,
        "enabled": False,
        "chunks": [],
        "error": "",
        "query_mode": "",
        "query_error": "",
        "vectorizer": None,
    }

    try:
        readiness = get_kb_readiness_report()
        public_vector_state = readiness.get("public_vector", {}) if isinstance(readiness, dict) else {}
        artifact_errors = readiness.get("errors", []) if isinstance(readiness, dict) else []
        warnings = readiness.get("warnings", []) if isinstance(readiness, dict) else []

        if not _PUBLIC_VECTOR_ENABLED:
            payload["error"] = "public vector disabled by env"
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        if not public_vector_state.get("ready"):
            if "public_kb_artifact_is_git_lfs_pointer" in warnings:
                payload["error"] = "public vector unavailable: git lfs pointer detected in pro_kb artifacts"
            elif "public_kb_artifacts_missing_or_invalid" in artifact_errors:
                payload["error"] = "public vector unavailable: pro_kb artifacts missing or invalid"
            else:
                payload["error"] = (
                    public_vector_state.get("deps_error")
                    or "public vector unavailable"
                )
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        deps_ready, deps_error = _load_public_faiss_dependencies()
        if not deps_ready:
            payload["error"] = f"public vector unavailable: {deps_error}"
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        if _FAISS_INDEX is None:
            _FAISS_INDEX = _FAISS_MODULE.read_index(_PRO_KB_FAISS_FILE)

        with open(_PRO_KB_TEXTS_FILE, "r", encoding="utf-8") as file_obj:
            chunks = json.load(file_obj)

        index_dimension = int(getattr(_FAISS_INDEX, "d", 0) or 0)
        embedding_model, embedding_error = _load_public_local_embedding_model()
        if embedding_model is not None:
            try:
                embedding_dimension = int(embedding_model.get_sentence_embedding_dimension() or 0)
            except Exception:
                embedding_dimension = 0

            if index_dimension > 0 and embedding_dimension == index_dimension:
                payload["query_mode"] = "sentence_transformer"
            else:
                payload["query_error"] = (
                    f"embedding_dimension_mismatch:index={index_dimension},model={embedding_dimension}"
                )
                embedding_model = None

        if not payload.get("query_mode"):
            vectorizer_ready, vectorizer_error = _load_public_query_vectorizer()
            vectorizer = _PUBLIC_QUERY_TFIDF_VECTORIZER if vectorizer_ready else None
            vectorizer_dimension = _get_vectorizer_feature_count(vectorizer)
            if vectorizer is not None and index_dimension > 0 and vectorizer_dimension == index_dimension:
                payload["query_mode"] = "tfidf"
                payload["vectorizer"] = vectorizer
                if embedding_error and not payload.get("query_error"):
                    payload["query_error"] = embedding_error
            else:
                query_errors = [payload.get("query_error"), embedding_error, vectorizer_error]
                payload["error"] = "public vector unavailable: no compatible query encoder for faiss index"
                payload["query_error"] = "; ".join(
                    _normalize_text(item) for item in query_errors if _normalize_text(item)
                )
                _PUBLIC_KB.update(payload)
                return _PUBLIC_KB

        payload.update(
            {
                "enabled": bool(chunks),
                "chunks": chunks,
            }
        )
    except Exception as exc:
        payload["error"] = f"public vector unavailable: {exc}"

    _PUBLIC_KB.update(payload)
    return _PUBLIC_KB


def _search_public_chunks(query: str, top_k: int = 3):
    q = _normalize_text(query)
    if not q:
        return []

    pub = _load_public_kb_once()
    if not pub.get("enabled"):
        return []

    query_mode = _normalize_text(pub.get("query_mode") or "")
    cache_key = ("public_search_dense", query_mode or "unknown", q, int(top_k or 3))
    cached_rows = _cache_get(cache_key)
    if cached_rows is not None:
        return cached_rows

    chunks = pub.get("chunks", [])
    if not chunks or _FAISS_INDEX is None or _NUMPY_MODULE is None or not query_mode:
        return []

    try:
        if query_mode == "sentence_transformer":
            if _EMBEDDING_MODEL is None:
                return []
            query_vector = _EMBEDDING_MODEL.encode([q])
        elif query_mode == "tfidf":
            vectorizer = pub.get("vectorizer") or _PUBLIC_QUERY_TFIDF_VECTORIZER
            if vectorizer is None:
                return []
            query_vector = vectorizer.transform([q]).toarray()
        else:
            return []

        query_vector = _NUMPY_MODULE.array(query_vector).astype("float32")
        if query_vector.ndim != 2 or query_vector.shape[1] != int(getattr(_FAISS_INDEX, "d", 0) or 0):
            return []
        recall_k = max(20, int(top_k or 3) * 10)
        distances, indices = _FAISS_INDEX.search(query_vector, recall_k)
    except Exception:
        return []

    rows = []
    for rank, idx in enumerate(indices[0]):
        if idx < 0 or idx >= len(chunks):
            continue
        row = chunks[idx]
        text = _normalize_text(row.get("text") or "")
        title = _normalize_text(row.get("knowledge_point") or row.get("chapter") or "公共知识片段")
        if not text and not title:
            continue

        vector_score = 1.0 / (1.0 + float(distances[0][rank]))
        lexical_score = _score(q, f"{title} {text}")
        hybrid = 0.75 * float(vector_score) + 0.25 * float(lexical_score)

        rows.append(
            {
                "doc_id": str(row.get("chunk_id") or row.get("card_id") or f"public_{idx}"),
                "source_doc_id": str(row.get("chunk_id") or row.get("card_id") or f"public_{idx}"),
                "title": title,
                "content": text,
                "snippet": text[:220],
                "source": "public_pro_kb",
                "content_type": _normalize_text(row.get("chunk_type") or "chunk"),
                "timestamp": "",
                "channel": "public_vector",
                "encoder_mode": query_mode,
                "score": round(float(hybrid), 4),
                "text_score": round(float(hybrid), 4),
                "vector_score": round(float(vector_score), 4),
                "lexical_score": round(float(lexical_score), 4),
                "discipline": _normalize_text(row.get("discipline") or ""),
                "chapter": _normalize_text(row.get("chapter") or ""),
                "tags": row.get("tags", []) if isinstance(row.get("tags", []), list) else [],
                "topics": row.get("tags", []) if isinstance(row.get("tags", []), list) else [],
                "source_type": "public",
            }
        )

    rows.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    rows = _dedupe_hits(rows, top_k=int(top_k or 3), max_per_title=2)
    return _cache_set(cache_key, rows, ttl=_PUBLIC_QUERY_CACHE_TTL_SECONDS)


def _search_public_demo_chunks(query: str, top_k: int = 3):
    q = _normalize_text(query)
    if not q or not _PUBLIC_DEMO_FALLBACK_ENABLED:
        return []

    cache_key = ("public_demo_search", q, int(top_k or 3))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    rows = []
    for idx, row in enumerate(_get_public_demo_chunks()):
        text = _normalize_text(row.get("text") or "")
        title = _normalize_text(row.get("knowledge_point") or row.get("chapter") or "公共知识片段")
        lexical_score = _score(q, f"{title} {text}")
        if lexical_score <= 0:
            continue
        rows.append(
            {
                "doc_id": str(row.get("chunk_id") or f"demo_public_{idx}"),
                "source_doc_id": str(row.get("chunk_id") or f"demo_public_{idx}"),
                "title": title,
                "content": text,
                "snippet": normalize_text_preview(text, 220),
                "source": "public_demo_fallback",
                "content_type": _normalize_text(row.get("chunk_type") or "chunk"),
                "timestamp": "",
                "channel": "public_demo_fallback",
                "score": round(float(lexical_score), 4),
                "text_score": round(float(lexical_score), 4),
                "lexical_score": round(float(lexical_score), 4),
                "discipline": _normalize_text(row.get("discipline") or ""),
                "chapter": _normalize_text(row.get("chapter") or ""),
                "tags": row.get("tags", []) if isinstance(row.get("tags", []), list) else [],
                "topics": row.get("tags", []) if isinstance(row.get("tags", []), list) else [],
                "source_type": "public",
                "fallback": True,
            }
        )

    rows.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    rows = _dedupe_hits(rows, top_k=int(top_k or 3), max_per_title=2)
    return _cache_set(cache_key, rows, ttl=_PUBLIC_QUERY_CACHE_TTL_SECONDS)


def _build_private_chunks(docs):
    chunks = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        content = _normalize_text(doc.get("content") or "")
        if not content:
            continue
        base_doc_id = str(doc.get("doc_id") or doc.get("source_doc_id") or uuid.uuid4().hex).strip()
        title = _normalize_text(doc.get("title") or "学习记录")
        for index, chunk_text in enumerate(split_text_into_chunks(content, chunk_size=720, overlap=120, max_chunks=40), start=1):
            chunks.append(
                {
                    "chunk_id": f"{base_doc_id}::chunk::{index}",
                    "doc_id": base_doc_id,
                    "source_doc_id": str(doc.get("source_doc_id") or base_doc_id),
                    "title": title,
                    "content": chunk_text,
                    "source": _normalize_text(doc.get("source") or "content_log"),
                    "content_type": _normalize_text(doc.get("content_type") or "note"),
                    "timestamp": _normalize_text(doc.get("timestamp") or ""),
                    "tags": [str(x).strip() for x in (doc.get("tags") or []) if str(x).strip()],
                    "topics": [str(x).strip() for x in (doc.get("topics") or []) if str(x).strip()],
                    "chunk_index": index,
                }
            )
    return chunks


def _get_private_vector_state(user_id: str, docs):
    uid = _normalize_private_user_id(user_id)
    cache_key = ("private_vector_state", uid)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    state = {
        "enabled": False,
        "error": "",
        "chunks": [],
        "vectorizer": None,
        "matrix": None,
    }
    if not uid:
        state["error"] = "missing user scope"
        return _cache_set(cache_key, state, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)

    if not _PRIVATE_VECTOR_ENABLED:
        state["error"] = "private vector disabled by env"
        return _cache_set(cache_key, state, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)

    deps_ready, deps_error = _load_private_vector_dependencies()
    if not deps_ready:
        state["error"] = f"private vector unavailable: {deps_error}"
        return _cache_set(cache_key, state, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)

    chunks = _build_private_chunks(docs)
    if not chunks:
        state["error"] = "no private chunks"
        return _cache_set(cache_key, state, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)

    try:
        texts = [f"{item.get('title', '')}\n{item.get('content', '')}" for item in chunks]
        vectorizer = _PRIVATE_TFIDF_VECTORIZER_CLASS(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            max_features=max(2000, min(24000, len(texts) * 36)),
        )
        matrix = vectorizer.fit_transform(texts)
        state.update(
            {
                "enabled": True,
                "chunks": chunks,
                "vectorizer": vectorizer,
                "matrix": matrix,
            }
        )
    except Exception as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"

    return _cache_set(cache_key, state, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)


def _search_private_vector_chunks(user_id: str, query: str, docs, top_k: int = 3):
    q = _normalize_text(query)
    uid = _normalize_private_user_id(user_id)
    if not q or not uid:
        return []

    cache_key = ("private_vector_search", uid, q, int(top_k or 3))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    state = _get_private_vector_state(uid, docs)
    if not state.get("enabled"):
        return []

    try:
        query_vector = state["vectorizer"].transform([q])
        scores = (state["matrix"] @ query_vector.T).toarray().ravel().tolist()
    except Exception:
        return []

    recall_k = max(10, int(top_k or 3) * 6)
    ranked = sorted(
        enumerate(scores),
        key=lambda item: float(item[1] or 0.0),
        reverse=True,
    )[:recall_k]

    rows = []
    chunks = state.get("chunks", [])
    for idx, vector_score in ranked:
        if idx < 0 or idx >= len(chunks):
            continue
        chunk = chunks[idx]
        content = _normalize_text(chunk.get("content") or "")
        title = _normalize_text(chunk.get("title") or "学习记录")
        lexical_score = _score(q, f"{title} {content}")
        hybrid_score = 0.68 * float(vector_score or 0.0) + 0.32 * float(lexical_score or 0.0)
        if hybrid_score <= 0:
            continue
        rows.append(
            {
                "doc_id": str(chunk.get("chunk_id") or chunk.get("doc_id") or f"private_chunk_{idx}"),
                "source_doc_id": str(chunk.get("source_doc_id") or chunk.get("doc_id") or ""),
                "title": title,
                "content": content,
                "snippet": normalize_text_preview(content, 220),
                "source": _normalize_text(chunk.get("source") or "content_log"),
                "content_type": _normalize_text(chunk.get("content_type") or "note"),
                "timestamp": _normalize_text(chunk.get("timestamp") or ""),
                "channel": "private_vector",
                "score": round(float(hybrid_score), 4),
                "text_score": round(float(hybrid_score), 4),
                "vector_score": round(float(vector_score or 0.0), 4),
                "lexical_score": round(float(lexical_score or 0.0), 4),
                "tags": chunk.get("tags", []) if isinstance(chunk.get("tags", []), list) else [],
                "topics": chunk.get("topics", []) if isinstance(chunk.get("topics", []), list) else [],
                "source_type": "private",
            }
        )

    rows = _dedupe_hits(rows, top_k=max(1, int(top_k or 3)), max_per_title=2)
    return _cache_set(cache_key, rows, ttl=_PRIVATE_VECTOR_CACHE_TTL_SECONDS)


def _candidate_concepts_from_text(text: str, max_keywords: int = 6):
    raw = _normalize_text(text)
    if not raw:
        return []

    extracted = extract_text_keywords(raw, stopwords=_CONCEPT_EXTRACTION_STOPWORDS, max_keywords=max_keywords)
    candidates = []
    if 2 <= len(raw) <= 20:
        candidates.append(raw)
    for item in extracted:
        cleaned = _normalize_text(item)
        if cleaned:
            candidates.append(cleaned)
    return candidates


def _extract_graph_concepts(query: str, candidate_rows=None, limit: int = 6):
    raw_candidates = []
    raw_candidates.extend(_candidate_concepts_from_text(query, max_keywords=max(6, limit)))

    for row in (candidate_rows or [])[:6]:
        raw_candidates.extend(_candidate_concepts_from_text(row.get("title"), max_keywords=4))
        raw_candidates.extend(_candidate_concepts_from_text(row.get("chapter"), max_keywords=2))
        raw_candidates.extend(_candidate_concepts_from_text(row.get("discipline"), max_keywords=2))
        for item in row.get("tags", []) if isinstance(row.get("tags", []), list) else []:
            raw_candidates.extend(_candidate_concepts_from_text(item, max_keywords=1))
        for item in row.get("topics", []) if isinstance(row.get("topics", []), list) else []:
            raw_candidates.extend(_candidate_concepts_from_text(item, max_keywords=1))

    cleaned_candidates = []
    seen = set()
    for item in raw_candidates:
        topic = _normalize_text(item)
        key = topic.lower()
        if not topic or key in seen or len(topic) < 2 or len(topic) > 20:
            continue
        cleaned_candidates.append(topic)
        seen.add(key)

    filtered = filter_learning_topics(cleaned_candidates, limit=limit)
    if filtered:
        return filtered[: max(1, int(limit or 6))]

    return cleaned_candidates[: max(1, int(limit or 6))]


def _sync_kb_note_graph(user_id: str, item: dict):
    concepts = [str(x).strip() for x in ((item or {}).get("topics") or (item or {}).get("tags") or []) if str(x).strip()]
    base_payload = {
        "enabled": False,
        "mode": "disabled",
        "synced": False,
        "submitted": False,
        "task_id": None,
        "task_type": "sync_kb_note_graph",
        "status_url": None,
        "document_id": (item or {}).get("id"),
        "document_title": (item or {}).get("title"),
        "concepts": concepts,
        "mentions_count": len(concepts),
    }

    try:
        store = _get_neo4j_store()
        if not store or not store.ensure_connected():
            return base_payload

        ok = bool(
            store.upsert_kb_note_graph(
                user_id=user_id,
                note_id=item.get("id"),
                title=item.get("title"),
                content=item.get("content"),
                concepts=item.get("topics") or item.get("tags") or [],
                source=item.get("source", "agent_kb"),
                tags=item.get("tags") or [],
            )
        )
        base_payload.update(
            {
                "enabled": True,
                "mode": "sync",
                "synced": ok,
            }
        )
        return base_payload
    except Exception:
        return base_payload


def _dispatch_kb_note_graph_sync(user_id: str, item: dict):
    concepts = [str(x).strip() for x in ((item or {}).get("topics") or (item or {}).get("tags") or []) if str(x).strip()]
    try:
        store = _get_neo4j_store()
    except Exception:
        store = None

    if not store or not store.ensure_connected():
        return {
            "enabled": False,
            "mode": "disabled",
            "synced": False,
            "submitted": False,
            "task_id": None,
            "task_type": "sync_kb_note_graph",
            "status_url": None,
            "document_id": (item or {}).get("id"),
            "document_title": (item or {}).get("title"),
            "concepts": concepts,
            "mentions_count": len(concepts),
        }

    if _GRAPH_SYNC_ASYNC:
        worker = threading.Thread(target=_sync_kb_note_graph, args=(user_id, item), daemon=True)
        worker.start()
        return {
            "enabled": True,
            "mode": "async",
            "synced": False,
            "submitted": True,
            "task_id": None,
            "task_type": "sync_kb_note_graph",
            "status_url": None,
            "document_id": (item or {}).get("id"),
            "document_title": (item or {}).get("title"),
            "concepts": concepts,
            "mentions_count": len(concepts),
        }

    return _sync_kb_note_graph(user_id, item)


def ingest_kb_note(user_id: str, title: str, content: str, source: str = "agent_kb", tags=None):
    uid = _normalize_private_user_id(user_id)
    if not uid:
        raise ValueError("user_id 不能为空")
    ttl_title = _normalize_text(title)[:120] or "知识笔记"
    body = _normalize_text(content)
    if not body:
        raise ValueError("content 不能为空")

    clean_tags = [str(x).strip() for x in (tags or []) if str(x).strip()][:8]
    concepts = _extract_graph_concepts(f"{ttl_title} {body}", candidate_rows=[{"tags": clean_tags}], limit=6)

    item = {
        "id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "content_type": "kb_note",
        "title": ttl_title,
        "content": body,
        "source": _normalize_text(source)[:40] or "agent_kb",
        "tags": clean_tags,
        "topics": concepts,
    }
    append_user_event(uid, "content", item)
    invalidate_user_kb_cache(uid)
    item["graph_sync"] = _dispatch_kb_note_graph_sync(uid, item)
    return item


def _append_private_doc(docs, *, doc_id, title, content, source, content_type, timestamp="", tags=None, topics=None):
    body = _normalize_text(content)
    if not body:
        return

    docs.append(
        {
            "doc_id": str(doc_id or ""),
            "source_doc_id": str(doc_id or ""),
            "title": _normalize_text(title or "学习记录"),
            "content": body,
            "source": _normalize_text(source or "content_log"),
            "content_type": _normalize_text(content_type or "note"),
            "timestamp": _normalize_text(timestamp or ""),
            "tags": [str(x).strip() for x in (tags or []) if str(x).strip()],
            "topics": [str(x).strip() for x in (topics or []) if str(x).strip()],
        }
    )


def _collect_docs(user_id: str):
    uid = _normalize_private_user_id(user_id)
    if not uid:
        return []
    cache_key = ("docs", uid)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    docs = []
    content_logs = get_user_event_list(uid, "content") or []
    for row in content_logs:
        if not isinstance(row, dict):
            continue
        title = _normalize_text(row.get("title") or "学习记录")
        content_type = _normalize_text(row.get("content_type") or "note")
        content = _normalize_text(row.get("content") or "")
        if content_type == "qa":
            question_text = _normalize_text(row.get("question_text") or "")
            answer_text = _normalize_text(row.get("answer_text") or "")
            rebuilt = _normalize_text(f"问题：{question_text}\n回答：{answer_text}")
            if rebuilt and len(rebuilt) >= len(content):
                content = rebuilt

        _append_private_doc(
            docs,
            doc_id=str(row.get("id") or ""),
            title=title,
            content=content,
            source=_normalize_text(row.get("source") or "content_log"),
            content_type=content_type,
            timestamp=_normalize_text(row.get("timestamp") or ""),
            tags=row.get("tags") or [],
            topics=row.get("topics") or [],
        )

    question_answer_logs = get_user_event_list(uid, "question_answer") or []
    for row in question_answer_logs:
        if not isinstance(row, dict):
            continue
        concept = _normalize_text(row.get("concept") or "")
        status_text = "正确" if bool(row.get("is_correct", False)) else "错误"
        content_parts = []
        question_text = _normalize_text(row.get("question") or "")
        user_answer = _normalize_text(row.get("user_answer") or "")
        expected_answer = _normalize_text(row.get("expected_answer") or "")
        difficulty = _normalize_text(row.get("difficulty") or "")
        score_text = str(row.get("score")).strip() if row.get("score") not in (None, "") else ""
        if question_text:
            content_parts.append(f"题目：{question_text}")
        if user_answer:
            content_parts.append(f"学生作答：{user_answer}")
        if expected_answer:
            content_parts.append(f"标准答案：{expected_answer}")
        content_parts.append(f"判题结果：{status_text}")
        if score_text:
            content_parts.append(f"得分：{score_text}")
        if difficulty:
            content_parts.append(f"难度：{difficulty}")
        content = "\n".join(content_parts)
        _append_private_doc(
            docs,
            doc_id=str(row.get("id") or row.get("question_id") or uuid.uuid4().hex),
            title=f"题库作答·{concept or _normalize_text(row.get('question_type') or '练习题') or '练习题'}",
            content=content,
            source="question_answer",
            content_type="question_answer",
            timestamp=_normalize_text(row.get("timestamp") or ""),
            tags=[concept] if concept else [],
            topics=row.get("topics") or ([concept] if concept else []),
        )

    wrong_question_logs = get_user_event_list(uid, "wrong_question") or []
    for row in wrong_question_logs:
        if not isinstance(row, dict):
            continue
        concept = _normalize_text(row.get("concept") or "")
        content_parts = []
        question_text = _normalize_text(row.get("question") or "")
        user_answer = _normalize_text(row.get("user_answer") or "")
        expected_answer = _normalize_text(row.get("expected_answer") or "")
        answer_excerpt = _normalize_text(row.get("answer_excerpt") or "")
        error_type = _normalize_text(row.get("error_type") or "")
        if question_text:
            content_parts.append(f"错题题目：{question_text}")
        if user_answer:
            content_parts.append(f"学生错误答案：{user_answer}")
        if concept:
            content_parts.append(f"知识点：{concept}")
        if expected_answer:
            content_parts.append(f"标准答案：{expected_answer}")
        if answer_excerpt:
            content_parts.append(f"答案摘录：{answer_excerpt}")
        if error_type:
            content_parts.append(f"错因标签：{error_type}")
        content = "\n".join(content_parts)
        _append_private_doc(
            docs,
            doc_id=str(row.get("id") or uuid.uuid4().hex),
            title=f"错题沉淀·{concept or '待订正'}",
            content=content,
            source="wrong_question",
            content_type="wrong_question",
            timestamp=_normalize_text(row.get("timestamp") or ""),
            tags=[concept] if concept else [],
            topics=row.get("topics") or ([concept] if concept else []),
        )

    space_payload = get_user_space_payload(uid) or {}
    for space in space_payload.get("spaces", []) if isinstance(space_payload, dict) else []:
        if not isinstance(space, dict):
            continue
        for item in space.get("items", []) if isinstance(space.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("content") or item.get("summary") or "")
            _append_private_doc(
                docs,
                doc_id=str(item.get("id") or ""),
                title=_normalize_text(item.get("name") or "空间资料"),
                content=text,
                source="space",
                content_type=_normalize_text(item.get("kind") or "document"),
                timestamp=str(item.get("updatedAt") or item.get("addedAt") or ""),
                tags=item.get("tags") or [],
                topics=item.get("topics") or [],
            )

    return _cache_set(cache_key, docs)


def _recall_private_hits(query: str, docs, top_k: int):
    q = _normalize_text(query)
    if not q:
        return []

    hits = []
    for doc in docs:
        title = _normalize_text(doc.get("title") or "")
        content = _normalize_text(doc.get("content") or "")
        score = _score(q, f"{title} {content}")
        if score <= 0:
            continue
        hits.append(
            {
                **doc,
                "snippet": content[:220],
                "channel": "private_lexical",
                "score": round(float(score), 4),
                "text_score": round(float(score), 4),
                "source_type": "private",
            }
        )

    hits.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return _dedupe_hits(hits, top_k=max(1, int(top_k or 3)), max_per_title=2)


def _query_graph_context(user_id: str, concepts, limit: int = 8):
    concept_list = [str(item).strip() for item in (concepts or []) if str(item).strip()]
    if not concept_list:
        return []

    try:
        store = _get_neo4j_store()
        return store.query_graph_rag_context(user_id, concept_list, limit=limit) or []
    except Exception:
        return []


def _hit_key(row, fallback_index: int = 0):
    doc_id = str(row.get("doc_id") or row.get("source_doc_id") or "").strip()
    if doc_id:
        return f"doc::{doc_id}"
    title = _normalize_text(row.get("title") or "")
    snippet = _normalize_text(row.get("snippet") or row.get("content") or "")
    return f"fp::{title}::{snippet[:120]}::{fallback_index}"


def _merge_graph_context_into_hits(query: str, mode: str, text_hits, graph_context):
    merged = {}
    for index, row in enumerate(text_hits, start=1):
        item = dict(row)
        item.setdefault("source_doc_id", str(item.get("doc_id") or ""))
        item.setdefault("snippet", _normalize_text(item.get("content") or "")[:220])
        item["text_score"] = round(float(item.get("text_score", item.get("score", 0.0)) or 0.0), 4)
        item["graph_score"] = round(float(item.get("graph_score", 0.0) or 0.0), 4)
        item["matched_concepts"] = list(item.get("matched_concepts", []) or [])
        item["graph_relations"] = list(item.get("graph_relations", []) or [])
        merged[_hit_key(item, fallback_index=index)] = item

    for ctx in graph_context:
        if not isinstance(ctx, dict):
            continue

        doc_id = str(ctx.get("doc_id") or ctx.get("source_doc_id") or "").strip()
        relations = ctx.get("relations", []) if isinstance(ctx.get("relations", []), list) else []
        if not doc_id and not relations:
            continue

        key = _hit_key(
            {
                "doc_id": doc_id,
                "source_doc_id": doc_id,
                "title": ctx.get("doc_title"),
                "content": ctx.get("doc_content"),
            },
            fallback_index=len(merged) + 1,
        )

        if key not in merged:
            if mode == "dense_vector" or not doc_id:
                continue
            doc_title = _normalize_text(ctx.get("doc_title") or ctx.get("concept") or "图谱文档")
            doc_content = _normalize_text(ctx.get("doc_content") or "")
            lexical_score = _score(query, f"{doc_title} {doc_content}")
            merged[key] = {
                "doc_id": doc_id,
                "source_doc_id": doc_id,
                "title": doc_title,
                "content": doc_content,
                "snippet": doc_content[:220],
                "source": _normalize_text(ctx.get("doc_source") or "neo4j_graph"),
                "content_type": "graph_document",
                "timestamp": "",
                "channel": "graph_rag",
                "score": round(float(lexical_score), 4),
                "text_score": round(float(lexical_score), 4),
                "graph_score": 0.0,
                "source_type": "private",
                "tags": ctx.get("doc_tags", []) if isinstance(ctx.get("doc_tags", []), list) else [],
                "topics": [],
                "matched_concepts": [],
                "graph_relations": [],
            }

        hit = merged[key]
        similarity = round(float(ctx.get("similarity_to_query", 0.0) or 0.0), 4)
        hit["graph_score"] = round(max(float(hit.get("graph_score", 0.0) or 0.0), similarity), 4)

        concept = _normalize_text(ctx.get("concept") or "")
        if concept and concept not in hit["matched_concepts"]:
            hit["matched_concepts"].append(concept)
        if concept and concept not in (hit.get("topics") or []):
            hit.setdefault("topics", []).append(concept)

        for rel in relations:
            if not isinstance(rel, dict):
                continue
            rel_item = {
                "neighbor": _normalize_text(rel.get("neighbor") or ""),
                "relation": _normalize_text(rel.get("relation") or "相关") or "相关",
            }
            if not rel_item["neighbor"]:
                continue
            if rel_item not in hit["graph_relations"]:
                hit["graph_relations"].append(rel_item)

    merged_rows = []
    for row in merged.values():
        text_score = float(row.get("text_score", row.get("score", 0.0)) or 0.0)
        graph_score = float(row.get("graph_score", 0.0) or 0.0)
        channel = str(row.get("channel") or "")

        if mode == "lexical":
            hybrid_score = 0.72 * text_score + 0.28 * graph_score
        elif mode == "dense_vector":
            hybrid_score = 0.9 * text_score + 0.1 * graph_score
        elif channel == "public_vector":
            hybrid_score = 0.7 * text_score + 0.1 * graph_score
        elif channel == "graph_rag":
            hybrid_score = 0.4 * text_score + 0.55 * graph_score
        else:
            hybrid_score = 0.55 * text_score + 0.35 * graph_score

        if graph_score > 0 and text_score <= 0:
            hybrid_score = max(hybrid_score, 0.45 * graph_score)

        row["hybrid_score"] = round(min(1.0, max(0.0, hybrid_score)), 4)
        row["matched_concepts"] = row.get("matched_concepts", [])[:6]
        row["graph_relations"] = row.get("graph_relations", [])[:6]
        merged_rows.append(row)

    merged_rows.sort(
        key=lambda item: (
            item.get("hybrid_score", 0.0),
            item.get("graph_score", 0.0),
            item.get("text_score", 0.0),
        ),
        reverse=True,
    )
    return merged_rows


def search_kb(user_id: str, query: str, top_k: int = 3, search_mode: str = "hybrid"):
    req_start_ts = _now_ts()
    uid = _normalize_private_user_id(user_id)
    q = _normalize_text(query)
    mode = _normalize_text(search_mode).lower() or "hybrid"
    if mode not in {"hybrid", "dense_vector", "lexical"}:
        mode = "hybrid"

    top = max(1, min(10, int(top_k or 3)))
    recall_k = max(top * 4, 8)
    docs = _collect_docs(uid) if uid else []

    private_recall = _recall_private_hits(q, docs, recall_k) if uid else []
    private_vector_recall = _search_private_vector_chunks(uid, q, docs, top_k=recall_k) if (uid and mode != "lexical") else []

    public_state = _load_public_kb_once() if mode != "lexical" else {"enabled": False, "chunks": [], "error": ""}
    public_recall = _search_public_chunks(q, top_k=recall_k) if mode != "lexical" else []
    public_source = "public_vector" if public_recall else ("public_vector" if public_state.get("enabled") else "unavailable")
    if not public_recall and not private_recall and not private_vector_recall:
        public_demo_recall = _search_public_demo_chunks(q, top_k=recall_k)
        if public_demo_recall:
            public_recall = public_demo_recall
            public_source = "demo_fallback"

    base_hits = []
    if mode == "lexical":
        base_hits.extend(private_recall)
        base_hits.extend(public_recall)
    elif mode == "dense_vector":
        base_hits.extend(private_vector_recall)
        base_hits.extend(public_recall)
    else:
        base_hits.extend(private_recall)
        base_hits.extend(private_vector_recall)
        base_hits.extend(public_recall)

    concept_seed_rows = private_vector_recall[:4] + private_recall[:4] + public_recall[:3]
    graph_concepts = _extract_graph_concepts(q, candidate_rows=concept_seed_rows, limit=max(4, top * 2))
    graph_context = _query_graph_context(uid, graph_concepts, limit=max(top * 3, 8)) if uid else []

    merged = _merge_graph_context_into_hits(q, mode, base_hits, graph_context)
    sliced = _dedupe_hits(merged, top_k=top)

    for row in sliced:
        row["snippet"] = row.get("snippet") or _normalize_text(row.get("content", ""))[:220]
        row.pop("content", None)

    query_time_ms = int(round((_now_ts() - req_start_ts) * 1000.0))

    total_score = sum(float(row.get("hybrid_score", 0.0) or 0.0) for row in sliced)
    graph_score_total = sum(float(row.get("graph_score", 0.0) or 0.0) for row in sliced)
    graph_contribution_rate = round(min(1.0, graph_score_total / max(total_score, 1e-6)), 4) if sliced else 0.0
    public_doc_count = len(public_state.get("chunks", [])) if public_state.get("enabled", False) else (
        len(_get_public_demo_chunks()) if public_source == "demo_fallback" else 0
    )

    return {
        "query": q,
        "search_mode": mode,
        "query_time_ms": query_time_ms,
        "total_docs": len(docs),
        "public_docs": public_doc_count,
        "public_source": public_source,
        "retrieval_mode": mode,
        "graph_query_concepts": graph_concepts,
        "hits": sliced,
        "graph_context": graph_context,
        "graph_contribution_rate": graph_contribution_rate,
    }
