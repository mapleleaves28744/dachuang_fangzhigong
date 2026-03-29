from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
from datetime import datetime, timedelta
from collections import deque
import os
import uuid
import re
import base64
import random
from knowledge_graph import KnowledgeGraph
from cognitive_diagnosis import CognitiveDiagnosis
from neo4j_store import Neo4jGraphStore
from celery_app import create_celery
from learning_profile import (
    build_learning_profile as build_learning_profile_core,
    build_recommendations as build_recommendations_core,
    build_recommendation_context,
)
import logging
import time

# 简单日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def try_delete_concept_with_retry(u_id, concept, attempts=3, base_delay=0.5):
    """模块级删除重试函数，供 sync 路径和 Celery 任务复用。"""
    for attempt in range(1, attempts + 1):
        try:
            ok = neo4j_store.delete_concept(user_id=u_id, concept=concept)
            if ok:
                logger.info("deleted concept '%s' for user %s (attempt %d)", concept, u_id, attempt)
                return True
            else:
                logger.warning("delete_concept returned False for %s (user=%s) on attempt %d", concept, u_id, attempt)
        except Exception as e:
            logger.exception("delete_concept exception for %s (user=%s) on attempt %d: %s", concept, u_id, attempt, e)

        if attempt < attempts:
            delay = base_delay * (2 ** (attempt - 1))
            time.sleep(delay)

    logger.error("failed to delete concept '%s' for user %s after %d attempts", concept, u_id, attempts)
    return False

try:
    from celery.result import AsyncResult
except ImportError:
    # Celery 5.x+ 或模块不存在时的兼容处理
    AsyncResult = None
except Exception:
    # 其他异常情况也设置为 None
    AsyncResult = None

app = Flask(__name__)
CORS(app)  # 允许跨域请求

TASK_META = {}
TASK_META_MAX_SIZE = 500
CELERY_WORKER_CACHE = {
    "checked_at": 0.0,
    "available": False,
}
CELERY_WORKER_CACHE_TTL = 2.0


def register_task_meta(task_id, task_type, user_id=None, extra=None):
    if not task_id:
        return

    TASK_META[task_id] = {
        "task_type": task_type,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "extra": extra or {},
    }

    # 控制内存大小，保留最新任务。
    if len(TASK_META) > TASK_META_MAX_SIZE:
        old_keys = sorted(TASK_META.keys(), key=lambda k: TASK_META[k].get("created_at", ""))[:50]
        for k in old_keys:
            TASK_META.pop(k, None)


def is_celery_worker_available(force=False):
    """检查 Celery worker 是否在线，避免任务提交后长期 PENDING。"""
    if not celery_client:
        return False

    now = time.time()
    if (not force) and (now - CELERY_WORKER_CACHE.get("checked_at", 0.0) <= CELERY_WORKER_CACHE_TTL):
        return bool(CELERY_WORKER_CACHE.get("available", False))

    available = False
    try:
        inspector = celery_client.control.inspect(timeout=0.6)
        ping_result = inspector.ping() if inspector else None
        available = bool(ping_result)
    except Exception:
        available = False

    CELERY_WORKER_CACHE["checked_at"] = now
    CELERY_WORKER_CACHE["available"] = available
    return available


def get_request_id():
    """获取或生成请求追踪ID。"""
    req_id = (request.headers.get("X-Request-Id", "") or "").strip()
    if req_id:
        return req_id

    req_id = (request.args.get("request_id", "") or "").strip()
    if req_id:
        return req_id

    body = request.get_json(silent=True) or {}
    req_id = str(body.get("request_id", "") or "").strip()
    if req_id:
        return req_id

    return str(uuid.uuid4())


def success_payload(request_id, message="", **data):
    payload = {
        "success": True,
        "request_id": request_id,
    }
    if message:
        payload["message"] = message
    payload.update(data)
    return payload


def error_response(request_id, status_code, error_code, error_message, **data):
    payload = {
        "success": False,
        "request_id": request_id,
        "error_code": error_code,
        "error_message": error_message,
        "message": error_message,
    }
    payload.update(data)
    return jsonify(payload), status_code


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
GRAPH_PRIMARY = os.getenv("GRAPH_PRIMARY", "auto").strip().lower()  # auto|neo4j|json
GRAPH_SYNC_MODE = os.getenv("GRAPH_SYNC_MODE", "auto").strip().lower()  # auto|sync|async
RELATION_MIN_SCORE = float(os.getenv("RELATION_MIN_SCORE", "0.45"))

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
    get_user_event_list as db_get_user_event_list,
    append_user_event as db_append_user_event,
    get_storage_info,
    init_storage,
    load_json,
    save_json,
)

# 初始化数据目录
def init_data():
    """初始化数据目录和文件"""
    os.makedirs("data", exist_ok=True)
    init_storage()

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

DEFAULT_CONCEPT_STOPWORDS = {
    "学习", "知识", "内容", "问题", "方法", "技巧", "步骤", "建议", "能力", "提升",
    "练习", "复习", "任务", "课程", "目标", "方向", "理解", "掌握", "应用",
    "这个", "那个", "我们", "你们", "他们", "如何", "什么", "为什么",
}


