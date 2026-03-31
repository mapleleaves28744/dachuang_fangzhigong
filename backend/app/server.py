from flask import Flask, Response, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import copy
from datetime import datetime, timedelta
from collections import Counter, defaultdict, deque
import os
import uuid
import re
import base64
import random
import hashlib
import secrets
from .services.cognitive_diagnosis import CognitiveDiagnosis
from .services.celery_app import create_celery
from .services.knowledge_graph import KnowledgeGraph
from .services.mastery_engine import calculate_concept_mastery, build_learning_advice
from .services.learning_profile import (
    build_learning_profile as build_learning_profile_core,
    build_recommendations as build_recommendations_core,
    build_recommendation_context,
)
from .services.concept_mapping import (
    DEFAULT_MATCH_THRESHOLDS as CONCEPT_MAPPING_THRESHOLDS,
    DEFAULT_METHOD_INFO as CONCEPT_MAPPING_METHOD_INFO,
    build_concept_profiles,
    map_learning_items,
)
from .services.dashboard_summary import build_dashboard_sections
from .services.neo4j_store import Neo4jGraphStore
import logging
import time
from werkzeug.security import check_password_hash, generate_password_hash

# 简单日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)


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


AUTH_TOKEN_TTL_DAYS = max(1, int(os.getenv("AUTH_TOKEN_TTL_DAYS", "14")))
AUTH_TOUCH_INTERVAL_SECONDS = 300
AUTH_BINDABLE_EVENT_SUFFIXES = (
    "content",
    "diagnosis",
    "behavior",
    "qa",
    "question_draw",
    "question_answer",
)
SPACE_MAX_ITEM_COUNT = max(20, int(os.getenv("SPACE_MAX_ITEM_COUNT", "200")))
SPACE_MAX_FILE_BYTES = max(1024, int(os.getenv("SPACE_MAX_FILE_BYTES", "10485760")))


def utcnow():
    return datetime.utcnow()


def iso_now():
    return utcnow().isoformat()


def deep_copy_data(value, default):
    try:
        return copy.deepcopy(value)
    except Exception:
        return copy.deepcopy(default)


