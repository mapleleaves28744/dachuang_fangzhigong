import unittest
from unittest.mock import patch

from app.services import agent_tools


class TestAgentToolsContract(unittest.TestCase):
    def test_generate_learning_plan_persists_plans(self):
        with patch.object(agent_tools, "get_user_plans", return_value=[]), \
             patch.object(agent_tools, "get_user_profile", return_value={
                 "learning_style": "visual",
                 "best_time_range": "19:00-21:00",
                 "focus_minutes": 35,
             }), \
             patch.object(agent_tools, "get_user_knowledge", return_value={
                 "concepts": [{"concept": "HTML", "mastery": 0.35}],
             }), \
             patch.object(agent_tools, "set_user_plans") as mock_set_plans, \
             patch.object(agent_tools, "append_user_event") as mock_append_event:
            result = agent_tools.tool_generate_learning_plan.invoke({"student_id": "u_plan", "topic": "HTML"})

        self.assertIn("已生成并录入", result)
        self.assertIn("HTML", result)
        self.assertTrue(mock_set_plans.called)
        saved_plans = mock_set_plans.call_args.args[1]
        self.assertEqual(len(saved_plans), 3)
        self.assertTrue(all(item.get("source") == "agent_learning_plan" for item in saved_plans))
        self.assertTrue(mock_append_event.called)
        self.assertEqual(mock_append_event.call_args.args[1], "learning_plan")

    def test_diagnose_mistake_persists_diagnosis_event(self):
        fake_result = {
            "error_type": "概念理解错误",
            "severity": "high",
            "recommendation": "先回顾定义再做两道基础题",
            "category": "knowledge",
        }
        with patch.object(agent_tools.diagnosis_engine, "analyze_error", return_value=fake_result), \
             patch.object(agent_tools, "append_user_event") as mock_append_event:
            result = agent_tools.tool_diagnose_mistake.invoke({
                "student_id": "u_diag",
                "question": "什么是 HTML？",
                "student_answer": "不会",
                "correct_answer": "HTML 是超文本标记语言",
                "topic": "HTML",
            })

        self.assertIn("【错题归因】", result)
        self.assertIn("概念理解错误", result)
        self.assertTrue(mock_append_event.called)
        self.assertEqual(mock_append_event.call_args.args[0], "u_diag")
        self.assertEqual(mock_append_event.call_args.args[1], "diagnosis")
        payload = mock_append_event.call_args.args[2]
        self.assertEqual(payload.get("concept"), "HTML")
        self.assertEqual(payload.get("source"), "agent_tool")


if __name__ == "__main__":
    unittest.main()
