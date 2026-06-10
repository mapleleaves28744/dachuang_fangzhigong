import unittest

try:
    from app.services.dashboard_summary import (
        build_data_pool_summary,
        build_intervention_summary,
        build_streak_widget_summary,
    )
    _SUMMARY_IMPORT_ERROR = ""
except Exception as e:
    build_data_pool_summary = None
    build_intervention_summary = None
    build_streak_widget_summary = None
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

    def test_data_pool_summary_filters_deleted_topics_from_dashboard_views(self):
        summary = build_data_pool_summary(
            content_logs=[
                {
                    "content_type": "note",
                    "timestamp": "2026-03-31T09:00:00",
                    "title": "HTML 笔记",
                    "topics": ["HTML", "CSS"],
                }
            ],
            qa_logs=[],
            behavior_logs=[],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            wrong_question_logs=[],
            space_payload={"spaces": []},
            hidden_metrics={
                "topic_total_table": [
                    {"topic": "HTML", "count": 4},
                    {"topic": "CSS", "count": 3},
                ],
            },
            blocked_topics=["HTML"],
            now="2026-03-31T12:00:00",
        )

        topics = [item.get("topic") for item in summary.get("top_topics", [])]
        self.assertNotIn("HTML", topics)
        self.assertIn("CSS", topics)

    def test_data_pool_summary_keeps_new_account_empty_when_only_has_behavior_logs(self):
        summary = build_data_pool_summary(
            content_logs=[],
            qa_logs=[],
            behavior_logs=[
                {
                    "timestamp": "2026-03-31T10:20:00",
                    "behavior_type": "auth_login",
                    "page": "auth",
                }
            ],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            wrong_question_logs=[],
            space_payload={"spaces": []},
            hidden_metrics={},
            now="2026-03-31T12:00:00",
        )

        self.assertEqual(summary.get("total_records"), 0)
        self.assertEqual(summary.get("active_days"), 0)
        self.assertEqual(summary.get("study_windows"), [])
        self.assertEqual(summary.get("top_topics"), [])

    def test_streak_widget_summary_tracks_login_days_and_current_streak(self):
        summary = build_streak_widget_summary(
            content_logs=[
                {
                    "timestamp": "2026-04-14T09:00:00",
                    "title": "周一笔记",
                },
                {
                    "timestamp": "2026-04-15T09:00:00",
                    "title": "周二笔记",
                },
            ],
            qa_logs=[],
            behavior_logs=[
                {
                    "timestamp": "2026-04-14T18:00:00",
                    "behavior_type": "auth_login",
                    "page": "auth",
                },
                {
                    "timestamp": "2026-04-15T18:00:00",
                    "behavior_type": "auth_session_active",
                    "page": "dashboard",
                },
                {
                    "timestamp": "2026-04-16T18:00:00",
                    "behavior_type": "auth_session_active",
                    "page": "question-bank",
                },
                {
                    "timestamp": "2026-04-16T18:05:00",
                    "behavior_type": "page_view",
                    "page": "dashboard",
                },
            ],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            now="2026-04-16T20:00:00",
        )

        self.assertEqual(summary.get("progress_label"), "2/2")
        self.assertEqual(summary.get("week_active_days"), 3)
        self.assertEqual(summary.get("current_streak"), 3)
        self.assertEqual(summary.get("message"), "连续登录已开始，继续保持这个节奏。")
        self.assertEqual(len(summary.get("week_days", [])), 7)
        self.assertTrue(any(item.get("today") and item.get("active") for item in summary.get("week_days", [])))

    def test_streak_widget_summary_ignores_non_login_activity(self):
        summary = build_streak_widget_summary(
            content_logs=[
                {
                    "timestamp": "2026-04-14T09:00:00",
                    "title": "周一笔记",
                },
            ],
            qa_logs=[
                {
                    "timestamp": "2026-04-15T10:00:00",
                    "question": "纺织材料是什么？",
                }
            ],
            behavior_logs=[
                {
                    "timestamp": "2026-04-16T18:00:00",
                    "behavior_type": "page_view",
                    "page": "dashboard",
                }
            ],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            now="2026-04-16T12:00:00",
        )

        self.assertEqual(summary.get("progress_label"), "0/2")
        self.assertEqual(summary.get("week_active_days"), 0)
        self.assertEqual(summary.get("current_streak"), 0)
        self.assertEqual(summary.get("message"), "本周登录 2 天以开始你的连续登录。")

    def test_streak_widget_summary_defaults_to_zero_state(self):
        summary = build_streak_widget_summary(
            content_logs=[],
            qa_logs=[],
            behavior_logs=[],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            now="2026-04-16T12:00:00",
        )

        self.assertEqual(summary.get("progress_label"), "0/2")
        self.assertEqual(summary.get("week_active_days"), 0)
        self.assertEqual(summary.get("current_streak"), 0)
        self.assertEqual(summary.get("status"), "warming")

    def test_intervention_summary_uses_learning_advice_fallback(self):
        summary = build_intervention_summary(
            profile={"best_time_range": "19:00-21:00"},
            diagnosis_report={
                "category_count": {"knowledge": 1, "skill": 0, "habit": 0},
                "latest": [
                    {
                        "timestamp": "2026-03-31T10:09:00",
                        "question": "导数定义题",
                        "diagnosis": {
                            "category": "knowledge",
                            "error_type": "知识性错误",
                            "signals": ["concept_miss"],
                        },
                        "learning_advice": {
                            "建议": "先复习导数定义，再做2道基础题",
                        },
                    }
                ],
            },
            recommendations=[],
            reminders={"due_items": []},
        )

        self.assertIn("latest_cases", summary)
        self.assertEqual(len(summary.get("latest_cases", [])), 1)
        self.assertEqual(
            summary.get("latest_cases", [])[0].get("recommendation"),
            "先复习导数定义，再做2道基础题",
        )

    def test_intervention_summary_builds_followup_actions_from_latest_cases(self):
        summary = build_intervention_summary(
            profile={"best_time_range": "20:00-21:00", "learning_style": "kinesthetic", "focus_minutes": 35},
            diagnosis_report={
                "category_count": {"knowledge": 1, "skill": 1, "habit": 0},
                "latest": [
                    {
                        "timestamp": "2026-03-31T11:00:00",
                        "question": "电流方向判定",
                        "diagnosis": {
                            "category": "skill",
                            "error_type": "步骤跳步",
                            "recommendation": "按步骤先列已知再判断方向",
                            "signals": ["step_missing"],
                        },
                        "learning_advice": {},
                    }
                ],
            },
            recommendations=[],
            reminders={"due_items": []},
        )

        action_queue = summary.get("action_queue", [])
        self.assertTrue(any(item.get("kind") == "diagnosis_followup" for item in action_queue))
        self.assertTrue(any("定向补救" in str(item.get("title") or "") for item in action_queue))

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

    def test_hidden_tables_filter_chat_noise_topics(self):
        hidden = backend_app.build_dashboard_hidden_tables(
            content_logs=[],
            qa_logs=[
                {
                    "timestamp": "2026-03-31T10:05:00",
                    "question": "我是你爹吗",
                    "answer": "你好呀，很高兴见到你",
                    "topics": ["我是你爹吗", "你好呀"],
                },
                {
                    "timestamp": "2026-03-31T10:10:00",
                    "question": "请问什么是html和css",
                    "answer": "HTML 和 CSS 是网页基础",
                    "topics": ["HTML", "CSS"],
                },
            ],
            question_draw_logs=[],
            question_answer_logs=[],
            diagnosis_logs=[],
            behavior_logs=[],
            space_payload={"spaces": []},
            detect_topics_fn=None,
        )

        topics = [item.get("topic") for item in hidden.get("topic_total_table", [])]
        self.assertNotIn("我是你爹吗", topics)
        self.assertNotIn("你好呀", topics)
        self.assertIn("HTML", topics)
        self.assertIn("CSS", topics)


if __name__ == "__main__":
    unittest.main()