def get_configured_concept_stopwords():
    """获取可配置的概念黑名单（环境变量 + 本地文件）。"""
    stopwords = set(DEFAULT_CONCEPT_STOPWORDS)

    # 1) 环境变量：支持 JSON 数组或逗号分隔文本
    env_raw = (os.getenv("CONCEPT_STOPWORDS", "") or "").strip()
    if env_raw:
        parsed_words = []
        try:
            env_parsed = json.loads(env_raw)
            if isinstance(env_parsed, list):
                parsed_words = [str(x).strip() for x in env_parsed if str(x).strip()]
        except Exception:
            parsed_words = [w.strip() for w in env_raw.split(",") if w.strip()]

        stopwords.update(parsed_words)

    # 2) 本地文件：backend/data/concept_stopwords.json
    file_path = os.path.join("data", "concept_stopwords.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                stopwords.update(str(x).strip() for x in data if str(x).strip())
            elif isinstance(data, dict):
                words = data.get("words", [])
                if isinstance(words, list):
                    stopwords.update(str(x).strip() for x in words if str(x).strip())
        except Exception:
            pass

    return {w for w in stopwords if w}


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
            "label": "前置",
            "score": 0.8,
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

    normalized_relations = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        source = normalize_concept_name(rel.get("source") or "")
        target = normalize_concept_name(rel.get("target") or "")
        if not source or not target or source == target:
            continue
        rel_type = (rel.get("type") or "相关").strip() or "相关"
        try:
            score = float(rel.get("score", 0.6))
        except Exception:
            score = 0.6
        score = round(max(0.0, min(1.0, score)), 3)
        normalized_relations.append({
            "source": source,
            "target": target,
            "type": rel_type,
            "score": score,
            "evidence": (rel.get("evidence") or "").strip(),
            "source_text": rel.get("source_text", ""),
            "created_at": rel.get("created_at"),
            "from": rel.get("from"),
        })

    deleted_concepts = [normalize_concept_name(c) for c in deleted_concepts if c]
    deleted_concepts = list(dict.fromkeys(deleted_concepts))

    knowledge["concepts"] = concepts
    knowledge["relations"] = normalized_relations
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
    """从文本中抽取知识点（规则兜底）。"""
    detected = []

    for item in DEFAULT_CONCEPTS:
        concept = item["concept"]
        if concept in text:
            detected.append(concept)

    if detected:
        return list(dict.fromkeys(detected))

    # 回退策略：从中文短语中提取候选词
    candidates = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    stopwords = get_configured_concept_stopwords()
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
                relation_set.add((prereq, target, "前置", 0.85, "命中默认先修关系"))

    # 若没有命中默认关系，按文本顺序建立弱关联
    if not relation_set and len(concepts) > 1:
        for i in range(len(concepts) - 1):
            source = concepts[i]
            target = concepts[i + 1]
            if source != target:
                relation_set.add((source, target, "相关", 0.52, "文本顺序弱关联"))

    return [
        {"source": s, "target": t, "type": r, "score": sc, "evidence": ev}
        for s, t, r, sc, ev in sorted(relation_set)
    ]


def parse_datetime_safe(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _build_learning_path_adjacency(user_knowledge):
    """构建学习路径有向图：先修 -> 目标。"""
    adjacency = {}

    for item in DEFAULT_CONCEPTS:
        target = (item.get("concept") or "").strip()
        if not target:
            continue
        adjacency.setdefault(target, set())
        for prereq in item.get("prerequisites", []) or []:
            source = (prereq or "").strip()
            if not source or source == target:
                continue
            adjacency.setdefault(source, set()).add(target)

    relations = (user_knowledge or {}).get("relations", []) if isinstance(user_knowledge, dict) else []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        source = (rel.get("source") or "").strip()
        target = (rel.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set())

    return adjacency


def _find_learning_path_bfs(starts, target, adjacency, max_depth=8):
    """从多个起点到目标做 BFS，返回最短路径。"""
    target_text = (target or "").strip()
    if not target_text:
        return []

    valid_starts = [s for s in (starts or []) if s and s != target_text]
    if not valid_starts:
        return []

    queue = deque()
    seen = set()
    for s in valid_starts:
        queue.append((s, [s], 0))
        seen.add(s)

    while queue:
        node, path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for nxt in adjacency.get(node, set()):
            if not nxt:
                continue
            next_path = path + [nxt]
            if nxt == target_text:
                return next_path
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append((nxt, next_path, depth + 1))

    return []


def _infer_default_target_chain(target, max_depth=8):
    """无可达起点时，按默认先修关系生成到目标的兜底链路。"""
    target_text = (target or "").strip()
    if not target_text:
        return []

    chain = []
    cur = target_text
    depth = 0
    while cur and depth < max_depth:
        chain.append(cur)
        prereqs = DEFAULT_PREREQ_MAP.get(cur, [])
        if not prereqs:
            break
        cur = (prereqs[0] or "").strip()
        if not cur or cur in chain:
            break
        depth += 1

    chain.reverse()
    return chain if chain and chain[-1] == target_text else []


def infer_learning_path_with_fallback(user_id, target):
    """学习路径兜底：掌握点可达优先，其次默认先修链。"""
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concepts = user_knowledge.get("concepts", []) if isinstance(user_knowledge, dict) else []

    mastered = []
    for item in concepts:
        if not isinstance(item, dict):
            continue
        concept = (item.get("concept") or "").strip()
        if not concept:
            continue
        mastery = float(item.get("mastery", 0.0) or 0.0)
        if mastery >= 0.7:
            mastered.append(concept)

    adjacency = _build_learning_path_adjacency(user_knowledge)
    bfs_path = _find_learning_path_bfs(mastered, target, adjacency, max_depth=8)
    if bfs_path:
        return bfs_path

    default_chain = _infer_default_target_chain(target, max_depth=8)
    if default_chain:
        return default_chain

    return []


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
    """读取用户事件列表。"""
    data = db_get_user_event_list(user_id, suffix)
    return data if isinstance(data, list) else []


def save_user_event_list(user_id, suffix, event_list):
    """兼容旧调用：批量覆盖事件列表。"""
    existing = load_user_event_list(user_id, suffix)
    target = event_list if isinstance(event_list, list) else []

    # 仅追加差集，避免破坏 SQL 后端的事件流水语义。
    for item in target[len(existing):]:
        db_append_user_event(user_id, suffix, item)


def append_user_event(user_id, suffix, item):
    """向用户事件日志追加一条记录。"""
    db_append_user_event(user_id, suffix, item)


def extract_topics_from_text(text):
    """从文本提取主题标签。"""
    source_text = (text or "").strip()
    if not source_text:
        return []

    ai_extract = extract_knowledge_with_ai(source_text)
    ai_concepts = ai_extract.get("concepts", []) if isinstance(ai_extract, dict) else []
    if ai_concepts:
        return ai_concepts[:6]

    return detect_concepts_from_text(source_text)


def build_learning_profile(user_id):
    """画像构建入口：统一委托给 learning_profile.py 实现。"""
    return build_learning_profile_core(
        user_id=user_id,
        get_user_profile=get_user_profile,
        set_user_profile=set_user_profile,
        load_user_event_list=load_user_event_list,
        get_user_knowledge=get_user_knowledge,
        normalize_user_knowledge=normalize_user_knowledge,
    )


def build_recommendations(user_id, limit=6):
    """推荐构建入口：统一委托给 learning_profile.py 实现。"""
    return build_recommendations_core(
        user_id=user_id,
        limit=limit,
        build_learning_profile_fn=build_learning_profile,
        get_user_knowledge=get_user_knowledge,
        normalize_user_knowledge=normalize_user_knowledge,
        load_user_event_list=load_user_event_list,
    )


def build_graph_response(user_id, min_relation_score=None):
    """内部构建图谱响应对象。"""
    threshold = RELATION_MIN_SCORE if min_relation_score is None else float(min_relation_score)
    threshold = max(0.0, min(1.0, threshold))

    prefer_neo4j = GRAPH_PRIMARY in {"auto", "neo4j"}
    if prefer_neo4j and neo4j_store.enabled:
        neo4j_payload = neo4j_store.fetch_graph(user_id)
        if neo4j_payload is not None:
            for link in neo4j_payload.get("links", []) or []:
                if isinstance(link, dict) and "score" not in link:
                    link["score"] = 0.7
            neo4j_payload["links"] = [
                l for l in (neo4j_payload.get("links", []) or [])
                if float((l or {}).get("score", 0.0) or 0.0) >= threshold
            ]
            # auto 模式仅在 Neo4j 有用户图数据时返回；neo4j 模式直接返回。
            if GRAPH_PRIMARY == "neo4j" or neo4j_payload.get("nodes"):
                return {
                    "success": True,
                    "user_id": user_id,
                    "graph": neo4j_payload,
                    "node_count": len(neo4j_payload.get("nodes", [])),
                    "edge_count": len(neo4j_payload.get("links", [])),
                    "storage": "neo4j",
                    "graph_primary": GRAPH_PRIMARY,
                    "min_relation_score": threshold,
                }

    kg = build_knowledge_graph()
    sync_user_mastery_to_graph(kg, user_id)
    payload = to_graph_payload(kg, user_id)

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    existing_links = {(l["source"], l["target"]) for l in payload["links"]}
    for rel in user_knowledge.get("relations", []):
        source = rel.get("source")
        target = rel.get("target")
        score = float(rel.get("score", 0.6) or 0.6)
        if not source or not target:
            continue
        if score < threshold:
            continue
        if (source, target) in existing_links:
            continue
        payload["links"].append({
            "source": source,
            "target": target,
            "label": rel.get("type", "相关"),
            "score": round(score, 3),
        })
        existing_links.add((source, target))

    return {
        "success": True,
        "user_id": user_id,
        "graph": payload,
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["links"]),
        "storage": "json",
        "graph_primary": GRAPH_PRIMARY,
        "min_relation_score": threshold,
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
            return {
                "success": False,
                "analysis": {},
                "ai_used": False,
                "provider": cfg["provider"],
                "error_code": "AI_KEY_MISSING",
                "error_message": f"未配置 {cfg['provider']} API Key",
            }

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
                return {
                    "success": False,
                    "analysis": {},
                    "ai_used": False,
                    "provider": cfg["provider"],
                    "error_code": "AI_BAD_RESPONSE",
                    "error_message": "模型返回内容不是合法JSON",
                }
        
        return {
            "success": True,
            "analysis": analysis,
            "ai_used": True,
            "provider": cfg["provider"],
            "error_code": "",
            "error_message": "",
        }
        
    except Exception as e:
        print(f"AI分析调用失败: {e}")
        cfg = get_ai_runtime_config()
        return {
            "success": False,
            "analysis": {},
            "ai_used": False,
            "provider": cfg["provider"],
            "error_code": "AI_UPSTREAM_ERROR",
            "error_message": str(e),
        }


def parse_json_from_ai_text(content):
    """从模型文本中提取 JSON 对象。"""
    text = (content or "").strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    # 兼容 ```json ... ``` 包裹或额外解释文本。
    code_block_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except Exception:
            pass

    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except Exception:
            return None
    return None


def normalize_ai_concepts(raw_concepts, max_count=8):
    """规范化 AI 返回的概念列表。"""
    generic_words = get_configured_concept_stopwords()
    generic_words_lower = {w.lower() for w in generic_words}

    def is_valid_concept(name):
        n = (name or "").strip()
        if not n:
            return False

        # 过滤过于泛化的词和动词短语
        if n in generic_words or n.lower() in generic_words_lower:
            return False
        if n.startswith("学习") or n.endswith("学习"):
            return False
        if n.startswith("我要") or n.startswith("想"):
            return False

        # 中文概念长度控制
        has_cn = bool(re.search(r"[\u4e00-\u9fff]", n))
        if has_cn and len(n) < 2:
            return False

        # 英文概念长度与字符过滤（如 Python / NumPy）
        has_en = bool(re.search(r"[A-Za-z]", n))
        if has_en and not re.match(r"^[A-Za-z][A-Za-z0-9_\-\+\.]{1,30}$", n):
            return False

        return True

    concepts = []
    if not isinstance(raw_concepts, list):
        return concepts

    for item in raw_concepts:
        if isinstance(item, str):
            name = normalize_concept_name(item)
        elif isinstance(item, dict):
            name = normalize_concept_name(item.get("concept") or item.get("name") or "")
        else:
            name = ""

        if not name:
            continue
        if len(name) > 20:
            name = name[:20].strip()
        if not is_valid_concept(name):
            continue
        if name and name not in concepts:
            concepts.append(name)
        if len(concepts) >= max_count:
            break

    return concepts


def normalize_ai_relations(raw_relations, allowed_concepts, extracted_concepts=None):
    """规范化 AI 返回的关系列表，并过滤非法引用。"""
    if not isinstance(raw_relations, list):
        return []

    valid_types = {"前置", "相关", "并列", "因果"}
    default_type_score = {"前置": 0.78, "因果": 0.72, "并列": 0.66, "相关": 0.58}
    allowed_set = set(allowed_concepts or [])
    extracted_set = set(extracted_concepts or [])
    seen = set()
    result = []

    for rel in raw_relations:
        if not isinstance(rel, dict):
            continue
        source = normalize_concept_name(rel.get("source") or "")
        target = normalize_concept_name(rel.get("target") or "")
        relation_type = (rel.get("type") or "相关").strip()

        if relation_type not in valid_types:
            relation_type = "相关"
        if not source or not target or source == target:
            continue
        if source not in allowed_set or target not in allowed_set:
            continue
        # 至少一个端点应为本次抽取知识点，避免“已有节点之间”被无依据重连。
        if extracted_set and (source not in extracted_set and target not in extracted_set):
            continue

        raw_score = rel.get("score", rel.get("confidence", default_type_score.get(relation_type, 0.58)))
        try:
            score = float(raw_score)
        except Exception:
            score = default_type_score.get(relation_type, 0.58)
        score = round(max(0.0, min(1.0, score)), 3)
        evidence = (rel.get("evidence") or rel.get("reason") or "").strip()

        key = (source, target, relation_type)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "source": source,
            "target": target,
            "type": relation_type,
            "score": score,
            "evidence": evidence,
        })

    return result


def build_default_prereq_map():
    prereq_map = {}
    for item in DEFAULT_CONCEPTS:
        c = item.get("concept")
        if not c:
            continue
        prereq_map[c] = list(item.get("prerequisites", []) or [])
    return prereq_map


DEFAULT_PREREQ_MAP = build_default_prereq_map()


