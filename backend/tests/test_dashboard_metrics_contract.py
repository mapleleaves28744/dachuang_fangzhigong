import unittest

try:
    from app.services.dashboard_summary import build_data_pool_summary
    _SUMMARY_IMPORT_ERROR = ""
except Exception as e:
    build_data_pool_summary = None
    _SUMMARY_IMPORT_ERROR = str(e)

try:
    from app import server as backend_app
    _SERVER_IMPORT_ERROR = ""
except Exception as e:
    backend_app = None
    _SERVER_IMPORT_ERROR = str(e)


@unittest.skipIf(build_data_pool_summary is None, f"dashboard summary unavailable: {_SUMMARY_IMPORT_ERROR}")
class TestDashboardDataPoolContract(unittest.TestCase):
    def test_data_pool_summary_tracks_consecutive_days_and_live_counts(self):
        summary = build_data_pool_summary(
            content_logs=[
                {
                    "content_type": "note",
                    "timestamp": "2026-03-30T09:00:00",
                    "title": "导数笔记",
                    "topics": ["导数"],
                },
                {
                    "content_type": "link",
                    "timestamp": "2026-03-31T09:30:00",
                    "title": "积分课程",
                    "topics": ["积分"],
                },
            ],
            qa_logs=[
                {
                    "timestamp": "2026-03-31T10:00:00",
                    "question": "导数是什么？",
                    "answer": "变化率",
                }
            ],
            behavior_logs=[
                {
                    "timestamp": "2026-03-31T10:20:00",
                    "behavior_type": "page_view",
                    "page": "dashboard",
                }
            ],
            question_draw_logs=[
                {
                    "timestamp": "2026-03-31T10:05:00",
                    "concept": "导数",
                    "difficulty": "medium",
                    "question_type": "single_choice",
                }
            ],
            question_answer_logs=[
                {
                    "timestamp": "2026-03-31T10:08:00",
                    "concept": "导数",
                    "is_correct": False,
                    "score": 0.4,
                }
            ],
            diagnosis_logs=[
                {
                    "timestamp": "2026-03-31T10:09:00",
                    "question": "导数定义题",
                    "diagnosis": {
                        "category": "knowledge",
                        "recommendation": "回到定义复习",
                    },
                }
            ],
            wrong_question_logs=[
                {
                    "timestamp": "2026-03-31T10:08:00",
                    "source": "question_answer",
                    "question": "导数练习题",
                }
            ],
            space_payload={
                "activeEntrySpaceId": "space_1",
                "spaces": [
                    {
                        "id": "space_1",
                        "name": "学习空间",
                        "items": [
                            {
                                "id": "item_1",
                                "kind": "note",
                                "name": "导数整理",
                                "content": "导数定义",
                                "summary": "导数整理",
                                "addedAt": 1711762200000,
                                "updatedAt": 1711762200000,
                            }
                        ],
                    }
                ],
            },
            hidden_metrics={},
            now="2026-03-31T12:00:00",
        )

        self.assertEqual(summary.get("active_days"), 2)
        self.assertEqual(summary.get("space_content_count"), 1)
        self.assertEqual(summary.get("wrong_question_count"), 1)
        self.assertEqual(summary.get("question_draw_count"), 1)
        self.assertEqual(summary.get("question_answer_count"), 1)
        self.assertEqual(summary.get("diagnosis_count"), 1)
        self.assertEqual(summary.get("qa_sample_total"), 2)
        self.assertGreater(summary.get("estimated_stay_minutes", 0), 0)

    def test_data_pool_summary_resets_streak_after_gap(self):
        summary = build_data_pool_summary(
            content_logs=[
                {
                    "content_type": "note",
                    "timestamp": "2026-03-29T09:00:00",
                    "title": "旧笔记",
                    "topics": ["纱线"],
                }
            ],
            qa_logs=[],
            behavior_logs=[],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            wrong_question_logs=[],
            space_payload={"spaces": []},
            hidden_metrics={},
            now="2026-03-31T12:00:00",
        )

        self.assertEqual(summary.get("active_days"), 1)

@unittest.skipIf(backend_app is None, f"backend app unavailable: {_SERVER_IMPORT_ERROR}")
class TestDashboardHiddenMetricsContract(unittest.TestCase):
    def test_hidden_tables_include_space_topics_and_windows(self):
        hidden = backend_app.build_dashboard_hidden_tables(
            content_logs=[
                {
                    "timestamp": "2026-03-31T10:05:00",
                    "title": "导数笔记",
                    "content": "导数定义与性质",
                    "topics": [],
                }
            ],
            qa_logs=[],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            behavior_logs=[
                {
                    "timestamp": "2026-03-31T10:20:00",
                    "behavior_type": "page_view",
                    "page": "dashboard",
                }
            ],
            space_payload={
                "activeEntrySpaceId": "space_1",
                "spaces": [
                    {
                        "id": "space_1",
                        "name": "学习空间",
                        "items": [
                            {
                                "id": "item_1",
                                "kind": "note",
                                "name": "导数整理",
                                "content": "导数例题",
                                "summary": "导数整理",
                                "addedAt": "2026-03-31T10:10:00",
                                "updatedAt": "2026-03-31T10:10:00",
                            },
                            {
                                "id": "item_2",
                                "kind": "note",
                                "name": "积分整理",
                                "content": "积分计算",
                                "summary": "积分整理",
                                "addedAt": "2026-03-31T10:40:00",
                                "updatedAt": "2026-03-31T10:40:00",
                            },
                        ],
                    }
                ],
            },
            detect_topics_fn=lambda text: (
                ["导数"] if "导数" in text else (["积分"] if "积分" in text else [])
            ),
        )

        top_topic = hidden.get("top_topic", {})
        top_window = hidden.get("top_study_window", {})

        self.assertEqual(top_topic.get("topic"), "导数")
        self.assertEqual(top_window.get("label"), "10:00-12:00")
        self.assertGreaterEqual(top_window.get("count", 0), 2)


if __name__ == "__main__":
    unittest.main()
