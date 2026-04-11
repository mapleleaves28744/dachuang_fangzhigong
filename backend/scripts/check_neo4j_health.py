import argparse
import json
import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)


def load_simple_env_files():
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
                    if line.startswith("export "):
                        line = line[len("export "):].strip()

                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if value and not (value.startswith('"') or value.startswith("'")) and " #" in value:
                        value = value.split(" #", 1)[0].rstrip()
                    value = value.strip().strip('"').strip("'")
                    if key and not os.getenv(key):
                        os.environ[key] = value
        except Exception:
            continue


def main():
    parser = argparse.ArgumentParser(description="Check Neo4j connectivity and configuration")
    parser.add_argument("--force", action="store_true", help="Force reconnect attempt")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    load_simple_env_files()

    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)

    from app.services.neo4j_store import Neo4jGraphStore

    store = Neo4jGraphStore()
    report = store.get_health_report(force=args.force)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Neo4j health check")
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if report.get("connected"):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
