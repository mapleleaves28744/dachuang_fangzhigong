#!/usr/bin/env python3
"""Security validation suite for auth/rate-limit/input checks.

Runs real HTTP checks and writes structured evidence JSON.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict | None = None,
    token: str | None = None,
    timeout: int = 10,
) -> tuple[int | None, dict, float, str]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, method=method.upper(), headers=headers, data=data)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            elapsed = (time.perf_counter() - started) * 1000.0
            body = json.loads(text) if text.strip() else {}
            return int(resp.getcode()), body, elapsed, ""
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="ignore")
        elapsed = (time.perf_counter() - started) * 1000.0
        try:
            body = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            body = {"raw": text}
        return int(exc.code), body, elapsed, ""
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000.0
        return None, {}, elapsed, str(exc)


def request_raw(base_url: str, method: str, path: str, raw: bytes, timeout: int = 10) -> tuple[int | None, str]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    req = urllib.request.Request(
        url,
        method=method.upper(),
        headers={"Content-Type": "application/json"},
        data=raw,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.getcode()), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def add_result(results: list[dict], name: str, passed: bool, severity: str, detail: str, evidence: dict) -> None:
    results.append(
        {
            "name": name,
            "passed": bool(passed),
            "severity": severity,
            "detail": detail,
            "evidence": evidence,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run security verification suite")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Backend API base URL")
    parser.add_argument("--output", default="docs/testing/security_results.json", help="Output JSON path")
    parser.add_argument("--burst", type=int, default=30, help="Burst request count for rate limit probe")
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d%H%M%S")
    username = f"sec_{stamp}_{uuid.uuid4().hex[:6]}"
    password = "Secret123!"
    results: list[dict] = []

    st, body, elapsed, err = request_json(args.base_url, "GET", "/api/auth/me")
    add_result(
        results,
        "auth.unauthorized_me",
        st == 401 and body.get("error_code") == "AUTH_REQUIRED",
        "high",
        "未携带 token 访问 /api/auth/me 应被拒绝",
        {"status": st, "error_code": body.get("error_code"), "latency_ms": round(elapsed, 3), "error": err},
    )

    st, body, elapsed, err = request_json(
        args.base_url,
        "POST",
        "/api/auth/register",
        {"username": username, "password": password, "display_name": "Security Runner", "locale": "CN"},
    )
    token = body.get("auth", {}).get("token") if isinstance(body, dict) else ""
    add_result(
        results,
        "auth.register",
        st == 200 and bool(token),
        "medium",
        "注册应返回 token 供后续鉴权测试",
        {"status": st, "latency_ms": round(elapsed, 3), "has_token": bool(token), "error": err},
    )

    st, body, elapsed, err = request_json(
        args.base_url,
        "POST",
        "/api/auth/login",
        {"username": username, "password": "wrong-password"},
    )
    add_result(
        results,
        "auth.login_wrong_password",
        st == 401 and body.get("error_code") == "AUTH_INVALID_CREDENTIALS",
        "high",
        "错误密码应被拒绝",
        {"status": st, "error_code": body.get("error_code"), "latency_ms": round(elapsed, 3), "error": err},
    )

    st, body, elapsed, err = request_json(
        args.base_url,
        "POST",
        "/api/auth/login",
        {"username": username, "password": password},
    )
    login_token = body.get("auth", {}).get("token") if isinstance(body, dict) else ""
    add_result(
        results,
        "auth.login_valid",
        st == 200 and bool(login_token),
        "medium",
        "正确密码应允许登录",
        {"status": st, "latency_ms": round(elapsed, 3), "has_token": bool(login_token), "error": err},
    )

    st, body, elapsed, err = request_json(args.base_url, "GET", "/api/auth/me", token="forged.token.invalid")
    add_result(
        results,
        "auth.forged_token",
        st == 401 and body.get("error_code") == "AUTH_REQUIRED",
        "high",
        "伪造 token 不应绕过鉴权",
        {"status": st, "error_code": body.get("error_code"), "latency_ms": round(elapsed, 3), "error": err},
    )

    st, body, elapsed, err = request_json(args.base_url, "GET", "/api/auth/me", token=login_token)
    me_user_id = body.get("auth", {}).get("user", {}).get("user_id") if isinstance(body, dict) else ""
    add_result(
        results,
        "auth.valid_token_access",
        st == 200 and me_user_id == username,
        "high",
        "合法 token 应绑定当前登录用户",
        {"status": st, "user_id": me_user_id, "latency_ms": round(elapsed, 3), "error": err},
    )

    st, body, elapsed, err = request_json(
        args.base_url,
        "POST",
        "/api/spaces",
        {"user_id": "other_user", "name": "Auth Binding Test"},
        token=login_token,
    )
    created_space = body.get("space", {}).get("id") if isinstance(body, dict) else ""
    st2, body2, elapsed2, err2 = request_json(
        args.base_url,
        "GET",
        "/api/spaces?user_id=other_user",
        token=login_token,
    )
    bound_user = body2.get("user_id") if isinstance(body2, dict) else ""
    add_result(
        results,
        "auth.horizontal_isolation",
        st == 200 and bool(created_space) and st2 == 200 and bound_user == username,
        "high",
        "携带 token 时应强制绑定登录用户，避免 user_id 参数越权",
        {
            "create_status": st,
            "list_status": st2,
            "bound_user_id": bound_user,
            "space_id": created_space,
            "latency_ms": round(elapsed + elapsed2, 3),
            "error": err or err2,
        },
    )

    st, body, elapsed, err = request_json(
        args.base_url,
        "POST",
        "/api/ask",
        {"user_id": username, "question": ""},
    )
    add_result(
        results,
        "input.empty_question",
        st == 400 and body.get("error_code") == "INVALID_INPUT",
        "medium",
        "空问题应触发参数校验",
        {"status": st, "error_code": body.get("error_code"), "latency_ms": round(elapsed, 3), "error": err},
    )

    status, raw_err = request_raw(args.base_url, "POST", "/api/auth/login", b"{bad-json")
    add_result(
        results,
        "input.malformed_json",
        status in (400, 415),
        "medium",
        "畸形 JSON 请求应被拒绝",
        {"status": status, "error": raw_err},
    )

    burst_statuses: list[int | None] = []
    for _ in range(max(1, args.burst)):
        st, _body, _elapsed, _err = request_json(
            args.base_url,
            "POST",
            "/api/auth/login",
            {"username": username, "password": "wrong-password"},
        )
        burst_statuses.append(st)

    got_429 = any(code == 429 for code in burst_statuses)
    add_result(
        results,
        "rate_limit.login_burst",
        got_429,
        "high",
        "高频错误登录应触发限流（若未触发记为风险）",
        {
            "burst": args.burst,
            "status_counter": {str(code): burst_statuses.count(code) for code in sorted(set(burst_statuses), key=lambda x: (x is None, x))},
            "rate_limit_detected": got_429,
        },
    )

    passed = sum(1 for item in results if item["passed"])
    total = len(results)
    failed_items = [item for item in results if not item["passed"]]

    risk_level = "low"
    if any(item for item in failed_items if item.get("severity") == "high"):
        risk_level = "high"
    elif failed_items:
        risk_level = "medium"

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": args.base_url,
            "burst": args.burst,
            "test_user": username,
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate_percent": round((passed / total * 100.0) if total else 0.0, 2),
            "risk_level": risk_level,
            "rate_limit_detected": any(item["name"] == "rate_limit.login_burst" and item["passed"] for item in results),
        },
        "items": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload["summary"], ensure_ascii=False))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
