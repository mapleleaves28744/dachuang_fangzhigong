#!/usr/bin/env python3
"""Real HTTP concurrency benchmark for FangZhiGong backend.

Outputs JSON metrics for multiple scenarios and concurrency levels.
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass
class Scenario:
    name: str
    method: str
    path: str
    expected_statuses: tuple[int, ...]
    payload: dict | None = None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int((len(sorted_values) - 1) * p)
    return float(sorted_values[idx])


def request_once(base_url: str, scenario: Scenario, timeout: float) -> tuple[bool, int | None, float, str]:
    full_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", scenario.path.lstrip("/"))
    headers = {"Content-Type": "application/json"}
    data = None
    if scenario.payload is not None:
        data = json.dumps(scenario.payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(full_url, method=scenario.method.upper(), headers=headers, data=data)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(256)
            status = int(resp.getcode())
            ok = status in scenario.expected_statuses
            return ok, status, (time.perf_counter() - started) * 1000.0, body.decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = exc.read(256).decode("utf-8", errors="ignore")
        ok = status in scenario.expected_statuses
        return ok, status, (time.perf_counter() - started) * 1000.0, payload
    except Exception as exc:  # noqa: BLE001
        return False, None, (time.perf_counter() - started) * 1000.0, str(exc)


def run_level(base_url: str, scenario: Scenario, workers: int, duration_sec: int, timeout_sec: int) -> dict:
    deadline = time.monotonic() + max(1, duration_sec)
    lock = threading.Lock()
    latencies: list[float] = []
    expected_hits = 0
    unexpected_hits = 0
    exceptions = 0
    status_counter: dict[str, int] = {}

    def worker() -> None:
        nonlocal expected_hits, unexpected_hits, exceptions
        while time.monotonic() < deadline:
            ok, status, latency_ms, _detail = request_once(base_url, scenario, timeout=float(timeout_sec))
            with lock:
                latencies.append(latency_ms)
                key = "ERR" if status is None else str(status)
                status_counter[key] = status_counter.get(key, 0) + 1
                if status is None:
                    exceptions += 1
                elif ok:
                    expected_hits += 1
                else:
                    unexpected_hits += 1

    start_wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker) for _ in range(workers)]
        for fut in as_completed(futures):
            fut.result()
    wall_elapsed = time.perf_counter() - start_wall

    total = len(latencies)
    throughput = (total / wall_elapsed) if wall_elapsed > 0 else 0.0
    error_rate = ((unexpected_hits + exceptions) / total * 100.0) if total else 0.0

    return {
        "scenario": scenario.name,
        "workers": workers,
        "duration_sec": duration_sec,
        "requests_total": total,
        "requests_expected": expected_hits,
        "requests_unexpected": unexpected_hits,
        "exceptions": exceptions,
        "error_rate_percent": round(error_rate, 3),
        "throughput_rps": round(throughput, 3),
        "latency_ms": {
            "avg": round(mean(latencies), 3) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 3),
            "p90": round(percentile(latencies, 0.90), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "min": round(min(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "status_counter": status_counter,
        "stable": total > 0 and error_rate <= 1.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real HTTP concurrency benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Backend API base URL")
    parser.add_argument("--duration-sec", type=int, default=20, help="Duration per level")
    parser.add_argument("--levels", default="20,50,100", help="Comma separated worker levels")
    parser.add_argument("--timeout-sec", type=int, default=8, help="Request timeout seconds")
    parser.add_argument(
        "--output",
        default="docs/testing/concurrency_results.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    levels = [int(x.strip()) for x in args.levels.split(",") if x.strip()]
    run_tag = f"cc_{int(time.time())}"

    scenarios = [
        Scenario("health", "GET", "/health", (200,)),
        Scenario("dashboard_summary", "GET", f"/api/dashboard/summary?user_id={run_tag}", (200,)),
        Scenario("auth_gate", "GET", "/api/auth/me", (401,)),
    ]

    results = []
    suite_start = time.perf_counter()
    for scenario in scenarios:
        for workers in levels:
            results.append(run_level(args.base_url, scenario, workers, args.duration_sec, args.timeout_sec))

    total_time = time.perf_counter() - suite_start
    p95_values = [item["latency_ms"]["p95"] for item in results if item.get("requests_total", 0) > 0]
    avg_errors = mean([item["error_rate_percent"] for item in results]) if results else 0.0
    overall_stable = all(bool(item.get("stable")) for item in results)

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": args.base_url,
            "duration_sec": args.duration_sec,
            "levels": levels,
            "scenarios": [s.name for s in scenarios],
            "suite_wall_time_sec": round(total_time, 3),
        },
        "summary": {
            "overall_stable": overall_stable,
            "avg_error_rate_percent": round(avg_errors, 3),
            "worst_p95_ms": round(max(p95_values), 3) if p95_values else 0.0,
            "best_p95_ms": round(min(p95_values), 3) if p95_values else 0.0,
            "max_rps": round(max((item["throughput_rps"] for item in results), default=0.0), 3),
        },
        "results": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload["summary"], ensure_ascii=False))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