def select_context_concepts_for_relation(user_knowledge, text, detected_hints=None, limit=24):
    """为关系推理挑选“当前图谱”中最相关的候选概念。"""
    source_text = (text or "").strip()
    text_lower = source_text.lower()
    detected_hints = [normalize_concept_name(x) for x in (detected_hints or []) if x]

    pool = set()
    for item in (user_knowledge or {}).get("concepts", []):
        c = normalize_concept_name(item.get("concept") if isinstance(item, dict) else "")
        if c:
            pool.add(c)
    for item in DEFAULT_CONCEPTS:
        c = normalize_concept_name(item.get("concept"))
        if c:
            pool.add(c)

    scored = []
    for concept in pool:
        score = 0.0
        c_lower = concept.lower()
        if concept in source_text or c_lower in text_lower:
            score += 5.0

        # 简单字符重叠度，辅助中文短句匹配。
        cn_chars = set(re.findall(r"[\u4e00-\u9fff]", concept))
        text_chars = set(re.findall(r"[\u4e00-\u9fff]", source_text))
        overlap = len(cn_chars & text_chars)
        if overlap >= 1:
            score += min(2.5, overlap * 0.7)

        # 与已检测概念有先修关联时加分。
        for d in detected_hints:
            if concept in DEFAULT_PREREQ_MAP.get(d, []):
                score += 2.0
            if d in DEFAULT_PREREQ_MAP.get(concept, []):
                score += 2.0

        if score > 0:
            scored.append((concept, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    picked = [c for c, _ in scored[:limit]]

    # 若文本命中较少，保留少量用户已有概念作为上下文兜底。
    if len(picked) < min(6, limit):
        for item in (user_knowledge or {}).get("concepts", [])[:limit]:
            c = normalize_concept_name(item.get("concept") if isinstance(item, dict) else "")
            if c and c not in picked:
                picked.append(c)
            if len(picked) >= limit:
                break

    return picked[:limit]


def infer_relations_with_existing_context(detected_concepts, context_concepts):
    """规则兜底：推断新概念与现有图谱概念关系（非无脑串联）。"""
    detected = [normalize_concept_name(x) for x in (detected_concepts or []) if x]
    context = [normalize_concept_name(x) for x in (context_concepts or []) if x]
    context_set = set(context)
    relations = set()

    for d in detected:
        for p in DEFAULT_PREREQ_MAP.get(d, []):
            if p in context_set:
                relations.add((p, d, "前置", 0.8, "命中默认先修关系"))
        for c in context:
            if d in DEFAULT_PREREQ_MAP.get(c, []):
                relations.add((d, c, "前置", 0.8, "命中默认先修关系"))

    return [
        {"source": s, "target": t, "type": r, "score": sc, "evidence": ev}
        for s, t, r, sc, ev in sorted(relations)
    ]


def extract_knowledge_with_ai(text, context_concepts=None, max_concepts=8):
    """AI 主导知识抽取：输出结构化 concepts/relations。"""
    source_text = (text or "").strip()
    if not source_text:
        return {"concepts": [], "relations": [], "ai_used": False, "provider": "none", "error": "empty_text"}

    if not USE_REAL_AI:
        return {"concepts": [], "relations": [], "ai_used": False, "provider": "mock", "error": "ai_disabled"}

    cfg = get_ai_runtime_config()
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {"concepts": [], "relations": [], "ai_used": False, "provider": cfg.get("provider", "unknown"), "error": "missing_api_key"}

    try:
        context_concepts = [normalize_concept_name(x) for x in (context_concepts or []) if x]
        context_concepts = list(dict.fromkeys([x for x in context_concepts if x]))[:24]
        context_text = "、".join(context_concepts) if context_concepts else "无"

        prompt = f"""
你是学习内容知识抽取器。请结合当前知识图谱候选节点，从文本中抽取“学习相关知识点”和“知识关系”，并只返回 JSON。

要求：
1) concepts: 只保留学习相关概念，2-12个字，去重，最多{max_concepts}个。
    禁止把“学习/知识/问题/方法/建议”等泛词当作概念。
2) relations: 关系允许来自以下节点集合：
   A. 本次抽取 concepts
   B. 当前图谱候选节点（见下方 context_concepts）
   但每条关系至少有一个端点必须来自本次抽取 concepts。
3) type 仅可为 前置/相关/并列/因果；没有证据时不要强行连边。
4) 每条 relation 增加 score（0~1）与 evidence（不超过20字）。
5) 若文本信息不足，relations 可为空数组。
6) 严禁输出解释文字，只输出一个 JSON 对象。

输出格式：
{{
  "concepts": ["概念1", "概念2"],
    "relations": [{{"source": "概念1", "target": "概念2", "type": "前置", "score": 0.82, "evidence": "定义依赖"}}]
}}

待抽取文本：
{source_text}

当前图谱候选节点（可用于跨图谱关系推理）：
{context_text}
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": cfg.get("model", "qwen-plus"),
            "messages": [
                {"role": "system", "content": "你是结构化信息抽取助手，必须输出合法JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 900,
        }

        resp = requests.post(cfg.get("api_url"), headers=headers, json=payload, timeout=35)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        parsed = parse_json_from_ai_text(content)
        if not isinstance(parsed, dict):
            return {
                "concepts": [],
                "relations": [],
                "ai_used": False,
                "provider": cfg.get("provider", "unknown"),
                "error": "invalid_ai_json",
            }

        concepts = normalize_ai_concepts(parsed.get("concepts", []), max_count=max_concepts)
        allowed_concepts = list(dict.fromkeys(concepts + context_concepts))
        relations = normalize_ai_relations(
            parsed.get("relations", []),
            allowed_concepts=allowed_concepts,
            extracted_concepts=concepts,
        )

        return {
            "concepts": concepts,
            "relations": relations,
            "ai_used": True,
            "provider": cfg.get("provider", "unknown"),
            "error": "",
        }
    except Exception as e:
        return {
            "concepts": [],
            "relations": [],
            "ai_used": False,
            "provider": cfg.get("provider", "unknown"),
            "error": str(e),
        }

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


QUESTION_BANK_TEMPLATES = [
    {
        "id": "qb-seed-derivative-001",
        "concept": "导数",
        "difficulty": "easy",
        "question_type": "single_choice",
        "question": "函数 f(x)=x^2 的导数是？",
        "options": ["A. x", "B. 2x", "C. x^2", "D. 2"],
        "answer": "B",
        "analysis": "幂函数求导： (x^n)' = nx^(n-1)。",
        "created_by": "system",
        "is_public": True,
        "bank_source": "seed_template",
    },
    {
        "id": "qb-seed-limit-001",
        "concept": "极限",
        "difficulty": "easy",
        "question_type": "short_answer",
        "question": "请简述“函数极限”描述的核心含义。",
        "options": [],
        "answer": "自变量趋近某值时，函数值的变化趋势。",
        "analysis": "极限强调的是趋近过程，不一定要求该点函数值存在。",
        "created_by": "system",
        "is_public": True,
        "bank_source": "seed_template",
    },
    {
        "id": "qb-seed-integral-001",
        "concept": "积分",
        "difficulty": "medium",
        "question_type": "single_choice",
        "question": "定积分最典型的应用之一是？",
        "options": ["A. 求切线斜率", "B. 求面积累积", "C. 求方程根", "D. 求函数奇偶性"],
        "answer": "B",
        "analysis": "定积分体现累计思想，常用于面积或总量计算。",
        "created_by": "system",
        "is_public": True,
        "bank_source": "seed_template",
    },
]

QUESTION_BANK_CUSTOM_FILE = "question_bank_custom.json"
QUESTION_BANK_OFFICIAL_FILE = "question_bank_official_ai.json"
QUESTION_TYPES = {"single_choice", "short_answer"}
QUESTION_DIFFICULTY = {"easy", "medium", "hard"}
QUESTION_BANK_SCOPE = {"all", "official", "mine"}
QUESTION_BANK_USER_SOURCES = {"user_custom", "user_import"}


def normalize_question_options(options):
    if not isinstance(options, list):
        return []

    normalized = []
    for item in options:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized[:8]


def normalize_question_item(raw, fallback_id="", creator="", is_public_default=True, bank_source=""):
    if not isinstance(raw, dict):
        return None

    concept = normalize_concept_name(raw.get("concept") or "")
    question = str(raw.get("question") or "").strip()
    answer = str(raw.get("answer") or "").strip()
    question_type = str(raw.get("question_type") or "single_choice").strip().lower()
    difficulty = str(raw.get("difficulty") or "medium").strip().lower()
    options = normalize_question_options(raw.get("options", []))
    analysis = str(raw.get("analysis") or "").strip()

    if not concept or concept == "??":
        return None
    if not question or not answer:
        return None

    if question_type not in QUESTION_TYPES:
        question_type = "single_choice"
    if difficulty not in QUESTION_DIFFICULTY:
        difficulty = "medium"

    if question_type == "single_choice" and len(options) < 2:
        return None

    return {
        "id": str(raw.get("id") or fallback_id or f"qb-custom-{uuid.uuid4().hex[:12]}"),
        "concept": concept,
        "difficulty": difficulty,
        "question_type": question_type,
        "question": question,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "created_at": str(raw.get("created_at") or datetime.now().isoformat()),
        "created_by": str(raw.get("created_by") or creator or "system"),
        "is_public": bool(raw.get("is_public", is_public_default)),
        "bank_source": str(raw.get("bank_source") or bank_source or "user_custom"),
    }


def is_official_question_item(item):
    source = str((item or {}).get("bank_source") or "").strip().lower()
    creator = str((item or {}).get("created_by") or "").strip().lower()
    return source.startswith("official") or creator == "official_ai"


def is_my_custom_question_item(item, user_id):
    if not isinstance(item, dict):
        return False
    source = str(item.get("bank_source") or "").strip().lower()
    creator = str(item.get("created_by") or "").strip()
    return source in QUESTION_BANK_USER_SOURCES and creator == user_id


def _dedupe_questions_by_id(items):
    seen = set()
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "").strip()
        if not qid or qid in seen:
            continue
        seen.add(qid)
        result.append(item)
    return result


def load_official_question_bank_items():
    data = load_json(QUESTION_BANK_OFFICIAL_FILE, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    result = []
    for item in items:
        normalized = normalize_question_item(
            item,
            creator="official_ai",
            is_public_default=True,
            bank_source="official_ai",
        )
        if not normalized:
            continue
        normalized["created_by"] = "official_ai"
        normalized["is_public"] = True
        normalized["bank_source"] = "official_ai"
        result.append(normalized)
    return _dedupe_questions_by_id(result)


def save_official_question_bank_items(items):
    normalized_items = []
    for item in items if isinstance(items, list) else []:
        normalized = normalize_question_item(
            item,
            creator="official_ai",
            is_public_default=True,
            bank_source="official_ai",
        )
        if not normalized:
            continue
        normalized["created_by"] = "official_ai"
        normalized["is_public"] = True
        normalized["bank_source"] = "official_ai"
        normalized_items.append(normalized)

    payload = {
        "items": _dedupe_questions_by_id(normalized_items),
        "updated_at": datetime.now().isoformat(),
    }
    save_json(QUESTION_BANK_OFFICIAL_FILE, payload)


def load_custom_question_bank_items():
    data = load_json(QUESTION_BANK_CUSTOM_FILE, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    custom_items = []
    for item in items:
        normalized = normalize_question_item(item)
        if not normalized:
            continue

        # 保证官方题目不会混入“我的题库”。
        if is_official_question_item(normalized):
            continue

        source = str(normalized.get("bank_source") or "").strip().lower()
        if source not in QUESTION_BANK_USER_SOURCES:
            normalized["bank_source"] = "user_custom"
        custom_items.append(normalized)

    return _dedupe_questions_by_id(custom_items)


def save_custom_question_bank_items(items):
    normalized_items = []
    for item in items if isinstance(items, list) else []:
        normalized = normalize_question_item(item)
        if not normalized:
            continue
        if is_official_question_item(normalized):
            continue
        source = str(normalized.get("bank_source") or "").strip().lower()
        if source not in QUESTION_BANK_USER_SOURCES:
            normalized["bank_source"] = "user_custom"
        normalized_items.append(normalized)

    payload = {
        "items": _dedupe_questions_by_id(normalized_items),
        "updated_at": datetime.now().isoformat(),
    }
    save_json(QUESTION_BANK_CUSTOM_FILE, payload)


def get_visible_custom_questions(user_id):
    visible = []
    for item in load_custom_question_bank_items():
        owner = str(item.get("created_by") or "")
        if bool(item.get("is_public", False)) or owner == user_id:
            visible.append(item)
    return visible


def build_question_bank_for_user(user_id):
    bank = []
    for item in QUESTION_BANK_TEMPLATES:
        row = dict(item)
        row.setdefault("bank_source", "seed_template")
        row.setdefault("created_by", "system")
        row.setdefault("is_public", True)
        bank.append(row)

    bank.extend(load_official_question_bank_items())
    bank.extend(get_visible_custom_questions(user_id))
    return _dedupe_questions_by_id(bank)


def get_recent_drawn_question_ids(user_id, limit=8):
    events = load_user_event_list(user_id, "question_draw")
    ids = []
    for item in reversed(events):
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if qid and qid not in ids:
            ids.append(qid)
        if len(ids) >= limit:
            break
    return set(ids)


def select_question_from_bank(bank, concept="", difficulty="", bank_scope="official", user_id="default_user", recent_ids=None):
    target_concept = normalize_concept_name(concept or "")
    target_diff = str(difficulty or "").strip().lower()
    target_scope = str(bank_scope or "official").strip().lower()
    if target_scope not in QUESTION_BANK_SCOPE:
        target_scope = "official"

    candidates = []
    for item in bank if isinstance(bank, list) else []:
        if not isinstance(item, dict):
            continue

        item_concept = normalize_concept_name(item.get("concept") or "")
        item_diff = str(item.get("difficulty") or "").strip().lower()
        item_source = str(item.get("bank_source") or "").strip().lower()

        if target_concept and item_concept != target_concept:
            continue
        if target_diff and target_diff in QUESTION_DIFFICULTY and item_diff != target_diff:
            continue

        if target_scope == "official" and item_source != "official_ai":
            continue
        if target_scope == "mine" and (not is_my_custom_question_item(item, user_id)):
            continue

        candidates.append(item)

    if not candidates:
        return None

    recent_ids = recent_ids or set()
    non_repeat = [item for item in candidates if str(item.get("id") or "") not in recent_ids]
    if non_repeat:
        candidates = non_repeat

    return random.choice(candidates)


def build_question_prompt_text(question_item):
    stem = str(question_item.get("question") or "").strip()
    options = question_item.get("options", []) if isinstance(question_item.get("options", []), list) else []
    level = str(question_item.get("difficulty") or "medium").strip().lower()
    concept = str(question_item.get("concept") or "综合").strip()
    source = str(question_item.get("bank_source") or "seed_template").strip().lower()

    source_label = "练习题库"
    if source == "official_ai":
        source_label = "官方AI题库"
    elif source in QUESTION_BANK_USER_SOURCES:
        source_label = "我的题库"

    lines = [f"【题库抽题】来源：{source_label}｜知识点：{concept}｜难度：{level}", stem]
    if options:
        lines.extend(str(opt) for opt in options)
        lines.append("请直接回复选项字母（如 A），我会给出判题反馈。")
    else:
        lines.append("请分步骤作答，我会给出判题反馈。")

    return "\n".join(lines)


def find_question_by_id(user_id, question_id):
    qid = str(question_id or "").strip()
    if not qid:
        return None

    for item in build_question_bank_for_user(user_id):
        if str(item.get("id") or "") == qid:
            return item
    return None


def extract_choice_letter(text):
    value = str(text or "").strip().upper()
    if not value:
        return ""
    m = re.search(r"([A-Z])", value)
    return m.group(1) if m else ""


def evaluate_question_answer(question_item, user_answer):
    q_type = str(question_item.get("question_type") or "single_choice").strip().lower()
    expected_answer = str(question_item.get("answer") or "").strip()
    analysis = str(question_item.get("analysis") or "").strip()
    user_text = str(user_answer or "").strip()

    if q_type == "single_choice":
        expected_choice = extract_choice_letter(expected_answer)
        user_choice = extract_choice_letter(user_text)
        is_correct = bool(expected_choice and user_choice and expected_choice == user_choice)
        score = 1.0 if is_correct else 0.0
        feedback = "回答正确，继续保持。" if is_correct else f"回答不正确，正确答案是 {expected_choice or expected_answer}。"
        if analysis:
            feedback = f"{feedback}\n解析：{analysis}"
        return {
            "is_correct": is_correct,
            "score": score,
            "expected_answer": expected_answer,
            "feedback": feedback,
            "evaluation_method": "rule_single_choice",
        }

    keywords = []
    for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{4,}", expected_answer):
        t = token.strip().lower()
        if t and t not in keywords:
            keywords.append(t)
        if len(keywords) >= 6:
            break

    user_lower = user_text.lower()
    hit = sum(1 for kw in keywords if kw in user_lower)
    denom = max(1, len(keywords))
    score = round(min(1.0, hit / denom), 3)
    if expected_answer and expected_answer in user_text:
        score = 1.0

    is_correct = score >= 0.6
    feedback = "回答基本正确，关键点覆盖较好。" if is_correct else "回答还不完整，建议补充定义关键词和关键步骤。"
    if analysis:
        feedback = f"{feedback}\n参考解析：{analysis}"

    return {
        "is_correct": is_correct,
        "score": score,
        "expected_answer": expected_answer,
        "feedback": feedback,
        "evaluation_method": "rule_keyword_match",
    }


def generate_official_questions_fallback(concept, difficulty, count):
    concept_text = normalize_concept_name(concept or "")
    level = (difficulty or "medium").strip().lower()
    level = level if level in QUESTION_DIFFICULTY else "medium"

    pool = [dict(item) for item in QUESTION_BANK_TEMPLATES]
    if concept_text:
        filtered = [x for x in pool if normalize_concept_name(x.get("concept") or "") == concept_text]
        if filtered:
            pool = filtered

    random.shuffle(pool)
    results = []
    safe_count = max(1, min(10, int(count or 3)))
    for i in range(safe_count):
        src = dict(pool[i % len(pool)])
        src["id"] = f"qb-ai-fallback-{uuid.uuid4().hex[:12]}"
        src["difficulty"] = level
        src["bank_source"] = "official_ai"
        src["created_by"] = "official_ai"
        src["is_public"] = True
        src["created_at"] = datetime.now().isoformat()
        results.append(src)
    return results


def generate_official_questions_with_ai(concept, difficulty, count):
    cfg = get_ai_runtime_config()
    target_count = max(1, min(10, int(count or 3)))
    level = (difficulty or "medium").strip().lower()
    concept_text = normalize_concept_name(concept or "")

    if not USE_REAL_AI or not str(cfg.get("api_key") or "").strip():
        return generate_official_questions_fallback(concept_text, level, target_count), "fallback"

    try:
        prompt = f"""
你是数学题库生成器。请生成 {target_count} 道题目，并只返回 JSON。

要求：
1) concept 优先使用“{concept_text or '导数'}”，difficulty 使用“{level if level in QUESTION_DIFFICULTY else 'medium'}”。
2) question_type 仅可 single_choice 或 short_answer。
3) single_choice 必须有 4 个 options（A/B/C/D），answer 为正确选项字母。
4) short_answer 可不填 options，answer 给标准要点。
5) 必须返回合法 JSON，不要解释文本。

