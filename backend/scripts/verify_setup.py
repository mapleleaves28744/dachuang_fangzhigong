#!/usr/bin/env python3
"""
真实环境验证脚本：
1. 检查关键依赖是否可导入
2. 检查公共 KB 制品是否存在 / 是否是 Git LFS 指针
3. 实际写入一条私有资料并验证检索命中
4. 验证公共 KB 或 demo fallback 是否可用于检索
"""
import argparse
import importlib
import json
import os
import sys
import time
from typing import Dict


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def check_import(module_name: str) -> Dict[str, object]:
    try:
        importlib.import_module(module_name)
        return {"module": module_name, "ok": True, "error": ""}
    except Exception as exc:
        return {"module": module_name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _hit_text(hit: Dict[str, object]) -> str:
    return " ".join(
        str(hit.get(key) or "").strip()
        for key in ("title", "snippet", "channel", "source", "doc_id", "source_doc_id")
    ).strip()


def _private_probe_hit_ok(hit: Dict[str, object], ingested_item: Dict[str, object]) -> bool:
    if not isinstance(hit, dict):
        return False
    expected_id = str((ingested_item or {}).get("id") or "").strip()
    if expected_id and str(hit.get("source_doc_id") or "").strip() == expected_id:
        return True

    text = _hit_text(hit)
    required = ("链式法则", "复合函数", "求导")
    matched = sum(1 for item in required if item in text)
    return matched >= 2 and str(hit.get("source_type") or "").strip() == "private"


def _public_probe_hit_ok(hit: Dict[str, object]) -> bool:
    if not isinstance(hit, dict):
        return False
    text = _hit_text(hit)
    required = ("导数", "切线斜率")
    matched = sum(1 for item in required if item in text)
    return matched >= 1 and str(hit.get("source_type") or "").strip() == "public"


def _recommendation_key(text: str) -> str:
    raw = str(text or "").strip()
    lowered = raw.lower()
    if "git lfs" in lowered:
        return "git_lfs"
    if "demo fallback" in lowered or ("离线" in raw and "公共向量库" in raw):
        return "demo_fallback"
    if "pip install" in lowered or "缺少运行依赖" in raw:
        return "deps"
    if "私有资料入库" in raw:
        return "private_probe"
    return raw


def build_report(strict_public: bool = False):
    from app.services.knowledge_base import get_kb_readiness_report, ingest_kb_note, search_kb

    imports = {
        name: check_import(name)
        for name in ("numpy", "faiss", "sentence_transformers", "sklearn")
    }

    kb_readiness = get_kb_readiness_report()

    probe_user = f"verify_setup_probe_{int(time.time())}"
    probe_content = (
        "链式法则用于复合函数求导。做题时先识别外层函数和内层函数，"
        "再对外层求导并乘以内层导数，最后检查括号和中间变量。"
    )
    ingest_item = ingest_kb_note(
        user_id=probe_user,
        title="链式法则验证笔记",
        content=probe_content,
        source="verify_setup",
        tags=["链式法则", "复合函数"],
    )
    private_probe = search_kb(probe_user, "链式法则 复合函数 求导", top_k=3)
    private_hits = private_probe.get("hits", []) if isinstance(private_probe, dict) else []
    private_ok = any(_private_probe_hit_ok(hit, ingest_item) for hit in private_hits)

    public_probe = search_kb("verify_setup_public_probe", "导数 切线斜率", top_k=3)
    public_hits = [
        hit for hit in (public_probe.get("hits", []) if isinstance(public_probe, dict) else [])
        if str(hit.get("source_type") or "").strip() == "public"
    ]
    public_ok = any(_public_probe_hit_ok(hit) for hit in public_hits)

    public_vector_ready = bool((kb_readiness.get("public_vector", {}) or {}).get("ready"))
    demo_fallback_ready = bool((kb_readiness.get("demo_fallback", {}) or {}).get("ready"))

    overall_ok = bool(private_ok and (public_vector_ready or demo_fallback_ready or public_ok))
    if strict_public:
        overall_ok = bool(private_ok and public_vector_ready and public_ok)

    recommendations = list(kb_readiness.get("recommended_actions", []) or [])
    warnings = list(kb_readiness.get("warnings", []) or [])
    missing_imports = [name for name, item in imports.items() if not item.get("ok")]
    if "public_kb_artifact_is_git_lfs_pointer" in warnings:
        recommendations.append("运行 git lfs pull，或重新放置真实的 pro_kb 制品文件。")
    if not public_vector_ready and demo_fallback_ready:
        recommendations.append("当前可用 demo fallback 演示，但正式答辩前建议恢复真实公共向量库。")
    if not private_ok:
        recommendations.append("检查私有资料入库链路，确认 content 事件成功写入并触发检索缓存刷新。")
    if missing_imports:
        recommendations.append(
            "缺少运行依赖："
            + ", ".join(missing_imports)
            + "。可尝试执行 python3 -m pip install faiss-cpu sentence-transformers scikit-learn。"
        )

    deduped_recommendations = []
    seen_recommendations = set()
    for item in recommendations:
        text = str(item or "").strip()
        key = _recommendation_key(text)
        if not text or key in seen_recommendations:
            continue
        deduped_recommendations.append(text)
        seen_recommendations.add(key)

    return {
        "overall_ok": overall_ok,
        "strict_public": strict_public,
        "imports": imports,
        "kb_readiness": kb_readiness,
        "private_probe": {
            "ok": private_ok,
            "user_id": probe_user,
            "ingested_item_id": ingest_item.get("id"),
            "hit_count": len(private_hits),
            "matched_expected_doc": any(
                str(hit.get("source_doc_id") or "").strip() == str(ingest_item.get("id") or "").strip()
                for hit in private_hits
                if isinstance(hit, dict)
            ),
            "top_hit": private_hits[0] if private_hits else {},
        },
        "public_probe": {
            "ok": public_ok,
            "hit_count": len(public_hits),
            "public_source": public_probe.get("public_source", "") if isinstance(public_probe, dict) else "",
            "matched_keywords": [
                keyword for keyword in ("导数", "切线斜率")
                if any(keyword in _hit_text(hit) for hit in public_hits if isinstance(hit, dict))
            ],
            "top_hit": public_hits[0] if public_hits else {},
        },
        "recommendations": deduped_recommendations,
    }


def render_human_report(report: Dict[str, object]):
    print("=" * 72)
    print("GraphRAG 环境真实验证")
    print("=" * 72)

    print("\n[1/4] 关键依赖")
    for name, item in (report.get("imports", {}) or {}).items():
        if item.get("ok"):
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}: {item.get('error')}")

    kb = report.get("kb_readiness", {}) or {}
    public_vector = kb.get("public_vector", {}) or {}
    demo_fallback = kb.get("demo_fallback", {}) or {}
    artifacts = public_vector.get("artifacts", {}) or {}

    print("\n[2/4] 公共知识库制品")
    print(f"  status: {kb.get('status')} | search_ready={kb.get('search_ready')}")
    for label, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            continue
        print(
            f"  - {label}: exists={artifact.get('exists')} size_kb={artifact.get('size_kb')} "
            f"git_lfs_pointer={artifact.get('git_lfs_pointer')} ready={artifact.get('ready')}"
        )
    print(
        f"  public_vector_ready={public_vector.get('ready')} | "
        f"demo_fallback_ready={demo_fallback.get('ready')} (chunks={demo_fallback.get('chunks')})"
    )
    if kb.get("summary"):
        print(
            f"  mode={kb.get('summary', {}).get('mode')} | "
            f"offline_chain_ready={kb.get('summary', {}).get('offline_chain_ready')}"
        )
    if kb.get("warnings"):
        print(f"  warnings: {', '.join(kb.get('warnings', []))}")
    if kb.get("errors"):
        print(f"  errors: {', '.join(kb.get('errors', []))}")

    private_probe = report.get("private_probe", {}) or {}
    print("\n[3/4] 私有资料入库与检索探测")
    print(
        f"  ok={private_probe.get('ok')} | user_id={private_probe.get('user_id')} "
        f"| hit_count={private_probe.get('hit_count')}"
    )
    print(f"  matched_expected_doc={private_probe.get('matched_expected_doc')}")
    top_private = private_probe.get("top_hit", {}) or {}
    if top_private:
        print(
            f"  top_hit: {top_private.get('title', 'unknown')} | "
            f"channel={top_private.get('channel', 'unknown')} | "
            f"snippet={top_private.get('snippet', '')}"
        )

    public_probe = report.get("public_probe", {}) or {}
    print("\n[4/4] 公共 KB / fallback 检索探测")
    print(
        f"  ok={public_probe.get('ok')} | source={public_probe.get('public_source', '')} "
        f"| hit_count={public_probe.get('hit_count')}"
    )
    if public_probe.get("matched_keywords"):
        print(f"  matched_keywords: {', '.join(public_probe.get('matched_keywords', []))}")
    top_public = public_probe.get("top_hit", {}) or {}
    if top_public:
        print(
            f"  top_hit: {top_public.get('title', 'unknown')} | "
            f"channel={top_public.get('channel', 'unknown')} | "
            f"snippet={top_public.get('snippet', '')}"
        )

    print("\n结果")
    print(f"  overall_ok={report.get('overall_ok')} | strict_public={report.get('strict_public')}")
    for line in report.get("recommendations", []) or []:
        print(f"  - {line}")


def main():
    parser = argparse.ArgumentParser(description="Verify backend KB readiness and retrieval pipeline.")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--strict-public",
        action="store_true",
        help="严格要求真实公共向量库可用；若仅 demo fallback 可用，则返回失败",
    )
    args = parser.parse_args()

    report = build_report(strict_public=args.strict_public)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render_human_report(report)

    raise SystemExit(0 if report.get("overall_ok") else 1)


if __name__ == "__main__":
    main()
