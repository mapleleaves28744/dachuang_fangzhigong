import unittest
from datetime import datetime

from app.services.learning_profile import (
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

    def test_build_profile_filters_noise_interests_and_deleted_topics(self):
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
                        "topics": ["我是你爹吗", "导数", "你好呀"],
                    }
                ]
            return []

        def get_user_knowledge(_):
            return {
                "concepts": [
                    {"concept": "导数", "mastery": 0.3},
                    {"concept": "你是谁", "mastery": 0.2},
                ],
                "deleted_concepts": ["你是谁"],
            }

        profile = svc.build_profile(
            user_id="u1",
            get_user_profile=get_user_profile,
            set_user_profile=set_user_profile,
            load_user_event_list=load_user_event_list,
            get_user_knowledge=get_user_knowledge,
            normalize_user_knowledge=None,
        )

        self.assertIn("导数", profile["interests"])
        self.assertNotIn("我是你爹吗", profile["interests"])
        self.assertNotIn("你是谁", profile["interests"])
        self.assertIn("导数", stored.get("interests", []))

    def test_build_profile_returns_empty_state_without_learning_signal(self):
        svc = LearningProfileService(kmeans_cls=None, np_module=None)
        stored = {}

        def get_user_profile(_):
            return {}

        def set_user_profile(_, profile):
            stored.update(profile)

        def load_user_event_list(_, __):
            return []

        def get_user_knowledge(_):
            return {"concepts": [], "relations": [], "deleted_concepts": []}

        profile = svc.build_profile(
            user_id="u-empty",
            get_user_profile=get_user_profile,
            set_user_profile=set_user_profile,
            load_user_event_list=load_user_event_list,
            get_user_knowledge=get_user_knowledge,
            normalize_user_knowledge=None,
        )

        self.assertEqual(profile["learning_style"], "")
        self.assertEqual(profile["interests"], [])
        self.assertEqual(profile["best_time_range"], "")
        self.assertIsNone(profile["focus_minutes"])
        self.assertEqual(stored.get("interests"), [])

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

    def test_build_recommendations_returns_empty_without_interests_or_weak_points(self):
        def fake_build_learning_profile(_):
            return {
                "learning_style": "",
                "style_method": "",
                "style_scores": {"visual": 0.0, "auditory": 0.0, "kinesthetic": 0.0},
                "style_features": {
                    "image_count": 0,
                    "link_count": 0,
                    "note_count": 0,
                    "qa_content_count": 0,
                },
                "best_time_range": "",
                "interests": [],
            }

        def fake_get_user_knowledge(_):
            return {
                "concepts": [],
                "relations": [],
                "deleted_concepts": [],
            }

        items = build_recommendations(
            user_id="u-empty",
            limit=3,
            build_learning_profile_fn=fake_build_learning_profile,
            get_user_knowledge=fake_get_user_knowledge,
            normalize_user_knowledge=lambda knowledge: knowledge,
            load_user_event_list=lambda *_: [],
        )

        self.assertEqual(items, [])

    def test_weak_recommendation_reason_varies_by_context(self):
        runtime = build_recommendation_runtime({
            "learning_style": "visual",
            "style_method": "rule",
            "style_scores": {"visual": 0.7, "auditory": 0.2, "kinesthetic": 0.1},
            "style_features": {"image_count": 2, "link_count": 1, "note_count": 0, "qa_content_count": 1},
            "best_time_range": "19:00-21:00",
        })

        item_a = build_weak_recommendation_item(
            concept_name="电流",
            mastery=0.3,
            runtime=runtime,
            diagnosis_examples=[{"category": "knowledge"}],
            recent_category_count={"knowledge": 2, "skill": 0, "habit": 0, "unknown": 0},
        )
        item_b = build_weak_recommendation_item(
            concept_name="电压",
            mastery=0.55,
            runtime=runtime,
            diagnosis_examples=[],
            recent_category_count={"knowledge": 0, "skill": 2, "habit": 0, "unknown": 0},
        )

        self.assertNotEqual(item_a.get("reason"), item_b.get("reason"))
        self.assertIn("mode:", "|".join(item_a.get("strategy_tags", [])))
        self.assertIn("focus:", "|".join(item_a.get("strategy_tags", [])))


if __name__ == "__main__":
    unittest.main()
