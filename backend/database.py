import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from db import ENGINE, Base, get_database_url, get_session
from models import AuthSession, AuthUser, UserEvent, UserKnowledge, UserPlan, UserProfile


DATA_DIR = "data"
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "json").strip().lower()


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


def init_storage():
    ensure_data_dir()
    if STORAGE_BACKEND == "sql":
        Base.metadata.create_all(bind=ENGINE)


def _build_repository():
    if STORAGE_BACKEND == "sql":
        return SqlRepository()
    return JsonRepository()


repo = _build_repository()


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


def get_storage_info() -> Dict[str, str]:
    db_url = get_database_url() if STORAGE_BACKEND == "sql" else ""
    scheme = ""
    if db_url:
        parsed = urlparse(db_url)
        scheme = parsed.scheme or ""

    return {
        "storage_backend": STORAGE_BACKEND,
        "database_scheme": scheme,
    }