格式：
{{
  "questions": [
    {{"concept":"导数","difficulty":"medium","question_type":"single_choice","question":"...","options":["A...","B...","C...","D..."],"answer":"A","analysis":"..."}}
  ]
}}
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.get('api_key', '')}",
        }
        payload = {
            "model": cfg.get("model", "qwen-plus"),
            "messages": [
                {"role": "system", "content": "你必须返回合法JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.6,
            "max_tokens": 1600,
        }

        resp = requests.post(cfg.get("api_url"), headers=headers, json=payload, timeout=35)
        resp.raise_for_status()
        content = (resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        parsed = parse_json_from_ai_text(content)

        raw_list = []
        if isinstance(parsed, dict):
            raw_list = parsed.get("questions", []) if isinstance(parsed.get("questions", []), list) else []
        elif isinstance(parsed, list):
            raw_list = parsed

        results = []
        for item in raw_list[:target_count * 2]:
            normalized = normalize_question_item(
                item,
                fallback_id=f"qb-ai-{uuid.uuid4().hex[:12]}",
                creator="official_ai",
                is_public_default=True,
                bank_source="official_ai",
            )
            if not normalized:
                continue
            normalized["created_by"] = "official_ai"
            normalized["is_public"] = True
            normalized["bank_source"] = "official_ai"
            results.append(normalized)
            if len(results) >= target_count:
                break

        if results:
            return results, "ai"
        return generate_official_questions_fallback(concept_text, level, target_count), "fallback"
    except Exception:
        return generate_official_questions_fallback(concept_text, level, target_count), "fallback"

def ask_ai_question(question, user_id):
    """调用大模型进行智能问答（支持 Qwen/DeepSeek）。"""
    try:
        cfg = get_ai_runtime_config()
        if not cfg["api_key"]:
            return {
                "success": False,
                "answer": "",
                "ai_used": False,
                "provider": cfg["provider"],
                "error_code": "AI_KEY_MISSING",
                "error_message": f"未配置 {cfg['provider']} API Key",
            }

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
            return {
                "success": False,
                "answer": "",
                "ai_used": False,
                "provider": cfg["provider"],
                "error_code": "AI_EMPTY_RESPONSE",
                "error_message": "模型返回内容为空",
            }
        
        return {
            "success": True,
            "answer": answer,
            "ai_used": True,
            "provider": cfg["provider"],
            "error_code": "",
            "error_message": "",
        }
        
    except Exception as e:
        print(f"AI问答失败: {e}")
        cfg = get_ai_runtime_config()
        return {
            "success": False,
            "answer": "",
            "ai_used": False,
            "provider": cfg["provider"],
            "error_code": "AI_UPSTREAM_ERROR",
            "error_message": str(e),
        }


def extract_text_from_image(file_storage):
    """OCR：从图片中提取文本。支持 mock 与 qwen_vl。"""
    if not file_storage:
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": OCR_PROVIDER,
            "error_code": "OCR_EMPTY_FILE",
            "error_message": "未提供图片文件",
        }

    if OCR_PROVIDER != "qwen_vl":
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": OCR_PROVIDER,
            "error_code": "OCR_PROVIDER_DISABLED",
            "error_message": "OCR_PROVIDER 不是 qwen_vl，已禁用真实OCR",
        }

    if not QWEN_API_KEY:
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_KEY_MISSING",
            "error_message": "未配置 QWEN_API_KEY",
        }

    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

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
        text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            return {
                "success": False,
                "text": "",
                "ai_used": False,
                "provider": "qwen_vl",
                "error_code": "OCR_EMPTY_RESPONSE",
                "error_message": "OCR返回内容为空",
            }

        return {
            "success": True,
            "text": text,
            "ai_used": True,
            "provider": "qwen_vl",
            "error_code": "",
            "error_message": "",
        }
    except Exception as e:
        print(f"Qwen OCR失败: {e}")
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_UPSTREAM_ERROR",
            "error_message": str(e),
        }