def stable_json_key(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def now_ms():
    return int(utcnow().timestamp() * 1000)


def build_api_absolute_url(path, params=None):
    base = (request.host_url or "").rstrip("/")
    query = ""
    if params:
        encoded = []
        for key, value in params.items():
            if value is None:
                continue
            encoded.append(f"{key}={requests.utils.quote(str(value), safe='')}")
        if encoded:
            query = f"?{'&'.join(encoded)}"
    return f"{base}{path}{query}"


def clamp_text(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit]


def normalize_space_name(value, fallback="新空间"):
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return (text or fallback or "新空间")[:40]


def summarize_space_item(name, kind, mime, size, source, content, has_file):
    kind_text = str(kind or "document").strip() or "document"
    mime_text = str(mime or "").strip() or "unknown"
    size_kb = max(1, round(max(0, int(size or 0)) / 1024))
    source_text = str(source or "space").strip() or "space"
    lines = [
        f"类型: {kind_text}",
        f"MIME: {mime_text}",
        f"大小: {size_kb} KB",
        f"来源: {source_text}",
    ]

    plain = re.sub(r"\s+", " ", str(content or "")).strip()
    if plain:
        excerpt = plain[:180]
        if len(plain) > 180:
            excerpt += "..."
        lines.append(f"内容摘要: {excerpt}")
    elif has_file:
        lines.append(f"已保存云端原始文件，可直接预览分析《{str(name or '未命名文件').strip() or '未命名文件'}》。")
    else:
        lines.append("当前条目已保存，可直接在空间中查看。")
    return "\n".join(lines)


def decode_space_data_url(data_url):
    raw = str(data_url or "").strip()
    if not raw or not raw.startswith("data:") or "," not in raw:
        return b"", ""

    header, payload = raw.split(",", 1)
    mime = header[5:].split(";")[0].strip() or "application/octet-stream"

    if ";base64" in header:
        try:
            return base64.b64decode(payload), mime
        except Exception:
            return b"", mime

    try:
        return requests.utils.unquote(payload).encode("utf-8"), mime
    except Exception:
        return payload.encode("utf-8"), mime


def build_space_item_fingerprint(item):
    if not isinstance(item, dict):
        return ""

    comparable = {
        "name": str(item.get("name") or ""),
        "kind": str(item.get("kind") or ""),
        "mime": str(item.get("mime") or ""),
        "size": int(item.get("size") or 0),
        "source": str(item.get("source") or ""),
        "content": str(item.get("content") or ""),
        "summary": str(item.get("summary") or ""),
        "audioDataUrl": str(item.get("audioDataUrl") or ""),
        "fileDataUrl": str(item.get("fileDataUrl") or ""),
    }
    return stable_json_key(comparable)


def create_space_record(name):
    ts = now_ms()
    return {
        "id": f"space_{ts}_{uuid.uuid4().hex[:6]}",
        "name": normalize_space_name(name, "新空间"),
        "createdAt": ts,
        "updatedAt": ts,
        "items": [],
    }


def normalize_space_item_input(raw_item, index_offset=0):
    if not isinstance(raw_item, dict):
        return None

    file_data_url = str(raw_item.get("fileDataUrl") or "")
    audio_data_url = str(raw_item.get("audioDataUrl") or "")
    primary_data_url = audio_data_url or file_data_url
    decoded_bytes, decoded_mime = decode_space_data_url(primary_data_url)
    if decoded_bytes and len(decoded_bytes) > SPACE_MAX_FILE_BYTES:
        raise ValueError(f"单个文件不能超过 {max(1, SPACE_MAX_FILE_BYTES // 1024 // 1024)} MB")

    ts = now_ms() + max(0, int(index_offset or 0))
    content = clamp_text(raw_item.get("content"), 120000)
    mime = str(raw_item.get("mime") or decoded_mime or "").strip()
    kind = str(raw_item.get("kind") or "document").strip() or "document"
    size = int(raw_item.get("size") or 0)
    if decoded_bytes:
        size = max(size, len(decoded_bytes))
    elif content:
        size = max(size, len(content.encode("utf-8")))

    item = {
        "id": f"item_{ts}_{uuid.uuid4().hex[:6]}",
        "name": clamp_text(raw_item.get("name") or "未命名文件", 180).strip() or "未命名文件",
        "kind": kind,
        "mime": mime,
        "size": max(0, size),
        "source": clamp_text(raw_item.get("source") or "space_upload", 64).strip(),
        "content": content,
        "summary": clamp_text(raw_item.get("summary"), 4000).strip(),
        "audioDataUrl": audio_data_url if kind == "audio" or mime.startswith("audio/") else "",
        "fileDataUrl": file_data_url or (audio_data_url if kind == "audio" or mime.startswith("audio/") else ""),
        "addedAt": ts,
        "updatedAt": ts,
    }
    if not item["summary"]:
        item["summary"] = summarize_space_item(
            name=item["name"],
            kind=item["kind"],
            mime=item["mime"],
            size=item["size"],
            source=item["source"],
            content=item["content"],
            has_file=bool(item["fileDataUrl"] or item["audioDataUrl"]),
        )
    return item


def find_space_by_id(space_payload, space_id):
    for space in (space_payload or {}).get("spaces", []):
        if str((space or {}).get("id") or "").strip() == str(space_id or "").strip():
            return space
    return None


def find_space_item(space_payload, item_id):
    target_id = str(item_id or "").strip()
    if not target_id:
        return None, None

    for space in (space_payload or {}).get("spaces", []):
        items = space.get("items", []) if isinstance(space, dict) else []
        for item in items if isinstance(items, list) else []:
            if str((item or {}).get("id") or "").strip() == target_id:
                return space, item
    return None, None


def merge_space_item_lists(existing_items, incoming_items):
    merged = [
        deep_copy_data(item, {})
        for item in existing_items if isinstance(item, dict)
    ]
    id_map = {
        str(item.get("id") or "").strip(): idx
        for idx, item in enumerate(merged)
        if str(item.get("id") or "").strip()
    }
    fingerprints = {
        build_space_item_fingerprint(item)
        for item in merged
        if build_space_item_fingerprint(item)
    }
    added_count = 0

    for raw_item in incoming_items if isinstance(incoming_items, list) else []:
        if not isinstance(raw_item, dict):
            continue
        payload = deep_copy_data(raw_item, {})
        item_id = str(payload.get("id") or "").strip()
        fingerprint = build_space_item_fingerprint(payload)

        if item_id and item_id in id_map:
            idx = id_map[item_id]
            current = merged[idx]
            current_updated = int(current.get("updatedAt") or current.get("addedAt") or 0)
            incoming_updated = int(payload.get("updatedAt") or payload.get("addedAt") or 0)
            if incoming_updated >= current_updated:
                merged[idx] = payload
            continue

        if fingerprint and fingerprint in fingerprints:
            continue

        merged.append(payload)
        if item_id:
            id_map[item_id] = len(merged) - 1
        if fingerprint:
            fingerprints.add(fingerprint)
        added_count += 1

    merged.sort(key=lambda item: int(item.get("addedAt") or 0), reverse=True)
    return merged[:SPACE_MAX_ITEM_COUNT], added_count


def merge_space_payloads(existing_payload, incoming_payload):
    current = deep_copy_data(existing_payload or {}, {"activeEntrySpaceId": "", "spaces": []})
    incoming = deep_copy_data(incoming_payload or {}, {"activeEntrySpaceId": "", "spaces": []})
    current_spaces = current.get("spaces", []) if isinstance(current.get("spaces"), list) else []
    incoming_spaces = incoming.get("spaces", []) if isinstance(incoming.get("spaces"), list) else []

    merged_spaces = [
        deep_copy_data(space, {})
        for space in current_spaces if isinstance(space, dict)
    ]
    space_map = {
        str(space.get("id") or "").strip(): idx
        for idx, space in enumerate(merged_spaces)
        if str(space.get("id") or "").strip()
    }

    added_spaces = 0
    added_items = 0

    for raw_space in incoming_spaces:
        if not isinstance(raw_space, dict):
            continue

        payload = deep_copy_data(raw_space, {})
        space_id = str(payload.get("id") or "").strip()
        if not space_id:
            continue

        if space_id in space_map:
            idx = space_map[space_id]
            target_space = merged_spaces[idx]
            merged_items, item_added = merge_space_item_lists(
                target_space.get("items", []),
                payload.get("items", []),
            )
            target_space["items"] = merged_items
            target_space["name"] = normalize_space_name(target_space.get("name") or payload.get("name"), "新空间")
            target_space["updatedAt"] = max(
                int(target_space.get("updatedAt") or target_space.get("createdAt") or 0),
                int(payload.get("updatedAt") or payload.get("createdAt") or 0),
            )
            added_items += item_added
            continue

        new_space = deep_copy_data(payload, {})
        new_space["name"] = normalize_space_name(new_space.get("name"), "新空间")
        new_space["items"] = (new_space.get("items", []) if isinstance(new_space.get("items"), list) else [])[:SPACE_MAX_ITEM_COUNT]
        merged_spaces.append(new_space)
        space_map[space_id] = len(merged_spaces) - 1
        added_spaces += 1
        added_items += len(new_space.get("items", []))

    valid_ids = [str(space.get("id") or "").strip() for space in merged_spaces if str(space.get("id") or "").strip()]
    active_space_id = str(current.get("activeEntrySpaceId") or "").strip()
    if active_space_id not in valid_ids:
        incoming_active = str(incoming.get("activeEntrySpaceId") or "").strip()
        active_space_id = incoming_active if incoming_active in valid_ids else (valid_ids[0] if valid_ids else "")

    merged_spaces.sort(key=lambda space: int(space.get("createdAt") or 0), reverse=True)
    return {
        "activeEntrySpaceId": active_space_id,
        "spaces": merged_spaces,
    }, {
        "spaces": added_spaces,
        "items": added_items,
    }


def serialize_space_item(item, user_id):
    auth_token = extract_bearer_token()
    preview_available = bool(
        str(item.get("audioDataUrl") or "").strip()
        or str(item.get("fileDataUrl") or "").strip()
        or str(item.get("content") or "").strip()
    )
    preview_url = build_api_absolute_url(
        f"/api/spaces/items/{requests.utils.quote(str(item.get('id') or ''), safe='')}/preview",
        {
            "user_id": user_id,
            "auth_token": auth_token or None,
        },
    ) if preview_available else ""

    return {
        "id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or "未命名文件"),
        "kind": str(item.get("kind") or "document"),
        "mime": str(item.get("mime") or ""),
        "size": int(item.get("size") or 0),
        "source": str(item.get("source") or ""),
        "content": str(item.get("content") or ""),
        "summary": str(item.get("summary") or ""),
        "addedAt": int(item.get("addedAt") or now_ms()),
        "updatedAt": int(item.get("updatedAt") or item.get("addedAt") or now_ms()),
        "previewUrl": preview_url,
        "previewAvailable": preview_available,
    }


def serialize_space(space, user_id):
    items = [
        serialize_space_item(item, user_id)
        for item in (space.get("items", []) if isinstance(space.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    items.sort(key=lambda item: int(item.get("addedAt") or 0), reverse=True)
    return {
        "id": str(space.get("id") or "").strip(),
        "name": normalize_space_name(space.get("name"), "新空间"),
        "createdAt": int(space.get("createdAt") or now_ms()),
        "updatedAt": int(space.get("updatedAt") or space.get("createdAt") or now_ms()),
        "items": items[:SPACE_MAX_ITEM_COUNT],
        "itemCount": len(items),
    }


def normalize_auth_username(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@-]{2,31}", text):
        return ""
    return text


def normalize_display_name(value, fallback="同学"):
    text = str(value or "").strip()
    if not text:
        text = str(fallback or "同学").strip() or "同学"
    return text[:24]


def normalize_auth_locale(value):
    locale = str(value or "").strip().upper()
    return "EN" if locale == "EN" else "CN"


def normalize_guest_binding_user_id(value, target_username=""):
    guest_user_id = str(value or "").strip()
    target_user_id = str(target_username or "").strip()
    if not guest_user_id or guest_user_id == target_user_id:
        return ""
    return guest_user_id


def hash_session_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def build_public_auth_user(user):
    if not isinstance(user, dict):
        return {
            "user_id": "",
            "username": "",
            "display_name": "同学",
            "locale": "CN",
        }

    username = str(user.get("username") or "").strip()
    return {
        "user_id": username,
        "username": username,
        "display_name": normalize_display_name(user.get("display_name"), fallback=username or "同学"),
        "locale": normalize_auth_locale(user.get("locale")),
        "created_at": str(user.get("created_at") or "").strip(),
        "updated_at": str(user.get("updated_at") or "").strip(),
        "last_login_at": str(user.get("last_login_at") or "").strip(),
    }


def create_auth_session_payload(user):
    now = utcnow()
    expires_at = now + timedelta(days=AUTH_TOKEN_TTL_DAYS)
    raw_token = secrets.token_urlsafe(32)
    session_data = {
        "session_id": uuid.uuid4().hex,
        "username": str(user.get("username") or "").strip(),
        "token_hash": hash_session_token(raw_token),
        "expires_at": expires_at.isoformat(),
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "revoked_at": None,
    }
    upsert_auth_session(session_data)
    return {
        "token": raw_token,
        "expires_at": session_data["expires_at"],
        "session_id": session_data["session_id"],
    }


def extract_bearer_token():
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    token = (request.headers.get("X-Auth-Token", "") or "").strip()
    if token:
        return token

    token = (request.args.get("auth_token", "") or "").strip()
    if token:
        return token

    return ""


def resolve_auth_context(touch=False):
    token = extract_bearer_token()
    if not token:
        return None

    token_hash = hash_session_token(token)
    session_data = get_auth_session_by_token_hash(token_hash)
    if not session_data:
        return None

    if session_data.get("revoked_at"):
        return None

    expires_at = session_data.get("expires_at")
    try:
        expires_dt = datetime.fromisoformat(expires_at) if expires_at else None
    except Exception:
        expires_dt = None

    if not expires_dt or expires_dt <= utcnow():
        revoke_auth_session(token_hash, iso_now())
        return None

    user = get_auth_user(session_data.get("username", ""))
    if not user:
        return None

    if touch:
        last_seen = session_data.get("last_seen_at")
        try:
            last_seen_dt = datetime.fromisoformat(last_seen) if last_seen else None
        except Exception:
            last_seen_dt = None
        if (not last_seen_dt) or ((utcnow() - last_seen_dt).total_seconds() >= AUTH_TOUCH_INTERVAL_SECONDS):
            touch_auth_session(token_hash, iso_now())

    return {
        "token": token,
        "token_hash": token_hash,
        "session": session_data,
        "user": user,
    }


def require_auth_context():
    auth_context = resolve_auth_context(touch=True)
    if auth_context:
        return auth_context, None

    return None, error_response(
        get_request_id(),
        401,
        "AUTH_REQUIRED",
        "请先登录后再访问",
    )


def normalize_request_user_id(value, fallback="default_user"):
    text = str(value or "").strip()
    return text or str(fallback or "default_user").strip() or "default_user"


def resolve_request_user_id(explicit_user_id=None, touch_session=True, fallback="default_user"):
    token = extract_bearer_token()
    if token:
        auth_context = resolve_auth_context(touch=touch_session)
        if not auth_context:
            return None, error_response(
                get_request_id(),
                401,
                "AUTH_REQUIRED",
                "当前登录状态已失效，请重新登录",
            )

        auth_user_id = normalize_request_user_id(
            (auth_context.get("user") or {}).get("username"),
            fallback=fallback,
        )
        requested_user_id = normalize_request_user_id(explicit_user_id, fallback=fallback)
        if requested_user_id != auth_user_id:
            logger.info(
                "override request user_id=%s with authenticated user=%s for path=%s",
                requested_user_id,
                auth_user_id,
                request.path,
            )
        return auth_user_id, None

    return normalize_request_user_id(explicit_user_id, fallback=fallback), None


def resolve_request_user_id_from_args(key="user_id", fallback="default_user", touch_session=True):
    return resolve_request_user_id(
        request.args.get(key, fallback),
        touch_session=touch_session,
        fallback=fallback,
    )


def resolve_request_user_id_from_json(data=None, key="user_id", fallback="default_user", touch_session=True):
    body = data if isinstance(data, dict) else {}
    return resolve_request_user_id(
        body.get(key, fallback),
        touch_session=touch_session,
        fallback=fallback,
    )


def merge_plan_lists(existing_plans, incoming_plans):
    merged = []
    existing_signatures = set()
    existing_ids = set()
    added_count = 0

    for item in existing_plans if isinstance(existing_plans, list) else []:
        if not isinstance(item, dict):
            continue
        payload = deep_copy_data(item, {})
        merged.append(payload)
        existing_signatures.add(stable_json_key(payload))
        plan_id = str(payload.get("id") or "").strip()
        if plan_id:
            existing_ids.add(plan_id)

    for item in incoming_plans if isinstance(incoming_plans, list) else []:
        if not isinstance(item, dict):
            continue
        payload = deep_copy_data(item, {})
        signature = stable_json_key(payload)
        if signature in existing_signatures:
            continue

        plan_id = str(payload.get("id") or "").strip()
        if not plan_id or plan_id in existing_ids:
            payload["id"] = str(uuid.uuid4())

        merged.append(payload)
        existing_signatures.add(stable_json_key(payload))
        existing_ids.add(str(payload.get("id") or "").strip())
        added_count += 1

    return merged, added_count


def choose_earlier_iso(first_value, second_value):
    first = str(first_value or "").strip()
    second = str(second_value or "").strip()
    if not first:
        return second or None
    if not second:
        return first or None
    return first if first <= second else second


def choose_later_iso(first_value, second_value):
    first = str(first_value or "").strip()
    second = str(second_value or "").strip()
    if not first:
        return second or None
    if not second:
        return first or None
    return first if first >= second else second


def merge_user_knowledge_payloads(existing_knowledge, incoming_knowledge):
    current = normalize_user_knowledge(deep_copy_data(existing_knowledge, {}))
    incoming = normalize_user_knowledge(deep_copy_data(incoming_knowledge, {}))

    concept_map = {}
    ordered_concepts = []
    for item in current.get("concepts", []):
        if not isinstance(item, dict):
            continue
        concept = normalize_concept_name(item.get("concept"))
        if not concept or concept in concept_map:
            continue
        payload = deep_copy_data(item, {})
        payload["concept"] = concept
        concept_map[concept] = payload
        ordered_concepts.append(payload)

    added_concepts = 0
    for item in incoming.get("concepts", []):
        if not isinstance(item, dict):
            continue
        concept = normalize_concept_name(item.get("concept"))
        if not concept:
            continue

        payload = deep_copy_data(item, {})
        payload["concept"] = concept

        if concept not in concept_map:
            concept_map[concept] = payload
            ordered_concepts.append(payload)
            added_concepts += 1
            continue

        target = concept_map[concept]
        target["description"] = str(target.get("description") or payload.get("description") or "").strip()
        try:
            target["mastery"] = max(float(target.get("mastery", 0.0) or 0.0), float(payload.get("mastery", 0.0) or 0.0))
        except Exception:
            target["mastery"] = float(target.get("mastery", 0.0) or 0.0)
        try:
            target["difficulty"] = max(float(target.get("difficulty", 0.0) or 0.0), float(payload.get("difficulty", 0.0) or 0.0))
        except Exception:
            pass
        try:
            target["review_count"] = max(int(target.get("review_count", 0) or 0), int(payload.get("review_count", 0) or 0))
        except Exception:
            pass
        target["first_seen"] = choose_earlier_iso(target.get("first_seen"), payload.get("first_seen"))
        target["last_seen"] = choose_later_iso(target.get("last_seen"), payload.get("last_seen"))
        target["last_reviewed"] = choose_later_iso(target.get("last_reviewed"), payload.get("last_reviewed"))

    relation_map = {}
    ordered_relations = []
    for rel in current.get("relations", []):
        if not isinstance(rel, dict):
            continue
        key = (
            normalize_concept_name(rel.get("source")),
            normalize_concept_name(rel.get("target")),
            str(rel.get("type") or "相关").strip() or "相关",
        )
        if not key[0] or not key[1]:
            continue
        payload = deep_copy_data(rel, {})
        payload["source"] = key[0]
        payload["target"] = key[1]
        payload["type"] = key[2]
        relation_map[key] = payload
        ordered_relations.append(payload)

    added_relations = 0
    for rel in incoming.get("relations", []):
        if not isinstance(rel, dict):
            continue
        key = (
            normalize_concept_name(rel.get("source")),
            normalize_concept_name(rel.get("target")),
            str(rel.get("type") or "相关").strip() or "相关",
        )
        if not key[0] or not key[1] or key[0] == key[1]:
            continue

        payload = deep_copy_data(rel, {})
        payload["source"] = key[0]
        payload["target"] = key[1]
        payload["type"] = key[2]

        if key not in relation_map:
            relation_map[key] = payload
            ordered_relations.append(payload)
            added_relations += 1
            continue

        target = relation_map[key]
        try:
            target["score"] = max(float(target.get("score", 0.0) or 0.0), float(payload.get("score", 0.0) or 0.0))
        except Exception:
            pass
        target["evidence"] = str(target.get("evidence") or payload.get("evidence") or "").strip()
        target["source_text"] = target.get("source_text") or payload.get("source_text") or ""
        target["created_at"] = choose_earlier_iso(target.get("created_at"), payload.get("created_at"))
        target["from"] = target.get("from") or payload.get("from")

    deleted_concepts = list(dict.fromkeys([
        *current.get("deleted_concepts", []),
        *incoming.get("deleted_concepts", []),
    ]))

    return {
        "concepts": ordered_concepts,
        "relations": ordered_relations,
        "deleted_concepts": deleted_concepts,
    }, {
        "concepts": added_concepts,
        "relations": added_relations,
    }


def merge_user_event_lists(existing_items, incoming_items):
    merged = []
    existing_signatures = set()
    added_count = 0

    for item in existing_items if isinstance(existing_items, list) else []:
        if not isinstance(item, dict):
            continue
        payload = deep_copy_data(item, {})
        merged.append(payload)
        existing_signatures.add(stable_json_key(payload))

    for item in incoming_items if isinstance(incoming_items, list) else []:
        if not isinstance(item, dict):
            continue
        payload = deep_copy_data(item, {})
        signature = stable_json_key(payload)
        if signature in existing_signatures:
            continue
        merged.append(payload)
        existing_signatures.add(signature)
        added_count += 1

    return merged, added_count


def bind_guest_user_data_to_auth_user(guest_user_id, target_user_id):
    source_user_id = normalize_guest_binding_user_id(guest_user_id, target_user_id)
    summary = {
        "guest_user_id": source_user_id,
        "user_id": normalize_request_user_id(target_user_id, fallback="default_user"),
        "migrated": False,
        "plans": 0,
        "spaces": 0,
        "space_items": 0,
        "concepts": 0,
        "relations": 0,
        "knowledge_updated": False,
        "events": 0,
        "message": "",
    }

    if not source_user_id:
        summary["message"] = "当前没有可绑定的访客数据"
        return summary

    target_plans = deep_copy_data(get_user_plans(target_user_id), [])
    source_plans = deep_copy_data(get_user_plans(source_user_id), [])
    merged_plans, added_plans = merge_plan_lists(target_plans, source_plans)
    if added_plans > 0:
        set_user_plans(target_user_id, merged_plans)
        summary["plans"] = added_plans

    target_knowledge = deep_copy_data(get_user_knowledge(target_user_id), {})
    source_knowledge = deep_copy_data(get_user_knowledge(source_user_id), {})
    normalized_target_knowledge = normalize_user_knowledge(deep_copy_data(target_knowledge, {}))
    merged_knowledge, knowledge_delta = merge_user_knowledge_payloads(normalized_target_knowledge, source_knowledge)
    if stable_json_key(normalized_target_knowledge) != stable_json_key(merged_knowledge):
        set_user_knowledge(target_user_id, merged_knowledge)
        summary["concepts"] = knowledge_delta["concepts"]
        summary["relations"] = knowledge_delta["relations"]
        summary["knowledge_updated"] = True

    target_space_payload = deep_copy_data(get_user_space_payload(target_user_id), {"activeEntrySpaceId": "", "spaces": []})
    source_space_payload = deep_copy_data(get_user_space_payload(source_user_id), {"activeEntrySpaceId": "", "spaces": []})
    merged_spaces, space_delta = merge_space_payloads(target_space_payload, source_space_payload)
    if stable_json_key(target_space_payload) != stable_json_key(merged_spaces):
        set_user_space_payload(target_user_id, merged_spaces)
        summary["spaces"] = int(space_delta.get("spaces", 0) or 0)
        summary["space_items"] = int(space_delta.get("items", 0) or 0)

    event_added = 0
    for suffix in AUTH_BINDABLE_EVENT_SUFFIXES:
        target_events = deep_copy_data(load_user_event_list(target_user_id, suffix), [])
        source_events = deep_copy_data(load_user_event_list(source_user_id, suffix), [])
        merged_events, added_count = merge_user_event_lists(target_events, source_events)
        if added_count > 0:
            save_user_event_list(target_user_id, suffix, merged_events)
            event_added += added_count
    summary["events"] = event_added

    summary["migrated"] = any([
        summary["plans"] > 0,
        summary["spaces"] > 0,
        summary["space_items"] > 0,
        summary["concepts"] > 0,
        summary["relations"] > 0,
        summary["knowledge_updated"],
        summary["events"] > 0,
    ])

    if summary["migrated"]:
        try:
            build_learning_profile(target_user_id)
        except Exception as exc:
            logger.exception("failed to rebuild profile after auth binding for user=%s: %s", target_user_id, exc)
        summary["message"] = "已将访客数据绑定到当前账号"
    else:
        summary["message"] = "当前没有可绑定的访客数据"

    return summary


def load_simple_env_files():
    """读取本地 .env 文件（仅填充尚未设置的环境变量）。"""
    candidates = [
        os.path.join(BACKEND_DIR, "config", ".env"),
        os.path.join(BACKEND_DIR, ".env"),
        os.path.join(PROJECT_ROOT, ".env"),
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
from .services.database import (
    delete_auth_user_account,
    delete_user_space_payload,
    get_auth_session_by_token_hash,
    get_auth_user,
    get_user_plans,
    set_user_plans,
    get_user_knowledge,
    set_user_knowledge,
    get_user_profile,
    get_user_space_payload,
    set_user_profile,
    set_user_space_payload,
    get_user_event_list as db_get_user_event_list,
    append_user_event as db_append_user_event,
    get_storage_info,
    init_storage,
    load_json,
    revoke_auth_session,
    save_json,
    touch_auth_session,
    upsert_auth_session,
    upsert_auth_user,
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
    user_concept_names = {
        (item.get("concept") or "").strip()
        for item in concepts
        if isinstance(item, dict) and (item.get("concept") or "").strip()
    }

    # 先给默认概念注入一组可视化友好的初始掌握度
    for item in DEFAULT_CONCEPTS:
        if item["concept"] in deleted_concepts:
            continue
        if item["concept"] in user_concept_names:
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
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = text.replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
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


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def infer_question_answer_duration_seconds(user_id, question_id, now_dt=None):
    question_key = str(question_id or "").strip()
    if not question_key:
        return None

    now_value = now_dt if isinstance(now_dt, datetime) else datetime.now()
    draw_logs = load_user_event_list(user_id, "question_draw")
    matched_dt = None
    for item in reversed(draw_logs if isinstance(draw_logs, list) else []):
        if str(item.get("question_id") or "").strip() != question_key:
            continue
        matched_dt = parse_datetime_safe(item.get("timestamp"))
        if matched_dt:
            break

    if not matched_dt:
        return None

    duration_seconds = (now_value - matched_dt).total_seconds()
    if duration_seconds < 0 or duration_seconds > 7200:
        return None
    return round(duration_seconds, 3)


def collect_concept_question_history(user_id, concept, current_record=None, limit=10):
    concept_text = normalize_concept_name(concept or "")
    history = []

    for item in load_user_event_list(user_id, "question_answer"):
        if not isinstance(item, dict):
            continue
        if normalize_concept_name(item.get("concept") or "") != concept_text:
            continue
        history.append(deep_copy_data(item, {}))

    if isinstance(current_record, dict) and concept_text and normalize_concept_name(current_record.get("concept") or "") == concept_text:
        history.append(deep_copy_data(current_record, {}))

    history.sort(key=lambda item: parse_datetime_safe(item.get("timestamp")) or datetime.min)
    return history[-max(1, int(limit)):]


def get_concept_mastery_from_knowledge(user_id, concept):
    concept_text = normalize_concept_name(concept or "")
    if not concept_text:
        return None

    knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    for item in knowledge.get("concepts", []):
        if normalize_concept_name(item.get("concept") or "") != concept_text:
            continue
        return safe_float(item.get("mastery"), 0.0)
    return None


def update_concept_mastery_snapshot(user_id, concept, mastery_assessment, answered_at=None):
    concept_text = normalize_concept_name(concept or "")
    if not concept_text or not isinstance(mastery_assessment, dict):
        return {}

    timestamp = (
        str(answered_at or "").strip()
        or str(mastery_assessment.get("最近作答时间") or "").strip()
        or datetime.now().isoformat()
    )

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    concept_list = user_knowledge.get("concepts", [])
    target = None
    for item in concept_list:
        if normalize_concept_name(item.get("concept") or "") == concept_text:
            target = item
            break

    if target is None:
        target = {
            "concept": concept_text,
            "first_seen": timestamp,
        }
        concept_list.append(target)

    target["mastery"] = max(0.0, min(1.0, safe_float(mastery_assessment.get("掌握度"), 0.0)))
    target["mastery_status"] = mastery_assessment.get("状态", "一般")
    target["accuracy"] = safe_float(mastery_assessment.get("正确率"), 0.0)
    target["raw_accuracy"] = safe_float(mastery_assessment.get("原始正确率"), 0.0)
    target["recent_accuracy"] = safe_float(mastery_assessment.get("最近正确率"), 0.0)
    target["practice_count"] = int(mastery_assessment.get("作答次数", 0) or 0)
    target["time_score"] = safe_float(mastery_assessment.get("时间得分"), 0.0)
    target["practice_score"] = safe_float(mastery_assessment.get("练习系数"), 0.0)
    target["forgetting_factor"] = safe_float(mastery_assessment.get("遗忘系数"), 1.0)
    target["base_mastery"] = safe_float(mastery_assessment.get("基础掌握度"), target["mastery"])
    target["median_answer_seconds"] = mastery_assessment.get("中位作答时间")
    target["standard_answer_seconds"] = mastery_assessment.get("标准作答时间")
    target["time_ratio"] = mastery_assessment.get("时间比值")
    target["last_seen"] = timestamp
    target["last_practiced"] = timestamp
    target["last_reviewed"] = timestamp
    target["review_count"] = max(int(target.get("review_count", 0) or 0), int(mastery_assessment.get("作答次数", 0) or 0))

    user_knowledge["concepts"] = concept_list
    set_user_knowledge(user_id, user_knowledge)

    graph_sync = sync_mastery_update(
        user_id=user_id,
        concept=concept_text,
        mastery=target["mastery"],
        review_count=int(target.get("review_count", 0) or 0),
        last_reviewed=timestamp,
    )
    return {
        "concept": concept_text,
        "mastery": target["mastery"],
        "graph_sync": graph_sync,
    }


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


def infer_mapping_content_type(value):
    source = str(value or "").strip().lower()
    if not source:
        return "generic"
    if any(token in source for token in ("question", "qa", "quiz", "题")):
        return "question"
    if any(token in source for token in ("video", "subtitle", "caption", "transcript", "视频", "字幕")):
        return "video"
    if any(token in source for token in ("note", "ocr", "image", "笔记", "截图")):
        return "note"
    return "generic"


def normalize_learning_behavior_item(raw_item, default_content_type="generic"):
    if isinstance(raw_item, str):
        text = raw_item.strip()
        if not text:
            return None
        return {
            "original_content": text,
            "match_text": text,
            "content_type": infer_mapping_content_type(default_content_type),
        }

    if not isinstance(raw_item, dict):
        return None

    raw_type = raw_item.get("content_type") or raw_item.get("source") or default_content_type
    content_type = infer_mapping_content_type(raw_type)

    pieces = []
    for key in ("title", "question", "text", "subtitle", "transcript", "content", "note", "ocr_text", "summary"):
        value = str(raw_item.get(key) or "").strip()
        if value and value not in pieces:
            pieces.append(value)

    options = raw_item.get("options", [])
    if isinstance(options, list):
        options_text = " ".join(str(item or "").strip() for item in options if str(item or "").strip())
        if options_text and options_text not in pieces:
            pieces.append(options_text)

    if not pieces:
        return None

    merged_text = " ".join(pieces).strip()
    if not merged_text:
        return None

    return {
        "original_content": merged_text,
        "match_text": merged_text,
        "content_type": content_type,
    }


def collect_learning_behavior_items(payload):
    items = []
    body = payload if isinstance(payload, dict) else {}

    raw_items = body.get("items", [])
    if isinstance(raw_items, list):
        for item in raw_items:
            normalized = normalize_learning_behavior_item(item)
            if normalized:
                items.append(normalized)

    for field, content_type in (
        ("question_texts", "question"),
        ("video_texts", "video"),
        ("note_texts", "note"),
    ):
        values = body.get(field, [])
        if not isinstance(values, list):
            continue
        for item in values:
            normalized = normalize_learning_behavior_item(item, default_content_type=content_type)
            if normalized:
                items.append(normalized)

    return items


def build_concept_mapping_sources(user_id):
    concept_map = {}

    def ensure_bucket(concept, description=""):
        concept_name = normalize_concept_name(concept)
        if not concept_name:
            return None
        bucket = concept_map.setdefault(
            concept_name,
            {
                "concept": concept_name,
                "description": "",
                "aliases": [],
                "support_texts": [],
            },
        )
        if description and not bucket.get("description"):
            bucket["description"] = str(description).strip()
        return bucket

    for item in DEFAULT_CONCEPTS:
        ensure_bucket(item.get("concept"), description=item.get("description"))

    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    for item in user_knowledge.get("concepts", []):
        if not isinstance(item, dict):
            continue
        bucket = ensure_bucket(item.get("concept"), description=item.get("description"))
        if not bucket:
            continue
        for key in ("description",):
            text = str(item.get(key) or "").strip()
            if text and text not in bucket["support_texts"]:
                bucket["support_texts"].append(text)

    bank, _ = build_question_bank_for_user(user_id)
    for item in bank:
        if not isinstance(item, dict):
            continue
        bucket = ensure_bucket(item.get("concept"))
        if not bucket:
            continue
        for key in ("question", "analysis"):
            text = str(item.get(key) or "").strip()
            if text and text not in bucket["support_texts"]:
                bucket["support_texts"].append(text)
        options = item.get("options", [])
        if isinstance(options, list):
            for option in options[:4]:
                option_text = str(option or "").strip()
                if option_text and option_text not in bucket["support_texts"]:
                    bucket["support_texts"].append(option_text)

    return list(concept_map.values())


def build_concept_mapping_runtime(user_id):
    stopwords = get_configured_concept_stopwords()
    concept_sources = build_concept_mapping_sources(user_id)
    profiles = build_concept_profiles(concept_sources, stopwords=stopwords, max_keywords_per_concept=10)
    return {
        "stopwords": stopwords,
        "profiles": profiles,
        "concept_library_size": len(profiles),
    }


CONFUSION_SIGNAL_TOKENS = (
    "不会",
    "不会做",
    "不太会",
    "看不懂",
    "没看懂",
    "不懂",
    "没思路",
    "不知道怎么做",
)


def contains_confusion_signal(text):
    content = str(text or "").strip()
    if not content:
        return False
    return any(token in content for token in CONFUSION_SIGNAL_TOKENS)


def normalize_topic_list(items):
    normalized = []
    for item in items if isinstance(items, list) else []:
        topic = normalize_concept_name(item)
        if topic and topic not in normalized:
            normalized.append(topic)
    return normalized


def extract_topics_from_qa_item(item):
    if not isinstance(item, dict):
        return []

    topics = normalize_topic_list(item.get("topics"))
    if topics:
        return topics[:6]

    merged = " ".join([
        str(item.get("question") or "").strip(),
        str(item.get("answer") or "").strip(),
    ]).strip()
    return normalize_topic_list(detect_concepts_from_text(merged))[:6]


def build_wrong_question_entry(source, question, user_answer, concept="", topics=None, extra=None):
    topic_list = normalize_topic_list(topics)
    concept_text = normalize_concept_name(concept or (topic_list[0] if topic_list else ""))
    payload = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "source": str(source or "wrong_question").strip() or "wrong_question",
        "question": str(question or "").strip(),
        "user_answer": str(user_answer or "").strip(),
        "concept": concept_text,
        "topics": topic_list,
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            payload[key] = value
    return payload


def sync_wrong_question_bank_from_logs(user_id, question_answer_logs, qa_logs, existing_wrong_logs):
    existing = [
        deep_copy_data(item, {})
        for item in (existing_wrong_logs if isinstance(existing_wrong_logs, list) else [])
        if isinstance(item, dict)
    ]
    existing_keys = set()
    for item in existing:
        key = str(item.get("source_key") or "").strip()
        if key:
            existing_keys.add(key)

    for item in question_answer_logs if isinstance(question_answer_logs, list) else []:
        if not isinstance(item, dict):
            continue
        if bool(item.get("is_correct", False)):
            continue

        timestamp = str(item.get("timestamp") or "").strip()
        question_id = str(item.get("question_id") or "").strip()
        concept = normalize_concept_name(item.get("concept") or "")
        question_text = str(item.get("question") or "").strip()
        user_answer = str(item.get("user_answer") or "").strip()
        source_key = f"question_answer::{timestamp}::{question_id or concept or question_text[:48]}"
        if source_key in existing_keys:
            continue

        wrong_item = build_wrong_question_entry(
            source="question_answer",
            question=question_text or f"{concept or '综合'} 练习题",
            user_answer=user_answer,
            concept=concept,
            topics=[concept] if concept else [],
            extra={
                "source_key": source_key,
                "question_id": question_id,
                "difficulty": item.get("difficulty"),
                
                "question_type": item.get("question_type"),
                "expected_answer": item.get("expected_answer") or item.get("correct_answer") or "",
                "score": float(item.get("score", 0.0) or 0.0),
                "is_correct": False,
            },
        )
        append_user_event(user_id, "wrong_question", wrong_item)
        existing.append(wrong_item)
        existing_keys.add(source_key)

    for item in qa_logs if isinstance(qa_logs, list) else []:
        if not isinstance(item, dict):
            continue
        question_text = str(item.get("question") or "").strip()
        if not contains_confusion_signal(question_text):
            continue

        timestamp = str(item.get("timestamp") or "").strip()
        source_key = f"qa_confusion::{timestamp}::{question_text[:80]}"
        if source_key in existing_keys:
            continue

        topics = extract_topics_from_qa_item(item)
        wrong_item = build_wrong_question_entry(
            source="qa_confusion",
            question=question_text,
            user_answer="不会/看不懂",
            concept=topics[0] if topics else "",
            topics=topics,
            extra={
                "source_key": source_key,
                "answer_excerpt": str(item.get("answer") or "")[:400],
                "is_correct": False,
            },
        )
        append_user_event(user_id, "wrong_question", wrong_item)
        existing.append(wrong_item)
        existing_keys.add(source_key)

    existing.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=False)
    return existing


def parse_space_item_datetime(item):
    if not isinstance(item, dict):
        return None

    for key in ["updatedAt", "addedAt", "timestamp"]:
        value = item.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000.0)
            except Exception:
                continue

        text = str(value).strip()
        if not text:
            continue
        if text.isdigit():
            try:
                return datetime.fromtimestamp(int(text) / 1000.0)
            except Exception:
                continue

        dt = parse_datetime_safe(text)
        if dt:
            return dt

    return None


def extract_topics_from_content_item(item, detect_topics_fn=None):
    if not isinstance(item, dict):
        return []

    topics = normalize_topic_list(item.get("topics"))
    if topics:
        return topics[:6]

    if not callable(detect_topics_fn):
        return []

    merged = " ".join([
        str(item.get("title") or "").strip(),
        str(item.get("content") or "").strip(),
    ]).strip()
    if not merged:
        return []
    return normalize_topic_list(detect_topics_fn(merged))[:6]


def extract_topics_from_space_item(item, detect_topics_fn=None):
    if not isinstance(item, dict):
        return []

    topics = normalize_topic_list(item.get("topics"))
    if topics:
        return topics[:6]

    if not callable(detect_topics_fn):
        return []

    content = str(item.get("content") or "").strip()
    name = str(item.get("name") or "").strip()
    summary = str(item.get("summary") or "").strip()
    kind = str(item.get("kind") or "").strip().lower()

    text_parts = []
    if content:
        text_parts.append(content[:2000])
    elif kind in {"note", "link", "text", "document"} and summary:
        text_parts.append(summary[:800])
    if name and name != "未命名文件":
        text_parts.append(name[:120])

    merged = "\n".join([part for part in text_parts if part]).strip()
    if not merged:
        return []
    return normalize_topic_list(detect_topics_fn(merged))[:6]


def build_dashboard_hidden_tables(
    content_logs,
    qa_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    behavior_logs,
    space_payload=None,
    detect_topics_fn=None,
):
    topic_daily_counter = defaultdict(Counter)
    study_window_daily_counter = defaultdict(Counter)
    study_window_daily_duration = defaultdict(lambda: defaultdict(float))
    study_window_total_counter = Counter()
    study_window_total_duration = defaultdict(float)

    def mark_study_window(dt, duration_seconds=0.0):
        if not dt:
            return
        label = f"{dt.hour:02d}:00-{(dt.hour + 2) % 24:02d}:00"
        date_key = dt.date().isoformat()
        study_window_daily_counter[date_key][label] += 1
        study_window_total_counter[label] += 1
        if duration_seconds > 0:
            study_window_daily_duration[date_key][label] += duration_seconds
            study_window_total_duration[label] += duration_seconds

    for item in content_logs if isinstance(content_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        date_key = dt.date().isoformat()
        for topic in extract_topics_from_content_item(item, detect_topics_fn=detect_topics_fn):
            topic_daily_counter[date_key][topic] += 1
        mark_study_window(dt)

    for item in qa_logs if isinstance(qa_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        date_key = dt.date().isoformat()
        for topic in extract_topics_from_qa_item(item):
            topic_daily_counter[date_key][topic] += 1
        mark_study_window(dt)

    for item in question_draw_logs if isinstance(question_draw_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        concept = normalize_concept_name(item.get("concept") or "")
        if not concept:
            continue
        topic_daily_counter[dt.date().isoformat()][concept] += 1
        mark_study_window(dt)

    for item in question_answer_logs if isinstance(question_answer_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        concept = normalize_concept_name(item.get("concept") or "")
        if not concept:
            continue
        topic_daily_counter[dt.date().isoformat()][concept] += 1
        mark_study_window(dt)

    for item in diagnosis_logs if isinstance(diagnosis_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        question_text = str(item.get("question") or "").strip()
        for topic in normalize_topic_list(detect_topics_fn(question_text) if callable(detect_topics_fn) and question_text else []):
            topic_daily_counter[dt.date().isoformat()][topic] += 1
        mark_study_window(dt)

    spaces = (space_payload or {}).get("spaces", []) if isinstance((space_payload or {}).get("spaces"), list) else []
    for space in spaces:
        if not isinstance(space, dict):
            continue
        for item in space.get("items", []) if isinstance(space.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            dt = parse_space_item_datetime(item)
            if not dt:
                continue
            date_key = dt.date().isoformat()
            for topic in extract_topics_from_space_item(item, detect_topics_fn=detect_topics_fn):
                topic_daily_counter[date_key][topic] += 1
            mark_study_window(dt)

    topic_total_counter = Counter()
    topic_daily_table = []
    for date_key in sorted(topic_daily_counter.keys()):
        counts = topic_daily_counter[date_key]
        if not counts:
            continue
        topic_total_counter.update(counts)
        topic_daily_table.append({
            "date": date_key,
            "topics": [
                {"topic": topic, "count": count}
                for topic, count in counts.most_common()
            ],
        })

    for item in behavior_logs if isinstance(behavior_logs, list) else []:
        if not isinstance(item, dict):
            continue
        dt = parse_datetime_safe(item.get("timestamp"))
        if not dt:
            continue
        behavior_type = str(item.get("behavior_type") or item.get("type") or "").strip().lower()
        try:
            duration_seconds = max(0.0, float(item.get("duration_seconds", 0.0) or 0.0))
        except Exception:
            duration_seconds = 0.0
        mark_study_window(dt, duration_seconds if behavior_type == "page_stay" else 0.0)

    study_window_daily_table = []
    for date_key in sorted(study_window_daily_counter.keys()):
        count_map = study_window_daily_counter[date_key]
        duration_map = study_window_daily_duration[date_key]
        if not count_map:
            continue
        label, count = max(
            count_map.items(),
            key=lambda pair: (pair[1], duration_map.get(pair[0], 0.0), pair[0]),
        )
        study_window_daily_table.append({
            "date": date_key,
            "label": label,
            "count": count,
            "duration_seconds": round(duration_map.get(label, 0.0), 3),
        })

    topic_total_table = [
        {"topic": topic, "count": count}
        for topic, count in topic_total_counter.most_common()
    ]
    study_window_total_table = [
        {
            "label": label,
            "count": count,
            "duration_seconds": round(study_window_total_duration.get(label, 0.0), 3),
        }
        for label, count in sorted(
            study_window_total_counter.items(),
            key=lambda pair: (
                pair[1],
                study_window_total_duration.get(pair[0], 0.0),
                pair[0],
            ),
            reverse=True,
        )
    ]

    return {
        "updated_at": datetime.now().isoformat(),
        "topic_daily_table": topic_daily_table,
        "topic_total_table": topic_total_table,
        "study_window_daily_table": study_window_daily_table,
        "study_window_total_table": study_window_total_table,
        "top_topic": topic_total_table[0] if topic_total_table else {},
        "top_study_window": study_window_total_table[0] if study_window_total_table else {},
    }


def sync_dashboard_hidden_metrics(
    user_id,
    profile,
    content_logs,
    qa_logs,
    question_draw_logs,
    question_answer_logs,
    diagnosis_logs,
    behavior_logs,
    space_payload=None,
):
    profile_obj = deep_copy_data(profile or {}, {})
    hidden_tables = build_dashboard_hidden_tables(
        content_logs=content_logs,
        qa_logs=qa_logs,
        question_draw_logs=question_draw_logs,
        question_answer_logs=question_answer_logs,
        diagnosis_logs=diagnosis_logs,
        behavior_logs=behavior_logs,
        space_payload=space_payload,
        detect_topics_fn=detect_concepts_from_text,
    )
    current_hidden = profile_obj.get("dashboard_hidden") if isinstance(profile_obj.get("dashboard_hidden"), dict) else {}
    next_best_time = str((hidden_tables.get("top_study_window") or {}).get("label") or "").strip()
    hidden_changed = stable_json_key(current_hidden) != stable_json_key(hidden_tables)
    profile_changed = False

    if next_best_time and str(profile_obj.get("best_time_range") or "").strip() != next_best_time:
        profile_obj["best_time_range"] = next_best_time
        profile_changed = True

    if not hidden_changed and not profile_changed:
        return profile_obj, current_hidden or hidden_tables

    profile_obj["dashboard_hidden"] = hidden_tables
    set_user_profile(user_id, profile_obj)
    return profile_obj, hidden_tables


def append_auth_login_behavior(user_id, source):
    user_key = str(user_id or "").strip()
    if not user_key:
        return

    append_user_event(user_key, "behavior", {
        "id": str(uuid.uuid4()),
        "user_id": user_key,
        "timestamp": datetime.now().isoformat(),
        "type": "auth_login",
        "behavior_type": "auth_login",
        "page": "auth",
        "target": "",
        "label": "账号登录",
        "title": "auth_login",
        "source": str(source or "auth").strip() or "auth",
        "duration_seconds": 0.0,
        "meta": {},
    })


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
    if prefer_neo4j and getattr(neo4j_store, "enabled", False) and neo4j_store.ensure_connected():
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

# ===== 空间 API 接口 =====

@app.route('/api/spaces', methods=['GET'])
def get_spaces():
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    spaces = [
        serialize_space(space, user_id)
        for space in (payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else [])
        if isinstance(space, dict)
    ]
    spaces.sort(key=lambda item: int(item.get("createdAt") or 0), reverse=True)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        spaces=spaces,
        count=len(spaces),
        activeEntrySpaceId=str(payload.get("activeEntrySpaceId") or ""),
        storage=get_storage_info(),
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces', methods=['POST'])
def create_space():
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    fallback_name = f"新空间 {len(payload.get('spaces', []) if isinstance(payload.get('spaces'), list) else []) + 1}"
    space = create_space_record(normalize_space_name(data.get("name"), fallback_name))
    payload["spaces"] = [space] + (payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else [])
    payload["activeEntrySpaceId"] = space["id"]
    set_user_space_payload(user_id, payload)

    return jsonify(success_payload(
        request_id,
        message="空间创建成功",
        user_id=user_id,
        space=serialize_space(space, user_id),
        count=len(payload.get("spaces", [])),
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces/<space_id>', methods=['DELETE'])
def delete_space(space_id):
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    spaces = payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else []
    target_index = -1
    removed_space = None

    for idx, space in enumerate(spaces):
        if str((space or {}).get("id") or "").strip() == str(space_id or "").strip():
            target_index = idx
            removed_space = space
            break

    if target_index < 0 or not isinstance(removed_space, dict):
        return error_response(request_id, 404, "SPACE_NOT_FOUND", "空间不存在或已被删除")

    spaces.pop(target_index)
    active_space_id = str(payload.get("activeEntrySpaceId") or "").strip()
    if active_space_id == str(removed_space.get("id") or "").strip():
        payload["activeEntrySpaceId"] = str((spaces[0] or {}).get("id") or "").strip() if spaces else ""
    payload["spaces"] = spaces
    set_user_space_payload(user_id, payload)

    removed_items = removed_space.get("items", []) if isinstance(removed_space.get("items"), list) else []
    return jsonify(success_payload(
        request_id,
        message="空间已删除",
        user_id=user_id,
        deleted=True,
        spaceId=str(removed_space.get("id") or ""),
        deletedItemCount=len(removed_items),
        count=len(spaces),
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces/<space_id>/items', methods=['POST'])
def create_space_items(space_id):
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return error_response(request_id, 400, "INVALID_INPUT", "请至少提交一个空间内容条目")

    payload = get_user_space_payload(user_id)
    space = find_space_by_id(payload, space_id)
    if not space:
        return error_response(request_id, 404, "SPACE_NOT_FOUND", "目标空间不存在，请刷新后重试")

    created_items = []
    try:
        for index, raw_item in enumerate(raw_items):
            item = normalize_space_item_input(raw_item, index)
            if item:
                created_items.append(item)
    except ValueError as exc:
        return error_response(request_id, 400, "INVALID_INPUT", str(exc))

    if not created_items:
        return error_response(request_id, 400, "INVALID_INPUT", "没有可保存的有效内容")

    previous_items = space.get("items", []) if isinstance(space.get("items"), list) else []
    space["items"] = (created_items + previous_items)[:SPACE_MAX_ITEM_COUNT]
    space["updatedAt"] = now_ms()
    payload["activeEntrySpaceId"] = str(space.get("id") or "").strip()
    set_user_space_payload(user_id, payload)

    return jsonify(success_payload(
        request_id,
        message="空间内容保存成功",
        user_id=user_id,
        createdCount=len(created_items),
        items=[serialize_space_item(item, user_id) for item in created_items],
        space=serialize_space(space, user_id),
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces/items/<item_id>', methods=['GET'])
def get_space_item_detail(item_id):
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    space, item = find_space_item(payload, item_id)
    if not item or not space:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        item=serialize_space_item(item, user_id),
        space={
            "id": str(space.get("id") or "").strip(),
            "name": normalize_space_name(space.get("name"), "新空间"),
        },
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces/items/<item_id>', methods=['PUT'])
def update_space_item(item_id):
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    space, item = find_space_item(payload, item_id)
    if not item or not space:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    updates = {}
    if "name" in data:
        updates["name"] = clamp_text(data.get("name") or "未命名文件", 180).strip() or "未命名文件"
    if "content" in data:
        updates["content"] = clamp_text(data.get("content"), 120000)
    if "summary" in data:
        updates["summary"] = clamp_text(data.get("summary"), 4000).strip()

    if not updates:
        return error_response(request_id, 400, "INVALID_INPUT", "没有可更新的内容")

    item.update(updates)
    item["updatedAt"] = now_ms()
    if "content" in updates and "summary" not in updates:
        item["summary"] = summarize_space_item(
            name=item.get("name"),
            kind=item.get("kind"),
            mime=item.get("mime"),
            size=item.get("size"),
            source=item.get("source"),
            content=item.get("content"),
            has_file=bool(item.get("fileDataUrl") or item.get("audioDataUrl")),
        )
    space["updatedAt"] = item["updatedAt"]
    set_user_space_payload(user_id, payload)

    return jsonify(success_payload(
        request_id,
        message="空间内容更新成功",
        user_id=user_id,
        item=serialize_space_item(item, user_id),
        error_code="",
        error_message="",
    ))


@app.route('/api/spaces/items/<item_id>/preview', methods=['GET'])
def preview_space_item(item_id):
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = get_user_space_payload(user_id)
    _, item = find_space_item(payload, item_id)
    if not item:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    data_url = str(item.get("audioDataUrl") or item.get("fileDataUrl") or "").strip()
    file_bytes = b""
    mime = str(item.get("mime") or "").strip()

    if data_url:
        file_bytes, decoded_mime = decode_space_data_url(data_url)
        mime = mime or decoded_mime or "application/octet-stream"
        if file_bytes:
            safe_name = requests.utils.quote(str(item.get("name") or "preview"), safe="")
            headers = {
                "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
                "Cache-Control": "private, max-age=600",
                "X-Request-Id": request_id,
            }
            return Response(file_bytes, mimetype=mime, headers=headers)

    text_content = str(item.get("content") or "")
    if text_content:
        safe_name = requests.utils.quote(str(item.get("name") or "preview.txt"), safe="")
        headers = {
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "Cache-Control": "private, max-age=600",
            "X-Request-Id": request_id,
        }
        return Response(text_content, content_type="text/plain; charset=utf-8", headers=headers)

    return error_response(request_id, 404, "SPACE_PREVIEW_NOT_AVAILABLE", "当前内容暂无可预览的原始文件")

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
        "id": "qb-limit-001",
        "concept": "极限",
        "difficulty": "easy",
        "question_type": "single_choice",
        "question": "函数极限的本质更接近下列哪一项？",
        "options": [
            "A. 函数在该点处的取值",
            "B. 自变量趋近某值时函数值的变化趋势",
            "C. 函数图像的最高点",
            "D. 导数的另一种写法",
        ],
        "answer": "B",
        "analysis": "极限描述的是趋近过程中的趋势，不要求该点函数值一定存在。",
    },
    {
        "id": "qb-function-001",
        "concept": "函数",
        "difficulty": "easy",
        "question_type": "single_choice",
        "question": "下列对函数关系的描述，哪一项正确？",
        "options": [
            "A. 一个输入可以对应多个输出",
            "B. 每个输入只能对应一个确定输出",
            "C. 输出必须是整数",
            "D. 自变量必须连续",
        ],
        "answer": "B",
        "analysis": "函数定义核心是“唯一对应”：每个输入对应唯一输出。",
    },
    {
        "id": "qb-derivative-001",
        "concept": "导数",
        "difficulty": "medium",
        "question_type": "single_choice",
        "question": "导数在几何上最直接表示为：",
        "options": [
            "A. 曲线某点切线斜率",
            "B. 曲线围成面积",
            "C. 函数在区间上的平均值",
            "D. 函数零点个数",
        ],
        "answer": "A",
        "analysis": "导数刻画瞬时变化率，几何意义是切线斜率。",
    },
    {
        "id": "qb-monotonic-001",
        "concept": "单调性",
        "difficulty": "medium",
        "question_type": "single_choice",
        "question": "若在某区间内 f'(x) > 0，则函数在该区间通常：",
        "options": [
            "A. 单调递减",
            "B. 单调递增",
            "C. 恒为常数",
            "D. 必有极大值",
        ],
        "answer": "B",
        "analysis": "导数大于 0 对应函数上升趋势，即单调递增。",
    },
    {
        "id": "qb-extreme-001",
        "concept": "极值",
        "difficulty": "hard",
        "question_type": "single_choice",
        "question": "判断极值点时，下列说法更合理的是：",
        "options": [
            "A. 只要 f'(x)=0 就一定是极值点",
            "B. 需结合一阶导号变或二阶导信息综合判断",
            "C. 任意连续点都可判为极值点",
            "D. 极值与导数无关",
        ],
        "answer": "B",
        "analysis": "驻点不一定是极值点，需要进一步判别导数符号变化或二阶导。",
    },
    {
        "id": "qb-integral-001",
        "concept": "积分",
        "difficulty": "medium",
        "question_type": "single_choice",
        "question": "定积分最典型的应用之一是：",
        "options": [
            "A. 求瞬时速度",
            "B. 求曲线与坐标轴围成区域的面积",
            "C. 判断函数奇偶性",
            "D. 求方程根的个数",
        ],
        "answer": "B",
        "analysis": "定积分常用于面积累计，体现“累加”思想。",
    },
]

QUESTION_BANK_CUSTOM_FILE = "question_bank_custom.json"
QUESTION_BANK_OFFICIAL_FILE = "question_bank_official_ai.json"
QUESTION_TYPES = {"single_choice", "short_answer", "retry"}
QUESTION_DIFFICULTY = {"easy", "medium", "hard"}
QUESTION_BANK_SCOPE = {"ai", "mine", "both", "official", "all"}
QUESTION_BANK_USER_SOURCES = {"user_custom", "user_import"}


def normalize_question_bank_scope(scope):
    value = str(scope or "both").strip().lower()
    if value == "official":
        return "ai"
    if value == "all":
        return "both"
    if value in {"ai", "mine", "both"}:
        return value
    return "both"


def is_user_question_bank_source(source):
    return str(source or "").strip().lower() in QUESTION_BANK_USER_SOURCES


def question_item_in_scope(item, bank_scope, user_id=""):
    target_scope = normalize_question_bank_scope(bank_scope)
    source = str((item or {}).get("bank_source") or "").strip().lower()
    owner = str((item or {}).get("created_by") or "").strip()
    is_mine_source = is_user_question_bank_source(source)
    owns_item = (not user_id) or owner == user_id
    if target_scope == "mine":
        return is_mine_source and owns_item
    if target_scope == "ai":
        return not is_mine_source
    if is_mine_source:
        return owns_item
    return True


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
    analysis = str(raw.get("analysis") or "").strip()
    options = normalize_question_options(raw.get("options", []))

    if not concept or concept == "??" or not question:
        return None
    if question_type not in QUESTION_TYPES:
        question_type = "single_choice"
    if difficulty not in QUESTION_DIFFICULTY:
        difficulty = "medium"
    if not answer:
        return None
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
    source = str(item.get("bank_source") or "").strip().lower()
    creator = str(item.get("created_by") or "").strip().lower()
    return source.startswith("official") or creator == "official_ai"


def _dedupe_questions_by_id(items):
    seen = set()
    result = []
    for item in items:
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
        if normalized:
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
        if normalized:
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
    legacy_official_items = []

    for item in items:
        normalized = normalize_question_item(item)
        if not normalized:
            continue
        if is_official_question_item(normalized):
            normalized["created_by"] = "official_ai"
            normalized["is_public"] = True
            normalized["bank_source"] = "official_ai"
            legacy_official_items.append(normalized)
            continue

        if str(normalized.get("bank_source") or "").strip().lower() in {"", "official_ai", "official_template"}:
            normalized["bank_source"] = "user_custom"
        custom_items.append(normalized)

    # 历史数据迁移：将误存到 custom 文件中的官方题目搬到官方题库文件。
    if legacy_official_items:
        official_items = load_official_question_bank_items()
        official_items.extend(legacy_official_items)
        save_official_question_bank_items(official_items)
        save_custom_question_bank_items(custom_items)

    return _dedupe_questions_by_id(custom_items)


def save_custom_question_bank_items(items):
    normalized_items = []
    for item in items if isinstance(items, list) else []:
        normalized = normalize_question_item(item)
        if not normalized:
            continue
        if is_official_question_item(normalized):
            # 官方题目不应写入自定义题库文件。
            continue
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
        if item.get("is_public", True) or owner == user_id:
            visible.append(item)
    return visible


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


def parse_import_questions_text(text, user_id):
    source_text = str(text or "").strip()
    if not source_text:
        return [], ["导入文本为空"]

    rows = []
    errors = []

    try:
        parsed = json.loads(source_text)
        if isinstance(parsed, dict):
            parsed = parsed.get("questions", [parsed])
        if isinstance(parsed, list):
            for i, item in enumerate(parsed):
                normalized = normalize_question_item(
                    item,
                    fallback_id=f"qb-import-{uuid.uuid4().hex[:12]}",
                    creator=user_id,
                    is_public_default=True,
                    bank_source="user_import",
                )
                if normalized:
                    rows.append(normalized)
                else:
                    errors.append(f"JSON第{i + 1}题格式无效")
            return rows, errors
    except Exception:
        pass

    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    for idx, line in enumerate(lines, start=1):
        parts = [p.strip() for p in line.split("||")]
        if len(parts) < 6:
            errors.append(f"第{idx}行字段不足，需至少6段（concept||difficulty||type||question||options||answer）")
            continue
        concept, difficulty, q_type, question, options_text, answer = parts[:6]
        analysis = parts[6] if len(parts) > 6 else ""
        options = [x.strip() for x in options_text.split(";") if x.strip()]

        normalized = normalize_question_item(
            {
                "concept": concept,
                "difficulty": difficulty,
                "question_type": q_type,
                "question": question,
                "options": options,
                "answer": answer,
                "analysis": analysis,
                "is_public": False,
            },
            fallback_id=f"qb-import-{uuid.uuid4().hex[:12]}",
            creator=user_id,
            is_public_default=False,
            bank_source="user_import",
        )
        if normalized:
            rows.append(normalized)
        else:
            errors.append(f"第{idx}行格式无效")

    return rows, errors


def generate_official_questions_fallback(concept, difficulty, count):
    concept_text = normalize_concept_name(concept or "")
    level = (difficulty or "medium").strip().lower()
    picked = []
    base_pool = [dict(x) for x in QUESTION_BANK_TEMPLATES]
    if concept_text:
        base_pool = [x for x in base_pool if normalize_concept_name(x.get("concept") or "") == concept_text] or base_pool
    random.shuffle(base_pool)

    for i in range(max(1, min(10, int(count or 3)))):
        src = base_pool[i % len(base_pool)]
        q = dict(src)
        q["id"] = f"qb-ai-fallback-{uuid.uuid4().hex[:12]}"
        q["difficulty"] = level if level in QUESTION_DIFFICULTY else str(src.get("difficulty") or "medium")
        q["question"] = f"{src.get('question', '')}（扩展题 {i + 1}）"
        q["bank_source"] = "official_ai"
        q["created_by"] = "official_ai"
        q["is_public"] = True
        q["created_at"] = datetime.now().isoformat()
        picked.append(q)
    return picked


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
            if normalized:
                normalized["created_by"] = "official_ai"
                normalized["bank_source"] = "official_ai"
                results.append(normalized)
            if len(results) >= target_count:
                break

        if results:
            return results, "ai"
        return generate_official_questions_fallback(concept_text, level, target_count), "fallback"
    except Exception:
        return generate_official_questions_fallback(concept_text, level, target_count), "fallback"


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
        feedback = "回答正确，继续下一题。" if is_correct else f"回答不正确，正确答案是 {expected_choice or expected_answer}。"
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
    if is_correct:
        feedback = "回答基本正确，关键点覆盖较好。"
    else:
        feedback = "回答还不完整，建议补充定义关键词和关键步骤。"
    if analysis:
        feedback = f"{feedback}\n参考解析：{analysis}"

    return {
        "is_correct": is_correct,
        "score": score,
        "expected_answer": expected_answer,
        "feedback": feedback,
        "evaluation_method": "rule_keyword_match",
    }


def find_question_by_id(user_id, question_id):
    if not question_id:
        return None
    bank, _ = build_question_bank_for_user(user_id)
    for item in bank:
        if str(item.get("id") or "") == str(question_id):
            return item
    return None


def build_dynamic_question_templates(user_id, user_knowledge):
    """根据用户薄弱点和诊断记录生成动态题目。"""
    dynamic_items = []
    dynamic_ids = set()
    concepts = user_knowledge.get("concepts", []) if isinstance(user_knowledge, dict) else []
    weak_items = []

    for item in concepts:
        if not isinstance(item, dict):
            continue
        concept = normalize_concept_name(item.get("concept") or "")
        if not concept:
            continue
        try:
            mastery = float(item.get("mastery", 0.35) or 0.35)
        except Exception:
            mastery = 0.35
        if mastery < 0.75:
            weak_items.append((concept, mastery))

    weak_items.sort(key=lambda x: x[1])
    for concept, mastery in weak_items[:4]:
        difficulty = "easy" if mastery < 0.35 else ("medium" if mastery < 0.6 else "hard")
        dynamic_items.append({
            "id": f"dyn-{user_id}-{concept}-sa",
            "concept": concept,
            "difficulty": difficulty,
            "question_type": "short_answer",
            "question": f"请用自己的话解释“{concept}”的核心定义，并给出 1 个应用场景。",
            "options": [],
            "answer": "应包含定义关键词，并给出可落地的例子。",
            "analysis": "可从“定义-条件-应用”三步作答，优先保证概念准确。",
            "bank_source": "dynamic_personal",
            "created_by": user_id,
        })
        dynamic_ids.add(dynamic_items[-1]["id"])

    diagnosis_list = load_user_event_list(user_id, "diagnosis")
    for event in diagnosis_list[-2:]:
        if not isinstance(event, dict):
            continue
        stem = str(event.get("question") or "").strip()
        correct_answer = str(event.get("correct_answer") or "").strip()
        if not stem:
            continue
        topic = "错题复盘"
        topics = event.get("topics", []) if isinstance(event.get("topics", []), list) else []
        if topics:
            topic = str(topics[0] or "错题复盘").strip() or "错题复盘"

        retry_id = f"dyn-{user_id}-{abs(hash(stem)) % 100000}-retry"
        if retry_id in dynamic_ids:
            continue
        dynamic_items.append({
            "id": retry_id,
            "concept": topic,
            "difficulty": "medium",
            "question_type": "retry",
            "question": f"错题重练：{stem}",
            "options": [],
            "answer": correct_answer,
            "analysis": "建议先写关键步骤，再对照标准答案补全遗漏点。",
            "bank_source": "dynamic_personal",
            "created_by": user_id,
        })
        dynamic_ids.add(retry_id)

    wrong_question_list = load_user_event_list(user_id, "wrong_question")
    for event in wrong_question_list[-4:]:
        if not isinstance(event, dict):
            continue
        stem = str(event.get("question") or "").strip()
        if not stem:
            continue
        topic = normalize_concept_name(event.get("concept") or "")
        topics = event.get("topics", []) if isinstance(event.get("topics"), list) else []
        if not topic and topics:
            topic = normalize_concept_name(topics[0] or "")
        if not topic:
            topic = "错题复盘"
        retry_id = f"dyn-{user_id}-{abs(hash(stem)) % 100000}-retry"
        if retry_id in dynamic_ids:
            continue

        dynamic_items.append({
            "id": retry_id,
            "concept": topic,
            "difficulty": str(event.get("difficulty") or "medium").strip().lower() or "medium",
            "question_type": "retry",
            "question": f"错题重练：{stem}",
            "options": [],
            "answer": str(event.get("expected_answer") or "").strip() or "请回顾正确解法并补全关键步骤。",
            "analysis": "建议先独立回忆关键步骤，再对照标准答案检查遗漏。",
            "bank_source": "dynamic_personal",
            "created_by": user_id,
        })
        dynamic_ids.add(retry_id)

    return dynamic_items


def build_question_bank_for_user(user_id):
    """构建用户题库（静态模板 + 动态生成）。"""
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    bank = []
    for item in QUESTION_BANK_TEMPLATES:
        row = dict(item)
        row.setdefault("bank_source", "seed_template")
        row.setdefault("created_by", "system")
        row.setdefault("is_public", True)
        bank.append(row)
    bank.extend(load_official_question_bank_items())
    bank.extend(get_visible_custom_questions(user_id))
    bank.extend(build_dynamic_question_templates(user_id, user_knowledge))

    mastery_map = {}
    for item in user_knowledge.get("concepts", []):
        if not isinstance(item, dict):
            continue
        concept = normalize_concept_name(item.get("concept") or "")
        if not concept:
            continue
        try:
            mastery_map[concept] = float(item.get("mastery", 0.35) or 0.35)
        except Exception:
            mastery_map[concept] = 0.35

    return bank, mastery_map


def select_question_from_bank(bank, mastery_map, concept=None, difficulty=None, recent_ids=None, bank_scope="all", user_id="default_user"):
    """按知识薄弱程度加权抽题。"""
    target_concept = normalize_concept_name(concept or "")
    target_difficulty = (difficulty or "").strip().lower()
    target_scope = normalize_question_bank_scope(bank_scope)

    candidates = []
    for item in bank:
        if not isinstance(item, dict):
            continue
        item_concept = normalize_concept_name(item.get("concept") or "")
        item_diff = str(item.get("difficulty") or "").strip().lower()

        if target_concept and item_concept != target_concept:
            continue
        if target_difficulty and item_diff != target_difficulty:
            continue
        if not question_item_in_scope(item, target_scope, user_id=user_id):
            continue

        candidates.append(item)

    if not candidates:
        return None

    recent_ids = recent_ids or set()
    non_repeat = [item for item in candidates if str(item.get("id") or "") not in recent_ids]
    if non_repeat:
        candidates = non_repeat

    if target_scope == "both" and not target_concept and not target_difficulty:
        mine_candidates = [
            item for item in candidates
            if question_item_in_scope(item, "mine", user_id=user_id)
        ]
        if mine_candidates and random.random() < 0.6:
            candidates = mine_candidates

    weights = []
    for item in candidates:
        item_concept = normalize_concept_name(item.get("concept") or "")
        mastery = mastery_map.get(item_concept, 0.45)
        base_weight = 1.0 + max(0.0, 1.0 - float(mastery)) * 2.5

        diff = str(item.get("difficulty") or "").lower()
        if diff == "easy":
            base_weight += 0.2
        elif diff == "hard":
            base_weight += 0.35

        if str(item.get("bank_source") or "") in {"user_custom", "user_import", "official_ai"}:
            base_weight += 0.4

        base_weight *= 0.9 + random.random() * 0.2

        weights.append(base_weight)

    picked = random.choices(candidates, weights=weights, k=1)[0]
    return picked


def build_question_prompt_text(question_item):
    """构造前端可直接展示的发问文本。"""
    stem = str(question_item.get("question") or "").strip()
    options = question_item.get("options", []) if isinstance(question_item.get("options", []), list) else []
    level = str(question_item.get("difficulty") or "medium").strip().lower()
    concept = str(question_item.get("concept") or "综合").strip()
    source = str(question_item.get("bank_source") or "official_template")

    source_label = "官方题库"
    if source in {"user_custom", "user_import"}:
        source_label = "我的题库"
    elif source == "official_ai":
        source_label = "官方AI题库"
    elif source == "seed_template":
        source_label = "基础练习题库"
    elif source == "dynamic_personal":
        source_label = "个性化动态题"

    lines = [f"【题库抽题】来源：{source_label}｜知识点：{concept}｜难度：{level}", stem]
    if options:
        lines.extend(str(opt) for opt in options)
        lines.append("请直接回复选项字母（如 A）并说明你的理由。")
    else:
        lines.append("请分步骤作答，我会继续追问并给出反馈。")

    return "\n".join(lines)

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
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    
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
        user_id, auth_error = resolve_request_user_id_from_args()
    else:
        question = (data.get('question', '') or '').strip()
        user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    
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
    qa_behavior = record_qa_behavior(user_id, question, answer)
    if contains_confusion_signal(question):
        topics = normalize_topic_list((qa_behavior or {}).get("topics"))[:6]
        append_user_event(user_id, "wrong_question", build_wrong_question_entry(
            source="qa_confusion",
            question=question,
            user_answer="不会/看不懂",
            concept=topics[0] if topics else "",
            topics=topics,
            extra={
                "source_key": f"qa_confusion::{(qa_behavior or {}).get('timestamp', '')}::{question[:80]}",
                "answer_excerpt": answer[:400],
                "is_correct": False,
            },
        ))
    
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
    """题库抽题：按指定知识点抽题并发问。"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    concept = normalize_concept_name(request.args.get('concept', '') or '')
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = normalize_question_bank_scope(request.args.get('bank_scope', 'both') or 'both')

    if not concept:
        return error_response(
            request_id,
            400,
            "INVALID_INPUT",
            "请先填写要考察的知识点",
            required_field="concept",
        )

    # 官方题库抽题时自动生题，避免题目长期不变。
    if bank_scope in {"ai", "both"}:
        existing_bank, _ = build_question_bank_for_user(user_id)
        official_ai_count = sum(1 for x in existing_bank if str(x.get("bank_source") or "") == "official_ai")
        should_generate = official_ai_count < 5 or random.random() < 0.35
        if should_generate:
            generate_count = 3 if official_ai_count < 5 else 1
            generated_items, _ = generate_official_questions_with_ai(concept, difficulty or "medium", generate_count)
            if generated_items:
                official_items = load_official_question_bank_items()
                official_items.extend(generated_items)
                save_official_question_bank_items(official_items)

    bank, mastery_map = build_question_bank_for_user(user_id)
    question_item = select_question_from_bank(
        bank,
        mastery_map,
        concept=concept,
        difficulty=difficulty,
        recent_ids=get_recent_drawn_question_ids(user_id, limit=8),
        bank_scope=bank_scope,
        user_id=user_id,
    )

    if not question_item:
        return error_response(
            request_id,
            404,
            "QUESTION_NOT_FOUND",
            "未找到满足条件的题目",
            concept=concept,
            difficulty=difficulty,
        )

    prompt_text = build_question_prompt_text(question_item)
    event_payload = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question_id": question_item.get("id"),
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
    }
    append_user_event(user_id, "question_draw", event_payload)

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
            "bank_source": question_item.get("bank_source", "official_template"),
        },
        prompt_text=prompt_text,
        bank_size=len(bank),
        filters={
            "concept": concept,
            "difficulty": difficulty,
            "bank_scope": bank_scope,
        },
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/questions', methods=['GET'])
def list_question_bank_questions_api():
    """查看题库（默认仅返回当前用户可见题）。"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    concept = normalize_concept_name(request.args.get('concept', '') or '')
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = normalize_question_bank_scope(request.args.get('bank_scope', 'both') or 'both')

    bank, _ = build_question_bank_for_user(user_id)
    items = []
    for item in bank:
        if not question_item_in_scope(item, bank_scope, user_id=user_id):
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
            "created_by": item.get("created_by", "system"),
            "is_public": bool(item.get("is_public", True)),
            "bank_source": item.get("bank_source", "official_template"),
        })

    neo4j_available = neo4j_store.ensure_connected()

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
    """动态新增题目到可扩展题库。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    normalized = normalize_question_item(
        raw=data,
        fallback_id=f"qb-custom-{uuid.uuid4().hex[:12]}",
        creator=user_id,
        is_public_default=False,
        bank_source="user_custom",
    )
    if not normalized:
        return error_response(request_id, 400, "INVALID_INPUT", "题目信息不完整或格式错误")

    custom_items = load_custom_question_bank_items()
    custom_items = [item for item in custom_items if str(item.get("id") or "") != normalized["id"]]
    custom_items.append(normalized)
    save_custom_question_bank_items(custom_items)

    return jsonify(success_payload(
        request_id,
        message="题目已加入动态题库",
        user_id=user_id,
        question={
            "id": normalized["id"],
            "concept": normalized["concept"],
            "difficulty": normalized["difficulty"],
            "question_type": normalized["question_type"],
            "question": normalized["question"],
            "options": normalized.get("options", []),
            "bank_source": normalized.get("bank_source", "user_custom"),
        },
        custom_bank_count=len(custom_items),
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/import', methods=['POST'])
def import_question_bank_question_api():
    """粘贴板导题：支持 JSON 或行文本批量导入。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    text = str(data.get('text') or '').strip()

    if not text:
        return error_response(request_id, 400, "INVALID_INPUT", "导入文本不能为空")

    imported, errors = parse_import_questions_text(text, user_id)
    if not imported:
        return error_response(request_id, 400, "INVALID_INPUT", "未解析到有效题目", parse_errors=errors[:8])

    custom_items = load_custom_question_bank_items()
    ids = {str(x.get("id") or "") for x in custom_items}
    for item in imported:
        if str(item.get("id") or "") in ids:
            item["id"] = f"qb-import-{uuid.uuid4().hex[:12]}"
        custom_items.append(item)
    save_custom_question_bank_items(custom_items)

    return jsonify(success_payload(
        request_id,
        message="导题成功",
        user_id=user_id,
        imported_count=len(imported),
        custom_bank_count=len(custom_items),
        parse_errors=errors[:8],
        error_code="",
        error_message="",
    ))


@app.route('/api/question_bank/generate', methods=['POST'])
def generate_question_bank_question_api():
    """官方题库：通过 AI 批量生题并入库。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    question_id = str(data.get('question_id') or '').strip()
    user_answer = str(data.get('user_answer') or '').strip()

    if not question_id:
        return error_response(request_id, 400, "INVALID_INPUT", "question_id 不能为空")
    if not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "user_answer 不能为空")

    question_item = find_question_by_id(user_id, question_id)
    if not question_item:
        return error_response(request_id, 404, "QUESTION_NOT_FOUND", "题目不存在或不可见")

    now_dt = datetime.now()
    evaluation = evaluate_question_answer(question_item, user_answer)
    duration_seconds = data.get("duration_seconds", None)
    if duration_seconds in ("", None):
        duration_seconds = infer_question_answer_duration_seconds(user_id, question_id, now_dt=now_dt)
    else:
        try:
            duration_seconds = max(0.0, min(7200.0, float(duration_seconds)))
        except Exception:
            duration_seconds = infer_question_answer_duration_seconds(user_id, question_id, now_dt=now_dt)

    event_payload = {
        "id": str(uuid.uuid4()),
        "timestamp": now_dt.isoformat(),
        "question_id": question_id,
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
        "question": question_item.get("question"),
        "expected_answer": question_item.get("answer"),
        "user_answer": user_answer,
        "is_correct": bool(evaluation.get("is_correct", False)),
        "score": float(evaluation.get("score", 0.0) or 0.0),
    }
    if duration_seconds is not None:
        event_payload["duration_seconds"] = round(float(duration_seconds), 3)

    concept = normalize_concept_name(question_item.get("concept") or "")
    concept_history_before = collect_concept_question_history(
        user_id=user_id,
        concept=concept,
        current_record=None,
        limit=10,
    ) if concept else []
    concept_history = collect_concept_question_history(
        user_id=user_id,
        concept=concept,
        current_record=event_payload,
        limit=10,
    ) if concept else []
    diagnosis_mastery_assessment = (
        calculate_concept_mastery(concept, concept_history_before, now=now_dt)
        if concept_history_before
        else None
    )

    mastery_assessment = calculate_concept_mastery(concept, concept_history, now=now_dt) if concept_history else {
        "知识点": concept,
        "掌握度": 0.0,
        "状态": "薄弱",
    }
    mastery_snapshot = update_concept_mastery_snapshot(
        user_id=user_id,
        concept=concept,
        mastery_assessment=mastery_assessment,
        answered_at=event_payload["timestamp"],
    ) if concept else {}

    append_user_event(user_id, "question_answer", event_payload)

    diagnosis = None
    learning_advice = None
    if (not bool(evaluation.get("is_correct", False))) or contains_confusion_signal(user_answer):
        diagnosis = diagnosis_engine.analyze_error(
            question=question_item.get("question"),
            answer=evaluation.get("expected_answer", ""),
            user_answer=user_answer,
            concept=concept,
            concept_mastery=(
                diagnosis_mastery_assessment.get("掌握度")
                if isinstance(diagnosis_mastery_assessment, dict)
                else mastery_assessment.get("掌握度")
            ),
            response_time_seconds=duration_seconds,
            attempt_count=(
                diagnosis_mastery_assessment.get("作答次数")
                if isinstance(diagnosis_mastery_assessment, dict)
                else len(concept_history_before)
            ),
            history_records=concept_history_before,
        )
        learning_advice = build_learning_advice(
            error_type=diagnosis.get("error_type", "知识性错误"),
            mastery_score=mastery_assessment.get("掌握度"),
            concept=concept,
            attempt_count=mastery_assessment.get("作答次数", len(concept_history)),
        )

        wrong_item = build_wrong_question_entry(
            source="question_answer",
            question=question_item.get("question"),
            user_answer=user_answer,
            concept=question_item.get("concept"),
            topics=[question_item.get("concept")] if question_item.get("concept") else [],
            extra={
                "source_key": f"question_answer::{event_payload['timestamp']}::{question_id or question_item.get('concept') or ''}",
                "question_id": question_id,
                "difficulty": question_item.get("difficulty"),
                "question_type": question_item.get("question_type"),
                "expected_answer": evaluation.get("expected_answer", ""),
                "score": float(evaluation.get("score", 0.0) or 0.0),
                "is_correct": bool(evaluation.get("is_correct", False)),
                "error_type": diagnosis.get("error_type", ""),
            },
        )
        append_user_event(user_id, "wrong_question", wrong_item)
        append_user_event(user_id, "diagnosis", {
            "id": str(uuid.uuid4()),
            "timestamp": now_dt.isoformat(),
            "question": str(question_item.get("question") or ""),
            "correct_answer": str(evaluation.get("expected_answer", "") or "")[:200],
            "user_answer": user_answer[:200],
            "concept": concept,
            "diagnosis": diagnosis,
            "mastery_assessment": mastery_assessment,
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
        duration_seconds=event_payload.get("duration_seconds"),
        mastery_assessment=mastery_assessment,
        graph_sync=(mastery_snapshot.get("graph_sync", {}) if isinstance(mastery_snapshot, dict) else {}),
        diagnosis=diagnosis,
        learning_advice=learning_advice,
        next_action="继续点击题库抽题进行下一题",
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
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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
        neo4j_synced=bool(graph_sync.get("synced", False)) if neo4j_store.ensure_connected() else False,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/node', methods=['DELETE'])
def delete_knowledge_node_api():
    """删除某个知识点节点（同时移除关联关系）。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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
        neo4j_synced=bool(graph_sync.get("synced", False)) if neo4j_store.ensure_connected() else False,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/path', methods=['GET'])
def get_learning_path_api():
    """获取从已掌握知识到目标知识点的学习路径"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    target = request.args.get('target', '').strip()

    if not target:
        return error_response(request_id, 400, "INVALID_INPUT", "target 参数不能为空")

    if GRAPH_PRIMARY in {"auto", "neo4j"} and getattr(neo4j_store, "enabled", False) and neo4j_store.ensure_connected():
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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
    mapping_results = extract_result.get("mapping_results", [])
    top_mapping = extract_result.get("top_mapping", {})

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
        mapping_results=mapping_results,
        top_mapping=top_mapping,
        graph_sync=graph_sync,
        error_code="",
        error_message="",
    ))


@app.route('/api/knowledge_graph/map', methods=['POST'])
def map_learning_behaviors_api():
    """将题目、视频文本、学生笔记等学习行为映射到知识点。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    items = collect_learning_behavior_items(data)
    if not items:
        return error_response(
            request_id,
            400,
            "INVALID_INPUT",
            "items 或 question_texts/video_texts/note_texts 不能为空",
        )

    runtime = build_concept_mapping_runtime(user_id)
    mapping_results = map_learning_items(
        items,
        runtime.get("profiles", []),
        stopwords=runtime.get("stopwords", set()),
    )

    return jsonify(success_payload(
        request_id,
        message="学习行为知识点映射成功",
        user_id=user_id,
        total_count=len(mapping_results),
        concept_library_size=runtime.get("concept_library_size", 0),
        method={
            **CONCEPT_MAPPING_METHOD_INFO,
            "thresholds": CONCEPT_MAPPING_THRESHOLDS,
        },
        mapping_results=mapping_results,
        error_code="",
        error_message="",
    ))


@app.route('/api/review/reminders', methods=['GET'])
def get_review_reminders_api():
    """根据掌握度和复习记录返回复习提醒。"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    result = build_review_reminders_response(user_id)
    if isinstance(result, dict):
        result["request_id"] = request_id
    return jsonify(result)


@app.route('/api/content/ingest', methods=['POST'])
def ingest_learning_content_api():
    """多源学习内容录入（笔记/链接/答题记录等）。"""
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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

    mapping_runtime = build_concept_mapping_runtime(user_id)
    mapping_results = map_learning_items(
        [{
            "original_content": text,
            "match_text": text,
            "content_type": infer_mapping_content_type(source),
        }],
        mapping_runtime.get("profiles", []),
        stopwords=mapping_runtime.get("stopwords", set()),
    )
    top_mapping = mapping_results[0] if mapping_results else {
        "原始内容": text,
        "知识点": "",
        "置信度": 0.0,
    }
    if detected_concepts and not top_mapping.get("知识点"):
        top_mapping["知识点"] = detected_concepts[0]
        top_mapping["置信度"] = 0.72 if extraction_method == "ai" else 0.62

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
        "mapping_results": mapping_results,
        "top_mapping": top_mapping,
        "neo4j_synced": bool(graph_sync.get("synced", False)) if neo4j_store.ensure_connected() else False,
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
    if not neo4j_store.ensure_connected():
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
    if not neo4j_store.ensure_connected():
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
    if not neo4j_store.ensure_connected():
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    question = (data.get('question') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    user_answer = (data.get('user_answer') or '').strip()
    concept = normalize_concept_name(data.get('concept') or '')
    response_time_seconds = data.get("response_time_seconds", data.get("duration_seconds"))

    if not question or not correct_answer or not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "question、correct_answer、user_answer 不能为空")

    concept_history = collect_concept_question_history(user_id, concept, current_record=None, limit=10) if concept else []
    mastery_assessment = calculate_concept_mastery(concept, concept_history) if concept_history else None
    concept_mastery = (
        mastery_assessment.get("掌握度")
        if isinstance(mastery_assessment, dict)
        else get_concept_mastery_from_knowledge(user_id, concept)
    )

    diagnosis = diagnosis_engine.analyze_error(
        question=question,
        answer=correct_answer,
        user_answer=user_answer,
        concept=concept,
        concept_mastery=concept_mastery,
        response_time_seconds=response_time_seconds,
        attempt_count=(mastery_assessment.get("作答次数") if isinstance(mastery_assessment, dict) else len(concept_history)),
        history_records=concept_history,
    )
    learning_advice = build_learning_advice(
        error_type=diagnosis.get("error_type", "知识性错误"),
        mastery_score=concept_mastery,
        concept=concept,
        attempt_count=(mastery_assessment.get("作答次数") if isinstance(mastery_assessment, dict) else len(concept_history)),
    )
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "correct_answer": correct_answer[:200],
        "user_answer": user_answer[:200],
        "concept": concept,
        "diagnosis": diagnosis,
        "mastery_assessment": mastery_assessment,
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
        learning_advice=learning_advice,
        mastery_assessment=mastery_assessment,
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
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
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


@app.route('/api/behavior/track', methods=['POST'])
def track_learning_behavior_api():
    """记录页面停留、导航点击等轻量行为埋点。"""
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    user_id, auth_error = resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    behavior_type = str(data.get("behavior_type") or data.get("type") or "").strip().lower()
    page = str(data.get("page") or "").strip().lower()
    target = str(data.get("target") or "").strip().lower()
    label = clamp_text(data.get("label") or "", 80)
    title = clamp_text(data.get("title") or "", 80)
    source = clamp_text(data.get("source") or "page_shell", 40)
    duration_seconds = data.get("duration_seconds", 0)
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    if not behavior_type:
        return error_response(request_id, 400, "INVALID_INPUT", "behavior_type 不能为空")

    allowed_types = {
        "page_view",
        "page_stay",
        "navigation_click",
        "action_click",
        "question_analysis",
        "qa_interaction",
    }
    if behavior_type not in allowed_types:
        behavior_type = "action_click"

    try:
        duration_seconds = max(0.0, min(86400.0, float(duration_seconds or 0.0)))
    except Exception:
        duration_seconds = 0.0

    if behavior_type == "page_stay" and duration_seconds < 1.0:
        return jsonify(success_payload(
            request_id,
            message="停留时长过短，已忽略",
            accepted=False,
            error_code="",
            error_message="",
        ))

    behavior = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "type": behavior_type,
        "behavior_type": behavior_type,
        "page": page,
        "target": target,
        "label": label,
        "title": title,
        "source": source,
        "duration_seconds": round(duration_seconds, 3),
        "meta": meta,
    }
    append_user_event(user_id, "behavior", behavior)

    return jsonify(success_payload(
        request_id,
        message="行为记录成功",
        accepted=True,
        behavior=behavior,
        error_code="",
        error_message="",
    ))


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
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    result = build_diagnosis_report_response(user_id)
    if isinstance(result, dict):
        result["request_id"] = request_id
    return jsonify(result)


@app.route('/api/profile', methods=['GET'])
def profile_api():
    """获取用户学习画像。"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
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
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    graph = build_graph_response(user_id)
    reminders = build_review_reminders_response(user_id)
    profile = build_learning_profile(user_id)
    diagnosis_report = build_diagnosis_report_response(user_id)
    recommendations = build_recommendations(user_id, limit=4)
    user_knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    content_logs = load_user_event_list(user_id, "content")
    qa_logs = load_user_event_list(user_id, "qa")
    behavior_logs = load_user_event_list(user_id, "behavior")
    question_draw_logs = load_user_event_list(user_id, "question_draw")
    question_answer_logs = load_user_event_list(user_id, "question_answer")
    diagnosis_logs = load_user_event_list(user_id, "diagnosis")
    wrong_question_logs = sync_wrong_question_bank_from_logs(
        user_id=user_id,
        question_answer_logs=question_answer_logs,
        qa_logs=qa_logs,
        existing_wrong_logs=load_user_event_list(user_id, "wrong_question"),
    )
    space_payload = get_user_space_payload(user_id)
    profile, hidden_metrics = sync_dashboard_hidden_metrics(
        user_id=user_id,
        profile=profile,
        content_logs=content_logs,
        qa_logs=qa_logs,
        question_draw_logs=question_draw_logs,
        question_answer_logs=question_answer_logs,
        diagnosis_logs=diagnosis_logs,
        behavior_logs=behavior_logs,
        space_payload=space_payload,
    )
    storage_info = get_storage_info()
    cfg = get_ai_runtime_config()
    neo4j_available = neo4j_store.ensure_connected()

    sections = build_dashboard_sections(
        user_id=user_id,
        user_knowledge=user_knowledge,
        graph_payload=graph.get("graph", {}) if isinstance(graph, dict) else {},
        reminders=reminders,
        profile=profile,
        diagnosis_report={
            **(diagnosis_report if isinstance(diagnosis_report, dict) else {}),
            "latest": diagnosis_logs[-5:][::-1] if isinstance(diagnosis_logs, list) else [],
            "total": len(diagnosis_logs) if isinstance(diagnosis_logs, list) else 0,
        },
        recommendations=recommendations,
        content_logs=content_logs,
        qa_logs=qa_logs,
        behavior_logs=behavior_logs,
        question_draw_logs=question_draw_logs,
        question_answer_logs=question_answer_logs,
        diagnosis_logs=diagnosis_logs,
        wrong_question_logs=wrong_question_logs,
        space_payload=space_payload,
        hidden_metrics=hidden_metrics,
        infer_learning_path_fn=infer_learning_path_with_fallback,
    )

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
            "upcoming_count": reminders.get("upcoming_count", 0),
            "due_items": reminders.get("due_items", []),
            "upcoming_items": reminders.get("upcoming_items", []),
        },
        profile=profile,
        diagnosis=diagnosis_report,
        recommendations=recommendations,
        data_pool=sections.get("data_pool", {}),
        graph_insights=sections.get("graph_insights", {}),
        profile_insights=sections.get("profile_insights", {}),
        intervention_summary=sections.get("intervention_summary", {}),
        system={
            "storage_backend": storage_info.get("storage_backend", "json"),
            "database_scheme": storage_info.get("database_scheme", ""),
            "graph_primary": GRAPH_PRIMARY,
            "graph_sync_mode": GRAPH_SYNC_MODE,
            "neo4j_enabled": neo4j_available,
            "celery_enabled": celery_client is not None,
            "ai_enabled": USE_REAL_AI,
            "ai_provider": cfg.get("provider", "mock") if USE_REAL_AI else "mock",
        },
        error_code="",
        error_message="",
    ))


@app.route('/api/wrong_questions', methods=['GET'])
def wrong_question_bank_api():
    """获取错题库列表。"""
    request_id = get_request_id()
    user_id, auth_error = resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    items = load_user_event_list(user_id, "wrong_question")
    normalized_items = [
        deep_copy_data(item, {})
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    ]
    normalized_items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        count=len(normalized_items),
        items=normalized_items[:100],
        error_code="",
        error_message="",
    ))


@app.route('/api/auth/register', methods=['POST'])
def register_auth_user_api():
    """注册账号并创建登录会话。"""
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    username = normalize_auth_username(data.get("username"))
    password = str(data.get("password") or "")
    display_name = normalize_display_name(data.get("display_name"), fallback=username or "同学")
    locale = normalize_auth_locale(data.get("locale"))

    if not username:
        return error_response(request_id, 400, "INVALID_INPUT", "账号格式不正确，请使用 3-32 位字母、数字或 . _ @ -")
    if len(password) < 6:
        return error_response(request_id, 400, "INVALID_INPUT", "密码长度至少需要 6 位")
    if get_auth_user(username):
        return error_response(request_id, 409, "AUTH_USER_EXISTS", "该账号已存在，请直接登录")

    now = iso_now()
    user = {
        "username": username,
        "display_name": display_name,
        "password_hash": generate_password_hash(password),
        "locale": locale,
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }
    saved_user = upsert_auth_user(user)
    session_bundle = create_auth_session_payload(saved_user)
    binding = bind_guest_user_data_to_auth_user(data.get("guest_user_id"), username)
    append_auth_login_behavior(username, "auth_register")

    return jsonify(success_payload(
        request_id,
        message="注册成功",
        auth={
            "authenticated": True,
            "user": build_public_auth_user(saved_user),
            "token": session_bundle["token"],
            "expires_at": session_bundle["expires_at"],
            "session_id": session_bundle["session_id"],
        },
        binding=binding,
        error_code="",
        error_message="",
    ))


@app.route('/api/auth/login', methods=['POST'])
def login_auth_user_api():
    """账号登录并签发 Bearer token。"""
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    username = normalize_auth_username(data.get("username"))
    password = str(data.get("password") or "")

    if not username or not password:
        return error_response(request_id, 400, "INVALID_INPUT", "请输入账号和密码")

    user = get_auth_user(username)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        return error_response(request_id, 401, "AUTH_INVALID_CREDENTIALS", "账号或密码错误")

    user["last_login_at"] = iso_now()
    user["updated_at"] = iso_now()
    saved_user = upsert_auth_user(user)
    session_bundle = create_auth_session_payload(saved_user)
    binding = bind_guest_user_data_to_auth_user(data.get("guest_user_id"), username)
    append_auth_login_behavior(username, "auth_login")

    return jsonify(success_payload(
        request_id,
        message="登录成功",
        auth={
            "authenticated": True,
            "user": build_public_auth_user(saved_user),
            "token": session_bundle["token"],
            "expires_at": session_bundle["expires_at"],
            "session_id": session_bundle["session_id"],
        },
        binding=binding,
        error_code="",
        error_message="",
    ))


@app.route('/api/auth/me', methods=['GET'])
def current_auth_user_api():
    """获取当前登录用户信息。"""
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=True)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    return jsonify(success_payload(
        request_id,
        auth={
            "authenticated": True,
            "user": build_public_auth_user(auth_context["user"]),
            "expires_at": auth_context["session"].get("expires_at"),
            "session_id": auth_context["session"].get("session_id"),
        },
        error_code="",
        error_message="",
    ))


@app.route('/api/auth/logout', methods=['POST'])
def logout_auth_user_api():
    """退出当前登录会话。"""
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if auth_context:
        revoke_auth_session(auth_context["token_hash"], iso_now())

    return jsonify(success_payload(
        request_id,
        message="已退出登录",
        logged_out=True,
        error_code="",
        error_message="",
    ))


@app.route('/api/auth/account', methods=['DELETE'])
def delete_auth_user_account_api():
    """删除当前登录账号及其关联学习数据。"""
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    username = normalize_auth_username((auth_context.get("user") or {}).get("username"))
    if not username:
        return error_response(request_id, 400, "INVALID_INPUT", "当前账号信息不完整，无法删除")

    cleanup = delete_auth_user_account(username)
    if not cleanup.get("auth_user_deleted"):
        return error_response(request_id, 500, "AUTH_DELETE_FAILED", "删除账户失败，请稍后重试")

    graph_cleanup_attempted = bool(neo4j_store.ensure_connected())
    graph_deleted = False
    if graph_cleanup_attempted:
        try:
            graph_deleted = bool(neo4j_store.delete_user_graph(username))
        except Exception as exc:
            logger.exception("failed to delete neo4j user graph for %s: %s", username, exc)
            graph_deleted = False

    return jsonify(success_payload(
        request_id,
        message="账户已删除",
        deleted_account=True,
        user_id=username,
        cleanup={
            **cleanup,
            "graph_cleanup_attempted": graph_cleanup_attempted,
            "graph_deleted": graph_deleted,
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
    topics = normalize_topic_list(detect_concepts_from_text(question))[:6]
    behavior = {
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer[:200],  # 只存储前200字符
        "topics": topics,
        "is_confusion_request": contains_confusion_signal(question),
        "type": "qa_interaction"
    }
    
    db_append_user_event(user_id, "qa", behavior)
    return behavior

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
    neo4j_available = neo4j_store.ensure_connected()
    neo4j_error = getattr(neo4j_store, "last_error", "")
    storage_info = get_storage_info()
    return jsonify({
        "status": "ok",
        "provider": cfg["provider"] if USE_REAL_AI else "mock",
        "model": cfg["model"] if USE_REAL_AI else "mock",
        "ai_key_configured": bool(cfg.get("api_key")),
        "ai_enabled": USE_REAL_AI,
        "ocr_provider": OCR_PROVIDER,
        "neo4j_enabled": neo4j_available,
        "neo4j_error": neo4j_error,
        "graph_primary": GRAPH_PRIMARY,
        "graph_sync_mode": GRAPH_SYNC_MODE,
        "celery_enabled": celery_client is not None,
        "celery_worker_available": is_celery_worker_available(),
        "storage_backend": storage_info.get("storage_backend", "json"),
        "database_scheme": storage_info.get("database_scheme", ""),
        "message": "智能学习伴侣服务运行正常"
    })


FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")


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


def run():
    backend_port = int(os.getenv("BACKEND_PORT", "5000"))
    debug_enabled = str(os.getenv("BACKEND_DEBUG", "true")).strip().lower() == "true"
    use_reloader = str(os.getenv("BACKEND_USE_RELOADER", "false")).strip().lower() == "true"
    app.run(debug=debug_enabled, use_reloader=use_reloader and debug_enabled, port=backend_port, host='0.0.0.0')


if __name__ == '__main__':
    run()
