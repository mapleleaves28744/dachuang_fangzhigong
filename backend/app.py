from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
from datetime import datetime, timedelta
import os
import uuid
import re
import base64
from knowledge_graph import KnowledgeGraph
from cognitive_diagnosis import CognitiveDiagnosis
from neo4j_store import Neo4jGraphStore
from celery_app import create_celery

try:
    from celery.result import AsyncResult
except Exception:
    AsyncResult = None

app = Flask(__name__)
CORS(app)  # 允许跨域请求


def load_simple_env_files():
    """读取本地 .env 文件（仅填充尚未设置的环境变量）。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, ".env"),
        os.path.join(os.path.dirname(base_dir), ".env"),
    ]

    for env_path in candidates:
        if not os.path.exists(env_path):
            continue

        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and not os.getenv(key):
                        os.environ[key] = value
        except Exception:
            # .env 加载失败时不影响服务启动
            continue


load_simple_env_files()

# ===== AI 配置（环境变量） =====
# 推荐：AI_PROVIDER=qwen
AI_PROVIDER = os.getenv("AI_PROVIDER", "qwen").lower()
USE_REAL_AI = os.getenv("USE_REAL_AI", "true").lower() == "true"

# Qwen (阿里云通义千问)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_API_URL = os.getenv(
    "QWEN_API_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")

# DeepSeek（保留兼容）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
# ===== 配置结束 =====

# OCR 配置
OCR_PROVIDER = os.getenv("OCR_PROVIDER", "mock").lower()  # mock|qwen_vl
QWEN_VL_MODEL_NAME = os.getenv("QWEN_VL_MODEL_NAME", "qwen-vl-plus")

# 异步任务配置
celery_client = create_celery()

# 学习计划存储（简化版，实际应该用数据库）
from database import (
    get_user_plans,
    set_user_plans,
    get_user_knowledge,
    set_user_knowledge,
    get_user_profile,
    set_user_profile,
)

# 初始化数据目录
def init_data():
    """初始化数据目录和文件"""
    os.makedirs("data", exist_ok=True)

init_data()
diagnosis_engine = CognitiveDiagnosis()
neo4j_store = Neo4jGraphStore()


# ===== 知识图谱初始化 =====

DEFAULT_CONCEPTS = [
    {
        "concept": "极限",
        "description": "函数在某点附近的变化趋势",
        "difficulty": 0.6,
        "prerequisites": []
    },
    {
        "concept": "函数",
        "description": "输入与输出的映射关系",
        "difficulty": 0.4,
        "prerequisites": []
    },
    {
        "concept": "导数",
        "description": "函数变化率的度量",
        "difficulty": 0.7,
        "prerequisites": ["极限", "函数"]
    },
    {
        "concept": "单调性",
        "description": "函数增减趋势判断",
        "difficulty": 0.65,
        "prerequisites": ["导数"]
    },
    {
        "concept": "极值",
        "description": "函数局部最大值和最小值",
        "difficulty": 0.75,
        "prerequisites": ["导数", "单调性"]
    },
    {
        "concept": "积分",
        "description": "面积累积与反导数",
        "difficulty": 0.8,
        "prerequisites": ["导数"]
    }
]


def build_knowledge_graph():
    """构建基础知识图谱"""
    kg = KnowledgeGraph()
    for item in DEFAULT_CONCEPTS:
        kg.add_concept(
            concept=item["concept"],
            description=item["description"],
            difficulty=item["difficulty"],
            prerequisites=item["prerequisites"]
        )
    return kg


def sync_user_mastery_to_graph(kg, user_id):
    """将用户知识文件中的掌握度同步到图谱内存结构"""
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concepts = user_knowledge.get("concepts", [])
    deleted_concepts = set(user_knowledge.get("deleted_concepts", []))

    # 先给默认概念注入一组可视化友好的初始掌握度
    for item in DEFAULT_CONCEPTS:
        if item["concept"] in deleted_concepts:
            continue
        score = max(0.2, min(0.95, 1.0 - item["difficulty"]))
        kg.update_mastery(user_id, item["concept"], score=score, confidence=0.7)

    for concept_item in concepts:
        concept_name = (concept_item.get("concept") or "").strip()
        mastery = concept_item.get("mastery", 0.3)
        # 过滤异常编码内容，避免出现 "??" 这类无意义节点
        if concept_name and concept_name != "??" and concept_name not in deleted_concepts:
            if concept_name not in kg.graph.nodes:
                kg.add_concept(
                    concept=concept_name,
                    description="用户新增知识点",
                    difficulty=0.5,
                    prerequisites=[]
                )
            kg.update_mastery(user_id, concept_name, score=float(mastery), confidence=0.85)

    for concept_name in deleted_concepts:
        if concept_name in kg.graph.nodes:
            kg.graph.remove_node(concept_name)


def to_graph_payload(kg, user_id):
    """将 networkx 图转换为前端可消费的 JSON 结构"""
    user_mastery = kg.user_mastery.get(user_id, {})

    nodes = []
    for concept, attrs in kg.graph.nodes(data=True):
        mastery_item = user_mastery.get(concept, {})
        nodes.append({
            "id": concept,
            "name": concept,
            "description": attrs.get("description", ""),
            "difficulty": attrs.get("difficulty", 0.5),
            "mastery": round(float(mastery_item.get("mastery", 0.2)), 3),
            "confidence": round(float(mastery_item.get("confidence", 0.6)), 3)
        })

    links = []
    for source, target in kg.graph.edges():
        links.append({
            "source": source,
            "target": target,
            "label": "前置"
        })

    return {
        "nodes": nodes,
        "links": links,
        "updated_at": datetime.now().isoformat()
    }


def normalize_user_knowledge(knowledge):
    """统一用户知识数据结构，兼容历史数据。"""
    if not isinstance(knowledge, dict):
        return {"concepts": [], "relations": [], "deleted_concepts": []}

    concepts = knowledge.get("concepts", [])
    relations = knowledge.get("relations", [])
    deleted_concepts = knowledge.get("deleted_concepts", [])

    if not isinstance(concepts, list):
        concepts = []
    if not isinstance(relations, list):
        relations = []
    if not isinstance(deleted_concepts, list):
        deleted_concepts = []

    for item in concepts:
        if isinstance(item, dict):
            item["concept"] = normalize_concept_name(item.get("concept"))

    deleted_concepts = [normalize_concept_name(c) for c in deleted_concepts if c]
    deleted_concepts = list(dict.fromkeys(deleted_concepts))

    knowledge["concepts"] = concepts
    knowledge["relations"] = relations
    knowledge["deleted_concepts"] = deleted_concepts
    return knowledge


def normalize_concept_name(concept):
    """修复可能出现的节点名乱码。"""
    text = (concept or "").strip()
    if not text:
        return ""

    default_names = {item["concept"] for item in DEFAULT_CONCEPTS}
    if text in default_names:
        return text

    for src_enc in ("gbk", "latin1"):
        try:
            repaired = text.encode(src_enc).decode("utf-8").strip()
            if repaired in default_names:
                return repaired
        except Exception:
            continue

    return text


def upsert_user_concept(concept_list, concept, mastery=0.35):
    """新增或更新用户知识点，返回是否新建。"""
    now = datetime.now().isoformat()
    for item in concept_list:
        if item.get("concept") == concept:
            item["mastery"] = max(float(item.get("mastery", 0.0)), float(mastery))
            item["last_seen"] = now
            return False

    concept_list.append({
        "concept": concept,
        "first_seen": now,
        "last_seen": now,
        "mastery": float(mastery),
        "review_count": 0,
        "last_reviewed": None
    })
    return True


def detect_concepts_from_text(text):
    """从文本中抽取知识点（规则版，可后续替换为NLP模型）。"""
    detected = []

    for item in DEFAULT_CONCEPTS:
        concept = item["concept"]
        if concept in text:
            detected.append(concept)

    if detected:
        return list(dict.fromkeys(detected))

    # 回退策略：从中文短语中提取候选词
    candidates = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    stopwords = {"这个", "那个", "我们", "你们", "他们", "学习", "知识", "内容", "问题", "方法", "如何", "什么", "为什么"}
    for word in candidates:
        if word not in stopwords and word not in detected:
            detected.append(word)
        if len(detected) >= 4:
            break

    return detected


def infer_relations_from_concepts(concepts):
    """根据概念列表推断知识关系。"""
    relation_set = set()

    concept_set = set(concepts)
    for item in DEFAULT_CONCEPTS:
        target = item["concept"]
        if target not in concept_set:
            continue
        for prereq in item.get("prerequisites", []):
            if prereq in concept_set:
                relation_set.add((prereq, target, "前置"))

    # 若没有命中默认关系，按文本顺序建立弱关联
    if not relation_set and len(concepts) > 1:
        for i in range(len(concepts) - 1):
            source = concepts[i]
            target = concepts[i + 1]
            if source != target:
                relation_set.add((source, target, "相关"))

    return [
        {"source": s, "target": t, "type": r}
        for s, t, r in sorted(relation_set)
    ]


def parse_datetime_safe(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def calc_review_interval_days(mastery, review_count):
    """基于掌握度和复习次数给出下次复习间隔。"""
    if mastery < 0.4:
        base = 1
    elif mastery < 0.7:
        base = 2
    else:
        base = 4
    bonus = min(int(review_count), 6)
    return min(14, base + bonus)


def load_user_event_list(user_id, suffix):
    """读取用户事件列表文件。"""
    file_path = f"data/{user_id}_{suffix}.json"
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_user_event_list(user_id, suffix, event_list):
    """保存用户事件列表文件。"""
    file_path = f"data/{user_id}_{suffix}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(event_list, f, ensure_ascii=False, indent=2)


def append_user_event(user_id, suffix, item):
    """向用户事件日志追加一条记录。"""
    events = load_user_event_list(user_id, suffix)
    events.append(item)
    save_user_event_list(user_id, suffix, events)


def extract_topics_from_text(text):
    """从文本提取主题标签。"""
    return detect_concepts_from_text(text or "")


def build_learning_profile(user_id):
    """基于用户行为日志构建学习画像。"""
    profile = get_user_profile(user_id) or {}
    content_logs = load_user_event_list(user_id, "content")
    qa_logs = load_user_event_list(user_id, "qa")
    knowledge = normalize_user_knowledge(get_user_knowledge(user_id))

    content_type_counter = {"note": 0, "link": 0, "image": 0, "qa": 0, "other": 0}
    hour_counter = {}
    interest_counter = {}

    for item in content_logs:
        content_type = item.get("content_type", "other")
        if content_type not in content_type_counter:
            content_type = "other"
        content_type_counter[content_type] += 1

        ts = parse_datetime_safe(item.get("timestamp"))
        if ts:
            hour_counter[ts.hour] = hour_counter.get(ts.hour, 0) + 1

        for topic in item.get("topics", []):
            interest_counter[topic] = interest_counter.get(topic, 0) + 1

    for item in knowledge.get("concepts", []):
        concept = item.get("concept")
        if concept:
            interest_counter[concept] = interest_counter.get(concept, 0) + 1

    visual_score = content_type_counter.get("image", 0) + content_type_counter.get("link", 0)
    auditory_score = max(0, len(qa_logs) // 3)
    kinesthetic_score = content_type_counter.get("qa", 0) + content_type_counter.get("note", 0)
    style_scores = {
        "visual": visual_score,
        "auditory": auditory_score,
        "kinesthetic": kinesthetic_score,
    }
    learning_style = max(style_scores, key=style_scores.get) if sum(style_scores.values()) > 0 else "visual"

    best_hour = max(hour_counter, key=hour_counter.get) if hour_counter else 15
    best_time_range = f"{best_hour:02d}:00-{(best_hour + 2) % 24:02d}:00"

    top_interests = sorted(interest_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    interests = [k for k, _ in top_interests] if top_interests else ["综合学习"]

    profile.update({
        "user_id": user_id,
        "updated_at": datetime.now().isoformat(),
        "learning_style": learning_style,
        "style_scores": style_scores,
        "interests": interests,
        "best_time_range": best_time_range,
        "focus_minutes": 45 if learning_style == "visual" else (35 if learning_style == "auditory" else 50),
        "content_type_counter": content_type_counter,
    })
    set_user_profile(user_id, profile)
    return profile


def build_recommendations(user_id, limit=6):
    """根据画像和薄弱点生成个性化推荐。"""
    profile = build_learning_profile(user_id)
    knowledge = normalize_user_knowledge(get_user_knowledge(user_id))

    weak_concepts = sorted(
        [c for c in knowledge.get("concepts", []) if float(c.get("mastery", 0)) < 0.6],
        key=lambda x: float(x.get("mastery", 0))
    )

    style = profile.get("learning_style", "visual")
    style_resource = {
        "visual": "图解微课",
        "auditory": "音频讲解",
        "kinesthetic": "互动练习",
    }

    items = []
    for concept in weak_concepts[:limit]:
        mastery = float(concept.get("mastery", 0.0))
        items.append({
            "concept": concept.get("concept", "未知知识点"),
            "mastery": mastery,
            "resource_type": style_resource.get(style, "图解微课"),
            "title": f"{concept.get('concept', '该知识点')} - {style_resource.get(style, '图解微课')}",
            "reason": f"掌握度仅 {int(mastery * 100)}%，建议优先巩固",
            "priority": round((1.0 - mastery) * 100, 2)
        })

    if not items:
        interests = profile.get("interests", ["综合学习"])
        for topic in interests[:limit]:
            items.append({
                "concept": topic,
                "mastery": 0.75,
                "resource_type": style_resource.get(style, "图解微课"),
                "title": f"{topic} - 进阶学习包",
                "reason": "保持优势，进行拓展学习",
                "priority": 20
            })

    return items[:limit]


def build_graph_response(user_id):
    """内部构建图谱响应对象。"""
    # 优先尝试从 Neo4j 读取
    neo4j_payload = neo4j_store.fetch_graph(user_id)
    if neo4j_payload and neo4j_payload.get("nodes"):
        return {
            "success": True,
            "user_id": user_id,
            "graph": neo4j_payload,
            "node_count": len(neo4j_payload.get("nodes", [])),
            "edge_count": len(neo4j_payload.get("links", [])),
            "storage": "neo4j",
        }

    kg = build_knowledge_graph()
    sync_user_mastery_to_graph(kg, user_id)
    payload = to_graph_payload(kg, user_id)

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    existing_links = {(l["source"], l["target"]) for l in payload["links"]}
    for rel in user_knowledge.get("relations", []):
        source = rel.get("source")
        target = rel.get("target")
        if not source or not target:
            continue
        if (source, target) in existing_links:
            continue
        payload["links"].append({
            "source": source,
            "target": target,
            "label": rel.get("type", "相关")
        })
        existing_links.add((source, target))

    return {
        "success": True,
        "user_id": user_id,
        "graph": payload,
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["links"]),
        "storage": "json",
    }


def build_review_reminders_response(user_id):
    """内部构建复习提醒响应对象。"""
    now = datetime.now()
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concept_list = user_knowledge.get("concepts", [])

    reminders = []
    for item in concept_list:
        concept = item.get("concept")
        if not concept:
            continue

        mastery = float(item.get("mastery", 0.0))
        review_count = int(item.get("review_count", 0))
        last_reviewed = parse_datetime_safe(item.get("last_reviewed"))
        first_seen = parse_datetime_safe(item.get("first_seen"))

        interval_days = calc_review_interval_days(mastery, review_count)
        ref_time = last_reviewed or first_seen or now
        next_review = ref_time + timedelta(days=interval_days)
        due = next_review <= now
        overdue_days = max(0, (now - next_review).days)
        priority = round((1.0 - mastery) * 100 + overdue_days * 5, 2)

        reminders.append({
            "concept": concept,
            "mastery": mastery,
            "review_count": review_count,
            "interval_days": interval_days,
            "next_review": next_review.isoformat(),
            "due": due,
            "overdue_days": overdue_days,
            "priority": priority
        })

    due_items = [r for r in reminders if r["due"]]
    due_items.sort(key=lambda x: (-x["priority"], x["mastery"]))
    upcoming = [r for r in reminders if not r["due"]]
    upcoming.sort(key=lambda x: x["next_review"])

    return {
        "success": True,
        "user_id": user_id,
        "generated_at": now.isoformat(),
        "due_count": len(due_items),
        "upcoming_count": len(upcoming),
        "due_items": due_items,
        "upcoming_items": upcoming[:8]
    }


def build_diagnosis_report_response(user_id):
    """内部构建诊断报告响应对象。"""
    items = load_user_event_list(user_id, "diagnosis")

    category_count = {"knowledge": 0, "skill": 0, "habit": 0, "unknown": 0}
    for item in items:
        category = item.get("diagnosis", {}).get("category", "unknown")
        category_count[category] = category_count.get(category, 0) + 1

    latest = items[-5:][::-1]
    return {
        "success": True,
        "user_id": user_id,
        "total": len(items),
        "category_count": category_count,
        "latest": latest
    }

# ===== 学习计划相关函数 =====

def get_user_plans_api(user_id):
    """获取指定用户的学习计划"""
    plans = get_user_plans(user_id)
    if not plans:
        # 初始化默认计划
        from datetime import datetime
        import uuid
        default_plans = [
            {
                "id": str(uuid.uuid4()),
                "time": "09:00",
                "task": "复习函数定义",
                "completed": False,
                "created_at": datetime.now().isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "time": "15:00",
                "task": "练习导数计算",
                "completed": False,
                "created_at": datetime.now().isoformat()
            }
        ]
        set_user_plans(user_id, default_plans)
        return default_plans
    return plans

def add_user_plan(user_id, time, task):
    """添加用户学习计划"""
    plans = get_user_plans(user_id)
    from datetime import datetime
    import uuid
    new_plan = {
        "id": str(uuid.uuid4()),
        "time": time,
        "task": task,
        "completed": False,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    plans.append(new_plan)
    set_user_plans(user_id, plans)
    return new_plan

def update_user_plan(user_id, plan_id, updates):
    """更新用户学习计划"""
    plans = get_user_plans(user_id)
    for i, plan in enumerate(plans):
        if plan["id"] == plan_id:
            plans[i].update(updates)
            plans[i]["updated_at"] = datetime.now().isoformat()
            set_user_plans(user_id, plans)
            return True
    return False

def delete_user_plan(user_id, plan_id):
    """删除用户学习计划"""
    plans = get_user_plans(user_id)
    new_plans = [p for p in plans if p["id"] != plan_id]
    if len(new_plans) != len(plans):
        set_user_plans(user_id, new_plans)
        return True
    return False

# ===== AI 相关函数 =====

def get_ai_runtime_config():
    """根据提供商返回运行时配置。"""
    provider = AI_PROVIDER

    if provider == "qwen":
        return {
            "provider": "qwen",
            "api_key": QWEN_API_KEY,
            "api_url": QWEN_API_URL,
            "model": QWEN_MODEL_NAME
        }

    return {
        "provider": "deepseek",
        "api_key": DEEPSEEK_API_KEY,
        "api_url": DEEPSEEK_API_URL,
        "model": DEEPSEEK_MODEL_NAME
    }


def analyze_with_ai(question):
    """调用大模型分析学习问题（支持 Qwen/DeepSeek）。"""
    try:
        cfg = get_ai_runtime_config()
        if not cfg["api_key"]:
            raise ValueError(f"未配置 {cfg['provider']} API Key")

        prompt = f"""
        你是一个智能学习伴侣，请分析用户的学习问题，提取以下信息：
        1. confusion_point: 用户困惑的知识点（如"极限定义"）
        2. interest_topic: 兴趣学科/主题（如"高等数学"）
        3. learning_preference: 学习偏好（如"喜欢图解"）
        
        用户问题：{question}
        
        请以严格的 JSON 格式返回，不要包含其他内容：
        {{
            "confusion_point": "...",
            "interest_topic": "...", 
            "learning_preference": "..."
        }}
        """
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}"
        }
        
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 500
        }
        
        response = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        if not content:
            raise ValueError("DeepSeek返回内容为空")
        
        try:
            analysis = json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                analysis = generate_mock_analysis(question)
        
        return analysis
        
    except Exception as e:
        print(f"AI分析调用失败: {e}")
        return generate_mock_analysis(question)

def generate_mock_analysis(question):
    """生成模拟分析"""
    if "数学" in question or "计算" in question:
        return {
            "confusion_point": "函数求导和极值判定",
            "interest_topic": "高等数学-微积分",
            "learning_preference": "需要更多图解和例题演示"
        }
    elif "物理" in question:
        return {
            "confusion_point": "牛顿运动定律的应用",
            "interest_topic": "经典力学",
            "learning_preference": "喜欢实验演示和物理模型"
        }
    elif "编程" in question or "代码" in question:
        return {
            "confusion_point": "算法逻辑和语法错误",
            "interest_topic": "计算机编程",
            "learning_preference": "喜欢动手实践和项目式学习"
        }
    else:
        return {
            "confusion_point": "核心概念理解",
            "interest_topic": "综合学习",
            "learning_preference": "视觉化学习和分步讲解"
        }

def ask_ai_question(question, user_id):
    """调用大模型进行智能问答（支持 Qwen/DeepSeek）。"""
    try:
        cfg = get_ai_runtime_config()
        if not cfg["api_key"]:
            raise ValueError(f"未配置 {cfg['provider']} API Key")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}"
        }
        
        prompt = f"""
        你是一个智能学习伴侣，请回答用户的学习问题。
        要求：
        1. 回答要专业、准确
        2. 语言要亲切、鼓励
        3. 如果问题不清晰，可以询问更多细节
        4. 适当提供学习建议
        
        用户问题：{question}
        """
        
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        response = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        if not answer:
            answer = "抱歉，我暂时无法回答这个问题。"
        
        return {
            "answer": answer,
            "ai_used": True,
            "provider": cfg["provider"],
            "error": ""
        }
        
    except Exception as e:
        print(f"AI问答失败: {e}")
        return {
            "answer": "这个问题涉及到多个知识点。根据我的分析，建议你从基础概念开始复习。如果你有更具体的问题，我可以更好地帮助你。",
            "ai_used": False,
            "provider": "fallback",
            "error": str(e)
        }


def extract_text_from_image(file_storage):
    """OCR：从图片中提取文本。支持 mock 与 qwen_vl。"""
    if not file_storage:
        return ""

    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

    if OCR_PROVIDER == "qwen_vl" and QWEN_API_KEY:
        try:
            ext = os.path.splitext(file_storage.filename or "")[1].lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            b64 = base64.b64encode(raw).decode("utf-8")
            data_url = f"data:{mime};base64,{b64}"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {QWEN_API_KEY}",
            }
            payload = {
                "model": QWEN_VL_MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请提取图片中的学习相关文字，只返回纯文本。"},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 800,
            }
            resp = requests.post(QWEN_API_URL, headers=headers, json=payload, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return (text or "").strip()
        except Exception as e:
            print(f"Qwen OCR失败: {e}")

    # mock 回退：保证功能可用
    return f"图片内容识别（模拟）：{file_storage.filename or '未命名图片'}，包含函数、导数、极值相关内容。"

# ===== 学习计划 API 接口 =====

@app.route('/api/plans', methods=['GET'])
def get_plans():
    """获取用户学习计划"""
    user_id = request.args.get('user_id', 'default_user')
    plans = get_user_plans(user_id)
    
    return jsonify({
        "success": True,
        "plans": plans,
        "count": len(plans)
    })

@app.route('/api/plans', methods=['POST'])
def add_plan():
    """添加新学习计划"""
    data = request.json
    user_id = data.get('user_id', 'default_user')
    time = data.get('time')
    task = data.get('task')
    
    if not time or not task:
        return jsonify({
            "success": False,
            "message": "时间和任务内容不能为空"
        }), 400
    
    new_plan = add_user_plan(user_id, time, task)
    
    return jsonify({
        "success": True,
        "message": "学习计划添加成功",
        "plan": new_plan
    })

@app.route('/api/plans/<plan_id>', methods=['PUT'])
def update_plan(plan_id):
    """更新学习计划（如打勾完成）"""
    data = request.json
    user_id = data.get('user_id', 'default_user')
    
    # 允许更新的字段
    updates = {}
    if 'completed' in data:
        updates['completed'] = data['completed']
    if 'time' in data:
        updates['time'] = data['time']
    if 'task' in data:
        updates['task'] = data['task']
    
    if not updates:
        return jsonify({
            "success": False,
            "message": "没有要更新的内容"
        }), 400
    
    success = update_user_plan(user_id, plan_id, updates)
    
    if success:
        return jsonify({
            "success": True,
            "message": "学习计划更新成功"
        })
    else:
        return jsonify({
            "success": False,
            "message": "计划不存在或更新失败"
        }), 404

@app.route('/api/plans/<plan_id>', methods=['DELETE'])
def delete_plan(plan_id):
    """删除学习计划"""
    data = request.json
    user_id = data.get('user_id', 'default_user')
    
    success = delete_user_plan(user_id, plan_id)
    
    if success:
        return jsonify({
            "success": True,
            "message": "学习计划删除成功"
        })
    else:
        return jsonify({
            "success": False,
            "message": "计划不存在或删除失败"
        }), 404

@app.route('/api/plans/clear', methods=['POST'])
def clear_completed_plans():
    """清空已完成的学习计划"""
    data = request.json
    user_id = data.get('user_id', 'default_user')
    
    plans = get_user_plans(user_id)

    # 保留未完成的任务
    incomplete_plans = [p for p in plans if not p.get('completed', False)]
    set_user_plans(user_id, incomplete_plans)
    
    return jsonify({
        "success": True,
        "message": "已完成计划已清空",
        "remaining_count": len(incomplete_plans)
    })

# ===== 原有 AI 问答接口 =====

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """分析学习问题"""
    data = request.json
    question = data.get('question', '').strip()
    user_id = data.get('user_id', 'default_user')
    
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    
    if USE_REAL_AI:
        analysis = analyze_with_ai(question)
    else:
        analysis = generate_mock_analysis(question)
    
    # 记录学习行为
    record_learning_behavior(user_id, question, analysis)
    
    return jsonify(analysis)

@app.route('/api/ask', methods=['POST'])
def ask_question():
    """智能问答"""
    data = request.json
    question = data.get('question', '').strip()
    user_id = data.get('user_id', 'default_user')
    
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    
    ai_used = False
    error_msg = ""
    source = "mock"
    if USE_REAL_AI:
        result = ask_ai_question(question, user_id)
        answer = result.get("answer", "")
        ai_used = bool(result.get("ai_used", False))
        source = result.get("provider", "fallback")
        if not ai_used:
            error_msg = result.get("error", "")
    else:
        answer = f"这个问题涉及到多个知识点。根据我的分析，{question} 的核心是理解基本概念。建议你查阅相关资料，多做练习。"
    
    # 记录问答行为
    record_qa_behavior(user_id, question, answer)
    
    return jsonify({
        "answer": answer,
        "source": source,
        "ai_used": ai_used,
        "error": error_msg
    })

@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    """上传学习图片并进行OCR解析。"""
    if 'image' not in request.files:
        return jsonify({"error": "没有上传图片"}), 400
    
    file = request.files['image']
    user_id = request.form.get('user_id', 'default_user')

    extracted_text = extract_text_from_image(file)
    extract_result = extract_knowledge_from_text_api_inner(user_id, extracted_text, "image_ocr")
    concepts = extract_result.get("detected_concepts", []) or ["函数图像", "数学公式", "几何图形"]

    append_user_event(user_id, "content", {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "content_type": "image",
        "title": file.filename or "学习图片",
        "content": extracted_text[:500],
        "source": "upload_image",
        "topics": concepts,
    })

    build_learning_profile(user_id)
    
    return jsonify({
        "message": "图片上传成功",
        "detected_concepts": concepts,
        "ocr_text": extracted_text,
        "analysis": "已完成OCR并更新知识图谱"
    })


# ===== 知识图谱 API 接口 =====

@app.route('/api/knowledge_graph', methods=['GET'])
def get_knowledge_graph_api():
    """获取用户知识图谱（节点/关系/掌握度）"""
    user_id = request.args.get('user_id', 'default_user')
    return jsonify(build_graph_response(user_id))


@app.route('/api/knowledge_graph/mastery', methods=['POST'])
def update_knowledge_mastery_api():
    """更新某个知识点掌握度"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    concept = normalize_concept_name(data.get('concept'))
    mastery = data.get('mastery', None)

    if not concept or mastery is None:
        return jsonify({
            "success": False,
            "message": "concept 和 mastery 不能为空"
        }), 400

    if concept == "??":
        return jsonify({
            "success": False,
            "message": "concept 编码异常，请使用页面操作或 UTF-8 请求"
        }), 400

    mastery = max(0.0, min(1.0, float(mastery)))

    user_knowledge = get_user_knowledge(user_id)
    user_knowledge = normalize_user_knowledge(user_knowledge)
    concept_list = user_knowledge.get("concepts", [])
    deleted_concepts = user_knowledge.get("deleted_concepts", [])

    matched = False
    for item in concept_list:
        if item.get("concept") == concept:
            item["mastery"] = mastery
            item["review_count"] = int(item.get("review_count", 0)) + 1
            item["last_reviewed"] = datetime.now().isoformat()
            matched = True
            break

    if not matched:
        concept_list.append({
            "concept": concept,
            "first_seen": datetime.now().isoformat(),
            "mastery": mastery,
            "review_count": 1,
            "last_reviewed": datetime.now().isoformat()
        })

    user_knowledge["concepts"] = concept_list
    user_knowledge["deleted_concepts"] = [c for c in deleted_concepts if c != concept]
    set_user_knowledge(user_id, user_knowledge)

    # 同步到 Neo4j（可选）
    review_count = 1
    last_reviewed = datetime.now().isoformat()
    for item in concept_list:
        if item.get("concept") == concept:
            review_count = int(item.get("review_count", 1))
            last_reviewed = item.get("last_reviewed") or last_reviewed
            break
    neo4j_store.update_mastery(
        user_id=user_id,
        concept=concept,
        mastery=mastery,
        review_count=review_count,
        last_reviewed=last_reviewed,
    )

    return jsonify({
        "success": True,
        "message": "掌握度更新成功",
        "concept": concept,
        "mastery": mastery
    })


