import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    _APP_IMPORT_ERROR = ""
except Exception as e:
    backend_app = None
    _APP_IMPORT_ERROR = str(e)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestApiContractIntegration(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def test_profile_contract(self):
        def fake_load_events(_, suffix):
            if suffix == "content":
                return [{"content_type": "note", "timestamp": "2026-03-16T09:00:00", "topics": ["导数"]}]
            return []

        with patch.object(backend_app, "get_user_profile", return_value={}), \
             patch.object(backend_app, "set_user_profile", return_value=None), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [{"concept": "极限", "mastery": 0.3}] }):
            resp = self.client.get("/api/profile?user_id=u_api")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        profile = data.get("profile", {})
        required = {
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
        self.assertTrue(required.issubset(set(profile.keys())))

    def test_recommendations_contract(self):
        def fake_load_events(_, suffix):
            if suffix == "content":
                return [{"content_type": "note", "timestamp": "2026-03-16T09:00:00", "topics": ["导数"]}]
            if suffix == "diagnosis":
                return [{
                    "question": "导数定义",
                    "user_answer": "不会",
                    "correct_answer": "变化率",
                    "timestamp": "2026-03-16T10:00:00",
                    "diagnosis": {"category": "knowledge", "error_type": "concept", "confidence": 0.9, "signals": ["miss"]},
                }]
            return []

        with patch.object(backend_app, "get_user_profile", return_value={}), \
             patch.object(backend_app, "set_user_profile", return_value=None), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [{"concept": "导数", "mastery": 0.25}], "relations": [], "deleted_concepts": []}):
            resp = self.client.get("/api/recommendations?user_id=u_api&limit=3")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("recommendation_context", data)
        self.assertIn("style_method", data.get("recommendation_context", {}))

        items = data.get("items", [])
        self.assertTrue(len(items) >= 1)
        first = items[0]
        self.assertIn("evidence_brief", first)
        self.assertIn("source_evidence", first)
        self.assertIn("strategy_tags", first)

    def test_learning_path_fallback_contract(self):
        with patch.object(backend_app, "get_user_knowledge", return_value={"concepts": [], "relations": [], "deleted_concepts": []}), \
             patch.object(backend_app, "neo4j_store") as neo4j:
            neo4j.enabled = False
            resp = self.client.get("/api/knowledge_graph/path?user_id=u_api&target=导数")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("path", data)
        self.assertIn("length", data)
        self.assertIn("storage", data)
        self.assertIn("path_source", data)
        self.assertEqual(data.get("path_source"), "json_fallback")
        self.assertGreaterEqual(data.get("length", 0), 2)

    def test_knowledge_graph_map_contract(self):
        bank = [
            {
                "concept": "导数",
                "question": "导数的几何意义与切线斜率",
                "analysis": "导数描述函数变化率，也可理解为切线斜率。",
                "options": ["A. 面积", "B. 切线斜率"],
            },
            {
                "concept": "积分",
                "question": "定积分与面积累计",
                "analysis": "积分体现累加思想。",
                "options": ["A. 变化率", "B. 面积"],
            },
        ]

        with patch.object(backend_app, "get_user_knowledge", return_value={
            "concepts": [{"concept": "导数", "mastery": 0.35}],
            "relations": [],
            "deleted_concepts": [],
        }), patch.object(backend_app, "build_question_bank_for_user", return_value=(bank, {})):
            resp = self.client.post("/api/knowledge_graph/map", json={
                "user_id": "u_api",
                "question_texts": ["导数的几何意义是什么？"],
                "video_texts": ["导数定义、变化率与切线斜率讲解"],
                "note_texts": ["课堂笔记：导数表示函数在某一点的变化率。"],
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("total_count"), 3)
        self.assertIn("method", data)
        self.assertEqual(data.get("method", {}).get("model"), "none")

        results = data.get("mapping_results", [])
        self.assertEqual(len(results), 3)
        for item in results:
            self.assertIn("原始内容", item)
            self.assertIn("知识点", item)
            self.assertIn("置信度", item)
            self.assertGreaterEqual(float(item.get("置信度", 0.0)), 0.0)
            self.assertLessEqual(float(item.get("置信度", 0.0)), 1.0)

        self.assertEqual(results[0].get("知识点"), "导数")
        self.assertEqual(results[1].get("知识点"), "导数")
        self.assertEqual(results[2].get("知识点"), "导数")

    def test_knowledge_graph_extract_returns_top_mapping(self):
        bank = [
            {
                "concept": "导数",
                "question": "导数的几何意义与切线斜率",
                "analysis": "导数描述函数变化率，也可理解为切线斜率。",
                "options": ["A. 面积", "B. 切线斜率"],
            },
        ]

        with patch.object(backend_app, "get_user_knowledge", return_value={
            "concepts": [],
            "relations": [],
            "deleted_concepts": [],
        }), \
             patch.object(backend_app, "set_user_knowledge", return_value=None), \
             patch.object(backend_app, "sync_user_graph", return_value={"synced": False}), \
             patch.object(backend_app, "build_question_bank_for_user", return_value=(bank, {})), \
             patch.object(backend_app, "extract_knowledge_with_ai", return_value={
                 "concepts": [],
                 "relations": [],
                 "ai_used": False,
                 "provider": "mock",
                 "error": "ai_disabled",
             }), \
             patch.object(backend_app, "neo4j_store") as neo4j:
            neo4j.ensure_connected.return_value = False
            resp = self.client.post("/api/knowledge_graph/extract", json={
                "user_id": "u_api",
                "text": "导数的几何意义是什么？",
                "source": "question",
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("mapping_results", data)
        self.assertIn("top_mapping", data)
        self.assertEqual(data.get("top_mapping", {}).get("知识点"), "导数")
        self.assertGreaterEqual(float(data.get("top_mapping", {}).get("置信度", 0.0)), 0.0)

    def test_question_bank_draw_contract(self):
        with patch.object(backend_app, "get_user_knowledge", return_value={
            "concepts": [{"concept": "导数", "mastery": 0.25}],
            "relations": [],
            "deleted_concepts": [],
        }), patch.object(backend_app, "load_user_event_list", return_value=[]):
            resp = self.client.get("/api/question_bank/draw?user_id=u_api&concept=导数")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("question", data)
        self.assertIn("prompt_text", data)
        q = data.get("question", {})
        self.assertIn("id", q)
        self.assertIn("question", q)
        self.assertIn("difficulty", q)

    def test_question_bank_draw_requires_concept(self):
        resp = self.client.get("/api/question_bank/draw?user_id=u_api")

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("error_code"), "INVALID_INPUT")
        self.assertEqual(data.get("required_field"), "concept")

    def test_question_bank_draw_scope_contract(self):
        bank = [
            {
                "id": "qb-ai-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题 1",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-ai-2",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题 2",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-ai-3",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题 3",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-ai-4",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题 4",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-ai-5",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题 5",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-seed-1",
                "concept": "极限",
                "difficulty": "easy",
                "question_type": "single_choice",
                "question": "模板题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "模板题解析",
                "bank_source": "seed_template",
                "created_by": "system",
            },
            {
                "id": "qb-dyn-1",
                "concept": "积分",
                "difficulty": "hard",
                "question_type": "short_answer",
                "question": "动态题",
                "options": [],
                "answer": "关键步骤",
                "analysis": "动态题解析",
                "bank_source": "dynamic_personal",
                "created_by": "u_api",
            },
            {
                "id": "qb-mine-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "我的题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "B",
                "analysis": "我的题解析",
                "bank_source": "user_custom",
                "created_by": "u_api",
            },
            {
                "id": "qb-other-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "别人的公开题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "C",
                "analysis": "别人的题解析",
                "bank_source": "user_import",
                "created_by": "other_user",
            },
        ]

        def pick_first(candidates, weights=None, k=1):
            return [candidates[0]]

        with patch.object(backend_app, "build_question_bank_for_user", return_value=(bank, {})), \
             patch.object(backend_app, "get_recent_drawn_question_ids", return_value=set()), \
             patch.object(backend_app, "append_user_event", return_value=None), \
             patch.object(backend_app.random, "choices", side_effect=pick_first):
            mine_resp = self.client.get("/api/question_bank/draw?user_id=u_api&concept=导数&bank_scope=mine")

            with patch.object(backend_app.random, "random", return_value=0.99):
                ai_resp = self.client.get("/api/question_bank/draw?user_id=u_api&concept=导数&bank_scope=ai")

            with patch.object(backend_app.random, "random", return_value=0.99):
                both_resp = self.client.get("/api/question_bank/draw?user_id=u_api&concept=导数&bank_scope=both")

        self.assertEqual(mine_resp.status_code, 200)
        self.assertEqual(ai_resp.status_code, 200)
        self.assertEqual(both_resp.status_code, 200)

        mine_data = mine_resp.get_json()
        ai_data = ai_resp.get_json()
        both_data = both_resp.get_json()

        self.assertEqual(mine_data.get("question", {}).get("bank_source"), "user_custom")
        self.assertIn(ai_data.get("question", {}).get("bank_source"), {"official_ai", "seed_template", "dynamic_personal"})
        self.assertNotIn(ai_data.get("question", {}).get("bank_source"), {"user_custom", "user_import"})
        self.assertEqual(both_data.get("question", {}).get("bank_source"), "official_ai")

    def test_question_bank_list_scope_contract(self):
        bank = [
            {
                "id": "qb-ai-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "AI题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "AI题解析",
                "bank_source": "official_ai",
                "created_by": "official_ai",
            },
            {
                "id": "qb-seed-1",
                "concept": "极限",
                "difficulty": "easy",
                "question_type": "single_choice",
                "question": "模板题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "A",
                "analysis": "模板题解析",
                "bank_source": "seed_template",
                "created_by": "system",
            },
            {
                "id": "qb-dyn-1",
                "concept": "积分",
                "difficulty": "hard",
                "question_type": "short_answer",
                "question": "动态题",
                "options": [],
                "answer": "关键步骤",
                "analysis": "动态题解析",
                "bank_source": "dynamic_personal",
                "created_by": "u_api",
            },
            {
                "id": "qb-mine-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "我的题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "B",
                "analysis": "我的题解析",
                "bank_source": "user_custom",
                "created_by": "u_api",
            },
            {
                "id": "qb-other-1",
                "concept": "导数",
                "difficulty": "medium",
                "question_type": "single_choice",
                "question": "别人的公开题",
                "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "answer": "C",
                "analysis": "别人的题解析",
                "bank_source": "user_import",
                "created_by": "other_user",
            },
        ]

        with patch.object(backend_app, "build_question_bank_for_user", return_value=(bank, {})):
            mine_resp = self.client.get("/api/question_bank/questions?user_id=u_api&bank_scope=mine")
            ai_resp = self.client.get("/api/question_bank/questions?user_id=u_api&bank_scope=ai")
            both_resp = self.client.get("/api/question_bank/questions?user_id=u_api&bank_scope=both")
            official_resp = self.client.get("/api/question_bank/questions?user_id=u_api&bank_scope=official")
            all_resp = self.client.get("/api/question_bank/questions?user_id=u_api&bank_scope=all")

        self.assertEqual(mine_resp.status_code, 200)
        self.assertEqual(ai_resp.status_code, 200)
        self.assertEqual(both_resp.status_code, 200)
        self.assertEqual(official_resp.status_code, 200)
        self.assertEqual(all_resp.status_code, 200)

        mine_data = mine_resp.get_json()
        ai_data = ai_resp.get_json()
        both_data = both_resp.get_json()
        official_data = official_resp.get_json()
        all_data = all_resp.get_json()

        self.assertEqual(mine_data.get("bank_scope"), "mine")
        self.assertEqual(mine_data.get("count"), 1)
        self.assertEqual(mine_data.get("questions", [{}])[0].get("id"), "qb-mine-1")

        ai_ids = {item.get("id") for item in ai_data.get("questions", [])}
        self.assertEqual(ai_data.get("bank_scope"), "ai")
        self.assertEqual(ai_ids, {"qb-ai-1", "qb-seed-1", "qb-dyn-1"})

        both_ids = {item.get("id") for item in both_data.get("questions", [])}
        self.assertEqual(both_data.get("bank_scope"), "both")
        self.assertEqual(both_ids, {"qb-ai-1", "qb-seed-1", "qb-dyn-1", "qb-mine-1"})
        self.assertNotIn("qb-other-1", both_ids)

        self.assertEqual(official_data.get("bank_scope"), "ai")
        self.assertEqual({item.get("id") for item in official_data.get("questions", [])}, ai_ids)
        self.assertEqual(all_data.get("bank_scope"), "both")
        self.assertEqual({item.get("id") for item in all_data.get("questions", [])}, both_ids)

    def test_question_bank_add_and_answer_contract(self):
        payload = {
            "user_id": "u_api",
            "concept": "导数",
            "difficulty": "medium",
            "question_type": "single_choice",
            "question": "导数的几何意义是？",
            "options": ["A. 曲线切线斜率", "B. 面积", "C. 周长"],
            "answer": "A",
            "analysis": "导数表示变化率，对应切线斜率。",
            "is_public": True,
        }

        with patch.object(backend_app, "load_json", return_value={"items": []}), \
             patch.object(backend_app, "save_json", return_value=None), \
             patch.object(backend_app, "append_user_event", return_value=None):
            add_resp = self.client.post("/api/question_bank/questions", json=payload)

        self.assertEqual(add_resp.status_code, 200)
        add_data = add_resp.get_json()
        self.assertTrue(add_data.get("success"))
        self.assertIn("question", add_data)
        question_id = add_data.get("question", {}).get("id")
        self.assertTrue(question_id)

        question_item = {
            "id": question_id,
            "concept": "导数",
            "difficulty": "medium",
            "question_type": "single_choice",
            "question": "导数的几何意义是？",
            "options": ["A. 曲线切线斜率", "B. 面积", "C. 周长"],
            "answer": "A",
            "analysis": "导数表示变化率，对应切线斜率。",
        }
        with patch.object(backend_app, "find_question_by_id", return_value=question_item), \
             patch.object(backend_app, "append_user_event", return_value=None):
            answer_resp = self.client.post("/api/question_bank/answer", json={
                "user_id": "u_api",
                "question_id": question_id,
                "user_answer": "A",
            })

        self.assertEqual(answer_resp.status_code, 200)
        answer_data = answer_resp.get_json()
        self.assertTrue(answer_data.get("success"))
        self.assertIn("is_correct", answer_data)
        self.assertIn("score", answer_data)
        self.assertIn("feedback", answer_data)

    def test_question_bank_answer_returns_mastery_and_advice_when_wrong(self):
        question_item = {
            "id": "qb-test-1",
            "concept": "导数",
            "difficulty": "medium",
            "question_type": "short_answer",
            "question": "导数的几何意义是？",
            "options": [],
            "answer": "切线斜率",
            "analysis": "导数表示变化率，对应切线斜率。",
        }
        appended = []
        saved = {}

        def fake_append(user_id, suffix, item):
            appended.append((user_id, suffix, item))

        def fake_load_events(_, suffix):
            if suffix == "question_draw":
                return [{
                    "timestamp": "2026-03-31T10:05:00",
                    "question_id": "qb-test-1",
                    "concept": "导数",
                }]
            if suffix == "question_answer":
                return [
                    {
                        "timestamp": "2026-03-30T10:00:00",
                        "concept": "导数",
                        "is_correct": True,
                        "score": 1.0,
                        "duration_seconds": 75,
                    },
                    {
                        "timestamp": "2026-03-31T09:00:00",
                        "concept": "导数",
                        "is_correct": True,
                        "score": 1.0,
                        "duration_seconds": 88,
                    },
                ]
            return []

        def fake_set_user_knowledge(_, payload):
            saved["knowledge"] = payload

        with patch.object(backend_app, "find_question_by_id", return_value=question_item), \
             patch.object(backend_app, "append_user_event", side_effect=fake_append), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_knowledge", return_value={
                 "concepts": [{"concept": "导数", "mastery": 0.78, "review_count": 2}],
                 "relations": [],
                 "deleted_concepts": [],
             }), \
             patch.object(backend_app, "set_user_knowledge", side_effect=fake_set_user_knowledge), \
             patch.object(backend_app, "sync_mastery_update", return_value={"enabled": False, "mode": "disabled", "synced": False}):
            answer_resp = self.client.post("/api/question_bank/answer", json={
                "user_id": "u_api",
                "question_id": "qb-test-1",
                "user_answer": "切线率",
            })

        self.assertEqual(answer_resp.status_code, 200)
        answer_data = answer_resp.get_json()
        self.assertTrue(answer_data.get("success"))
        self.assertIn("mastery_assessment", answer_data)
        self.assertIn("learning_advice", answer_data)
        self.assertIn("graph_sync", answer_data)
        self.assertEqual(answer_data.get("diagnosis", {}).get("error_type"), "习惯性错误")
        self.assertIn("recent_accuracy", answer_data.get("diagnosis", {}))
        self.assertIn("near_miss", answer_data.get("diagnosis", {}))
        self.assertTrue(any(suffix == "diagnosis" for _, suffix, _ in appended))
        self.assertTrue(saved.get("knowledge"))
        concept_items = saved["knowledge"].get("concepts", [])
        concept_item = next(item for item in concept_items if item.get("concept") == "导数")
        self.assertIn("mastery_status", concept_item)
        self.assertIn("practice_count", concept_item)
        self.assertIn("recent_accuracy", concept_item)
        self.assertIn("standard_answer_seconds", concept_item)

    def test_question_bank_import_contract(self):
        import_body = {
            "user_id": "u_api",
            "text": "导数||medium||single_choice||导数的几何意义是？||A.切线斜率;B.面积;C.体积||A||导数表示变化率",
        }
        with patch.object(backend_app, "load_json", return_value={"items": []}), \
             patch.object(backend_app, "save_json", return_value=None):
            resp = self.client.post("/api/question_bank/import", json=import_body)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("imported_count", data)
        self.assertGreaterEqual(data.get("imported_count", 0), 1)

    def test_question_bank_generate_contract(self):
        fake_questions = [{
            "id": "qb-ai-1",
            "concept": "导数",
            "difficulty": "medium",
            "question_type": "single_choice",
            "question": "导数的几何意义是？",
            "options": ["A.切线斜率", "B.面积", "C.体积", "D.均值"],
            "answer": "A",
            "analysis": "导数表示变化率",
            "bank_source": "official_ai",
            "created_by": "official_ai",
            "is_public": True,
        }]
        with patch.object(backend_app, "generate_official_questions_with_ai", return_value=(fake_questions, "ai")), \
             patch.object(backend_app, "load_json", return_value={"items": []}), \
             patch.object(backend_app, "save_json", return_value=None):
            resp = self.client.post("/api/question_bank/generate", json={
                "user_id": "u_api",
                "concept": "导数",
                "difficulty": "medium",
                "count": 1,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("generated_count"), 1)
        self.assertIn("sample_questions", data)

    def test_behavior_track_contract(self):
        captured = {}

        def fake_append(user_id, suffix, item):
            captured["user_id"] = user_id
            captured["suffix"] = suffix
            captured["item"] = item

        with patch.object(backend_app, "append_user_event", side_effect=fake_append):
            resp = self.client.post("/api/behavior/track", json={
                "user_id": "u_api",
                "behavior_type": "page_stay",
                "page": "dashboard",
                "duration_seconds": 128.4,
                "label": "pagehide",
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("accepted"))
        self.assertEqual(captured.get("user_id"), "u_api")
        self.assertEqual(captured.get("suffix"), "behavior")
        self.assertEqual(captured.get("item", {}).get("behavior_type"), "page_stay")
        self.assertEqual(captured.get("item", {}).get("page"), "dashboard")

    def test_dashboard_summary_contract(self):
        def fake_load_events(_, suffix):
            if suffix == "content":
                return [
                    {
                        "content_type": "image",
                        "timestamp": "2026-03-30T08:30:00",
                        "title": "导数截图",
                        "source": "upload_image",
                        "topics": ["导数", "极限"],
                    },
                    {
                        "content_type": "link",
                        "timestamp": "2026-03-30T19:30:00",
                        "title": "导数视频讲解",
                        "source": "manual",
                        "topics": ["导数"],
                    },
                    {
                        "content_type": "note",
                        "timestamp": "2026-03-31T09:10:00",
                        "title": "积分笔记",
                        "source": "manual",
                        "topics": ["积分"],
                    },
                ]
            if suffix == "qa":
                return [
                    {
                        "timestamp": "2026-03-31T10:00:00",
                        "question": "导数的定义是什么？",
                        "answer": "变化率",
                    }
                ]
            if suffix == "behavior":
                return [
                    {
                        "timestamp": "2026-03-31T10:20:00",
                        "behavior_type": "page_stay",
                        "page": "question-bank",
                        "duration_seconds": 600,
                    },
                    {
                        "timestamp": "2026-03-31T10:21:00",
                        "behavior_type": "navigation_click",
                        "page": "index",
                        "target": "knowledge-map",
                        "label": "知识图谱",
                    },
                ]
            if suffix == "question_draw":
                return [
                    {
                        "timestamp": "2026-03-31T10:05:00",
                        "concept": "导数",
                        "difficulty": "medium",
                        "question_type": "single_choice",
                    }
                ]
            if suffix == "question_answer":
                return [
                    {
                        "timestamp": "2026-03-31T10:08:00",
                        "concept": "导数",
                        "difficulty": "medium",
                        "question_type": "single_choice",
                        "is_correct": False,
                        "score": 0.4,
                    }
                ]
            if suffix == "diagnosis":
                return [
                    {
                        "timestamp": "2026-03-31T10:09:00",
                        "question": "导数定义题",
                        "correct_answer": "变化率",
                        "user_answer": "不会",
                        "diagnosis": {
                            "category": "knowledge",
                            "error_type": "概念性错误",
                            "severity": "high",
                            "signals": ["答案过短"],
                            "recommendation": "回到定义和典型例题进行复习",
                        },
                    }
                ]
            if suffix == "wrong_question":
                return [
                    {
                        "timestamp": "2026-03-31T10:08:00",
                        "source": "question_answer",
                        "source_key": "question_answer::2026-03-31T10:08:00::导数",
                        "question": "导数练习题",
                        "user_answer": "B",
                        "concept": "导数",
                        "topics": ["导数"],
                        "is_correct": False,
                    }
                ]
            return []

        with patch.object(backend_app, "get_user_profile", return_value={}), \
             patch.object(backend_app, "set_user_profile", return_value=None), \
             patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events), \
             patch.object(backend_app, "get_user_space_payload", return_value={
                 "activeEntrySpaceId": "space_1",
                 "spaces": [
                     {
                         "id": "space_1",
                         "name": "学习空间",
                         "items": [
                             {"id": "item_1", "kind": "image", "name": "导数截图", "summary": "图片内容"},
                             {"id": "item_2", "kind": "link", "name": "导数课程链接", "summary": "链接内容"},
                         ],
                     }
                 ],
             }), \
             patch.object(backend_app, "get_user_knowledge", return_value={
                 "concepts": [
                     {"concept": "导数", "mastery": 0.35, "review_count": 1, "first_seen": "2026-03-30T08:30:00"},
                     {"concept": "极限", "mastery": 0.72, "review_count": 2, "first_seen": "2026-03-29T08:30:00"},
                 ],
                 "relations": [
                     {"source": "极限", "target": "导数", "type": "前置", "score": 0.9},
                 ],
                 "deleted_concepts": [],
             }), \
             patch.object(backend_app, "build_graph_response", return_value={
                 "success": True,
                 "graph": {
                     "nodes": [
                         {"id": "极限", "mastery": 0.72},
                         {"id": "导数", "mastery": 0.35},
                     ],
                     "links": [
                         {"source": "极限", "target": "导数", "label": "前置", "score": 0.9},
                     ],
                 },
                 "node_count": 2,
                 "edge_count": 1,
             }), \
             patch.object(backend_app, "build_review_reminders_response", return_value={
                 "due_count": 1,
                 "upcoming_count": 1,
                 "due_items": [
                     {"concept": "导数", "mastery": 0.35, "due": True, "overdue_days": 1, "next_review": "2026-03-31T08:00:00"},
                 ],
                 "upcoming_items": [
                     {"concept": "极限", "mastery": 0.72, "due": False, "overdue_days": 0, "next_review": "2026-04-02T08:00:00"},
                 ],
             }), \
             patch.object(backend_app, "build_recommendations", return_value=[
                 {
                     "concept": "导数",
                     "title": "导数 - 知识导图+图解微课",
                     "reason": "掌握度较低，优先补强",
                     "resource_type": "知识导图+图解微课",
                     "recommend_time": "19:00-21:00",
                     "strategy_tags": ["style:visual", "channel:visual", "method:kmeans"],
                     "evidence_brief": "画像:视觉型(kmeans) | 图谱:掌握度35%",
                 }
             ]), \
             patch.object(backend_app, "get_storage_info", return_value={"storage_backend": "json", "database_scheme": "json"}), \
             patch.object(backend_app, "get_ai_runtime_config", return_value={"provider": "mock"}), \
             patch.object(backend_app, "neo4j_store") as neo4j:
            neo4j.ensure_connected.return_value = False
            resp = self.client.get("/api/dashboard/summary?user_id=u_api")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("data_pool", data)
        self.assertIn("graph_insights", data)
        self.assertIn("profile_insights", data)
        self.assertIn("intervention_summary", data)
        self.assertGreaterEqual(data.get("data_pool", {}).get("total_records", 0), 1)
        self.assertEqual(data.get("data_pool", {}).get("wrong_question_count"), 1)
        self.assertEqual(data.get("data_pool", {}).get("space_content_count"), 2)
        self.assertGreaterEqual(data.get("data_pool", {}).get("learning_content_record_count", 0), 2)
        self.assertTrue(len(data.get("graph_insights", {}).get("mastery_heatmap", [])) >= 1)
        self.assertTrue(len(data.get("profile_insights", {}).get("media_preferences", [])) >= 1)
        self.assertTrue(len(data.get("intervention_summary", {}).get("action_queue", [])) >= 1)

    def test_wrong_question_bank_contract(self):
        wrong_items = [
            {
                "timestamp": "2026-03-31T11:20:00",
                "source": "question_answer",
                "question": "导数的几何意义是什么？",
                "user_answer": "不会",
                "concept": "导数",
                "topics": ["导数"],
                "is_correct": False,
            },
            {
                "timestamp": "2026-03-30T09:05:00",
                "source": "qa_confusion",
                "question": "这个积分换元我看不懂",
                "user_answer": "不会/看不懂",
                "concept": "积分",
                "topics": ["积分"],
                "is_correct": False,
            },
        ]

        def fake_load_events(_, suffix):
            if suffix == "wrong_question":
                return wrong_items
            return []

        with patch.object(backend_app, "load_user_event_list", side_effect=fake_load_events):
            resp = self.client.get("/api/wrong_questions?user_id=u_api")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("count"), 2)
        self.assertEqual(data.get("items", [])[0].get("concept"), "导数")


if __name__ == "__main__":
    unittest.main()
