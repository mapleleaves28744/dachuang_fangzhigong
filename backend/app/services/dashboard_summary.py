from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .topic_guard import filter_learning_topics, is_learning_topic


STYLE_LABELS = {
    "visual": "视觉型学习者",
    "auditory": "听觉型学习者",
    "kinesthetic": "动觉型学习者",
}

METHOD_LABELS = {
    "kmeans": "KMeans聚类",
    "rule": "规则推断",
    "rule_fallback": "规则回退",
}

CATEGORY_LABELS = {
    "knowledge": "知识性错误",
    "skill": "技能性错误",
    "habit": "习惯性错误",
    "unknown": "未分类错误",
}

PAGE_LABELS = {
    "index": "内容录入页",
    "chat": "智能问答页",
    "question-bank": "题库练习页",
    "knowledge-map": "知识图谱页",
    "dashboard": "学习仪表盘",
    "spaces": "我的空间",
}

WEEKDAY_LABELS_CN = ["一", "二", "三", "四", "五", "六", "日"]
DEFAULT_STREAK_START_GOAL_DAYS = 2
LOGIN_STREAK_BEHAVIOR_TYPES = {"auth_login", "auth_register", "auth_session_active"}

CONTENT_TYPE_LABELS = {
    "image": "截图识别",
    "link": "链接内容",
    "qa": "习题作答",
    "note": "学习笔记",
    "other": "其他内容",
}

RESOURCE_BY_CATEGORY = {
    "knowledge": "概念图谱 + 定义回顾微课",
    "skill": "步骤拆解练习 + 例题序列",
    "habit": "检查清单 + 规范化训练",
    "unknown": "同类题复练 + 元认知提示",
}


