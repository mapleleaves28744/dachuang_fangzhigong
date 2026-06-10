import uuid
from datetime import datetime

from .agent_tools import _build_learning_plan_payload
from .concept_mapping import extract_text_keywords
from .database import append_user_event, get_user_knowledge, get_user_plans, set_user_plans
from .knowledge_base import search_kb
from .topic_guard import filter_learning_topics


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _pick_focus_topic(question: str, search_result: dict, knowledge: dict) -> str:
    graph_concepts = search_result.get("graph_query_concepts", []) if isinstance(search_result, dict) else []
    if graph_concepts:
        return str(graph_concepts[0] or "").strip()

    hits = search_result.get("hits", []) if isinstance(search_result, dict) else []
    if hits:
        first = hits[0]
        matched = first.get("matched_concepts", []) if isinstance(first.get("matched_concepts", []), list) else []
        if matched:
            return str(matched[0] or "").strip()
        title = str(first.get("title") or "").strip()
        if title:
            return title

    concepts = knowledge.get("concepts", []) if isinstance(knowledge, dict) else []
    keywords = extract_text_keywords(str(question or ""), max_keywords=6)
    filtered = filter_learning_topics(keywords, limit=6)
    for keyword in filtered:
        topic = str(keyword or "").strip()
        if topic:
            return topic

    for item in concepts:
        concept = str((item or {}).get("concept") or "").strip()
        if concept:
            return concept
    return "当前主题"


def _get_mastery_info(knowledge: dict, topic: str):
    topic_text = str(topic or "").strip()
    concepts = knowledge.get("concepts", []) if isinstance(knowledge, dict) else []
    for item in concepts:
        concept = str((item or {}).get("concept") or "").strip()
        if not concept:
            continue
        if concept == topic_text or topic_text in concept or concept in topic_text:
            try:
                mastery = float(item.get("mastery", 0.0) or 0.0)
            except Exception:
                mastery = 0.0
            return {"concept": concept, "mastery": mastery}
    return {"concept": topic_text, "mastery": None}


def _mastery_label(score):
    if score is None:
        return "暂无画像数据"
    if score < 0.4:
        return "当前掌握偏弱，适合先补概念和步骤"
    if score < 0.7:
        return "当前掌握一般，适合做变式训练"
    return "当前掌握较好，适合做综合拓展"


def _persist_learning_plan(plan: dict):
    student_id = str(plan.get("student_id") or "").strip()
    if not student_id:
        return plan
    topic = str(plan.get("topic") or "").strip()
    plan_items = plan.get("plan_items", []) if isinstance(plan.get("plan_items", []), list) else []
    if not plan_items:
        return plan

    existing_plans = get_user_plans(student_id) or []
    retained = [
        item for item in existing_plans
        if not (
            isinstance(item, dict)
            and str(item.get("source") or "").strip() == "agent_learning_plan"
            and str(item.get("topic") or "").strip() == topic
        )
    ]
    merged = retained + plan_items
    merged.sort(key=lambda item: (str(item.get("time") or ""), str(item.get("id") or "")))
    set_user_plans(student_id, merged)

    append_user_event(student_id, "learning_plan", {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "student_id": student_id,
        "topic": topic,
        "style": plan.get("style", "visual"),
        "mastery": plan.get("mastery"),
        "best_time_range": plan.get("best_time_range"),
        "focus_minutes": plan.get("focus_minutes"),
        "plan_items": plan_items,
        "source": "local_rule_fallback",
    })
    return plan