# ===== 学习计划 API 接口 =====

@app.route('/api/plans', methods=['GET'])
def get_plans():
    """获取用户学习计划"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    plans = get_user_plans(user_id)
    
    return jsonify(success_payload(
        request_id,
        plans=plans,
        count=len(plans),
        error_code="",
        error_message="",
    ))

@app.route('/api/plans', methods=['POST'])
def add_plan():
    """添加新学习计划"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    time = data.get('time')
    task = data.get('task')
    
    if not time or not task:
        return error_response(request_id, 400, "INVALID_INPUT", "时间和任务内容不能为空")
    
    new_plan = add_user_plan(user_id, time, task)
    
    return jsonify(success_payload(
        request_id,
        message="学习计划添加成功",
        plan=new_plan,
        error_code="",
        error_message="",
    ))

@app.route('/api/plans/<plan_id>', methods=['PUT'])
def update_plan(plan_id):
    """更新学习计划（如打勾完成）"""
    request_id = get_request_id()
    data = request.json or {}
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
        return error_response(request_id, 400, "INVALID_INPUT", "没有要更新的内容")
    
    success = update_user_plan(user_id, plan_id, updates)
    
    if success:
        return jsonify(success_payload(
            request_id,
            message="学习计划更新成功",
            error_code="",
            error_message="",
        ))
    else:
        return error_response(request_id, 404, "PLAN_NOT_FOUND", "计划不存在或更新失败")

@app.route('/api/plans/<plan_id>', methods=['DELETE'])
def delete_plan(plan_id):
    """删除学习计划"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    
    success = delete_user_plan(user_id, plan_id)
    
    if success:
        return jsonify(success_payload(
            request_id,
            message="学习计划删除成功",
            error_code="",
            error_message="",
        ))
    else:
        return error_response(request_id, 404, "PLAN_NOT_FOUND", "计划不存在或删除失败")

@app.route('/api/plans/clear', methods=['POST'])
def clear_completed_plans():
    """清空已完成的学习计划"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    
    plans = get_user_plans(user_id)

    # 保留未完成的任务
    incomplete_plans = [p for p in plans if not p.get('completed', False)]
    set_user_plans(user_id, incomplete_plans)
    
    return jsonify(success_payload(
        request_id,
        message="已完成计划已清空",
        remaining_count=len(incomplete_plans),
        error_code="",
        error_message="",
    ))

# ===== 原有 AI 问答接口 =====

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """分析学习问题"""
    request_id = get_request_id()
    data = request.json or {}
    question = data.get('question', '').strip()
    user_id = data.get('user_id', 'default_user')
    
    if not question:
        return error_response(request_id, 400, "INVALID_INPUT", "问题不能为空")

    if not USE_REAL_AI:
        return error_response(request_id, 503, "AI_DISABLED", "USE_REAL_AI=false，当前仅允许真实AI分析")

    ai_result = analyze_with_ai(question)
    if not ai_result.get("success"):
        return error_response(
            request_id,
            502,
            ai_result.get("error_code", "AI_UPSTREAM_ERROR"),
            ai_result.get("error_message", "AI分析失败"),
            ai_used=False,
            provider=ai_result.get("provider", "unknown"),
        )

    analysis = ai_result.get("analysis", {})
    
    # 记录学习行为
    record_learning_behavior(user_id, question, analysis)
    
    return jsonify(success_payload(
        request_id,
        message="分析成功",
        analysis=analysis,
        ai_used=True,
        provider=ai_result.get("provider", "unknown"),
        error_code="",
        error_message="",
    ))

