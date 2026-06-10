import logging
import traceback
import json

from flask import Blueprint, jsonify, request, Response, stream_with_context

from ..services.agent_metrics import agent_metrics
from ..services.knowledge_base import ingest_kb_note, search_kb
from ..services.ocr_service import extract_text_from_image

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__)

tutor_agent = None


def get_tutor_agent():
    """延迟初始化，避免在 .env 尚未加载时读取到错误配置。"""
    global tutor_agent
    if tutor_agent is not None:
        return tutor_agent

    try:
        from ..services.agent_service import TutorAgentService

        tutor_agent = TutorAgentService()
        return tutor_agent
    except Exception as e:
        logger.error(f"Failed to load TutorAgentService: {e}")
        return None


def resolve_agent_identity(touch_session=True):
    from ..server import resolve_current_request_identity

    return resolve_current_request_identity(
        touch_session=touch_session,
        allow_guest=True,
    )


def build_agent_session_id(identity, raw_session_id=None):
    from ..server import build_scoped_agent_session_id

    return build_scoped_agent_session_id(identity, raw_session_id)


def resolve_agent_request_context(data=None):
    body = data if isinstance(data, dict) else {}
    identity, auth_error = resolve_agent_identity(touch_session=True)
    if auth_error:
        return None, auth_error

    student_id = str((identity or {}).get("user_id") or "").strip()
    session_id = build_agent_session_id(
        identity,
        body.get("session_id") or request.form.get("session_id"),
    )
    return {
        "identity": identity,
        "student_id": student_id,
        "session_id": session_id,
    }, None


