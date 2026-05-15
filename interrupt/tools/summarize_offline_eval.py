#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path


def _is_yes(value: str) -> bool:
    return str(value or "").strip().lower() == "yes"


def summarize(path: Path) -> str:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    total = len(rows)
    if total == 0:
      return f"{path.name}: no rows"

    metrics = {
        "request_success": 0,
        "intent_correct": 0,
        "schema_valid": 0,
        "semantic_correct": 0,
        "invalid_action_no": 0,
        "interrupt_recovered": 0,
        "final_case_pass": 0,
    }

    for row in rows:
        if _is_yes(row.get("request_success", "")):
            metrics["request_success"] += 1
        if _is_yes(row.get("intent_correct", "")):
            metrics["intent_correct"] += 1
        if _is_yes(row.get("schema_valid", "")):
            metrics["schema_valid"] += 1
        if _is_yes(row.get("semantic_correct", "")):
            metrics["semantic_correct"] += 1
        if str(row.get("invalid_action", "")).strip().lower() == "no":
            metrics["invalid_action_no"] += 1
        if _is_yes(row.get("interrupt_recovered", "")):
            metrics["interrupt_recovered"] += 1
        if str(row.get("final_case_result", "")).strip().lower() in {"pass", "passed", "yes"}:
            metrics["final_case_pass"] += 1

    def pct(value: int) -> str:
        return f"{(value / total) * 100:.1f}%"

    lines = [
        f"{path.name}",
        f"  total_cases: {total}",
        f"  request_success: {metrics['request_success']}/{total} ({pct(metrics['request_success'])})",
        f"  intent_correct: {metrics['intent_correct']}/{total} ({pct(metrics['intent_correct'])})",
        f"  schema_valid: {metrics['schema_valid']}/{total} ({pct(metrics['schema_valid'])})",
        f"  semantic_correct: {metrics['semantic_correct']}/{total} ({pct(metrics['semantic_correct'])})",
        f"  invalid_action=no: {metrics['invalid_action_no']}/{total} ({pct(metrics['invalid_action_no'])})",
        f"  interrupt_recovered: {metrics['interrupt_recovered']}/{total} ({pct(metrics['interrupt_recovered'])})",
        f"  final_case_pass: {metrics['final_case_pass']}/{total} ({pct(metrics['final_case_pass'])})",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: summarize_offline_eval.py <results.csv> [more.csv ...]", file=sys.stderr)
        return 1
    for raw in argv[1:]:
        path = Path(raw)
        if not path.is_file():
            print(f"missing file: {path}", file=sys.stderr)
            return 1
        print(summarize(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
