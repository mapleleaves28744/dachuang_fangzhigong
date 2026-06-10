import math
import re
from collections import Counter
from difflib import SequenceMatcher


SUPPORTED_QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "fill_blank",
    "term_definition",
    "step",
    "comprehensive",
    "short_answer",
    "retry",
}

QUESTION_TYPE_ALIASES = {
    "choice": "single_choice",
    "radio": "single_choice",
    "blank": "fill_blank",
    "fill": "fill_blank",
    "definition": "term_definition",
    "define": "term_definition",
    "process": "step",
    "procedure": "step",
    "steps": "step",
    "essay": "comprehensive",
    "case": "comprehensive",
}

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,8}|[A-Za-z]{2,}|[0-9]+(?:\.[0-9]+)?")
BLANK_SPLIT_PATTERN = re.compile(r"[|/／；;、，,\n]+")
CLAUSE_SPLIT_PATTERN = re.compile(r"(?:\n+|[。！？!?；;])")
NUMBERED_STEP_PATTERN = re.compile(r"(?:^|\n)\s*(?:\d+[\.、)]|[一二三四五六七八九十]+[、.]|首先|第一步|其次|然后|最后)")

STOPWORDS = {
    "答案",
    "结果",
    "进行",
    "需要",
    "这个",
    "那个",
    "因为",
    "所以",
    "然后",
    "其中",
    "说明",
    "分析",
    "步骤",
    "方法",
    "核心",
}

DEFINITION_HINTS = ("定义", "概念", "是什么", "含义", "解释", "几何意义", "物理意义")
STEP_HINTS = ("步骤", "过程", "推导", "证明", "求解", "如何", "怎么做", "说明做法", "错题重练")
COMPREHENSIVE_HINTS = ("综合", "分析", "比较", "评价", "结合", "应用", "联系实际", "举例说明")
FILL_HINTS = ("填空", "____", "___", "（ ）", "()")
EXAMPLE_HINTS = ("举例", "应用场景", "例子", "例如", "比如", "实例")

ORDER_MARKERS = (
    "首先",
    "先",
    "第一",
    "第一步",
    "其次",
    "再",
    "然后",
    "接着",
    "最后",
    "因此",
    "所以",
    "代入",
    "计算",
    "得到",
)

LOGIC_MARKERS = ("因为", "所以", "因此", "由此", "从而", "进而", "说明")


