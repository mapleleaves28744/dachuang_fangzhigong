import argparse
import json
import os
import sys
import time
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)


def load_simple_env_files():
    candidates = [
        os.path.join(BACKEND_DIR, "config", ".env"),
        os.path.join(BACKEND_DIR, ".env"),
        os.path.join(PROJECT_ROOT, ".env"),
    ]

    for env_path in candidates:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if value and not (value.startswith('"') or value.startswith("'")) and " #" in value:
                        value = value.split(" #", 1)[0].rstrip()
                    value = value.strip().strip('"').strip("'")
                    if key and not os.getenv(key):
                        os.environ[key] = value
        except Exception:
            continue


load_simple_env_files()

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.knowledge_base import ingest_kb_note, search_kb


def load_cases(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("cases 文件必须是 JSON 数组")
    return [x for x in data if isinstance(x, dict)]


def contains_any(text: str, words):
    low = str(text or "").lower()
    for w in words:
        if str(w or "").strip().lower() in low:
            return True
    return False


def keyword_coverage(evidence_text: str, expected_keywords):
    kws = [str(x).strip() for x in (expected_keywords or []) if str(x).strip()]
    if not kws:
        return 1.0
    low = str(evidence_text or "").lower()
    hit = 0
    for kw in kws:
        if kw.lower() in low:
            hit += 1
    return round(hit / max(1, len(kws)), 4)


def build_evidence_text(hit: dict):
    fields = [
        hit.get("title", ""),
        hit.get("snippet", ""),
        hit.get("chapter", ""),
        hit.get("discipline", ""),
        " ".join(hit.get("tags", [])) if isinstance(hit.get("tags", []), list) else "",
    ]
    return " ".join([str(x) for x in fields if x])


def evaluate_case(case: dict, top_k: int):
    user_id = str(case.get("user_id") or "eval_hybrid_user").strip()
    query = str(case.get("query") or "").strip()
    if not query:
        return {
            "id": str(case.get("id") or "unknown"),
            "error": "query 为空",
        }

    private_note = case.get("private_note")
    if isinstance(private_note, dict) and str(private_note.get("content") or "").strip():
        ingest_kb_note(
            user_id=user_id,
            title=str(private_note.get("title") or "评测私有笔记"),
            content=str(private_note.get("content") or ""),
            tags=private_note.get("tags") or [],
            source="eval_hybrid",
        )

    t0 = time.perf_counter()
    out = search_kb(user_id, query, top_k=top_k)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    hits = out.get("hits", []) if isinstance(out, dict) else []
    graph_context = out.get("graph_context", []) if isinstance(out, dict) else []
    channels = [str(x.get("channel") or "") for x in hits if isinstance(x, dict)]

    expected_keywords = case.get("expected_keywords") or []
    expected_channels = case.get("expected_channels") or []

    evidence_blob = " ".join([build_evidence_text(x) for x in hits if isinstance(x, dict)])
    kw_cov = keyword_coverage(evidence_blob, expected_keywords)

    channel_hit = 1.0
    if isinstance(expected_channels, list) and expected_channels:
        channel_hit = 1.0 if all(ch in channels for ch in expected_channels) else 0.0

    top_hybrid = 0.0
    if hits and isinstance(hits[0], dict):
        top_hybrid = float(hits[0].get("hybrid_score") or 0.0)

    score = round(0.5 * kw_cov + 0.3 * channel_hit + 0.2 * (1.0 if len(graph_context) > 0 else 0.0), 4)

    return {
        "id": str(case.get("id") or "unknown"),
        "query": query,
        "user_id": user_id,
        "latency_ms": latency_ms,
        "hit_count": len(hits),
        "graph_context_count": len(graph_context),
        "channels": sorted(list(set(channels))),
        "keyword_coverage": kw_cov,
        "channel_match": channel_hit,
        "top_hybrid_score": round(top_hybrid, 4),
        "score": score,
    }


def summarize(rows):
    valid = [x for x in rows if "error" not in x]
    if not valid:
        return {
            "cases": 0,
            "hit_at_k": 0.0,
            "public_hit_rate": 0.0,
            "private_hit_rate": 0.0,
            "graph_context_rate": 0.0,
            "avg_keyword_coverage": 0.0,
            "avg_top_hybrid_score": 0.0,
            "avg_score": 0.0,
            "avg_latency_ms": 0.0,
        }

    n = len(valid)

    def avg(name):
        return round(sum(float(x.get(name) or 0.0) for x in valid) / n, 4)

    return {
        "cases": n,
        "hit_at_k": round(sum(1 for x in valid if int(x.get("hit_count") or 0) > 0) / n, 4),
        "public_hit_rate": round(sum(1 for x in valid if "public_vector" in (x.get("channels") or [])) / n, 4),
        "private_hit_rate": round(sum(1 for x in valid if "private_lexical" in (x.get("channels") or [])) / n, 4),
        "graph_context_rate": round(sum(1 for x in valid if int(x.get("graph_context_count") or 0) > 0) / n, 4),
        "avg_keyword_coverage": avg("keyword_coverage"),
        "avg_top_hybrid_score": avg("top_hybrid_score"),
        "avg_score": avg("score"),
        "avg_latency_ms": avg("latency_ms"),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate hybrid retrieval quality for public+private+graph pipeline")
    parser.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "hybrid_retrieval_eval_cases.json"),
        help="Path to retrieval evaluation cases JSON",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "hybrid_retrieval_report.json"),
        help="Output report path",
    )
    parser.add_argument("--top_k", type=int, default=5, help="Top-K for search_kb")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    results = [evaluate_case(case, top_k=max(1, min(10, int(args.top_k or 5)))) for case in cases]
    summary = summarize(results)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "retrieval_mode": "hybrid",
        "top_k": max(1, min(10, int(args.top_k or 5))),
        "cases_file": args.cases,
        "summary": summary,
        "results": results,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("Hybrid retrieval eval done")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report={args.out}")


if __name__ == "__main__":
    main()
