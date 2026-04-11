import argparse
import json
import os
import re
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
from app.services.neo4j_store import Neo4jGraphStore


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9_]+")


def tokenize(text: str):
    return [x.lower() for x in TOKEN_PATTERN.findall(str(text or "")) if x]


def load_cases(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("cases 文件必须是 JSON 数组")
    return [x for x in data if isinstance(x, dict)]


def flatten_graph_context(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append(
            " ".join(
                [
                    str(row.get("concept") or ""),
                    str(row.get("neighbor") or ""),
                    str(row.get("doc_title") or ""),
                    str(row.get("relation") or ""),
                ]
            ).strip()
        )
    return " ".join([x for x in out if x])


def flatten_hit_evidence(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        tags = row.get("tags", []) if isinstance(row.get("tags", []), list) else []
        out.append(
            " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("snippet") or ""),
                    str(row.get("chapter") or ""),
                    str(row.get("discipline") or ""),
                    " ".join([str(t) for t in tags]),
                ]
            ).strip()
        )
    return " ".join([x for x in out if x])


def compute_graph_recall(graph_text: str, expected_terms):
    terms = [str(x).strip().lower() for x in (expected_terms or []) if str(x).strip()]
    if not terms:
        return 1.0
    blob = str(graph_text or "").lower()
    hit = sum(1 for t in terms if t in blob)
    return round(hit / max(1, len(terms)), 4)


def compute_evidence_consistency(graph_text: str, hit_text: str):
    graph_tokens = set(tokenize(graph_text))
    hit_tokens = set(tokenize(hit_text))
    if not graph_tokens:
        return 0.0
    overlap = len(graph_tokens & hit_tokens)
    return round(overlap / max(1, len(graph_tokens)), 4)


def evaluate_case(case: dict, top_k: int, graph_store: Neo4jGraphStore):
    cid = str(case.get("id") or "unknown")
    user_id = str(case.get("user_id") or "eval_graph_user").strip()
    query = str(case.get("query") or "").strip()
    if not query:
        return {"id": cid, "error": "query 为空"}

    private_note = case.get("private_note")
    if isinstance(private_note, dict) and str(private_note.get("content") or "").strip():
        ingest_kb_note(
            user_id=user_id,
            title=str(private_note.get("title") or "图谱评测私有笔记"),
            content=str(private_note.get("content") or ""),
            tags=private_note.get("tags") or [],
            source="eval_graph",
        )

    graph_connected = bool(graph_store.ensure_connected(force=True))
    graph_last_error = str(graph_store.last_error or "")

    t0 = time.perf_counter()
    out = search_kb(user_id, query, top_k=top_k)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    hits = out.get("hits", []) if isinstance(out, dict) else []
    graph_context = out.get("graph_context", []) if isinstance(out, dict) else []

    graph_text = flatten_graph_context(graph_context)
    hit_text = flatten_hit_evidence(hits)
    expected_terms = case.get("expected_graph_terms") or []

    graph_recall = compute_graph_recall(graph_text, expected_terms)
    evidence_consistency = compute_evidence_consistency(graph_text, hit_text)

    score = round(
        0.4 * (1.0 if graph_connected else 0.0)
        + 0.35 * graph_recall
        + 0.25 * evidence_consistency,
        4,
    )

    return {
        "id": cid,
        "query": query,
        "user_id": user_id,
        "latency_ms": latency_ms,
        "graph_connected": graph_connected,
        "graph_last_error": graph_last_error,
        "graph_context_count": len(graph_context),
        "hit_count": len(hits),
        "graph_recall": graph_recall,
        "evidence_consistency": evidence_consistency,
        "score": score,
    }


def summarize(rows):
    valid = [x for x in rows if "error" not in x]
    if not valid:
        return {
            "cases": 0,
            "graph_connectivity_rate": 0.0,
            "graph_recall_rate": 0.0,
            "evidence_consistency_rate": 0.0,
            "graph_context_rate": 0.0,
            "avg_latency_ms": 0.0,
            "avg_score": 0.0,
        }

    n = len(valid)
    return {
        "cases": n,
        "graph_connectivity_rate": round(sum(1 for x in valid if x.get("graph_connected")) / n, 4),
        "graph_recall_rate": round(sum(float(x.get("graph_recall") or 0.0) for x in valid) / n, 4),
        "evidence_consistency_rate": round(sum(float(x.get("evidence_consistency") or 0.0) for x in valid) / n, 4),
        "graph_context_rate": round(sum(1 for x in valid if int(x.get("graph_context_count") or 0) > 0) / n, 4),
        "avg_latency_ms": round(sum(float(x.get("latency_ms") or 0.0) for x in valid) / n, 4),
        "avg_score": round(sum(float(x.get("score") or 0.0) for x in valid) / n, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate graph availability for hybrid retrieval")
    parser.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "graph_availability_eval_cases.json"),
        help="Path to graph availability eval cases",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "graph_availability_report.json"),
        help="Output report path",
    )
    parser.add_argument("--top_k", type=int, default=5, help="Top-K for search_kb")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    graph_store = Neo4jGraphStore()

    top_k = max(1, min(10, int(args.top_k or 5)))
    results = [evaluate_case(case, top_k=top_k, graph_store=graph_store) for case in cases]
    summary = summarize(results)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "top_k": top_k,
        "cases_file": args.cases,
        "summary": summary,
        "results": results,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("Graph availability eval done")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report={args.out}")


if __name__ == "__main__":
    main()
