import networkx as nx
import json
from datetime import datetime, timedelta

class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.user_mastery = {}  # 用户掌握程度
        
    def add_concept(self, concept, description, difficulty, prerequisites=None):
        """添加知识概念"""
        self.graph.add_node(concept, 
                           description=description,
                           difficulty=difficulty,
                           created_at=datetime.now())
        
        if prerequisites:
            for prereq in prerequisites:
                self.graph.add_edge(prereq, concept)
    
    def update_mastery(self, user_id, concept, score, confidence=1.0):
        """更新概念掌握程度（基于遗忘曲线）"""
        if user_id not in self.user_mastery:
            self.user_mastery[user_id] = {}
        
        prev_item = self.user_mastery[user_id].get(concept, 0)
        if isinstance(prev_item, dict):
            prev_mastery = float(prev_item.get("mastery", 0))
            last_reviewed = prev_item.get("last_reviewed")
        else:
            prev_mastery = float(prev_item)
            last_reviewed = None

        # 遗忘曲线计算：仅对历史记忆做衰减，不衰减当前新评分
        forgetting_rate = 0.08  # 每天遗忘率
        days_since_last = 1
        if isinstance(last_reviewed, datetime):
            delta = datetime.now() - last_reviewed
            days_since_last = max(1, delta.days)

        decayed_prev = prev_mastery * (1 - forgetting_rate) ** days_since_last
        score = max(0.0, min(1.0, float(score)))

        # 新评分代表最新测得掌握度
        new_mastery = max(decayed_prev, score)
        
        self.user_mastery[user_id][concept] = {
            "mastery": new_mastery,
            "confidence": confidence,
            "last_reviewed": datetime.now(),
            "next_review": self.calculate_next_review(new_mastery)
        }
    
    def calculate_next_review(self, mastery):
        """基于记忆强度计算下次复习时间"""
        intervals = [1, 2, 4, 7, 15, 30]  # 间隔天数
        idx = int(mastery * len(intervals))
        idx = min(idx, len(intervals) - 1)
        return datetime.now() + timedelta(days=intervals[idx])
    
    def get_learning_path(self, user_id, target_concept):
        """获取个性化学习路径"""
        try:
            # 找到从已知到目标的最短路径
            known_concepts = [c for c, data in self.user_mastery.get(user_id, {}).items() 
                            if data["mastery"] > 0.7]
            
            if not known_concepts:
                known_concepts = list(self.graph.nodes())[:3]  # 从基础开始
            
            paths = []
            for start in known_concepts:
                try:
                    path = nx.shortest_path(self.graph, start, target_concept)
                    paths.append(path)
                except:
                    continue
            
            return min(paths, key=len) if paths else []
        except:
            return []