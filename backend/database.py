import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from db import ENGINE, Base, get_database_url, get_session
from models import UserEvent, UserKnowledge, UserPlan, UserProfile


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
