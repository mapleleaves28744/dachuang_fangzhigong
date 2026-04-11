import argparse
import json
import os
from datetime import datetime

import requests


def load_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Run online/offline evaluation for agent OCR tutor.")
    parser.add_argument("--base", default=os.getenv("EVAL_BASE", "http://127.0.0.1:5000"), help="Backend base url")
    parser.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "agent_eval_samples.json"),
        help="Path to eval cases json",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "agent_eval_report.json"),
        help="Output report path",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases)
    url = args.base.rstrip("/") + "/api/agent/eval"

    response = requests.post(url, json={"cases": cases}, timeout=120)
    response.raise_for_status()
    report = response.json()
    report["generated_at"] = datetime.now().isoformat()
    report["endpoint"] = url

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    summary = report.get("summary", {})
    print("Agent eval done")
    print(f"cases={summary.get('cases', 0)} avg_score={summary.get('avg_score', 0)}")
    print(f"report={args.out}")


if __name__ == "__main__":
    main()
