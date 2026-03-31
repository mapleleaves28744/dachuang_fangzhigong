from datetime import datetime
from difflib import SequenceMatcher
from statistics import median
import re


CONFUSION_MARKERS = {
    "不会",
    "不懂",
    "不知道",
    "不会做",
    "没思路",
    "看不懂",
    "忘了",
    "想不起来",
}

STEP_MARKERS = (
    "先",
    "再",
    "然后",
    "所以",
    "因此",
    "代入",
    "计算",
    "步骤",
    "公式",
    "=",
)

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,}|[0-9]+(?:\.[0-9]+)?")
NUMBER_PATTERN = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
STOPWORDS = {
    "答案",
    "结果",
    "因为",
    "所以",
    "然后",
    "这个",
    "那个",
    "一种",
    "可以",
    "需要",
    "进行",
    "通过",
    "其中",
    "如果",
    "得到",
}

DEFAULT_STANDARD_SECONDS = 60.0


def clamp01(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


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


def normalize_text(value):
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def normalize_core_text(value):
    text = normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[，。；：,.!?！？()（）【】\\[\\]{}<>“”'\"`~·/\\\\\\-_+=*^%$#@|]", "", text)


def extract_keywords(text, limit=8):
    tokens = []
    for token in TOKEN_PATTERN.findall(str(text or "")):
        current = token.strip().lower()
        if len(current) < 2 or current in STOPWORDS or current in tokens:
            continue
        tokens.append(current)
        if len(tokens) >= int(limit):
            break
    return tokens


def keyword_overlap(correct_answer, user_answer):
    keywords = extract_keywords(correct_answer)
    if not keywords:
        return 1.0 if normalize_core_text(correct_answer) == normalize_core_text(user_answer) else 0.0

    user_text = normalize_core_text(user_answer)
    hit_count = sum(1 for keyword in keywords if keyword in user_text)
    return round(hit_count / max(1, len(keywords)), 3)


def answer_similarity(correct_answer, user_answer):
    correct_text = normalize_core_text(correct_answer)
    user_text = normalize_core_text(user_answer)
    if not correct_text or not user_text:
        return 0.0
    return round(SequenceMatcher(None, correct_text, user_text).ratio(), 3)


def bool_from_record(record):
    if not isinstance(record, dict):
        return False

    if "is_correct" in record:
        return bool(record.get("is_correct"))

    try:
        return float(record.get("score", 0.0) or 0.0) >= 0.6
    except Exception:
        return False


def duration_from_record(record):
    if not isinstance(record, dict):
        return None
    seconds = safe_float(record.get("duration_seconds"), None)
    if seconds is None or seconds <= 0:
        return None
    return seconds


def recent_records(records, limit=10):
    prepared = []
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        prepared.append((dt or datetime.min, item))
    prepared.sort(key=lambda pair: pair[0])
    return [item for _, item in prepared[-int(limit):]]


def compute_accuracy(records):
    source = recent_records(records, limit=10)
    total = len(source)
    if total <= 0:
        return {
            "weighted_accuracy": 0.0,
            "raw_accuracy": 0.0,
            "recent_accuracy": 0.0,
            "correct_count": 0,
            "total_count": 0,
        }

    correct_count = sum(1 for item in source if bool_from_record(item))
    raw_accuracy = correct_count / total

    recent_start = max(0, total - 3)
    weighted_correct = 0.0
    weight_sum = 0.0
    for idx, item in enumerate(source):
        weight = 1.5 if total >= 3 and idx >= recent_start else 1.0
        weight_sum += weight
        weighted_correct += (1.0 if bool_from_record(item) else 0.0) * weight

    recent_window = source[-min(5, total):]
    recent_accuracy = sum(1 for item in recent_window if bool_from_record(item)) / max(1, len(recent_window))

    return {
        "weighted_accuracy": round(weighted_correct / max(weight_sum, 1.0), 3),
        "raw_accuracy": round(raw_accuracy, 3),
        "recent_accuracy": round(recent_accuracy, 3),
        "correct_count": int(correct_count),
        "total_count": int(total),
    }


def recent_accuracy(records, limit=5):
    source = recent_records(records, limit=limit)
    if not source:
        return 0.0
    correct_count = sum(1 for item in source if bool_from_record(item))
    return round(correct_count / len(source), 3)


def infer_standard_time_seconds(records, fallback=DEFAULT_STANDARD_SECONDS):
    source = recent_records(records, limit=20)
    correct_durations = [
        seconds
        for item in source
        for seconds in [duration_from_record(item)]
        if seconds is not None and bool_from_record(item)
    ]
    durations = [
        seconds
        for item in source
        for seconds in [duration_from_record(item)]
        if seconds is not None
    ]

    if len(correct_durations) >= 2:
        return round(max(15.0, min(600.0, float(median(correct_durations)))), 3)
    if durations:
        return round(max(15.0, min(600.0, float(median(durations)))), 3)
    return round(max(15.0, float(fallback or DEFAULT_STANDARD_SECONDS)), 3)


def compute_time_score(records, accuracy_score, standard_time_seconds=None):
    source = recent_records(records, limit=5)
    durations = [
        seconds
        for item in source
        for seconds in [duration_from_record(item)]
        if seconds is not None
    ]

    resolved_standard = safe_float(standard_time_seconds, None)
    if resolved_standard is None or resolved_standard <= 0:
        resolved_standard = infer_standard_time_seconds(records)

    if not durations:
        return 0.8, None, round(resolved_standard, 3), None

    median_seconds = float(median(durations))
    time_ratio = median_seconds / max(resolved_standard, 1.0)

    if 0.7 <= time_ratio <= 1.3:
        time_score = 1.0
    elif 1.3 < time_ratio <= 2.0:
        time_score = 0.75
    elif time_ratio > 2.0:
        time_score = 0.55
    elif 0.4 <= time_ratio < 0.7:
        time_score = 0.95 if accuracy_score >= 0.8 else 0.75
    else:
        time_score = 0.85 if accuracy_score >= 0.8 else 0.6

    return (
        round(time_score, 3),
        round(median_seconds, 3),
        round(resolved_standard, 3),
        round(time_ratio, 3),
    )


def compute_practice_score(total_count, accuracy_score):
    attempts = int(total_count or 0)
    accuracy = clamp01(accuracy_score)

    if attempts <= 1:
        score = 0.55
    elif attempts == 2:
        score = 0.7
    elif attempts == 3:
        score = 0.82
    elif attempts <= 5:
        score = 0.92
    else:
        score = 1.0

    if accuracy < 0.4:
        score = min(score, 0.7)
    return round(score, 3)


def compute_forgetting_factor(last_timestamp, now=None):
    now_dt = parse_datetime_safe(now) or datetime.now()
    last_dt = parse_datetime_safe(last_timestamp)
    if not last_dt:
        return 0.9, None

    days = max(0, (now_dt - last_dt).days)
    if days <= 1:
        return 1.0, days
    if days <= 3:
        return 0.95, days
    if days <= 7:
        return 0.9, days
    if days <= 14:
        return 0.8, days
    if days <= 30:
        return 0.65, days
    return 0.5, days


def mastery_status(mastery_score):
    score = clamp01(mastery_score)
    if score >= 0.8:
        return "熟练"
    if score >= 0.5:
        return "一般"
    return "薄弱"


def calculate_concept_mastery(concept, records, now=None, standard_time_seconds=None):
    source = recent_records(records, limit=10)
    accuracy_detail = compute_accuracy(source)
    accuracy_score = accuracy_detail["weighted_accuracy"]
    correct_count = accuracy_detail["correct_count"]
    total_count = accuracy_detail["total_count"]
    time_score, median_seconds, resolved_standard_seconds, time_ratio = compute_time_score(
        source,
        accuracy_score,
        standard_time_seconds=standard_time_seconds,
    )
    practice_score = compute_practice_score(total_count, accuracy_score)

    last_timestamp = source[-1].get("timestamp") if source else None
    forgetting_factor, idle_days = compute_forgetting_factor(last_timestamp, now=now)

    base_mastery = (
        0.6 * accuracy_score
        + 0.25 * time_score
        + 0.15 * practice_score
    )
    final_mastery = round(clamp01(base_mastery * forgetting_factor), 3)

    return {
        "知识点": str(concept or "").strip(),
        "掌握度": final_mastery,
        "状态": mastery_status(final_mastery),
        "正确率": round(accuracy_score, 3),
        "原始正确率": round(accuracy_detail["raw_accuracy"], 3),
        "最近正确率": round(accuracy_detail["recent_accuracy"], 3),
        "正确次数": int(correct_count),
        "作答次数": int(total_count),
        "时间得分": round(time_score, 3),
        "中位作答时间": median_seconds,
        "标准作答时间": resolved_standard_seconds,
        "时间比值": time_ratio,
        "练习系数": round(practice_score, 3),
        "基础掌握度": round(base_mastery, 3),
        "遗忘系数": round(forgetting_factor, 3),
        "距今未练天数": idle_days,
        "最近作答时间": last_timestamp,
    }


def contains_confusion_text(user_answer):
    normalized = normalize_core_text(user_answer)
    if not normalized:
        return True
    return any(marker in normalized for marker in CONFUSION_MARKERS)


def has_step_expression(user_answer):
    text = str(user_answer or "")
    return any(marker in text for marker in STEP_MARKERS)


def compute_wrong_streak(history_records):
    streak = 0
    for item in reversed(recent_records(history_records, limit=10)):
        if bool_from_record(item):
            break
        streak += 1
    return streak


def extract_first_number(value):
    match = NUMBER_PATTERN.search(str(value or ""))
    if not match:
        return None
    return safe_float(match.group(0), None)


def detect_near_miss(correct_answer, user_answer, similarity=None, overlap=None):
    similarity_value = answer_similarity(correct_answer, user_answer) if similarity is None else float(similarity)
    overlap_value = keyword_overlap(correct_answer, user_answer) if overlap is None else float(overlap)

    correct_number = extract_first_number(correct_answer)
    user_number = extract_first_number(user_answer)
    if correct_number is not None and user_number is not None:
        if abs(correct_number - user_number) / max(abs(correct_number), 1.0) <= 0.1:
            return True, "数值结果接近正确答案"
        tolerance = max(0.1, abs(correct_number) * 0.02)
        if abs(abs(correct_number) - abs(user_number)) <= tolerance and correct_number * user_number < 0:
            return True, "结果大小接近但符号相反"
        if (
            abs(user_number - correct_number * 10) <= max(0.5, abs(correct_number) * 0.02)
            or abs(correct_number - user_number * 10) <= max(0.5, abs(correct_number) * 0.02)
        ):
            return True, "结果疑似出现小数点错位"

    correct_text = normalize_core_text(correct_answer)
    user_text = normalize_core_text(user_answer)
    if not correct_text or not user_text:
        return False, ""
    if correct_text == user_text:
        return True, "答案与标准答案一致"
    if similarity_value >= 0.72 and abs(len(correct_text) - len(user_text)) <= 3:
        return True, "答案与标准答案非常接近"
    if overlap_value >= 0.6 and similarity_value >= 0.6:
        return True, "大部分关键词已命中"
    return False, ""


def build_error_scores(
    question,
    correct_answer,
    user_answer,
    concept_mastery=None,
    response_time_seconds=None,
    attempt_count=None,
    history_records=None,
    standard_time_seconds=None,
):
    mastery = None
    if concept_mastery is not None:
        mastery = clamp01(concept_mastery)

    history = recent_records(history_records or [], limit=10)
    overlap = keyword_overlap(correct_answer, user_answer)
    similarity = answer_similarity(correct_answer, user_answer)
    near_miss, near_miss_reason = detect_near_miss(
        correct_answer,
        user_answer,
        similarity=similarity,
        overlap=overlap,
    )
    confusion = contains_confusion_text(user_answer)
    step_expression = has_step_expression(user_answer)
    history_total = int(attempt_count or len(history))
    wrong_streak = compute_wrong_streak(history)
    recent_rate = recent_accuracy(history, limit=5)
    response_seconds = None
    if response_time_seconds is not None:
        try:
            response_seconds = max(0.0, float(response_time_seconds))
        except Exception:
            response_seconds = None

    standard_seconds = safe_float(standard_time_seconds, None)
    if standard_seconds is None or standard_seconds <= 0:
        standard_seconds = infer_standard_time_seconds(history)
    time_ratio = (
        round(response_seconds / max(standard_seconds, 1.0), 3)
        if response_seconds is not None
        else None
    )

    blank_answer = not bool(normalize_core_text(user_answer))
    high_mastery = (mastery is not None and mastery >= 0.8) or recent_rate >= 0.8
    low_mastery = mastery is not None and mastery < 0.4
    fast_and_risky = time_ratio is not None and time_ratio < 0.6
    slow_response = time_ratio is not None and time_ratio > 1.3

    knowledge_hits = []
    skill_hits = []
    habit_hits = []

    if blank_answer:
        knowledge_hits.append("答案为空，说明当前缺少稳定思路")
    if confusion:
        knowledge_hits.append("出现不会/不懂类表达")
    if low_mastery:
        knowledge_hits.append("该知识点作答前掌握度低于 0.4")
    if history_total <= 1:
        knowledge_hits.append("该知识点首次接触即答错")
    if history_total >= 3 and recent_rate < 0.4:
        knowledge_hits.append("最近多次作答正确率低于 0.4")
    if wrong_streak >= 2:
        knowledge_hits.append("该知识点连续答错")
    if overlap < 0.2 and not near_miss and not step_expression:
        knowledge_hits.append("与标准答案关键点重合较低")

    if step_expression:
        skill_hits.append("答案中有步骤痕迹，说明尝试过方法应用")
    if slow_response:
        skill_hits.append("作答时间偏长，说明应用步骤还不熟")
    if mastery is not None and 0.4 <= mastery < 0.8:
        skill_hits.append("掌握度处于一般区间，说明会但不稳定")
    if 0.4 <= recent_rate < 0.8:
        skill_hits.append("近期正确率一般，说明方法迁移还不稳")
    if 0.2 <= overlap < 0.7 or 0.55 <= similarity < 0.85:
        skill_hits.append("知道部分关键点，但答案不够完整")

    if high_mastery:
        habit_hits.append("该知识点近期表现较好")
    if fast_and_risky:
        habit_hits.append("本次作答明显偏快")
    if near_miss:
        habit_hits.append(near_miss_reason or "答案与正确答案很接近")

    if high_mastery and (fast_and_risky or near_miss):
        top_category = "habit"
        primary_hits = habit_hits
    elif knowledge_hits and (
        blank_answer
        or confusion
        or low_mastery
        or history_total <= 1
        or (history_total >= 3 and recent_rate < 0.4)
    ):
        top_category = "knowledge"
        primary_hits = knowledge_hits
    else:
        top_category = "skill"
        primary_hits = skill_hits or ["存在一定基础，但本题应用过程不稳定"]

    confidence = min(0.94, 0.68 + 0.06 * min(len(primary_hits), 4))

    return {
        "top_category": top_category,
        "confidence": round(confidence, 3),
        "signals": (primary_hits + knowledge_hits + skill_hits + habit_hits)[:8],
        "score_detail": {
            "knowledge_rule_hits": len(knowledge_hits),
            "skill_rule_hits": len(skill_hits),
            "habit_rule_hits": len(habit_hits),
            "recent_accuracy": round(recent_rate, 3),
            "time_ratio": time_ratio,
            "standard_time_seconds": round(standard_seconds, 3) if standard_seconds is not None else None,
            "response_time_seconds": round(response_seconds, 3) if response_seconds is not None else None,
            "near_miss": bool(near_miss),
            "mastery_reference": round(mastery, 3) if mastery is not None else None,
        },
        "overlap": overlap,
        "similarity": similarity,
        "wrong_streak": wrong_streak,
        "history_total": history_total,
        "recent_accuracy": recent_rate,
        "time_ratio": time_ratio,
        "near_miss": near_miss,
    }


def classify_error_by_rules(
    question,
    correct_answer,
    user_answer,
    concept_mastery=None,
    response_time_seconds=None,
    attempt_count=None,
    history_records=None,
    standard_time_seconds=None,
):
    detail = build_error_scores(
        question=question,
        correct_answer=correct_answer,
        user_answer=user_answer,
        concept_mastery=concept_mastery,
        response_time_seconds=response_time_seconds,
        attempt_count=attempt_count,
        history_records=history_records,
        standard_time_seconds=standard_time_seconds,
    )

    error_label = {
        "knowledge": "知识性错误",
        "skill": "技能性错误",
        "habit": "习惯性错误",
    }
    category = detail["top_category"]
    return {
        "error_type": error_label.get(category, "知识性错误"),
        "category": category,
        "confidence": detail["confidence"],
        "signals": detail["signals"],
        "score_detail": detail["score_detail"],
        "overlap": detail["overlap"],
        "similarity": detail["similarity"],
        "wrong_streak": detail["wrong_streak"],
        "history_total": detail["history_total"],
        "recent_accuracy": detail.get("recent_accuracy", 0.0),
        "time_ratio": detail.get("time_ratio"),
        "near_miss": bool(detail.get("near_miss", False)),
    }


def build_learning_advice(error_type, mastery_score=None, concept="", attempt_count=None):
    mastery = clamp01(mastery_score) if mastery_score is not None else None
    concept_text = str(concept or "").strip() or "该知识点"
    attempts = max(0, int(attempt_count or 0))
    status = mastery_status(mastery) if mastery is not None else "一般"

    if error_type == "知识性错误":
        if mastery is None or mastery < 0.5:
            reason = f"{concept_text}的定义、公式或判断条件还没有真正建立，看到题目时不知道该从哪里开始。"
            suggestion = (
                f"先暂停刷题，先把“{concept_text}”补清楚。先看 1 个 5-8 分钟讲解视频，"
                "再整理 1 张概念/公式卡片，然后做 2 道基础例题，最后当天重做这道题。"
            )
            actions = ["看该知识点5-8分钟讲解视频", "整理1张公式/概念卡片", "做2道基础例题并对照答案", "当天再复做原题1次"]
        else:
            reason = f"{concept_text}并非完全陌生，但某个关键定义或条件点还没补齐，所以一遇到题目就容易卡住。"
            suggestion = (
                f"先回到“{concept_text}”最核心的定义和判定条件，"
                "先对照本题找出缺失点，再做 2 道同小类基础题，晚上再复做原题。"
            )
            actions = ["回看本题涉及的定义或公式2分钟", "做2道同一小类基础题", "把错题和正确解法写成对照", "晚上再复做原题"]
    elif error_type == "技能性错误":
        if mastery is None or mastery < 0.5:
            reason = f"你对{concept_text}有一点印象，但还不会把方法真正用到题目里，解题步骤容易中断。"
            suggestion = (
                "先学标准步骤，再按步骤练，不要只看最终答案。先看 1 道完整例题，"
                "把步骤写成 3 步模板，再按模板做 3 道同类型题。"
            )
            actions = ["看1道完整例题讲解", "把解题步骤写成3步模板", "按模板做3道同类型题", "每题做完对照步骤自查"]
        else:
            reason = f"{concept_text}已经有基础，但迁移到题目里时还不够稳定，容易在变形、代入或审题环节出错。"
            suggestion = (
                "先不要盲目加量，先限定题型练习。先做 3 道同题型题并写出关键步骤，"
                "再做 1 道限时题，要求先做对再做快。"
            )
            actions = ["做3道同题型题并写出关键步骤", "对照标准答案标记丢步骤的位置", "再做1道限时题", "把本题常用步骤总结成清单"]
    else:
        if mastery is not None and mastery >= 0.8:
            reason = f"{concept_text}整体掌握较好，这次更像是求快、漏看条件、符号或单位上的偶发失误。"
            suggestion = (
                "不需要重学大段内容，固定检查流程更有效。重做原题 1 遍并说出错因，"
                "再做 2 道限时题，每题结束都按“条件-符号-单位-结果”顺序检查。"
            )
            actions = ["重做原题1遍并口头说明错因", "做2道限时题训练稳定性", "每题结束按“条件-符号-单位-结果”检查", "下一次同类题先审题再下笔"]
        else:
            reason = f"{concept_text}基本会做，但做题节奏还不够稳，容易因为急躁出现低级错误。"
            suggestion = (
                "这时重点不是再学新内容，而是把检查动作做实。先重做原题并圈出出错点，"
                "再做 2 道同类题，每题固定留 30 秒检查。"
            )
            actions = ["重做原题并圈出出错点", "做2道同类题且每题留30秒检查", "重点检查符号/单位/小数点/抄写", "记录本次粗心标签"]

    if status == "薄弱" and error_type != "知识性错误":
        suggestion = f"先回到基础层再推进。{suggestion}"
    if attempts >= 6 and error_type == "知识性错误":
        suggestion = f"这不是偶然失误，已经连续多次暴露同类问题。{suggestion}"

    return {
        "错误类型": error_type,
        "原因": reason,
        "建议": suggestion,
        "推荐行动": actions,
    }
