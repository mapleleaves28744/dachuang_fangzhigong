import math
import os
import json
import re
import time
import uuid

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from .database import append_user_event, get_user_event_list, get_user_space_payload


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9_]+")
_CACHE = {}
_CACHE_TTL_SECONDS = 45
_PUBLIC_QUERY_CACHE_TTL_SECONDS = 180

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PRO_KB_DIR = os.path.join(_BACKEND_DIR, "data", "pro_kb")
_PRO_KB_FAISS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_faiss.index")
_PRO_KB_TEXTS_FILE = os.path.join(_PRO_KB_DIR, "pro_kb_texts.json")
_PUBLIC_VECTOR_ENABLED = str(os.getenv("KB_PUBLIC_VECTOR_ENABLED", "true")).strip().lower() == "true"
_PUBLIC_VECTOR_MODEL_NAME = os.getenv("KB_PUBLIC_VECTOR_MODEL", "BAAI/bge-small-zh-v1.5").strip() or "BAAI/bge-small-zh-v1.5"

_FAISS_INDEX = None
_EMBEDDING_MODEL = None
_PUBLIC_KB = {
	"loaded": False,
	"enabled": False,
	"chunks": [],
	"error": "",
}


def _now_ts():
	return time.time()


def _normalize_text(value: str) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(text: str):
	return [t.lower() for t in _TOKEN_PATTERN.findall(str(text or "")) if t]


def _score(query: str, text: str):
	q = _normalize_text(query)
	t = _normalize_text(text)
	if not q or not t:
		return 0.0

	q_tokens = _tokenize(q)
	t_tokens = _tokenize(t)
	if not q_tokens or not t_tokens:
		return 0.0

	q_set = set(q_tokens)
	t_set = set(t_tokens)
	overlap = len(q_set & t_set)
	if overlap <= 0:
		return 0.0

	jaccard = overlap / max(1, len(q_set | t_set))
	cover = overlap / max(1, len(q_set))
	exact_bonus = 0.15 if q in t else 0.0
	length_penalty = 1.0 / max(1.0, math.log(len(t_tokens) + 3, 3))
	return round((0.55 * cover + 0.35 * jaccard + exact_bonus) * (0.65 + 0.35 * length_penalty), 4)


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
		# 标题标准化：去空白并统一大小写；保留 K 编号，避免不同题卡误合并
		return _normalize_text(title).lower()

	# 第一轮：严格多样性优先（同标题最多 max_per_title 条）
	for row in rows:
		doc_id = str(row.get("doc_id") or "").strip()
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

	# 第二轮：若结果不足，再放宽标题约束补齐（仍保持内容指纹去重）
	for row in rows:
		doc_id = str(row.get("doc_id") or "").strip()
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

		if _EMBEDDING_MODEL is None:
			# Fail fast under unstable network: only use locally cached model.
			try:
				_EMBEDDING_MODEL = SentenceTransformer(_PUBLIC_VECTOR_MODEL_NAME, local_files_only=True)
			except TypeError:
				# Backward compatibility for sentence-transformers versions without local_files_only.
				os.environ.setdefault("HF_HUB_OFFLINE", "1")
				_EMBEDDING_MODEL = SentenceTransformer(_PUBLIC_VECTOR_MODEL_NAME)
		if _FAISS_INDEX is None:
			_FAISS_INDEX = faiss.read_index(_PRO_KB_FAISS_FILE)

		with open(_PRO_KB_TEXTS_FILE, "r", encoding="utf-8") as f:
			chunks = json.load(f)

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
	if not chunks or _FAISS_INDEX is None or _EMBEDDING_MODEL is None:
		return []

	try:
		query_vector = _EMBEDDING_MODEL.encode([q])
		query_vector = np.array(query_vector).astype("float32")
		recall_k = max(20, int(top_k or 3) * 10)
		distances, indices = _FAISS_INDEX.search(query_vector, recall_k)
	except Exception:
		return []

	rows = []
	for i, idx in enumerate(indices[0]):
		if idx < 0 or idx >= len(chunks):
			continue
		row = chunks[idx]
		text = _normalize_text(row.get("text") or "")
		title = _normalize_text(row.get("knowledge_point") or row.get("chapter") or "公共知识片段")
		if not text and not title:
			continue

		vector_score = 1.0 / (1.0 + float(distances[0][i]))
		lexical_score = _score(q, f"{title} {text}")
		hybrid = 0.75 * float(vector_score) + 0.25 * float(lexical_score)

		rows.append(
			{
				"doc_id": str(row.get("chunk_id") or row.get("card_id") or f"public_{idx}"),
				"title": title,
				"content": text,
				"snippet": text[:220],
				"source": "public_pro_kb",
				"content_type": _normalize_text(row.get("chunk_type") or "chunk"),
				"timestamp": "",
				"channel": "public_vector",
				"score": round(float(hybrid), 4),
				"vector_score": round(float(vector_score), 4),
				"lexical_score": round(float(lexical_score), 4),
				"discipline": _normalize_text(row.get("discipline") or ""),
				"chapter": _normalize_text(row.get("chapter") or ""),
				"tags": row.get("tags", []) if isinstance(row.get("tags", []), list) else [],
			}
		)

	rows.sort(key=lambda x: x.get("score", 0.0), reverse=True)
	rows = _dedupe_hits(rows, top_k=int(top_k or 3))
	return _cache_set(cache_key, rows, ttl=_PUBLIC_QUERY_CACHE_TTL_SECONDS)


