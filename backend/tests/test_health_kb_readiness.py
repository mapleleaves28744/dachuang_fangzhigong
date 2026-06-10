import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestHealthKbReadiness(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def test_health_includes_kb_readiness(self):
        with patch.object(backend_app, "get_ai_runtime_config", return_value={"provider": "mock", "model": "mock", "api_key": ""}), patch.object(
            backend_app,
            "get_kb_readiness_report",
            return_value={
                "status": "degraded",
                "ready": True,
                "search_ready": True,
                "warnings": ["public_kb_artifact_is_git_lfs_pointer"],
                "errors": [],
                "public_vector": {"ready": False},
                "private_vector": {"enabled": True, "ready": True},
                "demo_fallback": {"ready": True, "chunks": 6},
                "offline_chain": {"ready": True},
                "summary": {"mode": "demo_fallback", "offline_chain_ready": True},
                "recommended_actions": ["运行 git lfs pull"],
            },
        ), patch.object(backend_app, "neo4j_store") as neo4j:
            neo4j.ensure_connected.return_value = False
            neo4j.last_error = ""
            resp = self.client.get("/health")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("kb_readiness", data)
        self.assertEqual(data.get("kb_readiness", {}).get("status"), "degraded")
        self.assertIn("local_demo_fallback_enabled", data)
        self.assertEqual(data.get("kb_mode"), "demo_fallback")
        self.assertTrue(data.get("offline_core_chain_ready"))
        self.assertIn("运行 git lfs pull", "".join(data.get("kb_recommendations", [])))


if __name__ == "__main__":
    unittest.main()
