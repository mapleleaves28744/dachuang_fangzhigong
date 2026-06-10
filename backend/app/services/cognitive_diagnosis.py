from .mastery_engine import build_learning_advice, classify_error_by_rules


class CognitiveDiagnosis:
    def analyze_error(
        self,
        question,
        answer,
        user_answer,
        concept="",
        concept_mastery=None,
        response_time_seconds=None,
        attempt_count=None,
        history_records=None,
        standard_time_seconds=None,
    ):
        """基于可解释规则输出错误归因与学习建议。"""
        result = classify_error_by_rules(
            question=question,
            correct_answer=answer,
            user_answer=user_answer,
            concept_mastery=concept_mastery,
            response_time_seconds=response_time_seconds,
            attempt_count=attempt_count,
            history_records=history_records,
            standard_time_seconds=standard_time_seconds,
        )

        advice = build_learning_advice(
            error_type=result.get("error_type", "知识性错误"),
            mastery_score=concept_mastery,
            concept=concept,
            attempt_count=attempt_count,
        )

        severity = self.assess_severity(
            category=result.get("category", "knowledge"),
            concept_mastery=concept_mastery,
        )

        return {
            "error_type": result.get("error_type", "知识性错误"),
            "category": result.get("category", "knowledge"),
            "severity": severity,
            "recommendation": advice.get("建议", ""),
            "confidence": float(result.get("confidence", 0.5)),
            "signals": result.get("signals", []),
            "score_detail": result.get("score_detail", {}),
            "reason": advice.get("原因", ""),
            "recommended_actions": advice.get("推荐行动", []),
            "recent_accuracy": float(result.get("recent_accuracy", 0.0) or 0.0),
            "time_ratio": result.get("time_ratio"),
            "near_miss": bool(result.get("near_miss", False)),
        }

    @staticmethod
    def assess_severity(category, concept_mastery=None):
        try:
            mastery = None if concept_mastery is None else float(concept_mastery)
        except Exception:
            mastery = None

        if category == "knowledge" and (mastery is None or mastery < 0.4):
            return "high"
        if category == "habit" and mastery is not None and mastery >= 0.7:
            return "low"
        return "medium"
