import sys
import os

from backend.app.services.agent_service import TutorAgentService

text = """
# 分析

根据知识库：...

---

## 讲解
"""
print("OUTPUT: >>>>")
print(TutorAgentService._sanitize_user_visible_answer(text))
print("<<<<")