@app.route('/api/knowledge_graph/node', methods=['DELETE'])
def delete_knowledge_node_api():
    """删除某个知识点节点（同时移除关联关系）。"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    concept = normalize_concept_name(data.get('concept'))

    if not concept:
        return jsonify({
            "success": False,
            "message": "concept 不能为空"
        }), 400

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concept_list = user_knowledge.get("concepts", [])
    relation_list = user_knowledge.get("relations", [])
    deleted_concepts = user_knowledge.get("deleted_concepts", [])

    before_concepts = len(concept_list)
    before_relations = len(relation_list)

    concept_list = [item for item in concept_list if item.get("concept") != concept]
    relation_list = [
        rel for rel in relation_list
        if rel.get("source") != concept and rel.get("target") != concept
    ]

    if concept not in deleted_concepts:
        deleted_concepts.append(concept)

    user_knowledge["concepts"] = concept_list
    user_knowledge["relations"] = relation_list
    user_knowledge["deleted_concepts"] = deleted_concepts
    set_user_knowledge(user_id, user_knowledge)

    neo4j_ok = neo4j_store.delete_concept(user_id=user_id, concept=concept)

    return jsonify({
        "success": True,
        "message": "节点删除成功",
        "concept": concept,
        "removed_concepts": before_concepts - len(concept_list),
        "removed_relations": before_relations - len(relation_list),
        "neo4j_synced": bool(neo4j_ok) if neo4j_store.enabled else False,
    })


@app.route('/api/knowledge_graph/path', methods=['GET'])
def get_learning_path_api():
    """获取从已掌握知识到目标知识点的学习路径"""
    user_id = request.args.get('user_id', 'default_user')
    target = request.args.get('target', '').strip()

    if not target:
        return jsonify({
            "success": False,
            "message": "target 参数不能为空"
        }), 400

    kg = build_knowledge_graph()
    sync_user_mastery_to_graph(kg, user_id)

    if target not in kg.graph.nodes:
        return jsonify({
            "success": False,
            "message": f"目标知识点不存在: {target}",
            "path": []
        }), 404

    path = kg.get_learning_path(user_id, target)
    return jsonify({
        "success": True,
        "user_id": user_id,
        "target": target,
        "path": path,
        "length": len(path)
    })


@app.route('/api/knowledge_graph/extract', methods=['POST'])
def extract_knowledge_from_text_api():
    """从文本抽取知识点并写入用户知识图谱。"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    text = (data.get('text') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not text:
        return jsonify({
            "success": False,
            "message": "text 不能为空"
        }), 400

    extract_result = extract_knowledge_from_text_api_inner(user_id, text, source)
    detected_concepts = extract_result.get("detected_concepts", [])
    relations = extract_result.get("relations", [])
    new_count = extract_result.get("new_concept_count", 0)

    return jsonify({
        "success": True,
        "message": "知识抽取成功",
        "user_id": user_id,
        "source": source,
        "detected_concepts": detected_concepts,
        "new_concept_count": new_count,
        "relations": relations
    })


