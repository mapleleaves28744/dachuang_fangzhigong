import unittest
from unittest.mock import MagicMock, patch

from app.services.knowledge_base import ingest_kb_note, search_kb


class TestKnowledgeBaseGraphRag(unittest.TestCase):
    def test_search_fallback_when_public_vector_unavailable(self):
        fake_docs = [
            {
                "doc_id": "d_private_1",
                "title": "HTML 与 CSS 入门",
                "content": "HTML 负责结构，CSS 负责样式。",
                "source": "content_log",
                "content_type": "note",
                "timestamp": "2026-04-11T10:00:00",
            }
        ]

        with patch("app.services.knowledge_base._collect_docs", return_value=fake_docs), patch(
            "app.services.knowledge_base._search_public_chunks", return_value=[]
        ), patch("app.services.knowledge_base._load_public_kb_once", return_value={"enabled": False, "chunks": [], "error": "offline"}):
            out = search_kb("u_offline", "HTML CSS 入门笔记", top_k=3)

        self.assertEqual(out.get("retrieval_mode"), "hybrid")
        self.assertEqual(out.get("public_docs"), 0)
        self.assertGreaterEqual(len(out.get("hits", [])), 1)

    def test_ingest_records_kb_note_event(self):
        with patch("app.services.knowledge_base.append_user_event") as mock_append:
            item = ingest_kb_note(
                user_id="u_graph",
                title="链式法则笔记",
                content="复合函数求导使用链式法则。",
                source="agent_kb",
                tags=["导数", "链式法则"],
            )

        self.assertIn("id", item)
        self.assertTrue(mock_append.called)

    def test_ingest_syncs_graph_note(self):
        fake_store = MagicMock()
        fake_store.upsert_kb_note_graph.return_value = True

        with patch("app.services.knowledge_base.append_user_event"), patch(
            "app.services.knowledge_base._extract_graph_concepts", return_value=["链式法则", "复合函数"]
        ), patch("app.services.knowledge_base._get_neo4j_store", return_value=fake_store):
            item = ingest_kb_note(
                user_id="u_graph_sync",
                title="链式法则笔记",
                content="复合函数求导使用链式法则。",
                source="agent_kb",
                tags=["导数", "链式法则"],
            )

        fake_store.upsert_kb_note_graph.assert_called_once()
        sync_kwargs = fake_store.upsert_kb_note_graph.call_args.kwargs
        self.assertEqual(sync_kwargs.get("note_id"), item.get("id"))
        self.assertEqual(sync_kwargs.get("user_id"), "u_graph_sync")
        self.assertIn("链式法则", sync_kwargs.get("concepts", []))

    def test_search_returns_basic_contract_fields(self):
        fake_docs = [
            {
                "doc_id": "d1",
                "title": "链式法则总结",
                "content": "复合函数求导常用链式法则",
                "source": "content_log",
                "content_type": "kb_note",
                "timestamp": "2026-04-10T10:00:00",
            }
        ]

        with patch("app.services.knowledge_base._collect_docs", return_value=fake_docs), patch(
            "app.services.knowledge_base._load_public_kb_once", return_value={"enabled": False, "chunks": [], "error": "offline"}
        ):
            out = search_kb("u_graph", "链式法则", top_k=3)

        self.assertIn("hits", out)
        self.assertIsInstance(out.get("hits", []), list)
        self.assertGreaterEqual(len(out.get("hits", [])), 1)
        self.assertIn("graph_context", out)
        self.assertIsInstance(out.get("graph_context", []), list)

    def test_search_returns_graph_context_when_graph_available(self):
        fake_docs = [
            {
                "doc_id": "d1",
                "source_doc_id": "d1",
                "title": "链式法则总结",
                "content": "复合函数求导常用链式法则",
                "source": "content_log",
                "content_type": "kb_note",
                "timestamp": "2026-04-10T10:00:00",
                "tags": ["链式法则"],
                "topics": ["链式法则"],
            }
        ]
        fake_store = MagicMock()
        fake_store.query_graph_rag_context.return_value = [
            {
                "concept": "链式法则",
                "query_concept": "链式法则",
                "doc_id": "d1",
                "source_doc_id": "d1",
                "doc_title": "链式法则总结",
                "doc_content": "复合函数求导常用链式法则",
                "doc_source": "agent_kb",
                "doc_tags": ["链式法则"],
                "relations": [{"neighbor": "复合函数", "relation": "前置"}],
                "relation_count": 1,
                "similarity_to_query": 0.91,
            }
        ]

        with patch("app.services.knowledge_base._collect_docs", return_value=fake_docs), patch(
            "app.services.knowledge_base._search_public_chunks", return_value=[]
        ), patch(
            "app.services.knowledge_base._load_public_kb_once",
            return_value={"enabled": False, "chunks": [], "error": "offline"},
        ), patch(
            "app.services.knowledge_base._extract_graph_concepts", return_value=["链式法则"]
        ), patch(
            "app.services.knowledge_base._get_neo4j_store", return_value=fake_store
        ):
            out = search_kb("u_graph", "链式法则是什么", top_k=3)

        self.assertGreaterEqual(len(out.get("graph_context", [])), 1)
        self.assertGreater(out.get("graph_contribution_rate", 0.0), 0.0)
        first_hit = out.get("hits", [])[0]
        self.assertEqual(first_hit.get("doc_id"), "d1")
        self.assertIn("链式法则", first_hit.get("matched_concepts", []))

    def test_search_hybrid_with_public_vector_hits(self):
        fake_docs = [
            {
                "doc_id": "d_private",
                "title": "私有笔记",
                "content": "链式法则用于复合函数求导。",
                "source": "content_log",
                "content_type": "kb_note",
                "timestamp": "2026-04-10T10:00:00",
            }
        ]
        fake_public = [
            {
                "doc_id": "d_public",
                "title": "公共知识点",
                "snippet": "导数与链式法则核心定义",
                "source": "public_pro_kb",
                "content_type": "core",
                "channel": "public_vector",
                "score": 0.92,
                "chapter": "导数与微分",
            }
        ]

        with patch("app.services.knowledge_base._collect_docs", return_value=fake_docs), patch(
            "app.services.knowledge_base._search_public_chunks", return_value=fake_public
        ), patch("app.services.knowledge_base._load_public_kb_once", return_value={"enabled": True, "chunks": [{}] * 5}):
            out = search_kb("u_hybrid", "链式法则", top_k=3)

            self.assertEqual(out.get("retrieval_mode"), "hybrid")
            self.assertGreater(out.get("public_docs", 0), 0)
            self.assertGreaterEqual(len(out.get("hits", [])), 1)
            channels = {x.get("channel") for x in out.get("hits", [])}
            self.assertIn("public_vector", channels)

    def test_search_falls_back_to_demo_public_chunks_when_public_vector_unavailable(self):
        with patch("app.services.knowledge_base._collect_docs", return_value=[]), patch(
            "app.services.knowledge_base._load_public_kb_once",
            return_value={"enabled": False, "chunks": [], "error": "git lfs pointer"},
        ), patch(
            "app.services.knowledge_base._query_graph_context",
            return_value=[],
        ):
            out = search_kb("u_demo_public", "导数 切线斜率", top_k=3)

        self.assertEqual(out.get("public_source"), "demo_fallback")
        self.assertGreater(out.get("public_docs", 0), 0)
        self.assertGreaterEqual(len(out.get("hits", [])), 1)
        self.assertIn("public_demo_fallback", {x.get("channel") for x in out.get("hits", [])})

    def test_search_uses_private_vector_chunks_for_long_documents(self):
        long_text = (
            "前言部分。"
            + "无关内容。" * 120
            + "关键知识：链式法则用于复合函数求导，先求外层导数再乘以内层导数。"
            + "补充说明。" * 120
        )
        fake_docs = [
            {
                "doc_id": "d_long",
                "source_doc_id": "d_long",
                "title": "复合函数长讲义",
                "content": long_text,
                "source": "content_log",
                "content_type": "note",
                "timestamp": "2026-04-14T10:00:00",
                "tags": ["链式法则"],
                "topics": ["链式法则"],
            }
        ]

        with patch("app.services.knowledge_base._collect_docs", return_value=fake_docs), patch(
            "app.services.knowledge_base._load_public_kb_once",
            return_value={"enabled": False, "chunks": [], "error": "offline"},
        ), patch(
            "app.services.knowledge_base._query_graph_context",
            return_value=[],
        ):
            out = search_kb("u_private_vector", "链式法则 复合函数 求导步骤", top_k=3)

        self.assertGreaterEqual(len(out.get("hits", [])), 1)
        channels = {x.get("channel") for x in out.get("hits", [])}
        self.assertIn("private_vector", channels)

    def test_search_uses_question_answer_and_wrong_question_logs_for_personalization(self):
        def fake_get_user_event_list(user_id, suffix):
            if suffix == "content":
                return []
            if suffix == "question_answer":
                return [
                    {
                        "id": "qa_answer_1",
                        "timestamp": "2026-04-14T10:00:00",
                        "question": "求复合函数的导数",
                        "user_answer": "我只对外层函数求导了",
                        "expected_answer": "先对外层求导，再乘以内层导数",
                        "concept": "链式法则",
                        "difficulty": "medium",
                        "score": 0.2,
                        "is_correct": False,
                    }
                ]
            if suffix == "wrong_question":
                return [
                    {
                        "id": "wrong_1",
                        "timestamp": "2026-04-14T10:05:00",
                        "question": "y=sin(x^2) 怎么求导",
                        "user_answer": "cos(x^2)",
                        "expected_answer": "2x*cos(x^2)",
                        "answer_excerpt": "漏乘了内层函数的导数 2x",
                        "error_type": "步骤遗漏",
                        "concept": "链式法则",
                        "topics": ["链式法则"],
                    }
                ]
            return []

        with patch("app.services.knowledge_base.get_user_event_list", side_effect=fake_get_user_event_list), patch(
            "app.services.knowledge_base.get_user_space_payload",
            return_value={"spaces": []},
        ), patch(
            "app.services.knowledge_base._load_public_kb_once",
            return_value={"enabled": False, "chunks": [], "error": "offline"},
        ):
            out = search_kb("u_personal_logs", "链式法则 漏乘 内层导数", top_k=3)

        self.assertGreaterEqual(len(out.get("hits", [])), 1)
        sources = {str(item.get("source") or "") for item in out.get("hits", [])}
        self.assertTrue({"question_answer", "wrong_question"} & sources)
        self.assertTrue(all(item.get("source_type") == "private" for item in out.get("hits", [])))


if __name__ == "__main__":
    unittest.main()
