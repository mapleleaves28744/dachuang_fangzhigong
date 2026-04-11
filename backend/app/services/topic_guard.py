import json
import os
import re
from functools import lru_cache


SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SERVICE_DIR)
BACKEND_DIR = os.path.dirname(APP_DIR)
TOPIC_STOPWORDS_PATH = os.path.join(BACKEND_DIR, "data", "concept_stopwords.json")

ASCII_TOPIC_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-\+\.#]{1,30}$")

DEFAULT_TOPIC_STOPWORDS = {
    "学习",
    "知识",
    "内容",
    "问题",
    "方法",
    "建议",
    "技巧",
    "步骤",
    "能力",
    "提升",
    "任务",
    "课程",
    "目标",
    "方向",
    "理解",
    "掌握",
    "应用",
    "资料",
    "模型",
    "实践",
    "框架",
    "动态",
    "推荐",
    "老师",
    "伙伴",
    "同学",
    "自学",
    "零基础",
    "初学",
    "初学者",
    "新手",
    "小白",
    "入门",
    "进阶",
}

NOISE_EXACT_TOPICS = {
    "你好",
    "你好呀",
    "测试",
    "你是谁",
    "我是你爹吗",
    "推荐今日穿搭",
    "自学",
    "零基础",
}

NOISE_PREFIXES = (
    "你好",
    "请问",
    "我是",
    "你是",
    "谁是",
    "帮我",
    "告诉我",
    "推荐",
    "教我",
)

NOISE_SUBSTRINGS = (
    "很高兴",
    "看到这个问题",
    "我忍不住",
    "开始探索",
    "输入了",
    "随手测试",
    "网页开发的世界",
    "不要直接给出",
    "启发式提示",
    "今日穿搭",
)

NOISE_HINT_TOKENS = (
    "什么",
    "怎么",
    "哪几",
    "多少",
    "为何",
    "吗",
    "呢",
    "呀",
    "吧",
    "谁",
    "推荐",
    "解释",
    "告诉",
    "看到",
    "输入",
    "开始",
    "资料",
    "动态",
    "实践",
    "驱动",
    "框架",
    "穿搭",
)


@lru_cache(maxsize=1)
def load_topic_stopwords():
    stopwords = set(DEFAULT_TOPIC_STOPWORDS)
    if os.path.exists(TOPIC_STOPWORDS_PATH):
        try:
            with open(TOPIC_STOPWORDS_PATH, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            if isinstance(payload, dict):
                words = payload.get("words", [])
            elif isinstance(payload, list):
                words = payload
            else:
                words = []
            stopwords.update(str(item).strip() for item in words if str(item).strip())
        except Exception:
            pass
    return stopwords


def normalize_topic_text(value):
    return str(value or "").strip()


def is_learning_topic(value, extra_stopwords=None):
    topic = normalize_topic_text(value)
    if not topic:
        return False

    if len(topic) > 20:
        return False

    if ASCII_TOPIC_PATTERN.fullmatch(topic):
        return True

    if re.search(r"[，。！？,.!?：:；;、/\\\\]", topic):
        return False

    lowered = topic.lower()
    stopwords = set(load_topic_stopwords())
    if extra_stopwords:
        stopwords.update(str(item).strip() for item in extra_stopwords if str(item).strip())
    lowered_stopwords = {item.lower() for item in stopwords}

    if topic in stopwords or lowered in lowered_stopwords:
        return False
    if topic in NOISE_EXACT_TOPICS or lowered in {item.lower() for item in NOISE_EXACT_TOPICS}:
        return False
    if any(topic.startswith(prefix) for prefix in NOISE_PREFIXES):
        return False
    if any(fragment in topic for fragment in NOISE_SUBSTRINGS):
        return False

    if len(topic) >= 3 and any(pronoun in topic for pronoun in ("你", "我")):
        return False

    generic_hits = sum(1 for word in stopwords if word and word in topic)
    if generic_hits >= 2:
        return False

    if len(topic) >= 6 and any(token in topic for token in NOISE_HINT_TOKENS):
        return False

    if topic.endswith(("吗", "呢", "么", "呀", "吧")):
        return False

    return True


def filter_learning_topics(items, blocked_topics=None, limit=None):
    blocked = {
        normalize_topic_text(item)
        for item in (blocked_topics if isinstance(blocked_topics, (list, tuple, set)) else [])
        if normalize_topic_text(item)
    }
    filtered = []
    for item in items if isinstance(items, list) else []:
        topic = normalize_topic_text(item)
        if not topic or topic in blocked:
            continue
        if not is_learning_topic(topic):
            continue
        if topic in filtered:
            continue
        filtered.append(topic)
        if limit and len(filtered) >= int(limit):
            break
    return filtered
