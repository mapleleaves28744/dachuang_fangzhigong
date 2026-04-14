import json
import math
import os
import re
import threading
import time
import uuid

from .concept_mapping import extract_text_keywords
from .database import append_user_event, get_user_event_list, get_user_space_payload
from .neo4j_store import Neo4jGraphStore
from .topic_guard import filter_learning_topics


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9_]+")
_CACHE = {}
_CACHE_TTL_SECONDS = 45
_PUBLIC_QUERY_CACHE_TTL_SECONDS = 180
_GRAPH_SYNC_ASYNC = str(os.getenv("KB_GRAPH_SYNC_ASYNC", "false")).strip().lower() == "true"

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_FAISS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_faiss.index")
_PRO_KB_TEXTS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_texts.json")
_PUBLIC_VECTOR_ENABLED = str(os.getenv("KB_PUBLIC_VECTOR_ENABLED", "true")).strip().lower() == "true"
_PUBLIC_VECTOR_MODEL_NAME = os.getenv("KB_PUBLIC_VECTOR_MODEL", "BAAI/bge-small-zh-v1.5").strip() or "BAAI/bge-small-zh-v1.5"

_FAISS_INDEX = None
_EMBEDDING_MODEL = None
_FAISS_MODULE = None
_NUMPY_MODULE = None
_SENTENCE_TRANSFORMER_CLASS = None
_NEO4J_STORE = None
_PUBLIC_KB = {
    "loaded": False,
    "enabled": False,
    "chunks": [],
    "error": "",
}

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


def _load_public_vector_dependencies():
    global _FAISS_MODULE, _NUMPY_MODULE, _SENTENCE_TRANSFORMER_CLASS

    if _FAISS_MODULE is not None and _NUMPY_MODULE is not None and _SENTENCE_TRANSFORMER_CLASS is not None:
        return True, ""

    try:
        if _FAISS_MODULE is None:
            import faiss as faiss_module

            _FAISS_MODULE = faiss_module
        if _NUMPY_MODULE is None:
            import numpy as numpy_module

            _NUMPY_MODULE = numpy_module
        if _SENTENCE_TRANSFORMER_CLASS is None:
            from sentence_transformers import SentenceTransformer as sentence_transformer_class

            _SENTENCE_TRANSFORMER_CLASS = sentence_transformer_class
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, ""


def _load_public_kb_once():
    global _FAISS_INDEX, _EMBEDDING_MODEL

    if _PUBLIC_KB.get("loaded"):
        return _PUBLIC_KB

    payload = {
        "loaded": True,
        "enabled": False,
        "chunks": [],
        "error": "",
    }

    try:
        if not _PUBLIC_VECTOR_ENABLED:
            payload["error"] = "public vector disabled by env"
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        if not (os.path.exists(_PRO_KB_FAISS_FILE) and os.path.exists(_PRO_KB_TEXTS_FILE)):
            payload["error"] = "pro_kb artifacts missing"
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        deps_ready, deps_error = _load_public_vector_dependencies()
        if not deps_ready:
            payload["error"] = f"public vector unavailable: {deps_error}"
            _PUBLIC_KB.update(payload)
            return _PUBLIC_KB

        if _EMBEDDING_MODEL is None:
            try:
                _EMBEDDING_MODEL = _SENTENCE_TRANSFORMER_CLASS(_PUBLIC_VECTOR_MODEL_NAME, local_files_only=True)
            except TypeError:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                _EMBEDDING_MODEL = _SENTENCE_TRANSFORMER_CLASS(_PUBLIC_VECTOR_MODEL_NAME)
        if _FAISS_INDEX is None:
            _FAISS_INDEX = _FAISS_MODULE.read_index(_PRO_KB_FAISS_FILE)

        with open(_PRO_KB_TEXTS_FILE, "r", encoding="utf-8") as file_obj:
            chunks = json.load(file_obj)

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

    cache_key = ("public_search_dense", q, int(top_k or 3))
    cached_rows = _cache_get(cache_key)
    if cached_rows is not None:
        return cached_rows

    chunks = pub.get("chunks", [])
    if not chunks or _FAISS_INDEX is None or _EMBEDDING_MODEL is None or _NUMPY_MODULE is None:
        return []

    try:
        query_vector = _EMBEDDING_MODEL.encode([q])
        query_vector = _NUMPY_MODULE.array(query_vector).astype("float32")
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
    try:
        store = _get_neo4j_store()
        store.upsert_kb_note_graph(
            user_id=user_id,
            note_id=item.get("id"),
            title=item.get("title"),
            content=item.get("content"),
            concepts=item.get("topics") or item.get("tags") or [],
            source=item.get("source", "agent_kb"),
            tags=item.get("tags") or [],
        )
    except Exception:
        return False
    return True