@app.route('/api/ask', methods=['GET', 'POST'])
def ask_question():
    """智能问答"""
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}

    # 兼容 POST(JSON) 与 GET(Query) 两种调用方式，降低前端/代理环境差异带来的 405 风险。
    if request.method == 'GET':
        question = (request.args.get('question', '') or '').strip()
        user_id = (request.args.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    else:
        question = (data.get('question', '') or '').strip()
        user_id = (data.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    
    if not question:
        return error_response(request_id, 400, "INVALID_INPUT", "问题不能为空")

    if not USE_REAL_AI:
        return error_response(request_id, 503, "AI_DISABLED", "USE_REAL_AI=false，当前仅允许真实AI问答")

    result = ask_ai_question(question, user_id)
    if not result.get("success"):
        return error_response(
            request_id,
            502,
            result.get("error_code", "AI_UPSTREAM_ERROR"),
            result.get("error_message", "AI问答失败"),
            source=result.get("provider", "unknown"),
            ai_used=False,
        )
    answer = result.get("answer", "")
    source = result.get("provider", "unknown")
    
    # 记录问答行为
    record_qa_behavior(user_id, question, answer)
    
    return jsonify(success_payload(
        request_id,
        message="问答成功",
        answer=answer,
        source=source,
        ai_used=True,
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/draw', methods=['GET'])
def draw_question_from_bank_api():
    """题库抽题：按官方题库/我的题库进行抽题。"""
    request_id = get_request_id()
    user_id = (request.args.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    concept = (request.args.get('concept', '') or '').strip()
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = (request.args.get('bank_scope', 'official') or 'official').strip().lower()

    if bank_scope not in QUESTION_BANK_SCOPE:
        bank_scope = 'official'
    if difficulty not in QUESTION_DIFFICULTY:
        difficulty = ''

    # 官方题库太少时自动补题，确保可抽。
    if bank_scope in {'official', 'all'}:
        official_count = len(load_official_question_bank_items())
        if official_count < 3:
            generated, _ = generate_official_questions_with_ai(concept, difficulty or 'medium', 3)
            if generated:
                official_items = load_official_question_bank_items()
                official_items.extend(generated)
                save_official_question_bank_items(official_items)

    bank = build_question_bank_for_user(user_id)
    question_item = select_question_from_bank(
        bank,
        concept=concept,
        difficulty=difficulty,
        bank_scope=bank_scope,
        user_id=user_id,
        recent_ids=get_recent_drawn_question_ids(user_id, limit=8),
    )

    if not question_item:
        return error_response(
            request_id,
            404,
            "QUESTION_NOT_FOUND",
            "未找到满足条件的题目",
            concept=concept,
            difficulty=difficulty,
            bank_scope=bank_scope,
        )

    append_user_event(user_id, "question_draw", {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question_id": question_item.get("id"),
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
        "bank_source": question_item.get("bank_source"),
    })

    return jsonify(success_payload(
        request_id,
        message="抽题成功",
        user_id=user_id,
        question={
            "id": question_item.get("id"),
            "concept": question_item.get("concept"),
            "difficulty": question_item.get("difficulty"),
            "question_type": question_item.get("question_type"),
            "question": question_item.get("question"),
            "options": question_item.get("options", []),
            "bank_source": question_item.get("bank_source", "seed_template"),
        },
        prompt_text=build_question_prompt_text(question_item),
        bank_scope=bank_scope,
        bank_size=len(bank),
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/questions', methods=['GET'])
def list_question_bank_questions_api():
    """查看题库题目（支持 official/mine/all 过滤）。"""
    request_id = get_request_id()
    user_id = (request.args.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    concept = normalize_concept_name(request.args.get('concept', '') or '')
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = (request.args.get('bank_scope', 'all') or 'all').strip().lower()

    if bank_scope not in QUESTION_BANK_SCOPE:
        bank_scope = 'all'
    if difficulty not in QUESTION_DIFFICULTY:
        difficulty = ''

    bank = build_question_bank_for_user(user_id)
    items = []
    for item in bank:
        source = str(item.get("bank_source") or "").strip().lower()
        creator = str(item.get("created_by") or "")

        if bank_scope == "official" and source != "official_ai":
            continue
        if bank_scope == "mine" and (not is_my_custom_question_item(item, user_id)):
            continue
        if concept and normalize_concept_name(item.get("concept") or "") != concept:
            continue
        if difficulty and str(item.get("difficulty") or "").strip().lower() != difficulty:
            continue

        items.append({
            "id": item.get("id"),
            "concept": item.get("concept"),
            "difficulty": item.get("difficulty"),
            "question_type": item.get("question_type"),
            "question": item.get("question"),
            "options": item.get("options", []),
            "created_by": creator,
            "is_public": bool(item.get("is_public", False)),
            "bank_source": source or "seed_template",
        })

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        bank_scope=bank_scope,
        count=len(items),
        questions=items,
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/questions', methods=['POST'])
def add_question_bank_question_api():
    """新增题目到“我的题库”。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = (data.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'

    normalized = normalize_question_item(
        raw=data,
        fallback_id=f"qb-custom-{uuid.uuid4().hex[:12]}",
        creator=user_id,
        is_public_default=False,
        bank_source="user_custom",
    )
    if not normalized:
        return error_response(request_id, 400, "INVALID_INPUT", "题目信息不完整或格式错误")

    normalized["created_by"] = user_id
    normalized["bank_source"] = "user_custom"
    if "is_public" not in data:
        normalized["is_public"] = False

    custom_items = load_custom_question_bank_items()
    custom_items = [item for item in custom_items if str(item.get("id") or "") != normalized["id"]]
    custom_items.append(normalized)
    save_custom_question_bank_items(custom_items)

    return jsonify(success_payload(
        request_id,
        message="题目已加入我的题库",
        user_id=user_id,
        question={
            "id": normalized.get("id"),
            "concept": normalized.get("concept"),
            "difficulty": normalized.get("difficulty"),
            "question_type": normalized.get("question_type"),
            "question": normalized.get("question"),
            "options": normalized.get("options", []),
            "bank_source": normalized.get("bank_source", "user_custom"),
        },
        custom_bank_count=len(custom_items),
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/generate', methods=['POST'])
def generate_question_bank_question_api():
    """官方题库：通过 AI 批量生题并入库。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = (data.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    concept = normalize_concept_name(data.get('concept') or '')
    difficulty = (data.get('difficulty', 'medium') or 'medium').strip().lower()

    try:
        count = int(data.get('count', 3) or 3)
    except Exception:
        count = 3
    count = max(1, min(10, count))

    questions, mode = generate_official_questions_with_ai(concept, difficulty, count)
    if not questions:
        return error_response(request_id, 502, "QUESTION_GENERATE_FAILED", "官方题库生题失败")

    official_items = load_official_question_bank_items()
    official_items.extend(questions)
    save_official_question_bank_items(official_items)

    return jsonify(success_payload(
        request_id,
        message="官方题库生题完成",
        user_id=user_id,
        generate_mode=mode,
        generated_count=len(questions),
        official_bank_count=len(load_official_question_bank_items()),
        sample_questions=[
            {
                "id": q.get("id"),
                "concept": q.get("concept"),
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "question": q.get("question"),
                "bank_source": q.get("bank_source", "official_ai"),
            }
            for q in questions[:5]
        ],
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/answer', methods=['POST'])
def answer_question_bank_question_api():
    """提交题库答案并返回判题反馈。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = (data.get('user_id', 'default_user') or 'default_user').strip() or 'default_user'
    question_id = str(data.get('question_id') or '').strip()
    user_answer = str(data.get('user_answer') or '').strip()

    if not question_id:
        return error_response(request_id, 400, "INVALID_INPUT", "question_id 不能为空")
    if not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "user_answer 不能为空")

    question_item = find_question_by_id(user_id, question_id)
    if not question_item:
        return error_response(request_id, 404, "QUESTION_NOT_FOUND", "题目不存在或不可见")

    evaluation = evaluate_question_answer(question_item, user_answer)

    append_user_event(user_id, "question_answer", {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question_id": question_id,
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
        "user_answer": user_answer,
        "is_correct": bool(evaluation.get("is_correct", False)),
        "score": float(evaluation.get("score", 0.0) or 0.0),
    })

    return jsonify(success_payload(
        request_id,
        message="判题完成",
        user_id=user_id,
        question_id=question_id,
        concept=question_item.get("concept"),
        is_correct=bool(evaluation.get("is_correct", False)),
        score=float(evaluation.get("score", 0.0) or 0.0),
        expected_answer=evaluation.get("expected_answer", ""),
        feedback=evaluation.get("feedback", ""),
        evaluation_method=evaluation.get("evaluation_method", "rule"),
        next_action="可继续抽题，或切换题库继续练习。",
        error_code="",
        error_message="",
    ))

@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    """上传学习图片并进行OCR解析。"""
    request_id = get_request_id()
    if 'image' not in request.files:
        return error_response(request_id, 400, "INVALID_INPUT", "没有上传图片")
    
    file = request.files['image']
    user_id = request.form.get('user_id', 'default_user')

    ocr_result = extract_text_from_image(file)
    if not ocr_result.get("success"):
        return error_response(
            request_id,
            502,
            ocr_result.get("error_code", "OCR_UPSTREAM_ERROR"),
            ocr_result.get("error_message", "OCR识别失败"),
            provider=ocr_result.get("provider", OCR_PROVIDER),
            ai_used=False,
        )

    extracted_text = ocr_result.get("text", "")
    extract_result = extract_knowledge_from_text_api_inner(user_id, extracted_text, "image_ocr")
    concepts = extract_result.get("detected_concepts", []) or []

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
    
    return jsonify(success_payload(
        request_id,
        message="图片上传成功",
        detected_concepts=concepts,
        ocr_text=extracted_text,
        analysis="已完成OCR并更新知识图谱",
        graph_sync=extract_result.get("graph_sync", {}),
        ai_used=True,
        provider=ocr_result.get("provider", "qwen_vl"),
        error_code="",
        error_message="",
    ))


# ===== 知识图谱 API 接口 =====

@app.route('/api/knowledge_graph', methods=['GET'])
def get_knowledge_graph_api():
    """获取用户知识图谱（节点/关系/掌握度）"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    min_relation_score_raw = request.args.get('min_relation_score', '')
    min_relation_score = None
    if str(min_relation_score_raw).strip() != '':
        try:
            min_relation_score = float(min_relation_score_raw)
        except Exception:
            return error_response(request_id, 400, "INVALID_INPUT", "min_relation_score 必须是 0~1 之间的数字")

    result = build_graph_response(user_id, min_relation_score=min_relation_score)
    if not isinstance(result, dict):
        return error_response(request_id, 500, "INTERNAL_ERROR", "图谱构建失败")
    result["request_id"] = request_id
    return jsonify(result)


@app.route('/api/knowledge_graph/mastery', methods=['POST'])
def update_knowledge_mastery_api():
    """更新某个知识点掌握度"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    concept = normalize_concept_name(data.get('concept'))
    mastery = data.get('mastery', None)

    if not concept or mastery is None:
        return error_response(request_id, 400, "INVALID_INPUT", "concept 和 mastery 不能为空")

    if concept == "??":
        return error_response(request_id, 400, "INVALID_INPUT", "concept 编码异常，请使用页面操作或 UTF-8 请求")

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
    graph_sync = sync_mastery_update(
        user_id=user_id,
        concept=concept,
        mastery=mastery,
        review_count=review_count,
        last_reviewed=last_reviewed,
    )

    return jsonify(success_payload(
        request_id,
        message="掌握度更新成功",
        concept=concept,
        mastery=mastery,
        graph_sync=graph_sync,
        neo4j_synced=bool(graph_sync.get("synced", False)) if neo4j_store.enabled else False,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/node', methods=['DELETE'])
def delete_knowledge_node_api():
    """删除某个知识点节点（同时移除关联关系）。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    concept = normalize_concept_name(data.get('concept'))

    if not concept:
        return error_response(request_id, 400, "INVALID_INPUT", "concept 不能为空")

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

    graph_sync = sync_delete_concept(user_id=user_id, concept=concept)

    return jsonify(success_payload(
        request_id,
        message="节点删除成功",
        concept=concept,
        removed_concepts=before_concepts - len(concept_list),
        removed_relations=before_relations - len(relation_list),
        graph_sync=graph_sync,
        neo4j_synced=bool(graph_sync.get("synced", False)) if neo4j_store.enabled else False,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/path', methods=['GET'])
def get_learning_path_api():
    """获取从已掌握知识到目标知识点的学习路径"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    target = request.args.get('target', '').strip()

    if not target:
        return error_response(request_id, 400, "INVALID_INPUT", "target 参数不能为空")

    if GRAPH_PRIMARY in {"auto", "neo4j"} and neo4j_store.enabled:
        exists_in_neo4j = neo4j_store.concept_exists(target)
        if not exists_in_neo4j and GRAPH_PRIMARY == "neo4j":
            return error_response(
                request_id,
                404,
                "TARGET_NOT_FOUND",
                f"目标知识点不存在: {target}",
                path=[],
                storage="neo4j",
            )

        neo4j_path = neo4j_store.fetch_learning_path(user_id=user_id, target=target, max_depth=8)
        if neo4j_path:
            return jsonify(success_payload(
                request_id,
                user_id=user_id,
                target=target,
                path=neo4j_path,
                length=len(neo4j_path),
                storage="neo4j",
                error_code="",
                error_message="",
            ))

    kg = build_knowledge_graph()
    sync_user_mastery_to_graph(kg, user_id)

    if target not in kg.graph.nodes:
        return error_response(
            request_id,
            404,
            "TARGET_NOT_FOUND",
            f"目标知识点不存在: {target}",
            path=[],
            storage="json",
        )

    path = kg.get_learning_path(user_id, target)
    path_source = "json"
    if not path:
        fallback_path = infer_learning_path_with_fallback(user_id, target)
        if fallback_path:
            path = fallback_path
            path_source = "json_fallback"

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        target=target,
        path=path,
        length=len(path),
        storage="json",
        path_source=path_source,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/extract', methods=['POST'])
def extract_knowledge_from_text_api():
    """从文本抽取知识点并写入用户知识图谱。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    text = (data.get('text') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not text:
        return error_response(request_id, 400, "INVALID_INPUT", "text 不能为空")

    extract_result = extract_knowledge_from_text_api_inner(user_id, text, source)
    detected_concepts = extract_result.get("detected_concepts", [])
    relations = extract_result.get("relations", [])
    new_count = extract_result.get("new_concept_count", 0)
    graph_sync = extract_result.get("graph_sync", {})
    extraction_method = extract_result.get("extraction_method", "rule")
    ai_extract = extract_result.get("ai_extract", {})

    return jsonify(success_payload(
        request_id,
        message="知识抽取成功",
        user_id=user_id,
        source=source,
        detected_concepts=detected_concepts,
        new_concept_count=new_count,
        relations=relations,
        extraction_method=extraction_method,
        ai_extract=ai_extract,
        graph_sync=graph_sync,
        error_code="",
        error_message="",
    ))


@app.route('/api/review/reminders', methods=['GET'])
def get_review_reminders_api():
    """根据掌握度和复习记录返回复习提醒。"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    result = build_review_reminders_response(user_id)
    if isinstance(result, dict):
        result["request_id"] = request_id
    return jsonify(result)


@app.route('/api/content/ingest', methods=['POST'])
def ingest_learning_content_api():
    """多源学习内容录入（笔记/链接/答题记录等）。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    content_type = (data.get('content_type') or 'note').strip().lower()
    content = (data.get('content') or '').strip()
    title = (data.get('title') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not content:
        return error_response(request_id, 400, "INVALID_INPUT", "content 不能为空")

    result = process_content_ingest_sync(user_id, content_type, content, title, source)
    return jsonify(success_payload(request_id, **result, mode="sync"))


def extract_knowledge_from_text_api_inner(user_id, text, source):
    """内部复用：执行一次知识抽取并返回结果对象。"""
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    context_concepts = select_context_concepts_for_relation(user_knowledge, text, detected_hints=[])

    ai_extract = extract_knowledge_with_ai(text, context_concepts=context_concepts)
    detected_concepts = ai_extract.get("concepts", []) if isinstance(ai_extract, dict) else []
    relations = ai_extract.get("relations", []) if isinstance(ai_extract, dict) else []

    extraction_method = "ai"
    if not detected_concepts:
        detected_concepts = detect_concepts_from_text(text)
        extraction_method = "rule"

    if not relations:
        inner_rel = infer_relations_from_concepts(detected_concepts) if detected_concepts else []
        # 规则兜底：补充“新概念与现有图谱概念”的关系。
        context_concepts = select_context_concepts_for_relation(user_knowledge, text, detected_hints=detected_concepts)
        cross_rel = infer_relations_with_existing_context(detected_concepts, context_concepts)
        all_rel_map = {}
        for rel in inner_rel + cross_rel:
            key = (rel.get("source"), rel.get("target"), rel.get("type"))
            if key[0] and key[1] and key[0] != key[1]:
                prev = all_rel_map.get(key)
                cur_score = float(rel.get("score", 0.6) or 0.6)
                cur_rel = {
                    "source": key[0],
                    "target": key[1],
                    "type": key[2],
                    "score": round(cur_score, 3),
                    "evidence": rel.get("evidence", ""),
                }
                if not prev or cur_score > float(prev.get("score", 0.0) or 0.0):
                    all_rel_map[key] = cur_rel
        relations = [r for r in all_rel_map.values() if float(r.get("score", 0.0) or 0.0) >= RELATION_MIN_SCORE]

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
        rel_score = float(rel.get("score", 0.6) or 0.6)
        if rel_score < RELATION_MIN_SCORE:
            continue
        rel_key = (rel["source"], rel["target"], rel["type"])
        if rel_key not in existing_relation_keys:
            relation_list.append({
                "source": rel["source"],
                "target": rel["target"],
                "type": rel["type"],
                "score": round(rel_score, 3),
                "evidence": (rel.get("evidence") or "")[:60],
                "source_text": text[:120],
                "created_at": datetime.now().isoformat(),
                "from": source
            })

    user_knowledge["concepts"] = concept_list
    user_knowledge["relations"] = relation_list
    user_knowledge["deleted_concepts"] = deleted_concepts
    set_user_knowledge(user_id, user_knowledge)

    # 同步到 Neo4j（支持异步任务 + 同步回退），传递已删除节点以避免被重建
    graph_sync = sync_user_graph(user_id, concept_list, relation_list, deleted_concepts=deleted_concepts)

    return {
        "detected_concepts": detected_concepts,
        "relations": relations,
        "new_concept_count": new_count,
        "extraction_method": extraction_method,
        "ai_extract": {
            "ai_used": bool(ai_extract.get("ai_used", False)) if isinstance(ai_extract, dict) else False,
            "provider": ai_extract.get("provider", "unknown") if isinstance(ai_extract, dict) else "unknown",
            "error": ai_extract.get("error", "") if isinstance(ai_extract, dict) else "",
        },
        "neo4j_synced": bool(graph_sync.get("synced", False)) if neo4j_store.enabled else False,
        "graph_sync": graph_sync,
    }


def process_content_ingest_sync(user_id, content_type, content, title, source):
    """同步处理内容录入，返回统一结果。"""
    extract_resp = extract_knowledge_from_text_api_inner(user_id, content, f"content_{content_type}")
    topics = (extract_resp.get("detected_concepts") or [])[:6]
    if not topics:
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
    profile = build_learning_profile(user_id)

    return {
        "success": True,
        "message": "内容录入成功",
        "event": event,
        "knowledge_extract": extract_resp,
        "profile": profile,
    }


if celery_client:
    @celery_client.task(name="tasks.sync_user_graph")
    def sync_user_graph_task(payload):
        user_id = payload.get("user_id", "default_user")
        concept_list = payload.get("concepts", []) or []
        relation_list = payload.get("relations", []) or []
        deleted = payload.get("deleted", []) or []

        # 先行删除云端已标记为删除的概念，避免被后续 upsert 重建（带重试与日志）
        for d in deleted:
            try_delete_concept_with_retry(user_id, d)

        # 过滤上报数据，避免重建已删除节点或连接
        if deleted:
            deleted_set = set(deleted)
            concept_list = [c for c in concept_list if (c.get("concept") if isinstance(c, dict) else c) not in deleted_set]
            relation_list = [r for r in relation_list if r.get("source") not in deleted_set and r.get("target") not in deleted_set]

        ok = neo4j_store.upsert_user_graph(user_id, concept_list, relation_list)
        return {
            "success": bool(ok),
            "user_id": user_id,
            "synced": bool(ok),
            "mode": "async",
        }

    @celery_client.task(name="tasks.process_content_ingest")
    def process_content_ingest_task(payload):
        user_id = payload.get("user_id", "default_user")
        content_type = payload.get("content_type", "note")
        content = payload.get("content", "")
        title = payload.get("title", "")
        source = payload.get("source", "manual_async")
        return process_content_ingest_sync(user_id, content_type, content, title, source)

    @celery_client.task(name="tasks.sync_mastery_update")
    def sync_mastery_update_task(payload):
        ok = neo4j_store.update_mastery(
            user_id=payload.get("user_id", "default_user"),
            concept=payload.get("concept", ""),
            mastery=float(payload.get("mastery", 0.0)),
            review_count=int(payload.get("review_count", 0)),
            last_reviewed=payload.get("last_reviewed"),
        )
        return {
            "success": bool(ok),
            "synced": bool(ok),
            "mode": "async",
        }

    @celery_client.task(name="tasks.sync_delete_concept")
    def sync_delete_concept_task(payload):
        ok = neo4j_store.delete_concept(
            user_id=payload.get("user_id", "default_user"),
            concept=payload.get("concept", ""),
        )
        return {
            "success": bool(ok),
            "synced": bool(ok),
            "mode": "async",
        }


def sync_user_graph(user_id, concept_list, relation_list, deleted_concepts=None):
    """统一图谱同步入口：支持 async/sync/auto 三种模式。
    支持传入 `deleted_concepts`，在向 Neo4j 上 upsert 之前先删除这些节点，
    避免因本地仍存在而在启动或同步时被重建。"""
    if not neo4j_store.enabled:
        return {
            "enabled": False,
            "mode": "disabled",
            "synced": False,
            "task_id": None,
        }

    mode = GRAPH_SYNC_MODE if GRAPH_SYNC_MODE in {"auto", "sync", "async"} else "auto"

    # async 明确启用，或 auto 且 Celery 可用时，优先异步。
    worker_available = is_celery_worker_available()
    use_async = mode == "async" or (mode == "auto" and celery_client and AsyncResult and worker_available)
    if use_async and celery_client:
        try:
            payload = {
                "user_id": user_id,
                "concepts": concept_list,
                "relations": relation_list,
                "deleted": deleted_concepts or []
            }
            result = sync_user_graph_task.delay(payload)
            register_task_meta(
                task_id=result.id,
                task_type="sync_user_graph",
                user_id=user_id,
                extra={"concept_count": len(concept_list), "relation_count": len(relation_list)},
            )
            return {
                "enabled": True,
                "mode": "async",
                "synced": False,
                "submitted": True,
                "task_id": result.id,
                "task_type": "sync_user_graph",
                "status_url": f"/api/tasks/{result.id}",
            }
        except Exception:
            # 提交任务失败则回退同步，避免丢写。
            pass
    # 同步路径：先删除再 upsert，保证已删除节点不会被重建
    if deleted_concepts:
        deleted_set = set(deleted_concepts or [])

        def try_delete_concept_with_retry(u_id, concept, attempts=3, base_delay=0.5):
            """尝试删除 Neo4j 概念，失败时重试并记录日志。"""
            for attempt in range(1, attempts + 1):
                try:
                    ok = neo4j_store.delete_concept(user_id=u_id, concept=concept)
                    if ok:
                        logger.info(f"deleted concept '%s' for user %s (attempt %d)", concept, u_id, attempt)
                        return True
                    else:
                        logger.warning("delete_concept returned False for %s (user=%s) on attempt %d", concept, u_id, attempt)
                except Exception as e:
                    logger.exception("delete_concept exception for %s (user=%s) on attempt %d: %s", concept, u_id, attempt, e)

                if attempt < attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    time.sleep(delay)

            logger.error("failed to delete concept '%s' for user %s after %d attempts", concept, u_id, attempts)
            return False

        for d in (deleted_concepts or []):
            try_delete_concept_with_retry(user_id, d)

        concept_list = [c for c in concept_list if (c.get("concept") if isinstance(c, dict) else c) not in deleted_set]
        relation_list = [r for r in relation_list if r.get("source") not in deleted_set and r.get("target") not in deleted_set]

    ok = neo4j_store.upsert_user_graph(user_id, concept_list, relation_list)
    return {
        "enabled": True,
        "mode": "sync",
        "synced": bool(ok),
        "task_id": None,
        "task_type": "sync_user_graph",
        "status_url": None,
    }


def sync_mastery_update(user_id, concept, mastery, review_count=0, last_reviewed=None):
    """统一掌握度同步入口：支持 async/sync/auto。"""
    if not neo4j_store.enabled:
        return {
            "enabled": False,
            "mode": "disabled",
            "synced": False,
            "task_id": None,
        }

    mode = GRAPH_SYNC_MODE if GRAPH_SYNC_MODE in {"auto", "sync", "async"} else "auto"
    worker_available = is_celery_worker_available()
    use_async = mode == "async" or (mode == "auto" and celery_client and AsyncResult and worker_available)
    if use_async and celery_client and "sync_mastery_update_task" in globals():
        try:
            payload = {
                "user_id": user_id,
                "concept": concept,
                "mastery": mastery,
                "review_count": review_count,
                "last_reviewed": last_reviewed,
            }
            result = sync_mastery_update_task.delay(payload)
            register_task_meta(
                task_id=result.id,
                task_type="sync_mastery_update",
                user_id=user_id,
                extra={"concept": concept},
            )
            return {
                "enabled": True,
                "mode": "async",
                "synced": False,
                "submitted": True,
                "task_id": result.id,
                "task_type": "sync_mastery_update",
                "status_url": f"/api/tasks/{result.id}",
            }
        except Exception:
            pass

    ok = neo4j_store.update_mastery(
        user_id=user_id,
        concept=concept,
        mastery=mastery,
        review_count=review_count,
        last_reviewed=last_reviewed,
    )
    return {
        "enabled": True,
        "mode": "sync",
        "synced": bool(ok),
        "task_id": None,
        "task_type": "sync_mastery_update",
        "status_url": None,
    }


def sync_delete_concept(user_id, concept):
    """统一删除节点同步入口：支持 async/sync/auto。"""
    if not neo4j_store.enabled:
        return {
            "enabled": False,
            "mode": "disabled",
            "synced": False,
            "task_id": None,
        }

    mode = GRAPH_SYNC_MODE if GRAPH_SYNC_MODE in {"auto", "sync", "async"} else "auto"
    worker_available = is_celery_worker_available()
    use_async = mode == "async" or (mode == "auto" and celery_client and AsyncResult and worker_available)
    if use_async and celery_client and "sync_delete_concept_task" in globals():
        try:
            payload = {"user_id": user_id, "concept": concept}
            result = sync_delete_concept_task.delay(payload)
            register_task_meta(
                task_id=result.id,
                task_type="sync_delete_concept",
                user_id=user_id,
                extra={"concept": concept},
            )
            return {
                "enabled": True,
                "mode": "async",
                "synced": False,
                "submitted": True,
                "task_id": result.id,
                "task_type": "sync_delete_concept",
                "status_url": f"/api/tasks/{result.id}",
            }
        except Exception:
            pass

    ok = neo4j_store.delete_concept(user_id=user_id, concept=concept)
    return {
        "enabled": True,
        "mode": "sync",
        "synced": bool(ok),
        "task_id": None,
        "task_type": "sync_delete_concept",
        "status_url": None,
    }


@app.route('/api/diagnosis/analyze', methods=['POST'])
def cognitive_diagnosis_api():
    """错题归因分析接口。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    question = (data.get('question') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    user_answer = (data.get('user_answer') or '').strip()

    if not question or not correct_answer or not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "question、correct_answer、user_answer 不能为空")

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
    extract_result = extract_knowledge_from_text_api_inner(user_id, question, "diagnosis")
    profile = build_learning_profile(user_id)

    return jsonify(success_payload(
        request_id,
        diagnosis=diagnosis,
        profile=profile,
        graph_sync=extract_result.get("graph_sync", {}),
        error_code="",
        error_message="",
    ))


@app.route('/api/content/ingest_async', methods=['POST'])
def ingest_learning_content_async_api():
    """异步内容录入接口（Celery）。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    content_type = (data.get('content_type') or 'note').strip().lower()
    content = (data.get('content') or '').strip()
    title = (data.get('title') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not content:
        return error_response(request_id, 400, "INVALID_INPUT", "content 不能为空")

    payload = {
        "user_id": user_id,
        "content_type": content_type,
        "content": content,
        "title": title,
        "source": source,
    }

    if celery_client and AsyncResult:
        async_result = process_content_ingest_task.delay(payload)
        register_task_meta(
            task_id=async_result.id,
            task_type="process_content_ingest",
            user_id=user_id,
            extra={"content_type": content_type, "source": source},
        )
        return jsonify(success_payload(
            request_id,
            mode="async",
            task_id=async_result.id,
            task_type="process_content_ingest",
            status_url=f"/api/tasks/{async_result.id}",
            error_code="",
            error_message="",
        ))

    # 无 Celery 时回退为同步
    result = process_content_ingest_sync(user_id, content_type, content, title, source)
    return jsonify(success_payload(request_id, **result, mode="sync_fallback"))


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status_api(task_id):
    """查询异步任务状态。"""
    request_id = get_request_id()
    if not (celery_client and AsyncResult):
        return error_response(
            request_id,
            503,
            "CELERY_DISABLED",
            "Celery 未启用",
            state="UNAVAILABLE",
            task_id=task_id,
        )

    result = AsyncResult(task_id, app=celery_client)
    payload = {
        "success": True,
        "request_id": request_id,
        "task_id": task_id,
        "state": result.state,
        "task_meta": TASK_META.get(task_id, {}),
        "error_code": "",
        "error_message": "",
    }

    if result.state == "SUCCESS":
        payload["result"] = result.result
    elif result.state == "FAILURE":
        payload["error"] = str(result.result)

    return jsonify(payload)


@app.route('/api/diagnosis/report', methods=['GET'])
def cognitive_diagnosis_report_api():
    """获取用户诊断统计报告。"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    result = build_diagnosis_report_response(user_id)
    if isinstance(result, dict):
        result["request_id"] = request_id
    return jsonify(result)


@app.route('/api/profile', methods=['GET'])
def profile_api():
    """获取用户学习画像。"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    profile = build_learning_profile(user_id)
    return jsonify(success_payload(
        request_id,
        profile=profile,
        error_code="",
        error_message="",
    ))


@app.route('/api/recommendations', methods=['GET'])
def recommendations_api():
    """获取个性化学习资源推荐。"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')
    limit = int(request.args.get('limit', 6))
    items = build_recommendations(user_id, limit=max(1, min(limit, 12)))
    profile = get_user_profile(user_id) or {}
    diagnosis_logs = load_user_event_list(user_id, "diagnosis")
    recent_diagnosis = diagnosis_logs[-10:] if isinstance(diagnosis_logs, list) else []
    diagnosis_count = len(recent_diagnosis)
    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        count=len(items),
        items=items,
        recommendation_context=build_recommendation_context(profile, diagnosis_count),
        error_code="",
        error_message="",
    ))


@app.route('/api/dashboard/summary', methods=['GET'])
def dashboard_summary_api():
    """仪表盘聚合数据接口。"""
    request_id = get_request_id()
    user_id = request.args.get('user_id', 'default_user')

    graph = build_graph_response(user_id)
    reminders = build_review_reminders_response(user_id)
    profile = build_learning_profile(user_id)
    diagnosis_report = build_diagnosis_report_response(user_id)
    recommendations = build_recommendations(user_id, limit=4)
    storage_info = get_storage_info()
    cfg = get_ai_runtime_config()

    nodes = graph.get("graph", {}).get("nodes", [])
    overall_mastery = 0
    if nodes:
        overall_mastery = round(sum(float(n.get("mastery", 0)) for n in nodes) / len(nodes), 3)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        overall_mastery=overall_mastery,
        graph={
            "node_count": graph.get("node_count", 0),
            "edge_count": graph.get("edge_count", 0)
        },
        review={
            "due_count": reminders.get("due_count", 0),
            "upcoming_count": reminders.get("upcoming_count", 0)
        },
        profile=profile,
        diagnosis=diagnosis_report,
        recommendations=recommendations,
        system={
            "storage_backend": storage_info.get("storage_backend", "json"),
            "database_scheme": storage_info.get("database_scheme", ""),
            "graph_primary": GRAPH_PRIMARY,
            "graph_sync_mode": GRAPH_SYNC_MODE,
            "neo4j_enabled": neo4j_store.enabled,
            "celery_enabled": celery_client is not None,
            "ai_enabled": USE_REAL_AI,
            "ai_provider": cfg.get("provider", "mock") if USE_REAL_AI else "mock",
        },
        error_code="",
        error_message="",
    ))

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
    
    db_append_user_event(user_id, "behavior", behavior)

def record_qa_behavior(user_id, question, answer):
    """记录问答行为"""
    behavior = {
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer[:200],  # 只存储前200字符
        "type": "qa_interaction"
    }
    
    db_append_user_event(user_id, "qa", behavior)

def update_user_knowledge(user_id, concepts):
    """更新用户知识图谱"""
    knowledge = get_user_knowledge(user_id)
    concept_list = knowledge.get("concepts", [])

    for concept in concepts:
        if concept not in [c.get("concept") for c in concept_list if isinstance(c, dict)]:
            concept_list.append({
                "concept": concept,
                "first_seen": datetime.now().isoformat(),
                "mastery": 0.3,
                "review_count": 0
            })

    knowledge["concepts"] = concept_list
    set_user_knowledge(user_id, knowledge)

@app.route('/health', methods=['GET'])
def health():
    """健康检查接口"""
    cfg = get_ai_runtime_config()
    neo4j_error = getattr(neo4j_store, "last_error", "")
    storage_info = get_storage_info()
    return jsonify({
        "status": "ok",
        "provider": cfg["provider"] if USE_REAL_AI else "mock",
        "model": cfg["model"] if USE_REAL_AI else "mock",
        "ai_key_configured": bool(cfg.get("api_key")),
        "ai_enabled": USE_REAL_AI,
        "ocr_provider": OCR_PROVIDER,
        "neo4j_enabled": neo4j_store.enabled,
        "neo4j_error": neo4j_error,
        "graph_primary": GRAPH_PRIMARY,
        "graph_sync_mode": GRAPH_SYNC_MODE,
        "celery_enabled": celery_client is not None,
        "celery_worker_available": is_celery_worker_available(),
        "storage_backend": storage_info.get("storage_backend", "json"),
        "database_scheme": storage_info.get("database_scheme", ""),
        "message": "智能学习伴侣服务运行正常"
    })


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


@app.route('/', methods=['GET'])
def frontend_index():
    """通过后端直接提供前端首页，便于远程端口转发场景统一走 5000 端口。"""
    index_file = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.isfile(index_file):
        return send_from_directory(FRONTEND_DIR, 'index.html')
    return jsonify({"success": False, "message": "frontend/index.html not found"}), 404


@app.route('/<path:asset_path>', methods=['GET'])
def frontend_assets(asset_path):
    """提供前端静态资源文件（js/css/html）。"""
    normalized = (asset_path or '').strip()
    if not normalized:
        return send_from_directory(FRONTEND_DIR, 'index.html')

    # 避免把未知 API 路径误当作静态文件。
    if normalized.startswith('api/'):
        return jsonify({"success": False, "message": "API endpoint not found"}), 404

    full_path = os.path.join(FRONTEND_DIR, normalized)
    if os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIR, normalized)

    return jsonify({"success": False, "message": "Resource not found"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')