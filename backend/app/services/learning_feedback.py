import math
from datetime import datetime

from .mastery_engine import compute_forgetting_factor, mastery_status, parse_datetime_safe


def clamp01(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _normalize_feedback_record(record):
    if not isinstance(record, dict):
        return None

    total_count = max(1, int(record.get("total_count") or 0))
    correct_count = max(0, min(total_count, int(record.get("correct_count") or 0)))
    accuracy = safe_float(record.get("accuracy"), None)
    if accuracy is None:
        accuracy = correct_count / max(1, total_count)
    accuracy = clamp01(accuracy)

    return {
        "accuracy": accuracy,
        "correct_count": correct_count,
        "total_count": total_count,
        "duration_seconds": max(0.0, safe_float(record.get("duration_seconds"), 0.0)),
        "timestamp": str(record.get("timestamp") or "").strip(),
    }


def _sorted_feedback_history(records):
    prepared = []
    for item in records if isinstance(records, list) else []:
        normalized = _normalize_feedback_record(item)
        if not normalized:
            continue
        dt = parse_datetime_safe(normalized.get("timestamp")) or datetime.min
        prepared.append((dt, normalized))
    prepared.sort(key=lambda pair: pair[0])
    return [item for _, item in prepared]


def _weighted_accuracy(records):
    history = _sorted_feedback_history(records)
    if not history:
        return 0.0, 0.0, 0.0

    correct_total = sum(item["correct_count"] for item in history)
    question_total = sum(item["total_count"] for item in history)
    raw_accuracy = correct_total / max(1, question_total)

    weighted_sum = 0.0
    weight_total = 0.0
    recent_window = history[-3:]
    recent_correct = sum(item["correct_count"] for item in recent_window)
    recent_total = sum(item["total_count"] for item in recent_window)
    recent_accuracy = recent_correct / max(1, recent_total)

    for idx, item in enumerate(history):
        recent_boost = 1.25 if idx >= max(0, len(history) - 3) else 1.0
        quantity_boost = min(2.0, 0.75 + item["total_count"] / 6.0)
        weight = recent_boost * quantity_boost
        weighted_sum += item["accuracy"] * weight
        weight_total += weight

    return (
        clamp01(weighted_sum / max(1.0, weight_total)),
        clamp01(raw_accuracy),
        clamp01(recent_accuracy),
    )


def _compute_duration_metrics(records):
    history = _sorted_feedback_history(records)
    if not history:
        return 0.8, None, 60.0, None

    per_question = []
    for item in history[-5:]:
        total = max(1, int(item["total_count"]))
        seconds = safe_float(item.get("duration_seconds"), 0.0)
        if seconds <= 0:
            continue
        per_question.append(seconds / total)

    if not per_question:
        return 0.8, None, 60.0, None

    avg_seconds = sum(per_question) / len(per_question)
    standard_seconds = 45.0
    time_ratio = avg_seconds / max(1.0, standard_seconds)

    if 0.7 <= time_ratio <= 1.6:
        duration_score = 1.0
    elif 0.45 <= time_ratio < 0.7 or 1.6 < time_ratio <= 2.2:
        duration_score = 0.8
    elif 0.25 <= time_ratio < 0.45 or 2.2 < time_ratio <= 3.0:
        duration_score = 0.65
    else:
        duration_score = 0.5

    if avg_seconds < 8:
        duration_score = min(duration_score, 0.6)

    return (
        clamp01(duration_score),
        round(avg_seconds, 3),
        round(standard_seconds, 3),
        round(time_ratio, 3),
    )


def _compute_trend_score(records):
    history = _sorted_feedback_history(records)
    if not history:
        return 0.5, 0.0

    current_accuracy = history[-1]["accuracy"]
    previous = history[:-1]
    if not previous:
        delta = current_accuracy - 0.5
        return clamp01(0.5 + delta * 0.5), round(delta, 3)

    recent_prev = previous[-3:]
    prev_correct = sum(item["correct_count"] for item in recent_prev)
    prev_total = sum(item["total_count"] for item in recent_prev)
    previous_accuracy = prev_correct / max(1, prev_total)
    delta = current_accuracy - previous_accuracy
    return clamp01(0.5 + delta * 0.8), round(delta, 3)


def _compute_practice_score(total_questions, current_total_count, current_accuracy):
    cumulative_factor = 1.0 - math.exp(-max(0, total_questions) / 10.0)
    session_factor = 1.0 - math.exp(-max(0, current_total_count) / 4.0)
    base_score = 0.55 + 0.3 * cumulative_factor + 0.15 * session_factor
    if current_accuracy < 0.4:
        base_score = min(base_score, 0.72)
    return clamp01(base_score)


def _compute_confidence_score(total_questions):
    return clamp01(1.0 - math.exp(-max(0, total_questions) / 12.0))


def build_feedback_mastery_assessment(concept, feedback_history, existing_snapshot=None, now=None):
    history = _sorted_feedback_history(feedback_history)
    current = history[-1] if history else _normalize_feedback_record({})
    total_questions = sum(item["total_count"] for item in history)
    current_total_count = int(current.get("total_count", 1) or 1)
    current_accuracy = clamp01(current.get("accuracy", 0.0))

    weighted_accuracy, raw_accuracy, recent_accuracy = _weighted_accuracy(history)
    trend_score, trend_delta = _compute_trend_score(history)
    duration_score, median_seconds, standard_seconds, time_ratio = _compute_duration_metrics(history)
    practice_score = _compute_practice_score(total_questions, current_total_count, current_accuracy)
    confidence_score = _compute_confidence_score(total_questions)

    existing = existing_snapshot if isinstance(existing_snapshot, dict) else {}
    previous_mastery = clamp01(existing.get("mastery", 0.35) or 0.35)
    previous_reviewed = (
        str(existing.get("last_reviewed") or "").strip()
        or str(existing.get("last_practiced") or "").strip()
        or str(existing.get("last_seen") or "").strip()
        or None
    )
    forgetting_factor, idle_days = compute_forgetting_factor(previous_reviewed, now=now)
    retained_mastery = previous_mastery * forgetting_factor

    base_mastery = (
        0.55 * weighted_accuracy
        + 0.15 * duration_score
        + 0.15 * practice_score
        + 0.15 * trend_score
    )

    session_strength = 1.0 - math.exp(-max(0, current_total_count) / 4.0)
    learning_rate = 0.08 + 0.24 * confidence_score * (0.45 + 0.55 * session_strength)
    learning_rate = clamp01(learning_rate)

    candidate_mastery = retained_mastery + (base_mastery - retained_mastery) * learning_rate
    delta = candidate_mastery - retained_mastery

    if current_total_count <= 1:
        max_up, max_down = 0.04, 0.05
    elif current_total_count <= 3:
        max_up, max_down = 0.07, 0.08
    else:
        max_up, max_down = 0.12, 0.14

    delta = max(-max_down, min(max_up, delta))
    final_mastery = clamp01(retained_mastery + delta)

    return {
        "知识点": str(concept or "").strip(),
        "掌握度": round(final_mastery, 3),
        "状态": mastery_status(final_mastery),
        "正确率": round(weighted_accuracy, 3),
        "原始正确率": round(raw_accuracy, 3),
        "最近正确率": round(recent_accuracy, 3),
        "正确次数": int(sum(item["correct_count"] for item in history)),
        "作答次数": int(total_questions),
        "时间得分": round(duration_score, 3),
        "中位作答时间": median_seconds,
        "标准作答时间": standard_seconds,
        "时间比值": time_ratio,
        "练习系数": round(practice_score, 3),
        "基础掌握度": round(base_mastery, 3),
        "遗忘系数": round(forgetting_factor, 3),
        "距今未练天数": idle_days,
        "最近作答时间": current.get("timestamp"),
        "趋势得分": round(trend_score, 3),
        "趋势变化": round(trend_delta, 3),
        "置信系数": round(confidence_score, 3),
        "更新系数": round(learning_rate, 3),
        "会话题量": int(current_total_count),
    }