def parse_datetime_safe(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = text.replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def short_text(value, limit):
    text = str(value or "").strip()
    if len(text) <= int(limit):
        return text
    return f"{text[:int(limit)]}..."


def normalize_topic(value):
    return str(value or "").strip()


def normalize_blocked_topics(blocked_topics):
    return {
        normalize_topic(item)
        for item in (blocked_topics if isinstance(blocked_topics, (list, tuple, set)) else [])
        if normalize_topic(item)
    }


def normalize_page_id(value):
    text = str(value or "").strip().lower()
    if text.endswith(".html"):
        text = text[:-5]
    return text


def page_label(value):
    page_id = normalize_page_id(value)
    return PAGE_LABELS.get(page_id, page_id or "未知页面")


def content_type_label(value):
    return CONTENT_TYPE_LABELS.get(str(value or "").strip().lower(), "其他内容")


def link_kind(item):
    title = str((item or {}).get("title") or "")
    content = str((item or {}).get("content") or "")
    source = str((item or {}).get("source") or "")
    merged = f"{title} {content} {source}".lower()
    video_hints = ["视频", "bilibili", "lecture", "video", "播放", "课程", "课堂", "youtube", "youtu.be"]
    return "video" if any(token in merged for token in video_hints) else "reading"


def hour_window_label(hour):
    start = max(0, int(hour))
    end = (start + 2) % 24
    return f"{start:02d}:00-{end:02d}:00"


def compute_current_streak(active_dates, today):
    if not active_dates:
        return 0

    date_set = set()
    for item in active_dates:
        text = str(item or "").strip()
        if text:
            date_set.add(text)

    if not date_set:
        return 0

    streak = 0
    cursor = today
    while cursor.isoformat() in date_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def mark_active_date(active_dates, value):
    dt = parse_datetime_safe(value)
    if not dt:
        return None
    active_dates.add(dt.date().isoformat())
    return dt


def is_login_streak_behavior(item):
    if not isinstance(item, dict):
        return False

    behavior_type = str(item.get("behavior_type") or item.get("type") or "").strip().lower()
    source = str(item.get("source") or "").strip().lower()
    return behavior_type in LOGIN_STREAK_BEHAVIOR_TYPES or source in LOGIN_STREAK_BEHAVIOR_TYPES


def collect_streak_active_dates(behavior_logs):
    active_days = set()
    for item in (behavior_logs if isinstance(behavior_logs, list) else []):
        if not is_login_streak_behavior(item):
            continue
        mark_active_date(active_days, item.get("timestamp") or item.get("updated_at") or item.get("created_at"))
    return active_days


def build_streak_widget_summary(
    content_logs,
    qa_logs,
    behavior_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    now=None,
    week_goal_days=DEFAULT_STREAK_START_GOAL_DAYS,
):
    current_time = parse_datetime_safe(now) or datetime.now()
    today = current_time.date()
    goal = max(1, int(week_goal_days or DEFAULT_STREAK_START_GOAL_DAYS))
    active_days = collect_streak_active_dates(behavior_logs=behavior_logs)

    week_start = today - timedelta(days=today.weekday())
    week_days = []
    week_active_days = 0
    for offset, label in enumerate(WEEKDAY_LABELS_CN):
        day = week_start + timedelta(days=offset)
        iso_day = day.isoformat()
        is_active = iso_day in active_days
        if is_active:
            week_active_days += 1
        week_days.append({
            "date": iso_day,
            "label": label,
            "active": is_active,
            "today": day == today,
        })

    current_streak = compute_current_streak(active_days, today)
    progress_current = min(week_active_days, goal)
    progress_label = f"{progress_current}/{goal}"

    if progress_current >= goal:
        status = "started"
        message = "连续登录已开始，继续保持这个节奏。"
        if current_streak > 0:
            helper = f"已连续登录 {current_streak} 天"
        else:
            helper = f"本周已登录 {week_active_days} 天"
    else:
        status = "warming"
        message = f"本周登录 {goal} 天以开始你的连续登录。"
        helper = f"还差 {max(0, goal - week_active_days)} 天即可点亮连续登录"

    return {
        "week_label": "本周",
        "week_goal_days": goal,
        "week_active_days": week_active_days,
        "progress_current": progress_current,
        "progress_label": progress_label,
        "current_streak": current_streak,
        "status": status,
        "message": message,
        "helper": helper,
        "week_days": week_days,
        "last_active_date": max(active_days) if active_days else "",
    }


def to_percent(value, total):
    if total <= 0:
        return 0
    return round(float(value) * 100.0 / float(total), 1)


def unique_preserve(seq, limit=None):
    seen = set()
    items = []
    for item in seq:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(key)
        if limit and len(items) >= int(limit):
            break
    return items


def collect_space_items(space_payload):
    spaces = [
        space for space in (space_payload.get("spaces", []) if isinstance(space_payload.get("spaces"), list) else [])
        if isinstance(space, dict)
    ]
    items = []
    for space in spaces:
        for item in (space.get("items", []) if isinstance(space.get("items"), list) else []):
            if isinstance(item, dict):
                items.append(item)
    return spaces, items


def has_learning_evidence(
    content_logs,
    qa_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    wrong_question_logs=None,
    space_payload=None,
):
    _, space_items = collect_space_items(space_payload if isinstance(space_payload, dict) else {"spaces": []})
    return any([
        bool(content_logs),
        bool(qa_logs),
        bool(question_draw_logs),
        bool(question_answer_logs),
        bool(diagnosis_logs),
        bool(wrong_question_logs),
        bool(space_items),
    ])


def build_data_pool_summary(
    content_logs,
    qa_logs,
    behavior_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    wrong_question_logs=None,
    space_payload=None,
    hidden_metrics=None,
    now=None,
    blocked_topics=None,
):
    content_logs = content_logs if isinstance(content_logs, list) else []
    qa_logs = qa_logs if isinstance(qa_logs, list) else []
    behavior_logs = behavior_logs if isinstance(behavior_logs, list) else []
    question_draw_logs = question_draw_logs if isinstance(question_draw_logs, list) else []
    question_answer_logs = question_answer_logs if isinstance(question_answer_logs, list) else []
    diagnosis_logs = diagnosis_logs if isinstance(diagnosis_logs, list) else []
    wrong_question_logs = wrong_question_logs if isinstance(wrong_question_logs, list) else []
    space_payload = space_payload if isinstance(space_payload, dict) else {"spaces": []}
    hidden_metrics = hidden_metrics if isinstance(hidden_metrics, dict) else {}
    current_time = parse_datetime_safe(now) or datetime.now()
    blocked_set = normalize_blocked_topics(blocked_topics)
    learning_evidence_exists = has_learning_evidence(
        content_logs=content_logs,
        qa_logs=qa_logs,
        question_draw_logs=question_draw_logs,
        question_answer_logs=question_answer_logs,
        diagnosis_logs=diagnosis_logs,
        wrong_question_logs=wrong_question_logs,
        space_payload=space_payload,
    )
    summary_behavior_logs = behavior_logs if learning_evidence_exists else []

    total_records = (
        len(content_logs)
        + len(qa_logs)
        + len(question_draw_logs)
        + len(question_answer_logs)
        + len(diagnosis_logs)
    )

    topic_counter = Counter()
    content_counter = Counter()
    interaction_counter = Counter()
    window_counter = Counter()
    page_duration_seconds = defaultdict(float)
    exploration_counter = Counter()
    recent_feed = []
    active_days = set()
    today_label = current_time.date().isoformat()
    today_stay_seconds = 0.0
    today_content_counter = Counter()
    today_question_draw_count = 0
    today_question_answer_count = 0
    today_qa_count = 0
    today_diagnosis_count = 0
    if learning_evidence_exists:
        active_days.add(today_label)

    def mark_timestamp(value):
        dt = parse_datetime_safe(value)
        if not dt:
            return None
        active_days.add(dt.date().isoformat())
        window_counter[hour_window_label(dt.hour)] += 1
        return dt

    last_topic = ""
    for item in content_logs:
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("content_type") or "other").strip().lower() or "other"
        if content_type not in {"image", "link", "qa", "note", "other"}:
            content_type = "other"
        content_counter[content_type] += 1
        interaction_counter["content_interactions"] += 1

        dt = mark_timestamp(item.get("timestamp"))
        if dt and dt.date().isoformat() == today_label:
            today_content_counter[content_type] += 1
        topics = filter_learning_topics(
            [normalize_topic(topic) for topic in (item.get("topics") or []) if normalize_topic(topic)],
            blocked_topics=blocked_set,
            limit=6,
        )
        for topic in topics:
            topic_counter[topic] += 1
        if topics:
            current_topic = topics[0]
            if last_topic and current_topic != last_topic:
                exploration_counter[(last_topic, current_topic, "topic")] += 1
            last_topic = current_topic

        recent_feed.append({
            "timestamp": item.get("timestamp") or "",
            "kind": content_type,
            "label": content_type_label(content_type),
            "title": short_text(item.get("title") or content_type_label(content_type), 28),
            "summary": short_text("、".join(topics) or str(item.get("source") or "内容录入"), 60),
        })

    for item in qa_logs:
        if not isinstance(item, dict):
            continue
        interaction_counter["qa_interactions"] += 1
        dt = mark_timestamp(item.get("timestamp"))
        if dt and dt.date().isoformat() == today_label:
            today_qa_count += 1
        recent_feed.append({
            "timestamp": item.get("timestamp") or "",
            "kind": "qa_dialog",
            "label": "智能问答",
            "title": short_text(item.get("question") or "问答记录", 28),
            "summary": short_text(item.get("answer") or "已生成回答", 60),
        })

    for item in question_draw_logs:
        if not isinstance(item, dict):
            continue
        interaction_counter["question_draw"] += 1
        dt = mark_timestamp(item.get("timestamp"))
        if dt and dt.date().isoformat() == today_label:
            today_question_draw_count += 1
        concept = str(item.get("concept") or "综合").strip() or "综合"
        if concept not in blocked_set and is_learning_topic(concept):
            topic_counter[concept] += 1
        recent_feed.append({
            "timestamp": item.get("timestamp") or "",
            "kind": "question_draw",
            "label": "题库抽题",
            "title": f"抽取题目：{short_text(concept, 18)}",
            "summary": f"难度 {item.get('difficulty') or '--'} · 类型 {item.get('question_type') or '--'}",
        })

    correct_count = 0
    score_total = 0.0
    for item in question_answer_logs:
        if not isinstance(item, dict):
            continue
        interaction_counter["question_answer"] += 1
        dt = mark_timestamp(item.get("timestamp"))
        if dt and dt.date().isoformat() == today_label:
            today_question_answer_count += 1
        concept = str(item.get("concept") or "综合").strip() or "综合"
        if concept not in blocked_set and is_learning_topic(concept):
            topic_counter[concept] += 1
        score = float(item.get("score", 0.0) or 0.0)
        score_total += score
        if bool(item.get("is_correct", False)):
            correct_count += 1
        recent_feed.append({
            "timestamp": item.get("timestamp") or "",
            "kind": "question_answer",
            "label": "提交答案",
            "title": f"作答反馈：{short_text(concept, 18)}",
            "summary": f"{'正确' if item.get('is_correct') else '待加强'} · 得分 {round(score * 100)}%",
        })

    for item in diagnosis_logs:
        if not isinstance(item, dict):
            continue
        interaction_counter["diagnosis"] += 1
        dt = mark_timestamp(item.get("timestamp"))
        if dt and dt.date().isoformat() == today_label:
            today_diagnosis_count += 1
        diagnosis = item.get("diagnosis", {}) or {}
        recent_feed.append({
            "timestamp": item.get("timestamp") or "",
            "kind": "diagnosis",
            "label": "认知诊断",
            "title": short_text(diagnosis.get("error_type") or CATEGORY_LABELS.get(diagnosis.get("category"), "认知诊断"), 28),
            "summary": short_text(diagnosis.get("recommendation") or item.get("question") or "", 60),
        })

    for item in summary_behavior_logs:
        if not isinstance(item, dict):
            continue
        behavior_type = str(item.get("behavior_type") or item.get("type") or "behavior").strip().lower() or "behavior"
        interaction_counter[behavior_type] += 1
        mark_timestamp(item.get("timestamp"))

        if behavior_type == "page_stay":
            page_key = normalize_page_id(item.get("page"))
            duration = max(0.0, float(item.get("duration_seconds", 0.0) or 0.0))
            page_duration_seconds[page_key] += duration
            dt = parse_datetime_safe(item.get("timestamp"))
            if dt and dt.date().isoformat() == today_label:
                today_stay_seconds += duration
        elif behavior_type == "navigation_click":
            source_page = normalize_page_id(item.get("page"))
            target_page = normalize_page_id(item.get("target"))
            if source_page and target_page and source_page != target_page:
                exploration_counter[(page_label(source_page), page_label(target_page), "page")] += 1

        if behavior_type in {"page_view", "page_stay", "navigation_click"}:
            page_text = page_label(item.get("page"))
            summary_parts = []
            if behavior_type == "page_stay" and float(item.get("duration_seconds", 0.0) or 0.0) > 0:
                summary_parts.append(f"停留 {round(float(item.get('duration_seconds', 0.0) or 0.0) / 60, 1)} 分钟")
            if item.get("target"):
                summary_parts.append(f"目标 {page_label(item.get('target'))}")
            recent_feed.append({
                "timestamp": item.get("timestamp") or "",
                "kind": behavior_type,
                "label": "行为轨迹",
                "title": f"{page_text} · {behavior_type}",
                "summary": " · ".join(summary_parts) or "已记录探索行为",
            })

    measured_stay_minutes = int(round(sum(page_duration_seconds.values()) / 60.0))
    if measured_stay_minutes <= 0:
        measured_stay_minutes = int(round(
            content_counter.get("image", 0) * 6
            + content_counter.get("link", 0) * 12
            + content_counter.get("note", 0) * 8
            + content_counter.get("qa", 0) * 7
            + content_counter.get("other", 0) * 5
            + len(question_answer_logs) * 4
            + len(qa_logs) * 5
            + len(diagnosis_logs) * 6
        ))
    today_stay_minutes = int(round(today_stay_seconds / 60.0))
    if today_stay_minutes <= 0:
        today_stay_minutes = int(round(
            today_content_counter.get("image", 0) * 6
            + today_content_counter.get("link", 0) * 12
            + today_content_counter.get("note", 0) * 8
            + today_content_counter.get("qa", 0) * 7
            + today_content_counter.get("other", 0) * 5
            + today_question_draw_count * 3
            + today_question_answer_count * 4
            + today_qa_count * 5
            + today_diagnosis_count * 6
        ))
    current_streak = compute_current_streak(active_days, current_time.date())

    hidden_topic_table = hidden_metrics.get("topic_total_table", []) if isinstance(hidden_metrics.get("topic_total_table"), list) else []
    hidden_window_table = hidden_metrics.get("study_window_total_table", []) if isinstance(hidden_metrics.get("study_window_total_table"), list) else []

    filtered_hidden_topic_table = []
    for item in hidden_topic_table:
        if not isinstance(item, dict):
            continue
        topic = normalize_topic(item.get("topic"))
        if topic in blocked_set or not is_learning_topic(topic):
            continue
        filtered_hidden_topic_table.append({
            "topic": topic,
            "count": int(item.get("count", 0) or 0),
        })

    top_topics = filtered_hidden_topic_table[:6] if filtered_hidden_topic_table else [
        {"topic": topic, "count": count}
        for topic, count in topic_counter.most_common()
        if topic not in blocked_set and is_learning_topic(topic)
    ][:6]

    study_windows = hidden_window_table[:6] if hidden_window_table else [
        {"label": label, "count": count}
        for label, count in window_counter.most_common(6)
    ]

    exploration_paths = []
    for (start, end, kind), count in exploration_counter.most_common(6):
        exploration_paths.append({
            "path": [start, end],
            "count": count,
            "kind": kind,
        })

    recent_feed.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    link_items = [item for item in content_logs if isinstance(item, dict) and str(item.get("content_type") or "").strip().lower() == "link"]
    video_like_count = sum(1 for item in link_items if link_kind(item) == "video")
    reading_like_count = max(0, len(link_items) - video_like_count)
    answer_accuracy = round(correct_count * 100.0 / len(question_answer_logs), 1) if question_answer_logs else 0.0
    average_answer_score = round(score_total * 100.0 / len(question_answer_logs), 1) if question_answer_logs else 0.0
    learning_record_count = (
        content_counter.get("image", 0)
        + content_counter.get("link", 0)
        + content_counter.get("note", 0)
        + content_counter.get("other", 0)
    )

    spaces, space_items = collect_space_items(space_payload)
    space_kind_counter = Counter()
    for item in space_items:
        kind = str(item.get("kind") or "document").strip().lower() or "document"
        space_kind_counter[kind] += 1

    space_content_count = len(space_items)
    learning_content_record_count = learning_record_count + space_content_count
    wrong_question_count = len(wrong_question_logs)
    sample_total = len(question_answer_logs) + len(diagnosis_logs)

    return {
        "total_records": total_records,
        "active_days": current_streak,
        "active_days_total": len(active_days),
        "estimated_stay_minutes": today_stay_minutes,
        "measured_stay_minutes_today": int(round(today_stay_seconds / 60.0)),
        "estimated_stay_minutes_total": measured_stay_minutes,
        "study_windows": study_windows,
        "top_topics": top_topics,
        "exploration_paths": exploration_paths,
        "recent_feed": recent_feed[:8],
        "learning_content_record_count": learning_content_record_count,
        "space_content_count": space_content_count,
        "space_count": len(spaces),
        "space_kind_breakdown": dict(space_kind_counter),
        "wrong_question_count": wrong_question_count,
        "question_draw_count": len(question_draw_logs),
        "question_answer_count": len(question_answer_logs),
        "diagnosis_count": len(diagnosis_logs),
        "qa_sample_total": sample_total,
        "modality_breakdown": {
            "image": content_counter.get("image", 0),
            "link": content_counter.get("link", 0),
            "note": content_counter.get("note", 0),
            "qa": content_counter.get("qa", 0),
            "other": content_counter.get("other", 0),
            "video_like": video_like_count,
            "reading_like": reading_like_count,
            "space_items": space_content_count,
        },
        "interaction_breakdown": {
            "qa_interactions": len(qa_logs),
            "question_draw": len(question_draw_logs),
            "question_answer": len(question_answer_logs),
            "diagnosis": len(diagnosis_logs),
            "behavior": len(behavior_logs),
            "answer_accuracy": answer_accuracy,
            "average_answer_score": average_answer_score,
            "wrong_questions": wrong_question_count,
            "qa_sample_total": sample_total,
        },
        "dimension_coverage": {
            "behavior_logs": len(behavior_logs),
            "content_interactions": len(content_logs),
            "evaluation_feedback": len(diagnosis_logs) + len(question_answer_logs),
        },
        "preprocessing_pipeline": [],
        "hidden_metrics": hidden_metrics,
    }