@agent_bp.route('/api/agent/ocr-tutor', methods=['POST'])
def handle_ocr_tutor():
    """多模态教育辅导入口：优先接收图片，再回退 ocr_text。"""
    try:
        data = request.get_json(silent=True) or {}
        agent_context, auth_error = resolve_agent_request_context(data)
        if auth_error:
            return auth_error

        student_id = str((agent_context or {}).get("student_id") or "").strip()
        session_id = str((agent_context or {}).get("session_id") or "").strip()
        question = str(data.get("question") or request.form.get("question") or "").strip()

        # 1) 图片优先
        ocr_text = ""
        image_file = request.files.get("image")
        if image_file:
            ocr_result = extract_text_from_image(image_file)
            if not ocr_result.get("success"):
                # OCR 失败时优先降级到文本路径，避免直接中断用户问答。
                fallback_text = str(data.get("ocr_text") or request.form.get("ocr_text") or question or "").strip()
                if not fallback_text:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error_code": ocr_result.get("error_code", "OCR_UPSTREAM_ERROR"),
                                "error_message": ocr_result.get("error_message", "OCR识别失败"),
                                "provider": ocr_result.get("provider", "unknown"),
                            }
                        ),
                        502,
                    )
                ocr_text = fallback_text
            else:
                ocr_text = str(ocr_result.get("text", "") or "").strip()

        # 2) 纯文本回退
        if not ocr_text:
            ocr_text = str(data.get("ocr_text") or request.form.get("ocr_text") or "").strip()

        if not ocr_text:
            return jsonify({"success": False, "error": "Missing image or ocr_text"}), 400

        agent = get_tutor_agent()
        if agent is None:
            return jsonify({"success": False, "error": "Agent service is not initialized properly."}), 500


        is_stream = str(data.get('stream') or request.form.get('stream') or 'false').lower() == 'true'
        if is_stream:
            question_for_trace = question or ocr_text

            def stream_with_post_process():
                try:
                    from ..server import post_process_qa_interaction, extract_learning_advice_from_answer
                except Exception as exc:
                    logger.warning("agent stream post process import skipped: %s", exc)
                    for chunk in agent.stream_solve_problem(
                        session_id=session_id,
                        student_id=student_id,
                        ocr_text=ocr_text,
                        question_text=question,
                    ):
                        yield chunk
                    return

                for chunk in agent.stream_solve_problem(
                    session_id=session_id,
                    student_id=student_id,
                    ocr_text=ocr_text,
                    question_text=question,
                ):
                    chunk_text = str(chunk or "")
                    stripped = chunk_text.strip()
                    if not stripped.startswith("data:"):
                        yield chunk
                        continue

                    try:
                        payload_text = stripped.split("data:", 1)[1].strip()
                        event_obj = json.loads(payload_text)
                    except Exception:
                        yield chunk
                        continue

                    if not (isinstance(event_obj, dict) and event_obj.get("type") == "final"):
                        yield chunk
                        continue

                    payload = event_obj.get("payload") if isinstance(event_obj.get("payload"), dict) else {}
                    answer_text = str(payload.get("answer", "") or "")

                    post_process = {}
                    try:
                        post_process = post_process_qa_interaction(
                            user_id=student_id,
                            question=question_for_trace,
                            answer=answer_text,
                            source="agent_ocr_tutor_stream",
                            include_wrong_question=True,
                            suggested_advice_text=extract_learning_advice_from_answer(answer_text),
                        )
                    except Exception as exc:
                        logger.warning("agent stream post process skipped: %s", exc)

                    payload["knowledge_extract"] = (post_process or {}).get("knowledge_extract", {})
                    payload["diagnosis"] = (post_process or {}).get("diagnosis")
                    payload["learning_advice"] = (post_process or {}).get("learning_advice")
                    event_obj["payload"] = payload
                    yield f"data: {json.dumps(event_obj, ensure_ascii=False)}\n\n"

            return Response(
                stream_with_context(stream_with_post_process()),
                mimetype='text/event-stream',
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )

        result = agent.solve_problem(
            session_id=session_id,
            student_id=student_id,
            ocr_text=ocr_text,
            question_text=question,
        )

        # 复用主后端问答后处理，确保智能体模式也写入知识抽取与建议数据源。
        post_process = {}
        try:
            from ..server import post_process_qa_interaction, extract_learning_advice_from_answer

            question_for_trace = question or ocr_text
            post_process = post_process_qa_interaction(
                user_id=student_id,
                question=question_for_trace,
                answer=str((result or {}).get("answer", "") or ""),
                source="agent_ocr_tutor",
                include_wrong_question=True,
                suggested_advice_text=extract_learning_advice_from_answer(str((result or {}).get("answer", "") or "")),
            )
        except Exception as exc:
            logger.warning("agent post process skipped: %s", exc)


        return jsonify(
            {
                "success": True,
                "student_id": student_id,
                "session_id": session_id,
                "ocr_text": ocr_text,
                "knowledge_extract": (post_process or {}).get("knowledge_extract", {}),
                "diagnosis": (post_process or {}).get("diagnosis"),
                "learning_advice": (post_process or {}).get("learning_advice"),
                **result,
            }
        )
    except Exception as e:
        logger.error(f"Error in handle_ocr_tutor: {e}")
        return jsonify({"success": False, "error": str(e), "trace": traceback.format_exc()}), 500


@agent_bp.route('/api/agent/metrics', methods=['GET'])
def get_agent_metrics():
    return jsonify({"success": True, "metrics": agent_metrics.snapshot()})


