import unittest
from unittest.mock import patch

from app import server as backend_app
from app.services.mastery_engine import (
    build_learning_advice,
    calculate_concept_mastery,
    classify_error_by_rules,
)


class TestMasteryEngineContract(unittest.TestCase):
    def test_calculate_concept_mastery_contract(self):
        records = [
            {"timestamp": "2026-03-28T09:00:00", "is_correct": True, "duration_seconds": 65},
            {"timestamp": "2026-03-28T09:10:00", "is_correct": True, "duration_seconds": 72},
            {"timestamp": "2026-03-29T09:20:00", "is_correct": False, "duration_seconds": 118},
            {"timestamp": "2026-03-30T09:30:00", "is_correct": True, "duration_seconds": 84},
            {"timestamp": "2026-03-31T09:40:00", "is_correct": True, "duration_seconds": 76},
        ]

        result = calculate_concept_mastery("导数", records, now="2026-03-31T12:00:00")

        self.assertEqual(result["知识点"], "导数")
        self.assertEqual(result["作答次数"], 5)
        self.assertAlmostEqual(result["正确率"], 0.769, places=3)
        self.assertAlmostEqual(result["原始正确率"], 0.8, places=3)
        self.assertAlmostEqual(result["最近正确率"], 0.8, places=3)
        self.assertTrue(0.0 <= result["掌握度"] <= 1.0)
        self.assertGreater(result["标准作答时间"], 0)
        self.assertIsNotNone(result["时间比值"])
        self.assertIn(result["状态"], {"熟练", "一般", "薄弱"})

    def test_forgetting_curve_lowers_mastery(self):
        base_records = [
            {"timestamp": "2026-03-30T09:00:00", "is_correct": True, "duration_seconds": 80},
            {"timestamp": "2026-03-30T09:10:00", "is_correct": True, "duration_seconds": 90},
            {"timestamp": "2026-03-31T09:20:00", "is_correct": True, "duration_seconds": 85},
        ]
        old_records = [
            {"timestamp": "2026-02-10T09:00:00", "is_correct": True, "duration_seconds": 80},
            {"timestamp": "2026-02-11T09:10:00", "is_correct": True, "duration_seconds": 90},
            {"timestamp": "2026-02-12T09:20:00", "is_correct": True, "duration_seconds": 85},
        ]

        recent_result = calculate_concept_mastery("积分", base_records, now="2026-03-31T12:00:00")
        old_result = calculate_concept_mastery("积分", old_records, now="2026-03-31T12:00:00")

        self.assertGreater(recent_result["掌握度"], old_result["掌握度"])
        self.assertEqual(old_result["遗忘系数"], 0.5)

    def test_classify_error_and_advice_contract(self):
        history = [
            {"timestamp": "2026-03-30T09:00:00", "is_correct": False, "score": 0.0},
            {"timestamp": "2026-03-31T09:00:00", "is_correct": False, "score": 0.0},
        ]

        result = classify_error_by_rules(
            question="什么是导数",
            correct_answer="导数表示函数在某点附近的变化率",
            user_answer="不会，没思路",
            concept_mastery=0.32,
            response_time_seconds=25,
            attempt_count=2,
            history_records=history,
        )
        advice = build_learning_advice(
            error_type=result["error_type"],
            mastery_score=0.32,
            concept="导数",
            attempt_count=2,
        )

        self.assertEqual(result["category"], "knowledge")
        self.assertAlmostEqual(result["recent_accuracy"], 0.0, places=3)
        self.assertIn("错误类型", advice)
        self.assertIn("原因", advice)
        self.assertIn("建议", advice)
        self.assertTrue(len(advice["推荐行动"]) >= 3)

    def test_classify_skill_error_for_mid_mastery_and_slow_response(self):
        history = [
            {"timestamp": "2026-03-28T09:00:00", "is_correct": True, "duration_seconds": 70},
            {"timestamp": "2026-03-29T09:00:00", "is_correct": False, "duration_seconds": 95},
            {"timestamp": "2026-03-30T09:00:00", "is_correct": True, "duration_seconds": 82},
            {"timestamp": "2026-03-31T08:30:00", "is_correct": True, "duration_seconds": 78},
        ]

        result = classify_error_by_rules(
            question="解分式方程",
            correct_answer="先去分母，再解方程，最后验根",
            user_answer="先去分母再计算，但后面卡住了",
            concept_mastery=0.58,
            response_time_seconds=180,
            attempt_count=4,
            history_records=history,
        )

        self.assertEqual(result["category"], "skill")
        self.assertGreater(result["time_ratio"], 1.3)

    def test_classify_habit_error_for_high_mastery_and_near_miss(self):
        history = [
            {"timestamp": "2026-03-28T09:00:00", "is_correct": True, "duration_seconds": 78},
            {"timestamp": "2026-03-29T09:00:00", "is_correct": True, "duration_seconds": 75},
            {"timestamp": "2026-03-30T09:00:00", "is_correct": True, "duration_seconds": 82},
            {"timestamp": "2026-03-31T08:30:00", "is_correct": True, "duration_seconds": 74},
        ]

        result = classify_error_by_rules(
            question="导数的几何意义是？",
            correct_answer="切线斜率",
            user_answer="切线率",
            concept_mastery=0.86,
            response_time_seconds=22,
            attempt_count=4,
            history_records=history,
        )

        self.assertEqual(result["category"], "habit")
        self.assertTrue(result["near_miss"])

    def test_sync_user_mastery_to_graph_prefers_user_score(self):
        kg = backend_app.build_knowledge_graph()

        with patch.object(backend_app, "get_user_knowledge", return_value={
            "concepts": [{"concept": "导数", "mastery": 0.35}],
            "relations": [],
            "deleted_concepts": [],
        }):
            backend_app.sync_user_mastery_to_graph(kg, "u_mastery")

        payload = backend_app.to_graph_payload(kg, "u_mastery")
        node = next(item for item in payload["nodes"] if item["id"] == "导数")
        self.assertEqual(node["mastery"], 0.35)


if __name__ == "__main__":
    unittest.main()