def build_graph_insights(
    user_id,
    user_knowledge,
    graph_payload,
    reminders,
    content_logs,
    infer_learning_path_fn=None,
    blocked_topics=None,
):
    user_knowledge = user_knowledge if isinstance(user_knowledge, dict) else {}
    graph_payload = graph_payload if isinstance(graph_payload, dict) else {}
    reminders = reminders if isinstance(reminders, dict) else {}
    content_logs = content_logs if isinstance(content_logs, list) else []
    blocked_set = normalize_blocked_topics(blocked_topics)

    concepts = user_knowledge.get("concepts", []) if isinstance(user_knowledge.get("concepts"), list) else []
    relations = user_knowledge.get("relations", []) if isinstance(user_knowledge.get("relations"), list) else []
    reminder_items = {}
    for item in (reminders.get("due_items") or []) + (reminders.get("upcoming_items") or []):
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        if concept:
            reminder_items[concept] = item

    concept_sources = defaultdict(list)
    for item in content_logs:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or content_type_label(item.get("content_type"))).strip() or "学习内容"
        source_item = {
            "title": title,
            "source": str(item.get("source") or "manual"),
            "content_type": str(item.get("content_type") or "other"),
            "timestamp": str(item.get("timestamp") or ""),
        }
        for topic in filter_learning_topics(
            [normalize_topic(topic) for topic in (item.get("topics") or []) if normalize_topic(topic)],
            blocked_topics=blocked_set,
            limit=6,
        ):
            concept_sources[topic].append(source_item)

    relation_snapshot = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        source = str(rel.get("source") or "").strip()
        target = str(rel.get("target") or "").strip()
        if (
            not source or not target
            or source in blocked_set
            or target in blocked_set
            or not is_learning_topic(source)
            or not is_learning_topic(target)
        ):
            continue
        relation_snapshot.append({
            "source": source,
            "target": target,
            "type": str(rel.get("type") or "相关"),
            "score": round(float(rel.get("score", 0.6) or 0.6) * 100),
        })
    relation_snapshot.sort(key=lambda item: item.get("score", 0), reverse=True)

    heatmap = []
    weak_count = 0
    medium_count = 0
    strong_count = 0
    for item in concepts:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        if not concept or concept in blocked_set or not is_learning_topic(concept):
            continue
        mastery = round(float(item.get("mastery", 0.0) or 0.0) * 100)
        if mastery < 45:
            status = "weak"
            weak_count += 1
        elif mastery < 70:
            status = "warn"
            medium_count += 1
        else:
            status = "good"
            strong_count += 1

        source_titles = unique_preserve([src.get("title") for src in concept_sources.get(concept, [])], limit=3)
        reminder = reminder_items.get(concept, {})
        heatmap.append({
            "concept": concept,
            "mastery": mastery,
            "status": status,
            "review_count": int(item.get("review_count", 0) or 0),
            "next_review": reminder.get("next_review"),
            "due": bool(reminder.get("due", False)),
            "overdue_days": int(reminder.get("overdue_days", 0) or 0),
            "source_titles": source_titles,
            "source_count": len(concept_sources.get(concept, [])),
        })
    heatmap.sort(key=lambda item: (item.get("mastery", 0), -item.get("source_count", 0), item.get("concept", "")))

    dependency_chain = []
    if infer_learning_path_fn:
        for item in heatmap[:5]:
            concept = item.get("concept")
            if not concept:
                continue
            try:
                path = infer_learning_path_fn(user_id, concept) or []
            except Exception:
                path = []
            if not isinstance(path, list):
                path = []
            if len(path) >= 2:
                dependency_chain.append({
                    "target": concept,
                    "path": path,
                    "reason": f"掌握度 {item.get('mastery', 0)}%，建议回溯前置链",
                    "mastery": item.get("mastery", 0),
                })

    if not dependency_chain:
        for rel in relation_snapshot[:5]:
            dependency_chain.append({
                "target": rel.get("target"),
                "path": [rel.get("source"), rel.get("target")],
                "reason": f"{rel.get('type')}关系强度 {rel.get('score')}%",
                "mastery": next((item.get("mastery", 0) for item in heatmap if item.get("concept") == rel.get("target")), 0),
            })

    source_trace = []
    for item in heatmap[:6]:
        source_trace.append({
            "concept": item.get("concept"),
            "mastery": item.get("mastery", 0),
            "status": item.get("status"),
            "sources": item.get("source_titles", []),
            "source_count": item.get("source_count", 0),
        })

    nodes = graph_payload.get("nodes", []) if isinstance(graph_payload.get("nodes"), list) else []
    edges = graph_payload.get("links", []) if isinstance(graph_payload.get("links"), list) else []

    return {
        "mastery_heatmap": heatmap[:8],
        "dependency_chain": dependency_chain[:6],
        "concept_source_trace": source_trace,
        "relation_snapshot": relation_snapshot[:8],
        "distribution": {
            "weak": weak_count,
            "medium": medium_count,
            "strong": strong_count,
        },
        "review_forecast": {
            "due_count": int(reminders.get("due_count", 0) or 0),
            "upcoming_count": int(reminders.get("upcoming_count", 0) or 0),
            "weak_concept_count": weak_count,
        },
        "graph_size": {
            "nodes": len(nodes),
            "edges": len(edges),
        },
    }