@agent_bp.route('/api/agent/eval', methods=['POST'])
def run_agent_eval():
    """在线评测：输入样例列表并返回可复现指标。"""
    payload = request.get_json(silent=True) or {}
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or not cases:
        return jsonify({"success": False, "error": "cases must be a non-empty list"}), 400

    agent = get_tutor_agent()
    if agent is None:
        return jsonify({"success": False, "error": "Agent service is not initialized properly."}), 500

    results = []
    score_sum = 0.0

    for idx, case in enumerate(cases):
        student_id = str(case.get("student_id") or f"eval_user_{idx}")
        session_id = str(case.get("session_id") or f"eval_session_{idx}")
        ocr_text = str(case.get("ocr_text") or "").strip()
        question = str(case.get("question") or "").strip()
        expected_keywords = case.get("expected_keywords", [])

        if not ocr_text and not question:
            continue

        out = agent.solve_problem(
            session_id=session_id,
            student_id=student_id,
            ocr_text=ocr_text,
            question_text=question,
        )

        answer = str(out.get("answer", ""))
        hit = 0
        for kw in expected_keywords if isinstance(expected_keywords, list) else []:
            if str(kw) and str(kw) in answer:
                hit += 1
        kw_total = max(1, len(expected_keywords) if isinstance(expected_keywords, list) else 0)
        kw_score = hit / kw_total

        has_tool_trace = bool(out.get("steps_log"))
        case_score = 0.6 * kw_score + 0.4 * (1.0 if has_tool_trace else 0.0)
        score_sum += case_score

        results.append(
            {
                "id": case.get("id", idx),
                "score": round(case_score, 4),
                "keyword_score": round(kw_score, 4),
                "has_tool_trace": has_tool_trace,
                "trace_count": len(out.get("steps_log", [])),
            }
        )

    avg_score = score_sum / max(1, len(results))
    return jsonify(
        {
            "success": True,
            "summary": {
                "cases": len(results),
                "avg_score": round(avg_score, 4),
            },
            "results": results,
        }
    )


@agent_bp.route('/api/agent/eval-ab', methods=['POST'])
def run_agent_eval_ab():
    """A/B 评测：对比基础模式与强制知识库路由模式。"""
    payload = request.get_json(silent=True) or {}
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or not cases:
        return jsonify({"success": False, "error": "cases must be a non-empty list"}), 400

    agent = get_tutor_agent()
    if agent is None:
        return jsonify({"success": False, "error": "Agent service is not initialized properly."}), 500

    def keyword_score(answer, expected_keywords):
        text = str(answer or "")
        exp = expected_keywords if isinstance(expected_keywords, list) else []
        if not exp:
            return 1.0
        hit = 0
        for kw in exp:
            if str(kw) and str(kw) in text:
                hit += 1
        return hit / max(1, len(exp))

    rows = []
    base_score_total = 0.0
    routed_score_total = 0.0
    base_kb_hits = 0
    routed_kb_hits = 0

    for idx, case in enumerate(cases):
        student_id = str(case.get("student_id") or f"eval_ab_user_{idx}")
        ocr_text = str(case.get("ocr_text") or "").strip()
        question = str(case.get("question") or "").strip()
        expected_keywords = case.get("expected_keywords", [])
        if not ocr_text and not question:
            continue

        baseline = agent.solve_problem(
            session_id=str(case.get("session_id") or f"eval_ab_base_{idx}"),
            student_id=student_id,
            ocr_text=ocr_text,
            question_text=question,
            force_use_kb=False,
        )
        routed = agent.solve_problem(
            session_id=str(case.get("session_id") or f"eval_ab_route_{idx}") + "_r",
            student_id=student_id,
            ocr_text=ocr_text,
            question_text=question,
            force_use_kb=True,
        )

        base_kw = keyword_score(baseline.get("answer", ""), expected_keywords)
        routed_kw = keyword_score(routed.get("answer", ""), expected_keywords)
        base_has_kb = bool((baseline.get("evidence") or {}).get("has_kb"))
        routed_has_kb = bool((routed.get("evidence") or {}).get("has_kb"))
        base_kb_hits += 1 if base_has_kb else 0
        routed_kb_hits += 1 if routed_has_kb else 0

        base_score_total += base_kw
        routed_score_total += routed_kw

        rows.append(
            {
                "id": case.get("id", idx),
                "baseline": {
                    "keyword_score": round(base_kw, 4),
                    "has_kb": base_has_kb,
                    "trace_count": len(baseline.get("steps_log", [])),
                },
                "kb_routed": {
                    "keyword_score": round(routed_kw, 4),
                    "has_kb": routed_has_kb,
                    "trace_count": len(routed.get("steps_log", [])),
                },
            }
        )

    n = max(1, len(rows))
    avg_base = base_score_total / n
    avg_routed = routed_score_total / n
    return jsonify(
        {
            "success": True,
            "summary": {
                "cases": len(rows),
                "baseline_avg_keyword_score": round(avg_base, 4),
                "kb_routed_avg_keyword_score": round(avg_routed, 4),
                "keyword_score_delta": round(avg_routed - avg_base, 4),
                "baseline_kb_hit_rate": round(base_kb_hits / n, 4),
                "kb_routed_hit_rate": round(routed_kb_hits / n, 4),
            },
            "results": rows,
        }
    )


