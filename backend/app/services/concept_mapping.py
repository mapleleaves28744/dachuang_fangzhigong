import re
from collections import Counter
from difflib import SequenceMatcher


DEFAULT_METHOD_INFO = {
    "extract_method": "keyword_rule",
    "similarity_method": "substring+keyword_overlap+sequence_match",
    "merge_method": "normalize_equal|prefix_suffix|sequence_match>=0.82",
    "model": "none",
    "bert_enabled": False,
}

DEFAULT_MATCH_THRESHOLDS = {
    "question": 0.68,
    "video": 0.64,
    "note": 0.60,
    "generic": 0.65,
}

DEFAULT_FALLBACK_CONFIDENCE = {
    "question": 0.58,
    "video": 0.56,
    "note": 0.55,
    "generic": 0.56,
}

_GENERIC_PATTERNS = (
    "关于",
    "什么是",
    "为什么",
    "怎么",
    "如何",
    "题目",
    "例题",
    "练习",
    "讲解",
    "视频",
    "字幕",
    "标题",
    "笔记",
    "解析",
    "专题",
    "课程",
    "知识点",
    "学习",
    "内容",
    "截图",
    "ocr",
)


def normalize_mapping_text(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _build_stopword_keys(stopwords):
    result = set()
    for item in stopwords if isinstance(stopwords, (list, set, tuple)) else []:
        raw = str(item or "").strip()
        key = normalize_mapping_text(raw)
        if raw:
            result.add(raw)
        if key:
            result.add(key)
    return result


def _looks_like_section_label(token):
    text = str(token or "").strip()
    if not text:
        return False
    return bool(re.fullmatch(r"第[一二三四五六七八九十百0-9]+[章节课讲题]", text))


def _clean_keyword(token, stopword_keys):
    raw = str(token or "").strip()
    if not raw:
        return ""

    raw = raw.strip("，。！？；：、（）()[]【】<>《》\"'")
    key = normalize_mapping_text(raw)
    if not key:
        return ""
    if len(key) < 2:
        return ""
    if key.isdigit():
        return ""
    if _looks_like_section_label(raw):
        return ""
    if raw in stopword_keys or key in stopword_keys:
        return ""
    if re.fullmatch(r"[A-Za-z]{1,2}", raw):
        return ""
    return raw


def _split_token_fragments(token):
    text = str(token or "").strip()
    if not text:
        return []

    working = text
    for marker in _GENERIC_PATTERNS:
        working = working.replace(marker, " ")

    pieces = []
    for part in re.split(r"(?:的|与|和|及|并|或|在|将|把|对|是|请|从|到|中|里|上|下|\s+)", working):
        item = str(part or "").strip()
        if item:
            pieces.append(item)

    if text not in pieces:
        pieces.insert(0, text)
    return pieces


def extract_text_keywords(text, stopwords=None, max_keywords=12):
    source_text = str(text or "").strip()
    if not source_text:
        return []

    stopword_keys = _build_stopword_keys(stopwords)
    raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,16}|[A-Za-z][A-Za-z0-9_+\-]{2,24}", source_text)

    expanded_tokens = []
    for token in raw_tokens:
        for part in _split_token_fragments(token):
            expanded_tokens.append(part)

    counts = Counter()
    display_map = {}
    order = []

    for token in expanded_tokens:
        cleaned = _clean_keyword(token, stopword_keys)
        if not cleaned:
            continue
        key = normalize_mapping_text(cleaned)
        counts[key] += 1
        if key not in display_map:
            display_map[key] = cleaned
            order.append(key)

    ranked = sorted(
        order,
        key=lambda key: (-counts.get(key, 0), -len(display_map.get(key, "")), order.index(key)),
    )
    return [display_map[key] for key in ranked[:max(1, int(max_keywords or 12))]]


