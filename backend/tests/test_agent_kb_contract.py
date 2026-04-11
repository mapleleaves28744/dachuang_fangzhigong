import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestAgentKbContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def test_kb_ingest_requires_content(self):
        resp = self.client.post("/api/agent/kb/ingest", json={"student_id": "u_kb", "title": "x"})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("success"))
        self.assertEqual(body.get("error_code"), "INVALID_INPUT")

    def test_kb_ingest_and_search(self):
        user_id = "u_kb_contract"
        ingest = self.client.post(
            "/api/agent/kb/ingest",
            json={
                "student_id": user_id,
                "title": "导数公式速记",
                "content": "幂函数求导公式是 (x^n)' = n*x^(n-1)。",
                "tags": ["导数", "公式"],
            },
        )
        self.assertEqual(ingest.status_code, 200)
        ingest_data = ingest.get_json()
        self.assertTrue(ingest_data.get("success"))

        search = self.client.post(
            "/api/agent/kb/search",
            json={
                "student_id": user_id,
                "query": "幂函数求导公式",
                "top_k": 2,
            },
        )
        self.assertEqual(search.status_code, 200)
        data = search.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(len(data.get("hits", [])), 1)

    def test_eval_ab_requires_cases(self):
        resp = self.client.post("/api/agent/eval-ab", json={"cases": []})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("success"))

    def test_eval_ab_contract(self):
        def _fake_solve_problem(session_id, student_id, ocr_text, question_text="", force_use_kb=False):
            if force_use_kb:
                return {
                    "answer": "链式法则 复合函数",
                    "steps_log": [{"tool_name": "tool_search_learning_kb"}],
                    "evidence": {"has_kb": True},
                }
            return {
                "answer": "复合函数",
                "steps_log": [{"tool_name": "tool_query_knowledge_graph"}],
                "evidence": {"has_kb": False},
            }

        with patch("app.api.agent_routes.tutor_agent") as mock_agent:
            mock_agent.solve_problem.side_effect = _fake_solve_problem
            resp = self.client.post(
                "/api/agent/eval-ab",
                json={
                    "cases": [
                        {
                            "id": "ab_1",
                            "student_id": "u_ab",
                            "ocr_text": "求复合函数导数",
                            "question": "结合知识库讲解",
                            "expected_keywords": ["链式法则", "复合函数"],
                        }
                    ]
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("summary", {}).get("cases"), 1)
        self.assertIn("keyword_score_delta", data.get("summary", {}))

    def test_learning_feedback_invalid_input(self):
        """Test learning-feedback endpoint with missing required fields."""
        resp = self.client.post("/api/agent/learning-feedback", json={})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("success"))
        self.assertEqual(body.get("error_code"), "INVALID_INPUT")

    def test_learning_feedback_success(self):
        """Test learning-feedback endpoint records feedback and updates mastery."""
        user_id = "u_feedback_test"
        concept = "导数基础"
        
        # First, record feedback with high accuracy
        resp = self.client.post(
            "/api/agent/learning-feedback",
            json={
                "student_id": user_id,
                "task_id": "task_001",
                "task_type": "quiz",
                "correct_count": 8,
                "total_count": 10,
                "duration_seconds": 300,
                "concept": concept,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("feedback_recorded"))
        self.assertEqual(data.get("accuracy"), 0.8)
        self.assertEqual(data.get("concept"), concept)

    def test_learning_feedback_mastery_update(self):
        """Test that mastery is updated based on feedback accuracy."""
        user_id = "u_mastery_update_test"
        concept = "链式法则"
        
        # Test low accuracy (should decrease mastery)
        resp = self.client.post(
            "/api/agent/learning-feedback",
            json={
                "student_id": user_id,
                "task_id": "task_002",
                "task_type": "practice",
                "correct_count": 2,
                "total_count": 10,
                "duration_seconds": 180,
                "concept": concept,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("accuracy"), 0.2)