@agent_bp.route('/api/agent/kb/ingest', methods=['POST'])
def ingest_agent_kb_note():
    """知识库入库：将学习资料写入个人内容库，供 Agent 检索引用。"""
    data = request.get_json(silent=True) or {}
    identity, auth_error = resolve_agent_identity(touch_session=True)
    if auth_error:
        return auth_error

    student_id = str((identity or {}).get("user_id") or "").strip()
    title = str(data.get("title") or "知识笔记").strip()
    content = str(data.get("content") or "").strip()
    source = str(data.get("source") or "agent_kb").strip()
    tags = data.get("tags", [])

    if not content:
        return jsonify({"success": False, "error_code": "INVALID_INPUT", "error_message": "content 不能为空"}), 400

    try:
        item = ingest_kb_note(
            user_id=student_id,
            title=title,
            content=content,
            source=source,
            tags=tags if isinstance(tags, list) else [],
        )
        return jsonify(
            {
                "success": True,
                "student_id": student_id,
                "item": item,
                "graph_sync": (item.get("graph_sync", {}) if isinstance(item, dict) else {}),
            }
        )
    except Exception as e:
        logger.error("ingest_agent_kb_note error: %s", e)
        return jsonify({"success": False, "error_code": "KB_INGEST_ERROR", "error_message": str(e)}), 500


@agent_bp.route('/api/agent/kb/search', methods=['POST'])
def search_agent_kb():
    """知识库检索：按查询词返回个人学习资料中的证据片段。"""
    data = request.get_json(silent=True) or {}
    identity, auth_error = resolve_agent_identity(touch_session=True)
    if auth_error:
        return auth_error

    student_id = str((identity or {}).get("user_id") or "").strip()
    query = str(data.get("query") or "").strip()
    top_k = int(data.get("top_k") or 3)
    search_mode = str(data.get("search_mode") or "hybrid").strip().lower()

    if not query:
        return jsonify({"success": False, "error_code": "INVALID_INPUT", "error_message": "query 不能为空"}), 400

    try:
        result = search_kb(student_id, query, top_k=top_k, search_mode=search_mode)
        return jsonify({"success": True, "student_id": student_id, **result})
    except Exception as e:
        logger.error("search_agent_kb error: %s", e)
        return jsonify({"success": False, "error_code": "KB_SEARCH_ERROR", "error_message": str(e)}), 500