@app.route('/api/review/reminders', methods=['GET'])
def get_review_reminders_api():
    """根据掌握度和复习记录返回复习提醒。"""
    user_id = request.args.get('user_id', 'default_user')
    return jsonify(build_review_reminders_response(user_id))


@app.route('/api/content/ingest', methods=['POST'])
def ingest_learning_content_api():
    """多源学习内容录入（笔记/链接/答题记录等）。"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    content_type = (data.get('content_type') or 'note').strip().lower()
    content = (data.get('content') or '').strip()
    title = (data.get('title') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not content:
        return jsonify({"success": False, "message": "content 不能为空"}), 400

    return jsonify(process_content_ingest_sync(user_id, content_type, content, title, source))


def extract_knowledge_from_text_api_inner(user_id, text, source):
    """内部复用：执行一次知识抽取并返回结果对象。"""
    detected_concepts = detect_concepts_from_text(text)
    relations = infer_relations_from_concepts(detected_concepts) if detected_concepts else []

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concept_list = user_knowledge["concepts"]
    relation_list = user_knowledge["relations"]
    deleted_concepts = user_knowledge.get("deleted_concepts", [])

    new_count = 0
    for concept in detected_concepts:
        if upsert_user_concept(concept_list, concept, mastery=0.35):
            new_count += 1
        deleted_concepts = [c for c in deleted_concepts if c != concept]

    existing_relation_keys = {
        (r.get("source"), r.get("target"), r.get("type"))
        for r in relation_list
    }
    for rel in relations:
        rel_key = (rel["source"], rel["target"], rel["type"])
        if rel_key not in existing_relation_keys:
            relation_list.append({
                "source": rel["source"],
                "target": rel["target"],
                "type": rel["type"],
                "source_text": text[:120],
                "created_at": datetime.now().isoformat(),
                "from": source
            })

    user_knowledge["concepts"] = concept_list
    user_knowledge["relations"] = relation_list
    user_knowledge["deleted_concepts"] = deleted_concepts
    set_user_knowledge(user_id, user_knowledge)

    # 同步到 Neo4j（可选）
    neo4j_store.upsert_user_graph(user_id, concept_list, relation_list)

    return {
        "detected_concepts": detected_concepts,
        "relations": relations,
        "new_concept_count": new_count,
    }


def process_content_ingest_sync(user_id, content_type, content, title, source):
    """同步处理内容录入，返回统一结果。"""
    topics = extract_topics_from_text(content)
    event = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "content_type": content_type,
        "title": title,
        "content": content[:500],
        "source": source,
        "topics": topics,
    }
    append_user_event(user_id, "content", event)

    extract_resp = extract_knowledge_from_text_api_inner(user_id, content, f"content_{content_type}")
    profile = build_learning_profile(user_id)

    return {
        "success": True,
        "message": "内容录入成功",
        "event": event,
        "knowledge_extract": extract_resp,
        "profile": profile,
    }


if celery_client:
    @celery_client.task(name="tasks.process_content_ingest")
    def process_content_ingest_task(payload):
        user_id = payload.get("user_id", "default_user")
        content_type = payload.get("content_type", "note")
        content = payload.get("content", "")
        title = payload.get("title", "")
        source = payload.get("source", "manual_async")
        return process_content_ingest_sync(user_id, content_type, content, title, source)


@app.route('/api/diagnosis/analyze', methods=['POST'])
def cognitive_diagnosis_api():
    """错题归因分析接口。"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    question = (data.get('question') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    user_answer = (data.get('user_answer') or '').strip()

    if not question or not correct_answer or not user_answer:
        return jsonify({
            "success": False,
            "message": "question、correct_answer、user_answer 不能为空"
        }), 400

    diagnosis = diagnosis_engine.analyze_error(question, correct_answer, user_answer)
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "correct_answer": correct_answer[:200],
        "user_answer": user_answer[:200],
        "diagnosis": diagnosis
    }
    append_user_event(user_id, "diagnosis", record)

    # 错题内容进入多源数据与图谱抽取
    append_user_event(user_id, "content", {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "content_type": "qa",
        "title": "错题记录",
        "content": question,
        "source": "diagnosis",
        "topics": extract_topics_from_text(question)
    })
    extract_knowledge_from_text_api_inner(user_id, question, "diagnosis")
    profile = build_learning_profile(user_id)

    return jsonify({
        "success": True,
        "diagnosis": diagnosis,
        "profile": profile
    })


