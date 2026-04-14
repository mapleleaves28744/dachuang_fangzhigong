import json
import re
import time
import uuid
from datetime import datetime, timedelta

from langchain_core.tools import tool

from .cognitive_diagnosis import CognitiveDiagnosis
from .database import append_user_event, get_user_knowledge, get_user_plans, get_user_profile, set_user_plans
from .knowledge_base import search_kb
from .neo4j_store import Neo4jGraphStore


diagnosis_engine = CognitiveDiagnosis()
_neo4j_store = None

_CACHE_TTL_SECONDS = 90
_CACHE = {}


def _cache_get(cache_key):
    item = _CACHE.get(cache_key)
    if not item:
        return None
    if time.time() > item["expires_at"]:
        _CACHE.pop(cache_key, None)
        return None
    return item["value"]


def _cache_set(cache_key, value, ttl=_CACHE_TTL_SECONDS):
    _CACHE[cache_key] = {
        "expires_at": time.time() + max(1, int(ttl or _CACHE_TTL_SECONDS)),
        "value": value,
    }
    return value


def _get_neo4j_store():
    global _neo4j_store
    if _neo4j_store is None:
        _neo4j_store = Neo4jGraphStore()
    return _neo4j_store


def _extract_mastery_from_knowledge(knowledge, topic):
    topic = str(topic or "").strip()
    if not topic:
        return None

    concepts = (knowledge or {}).get("concepts", [])
    for item in concepts:
        concept = str(item.get("concept", "")).strip()
        if concept == topic:
            try:
                return float(item.get("mastery", 0.0) or 0.0)
            except Exception:
                return 0.0

    for item in concepts:
        concept = str(item.get("concept", "")).strip()
        if topic in concept or concept in topic:
            try:
                return float(item.get("mastery", 0.0) or 0.0)
            except Exception:
                return 0.0

    return None


