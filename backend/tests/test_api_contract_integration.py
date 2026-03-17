import unittest
from unittest.mock import patch

try:
    import app as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as e:
    backend_app = None
    _APP_IMPORT_ERROR = str(e)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestApiContractIntegration(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def test_profile_contract(self):
        def fake_load_events(_, suffix):
            if suffix == "content":
                return [{"content_type": "note", "timestamp": "2026-03-16T09:00:00", "topics": ["导数"]}]
            return []

        with patch.object(backend_app, "get_user_profile", return_value={}), \
             patch.object(backend_app, "set_user_profile", return_value=None), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [{"concept": "极限", "mastery": 0.3}] }):
            resp = self.client.get("/api/profile?user_id=u_api")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        profile = data.get("profile", {})
        required = {
            "user_id",
            "updated_at",
            "learning_style",
            "style_scores",
            "style_method",
            "style_features",
            "interests",
            "best_time_range",
            "focus_minutes",
            "content_type_counter",
        }
        self.assertTrue(required.issubset(set(profile.keys())))

    def test_recommendations_contract(self):
        def fake_load_events(_, suffix):
            if suffix == "content":
                return [{"content_type": "note", "timestamp": "2026-03-16T09:00:00", "topics": ["导数"]}]
            if suffix == "diagnosis":
                return [{
                    "question": "导数定义",
                    "user_answer": "不会",
                    "correct_answer": "变化率",
                    "timestamp": "2026-03-16T10:00:00",
                    "diagnosis": {"category": "knowledge", "error_type": "concept", "confidence": 0.9, "signals": ["miss"]},
                }]
            return []

        with patch.object(backend_app, "get_user_profile", return_value={}), \
             patch.object(backend_app, "set_user_profile", return_value=None), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [{"concept": "导数", "mastery": 0.25}], "relations": [], "deleted_concepts": []}):
            resp = self.client.get("/api/recommendations?user_id=u_api&limit=3")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("recommendation_context", data)
        self.assertIn("style_method", data.get("recommendation_context", {}))

        items = data.get("items", [])
        self.assertTrue(len(items) >= 1)
        first = items[0]
        self.assertIn("evidence_brief", first)
        self.assertIn("source_evidence", first)
        self.assertIn("strategy_tags", first)

    def test_learning_path_fallback_contract(self):
        with patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [], "relations": [], "deleted_concepts": []}), \
             patch.object(backend_app, "neo4j_store") as neo4j:
            neo4j.enabled = False
            resp = self.client.get("/api/knowledge_graph/path?user_id=u_api&target=导数")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("path", data)
        self.assertIn("length", data)
        self.assertIn("storage", data)
        self.assertIn("path_source", data)
        self.assertEqual(data.get("path_source"), "json_fallback")
        self.assertGreaterEqual(data.get("length", 0), 2)


if __name__ == "__main__":
    unittest.main()