@app.route('/api/content/ingest_async', methods=['POST'])
def ingest_learning_content_async_api():
    """异步内容录入接口（Celery）。"""
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    content_type = (data.get('content_type') or 'note').strip().lower()
    content = (data.get('content') or '').strip()
    title = (data.get('title') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not content:
        return jsonify({"success": False, "message": "content 不能为空"}), 400

    payload = {
        "user_id": user_id,
        "content_type": content_type,
        "content": content,
        "title": title,
        "source": source,
    }

    if celery_client and AsyncResult:
        async_result = process_content_ingest_task.delay(payload)
        return jsonify({
            "success": True,
            "mode": "async",
            "task_id": async_result.id,
            "status_url": f"/api/tasks/{async_result.id}",
        })

    # 无 Celery 时回退为同步
    result = process_content_ingest_sync(user_id, content_type, content, title, source)
    result["mode"] = "sync_fallback"
    return jsonify(result)


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status_api(task_id):
    """查询异步任务状态。"""
    if not (celery_client and AsyncResult):
        return jsonify({
            "success": False,
            "message": "Celery 未启用",
            "state": "UNAVAILABLE"
        }), 503

    result = AsyncResult(task_id, app=celery_client)
    payload = {
        "success": True,
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "SUCCESS":
        payload["result"] = result.result
    elif result.state == "FAILURE":
        payload["error"] = str(result.result)

    return jsonify(payload)


@app.route('/api/diagnosis/report', methods=['GET'])
def cognitive_diagnosis_report_api():
    """获取用户诊断统计报告。"""
    user_id = request.args.get('user_id', 'default_user')
    return jsonify(build_diagnosis_report_response(user_id))


@app.route('/api/profile', methods=['GET'])
def profile_api():
    """获取用户学习画像。"""
    user_id = request.args.get('user_id', 'default_user')
    profile = build_learning_profile(user_id)
    return jsonify({
        "success": True,
        "profile": profile
    })


@app.route('/api/recommendations', methods=['GET'])
def recommendations_api():
    """获取个性化学习资源推荐。"""
    user_id = request.args.get('user_id', 'default_user')
    limit = int(request.args.get('limit', 6))
    items = build_recommendations(user_id, limit=max(1, min(limit, 12)))
    return jsonify({
        "success": True,
        "user_id": user_id,
        "count": len(items),
        "items": items
    })


@app.route('/api/dashboard/summary', methods=['GET'])
def dashboard_summary_api():
    """仪表盘聚合数据接口。"""
    user_id = request.args.get('user_id', 'default_user')

    graph = build_graph_response(user_id)
    reminders = build_review_reminders_response(user_id)
    profile = build_learning_profile(user_id)
    diagnosis_report = build_diagnosis_report_response(user_id)
    recommendations = build_recommendations(user_id, limit=4)

    nodes = graph.get("graph", {}).get("nodes", [])
    overall_mastery = 0
    if nodes:
        overall_mastery = round(sum(float(n.get("mastery", 0)) for n in nodes) / len(nodes), 3)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "overall_mastery": overall_mastery,
        "graph": {
            "node_count": graph.get("node_count", 0),
            "edge_count": graph.get("edge_count", 0)
        },
        "review": {
            "due_count": reminders.get("due_count", 0),
            "upcoming_count": reminders.get("upcoming_count", 0)
        },
        "profile": profile,
        "diagnosis": diagnosis_report,
        "recommendations": recommendations
    })