def _normalize_topic_text(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    # Remove common descriptive suffixes to improve matching recall.
    raw = re.sub(r"(基础概念|基础知识|入门|知识点|专题|模块|部分)$", "", raw)
    return re.sub(r"\s+", "", raw)


def _split_composite_topic(topic):
    text = _normalize_topic_text(topic)
    if not text:
        return []
    # Keep ascii words and CJK tokens split by common connectors.
    tokens = re.split(r"(?:与|和|及|、|/|\\|\||,|，|\+|及其|以及)", text)
    cleaned = []
    for tok in tokens:
        tok = str(tok or "").strip()
        if not tok:
            continue
        tok = re.sub(r"^(关于|有关)", "", tok)
        tok = re.sub(r"(的基础|基础)$", "", tok)
        if tok and tok not in cleaned:
            cleaned.append(tok)
    if text not in cleaned:
        cleaned.insert(0, text)
    return cleaned


def _extract_mastery_detail_from_knowledge(knowledge, topic):
    concepts = (knowledge or {}).get("concepts", [])
    if not isinstance(concepts, list):
        return {"mastery": None, "matched": []}

    topic_norm = _normalize_topic_text(topic)
    if not topic_norm:
        return {"mastery": None, "matched": []}

    # 1) Exact / contains matching first.
    for item in concepts:
        concept = str((item or {}).get("concept", "")).strip()
        concept_norm = _normalize_topic_text(concept)
        if not concept_norm:
            continue
        if concept_norm == topic_norm:
            try:
                mastery = float(item.get("mastery", 0.0) or 0.0)
            except Exception:
                mastery = 0.0
            return {"mastery": mastery, "matched": [concept]}

    # 2) Composite-topic fallback: aggregate multiple concept mastery.
    tokens = _split_composite_topic(topic)
    if len(tokens) <= 1:
        tokens = []
    token_matches = []
    for token in tokens:
        for item in concepts:
            concept = str((item or {}).get("concept", "")).strip()
            concept_norm = _normalize_topic_text(concept)
            if not concept_norm:
                continue
            if concept_norm == token or token in concept_norm or concept_norm in token:
                try:
                    token_matches.append((concept, float(item.get("mastery", 0.0) or 0.0)))
                except Exception:
                    token_matches.append((concept, 0.0))

    if token_matches:
        seen = set()
        deduped = []
        for concept, mastery in token_matches:
            if concept in seen:
                continue
            seen.add(concept)
            deduped.append((concept, mastery))
        mastery = sum(x[1] for x in deduped) / max(1, len(deduped))
        return {"mastery": mastery, "matched": [x[0] for x in deduped[:4]]}

    # 3) Generic contains fallback for single-topic fuzzy matching.
    contains_matches = []
    for item in concepts:
        concept = str((item or {}).get("concept", "")).strip()
        concept_norm = _normalize_topic_text(concept)
        if not concept_norm:
            continue
        if topic_norm in concept_norm or concept_norm in topic_norm:
            try:
                contains_matches.append((concept, float(item.get("mastery", 0.0) or 0.0)))
            except Exception:
                contains_matches.append((concept, 0.0))

    if contains_matches:
        contains_matches.sort(key=lambda x: len(_normalize_topic_text(x[0])), reverse=True)
        concept, mastery = contains_matches[0]
        return {"mastery": mastery, "matched": [concept]}

    return {"mastery": None, "matched": []}


def _find_weakest_topic(knowledge):
    concepts = (knowledge or {}).get("concepts", [])
    if not isinstance(concepts, list):
        return ""

    weakest_topic = ""
    weakest_mastery = 10.0
    for item in concepts:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept", "")).strip()
        if not concept:
            continue
        try:
            mastery = float(item.get("mastery", 0.0) or 0.0)
        except Exception:
            mastery = 0.0
        if mastery < weakest_mastery:
            weakest_mastery = mastery
            weakest_topic = concept
    return weakest_topic


def _normalize_learning_style(profile):
    style = str((profile or {}).get("learning_style") or "").strip().lower()
    if style in {"visual", "auditory", "kinesthetic"}:
        return style
    return "visual"


def _build_plan_variant(style, mastery, day_index, base_topic):
    weak = mastery < 0.4
    mid = mastery < 0.7
    if weak:
        templates = [
            f"重建 {base_topic} 的基础定义与关键词",
            f"用 1 道例题拆解 {base_topic} 的关键步骤",
            f"完成 {base_topic} 同类题 5 题并复盘错因",
        ]
    elif mid:
        templates = [
            f"回顾 {base_topic} 的易错点并做针对性修正",
            f"完成 {base_topic} 变式训练 4 题",
            f"限时整理 {base_topic} 的解题模板与检查清单",
        ]
    else:
        templates = [
            f"尝试 {base_topic} 的综合应用题并总结方法",
            f"用讲解方式复述 {base_topic} 的核心逻辑",
            f"做一套 {base_topic} 提升题并整理拓展点",
        ]

    style_suffix = {
        "visual": "配思维导图和图例",
        "auditory": "先口述再整理成笔记",
        "kinesthetic": "边做边写步骤",
    }.get(style, "结合图文复盘")

    chosen = templates[min(day_index, len(templates) - 1)]
    if day_index == 0:
        return f"{chosen}，{style_suffix}"
    if day_index == 1:
        return f"{chosen}，用 15 分钟口头/书面复述关键步骤"
    return f"{chosen}，最后用 1 次自测检验掌握情况"


def _build_learning_plan_payload(student_id, topic):
    sid = str(student_id or "").strip() or "default_user"
    profile = get_user_profile(sid) or {}
    knowledge = get_user_knowledge(sid) or {}
    style = _normalize_learning_style(profile)
    best_time_range = str(profile.get("best_time_range") or "").strip() or "今晚"
    focus_minutes = max(20, min(60, int(profile.get("focus_minutes", 40) or 40)))

    base_topic = str(topic or "").strip()
    if not base_topic:
        base_topic = _find_weakest_topic(knowledge) or "核心知识点"

    mastery = _extract_mastery_from_knowledge(knowledge, base_topic)
    if mastery is None:
        mastery = 0.5

    today = datetime.now()
    plan_items = []
    for idx in range(3):
        day = (today + timedelta(days=idx)).strftime("%Y-%m-%d")
        task = _build_plan_variant(style, mastery, idx, base_topic)
        if idx == 0:
            phase = "夯实基础"
        elif idx == 1:
            phase = "强化训练"
        else:
            phase = "验收复盘"

        plan_items.append({
            "id": str(uuid.uuid4()),
            "time": day,
            "task": f"D{idx + 1}({day})：{phase} - {task}",
            "completed": False,
            "topic": base_topic,
            "mastery": round(float(mastery), 3),
            "style": style,
            "focus_minutes": focus_minutes,
            "source": "agent_learning_plan",
            "generated_at": today.isoformat(),
            "priority": max(1, 5 - idx),
        })

    return {
        "student_id": sid,
        "topic": base_topic,
        "style": style,
        "best_time_range": best_time_range,
        "focus_minutes": focus_minutes,
        "mastery": mastery,
        "plan_items": plan_items,
    }


def _mastery_level(score):
    if score is None:
        return "未知"
    if score < 0.4:
        return "偏弱"
    if score < 0.7:
        return "一般"
    return "较好"


@tool
def tool_get_student_mastery(student_id: str, topic: str) -> str:
    """当需要知道学生对某个具体知识点掌握程度时调用此工具。"""
    sid = str(student_id or "").strip() or "default_user"
    tp = str(topic or "").strip()
    cache_key = ("mastery", sid, tp)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        user_knowledge = get_user_knowledge(sid) or {}
        detail = _extract_mastery_detail_from_knowledge(user_knowledge, tp)
        mastery = detail.get("mastery")
        if mastery is None:
            result = f"【学生掌握度】未查到学生 {sid} 在知识点“{tp}”的数据。"
            return _cache_set(cache_key, result)

        matched = detail.get("matched", []) if isinstance(detail, dict) else []
        matched_text = f"（匹配依据：{'、'.join(matched)}）" if matched else ""

        result = (
            f"【学生掌握度】学生 {sid} 在“{tp}”上的掌握度为 {mastery:.2f}，"
            f"水平判定：{_mastery_level(mastery)}。{matched_text}"
        )
        return _cache_set(cache_key, result)
    except Exception as exc:
        return f"查询掌握度异常: {exc}"


@tool
def tool_query_knowledge_graph(concept: str) -> str:
    """当需要查询某个知识点的前置依赖、后继知识点或相关概念时调用此工具。"""
    cp = str(concept or "").strip()
    cache_key = ("graph", cp)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        relations = _get_neo4j_store().query_related_concepts(cp, limit=24)
        if not relations:
            result = f"【知识图谱】知识点“{cp}”暂无可用关联数据。"
            return _cache_set(cache_key, result)

        uniq = []
        seen = set()
        for it in relations:
            source = str((it or {}).get("source") or "").strip()
            target = str((it or {}).get("target") or "").strip()
            relation = str((it or {}).get("relation") or "相关").strip() or "相关"
            if not source or not target:
                continue
            key = (source, target, relation)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(key)
            if len(uniq) >= 8:
                break

        if not uniq:
            result = f"【知识图谱】知识点“{cp}”暂无可用关联数据。"
            return _cache_set(cache_key, result)

        items = [f"{src} -> {dst}（{rel}）" for src, dst, rel in uniq]
        result = "【知识图谱】关联结果：\n" + "\n".join(items)
        return _cache_set(cache_key, result)
    except Exception as exc:
        return f"查询知识图谱异常: {exc}"


@tool
def tool_generate_learning_plan(student_id: str, topic: str = "") -> str:
    """当需要给学生生成可执行的 3 天或 7 天学习计划时调用此工具。"""
    try:
        plan = _build_learning_plan_payload(student_id, topic)
        sid = plan["student_id"]
        base_topic = plan["topic"]
        plan_items = plan["plan_items"]

        existing_plans = get_user_plans(sid) or []
        retained_plans = [
            item for item in existing_plans
            if not (
                isinstance(item, dict)
                and str(item.get("source") or "").strip() == "agent_learning_plan"
                and str(item.get("topic") or "").strip() == base_topic
            )
        ]
        merged_plans = retained_plans + plan_items
        merged_plans.sort(key=lambda item: (str(item.get("time") or ""), str(item.get("id") or "")))
        set_user_plans(sid, merged_plans)

        append_user_event(sid, "learning_plan", {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "student_id": sid,
            "topic": base_topic,
            "style": plan["style"],
            "mastery": round(float(plan["mastery"]), 3),
            "best_time_range": plan["best_time_range"],
            "focus_minutes": plan["focus_minutes"],
            "plan_items": plan_items,
            "source": "agent",
        })

        style_label = {
            "visual": "视觉型",
            "auditory": "听觉型",
            "kinesthetic": "动觉型",
        }.get(plan["style"], "视觉型")
        plan_lines = []
        for item in plan_items:
            plan_lines.append(f"{item['task']}（{item['time']}，每次约 {item['focus_minutes']} 分钟）")
        result = (
            f"【学习计划】已生成并录入：{base_topic}（{style_label}，当前掌握度 {round(float(plan['mastery']) * 100)}%）\n"
            + "\n".join(plan_lines)
        )
        return result
    except Exception as exc:
        return f"生成学习计划异常: {exc}"


@tool
def tool_diagnose_mistake(question: str, student_answer: str, correct_answer: str, topic: str = "", student_id: str = "") -> str:
    """当需要对学生错题进行归因（知识性/步骤性/习惯性）并给出建议时调用此工具。"""
    q = str(question or "").strip()
    ua = str(student_answer or "").strip()
    ca = str(correct_answer or "").strip()
    tp = str(topic or "").strip()
    sid = str(student_id or "").strip() or "default_user"

    try:
        result = diagnosis_engine.analyze_error(
            question=q,
            answer=ca,
            user_answer=ua,
            concept=tp,
            concept_mastery=None,
        )
        diagnosis_record = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "question": q[:300],
            "correct_answer": ca[:200],
            "user_answer": ua[:200],
            "concept": tp,
            "diagnosis": result,
            "learning_advice": {
                "建议": result.get("recommendation", "请回顾核心定义并完成针对练习"),
            },
            "mastery_assessment": {
                "知识点": tp,
                "掌握度": float(result.get("mastery", 0.0) or 0.0) if isinstance(result, dict) else 0.0,
            },
            "source": "agent_tool",
        }
        append_user_event(sid, "diagnosis", diagnosis_record)
        return (
            "【错题归因】"
            f"类型={result.get('error_type', '未知')}，"
            f"严重度={result.get('severity', 'medium')}，"
            f"建议={result.get('recommendation', '请回顾核心定义并完成针对练习')}"
        )
    except Exception as exc:
        return f"错题归因异常: {exc}"