def build_profile_insights(profile, data_pool, blocked_topics=None):
    profile = profile if isinstance(profile, dict) else {}
    data_pool = data_pool if isinstance(data_pool, dict) else {}
    blocked_set = normalize_blocked_topics(blocked_topics)

    content_counter = profile.get("content_type_counter", {}) if isinstance(profile.get("content_type_counter"), dict) else {}
    style_scores = profile.get("style_scores", {}) if isinstance(profile.get("style_scores"), dict) else {}
    total_media = sum(
        int(content_counter.get(key, 0) or 0)
        for key in ["image", "link", "qa", "note", "other"]
    )

    media_preferences = []
    media_map = [
        ("image", "截图 / 图像"),
        ("link", "链接 / 视频"),
        ("qa", "练习 / 作答"),
        ("note", "笔记 / 总结"),
        ("other", "其他内容"),
    ]
    for key, label in media_map:
        count = int(content_counter.get(key, 0) or 0)
        media_preferences.append({
            "key": key,
            "label": label,
            "count": count,
            "percent": to_percent(count, total_media),
        })
    media_preferences.sort(key=lambda item: item.get("count", 0), reverse=True)

    top_topics = data_pool.get("top_topics", []) if isinstance(data_pool.get("top_topics"), list) else []
    explicit_interests = filter_learning_topics(
        [normalize_topic(item) for item in (profile.get("interests") or []) if normalize_topic(item)],
        blocked_topics=blocked_set,
        limit=8,
    )
    implicit_map = {
        normalize_topic(item.get("topic")): int(item.get("count", 0) or 0)
        for item in top_topics
        if isinstance(item, dict)
        and normalize_topic(item.get("topic"))
        and normalize_topic(item.get("topic")) not in blocked_set
        and is_learning_topic(normalize_topic(item.get("topic")))
    }

    interests = []
    interest_keys = unique_preserve(explicit_interests + list(implicit_map.keys()), limit=8)
    for key in interest_keys:
        source = "显性兴趣"
        if key in explicit_interests and key in implicit_map:
            source = "显性 + 隐性"
        elif key in implicit_map:
            source = "隐性行为"
        interests.append({
            "topic": key,
            "count": implicit_map.get(key, 0),
            "source": source,
        })

    learning_style = str(profile.get("learning_style") or "").strip()
    style_method = str(profile.get("style_method") or "").strip()
    profile_traits = []
    has_profile_signal = any([
        learning_style,
        explicit_interests,
        any(int(item.get("count", 0) or 0) > 0 for item in media_preferences),
        str(profile.get("best_time_range") or "").strip(),
        bool(profile.get("focus_minutes")),
    ])

    if media_preferences and media_preferences[0].get("count", 0) > 0:
        profile_traits.append(f"当前最常使用的内容通道为“{media_preferences[0]['label']}”，说明学习输入更依赖该媒介。")
    if learning_style:
        profile_traits.append(f"画像识别结果为“{STYLE_LABELS.get(learning_style, learning_style)}”，推断方式为 {METHOD_LABELS.get(style_method, style_method or '--')}。")
    if profile.get("best_time_range"):
        profile_traits.append(f"高频活跃时段集中在 {profile.get('best_time_range')}，可优先安排高强度学习任务。")
    if profile.get("focus_minutes"):
        profile_traits.append(f"建议单次专注学习时长控制在 {profile.get('focus_minutes')} 分钟左右，以兼顾效率与持续性。")

    return {
        "learning_style_label": STYLE_LABELS.get(learning_style, learning_style) if has_profile_signal else "",
        "style_method_label": METHOD_LABELS.get(style_method, style_method or "--"),
        "style_scores": {
            "visual": round(float(style_scores.get("visual", 0.0) or 0.0) * 100),
            "auditory": round(float(style_scores.get("auditory", 0.0) or 0.0) * 100),
            "kinesthetic": round(float(style_scores.get("kinesthetic", 0.0) or 0.0) * 100),
        },
        "media_preferences": media_preferences,
        "interests": interests,
        "profile_traits": profile_traits[:4],
        "has_profile_signal": bool(has_profile_signal),
    }


