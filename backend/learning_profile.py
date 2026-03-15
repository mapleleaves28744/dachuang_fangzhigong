from datetime import datetime

class LearningProfile:
    def __init__(self):
        self.profiles = {}
    
    def update_profile(self, user_id, behavior_data):
        """更新学习画像"""
        if user_id not in self.profiles:
            self.profiles[user_id] = {
                "learning_style": self.detect_learning_style(behavior_data),
                "preferences": {},
                "interests": set(),
                "behavior_stats": []
            }
        
        profile = self.profiles[user_id]
        
        # 检测学习风格
        profile["learning_style"] = self.detect_learning_style(behavior_data)
        
        # 更新兴趣
        if "content_topics" in behavior_data:
            profile["interests"].update(behavior_data["content_topics"])
        
        # 记录行为统计
        profile["behavior_stats"].append({
            "timestamp": datetime.now(),
            "duration": behavior_data.get("duration", 0),
            "content_type": behavior_data.get("content_type", "unknown"),
            "engagement": behavior_data.get("engagement", 0)
        })
    
    def detect_learning_style(self, behavior_data):
        """检测学习风格（视觉/听觉/动觉）"""
        style_scores = {"visual": 0, "auditory": 0, "kinesthetic": 0}
        
        # 基于内容类型偏好
        content_prefs = behavior_data.get("content_preferences", {})
        style_scores["visual"] += content_prefs.get("video", 0) + content_prefs.get("image", 0)
        style_scores["auditory"] += content_prefs.get("audio", 0) + content_prefs.get("lecture", 0)
        style_scores["kinesthetic"] += content_prefs.get("interactive", 0) + content_prefs.get("exercise", 0)
        
        return max(style_scores, key=style_scores.get)
    
    def get_recommendations(self, user_id):
        """获取内容推荐"""
        profile = self.profiles.get(user_id, {})
        style = profile.get("learning_style", "visual")
        
        recommendations = {
            "visual": ["视频讲解", "图解示例", "思维导图"],
            "auditory": ["音频讲解", "播客", "讨论课"],
            "kinesthetic": ["交互练习", "实验操作", "项目实践"]
        }
        
        return recommendations.get(style, [])