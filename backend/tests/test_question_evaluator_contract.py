import unittest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.question_evaluator import evaluate_answer


class TestQuestionEvaluatorContract(unittest.TestCase):
    def test_fill_blank_uses_dedicated_rule(self):
        result = evaluate_answer(
            {
                "question_type": "fill_blank",
                "question": "导数的几何意义是 ____ 。",
                "answer": "切线斜率",
                "analysis": "几何意义对应曲线在该点的切线斜率。",
            },
            "切线斜率",
        )

        self.assertTrue(result["is_correct"])
        self.assertEqual(result["scoring_type"], "fill_blank")
        self.assertEqual(result["evaluation_method"], "rule_fill_blank")

    def test_definition_keyword_stuffing_is_rejected(self):
        result = evaluate_answer(
            {
                "question_type": "term_definition",
                "question": "什么是链式法则？",
                "answer": "链式法则用于复合函数求导，需要先求外函数导数，再乘以内函数导数。",
                "analysis": "定义题要说明适用对象和求导顺序。",
            },
            "链式法则 复合函数 导数 外函数 内函数 导数 乘法 链式法则 复合函数",
        )

        self.assertFalse(result["is_correct"])
        self.assertLess(result["score"], 0.6)
        self.assertIn("keyword_stuffing", result["evidence"]["risk_flags"])

    def test_step_question_requires_process_not_just_final_result(self):
        result = evaluate_answer(
            {
                "question_type": "step",
                "question": "请写出求解步骤。",
                "answer": "先设函数 y=x^2+1，然后求导得到 y'=2x，最后代入 x=1 得到结果 2。",
                "analysis": "步骤题要写出列式、求导和代入。",
            },
            "答案是 2。",
        )

        self.assertFalse(result["is_correct"])
        self.assertLess(result["score"], 0.6)
        self.assertIn("missing_required_steps", result["evidence"]["risk_flags"])

    def test_subjective_verbatim_copy_is_penalized(self):
        standard_answer = "链式法则用于复合函数求导，需要先求外函数导数，再乘以内函数导数。"
        result = evaluate_answer(
            {
                "question_type": "short_answer",
                "question": "解释链式法则。",
                "answer": standard_answer,
                "analysis": "可从适用对象和求导顺序两点作答。",
            },
            standard_answer,
        )

        self.assertFalse(result["is_correct"])
        self.assertLessEqual(result["score"], 0.6)
        self.assertIn("verbatim_copy", result["evidence"]["risk_flags"])
