import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..models.db import ENGINE, Base, get_database_url, get_session
from ..models.entities import AuthSession, AuthUser, UserEvent, UserKnowledge, UserPlan, UserProfile, UserSpaceState


DATA_DIR = "data"
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "json").strip().lower()
SPACE_STORAGE_BACKEND = os.getenv("SPACE_STORAGE_BACKEND", "sql").strip().lower()
SPACE_FILE_SUFFIX = "_spaces.json"


def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def load_json(filename, default=None):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_json_load_text(text: Optional[str], default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)


def _to_int(value, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _normalize_space_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    item_id = str(item.get("id") or "").strip()
    if not item_id:
        return None

    now_ms = _now_ms()
    added_at = _to_int(item.get("addedAt"), now_ms)
    updated_at = _to_int(item.get("updatedAt"), added_at)

    return {
        "id": item_id,
        "name": str(item.get("name") or "未命名文件").strip() or "未命名文件",
        "kind": str(item.get("kind") or "document").strip() or "document",
        "mime": str(item.get("mime") or "").strip(),
        "size": max(0, _to_int(item.get("size"), 0)),
        "source": str(item.get("source") or "").strip(),
        "content": str(item.get("content") or ""),
        "summary": str(item.get("summary") or ""),
        "audioDataUrl": str(item.get("audioDataUrl") or ""),
        "fileDataUrl": str(item.get("fileDataUrl") or ""),
        "addedAt": added_at,
        "updatedAt": updated_at,
    }


def _normalize_space_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    current = payload if isinstance(payload, dict) else {}
    spaces: List[Dict[str, Any]] = []
    active_space_id = str(current.get("activeEntrySpaceId") or "").strip()

    for raw_space in current.get("spaces", []) if isinstance(current.get("spaces"), list) else []:
        if not isinstance(raw_space, dict):
            continue

        space_id = str(raw_space.get("id") or "").strip()
        if not space_id:
            continue

        now_ms = _now_ms()
        created_at = _to_int(raw_space.get("createdAt"), now_ms)
        updated_at = _to_int(raw_space.get("updatedAt"), created_at)
        items = [
            item
            for item in (
                _normalize_space_item(raw_item)
                for raw_item in (raw_space.get("items", []) if isinstance(raw_space.get("items"), list) else [])
            )
            if item
        ]

        if items:
            updated_at = max([updated_at] + [max(item.get("updatedAt", item.get("addedAt", updated_at)), updated_at) for item in items])

        spaces.append({
            "id": space_id,
            "name": str(raw_space.get("name") or "新空间").strip() or "新空间",
            "createdAt": created_at,
            "updatedAt": updated_at,
            "items": items,
        })

    valid_ids = {space["id"] for space in spaces}
    if active_space_id not in valid_ids:
        active_space_id = spaces[0]["id"] if spaces else ""

    return {
        "activeEntrySpaceId": active_space_id,
        "spaces": spaces,
    }


def _count_space_items(payload: Dict[str, Any]) -> int:
    normalized = _normalize_space_payload(payload)
    return sum(len(space.get("items", []) or []) for space in normalized.get("spaces", []))


class JsonSpaceRepository:
    @staticmethod
    def _filename(user_id: str) -> str:
        return f"{str(user_id or '').strip()}{SPACE_FILE_SUFFIX}"

    def get_user_space_payload(self, user_id: str) -> Dict[str, Any]:
        filename = self._filename(user_id)
        return _normalize_space_payload(load_json(filename, {"activeEntrySpaceId": "", "spaces": []}))

    def set_user_space_payload(self, user_id: str, payload: Dict[str, Any]) -> None:
        filename = self._filename(user_id)
        save_json(filename, _normalize_space_payload(payload))

    def delete_user_space_payload(self, user_id: str) -> Dict[str, Any]:
        filename = self._filename(user_id)
        payload = self.get_user_space_payload(user_id)
        deleted = JsonRepository._delete_file(filename)
        return {
            "deleted": deleted,
            "spaces_deleted": len(payload.get("spaces", [])),
            "space_items_deleted": _count_space_items(payload),
        }


class SqlSpaceRepository:
    def get_user_space_payload(self, user_id: str) -> Dict[str, Any]:
        with get_session() as session:
            row = session.query(UserSpaceState).filter(UserSpaceState.user_id == user_id).one_or_none()
            return _normalize_space_payload(_safe_json_load_text(row.payload if row else None, {"activeEntrySpaceId": "", "spaces": []}))

    def set_user_space_payload(self, user_id: str, payload: Dict[str, Any]) -> None:
        with get_session() as session:
            row = session.query(UserSpaceState).filter(UserSpaceState.user_id == user_id).one_or_none()
            if not row:
                row = UserSpaceState(user_id=user_id, payload="{}")
                session.add(row)
            row.payload = json.dumps(_normalize_space_payload(payload), ensure_ascii=False)

    def delete_user_space_payload(self, user_id: str) -> Dict[str, Any]:
        payload = self.get_user_space_payload(user_id)
        with get_session() as session:
            deleted = session.query(UserSpaceState).filter(
                UserSpaceState.user_id == user_id
            ).delete(synchronize_session=False)
        return {
            "deleted": bool(deleted),
            "spaces_deleted": len(payload.get("spaces", [])),
            "space_items_deleted": _count_space_items(payload),
        }


class JsonRepository:
    @staticmethod
    def _load_items(filename: str) -> List[Dict[str, Any]]:
        data = load_json(filename, {"items": []})
        if isinstance(data, dict):
            items = data.get("items", [])
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    @staticmethod
    def _save_items(filename: str, items: List[Dict[str, Any]]) -> None:
        save_json(filename, {"items": items})

    @staticmethod
    def _delete_file(filename: str) -> bool:
        ensure_data_dir()
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True

    def get_user_plans(self, user_id: str) -> List[Dict[str, Any]]:
        plans = load_json("user_plans.json", {})
        return plans.get(user_id, [])

    def set_user_plans(self, user_id: str, plan_list: List[Dict[str, Any]]) -> None:
        plans = load_json("user_plans.json", {})
        plans[user_id] = plan_list
        save_json("user_plans.json", plans)

    def get_user_knowledge(self, user_id: str) -> Dict[str, Any]:
        return load_json(f"{user_id}_knowledge.json", {"concepts": []})

    def set_user_knowledge(self, user_id: str, knowledge: Dict[str, Any]) -> None:
        save_json(f"{user_id}_knowledge.json", knowledge)

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        return load_json(f"{user_id}_profile.json", {})

    def set_user_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        save_json(f"{user_id}_profile.json", profile)

    def get_user_events(self, user_id: str, suffix: str) -> List[Dict[str, Any]]:
        return load_json(f"{user_id}_{suffix}.json", [])

    def append_user_event(self, user_id: str, suffix: str, item: Dict[str, Any]) -> None:
        events = self.get_user_events(user_id, suffix)
        events.append(item)
        save_json(f"{user_id}_{suffix}.json", events)

    def get_auth_user(self, username: str) -> Optional[Dict[str, Any]]:
        username = str(username or "").strip()
        if not username:
            return None

        for item in self._load_items("auth_users.json"):
            if str(item.get("username", "")).strip() == username:
                return dict(item)
        return None

    def upsert_auth_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        items = self._load_items("auth_users.json")
        username = str(user.get("username", "")).strip()
        updated = False
        for idx, item in enumerate(items):
            if str(item.get("username", "")).strip() == username:
                items[idx] = dict(user)
                updated = True
                break
        if not updated:
            items.append(dict(user))
        self._save_items("auth_users.json", items)
        return dict(user)

    def get_auth_session_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        token_hash = str(token_hash or "").strip()
        if not token_hash:
            return None

        for item in self._load_items("auth_sessions.json"):
            if str(item.get("token_hash", "")).strip() == token_hash:
                return dict(item)
        return None

    def upsert_auth_session(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        items = self._load_items("auth_sessions.json")
        session_id = str(session_data.get("session_id", "")).strip()
        updated = False
        for idx, item in enumerate(items):
            if str(item.get("session_id", "")).strip() == session_id:
                items[idx] = dict(session_data)
                updated = True
                break
        if not updated:
            items.append(dict(session_data))
        self._save_items("auth_sessions.json", items)
        return dict(session_data)

    def revoke_auth_session(self, token_hash: str, revoked_at: str) -> bool:
        items = self._load_items("auth_sessions.json")
        token_hash = str(token_hash or "").strip()
        changed = False
        for item in items:
            if str(item.get("token_hash", "")).strip() == token_hash:
                item["revoked_at"] = revoked_at
                changed = True
                break
        if changed:
            self._save_items("auth_sessions.json", items)
        return changed

    def touch_auth_session(self, token_hash: str, last_seen_at: str) -> bool:
        items = self._load_items("auth_sessions.json")
        token_hash = str(token_hash or "").strip()
        changed = False
        for item in items:
            if str(item.get("token_hash", "")).strip() == token_hash:
                item["last_seen_at"] = last_seen_at
                changed = True
                break
        if changed:
            self._save_items("auth_sessions.json", items)
        return changed

    def delete_auth_user_account(self, username: str) -> Dict[str, Any]:
        username = str(username or "").strip()
        summary = {
            "user_id": username,
            "auth_user_deleted": False,
            "sessions_deleted": 0,
            "plans_deleted": 0,
            "knowledge_deleted": 0,
            "profile_deleted": 0,
            "events_deleted": 0,
        }
        if not username:
            return summary

        auth_users = self._load_items("auth_users.json")
        remaining_users = [
            item for item in auth_users
            if str(item.get("username", "")).strip() != username
        ]
        if len(remaining_users) != len(auth_users):
            self._save_items("auth_users.json", remaining_users)
            summary["auth_user_deleted"] = True

        auth_sessions = self._load_items("auth_sessions.json")
        remaining_sessions = [
            item for item in auth_sessions
            if str(item.get("username", "")).strip() != username
        ]
        summary["sessions_deleted"] = len(auth_sessions) - len(remaining_sessions)
        if summary["sessions_deleted"] > 0:
            self._save_items("auth_sessions.json", remaining_sessions)

        plans = load_json("user_plans.json", {})
        if isinstance(plans, dict) and username in plans:
            plans.pop(username, None)
            save_json("user_plans.json", plans)
            summary["plans_deleted"] = 1

        if self._delete_file(f"{username}_knowledge.json"):
            summary["knowledge_deleted"] = 1
        if self._delete_file(f"{username}_profile.json"):
            summary["profile_deleted"] = 1

        event_file_count = 0
        prefix = f"{username}_"
        skip_names = {
            f"{username}_knowledge.json",
            f"{username}_profile.json",
        }
        for filename in os.listdir(DATA_DIR):
            if filename in skip_names:
                continue
            if not filename.startswith(prefix) or not filename.endswith(".json"):
                continue
            os.remove(os.path.join(DATA_DIR, filename))
            event_file_count += 1
        summary["events_deleted"] = event_file_count

        return summary


class SqlRepository:
    @staticmethod
    def _safe_json_load(text: Optional[str], default):
        if not text:
            return default
        try:
            return json.loads(text)
        except Exception:
            return default

    def get_user_plans(self, user_id: str) -> List[Dict[str, Any]]:
        with get_session() as session:
            row = session.query(UserPlan).filter(UserPlan.user_id == user_id).one_or_none()
            return self._safe_json_load(row.payload if row else None, [])

    def set_user_plans(self, user_id: str, plan_list: List[Dict[str, Any]]) -> None:
        with get_session() as session:
            row = session.query(UserPlan).filter(UserPlan.user_id == user_id).one_or_none()
            if not row:
                row = UserPlan(user_id=user_id, payload="[]")
                session.add(row)
            row.payload = json.dumps(plan_list, ensure_ascii=False)

    def get_user_knowledge(self, user_id: str) -> Dict[str, Any]:
        with get_session() as session:
            row = session.query(UserKnowledge).filter(UserKnowledge.user_id == user_id).one_or_none()
            return self._safe_json_load(row.payload if row else None, {"concepts": []})

    def set_user_knowledge(self, user_id: str, knowledge: Dict[str, Any]) -> None:
        with get_session() as session:
            row = session.query(UserKnowledge).filter(UserKnowledge.user_id == user_id).one_or_none()
            if not row:
                row = UserKnowledge(user_id=user_id, payload="{}")
                session.add(row)
            row.payload = json.dumps(knowledge, ensure_ascii=False)

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        with get_session() as session:
            row = session.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
            return self._safe_json_load(row.payload if row else None, {})

    def set_user_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        with get_session() as session:
            row = session.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
            if not row:
                row = UserProfile(user_id=user_id, payload="{}")
                session.add(row)
            row.payload = json.dumps(profile, ensure_ascii=False)

    def get_user_events(self, user_id: str, suffix: str) -> List[Dict[str, Any]]:
        with get_session() as session:
            rows = (
                session.query(UserEvent)
                .filter(UserEvent.user_id == user_id, UserEvent.suffix == suffix)
                .order_by(UserEvent.created_at.asc(), UserEvent.id.asc())
                .all()
            )
            return [self._safe_json_load(r.payload, {}) for r in rows]

    def append_user_event(self, user_id: str, suffix: str, item: Dict[str, Any]) -> None:
        with get_session() as session:
            session.add(
                UserEvent(
                    user_id=user_id,
                    suffix=suffix,
                    payload=json.dumps(item, ensure_ascii=False),
                )
            )

    def get_auth_user(self, username: str) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            row = session.query(AuthUser).filter(AuthUser.username == username).one_or_none()
            if not row:
                return None
            return {
                "username": row.username,
                "display_name": row.display_name,
                "password_hash": row.password_hash,
                "locale": row.locale,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
            }

    def upsert_auth_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        with get_session() as session:
            row = session.query(AuthUser).filter(AuthUser.username == user["username"]).one_or_none()
            if not row:
                row = AuthUser(username=user["username"])
                session.add(row)

            row.display_name = user.get("display_name") or user["username"]
            row.password_hash = user.get("password_hash") or ""
            row.locale = user.get("locale") or "CN"
            if user.get("last_login_at"):
                row.last_login_at = datetime.fromisoformat(user["last_login_at"])

            session.flush()
            return {
                "username": row.username,
                "display_name": row.display_name,
                "password_hash": row.password_hash,
                "locale": row.locale,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
            }

    def get_auth_session_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            row = session.query(AuthSession).filter(AuthSession.token_hash == token_hash).one_or_none()
            if not row:
                return None
            return {
                "session_id": row.session_id,
                "username": row.username,
                "token_hash": row.token_hash,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }

    def upsert_auth_session(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        with get_session() as session:
            row = session.query(AuthSession).filter(AuthSession.session_id == session_data["session_id"]).one_or_none()
            if not row:
                row = AuthSession(session_id=session_data["session_id"])
                session.add(row)

            row.username = session_data.get("username") or ""
            row.token_hash = session_data.get("token_hash") or ""
            row.expires_at = datetime.fromisoformat(session_data["expires_at"])
            row.last_seen_at = datetime.fromisoformat(session_data["last_seen_at"])
            if session_data.get("revoked_at"):
                row.revoked_at = datetime.fromisoformat(session_data["revoked_at"])
            else:
                row.revoked_at = None

            session.flush()
            return {
                "session_id": row.session_id,
                "username": row.username,
                "token_hash": row.token_hash,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }

    def revoke_auth_session(self, token_hash: str, revoked_at: str) -> bool:
        with get_session() as session:
            row = session.query(AuthSession).filter(AuthSession.token_hash == token_hash).one_or_none()
            if not row:
                return False
            row.revoked_at = datetime.fromisoformat(revoked_at)
            return True

    def touch_auth_session(self, token_hash: str, last_seen_at: str) -> bool:
        with get_session() as session:
            row = session.query(AuthSession).filter(AuthSession.token_hash == token_hash).one_or_none()
            if not row:
                return False
            row.last_seen_at = datetime.fromisoformat(last_seen_at)
            return True

    def delete_auth_user_account(self, username: str) -> Dict[str, Any]:
        username = str(username or "").strip()
        summary = {
            "user_id": username,
            "auth_user_deleted": False,
            "sessions_deleted": 0,
            "plans_deleted": 0,
            "knowledge_deleted": 0,
            "profile_deleted": 0,
            "events_deleted": 0,
        }
        if not username:
            return summary

        with get_session() as session:
            summary["sessions_deleted"] = session.query(AuthSession).filter(
                AuthSession.username == username
            ).delete(synchronize_session=False)
            summary["plans_deleted"] = session.query(UserPlan).filter(
                UserPlan.user_id == username
            ).delete(synchronize_session=False)
            summary["knowledge_deleted"] = session.query(UserKnowledge).filter(
                UserKnowledge.user_id == username
            ).delete(synchronize_session=False)
            summary["profile_deleted"] = session.query(UserProfile).filter(
                UserProfile.user_id == username
            ).delete(synchronize_session=False)
            summary["events_deleted"] = session.query(UserEvent).filter(
                UserEvent.user_id == username
            ).delete(synchronize_session=False)
            summary["auth_user_deleted"] = bool(session.query(AuthUser).filter(
                AuthUser.username == username
            ).delete(synchronize_session=False))

        return summary


def init_storage():
    ensure_data_dir()
    if STORAGE_BACKEND == "sql" or SPACE_STORAGE_BACKEND == "sql":
        Base.metadata.create_all(bind=ENGINE)


def _build_repository():
    if STORAGE_BACKEND == "sql":
        return SqlRepository()
    return JsonRepository()


def _build_space_repository():
    if SPACE_STORAGE_BACKEND == "sql":
        return SqlSpaceRepository()
    return JsonSpaceRepository()


repo = _build_repository()
space_repo = _build_space_repository()


def get_user_plans(user_id):
    return repo.get_user_plans(user_id)


def set_user_plans(user_id, plan_list):
    repo.set_user_plans(user_id, plan_list)


def get_user_knowledge(user_id):
    return repo.get_user_knowledge(user_id)


def set_user_knowledge(user_id, knowledge):
    repo.set_user_knowledge(user_id, knowledge)


def get_user_profile(user_id):
    return repo.get_user_profile(user_id)


def set_user_profile(user_id, profile):
    repo.set_user_profile(user_id, profile)


def get_user_event_list(user_id, suffix):
    return repo.get_user_events(user_id, suffix)


def append_user_event(user_id, suffix, item):
    repo.append_user_event(user_id, suffix, item)


def get_auth_user(username):
    return repo.get_auth_user(username)


def upsert_auth_user(user):
    return repo.upsert_auth_user(user)


def get_auth_session_by_token_hash(token_hash):
    return repo.get_auth_session_by_token_hash(token_hash)


def upsert_auth_session(session_data):
    return repo.upsert_auth_session(session_data)


def revoke_auth_session(token_hash, revoked_at):
    return repo.revoke_auth_session(token_hash, revoked_at)


def touch_auth_session(token_hash, last_seen_at):
    return repo.touch_auth_session(token_hash, last_seen_at)


def delete_auth_user_account(username):
    summary = repo.delete_auth_user_account(username)
    space_summary = space_repo.delete_user_space_payload(username)
    summary["spaces_deleted"] = int(space_summary.get("spaces_deleted", 0) or 0)
    summary["space_items_deleted"] = int(space_summary.get("space_items_deleted", 0) or 0)
    return summary


def get_user_space_payload(user_id):
    return space_repo.get_user_space_payload(user_id)


def set_user_space_payload(user_id, payload):
    space_repo.set_user_space_payload(user_id, payload)


def delete_user_space_payload(user_id):
    return space_repo.delete_user_space_payload(user_id)


def get_storage_info() -> Dict[str, str]:
    db_url = get_database_url() if (STORAGE_BACKEND == "sql" or SPACE_STORAGE_BACKEND == "sql") else ""
    scheme = ""
    if db_url:
        parsed = urlparse(db_url)
        scheme = parsed.scheme or ""

    return {
        "storage_backend": STORAGE_BACKEND,
        "space_storage_backend": SPACE_STORAGE_BACKEND,
        "database_scheme": scheme,
    }
