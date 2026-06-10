import json
import unittest
import sys
import types
from unittest.mock import MagicMock, patch


def _install_langchain_stubs():
    class _DummyTool:
        def __init__(self, fn):
            self._fn = fn
            self.name = getattr(fn, "__name__", "tool")

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

        def invoke(self, payload):
            if isinstance(payload, dict):
                return self._fn(**payload)
            return self._fn(payload)

    def _tool(fn=None, **_kwargs):
        if fn is None:
            return lambda inner: _DummyTool(inner)
        return _DummyTool(fn)

    langchain_pkg = types.ModuleType("langchain")
    langchain_agents = types.ModuleType("langchain.agents")
    langchain_agents.AgentExecutor = object
    langchain_agents.create_tool_calling_agent = lambda *args, **kwargs: None

    langchain_memory = types.ModuleType("langchain.memory")
    langchain_memory_chat = types.ModuleType("langchain.memory.chat_message_histories")

    class _ChatMessageHistory:
        def __init__(self, *args, **kwargs):
            self.messages = []

    langchain_memory_chat.ChatMessageHistory = _ChatMessageHistory

    langchain_core = types.ModuleType("langchain_core")
    langchain_core_tools = types.ModuleType("langchain_core.tools")
    langchain_core_tools.tool = _tool

    langchain_core_callbacks = types.ModuleType("langchain_core.callbacks")

    class _BaseCallbackHandler:
        pass

    langchain_core_callbacks.BaseCallbackHandler = _BaseCallbackHandler

    langchain_core_prompts = types.ModuleType("langchain_core.prompts")

    class _ChatPromptTemplate:
        @staticmethod
        def from_messages(_messages):
            return None

    class _MessagesPlaceholder:
        def __init__(self, *args, **kwargs):
            pass

    langchain_core_prompts.ChatPromptTemplate = _ChatPromptTemplate
    langchain_core_prompts.MessagesPlaceholder = _MessagesPlaceholder

    langchain_core_runnables = types.ModuleType("langchain_core.runnables")
    langchain_core_runnables_history = types.ModuleType("langchain_core.runnables.history")
    langchain_core_runnables_history.RunnableWithMessageHistory = object

    langchain_openai = types.ModuleType("langchain_openai")
    langchain_openai.ChatOpenAI = object

    langchain_community = types.ModuleType("langchain_community")
    langchain_community_chat = types.ModuleType("langchain_community.chat_message_histories")
    langchain_community_chat.RedisChatMessageHistory = _ChatMessageHistory
    langchain_community_chat.ChatMessageHistory = _ChatMessageHistory

    sys.modules.setdefault("langchain", langchain_pkg)
    sys.modules["langchain.agents"] = langchain_agents
    sys.modules["langchain.memory"] = langchain_memory
    sys.modules["langchain.memory.chat_message_histories"] = langchain_memory_chat
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_core_tools
    sys.modules["langchain_core.callbacks"] = langchain_core_callbacks
    sys.modules["langchain_core.prompts"] = langchain_core_prompts
    sys.modules["langchain_core.runnables"] = langchain_core_runnables
    sys.modules["langchain_core.runnables.history"] = langchain_core_runnables_history
    sys.modules["langchain_openai"] = langchain_openai
    sys.modules["langchain_community"] = langchain_community
    sys.modules["langchain_community.chat_message_histories"] = langchain_community_chat


try:
    from app.services.agent_service import TutorAgentService

    _IMPORT_ERROR = ""
except Exception as exc:
    TutorAgentService = None
    _IMPORT_ERROR = str(exc)
    if "langchain" in _IMPORT_ERROR.lower():
        try:
            _install_langchain_stubs()
            from app.services.agent_service import TutorAgentService

            _IMPORT_ERROR = ""
        except Exception as retry_exc:
            TutorAgentService = None
            _IMPORT_ERROR = str(retry_exc)


