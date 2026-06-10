import unittest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.learning_feedback import build_feedback_mastery_assessment


class TestLearningFeedbackService(unittest.TestCase):
    def test_single_lucky_guess_does_not_spike_mastery(self):
        result = build_feedback_mastery_assessment(
            concept="导数",
            feedback_history=[
                {
                    "correct_count": 1,
                    "total_count": 1,
                    "duration_seconds": 5,
                    "timestamp": "2026-04-15T10:00:00",
                }
            ],
            existing_snapshot={
                "concept": "导数",
                "mastery": 0.4,
                "last_reviewed": "2026-04-14T10:00:00",
            },
            now="2026-04-15T10:00:00",
        )

        self.assertLessEqual(result["掌握度"], 0.44)
        self.assertEqual(result["会话题量"], 1)

    def test_consistent_practice_raises_mastery_stably(self):
        snapshot = {
            "concept": "链式法则",
            "mastery": 0.32,
            "last_reviewed": "2026-04-01T10:00:00",
        }

        history1 = [
            {
                "correct_count": 2,
                "total_count": 4,
                "duration_seconds": 220,
                "timestamp": "2026-04-10T10:00:00",
            }
        ]
        result1 = build_feedback_mastery_assessment(
            concept="链式法则",
            feedback_history=history1,
            existing_snapshot=snapshot,
            now="2026-04-10T10:00:00",
        )

        snapshot2 = {
            "concept": "链式法则",
            "mastery": result1["掌握度"],
            "last_reviewed": "2026-04-10T10:00:00",
        }
        history2 = history1 + [
            {
                "correct_count": 4,
                "total_count": 5,
                "duration_seconds": 260,
                "timestamp": "2026-04-12T10:00:00",
            }
        ]
        result2 = build_feedback_mastery_assessment(
            concept="链式法则",
            feedback_history=history2,
            existing_snapshot=snapshot2,
            now="2026-04-12T10:00:00",
        )

        snapshot3 = {
            "concept": "链式法则",
            "mastery": result2["掌握度"],
            "last_reviewed": "2026-04-12T10:00:00",
        }
        history3 = history2 + [
            {
                "correct_count": 5,
                "total_count": 6,
                "duration_seconds": 300,
                "timestamp": "2026-04-15T10:00:00",
            }
        ]
        result3 = build_feedback_mastery_assessment(
            concept="链式法则",
            feedback_history=history3,
            existing_snapshot=snapshot3,
            now="2026-04-15T10:00:00",
        )

        self.assertLess(result1["掌握度"], result2["掌握度"])
        self.assertLess(result2["掌握度"], result3["掌握度"])
        self.assertGreater(result3["趋势得分"], 0.5)