def build_intervention_summary(profile, diagnosis_report, recommendations, reminders):
    profile = profile if isinstance(profile, dict) else {}
    diagnosis_report = diagnosis_report if isinstance(diagnosis_report, dict) else {}
    recommendations = recommendations if isinstance(recommendations, list) else []
    reminders = reminders if isinstance(reminders, dict) else {}

    category_count = diagnosis_report.get("category_count", {}) if isinstance(diagnosis_report.get("category_count"), dict) else {}
    latest_items = diagnosis_report.get("latest", []) if isinstance(diagnosis_report.get("latest"), list) else []
    due_items = reminders.get("due_items", []) if isinstance(reminders.get("due_items"), list) else []

    resource_mix = []
    for key in ["knowledge", "skill", "habit"]:
        count = int(category_count.get(key, 0) or 0)
        resource_mix.append({
            "category": key,
            "label": CATEGORY_LABELS.get(key, key),
            "count": count,
            "resource": RESOURCE_BY_CATEGORY.get(key, RESOURCE_BY_CATEGORY["unknown"]),
        })

    latest_cases = []
    for item in latest_items[:5]:
        if not isinstance(item, dict):
            continue
        diagnosis = item.get("diagnosis", {}) or {}
        advice = item.get("learning_advice", {}) if isinstance(item.get("learning_advice"), dict) else {}
        category = str(diagnosis.get("category") or "unknown").strip() or "unknown"
        recommendation_text = (
            diagnosis.get("recommendation")
            or advice.get("建议")
            or RESOURCE_BY_CATEGORY.get(category, RESOURCE_BY_CATEGORY["unknown"])
        )
        latest_cases.append({
            "timestamp": item.get("timestamp") or "",
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, CATEGORY_LABELS["unknown"]),
            "error_type": diagnosis.get("error_type") or CATEGORY_LABELS.get(category, "认知诊断"),
            "question_excerpt": short_text(item.get("question") or "", 80),
            "signals": diagnosis.get("signals", [])[:3] if isinstance(diagnosis.get("signals"), list) else [],
            "recommendation": recommendation_text,
        })

    action_queue = []
    queued_keys = set()

    style = str(profile.get("learning_style") or "").strip() or "visual"
    focus_minutes = int(profile.get("focus_minutes", 40) or 40)
    style_action_hint = {
        "visual": "先看图解再口头复述",
        "auditory": "先听讲解再复述关键点",
        "kinesthetic": "先做1题再回看解析",
    }.get(style, "先做后讲")

    for case in latest_cases[:4]:
        if not isinstance(case, dict):
            continue
        case_target = str(case.get("error_type") or case.get("category_label") or "认知诊断").strip()
        case_recommend = str(case.get("recommendation") or "").strip()
        if not case_target or not case_recommend:
            continue
        queue_key = f"diag:{case_target}:{case_recommend[:32]}"
        if queue_key in queued_keys:
            continue
        queued_keys.add(queue_key)
        action_queue.append({
            "kind": "diagnosis_followup",
            "title": f"{case_target} - 定向补救",
            "target": case_target,
            "time": profile.get("best_time_range") or "今天完成",
            "resource": f"{style_action_hint} + {RESOURCE_BY_CATEGORY.get(str(case.get('category') or 'unknown'), RESOURCE_BY_CATEGORY['unknown'])}",
            "reason": f"最近诊断提示：{case_recommend}",
            "evidence": f"单次训练建议 {focus_minutes} 分钟，结合最新诊断信号执行",
        })
    for item in recommendations[:5]:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or item.get("title") or "").strip()
        queue_key = f"rec:{concept}"
        if queue_key in queued_keys:
            continue
        queued_keys.add(queue_key)
        action_queue.append({
            "kind": "recommendation",
            "title": item.get("title") or f"{concept} 补救任务",
            "target": concept,
            "time": item.get("recommend_time") or profile.get("best_time_range") or "--",
            "resource": item.get("resource_type") or "个性化学习包",
            "reason": item.get("reason") or "结合当前画像与图谱状态自动生成",
            "evidence": item.get("evidence_brief") or "",
        })

    for item in due_items[:3]:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        queue_key = f"review:{concept}"
        if not concept or queue_key in queued_keys:
            continue
        queued_keys.add(queue_key)
        action_queue.append({
            "kind": "review",
            "title": f"优先复习 {concept}",
            "target": concept,
            "time": "今天完成",
            "resource": "复习卡片 + 同类题巩固",
            "reason": f"掌握度 {round(float(item.get('mastery', 0.0) or 0.0) * 100)}%，已进入遗忘曲线复习窗口",
            "evidence": f"逾期 {int(item.get('overdue_days', 0) or 0)} 天" if item.get("overdue_days") else "到期复习节点",
        })

    for key in ["knowledge", "skill", "habit"]:
        count = int(category_count.get(key, 0) or 0)
        if count <= 0:
            continue
        queue_key = f"category:{key}"
        if queue_key in queued_keys:
            continue
        queued_keys.add(queue_key)
        action_queue.append({
            "kind": "category",
            "title": f"{CATEGORY_LABELS.get(key, key)}专项补救",
            "target": CATEGORY_LABELS.get(key, key),
            "time": profile.get("best_time_range") or "--",
            "resource": RESOURCE_BY_CATEGORY.get(key, RESOURCE_BY_CATEGORY["unknown"]),
            "reason": f"最近累计出现 {count} 次 {CATEGORY_LABELS.get(key, key)}，建议进行专项干预。",
            "evidence": "由错题归因与提示工程规则自动汇总",
        })

    return {
        "pending_count": len(action_queue),
        "resource_mix": resource_mix,
        "latest_cases": latest_cases,
        "action_queue": action_queue[:8],
    }