def _dispatch_kb_note_graph_sync(user_id: str, item: dict):
    if _GRAPH_SYNC_ASYNC:
        worker = threading.Thread(target=_sync_kb_note_graph, args=(user_id, item), daemon=True)
        worker.start()
        return True
    return _sync_kb_note_graph(user_id, item)


def ingest_kb_note(user_id: str, title: str, content: str, source: str = "agent_kb", tags=None):
    uid = _normalize_text(user_id) or "default_user"
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
    _CACHE.pop(("docs", uid), None)
    _dispatch_kb_note_graph_sync(uid, item)
    return item


def _collect_docs(user_id: str):
    uid = _normalize_text(user_id) or "default_user"
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
        content = _normalize_text(row.get("content") or "")
        if not content:
            continue
        docs.append(
            {
                "doc_id": str(row.get("id") or ""),
                "source_doc_id": str(row.get("id") or ""),
                "title": title,
                "content": content,
                "source": _normalize_text(row.get("source") or "content_log"),
                "content_type": _normalize_text(row.get("content_type") or "note"),
                "timestamp": _normalize_text(row.get("timestamp") or ""),
                "tags": [str(x).strip() for x in (row.get("tags") or []) if str(x).strip()],
                "topics": [str(x).strip() for x in (row.get("topics") or []) if str(x).strip()],
            }
        )

    space_payload = get_user_space_payload(uid) or {}
    for space in space_payload.get("spaces", []) if isinstance(space_payload, dict) else []:
        if not isinstance(space, dict):
            continue
        for item in space.get("items", []) if isinstance(space.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("content") or item.get("summary") or "")
            if not text:
                continue
            docs.append(
                {
                    "doc_id": str(item.get("id") or ""),
                    "source_doc_id": str(item.get("id") or ""),
                    "title": _normalize_text(item.get("name") or "空间资料"),
                    "content": text,
                    "source": "space",
                    "content_type": _normalize_text(item.get("kind") or "document"),
                    "timestamp": str(item.get("updatedAt") or item.get("addedAt") or ""),
                    "tags": [str(x).strip() for x in (item.get("tags") or []) if str(x).strip()],
                    "topics": [str(x).strip() for x in (item.get("topics") or []) if str(x).strip()],
                }
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
    uid = _normalize_text(user_id) or "default_user"
    q = _normalize_text(query)
    mode = _normalize_text(search_mode).lower() or "hybrid"
    if mode not in {"hybrid", "dense_vector", "lexical"}:
        mode = "hybrid"

    top = max(1, min(10, int(top_k or 3)))
    recall_k = max(top * 4, 8)
    docs = _collect_docs(uid)

    private_recall = _recall_private_hits(q, docs, recall_k)
    public_recall = _search_public_chunks(q, top_k=recall_k) if mode != "lexical" else []

    base_hits = []
    if mode == "lexical":
        base_hits.extend(private_recall)
    elif mode == "dense_vector":
        base_hits.extend(public_recall)
    else:
        base_hits.extend(private_recall)
        base_hits.extend(public_recall)

    concept_seed_rows = private_recall[:4] + public_recall[:3]
    graph_concepts = _extract_graph_concepts(q, candidate_rows=concept_seed_rows, limit=max(4, top * 2))
    graph_context = _query_graph_context(uid, graph_concepts, limit=max(top * 3, 8))

    merged = _merge_graph_context_into_hits(q, mode, base_hits, graph_context)
    sliced = _dedupe_hits(merged, top_k=top)

    for row in sliced:
        row["snippet"] = row.get("snippet") or _normalize_text(row.get("content", ""))[:220]
        row.pop("content", None)

    public_state = _load_public_kb_once()
    query_time_ms = int(round((_now_ts() - req_start_ts) * 1000.0))

    total_score = sum(float(row.get("hybrid_score", 0.0) or 0.0) for row in sliced)
    graph_score_total = sum(float(row.get("graph_score", 0.0) or 0.0) for row in sliced)
    graph_contribution_rate = round(min(1.0, graph_score_total / max(total_score, 1e-6)), 4) if sliced else 0.0

    return {
        "query": q,
        "search_mode": mode,
        "query_time_ms": query_time_ms,
        "total_docs": len(docs),
        "public_docs": len(public_state.get("chunks", [])) if public_state.get("enabled", False) else 0,
        "retrieval_mode": mode,
        "graph_query_concepts": graph_concepts,
        "hits": sliced,
        "graph_context": graph_context,
        "graph_contribution_rate": graph_contribution_rate,
    }