def clamp01(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def safe_round(value, ndigits=3):
    try:
        return round(float(value), int(ndigits))
    except Exception:
        return 0.0


def normalize_question_type(value):
    text = str(value or "").strip().lower().replace("-", "_")
    return QUESTION_TYPE_ALIASES.get(text, text or "short_answer")


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_core_text(value):
    text = normalize_text(value).lower()
    return re.sub(r"[\s，。；：,.!?！？()（）【】\[\]{}<>“”'\"`~·/\\\-_+=*^%$#@|]", "", text)


def tokenize_text(value):
    tokens = []
    for token in TOKEN_PATTERN.findall(str(value or "")):
        current = token.strip().lower()
        if len(current) <= 1 and not current.isdigit():
            continue
        if current in STOPWORDS:
            continue
        tokens.append(current)
    return tokens


def unique_tokens(value):
    items = []
    for token in tokenize_text(value):
        if token not in items:
            items.append(token)
    return items


def extract_choice_letter(text):
    value = str(text or "").strip().upper()
    if not value:
        return ""
    match = re.search(r"([A-Z])", value)
    return match.group(1) if match else ""


def split_clauses(text):
    clauses = []
    for raw in CLAUSE_SPLIT_PATTERN.split(str(text or "")):
        cleaned = raw.strip(" \t\r\n，,、:：")
        if normalize_core_text(cleaned):
            clauses.append(cleaned)
    return clauses


def split_reference_points(answer, analysis):
    points = []
    seen = set()

    def add_point(text, source):
        cleaned = normalize_text(text).strip("：:，,、")
        core = normalize_core_text(cleaned)
        if len(core) < 2 or core in seen:
            return
        seen.add(core)
        points.append({
            "text": cleaned,
            "source": source,
            "critical": source == "answer",
        })

    for source_name, raw_text in (("answer", answer), ("analysis", analysis)):
        for clause in split_clauses(raw_text):
            add_point(clause, source_name)

        for quoted in re.findall(r"[“\"]([^”\"]{2,50})[”\"]", str(raw_text or "")):
            for item in re.split(r"[-/、，,]", quoted):
                add_point(item, source_name)

    if not points:
        for token in unique_tokens(f"{answer} {analysis}")[:4]:
            add_point(token, "answer")

    if len(points) <= 1:
        for item in re.split(r"[-/、，,和并及]", str(answer or "")):
            add_point(item, "answer")

    return points[:6]


def longest_common_size(left, right):
    l_text = normalize_core_text(left)
    r_text = normalize_core_text(right)
    if not l_text or not r_text:
        return 0
    matcher = SequenceMatcher(None, l_text, r_text)
    return matcher.find_longest_match(0, len(l_text), 0, len(r_text)).size


def match_reference_point(point_text, user_clauses):
    point_core = normalize_core_text(point_text)
    point_tokens = unique_tokens(point_text)
    best_score = 0.0
    best_clause = ""

    for clause in user_clauses:
        clause_core = normalize_core_text(clause)
        if not clause_core:
            continue

        if point_core and point_core in clause_core:
            return 1.0, clause

        keyword_hits = sum(1 for token in point_tokens if token in clause_core)
        keyword_score = keyword_hits / max(1, len(point_tokens))
        similarity = SequenceMatcher(None, point_core, clause_core).ratio() if point_core else 0.0
        fragment_size = longest_common_size(point_text, clause)
        fragment_score = fragment_size / max(1, len(point_core))
        score = max(keyword_score, similarity * 0.85, fragment_score)
        if score > best_score:
            best_score = score
            best_clause = clause

    return clamp01(best_score), best_clause


def detect_question_family(question_item):
    raw_type = normalize_question_type(question_item.get("question_type"))
    question = normalize_text(question_item.get("question") or "")
    answer = normalize_text(question_item.get("answer") or "")
    analysis = normalize_text(question_item.get("analysis") or "")
    hint_text = f"{question} {analysis}"

    if raw_type in {"single_choice", "multiple_choice"}:
        return raw_type
    if raw_type == "fill_blank":
        return "fill_blank"
    if raw_type == "term_definition":
        return "term_definition"
    if raw_type == "step":
        return "step"
    if raw_type == "comprehensive":
        return "comprehensive"
    if raw_type == "retry":
        return "step"

    if any(hint in question for hint in FILL_HINTS):
        return "fill_blank"
    if any(hint in hint_text for hint in STEP_HINTS):
        return "step"
    if any(hint in hint_text for hint in COMPREHENSIVE_HINTS):
        return "comprehensive"
    if any(hint in hint_text for hint in DEFINITION_HINTS):
        return "term_definition"

    if len(split_reference_points(answer, analysis)) >= 3:
        return "comprehensive"
    return "term_definition"


def build_breakdown_item(item, score, weight, verdict, evidence):
    current_score = clamp01(score)
    current_weight = clamp01(weight)
    return {
        "item": str(item or "").strip(),
        "score": safe_round(current_score),
        "weight": safe_round(current_weight),
        "weighted_score": safe_round(current_score * current_weight),
        "verdict": str(verdict or "").strip(),
        "evidence": [str(x).strip() for x in (evidence or []) if str(x).strip()][:6],
    }


def evaluate_single_choice(expected_answer, user_answer, analysis):
    expected_choice = extract_choice_letter(expected_answer)
    user_choice = extract_choice_letter(user_answer)
    is_correct = bool(expected_choice and user_choice and expected_choice == user_choice)
    score = 1.0 if is_correct else 0.0
    summary = "选项匹配正确。" if is_correct else f"选项不匹配，正确答案是 {expected_choice or expected_answer}。"
    feedback = "回答正确，继续下一题。" if is_correct else f"回答不正确，正确答案是 {expected_choice or expected_answer}。"
    if analysis:
        feedback = f"{feedback}\n解析：{analysis}"

    return {
        "is_correct": is_correct,
        "score": score,
        "expected_answer": expected_answer,
        "feedback": feedback,
        "evaluation_method": "rule_single_choice",
        "scoring_type": "single_choice",
        "breakdown": [
            build_breakdown_item(
                item="选项匹配",
                score=score,
                weight=1.0,
                verdict="命中正确选项" if is_correct else "未命中正确选项",
                evidence=[
                    f"学生作答：{user_choice or normalize_text(user_answer) or '空'}",
                    f"标准答案：{expected_choice or expected_answer}",
                ],
            )
        ],
        "evidence": {
            "expected_choice": expected_choice or expected_answer,
            "matched_choice": user_choice or normalize_text(user_answer),
            "risk_flags": [],
        },
        "summary": summary,
    }


def evaluate_fill_blank(expected_answer, user_answer, analysis):
    expected_candidates = [
        normalize_core_text(item)
        for item in BLANK_SPLIT_PATTERN.split(str(expected_answer or ""))
        if normalize_core_text(item)
    ]
    user_candidates = [
        normalize_core_text(item)
        for item in BLANK_SPLIT_PATTERN.split(str(user_answer or ""))
        if normalize_core_text(item)
    ]

    if not expected_candidates:
        expected_candidates = [normalize_core_text(expected_answer)]
    if not user_candidates:
        user_candidates = [normalize_core_text(user_answer)]

    matched = 0
    missing = []
    remaining = list(user_candidates)
    for expected in expected_candidates:
        idx = next((i for i, item in enumerate(remaining) if item == expected), -1)
        if idx >= 0:
            matched += 1
            remaining.pop(idx)
        else:
            missing.append(expected)

    score = matched / max(1, len(expected_candidates))
    is_correct = matched == len(expected_candidates)
    summary = "填空答案匹配完成。" if is_correct else f"仍缺少 {len(missing)} 个空缺答案。"
    feedback = "填空正确。" if is_correct else "填空未完全命中，请补全缺失空缺。"
    if analysis:
        feedback = f"{feedback}\n解析：{analysis}"

    return {
        "is_correct": is_correct,
        "score": safe_round(score),
        "expected_answer": expected_answer,
        "feedback": feedback,
        "evaluation_method": "rule_fill_blank",
        "scoring_type": "fill_blank",
        "breakdown": [
            build_breakdown_item(
                item="答案规范化",
                score=1.0 if normalize_core_text(user_answer) else 0.0,
                weight=0.2,
                verdict="已完成空白答案规范化" if normalize_core_text(user_answer) else "未识别到有效答案",
                evidence=[
                    f"标准空缺数：{len(expected_candidates)}",
                    f"学生填写数：{len(user_candidates)}",
                ],
            ),
            build_breakdown_item(
                item="空缺匹配",
                score=score,
                weight=0.8,
                verdict=f"命中 {matched}/{len(expected_candidates)} 个空缺",
                evidence=[
                    f"缺失答案：{'、'.join(missing[:3])}" if missing else "空缺答案已全部命中",
                ],
            ),
        ],
        "evidence": {
            "expected_candidates": expected_candidates,
            "user_candidates": user_candidates,
            "missing_candidates": missing,
            "risk_flags": [],
        },
        "summary": summary,
    }


def answer_normalization_score(user_answer):
    normalized = normalize_core_text(user_answer)
    token_count = len(tokenize_text(user_answer))
    if not normalized:
        return 0.0, "未识别到有效答案", ["规范化后内容为空"]
    if len(normalized) <= 3:
        return 0.35, "答案过短", [f"规范化后长度仅 {len(normalized)}"]
    if token_count <= 2:
        return 0.55, "答案信息量偏少", [f"有效词元数 {token_count}"]
    return 1.0, "答案已规范化", [f"规范化后长度 {len(normalized)}", f"有效词元数 {token_count}"]


def evaluate_key_point_coverage(reference_points, user_answer):
    clauses = split_clauses(user_answer)
    if not clauses:
        clauses = [normalize_text(user_answer)]

    matched_points = []
    missing_points = []
    critical_missing = []
    partial_matches = []
    coverage_sum = 0.0

    for point in reference_points:
        match_score, matched_clause = match_reference_point(point["text"], clauses)
        coverage_sum += match_score
        evidence = {
            "point": point["text"],
            "score": safe_round(match_score),
            "matched_clause": normalize_text(matched_clause),
            "critical": bool(point.get("critical", False)),
        }
        if match_score >= 0.58:
            matched_points.append(evidence)
        elif match_score >= 0.35:
            partial_matches.append(evidence)
            missing_points.append(point["text"])
            if point.get("critical", False):
                critical_missing.append(point["text"])
        else:
            missing_points.append(point["text"])
            if point.get("critical", False):
                critical_missing.append(point["text"])

    coverage_score = coverage_sum / max(1, len(reference_points))
    verdict = f"命中 {len(matched_points)}/{len(reference_points)} 个关键点"
    evidence_lines = []
    if matched_points:
        evidence_lines.append(f"已覆盖：{'；'.join(item['point'] for item in matched_points[:3])}")
    if partial_matches:
        evidence_lines.append(f"部分覆盖：{'；'.join(item['point'] for item in partial_matches[:2])}")
    if missing_points:
        evidence_lines.append(f"缺失：{'；'.join(missing_points[:3])}")
    if not evidence_lines:
        evidence_lines.append("未识别到有效关键点覆盖")

    return {
        "score": clamp01(coverage_score),
        "verdict": verdict,
        "evidence_lines": evidence_lines,
        "matched_points": matched_points,
        "missing_points": missing_points,
        "critical_missing_points": critical_missing,
    }


def question_requires_example(question_item):
    merged = f"{question_item.get('question') or ''} {question_item.get('analysis') or ''}"
    return any(flag in merged for flag in EXAMPLE_HINTS)


def compute_structure_score(scoring_type, question_item, reference_points, user_answer, coverage_detail):
    normalized_text = str(user_answer or "")
    clauses = split_clauses(normalized_text)
    clause_count = len(clauses)
    order_marker_count = sum(1 for marker in ORDER_MARKERS if marker in normalized_text)
    logic_marker_count = sum(1 for marker in LOGIC_MARKERS if marker in normalized_text)
    numbered_step_count = len(NUMBERED_STEP_PATTERN.findall(normalized_text))
    example_present = any(flag in normalized_text for flag in EXAMPLE_HINTS)

    matched_count = len(coverage_detail.get("matched_points", []))
    required_example = question_requires_example(question_item)
    evidence_lines = [
        f"分句数：{clause_count}",
        f"顺序标记：{order_marker_count + numbered_step_count}",
    ]

    if scoring_type == "step":
        expected_steps = max(2, min(4, len(reference_points)))
        step_units = max(numbered_step_count, clause_count)
        completion_score = min(1.0, step_units / max(1, expected_steps))
        marker_score = 1.0 if (order_marker_count + numbered_step_count) >= 2 else (0.55 if step_units >= 2 else 0.2)
        logic_score = 1.0 if (logic_marker_count > 0 or "得到" in normalized_text or "=" in normalized_text) else 0.55
        structure_score = 0.45 * completion_score + 0.35 * marker_score + 0.20 * logic_score
        verdict = f"步骤结构 {step_units}/{expected_steps}，逻辑标记 {logic_marker_count}"
        flags = [] if structure_score >= 0.55 else ["missing_required_steps"]
    elif scoring_type == "comprehensive":
        expected_sections = max(2, min(4, len(reference_points)))
        section_score = min(1.0, clause_count / max(1, expected_sections))
        logic_score = 1.0 if (logic_marker_count > 0 or order_marker_count > 0) else 0.55
        breadth_score = min(1.0, matched_count / max(1, min(len(reference_points), expected_sections)))
        example_score = 1.0 if (not required_example or example_present) else 0.35
        structure_score = 0.35 * section_score + 0.30 * logic_score + 0.20 * breadth_score + 0.15 * example_score
        verdict = f"结构分段 {clause_count}/{expected_sections}，逻辑连接 {logic_marker_count}"
        flags = [] if structure_score >= 0.5 else ["weak_structure"]
        if required_example and not example_present:
            flags.append("missing_example")
    else:
        expected_clauses = 2 if len(reference_points) >= 2 or required_example else 1
        clause_score = min(1.0, clause_count / max(1, expected_clauses))
        focus_score = min(1.0, matched_count / max(1, min(2, len(reference_points) or 1)))
        example_score = 1.0 if (not required_example or example_present) else 0.35
        structure_score = 0.45 * clause_score + 0.35 * focus_score + 0.20 * example_score
        verdict = f"表述分句 {clause_count}/{expected_clauses}"
        flags = []
        if required_example and not example_present:
            flags.append("missing_example")

    if required_example:
        evidence_lines.append("已提供例子" if example_present else "缺少题目要求的例子/应用场景")
    evidence_lines.append(f"逻辑连接词：{logic_marker_count}")

    return {
        "score": clamp01(structure_score),
        "verdict": verdict,
        "evidence_lines": evidence_lines,
        "flags": flags,
        "signals": {
            "clause_count": clause_count,
            "order_marker_count": order_marker_count,
            "numbered_step_count": numbered_step_count,
            "logic_marker_count": logic_marker_count,
            "example_present": example_present,
        },
    }


def detect_copy_or_noise(scoring_type, expected_answer, analysis, user_answer):
    answer_core = normalize_core_text(expected_answer)
    analysis_core = normalize_core_text(analysis)
    user_core = normalize_core_text(user_answer)
    tokens = tokenize_text(user_answer)
    token_counter = Counter(tokens)
    unique_ratio = (len(set(tokens)) / len(tokens)) if tokens else 0.0
    max_repeat = max(token_counter.values()) if token_counter else 0

    reference_text = f"{answer_core}{analysis_core}"
    keyword_hits = sum(1 for token in tokens if token and token in reference_text)
    keyword_density = keyword_hits / max(1, len(tokens))
    has_structure_signal = any(marker in str(user_answer or "") for marker in ORDER_MARKERS + LOGIC_MARKERS + EXAMPLE_HINTS)

    copy_similarity = max(
        SequenceMatcher(None, user_core, answer_core).ratio() if user_core and answer_core else 0.0,
        SequenceMatcher(None, user_core, analysis_core).ratio() if user_core and analysis_core else 0.0,
    )
    answer_fragment = longest_common_size(user_core, answer_core)
    analysis_fragment = longest_common_size(user_core, analysis_core)
    longest_fragment = max(answer_fragment, analysis_fragment)
    ref_length = max(1, len(answer_core), len(analysis_core))

    flags = []
    evidence_lines = []
    anti_score = 1.0

    if scoring_type in {"term_definition", "step", "comprehensive"}:
        if user_core and ref_length >= 10 and (
            copy_similarity >= 0.9
            or (longest_fragment / ref_length) >= 0.65
            or (answer_core and answer_core == user_core)
        ):
            flags.append("verbatim_copy")
            anti_score -= 0.55
            evidence_lines.append("检测到与标准答案/解析高度重合的片段")

        if len(tokens) >= 6 and keyword_density >= 0.45 and not has_structure_signal and (unique_ratio < 0.82 or max_repeat >= 2):
            flags.append("keyword_stuffing")
            anti_score -= 0.45
            evidence_lines.append("答案更像关键词堆叠，缺少完整表述或逻辑连接")

        if len(tokens) >= 8 and unique_ratio < 0.45:
            flags.append("low_information_density")
            anti_score -= 0.25
            evidence_lines.append("重复词占比过高，信息密度偏低")

    if not evidence_lines:
        evidence_lines.append("未发现明显抄写或无意义堆词")

    return {
        "score": clamp01(anti_score),
        "verdict": "存在风险信号" if flags else "未发现明显风险",
        "evidence_lines": evidence_lines,
        "flags": flags,
        "signals": {
            "copy_similarity": safe_round(copy_similarity),
            "longest_fragment": int(longest_fragment),
            "keyword_density": safe_round(keyword_density),
            "unique_ratio": safe_round(unique_ratio),
            "max_repeat": int(max_repeat),
        },
    }


def subjective_config(scoring_type):
    if scoring_type == "step":
        return {
            "weights": {
                "normalization": 0.10,
                "coverage": 0.35,
                "structure": 0.35,
                "anti": 0.20,
            },
            "pass_threshold": 0.72,
        }
    if scoring_type == "comprehensive":
        return {
            "weights": {
                "normalization": 0.10,
                "coverage": 0.45,
                "structure": 0.25,
                "anti": 0.20,
            },
            "pass_threshold": 0.74,
        }
    return {
        "weights": {
            "normalization": 0.10,
            "coverage": 0.55,
            "structure": 0.15,
            "anti": 0.20,
        },
        "pass_threshold": 0.70,
    }


def evaluate_subjective_answer(scoring_type, question_item, expected_answer, user_answer, analysis):
    reference_points = split_reference_points(expected_answer, analysis)
    normalization_score, normalization_verdict, normalization_evidence = answer_normalization_score(user_answer)
    coverage_detail = evaluate_key_point_coverage(reference_points, user_answer)
    structure_detail = compute_structure_score(scoring_type, question_item, reference_points, user_answer, coverage_detail)
    anti_detail = detect_copy_or_noise(scoring_type, expected_answer, analysis, user_answer)

    config = subjective_config(scoring_type)
    weights = config["weights"]
    total_score = (
        normalization_score * weights["normalization"]
        + coverage_detail["score"] * weights["coverage"]
        + structure_detail["score"] * weights["structure"]
        + anti_detail["score"] * weights["anti"]
    )

    cap = 1.0
    gate_notes = []
    missing_points = coverage_detail["missing_points"]
    critical_missing = coverage_detail["critical_missing_points"]
    risk_flags = list(dict.fromkeys(
        anti_detail["flags"]
        + structure_detail["flags"]
    ))

    if critical_missing:
        cap = min(cap, 0.58)
        gate_notes.append(f"缺失关键点：{'、'.join(critical_missing[:2])}")
    elif len(missing_points) >= max(2, math.ceil(len(reference_points) / 2.0)) and reference_points:
        cap = min(cap, 0.59)
        gate_notes.append("关键点覆盖不足")

    if scoring_type == "step" and structure_detail["score"] < 0.55:
        cap = min(cap, 0.54)
        if "missing_required_steps" not in risk_flags:
            risk_flags.append("missing_required_steps")
        gate_notes.append("缺少必要步骤结构")

    if "keyword_stuffing" in anti_detail["flags"]:
        cap = min(cap, 0.45)
        gate_notes.append("存在关键词堆叠风险")

    if "verbatim_copy" in anti_detail["flags"] and structure_detail["score"] < 0.85:
        cap = min(cap, 0.59)
        gate_notes.append("与标准答案重合度过高，缺少自主组织")

    final_score = safe_round(min(total_score, cap))
    is_correct = final_score >= config["pass_threshold"]

    summary_parts = [
        f"关键点命中 {len(coverage_detail['matched_points'])}/{len(reference_points)}",
        f"结构得分 {safe_round(structure_detail['score'])}",
    ]
    if gate_notes:
        summary_parts.append("；".join(gate_notes[:2]))
    if not gate_notes and not risk_flags:
        summary_parts.append("整体作答较完整")
    summary = "，".join(summary_parts)

    if is_correct:
        feedback = f"回答基本达标。{summary}。"
    else:
        missing_text = "、".join(missing_points[:2]) if missing_points else "关键点和步骤组织"
        feedback = f"回答未达标。建议补充：{missing_text}。{summary}。"
    if analysis:
        feedback = f"{feedback}\n参考解析：{analysis}"

    breakdown = [
        build_breakdown_item(
            item="答案规范化",
            score=normalization_score,
            weight=weights["normalization"],
            verdict=normalization_verdict,
            evidence=normalization_evidence,
        ),
        build_breakdown_item(
            item="关键点覆盖",
            score=coverage_detail["score"],
            weight=weights["coverage"],
            verdict=coverage_detail["verdict"],
            evidence=coverage_detail["evidence_lines"],
        ),
        build_breakdown_item(
            item="步骤结构检查",
            score=structure_detail["score"],
            weight=weights["structure"],
            verdict=structure_detail["verdict"],
            evidence=structure_detail["evidence_lines"],
        ),
        build_breakdown_item(
            item="反抄写/堆词检测",
            score=anti_detail["score"],
            weight=weights["anti"],
            verdict=anti_detail["verdict"],
            evidence=anti_detail["evidence_lines"],
        ),
    ]

    return {
        "is_correct": is_correct,
        "score": final_score,
        "expected_answer": expected_answer,
        "feedback": feedback,
        "evaluation_method": f"rubric_{scoring_type}",
        "scoring_type": scoring_type,
        "breakdown": breakdown,
        "evidence": {
            "reference_points": [item["text"] for item in reference_points],
            "matched_key_points": coverage_detail["matched_points"],
            "missing_key_points": missing_points,
            "critical_missing_points": critical_missing,
            "structure_signals": structure_detail["signals"],
            "risk_flags": risk_flags,
            "gate_notes": gate_notes,
            "anti_copy_signals": anti_detail["signals"],
            "normalized_answer": normalize_text(user_answer),
        },
        "summary": summary,
    }


def evaluate_answer(question_item, user_answer):
    question_obj = question_item if isinstance(question_item, dict) else {}
    expected_answer = normalize_text(question_obj.get("answer") or "")
    analysis = normalize_text(question_obj.get("analysis") or "")
    user_text = normalize_text(user_answer or "")
    scoring_type = detect_question_family(question_obj)

    if scoring_type in {"single_choice", "multiple_choice"}:
        return evaluate_single_choice(expected_answer, user_text, analysis)
    if scoring_type == "fill_blank":
        return evaluate_fill_blank(expected_answer, user_text, analysis)
    return evaluate_subjective_answer(scoring_type, question_obj, expected_answer, user_text, analysis)
