import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

class CognitiveDiagnosis:
    def __init__(self):
        self.error_categories = {
            "knowledge": ["概念混淆", "定义错误", "原理误解"],
            "skill": ["步骤缺失", "方法错误", "计算错误"],
            "habit": ["粗心大意", "格式错误", "单位错误"]
        }
        
    def analyze_error(self, question, answer, user_answer):
        """分析错误类型"""
        score_detail = self.score_error_categories(question, answer, user_answer)
        error_type = score_detail.get("error_type") or self.classify_error(question, answer, user_answer)
        confidence = float(score_detail.get("confidence", 0.5))
        
        diagnosis = {
            "error_type": error_type,
            "category": self.map_to_category(error_type),
            "severity": self.assess_severity(question, user_answer),
            "recommendation": self.generate_recommendation(error_type),
            "confidence": round(confidence, 3),
            "signals": score_detail.get("signals", []),
            "score_detail": score_detail.get("score_detail", {}),
        }
        
        return diagnosis

    def score_error_categories(self, question, correct_answer, user_answer):
        """基于关键词与答案差异进行可解释打分。"""
        q = (question or "").strip()
        c = (correct_answer or "").strip()
        u = (user_answer or "").strip()
        text = f"{q} {u}"

        score = {
            "knowledge": 0.0,
            "skill": 0.0,
            "habit": 0.0,
        }
        signals = []

        knowledge_words = ["概念", "定义", "原理", "理解", "混淆", "定理", "本质"]
        skill_words = ["步骤", "方法", "过程", "计算", "推导", "公式", "求解"]
        habit_words = ["粗心", "单位", "符号", "抄错", "看错", "漏写", "格式"]

        for w in knowledge_words:
            if w in text:
                score["knowledge"] += 1.2
                signals.append(f"命中知识信号:{w}")
        for w in skill_words:
            if w in text:
                score["skill"] += 1.1
                signals.append(f"命中技能信号:{w}")
        for w in habit_words:
            if w in text:
                score["habit"] += 1.0
                signals.append(f"命中习惯信号:{w}")

        # 答案过短时，通常偏向知识未掌握或习惯性漏写。
        if len(u) <= 2:
            score["knowledge"] += 0.6
            score["habit"] += 0.5
            signals.append("答案过短")

        # 与标准答案长度差异较大，偏向技能/步骤缺失。
        if c:
            ratio = len(u) / max(1, len(c))
            if ratio < 0.45:
                score["skill"] += 0.7
                signals.append("答案长度显著不足")

        top_category = max(score, key=score.get)
        sorted_scores = sorted(score.items(), key=lambda x: x[1], reverse=True)
        gap = sorted_scores[0][1] - sorted_scores[1][1]
        confidence = max(0.35, min(0.95, 0.55 + gap * 0.22))

        category_to_error = {
            "knowledge": "概念性错误",
            "skill": "程序性错误",
            "habit": "习惯性错误",
        }

        return {
            "error_type": category_to_error.get(top_category, "未知错误类型"),
            "confidence": confidence,
            "signals": signals[:8],
            "score_detail": {k: round(v, 3) for k, v in score.items()},
        }
    
    def classify_error(self, question, correct_answer, user_answer):
        """基于语义的错误分类"""
        # 使用简单规则（可替换为ML模型）
        keywords = {
            "忘记": "记忆性错误",
            "混淆": "概念性错误",
            "步骤": "程序性错误",
            "计算": "运算性错误",
            "粗心": "习惯性错误"
        }
        
        for keyword, error in keywords.items():
            if keyword in question or keyword in user_answer:
                return error
        
        return "未知错误类型"
    
    def map_to_category(self, error_type):
        """映射到大类（知识/技能/习惯）"""
        mapping = {
            "记忆性错误": "knowledge",
            "概念性错误": "knowledge", 
            "程序性错误": "skill",
            "运算性错误": "skill",
            "习惯性错误": "habit"
        }
        return mapping.get(error_type, "unknown")

    def assess_severity(self, question, user_answer):
        """评估错误严重程度。"""
        q_len = len((question or "").strip())
        a_len = len((user_answer or "").strip())

        if a_len <= 2:
            return "high"
        if a_len < max(6, q_len // 6):
            return "medium"
        return "low"

    def generate_recommendation(self, error_type):
        """根据错误类型生成干预建议。"""
        recommendations = {
            "记忆性错误": "建议使用间隔复习法，今天+明天+三天后各复习一次关键概念。",
            "概念性错误": "建议回到定义和典型例题，先用自己的话重述概念再做题。",
            "程序性错误": "建议拆解步骤，按“审题-建模-求解-检验”四步训练。",
            "运算性错误": "建议增加基础计算练习，并在草稿中保留中间过程。",
            "习惯性错误": "建议建立检查清单，提交前至少做一次单位与符号检查。",
            "未知错误类型": "建议先回顾相关知识点，再做2-3道同类题验证理解。"
        }
        return recommendations.get(error_type, recommendations["未知错误类型"])