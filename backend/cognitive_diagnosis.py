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
        error_type = self.classify_error(question, answer, user_answer)
        
        diagnosis = {
            "error_type": error_type,
            "category": self.map_to_category(error_type),
            "severity": self.assess_severity(question, user_answer),
            "recommendation": self.generate_recommendation(error_type)
        }
        
        return diagnosis
    
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