def ingest_kb_note(user_id: str, title: str, content: str, source: str = "agent_kb", tags=None):
	uid = _normalize_text(user_id) or "default_user"
	ttl_title = _normalize_text(title)[:120] or "知识笔记"
	body = _normalize_text(content)
	if not body:
		raise ValueError("content 不能为空")

	item = {
		"id": str(uuid.uuid4()),
		"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
		"content_type": "kb_note",
		"title": ttl_title,
		"content": body,
		"source": _normalize_text(source)[:40] or "agent_kb",
		"tags": [str(x).strip() for x in (tags or []) if str(x).strip()][:8],
	}
	append_user_event(uid, "content", item)
	_CACHE.pop(("docs", uid), None)
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
				"title": title,
				"content": content,
				"source": _normalize_text(row.get("source") or "content_log"),
				"content_type": _normalize_text(row.get("content_type") or "note"),
				"timestamp": _normalize_text(row.get("timestamp") or ""),
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
					"title": _normalize_text(item.get("name") or "空间资料"),
					"content": text,
					"source": "space",
					"content_type": _normalize_text(item.get("kind") or "document"),
					"timestamp": str(item.get("updatedAt") or item.get("addedAt") or ""),
				}
			)

	return _cache_set(cache_key, docs)


def search_kb(user_id: str, query: str, top_k: int = 3, search_mode: str = "hybrid"):
	req_start_ts = _now_ts()
	uid = _normalize_text(user_id) or "default_user"
	q = _normalize_text(query)
	mode = _normalize_text(search_mode).lower() or "hybrid"
	if mode not in {"hybrid", "dense_vector", "lexical"}:
		mode = "hybrid"

	top = max(1, min(10, int(top_k or 3)))
	docs = _collect_docs(uid)

	private_hits = []
	for doc in docs:
		score = _score(q, doc.get("title", "") + " " + doc.get("content", ""))
		if score <= 0:
			continue
		private_hits.append({**doc, "score": score, "channel": "private_lexical"})

	public_hits = _search_public_chunks(q, top_k=top)

	merged = []
	if mode == "lexical":
		for row in private_hits:
			merged.append({**row, "hybrid_score": round(float(row.get("score", 0.0)), 4), "source_type": "private"})
	elif mode == "dense_vector":
		for row in public_hits:
			merged.append({**row, "hybrid_score": round(float(row.get("score", 0.0)), 4), "source_type": "public"})
	else:
		for row in private_hits:
			hybrid = 0.45 * float(row.get("score", 0.0))
			merged.append({**row, "hybrid_score": round(hybrid, 4), "source_type": "private"})
		for row in public_hits:
			hybrid = 0.55 * float(row.get("score", 0.0))
			merged.append({**row, "hybrid_score": round(hybrid, 4), "source_type": "public"})

	merged.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
	sliced = _dedupe_hits(merged, top_k=top)

	for row in sliced:
		row["snippet"] = row.get("snippet") or _normalize_text(row.get("content", ""))[:220]
		row.pop("content", None)

	public_state = _load_public_kb_once()
	query_time_ms = int(round((_now_ts() - req_start_ts) * 1000.0))

	return {
		"query": q,
		"search_mode": mode,
		"query_time_ms": query_time_ms,
		"total_docs": len(docs),
		"public_docs": len(public_state.get("chunks", [])) if public_state.get("enabled", False) else 0,
		"retrieval_mode": mode,
		"hits": sliced,
		"graph_context": [],
		"graph_contribution_rate": 0.0,
	}
