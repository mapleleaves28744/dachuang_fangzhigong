import threading
import time


class AgentMetrics:
    """轻量内存指标，便于比赛演示与本地调试。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._created_at = time.time()
        self._requests = 0
        self._success = 0
        self._fail = 0
        self._tool_calls = 0
        self._tool_fail = 0
        self._latency_total_ms = 0.0
        self._timeouts = 0
        self._retries = 0

    def record_request(self, success=True, latency_ms=0.0, timed_out=False, retries=0):
        with self._lock:
            self._requests += 1
            if success:
                self._success += 1
            else:
                self._fail += 1
            if timed_out:
                self._timeouts += 1
            self._retries += int(max(0, retries or 0))
            self._latency_total_ms += float(max(0.0, latency_ms or 0.0))

    def record_tool(self, ok=True):
        with self._lock:
            self._tool_calls += 1
            if not ok:
                self._tool_fail += 1

    def snapshot(self):
        with self._lock:
            req = max(1, self._requests)
            return {
                "uptime_seconds": round(time.time() - self._created_at, 3),
                "requests": self._requests,
                "success": self._success,
                "fail": self._fail,
                "success_rate": round(self._success / req, 4),
                "avg_latency_ms": round(self._latency_total_ms / req, 2),
                "timeouts": self._timeouts,
                "retries": self._retries,
                "tool_calls": self._tool_calls,
                "tool_fail": self._tool_fail,
                "tool_fail_rate": round(self._tool_fail / max(1, self._tool_calls), 4),
            }


agent_metrics = AgentMetrics()
