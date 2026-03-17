import json
import os
import sys
from pathlib import Path

# 迁移脚本：将现有 data 目录中的 JSON 数据写入 SQL 后端。
os.environ["STORAGE_BACKEND"] = "sql"

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import (  # noqa: E402
    append_user_event,
    get_user_event_list,
    get_user_knowledge,
    get_user_plans,
    get_user_profile,
    init_storage,
    set_user_knowledge,
    set_user_plans,
    set_user_profile,
)


def load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def migrate_plans(data_dir: Path, report: dict):
    path = data_dir / "user_plans.json"
    plans = load_json_file(path, {})
    for user_id, plan_list in plans.items():
        set_user_plans(user_id, plan_list if isinstance(plan_list, list) else [])
        report["plans"] += 1


def migrate_profiles_and_knowledge(data_dir: Path, report: dict):
    for p in data_dir.glob("*_profile.json"):
        user_id = p.stem.replace("_profile", "")
        profile = load_json_file(p, {})
        set_user_profile(user_id, profile if isinstance(profile, dict) else {})
        report["profiles"] += 1

    for p in data_dir.glob("*_knowledge.json"):
        user_id = p.stem.replace("_knowledge", "")
        knowledge = load_json_file(p, {"concepts": []})
        set_user_knowledge(user_id, knowledge if isinstance(knowledge, dict) else {"concepts": []})
        report["knowledge"] += 1


def migrate_events(data_dir: Path, report: dict):
    suffixes = ["qa", "behavior", "content", "diagnosis"]
    for suffix in suffixes:
        pattern = f"*_{suffix}.json"
        for p in data_dir.glob(pattern):
            user_id = p.stem[: -(len(suffix) + 1)]
            items = load_json_file(p, [])
            if not isinstance(items, list):
                items = []

            existing = get_user_event_list(user_id, suffix)
            existing_key = {json.dumps(i, ensure_ascii=False, sort_keys=True) for i in existing if isinstance(i, dict)}
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in existing_key:
                    continue
                append_user_event(user_id, suffix, item)
                existing_key.add(key)
                report["events"] += 1


def main():
    backend_dir = BACKEND_DIR
    data_dir = backend_dir / "data"

    if not data_dir.exists():
        print(f"data dir not found: {data_dir}")
        return

    init_storage()

    report = {
        "plans": 0,
        "profiles": 0,
        "knowledge": 0,
        "events": 0,
    }

    migrate_plans(data_dir, report)
    migrate_profiles_and_knowledge(data_dir, report)
    migrate_events(data_dir, report)

    print("migration done")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