# ===== 辅助函数 =====

def record_learning_behavior(user_id, question, analysis):
    """记录学习行为"""
    behavior = {
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "analysis": analysis,
        "type": "question_analysis"
    }
    
    data_file = f"data/{user_id}_behavior.json"
    
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except:
        data = []
    
    data.append(behavior)
    
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def record_qa_behavior(user_id, question, answer):
    """记录问答行为"""
    behavior = {
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer[:200],  # 只存储前200字符
        "type": "qa_interaction"
    }
    
    data_file = f"data/{user_id}_qa.json"
    
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except:
        data = []
    
    data.append(behavior)
    
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def update_user_knowledge(user_id, concepts):
    """更新用户知识图谱"""
    knowledge_file = f"data/{user_id}_knowledge.json"
    
    try:
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            knowledge = json.load(f)
    except:
        knowledge = {"concepts": []}
    
    for concept in concepts:
        if concept not in [c["concept"] for c in knowledge["concepts"]]:
            knowledge["concepts"].append({
                "concept": concept,
                "first_seen": datetime.now().isoformat(),
                "mastery": 0.3,
                "review_count": 0
            })
    
    with open(knowledge_file, 'w', encoding='utf-8') as f:
        json.dump(knowledge, f, ensure_ascii=False, indent=2)

@app.route('/health', methods=['GET'])
def health():
    """健康检查接口"""
    cfg = get_ai_runtime_config()
    neo4j_error = getattr(neo4j_store, "last_error", "")
    return jsonify({
        "status": "ok",
        "provider": cfg["provider"] if USE_REAL_AI else "mock",
        "model": cfg["model"] if USE_REAL_AI else "mock",
        "ai_key_configured": bool(cfg.get("api_key")),
        "ai_enabled": USE_REAL_AI,
        "ocr_provider": OCR_PROVIDER,
        "neo4j_enabled": neo4j_store.enabled,
        "neo4j_error": neo4j_error,
        "celery_enabled": celery_client is not None,
        "message": "智能学习伴侣服务运行正常"
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')