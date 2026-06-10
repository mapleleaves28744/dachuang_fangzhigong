#!/usr/bin/env python3
"""Lightweight usability evaluation based on key user journeys."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def request_json(base_url: str, method: str, path: str, payload: dict | None = None, token: str | None = None, timeout: int = 12):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, method=method.upper(), headers=headers, data=data)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            body = json.loads(text) if text.strip() else {}
            return int(resp.getcode()), body, (time.perf_counter() - started) * 1000.0, ""
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            body = {"raw": text}
        return int(exc.code), body, (time.perf_counter() - started) * 1000.0, ""
    except Exception as exc:  # noqa: BLE001
        return None, {}, (time.perf_counter() - started) * 1000.0, str(exc)


def run_step(base_url: str, step: dict, context: dict) -> dict:
    token = context.get("token")
    user_id = context.get("user_id")

    payload = step.get("payload")
    if callable(payload):
        payload = payload(context)

    path = step["path"]
    if "{user_id}" in path:
        path = path.replace("{user_id}", user_id or "default_user")

    st, body, latency, err = request_json(base_url, step["method"], path, payload, token=token if step.get("auth") else None)

    expected = step.get("expected_status", [])
    ok_status = st in expected
    ok_predicate = step.get("predicate", lambda _s, _b, _c: True)(st, body, context)
    passed = ok_status and ok_predicate

    if passed and step.get("capture_token"):
        context["token"] = body.get("auth", {}).get("token", "")
    if passed and step.get("capture_space_id"):
        context["space_id"] = body.get("space", {}).get("id", "")

    return {
        "name": step["name"],
        "passed": bool(passed),
        "status": st,
        "latency_ms": round(latency, 3),
        "error": err,
        "error_code": body.get("error_code") if isinstance(body, dict) else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run key journey usability checks")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--output", default="docs/testing/usability_results.json")
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d%H%M%S")
    user_id = f"ux_{stamp}_{uuid.uuid4().hex[:6]}"
    password = "Secret123!"

    context = {"user_id": user_id, "token": "", "space_id": ""}

    steps = [
        {
            "name": "register",
            "method": "POST",
            "path": "/api/auth/register",
            "payload": lambda c: {
                "username": c["user_id"],
                "password": password,
                "display_name": "UX Runner",
                "locale": "CN",
            },
            "expected_status": [200],
            "predicate": lambda _s, b, _c: bool(b.get("auth", {}).get("token")),
            "capture_token": True,
        },
        {
            "name": "dashboard_summary",
            "method": "GET",
            "path": "/api/dashboard/summary?user_id={user_id}",
            "expected_status": [200],
            "auth": True,
        },
        {
            "name": "ask_valid",
            "method": "POST",
            "path": "/api/ask",
            "payload": lambda c: {"user_id": c["user_id"], "question": "什么是导数"},
            "expected_status": [200],
        },
        {
            "name": "create_space",
            "method": "POST",
            "path": "/api/spaces",
            "payload": lambda _c: {"user_id": "spoofed_user", "name": "UX Space"},
            "expected_status": [200],
            "auth": True,
            "predicate": lambda _s, b, c: b.get("space", {}).get("user_id") in (c["user_id"], None),
            "capture_space_id": True,
        },
        {
            "name": "list_spaces",
            "method": "GET",
            "path": "/api/spaces?user_id=spoofed_user",
            "expected_status": [200],
            "auth": True,
            "predicate": lambda _s, b, c: b.get("user_id") == c["user_id"],
        },
        {
            "name": "recommendations",
            "method": "GET",
            "path": "/api/recommendations?user_id={user_id}&limit=3",
            "expected_status": [200],
        },
        {
            "name": "knowledge_graph",
            "method": "GET",
            "path": "/api/knowledge_graph?user_id={user_id}",
            "expected_status": [200],
        },
    ]

    results: list[dict] = []
    retries = 0
    for step in steps:
        first = run_step(args.base_url, step, context)
        if first["passed"]:
            first["attempts"] = 1
            results.append(first)
            continue

        retries += 1
        second = run_step(args.base_url, step, context)
        second["attempts"] = 2
        second["retried_from_status"] = first.get("status")
        results.append(second)

    total = len(results)
    passed = sum(1 for x in results if x.get("passed"))
    completion_rate = (passed / total * 100.0) if total else 0.0
    avg_latency = sum(x.get("latency_ms", 0.0) for x in results) / total if total else 0.0
    slow_steps = sorted(results, key=lambda x: x.get("latency_ms", 0.0), reverse=True)[:3]

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": args.base_url,
            "user_id": user_id,
            "steps": [s["name"] for s in steps],
        },
        "summary": {
            "total_steps": total,
            "passed_steps": passed,
            "failed_steps": total - passed,
            "completion_rate_percent": round(completion_rate, 2),
            "avg_step_latency_ms": round(avg_latency, 3),
            "retry_count": retries,
            "retry_rate_percent": round((retries / total * 100.0) if total else 0.0, 2),
            "usability_level": "good" if completion_rate >= 85 else "needs_improvement",
        },
        "results": results,
        "slowest_steps": [{"name": s["name"], "latency_ms": s["latency_ms"], "passed": s["passed"]} for s in slow_steps],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload["summary"], ensure_ascii=False))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