def build_rule_based_tutor_response(
    *,
    student_id: str,
    question: str,
    route_type: str = "kb_search",
    persist_plan: bool = True,
):
    uid = str(student_id or "").strip()
    question_text = str(question or "").strip() or "请根据我的资料做学习辅导"
    knowledge = (get_user_knowledge(uid) or {}) if uid else {}
    kb_result = search_kb(uid, question_text, top_k=3, search_mode="hybrid")
    hits = kb_result.get("hits", []) if isinstance(kb_result, dict) else []
    graph_context = kb_result.get("graph_context", []) if isinstance(kb_result, dict) else []

    focus_topic = _pick_focus_topic(question_text, kb_result, knowledge)
    mastery_info = _get_mastery_info(knowledge, focus_topic)
    if uid:
        plan = _build_learning_plan_payload(uid, focus_topic)
    else:
        plan = {
            "student_id": "",
            "topic": focus_topic,
            "style": "visual",
            "best_time_range": "",
            "focus_minutes": 40,
            "mastery": mastery_info.get("mastery"),
            "plan_items": [],
        }
    if persist_plan and uid:
        plan = _persist_learning_plan(plan)

    analysis_lines = [
        "分析",
        f"当前问题聚焦于“{focus_topic}”。",
        f"检索结果显示：命中 {len(hits)} 条资料，图谱增强贡献 {float(kb_result.get('graph_contribution_rate', 0.0) or 0.0):.3f}。",
    ]
    if hits:
        top_hit = hits[0]
        analysis_lines.append(
            f"优先证据来自《{top_hit.get('title', '学习资料')}》，来源通道为 {top_hit.get('channel', 'unknown')}。"
        )

    explain_lines = ["讲解"]
    if hits:
        for idx, hit in enumerate(hits[:2], start=1):
            explain_lines.append(
                f"{idx}. 根据资料《{hit.get('title', '学习资料')}》：{_normalize_text(hit.get('snippet', ''))}"
            )
    else:
        explain_lines.append("当前没有命中现成资料，我会按已有知识图谱和学习画像给出规则化建议。")

    if graph_context:
        first_graph = graph_context[0]
        relation_summary = "；".join(
            f"{str(rel.get('relation') or '相关')}->{str(rel.get('neighbor') or '').strip()}"
            for rel in (first_graph.get("relations", []) if isinstance(first_graph.get("relations", []), list) else [])[:4]
            if str((rel or {}).get("neighbor") or "").strip()
        )
        if relation_summary:
            explain_lines.append(f"图谱提示：{focus_topic} 相关路径包括 {relation_summary}。")

    advice_lines = [
        "建议",
        f"{_mastery_label(mastery_info.get('mastery'))}。",
        "先看定义和公式来源，再做同题型练习，最后复盘口头表达是否清楚。",
    ]

    practice_lines = ["练习"]
    plan_items = plan.get("plan_items", []) if isinstance(plan.get("plan_items", []), list) else []
    for idx, item in enumerate(plan_items[:3], start=1):
        practice_lines.append(f"D{idx}: {item.get('task', '')}")
    if not plan_items:
        practice_lines.append("今天先完成 3 道针对练习，并把错因写成一句话。")

    answer = "\n".join(analysis_lines + [""] + explain_lines + [""] + advice_lines + [""] + practice_lines)

    kb_tool_name = "tool_graph_rag_search" if route_type == "graph_rag" else "tool_search_learning_kb"
    steps_log = [
        {
            "tool_name": kb_tool_name,
            "tool_input": {"student_id": uid, "query": question_text},
            "tool_output_summary": f"命中 {len(hits)} 条资料，public_source={kb_result.get('public_source', 'unavailable')}",
            "latency_ms": max(1, int(kb_result.get("query_time_ms", 1) or 1)),
            "status": "success",
        },
        {
            "tool_name": "tool_get_student_mastery",
            "tool_input": {"student_id": uid, "topic": focus_topic},
            "tool_output_summary": (
                f"topic={mastery_info.get('concept') or focus_topic}, mastery={mastery_info.get('mastery')}"
            ),
            "latency_ms": 1,
            "status": "success",
        },
        {
            "tool_name": "tool_generate_learning_plan",
            "tool_input": {"student_id": uid, "topic": focus_topic},
            "tool_output_summary": f"已生成 {len(plan_items)} 条 3 天学习任务",
            "latency_ms": 1,
            "status": "success",
        },
    ]

    evidence = {
        "tool_calls": [step.get("tool_name") for step in steps_log],
        "trace_count": len(steps_log),
        "has_mastery": True,
        "has_graph": bool(graph_context),
        "has_kb": True,
        "offline_fallback_used": True,
    }

    return {
        "answer": answer,
        "steps_log": steps_log,
        "evidence": evidence,
        "plan_items": plan_items,
        "focus_topic": focus_topic,
        "kb_result": kb_result,
        "mastery_info": mastery_info,
    }