@tool
def tool_search_learning_kb(student_id: str, query: str, top_k: int = 3) -> str:
    """当需要从学生个人学习资料中检索可引用证据时调用此工具。"""
    sid = str(student_id or "").strip() or "default_user"
    q = str(query or "").strip()
    cache_key = ("kb", sid, q, int(top_k or 3))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not q:
        return "【知识库检索】query 不能为空。"

    try:
        result = search_kb(sid, q, top_k=top_k)
        hits = result.get("hits", []) if isinstance(result, dict) else []
        retrieval_mode = (result.get("retrieval_mode") if isinstance(result, dict) else "") or "lexical"
        public_docs = int(result.get("public_docs", 0) or 0) if isinstance(result, dict) else 0
        graph_rate = float(result.get("graph_contribution_rate", 0.0) or 0.0) if isinstance(result, dict) else 0.0
        if not hits:
            return _cache_set(cache_key, f"【知识库检索】未命中。当前知识库文档数={result.get('total_docs', 0)}。")

        lines = [
            (
                f"【知识库检索】命中 {len(hits)} 条（私有文档={result.get('total_docs', 0)}，"
                f"公共向量文档={public_docs}，模式={retrieval_mode}，图增强贡献={graph_rate:.3f}）："
            )
        ]
        for idx, row in enumerate(hits, start=1):
            chapter = str(row.get("chapter", "") or "").strip()
            channel = str(row.get("channel", "") or "unknown").strip()
            chapter_part = f" | chapter={chapter}" if chapter else ""
            lines.append(
                f"{idx}. {row.get('title', '未命名')} | score={row.get('hybrid_score', row.get('score', 0)):.3f} | "
                f"channel={channel} | source={row.get('source', 'unknown')}{chapter_part} | snippet={row.get('snippet', '')}"
            )

        # 教育赛道增强：自动给出“先学什么”的助学提示。
        first_hit = hits[0] if hits else {}
        first_topic = str(first_hit.get("title") or first_hit.get("knowledge_point") or "当前主题").strip()
        lines.append(f"【学习支持建议】优先复习：{first_topic}；先看定义与公式，再做1道同题型练习并口述步骤。")
        return _cache_set(cache_key, "\n".join(lines))
    except Exception as exc:
        return f"知识库检索异常: {exc}"



