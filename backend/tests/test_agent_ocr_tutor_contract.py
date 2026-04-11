import io
import json
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestAgentOcrTutorContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def test_requires_image_or_ocr_text(self):
        resp = self.client.post("/api/agent/ocr-tutor", json={"student_id": "u1"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("success"))

    def test_json_text_success_contract(self):
        fake_result = {
            "answer": "这是答案",
            "steps_log": [
                {
                    "tool_name": "tool_get_student_mastery",
                    "tool_input": {"student_id": "u1", "topic": "导数"},
                    "tool_output_summary": "ok",
                    "latency_ms": 12,
                    "status": "success",
                }
            ],
            "evidence": {"tool_calls": ["tool_get_student_mastery"], "trace_count": 1},
            "meta": {"latency_ms": 50, "retry_count": 0},
            "safety": {"guard_enabled": True, "prompt_injection_flags": []},
        }

        with patch("app.api.agent_routes.tutor_agent") as mock_agent, \
             patch("app.server.post_process_qa_interaction", return_value={
                 "knowledge_extract": {"detected_concepts": ["导数"]},
                 "diagnosis": {"error_type": "知识性错误"},
                 "learning_advice": {"建议": "复习定义"},
             }):
            mock_agent.solve_problem.return_value = fake_result
            resp = self.client.post(
                "/api/agent/ocr-tutor",
                json={"student_id": "u1", "session_id": "s1", "ocr_text": "题目文本"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("answer", data)
        self.assertIn("steps_log", data)
        self.assertIsInstance(data.get("steps_log"), list)
        self.assertIn("evidence", data)
        self.assertIn("knowledge_extract", data)
        self.assertIn("diagnosis", data)
        self.assertIn("learning_advice", data)

    def test_image_path_calls_ocr_then_agent(self):
        fake_result = {
            "answer": "图像题已解答",
            "steps_log": [],
            "evidence": {"tool_calls": [], "trace_count": 0},
            "meta": {"latency_ms": 30, "retry_count": 0},
            "safety": {"guard_enabled": True, "prompt_injection_flags": []},
        }

        with patch("app.api.agent_routes.extract_text_from_image") as mock_ocr, patch("app.api.agent_routes.tutor_agent") as mock_agent:
            mock_ocr.return_value = {
                "success": True,
                "text": "OCR文本",
                "provider": "qwen_vl",
            }
            mock_agent.solve_problem.return_value = fake_result
            resp = self.client.post(
                "/api/agent/ocr-tutor",
                data={
                    "student_id": "u2",
                    "image": (io.BytesIO(b"fake-image"), "q.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("ocr_text"), "OCR文本")

    def test_image_ocr_failure_contract(self):
        with patch("app.api.agent_routes.extract_text_from_image") as mock_ocr:
            mock_ocr.return_value = {
                "success": False,
                "error_code": "OCR_UPSTREAM_ERROR",
                "error_message": "upstream down",
                "provider": "qwen_vl",
            }
            resp = self.client.post(
                "/api/agent/ocr-tutor",
                data={"image": (io.BytesIO(b"x"), "q.jpg")},
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("error_code"), "OCR_UPSTREAM_ERROR")

    def test_image_ocr_failure_fallback_to_question_text(self):
        fake_result = {
            "answer": "已按文本降级回答",
            "steps_log": [],
            "evidence": {"tool_calls": [], "trace_count": 0},
            "meta": {"latency_ms": 10, "retry_count": 0},
            "safety": {"guard_enabled": True, "prompt_injection_flags": []},
        }

        with patch("app.api.agent_routes.extract_text_from_image") as mock_ocr, patch("app.api.agent_routes.tutor_agent") as mock_agent:
            mock_ocr.return_value = {
                "success": False,
                "error_code": "OCR_UPSTREAM_ERROR",
                "error_message": "upstream down",
                "provider": "qwen_vl",
            }
            mock_agent.solve_problem.return_value = fake_result

            resp = self.client.post(
                "/api/agent/ocr-tutor",
                data={
                    "question": "请解释链式法则",
                    "image": (io.BytesIO(b"x"), "q.jpg"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("answer", data)

    def test_stream_contract_sse(self):
        with patch("app.api.agent_routes.tutor_agent") as mock_agent, \
             patch("app.server.post_process_qa_interaction", return_value={
                 "knowledge_extract": {"detected_concepts": ["电流"]},
                 "diagnosis": {"error_type": "学习建议"},
                 "learning_advice": {"建议": "先复习电流定义"},
             }), \
             patch("app.server.extract_learning_advice_from_answer", return_value="先复习电流定义"):
            mock_agent.stream_solve_problem.return_value = iter(
                [
                    "data: {\"type\": \"start\", \"content\": \"ok\"}\n\n",
                    "data: {\"type\": \"final\", \"payload\": {\"answer\": \"建议：先复习电流定义\"}}\n\n",
                    "data: {\"type\": \"done\"}\n\n",
                ]
            )
            resp = self.client.post(
                "/api/agent/ocr-tutor",
                json={
                    "student_id": "u_stream",
                    "session_id": "s_stream",
                    "ocr_text": "题目",
                    "stream": "true",
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        events = []
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[5:].strip()))
            except Exception:
                continue

        final_event = next((evt for evt in events if evt.get("type") == "final"), {})
        payload = final_event.get("payload", {}) if isinstance(final_event, dict) else {}
        self.assertIn("knowledge_extract", payload)
        self.assertIn("diagnosis", payload)
        self.assertIn("learning_advice", payload)
