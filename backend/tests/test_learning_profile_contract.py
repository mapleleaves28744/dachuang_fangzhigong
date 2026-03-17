import unittest
from datetime import datetime

from learning_profile import (
    LearningProfileService,
    build_recommendations,
    build_recommendation_context,
    build_recommendation_runtime,
    collect_concept_diagnosis_evidence,
    build_weak_recommendation_item,
    build_interest_recommendation_item,
)


class TestLearningProfileContract(unittest.TestCase):
    def test_parse_datetime_safe_supports_iso_z(self):
        svc = LearningProfileService(kmeans_cls=None, np_module=None)
        dt = svc.parse_datetime_safe("2026-03-16T12:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo is not None, True)

    def test_parse_datetime_safe_supports_space_separator(self):
        svc = LearningProfileService(kmeans_cls=None, np_module=None)
        dt = svc.parse_datetime_safe("2026-03-16 12:34:56")
        self.assertIsNotNone(dt)
        self.assertIsInstance(dt, datetime)

    def test_build_profile_has_required_fields(self):
        svc = LearningProfileService(kmeans_cls=None, np_module=None)
        stored = {}

        def get_user_profile(_):
            return {}

        def set_user_profile(_, profile):
            stored.update(profile)

        def load_user_event_list(_, suffix):
            if suffix == "content":
                return [
                    {
                        "content_type": "note",
                        "timestamp": "2026-03-16T09:30:00",
                        "topics": ["导数"],
                    }
                ]
            return []

        def get_user_knowledge(_):
            return {"concepts": [{"concept": "极限", "mastery": 0.3}]}

        profile = svc.build_profile(
            user_id="u1",
            get_user_profile=get_user_profile,
            set_user_profile=set_user_profile,
            load_user_event_list=load_user_event_list,
            get_user_knowledge=get_user_knowledge,
            normalize_user_knowledge=None,
        )

        required_keys = {
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

        self.assertTrue(required_keys.issubset(set(profile.keys())))
        self.assertEqual(profile["user_id"], "u1")
        self.assertIn("u1", stored.get("user_id", "u1"))

    def test_build_recommendation_context(self):
        ctx = build_recommendation_context({"learning_style": "auditory", "style_method": "kmeans"}, 4)
        self.assertEqual(ctx["learning_style"], "auditory")
        self.assertEqual(ctx["style_method"], "kmeans")
        self.assertEqual(ctx["diagnosis_recent_count"], 4)
        self.assertTrue(ctx.get("generated_at"))

    def test_build_recommendation_runtime(self):
        runtime = build_recommendation_runtime({
            "learning_style": "visual",
            "style_method": "kmeans",
            "style_scores": {"visual": 0.81},
            "style_features": {
                "image_count": 2,
                "link_count": 3,
                "qa_content_count": 0,
                "note_count": 1,
            },
            "best_time_range": "20:00-22:00",
        })
        self.assertEqual(runtime["style"], "visual")
        self.assertEqual(runtime["style_method"], "kmeans")
        self.assertEqual(runtime["behavior_channel"], "visual")
        self.assertEqual(runtime["best_time_range"], "20:00-22:00")

    def test_collect_concept_diagnosis_evidence(self):
        recent = [
            {
                "question": "什么是导数",
                "user_answer": "不会",
                "correct_answer": "变化率",
                "timestamp": "2026-03-16T10:00:00",
                "diagnosis": {"category": "knowledge", "error_type": "concept", "confidence": 0.8, "signals": ["s1", "s2"]},
            }
        ]
        ev = collect_concept_diagnosis_evidence("导数", recent)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["category"], "knowledge")

    def test_recommendation_items_contract(self):
        runtime = build_recommendation_runtime({
            "learning_style": "auditory",
            "style_method": "rule",
            "style_scores": {"auditory": 0.75},
            "style_features": {"qa_content_count": 4, "note_count": 1},
            "best_time_range": "09:00-11:00",
        })
        recent_category_count = {"knowledge": 1, "skill": 0, "habit": 0, "unknown": 0}

        weak_item = build_weak_recommendation_item(
            concept_name="导数",
            mastery=0.35,
            runtime=runtime,
            diagnosis_examples=[],
            recent_category_count=recent_category_count,
        )
        self.assertIn("evidence_brief", weak_item)
        self.assertIn("source_evidence", weak_item)
        self.assertIn("strategy_tags", weak_item)

        interest_item = build_interest_recommendation_item(
            topic="函数",
            runtime=runtime,
            recent_category_count=recent_category_count,
        )
        self.assertEqual(interest_item["concept"], "函数")
        self.assertIn("source_evidence", interest_item)

    def test_build_recommendations_delegated_flow(self):
        def fake_build_learning_profile(_):
            return {
                "learning_style": "visual",
                "style_method": "rule",
                "style_scores": {"visual": 0.7},
                "style_features": {"image_count": 1, "link_count": 1, "note_count": 0, "qa_content_count": 0},
                "best_time_range": "10:00-12:00",
                "interests": ["函数"],
            }

        def fake_get_user_knowledge(_):
            return {
                "concepts": [{"concept": "导数", "mastery": 0.3}],
                "relations": [],
                "deleted_concepts": [],
            }

        def fake_normalize(knowledge):
            return knowledge

        def fake_load_events(_, suffix):
            if suffix == "diagnosis":
                return [
                    {
                        "question": "导数定义",
                        "user_answer": "不会",
                        "correct_answer": "变化率",
                        "timestamp": "2026-03-16T10:00:00",
                        "diagnosis": {"category": "knowledge", "error_type": "concept", "confidence": 0.9, "signals": ["miss"]},
                    }
                ]
            return []

        items = build_recommendations(
            user_id="u1",
            limit=3,
            build_learning_profile_fn=fake_build_learning_profile,
            get_user_knowledge=fake_get_user_knowledge,
            normalize_user_knowledge=fake_normalize,
            load_user_event_list=fake_load_events,
        )

        self.assertTrue(len(items) >= 1)
        first = items[0]
        self.assertIn("evidence_brief", first)
        self.assertIn("source_evidence", first)
        self.assertIn("strategy_tags", first)


if __name__ == "__main__":
    unittest.main()