def _is_similar_label(left, right, similarity_threshold=0.82):
    left_key = normalize_mapping_text(left)
    right_key = normalize_mapping_text(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True

    shorter, longer = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
    if len(shorter) >= 2 and (longer.startswith(shorter) or longer.endswith(shorter)) and (len(longer) - len(shorter) <= 2):
        return True

    if len(shorter) >= 3 and SequenceMatcher(None, left_key, right_key).ratio() >= float(similarity_threshold):
        return True
    return False


def _pick_better_label(current, candidate, known_label_keys=None):
    known_keys = known_label_keys or set()
    current_key = normalize_mapping_text(current)
    candidate_key = normalize_mapping_text(candidate)

    current_known = current_key in known_keys
    candidate_known = candidate_key in known_keys
    if candidate_known and not current_known:
        return candidate
    if current_known and not candidate_known:
        return current

    if len(candidate_key) < len(current_key):
        return candidate
    if len(candidate_key) > len(current_key):
        return current
    return current


def merge_similar_labels(labels, known_labels=None, similarity_threshold=0.82):
    known_keys = {normalize_mapping_text(item) for item in (known_labels or []) if normalize_mapping_text(item)}
    merged = []

    for raw in labels if isinstance(labels, list) else []:
        label = str(raw or "").strip()
        if not label:
            continue

        matched_index = -1
        for idx, current in enumerate(merged):
            if _is_similar_label(current, label, similarity_threshold=similarity_threshold):
                matched_index = idx
                break

        if matched_index < 0:
            merged.append(label)
            continue

        merged[matched_index] = _pick_better_label(
            merged[matched_index],
            label,
            known_label_keys=known_keys,
        )

    return merged


def build_concept_profiles(concept_sources, stopwords=None, max_keywords_per_concept=12):
    concept_map = {}

    for raw in concept_sources if isinstance(concept_sources, list) else []:
        if not isinstance(raw, dict):
            continue
        concept = str(raw.get("concept") or "").strip()
        if not concept:
            continue

        key = normalize_mapping_text(concept)
        if not key:
            continue

        bucket = concept_map.setdefault(
            key,
            {
                "concept": concept,
                "descriptions": [],
                "aliases": [],
                "support_texts": [],
            },
        )

        if len(normalize_mapping_text(concept)) < len(normalize_mapping_text(bucket.get("concept") or "")):
            bucket["concept"] = concept

        description = str(raw.get("description") or "").strip()
        if description:
            bucket["descriptions"].append(description)

        for alias in raw.get("aliases", []) if isinstance(raw.get("aliases"), list) else []:
            alias_text = str(alias or "").strip()
            if alias_text:
                bucket["aliases"].append(alias_text)

        for text in raw.get("support_texts", []) if isinstance(raw.get("support_texts"), list) else []:
            support = str(text or "").strip()
            if support:
                bucket["support_texts"].append(support)

    known_labels = [item["concept"] for item in concept_map.values()]
    profiles = []

    for bucket in concept_map.values():
        concept = bucket["concept"]
        seed_labels = [concept, *bucket["aliases"]]
        seed_labels = merge_similar_labels(seed_labels, known_labels=known_labels)

        keyword_candidates = []
        for text in bucket["descriptions"] + bucket["support_texts"]:
            keyword_candidates.extend(extract_text_keywords(text, stopwords=stopwords, max_keywords=max_keywords_per_concept))

        merged_keywords = merge_similar_labels(
            [concept, *seed_labels, *keyword_candidates],
            known_labels=known_labels,
        )
        merged_keywords = merged_keywords[:max(4, int(max_keywords_per_concept or 12))]

        alias_keys = [normalize_mapping_text(item) for item in seed_labels if normalize_mapping_text(item)]
        keyword_keys = [normalize_mapping_text(item) for item in merged_keywords if normalize_mapping_text(item)]

        profiles.append({
            "concept": concept,
            "aliases": seed_labels,
            "keywords": merged_keywords,
            "alias_keys": list(dict.fromkeys(alias_keys)),
            "keyword_keys": list(dict.fromkeys(keyword_keys)),
        })

    profiles.sort(key=lambda item: (-len(normalize_mapping_text(item.get("concept"))), item.get("concept", "")))
    return profiles


def _score_concept_profile(match_text, text_keywords, profile, content_type="generic"):
    text_key = normalize_mapping_text(match_text)
    text_keyword_keys = [normalize_mapping_text(item) for item in text_keywords if normalize_mapping_text(item)]

    exact_hit = 1.0 if any(alias_key and alias_key in text_key for alias_key in profile.get("alias_keys", [])) else 0.0

    keyword_hits = 0
    for keyword_key in profile.get("keyword_keys", []):
        if not keyword_key:
            continue
        if keyword_key in text_key:
            keyword_hits += 1
            continue
        if any(
            len(keyword_key) >= 3 and len(text_kw) >= 3 and SequenceMatcher(None, keyword_key, text_kw).ratio() >= 0.88
            for text_kw in text_keyword_keys
        ):
            keyword_hits += 1

    overlap_base = max(1, min(4, len(profile.get("keyword_keys", []))))
    overlap_score = min(1.0, keyword_hits / float(overlap_base))

    fuzzy_score = 0.0
    compare_keys = profile.get("alias_keys", [])[:6] + profile.get("keyword_keys", [])[:8]
    for text_kw in text_keyword_keys:
        for concept_kw in compare_keys:
            if not text_kw or not concept_kw:
                continue
            fuzzy_score = max(fuzzy_score, SequenceMatcher(None, text_kw, concept_kw).ratio())

    if exact_hit:
        score = 0.88 + overlap_score * 0.07 + fuzzy_score * 0.05
    else:
        score = overlap_score * 0.55 + fuzzy_score * 0.45

    if content_type == "note" and exact_hit:
        score += 0.02

    if content_type == "question" and len(profile.get("concept", "")) >= 3 and exact_hit:
        score += 0.01

    return round(max(0.0, min(1.0, score)), 3), {
        "exact_hit": exact_hit,
        "overlap_score": round(overlap_score, 3),
        "fuzzy_score": round(fuzzy_score, 3),
    }


def map_text_to_concept(raw_content, concept_profiles, stopwords=None, content_type="generic"):
    original = str(raw_content or "").strip()
    if not original:
        return {"原始内容": "", "知识点": "", "置信度": 0.0}

    text_keywords = extract_text_keywords(original, stopwords=stopwords, max_keywords=12)
    best_concept = ""
    best_score = 0.0

    for profile in concept_profiles if isinstance(concept_profiles, list) else []:
        score, _ = _score_concept_profile(
            original,
            text_keywords,
            profile,
            content_type=content_type,
        )
        if score > best_score:
            best_concept = str(profile.get("concept") or "").strip()
            best_score = score

    threshold = DEFAULT_MATCH_THRESHOLDS.get(content_type, DEFAULT_MATCH_THRESHOLDS["generic"])
    if best_concept and best_score >= threshold:
        return {
            "原始内容": original,
            "知识点": best_concept,
            "置信度": round(best_score, 3),
        }

    fallback_keywords = merge_similar_labels(
        list(text_keywords),
        known_labels=[item.get("concept") for item in concept_profiles if isinstance(item, dict)],
    )
    fallback_concept = str(fallback_keywords[0] or "").strip() if fallback_keywords else ""
    fallback_confidence = DEFAULT_FALLBACK_CONFIDENCE.get(content_type, DEFAULT_FALLBACK_CONFIDENCE["generic"])
    if best_concept and best_score >= fallback_confidence:
        fallback_concept = best_concept

    return {
        "原始内容": original,
        "知识点": fallback_concept,
        "置信度": round(best_score if best_concept and best_score >= fallback_confidence else (fallback_confidence if fallback_concept else 0.0), 3),
    }


def map_learning_items(items, concept_profiles, stopwords=None):
    results = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            raw_content = item
            match_text = raw_content
            content_type = "generic"
        elif isinstance(item, dict):
            raw_content = str(item.get("original_content") or item.get("text") or "").strip()
            match_text = str(item.get("match_text") or raw_content).strip()
            content_type = str(item.get("content_type") or "generic").strip().lower() or "generic"
        else:
            continue

        results.append(
            map_text_to_concept(
                raw_content=match_text or raw_content,
                concept_profiles=concept_profiles,
                stopwords=stopwords,
                content_type=content_type,
            )
        )
        if raw_content and results[-1].get("原始内容") != raw_content:
            results[-1]["原始内容"] = raw_content
    return results