@agent_bp.route('/api/agent/learning-feedback', methods=['POST'])
def handle_learning_feedback():
    """学习反馈接口（P2 改造新增）：记录任务完成度、正确率、耗时，并回写掌握度。"""
    try:
        from uuid import uuid4
        from datetime import datetime
        from ..services.database import append_user_event, get_user_knowledge
        from ..services.learning_feedback import build_feedback_mastery_assessment
        from ..server import (
            build_evaluation_fact_source,
            load_user_event_list,
            normalize_concept_name,
            normalize_user_knowledge,
            refresh_learning_runtime_cache,
            update_concept_mastery_snapshot,
        )

        data = request.get_json(silent=True) or {}
        identity, auth_error = resolve_agent_identity(touch_session=True)
        if auth_error:
            return auth_error

        student_id = str((identity or {}).get("user_id") or "").strip()
        task_id = str(data.get("task_id") or "").strip()
        task_type = str(data.get("task_type") or "unknown").strip()  # 类型：quiz/practice/review
        total_count = max(1, int(data.get("total_count") or 1))
        correct_count = max(0, min(total_count, int(data.get("correct_count") or 0)))
        duration_seconds = max(0, int(data.get("duration_seconds") or 0))
        concept = normalize_concept_name(data.get("concept") or "")

        if not concept:
            return jsonify({"success": False, "error_code": "INVALID_INPUT", "error_message": "concept 不能为空"}), 400

        accuracy = round(correct_count / max(1, total_count), 3)
        now_iso = datetime.now().isoformat()
        feedback_id = str(uuid4())
        fact_source = build_evaluation_fact_source(
            primary_source="learning_feedback",
            fact_id=feedback_id,
            task_id=task_id,
            concept=concept,
            timestamp=now_iso,
        )

        feedback_record = {
            "id": feedback_id,
            "task_id": task_id,
            "task_type": task_type,
            "concept": concept,
            "accuracy": accuracy,
            "correct_count": correct_count,
            "total_count": total_count,
            "duration_seconds": duration_seconds,
            "timestamp": now_iso,
            "fact_source": fact_source,
        }
        append_user_event(student_id, "feedback", feedback_record)

        user_knowledge = normalize_user_knowledge(get_user_knowledge(student_id))
        concept_snapshot = next(
            (
                item for item in user_knowledge.get("concepts", [])
                if isinstance(item, dict) and str(item.get("concept") or "").strip() == concept
            ),
            None,
        )
        feedback_history = [
            item
            for item in load_user_event_list(student_id, "feedback")
            if isinstance(item, dict) and normalize_concept_name(item.get("concept") or "") == concept
        ]
        mastery_assessment = build_feedback_mastery_assessment(
            concept=concept,
            feedback_history=feedback_history,
            existing_snapshot=concept_snapshot,
            now=now_iso,
        )
        mastery_snapshot = update_concept_mastery_snapshot(
            user_id=student_id,
            concept=concept,
            mastery_assessment=mastery_assessment,
            answered_at=now_iso,
        )
        runtime_refresh = refresh_learning_runtime_cache(
            user_id=student_id,
            reason="learning_feedback",
            focus_concept=concept,
            recommendation_limit=4,
            context={
                "source": "learning_feedback",
                "task_id": task_id,
                "task_type": task_type,
                "concept": concept,
                "accuracy": accuracy,
                "correct_count": correct_count,
                "total_count": total_count,
                "duration_seconds": duration_seconds,
                "fact_source": fact_source,
            },
        )

        return jsonify({
            "success": True,
            "student_id": student_id,
            "feedback_recorded": True,
            "task_type": task_type,
            "accuracy": accuracy,
            "concept": concept,
            "mastery_updated": bool(mastery_snapshot),
            "mastery_assessment": mastery_assessment,
            "mastery_snapshot": mastery_snapshot,
            "graph_sync": (mastery_snapshot.get("graph_sync", {}) if isinstance(mastery_snapshot, dict) else {}),
            "fact_source": fact_source,
            "recommendation_cache_refreshed": True,
            "profile": (runtime_refresh.get("profile", {}) if isinstance(runtime_refresh, dict) else {}),
            "recommendations": (runtime_refresh.get("recommendations", []) if isinstance(runtime_refresh, dict) else []),
            "review_reminders": (runtime_refresh.get("review_reminders", {}) if isinstance(runtime_refresh, dict) else {}),
        })
    except Exception as e:
        logger.error("handle_learning_feedback error: %s", e)
        return jsonify({"success": False, "error_code": "FEEDBACK_ERROR", "error_message": str(e)}), 500