@tool
def tool_graph_rag_search(student_id: str, query: str, top_k: int = 3) -> str:
    """综合了文本检索和知识图谱节点的增强版检索。返回知识点内容及相关的图谱关联路径。"""
    sid = str(student_id or "").strip() or "default_user"
    q = str(query or "").strip()
    if not q:
        return "【RAG-Graph检索】query 不能为空。"

    kb_result = search_kb(sid, q, top_k=top_k)
    text_hits = kb_result.get("hits", []) if isinstance(kb_result, dict) else []
    graph_ctx = list(kb_result.get("graph_context", [])) if isinstance(kb_result, dict) else []
    retrieval_mode = (kb_result.get("retrieval_mode") if isinstance(kb_result, dict) else "") or "lexical"
    public_docs = int(kb_result.get("public_docs", 0) or 0) if isinstance(kb_result, dict) else 0
    graph_rate = float(kb_result.get("graph_contribution_rate", 0.0) or 0.0) if isinstance(kb_result, dict) else 0.0
    graph_concepts = kb_result.get("graph_query_concepts", []) if isinstance(kb_result, dict) else []

    res = []
    res.append(
        (
            f"【文档检索结果】命中 {len(text_hits)} 条（私有文档={kb_result.get('total_docs', 0) if isinstance(kb_result, dict) else 0}，"
            f"公共向量文档={public_docs}，模式={retrieval_mode}，图增强贡献={graph_rate:.3f}）"
        )
    )
    if graph_concepts:
        res.append(f"【图谱概念路由】{', '.join(graph_concepts[:6])}")
    for h in text_hits:
        chapter = str(h.get("chapter", "") or "").strip()
        channel = str(h.get("channel", "") or "unknown").strip()
        chapter_part = f" | chapter={chapter}" if chapter else ""
        concept_part = ""
        matched_concepts = h.get("matched_concepts", []) if isinstance(h.get("matched_concepts", []), list) else []
        if matched_concepts:
            concept_part = f" | concepts={','.join(matched_concepts[:4])}"
        res.append(
            f"- 标题: {h.get('title', '未知')} | score={h.get('hybrid_score', h.get('score', 0)):.3f} | "
            f"channel={channel} | source={h.get('source', 'unknown')}{chapter_part}{concept_part}"
            f"\n  摘要: {h.get('snippet', '')}"
        )
    
    if graph_ctx:
        res.append("【相关图谱知识路径】")
        for idx, item in enumerate(graph_ctx[: max(3, int(top_k or 3) * 2)], start=1):
            concept = str(item.get("concept") or "未知概念").strip()
            title = str(item.get("doc_title") or "未关联文档").strip()
            similarity = float(item.get("similarity_to_query", 0.0) or 0.0)
            relations = item.get("relations", []) if isinstance(item.get("relations", []), list) else []
            relation_summary = "；".join(
                f"{rel.get('relation', '相关')}->{rel.get('neighbor', '')}"
                for rel in relations[:4]
                if isinstance(rel, dict) and str(rel.get("neighbor") or "").strip()
            ) or "暂无概念关系"
            res.append(
                f"{idx}. 概念={concept} | 文档={title} | graph_score={similarity:.3f} | 关系={relation_summary}"
            )
    else:
        res.append("【相关图谱知识路径】暂无可用图谱关系，已回退为文本检索结果。")

    # 教育助学增强：给出分层学习路径提示。
    if text_hits:
        topic = str(text_hits[0].get("title") or text_hits[0].get("knowledge_point") or "当前主题").strip()
    else:
        topic = q or "当前主题"
    res.append(f"【学习路径建议】{topic}：先概念定义 -> 再公式推导 -> 再题型训练 -> 最后错因复盘。")
    res.append("【答题规范】请先写条件与公式来源，再给步骤结论，避免直接跳结论。")
    
    return "\n".join(res)

agent_tools = [
    tool_graph_rag_search,
    tool_get_student_mastery,
    tool_query_knowledge_graph,
    tool_search_learning_kb,
    tool_generate_learning_plan,
    tool_diagnose_mistake,
]
