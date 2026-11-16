from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "exp02_results.json"


def main() -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    print("sample_sizes:", payload["sample_sizes"])
    print("usage:", payload["usage"])
    print("fallback_counts:", payload.get("fallback_counts"))
    print("repair_cases:", {key: len(value) for key, value in (payload.get("repair_cases") or {}).items()})
    print("finish_reasons:", payload.get("finish_reasons"))
    print()

    issue = payload["rows"]["issue"]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for row in issue:
        confusion[str(row["expected"])][str(row["predicted"])] += 1
    print("Issue confusion matrix (expected -> predicted):")
    for expected, counter in sorted(confusion.items()):
        print(f"  {expected}: {dict(counter)}")
    print()

    print("PR by bug type:")
    pr_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "detected": 0})
    for row in payload["rows"]["pr"]:
        if not row["has_bug"]:
            continue
        pr_stats[row["bug_type"]]["n"] += 1
        pr_stats[row["bug_type"]]["detected"] += int(bool(row["detected"]))
    for bug_type, item in sorted(pr_stats.items()):
        print(f"  {bug_type}: {item['detected']}/{item['n']}")
    print()

    print("CI by failure type:")
    ci_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "type_ok": 0, "cause_ok": 0})
    for row in payload["rows"]["ci"]:
        item = ci_stats[row["expected_failure_type"]]
        item["n"] += 1
        item["type_ok"] += int(bool(row["failure_type_correct"]))
        item["cause_ok"] += int(bool(row["root_cause_hit"]))
    for failure_type, item in sorted(ci_stats.items()):
        print(f"  {failure_type}: type {item['type_ok']}/{item['n']}, root {item['cause_ok']}/{item['n']}")
    print()

    print("PR false positives:")
    for row in payload["rows"]["pr"]:
        if not row["has_bug"] and row["detected"]:
            print(f"  {row['id']}")


if __name__ == "__main__":
    main()