@unittest.skipIf(TutorAgentService is None, f"agent service unavailable: {_IMPORT_ERROR}")
class TestAgentServiceGraphRagRouting(unittest.TestCase):
    def _build_service(self):
        service = TutorAgentService.__new__(TutorAgentService)
        service.enable_guard = False
        service.chat_history_backend = "memory"
        service.max_retries = 0
        service._build_steps_log = MagicMock(
            side_effect=[
                [
                    {
                        "tool_name": "tool_search_learning_kb",
                        "tool_input": {"student_id": "u1", "query": "链式法则"},
                        "tool_output_summary": "ok",
                        "latency_ms": 5,
                        "status": "success",
                    }
                ],
                [
                    {
                        "tool_name": "tool_graph_rag_search",
                        "tool_input": {"student_id": "u1", "query": "链式法则"},
                        "tool_output_summary": "ok",
                        "latency_ms": 4,
                        "status": "success",
                    }
                ],
            ]
        )
        service._invoke_with_timeout_retry = MagicMock(
            side_effect=[
                (
                    {
                        "output": "第一次回答",
                        "intermediate_steps": [("first", "result")],
                    },
                    12.0,
                    False,
                    0,
                ),
                (
                    {
                        "output": "第二次回答",
                        "intermediate_steps": [("second", "result")],
                    },
                    8.0,
                    False,
                    0,
                ),
            ]
        )
        return service

    def test_graph_question_routes_to_graph_tool(self):
        service = self._build_service()

        with patch("app.services.agent_service.get_user_knowledge", return_value={}), patch(
            "app.services.agent_service.agent_metrics.record_request"
        ):
            result = service.solve_problem(
                session_id="s_graph",
                student_id="u1",
                ocr_text="求复合函数导数",
                question_text="链式法则和复合函数是什么关系",
            )

        self.assertEqual(service._invoke_with_timeout_retry.call_count, 2)
        first_input = service._invoke_with_timeout_retry.call_args_list[0].args[0]["input"]
        second_input = service._invoke_with_timeout_retry.call_args_list[1].args[0]["input"]

        self.assertIn("tool_graph_rag_search(student_id, query)", first_input)
        self.assertIn("必须先调用 tool_graph_rag_search", second_input)
        self.assertTrue(result.get("meta", {}).get("kb_retry_triggered"))
        self.assertEqual(result.get("meta", {}).get("preferred_kb_tool"), "tool_graph_rag_search")
        self.assertEqual(result.get("steps_log", [])[0].get("tool_name"), "tool_graph_rag_search")

    def test_stream_graph_question_routes_to_graph_tool(self):
        service = self._build_service()

        with patch("app.services.agent_service.get_user_knowledge", return_value={}), patch(
            "app.services.agent_service.agent_metrics.record_request"
        ):
            events = list(
                service.stream_solve_problem(
                    session_id="s_graph_stream",
                    student_id="u1",
                    ocr_text="求复合函数导数",
                    question_text="链式法则和复合函数是什么关系",
                )
            )

        self.assertEqual(service._invoke_with_timeout_retry.call_count, 2)
        self.assertTrue(any('"type": "retry"' in event for event in events))

        final_raw = next(event for event in events if '"type": "final"' in event)
        final_payload = json.loads(final_raw.split("data:", 1)[1].strip()).get("payload", {})

        self.assertTrue(final_payload.get("meta", {}).get("kb_retry_triggered"))
        self.assertEqual(final_payload.get("meta", {}).get("preferred_kb_tool"), "tool_graph_rag_search")
        self.assertEqual(final_payload.get("steps_log", [])[0].get("tool_name"), "tool_graph_rag_search")

    def test_sanitize_user_visible_answer_hides_internal_analysis_block(self):
        raw_answer = (
            "# 分析\n"
            "学生当前掌握度偏低，依据 `tool_get_student_mastery` 返回值需要先补基础。\n\n"
            "## 讲解\n"
            "函数表示输入和输出之间的对应关系。\n\n"
            "## 建议\n"
            "先复习定义，再做两道基础题。"
        )

        cleaned = TutorAgentService._sanitize_user_visible_answer(raw_answer)

        self.assertNotIn("tool_get_student_mastery", cleaned)
        self.assertNotIn("# 分析", cleaned)
        self.assertIn("## 讲解", cleaned)
        self.assertIn("## 建议", cleaned)

    def test_sanitize_user_visible_answer_keeps_normal_explanation(self):
        raw_answer = (
            "讲解\n"
            "函数的核心是每个输入只对应一个输出。\n\n"
            "建议\n"
            "记住“唯一对应”这个关键词。"
        )

        cleaned = TutorAgentService._sanitize_user_visible_answer(raw_answer)

        self.assertEqual(cleaned, raw_answer)


if __name__ == "__main__":
    unittest.main()
