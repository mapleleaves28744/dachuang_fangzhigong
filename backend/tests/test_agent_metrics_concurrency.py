import threading
import unittest

from app.services.agent_metrics import AgentMetrics


class TestAgentMetricsConcurrency(unittest.TestCase):
    def test_record_request_and_tool_thread_safe(self):
        metrics = AgentMetrics()

        def worker():
            for _ in range(200):
                metrics.record_request(success=True, latency_ms=10.0, timed_out=False, retries=1)
                metrics.record_tool(ok=True)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = metrics.snapshot()
        expected = 200 * 8
        self.assertEqual(snap.get("requests"), expected)
        self.assertEqual(snap.get("success"), expected)
        self.assertEqual(snap.get("tool_calls"), expected)
        self.assertEqual(snap.get("retries"), expected)


if __name__ == "__main__":
    unittest.main()