def build_dashboard_sections(
    user_id,
    user_knowledge,
    graph_payload,
    reminders,
    profile,
    diagnosis_report,
    recommendations,
    content_logs,
    qa_logs,
    behavior_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    wrong_question_logs=None,
    space_payload=None,
    hidden_metrics=None,
    infer_learning_path_fn=None,
):
    blocked_topics = user_knowledge.get("deleted_concepts", []) if isinstance(user_knowledge, dict) else []
    data_pool = build_data_pool_summary(
        content_logs=content_logs,
        qa_logs=qa_logs,
        behavior_logs=behavior_logs,
        question_draw_logs=question_draw_logs,
        question_answer_logs=question_answer_logs,
        diagnosis_logs=diagnosis_logs,
        wrong_question_logs=wrong_question_logs,
        space_payload=space_payload,
        hidden_metrics=hidden_metrics,
        blocked_topics=blocked_topics,
    )

    # 认知诊断样本总量应使用完整 diagnosis_report，而不是 latest 切片。
    if isinstance(diagnosis_report, dict):
        data_pool["interaction_breakdown"]["diagnosis"] = int(diagnosis_report.get("total", 0) or 0)
        data_pool["qa_sample_total"] = len(question_answer_logs) + int(diagnosis_report.get("total", 0) or 0)
        data_pool["interaction_breakdown"]["qa_sample_total"] = data_pool["qa_sample_total"]
        if data_pool.get("preprocessing_pipeline"):
            data_pool["preprocessing_pipeline"][-1]["detail"] = (
                f"累计抽取 {sum(item.get('count', 0) for item in data_pool.get('top_topics', []))} 个主题命中，"
                f"沉淀 {int(diagnosis_report.get('total', 0) or 0)} 条认知诊断样本"
            )

    graph_insights = build_graph_insights(
        user_id=user_id,
        user_knowledge=user_knowledge,
        graph_payload=graph_payload,
        reminders=reminders,
        content_logs=content_logs,
        infer_learning_path_fn=infer_learning_path_fn,
        blocked_topics=blocked_topics,
    )
    profile_insights = build_profile_insights(profile=profile, data_pool=data_pool, blocked_topics=blocked_topics)
    intervention_summary = build_intervention_summary(
        profile=profile,
        diagnosis_report=diagnosis_report,
        recommendations=recommendations,
        reminders=reminders,
    )

    return {
        "data_pool": data_pool,
        "graph_insights": graph_insights,
        "profile_insights": profile_insights,
        "intervention_summary": intervention_summary,
    }
