"""Print a compact summary of the most recent agent run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "agent.jsonl"


def _read_entries(path: Path) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as log_file:
        for line in log_file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, Mapping):
                entries.append(entry)
    return entries


def _latest_run(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    start = 0
    previous_step: int | None = None
    for index, entry in enumerate(entries):
        step = entry.get("step")
        if isinstance(step, bool) or not isinstance(step, int):
            continue
        if previous_step is not None and step <= previous_step:
            start = index
        previous_step = step
    return list(entries[start:])


def _rule_id(entry: Mapping[str, Any]) -> str | None:
    rule_id = entry.get("rule_id")
    if isinstance(rule_id, str) and rule_id:
        return rule_id
    evaluation = entry.get("rule_evaluation")
    selected = evaluation.get("selected") if isinstance(evaluation, Mapping) else None
    rule_id = selected.get("rule_id") if isinstance(selected, Mapping) else None
    return rule_id if isinstance(rule_id, str) and rule_id else None


def _display(value: Any) -> str:
    return str(value) if value is not None else "?"


def format_summary(path: str | Path = DEFAULT_LOG_PATH) -> str:
    """Return an eight-line summary of the latest contiguous run."""
    entries = _read_entries(Path(path))
    run = _latest_run(entries)
    if not run:
        return "Không có lượt log hợp lệ.\n"

    latest = run[-1]
    first_step, last_step = run[0].get("step"), latest.get("step")
    state = latest.get("state")
    state = state if isinstance(state, Mapping) else {}
    actions_total = sum(
        len(entry["actions"])
        for entry in run
        if isinstance(entry.get("actions"), list)
    )
    latest_actions = latest.get("actions")
    latest_action_count = len(latest_actions) if isinstance(latest_actions, list) else 0

    skip_reasons: Counter[str] = Counter()
    skipped_total = 0
    for entry in run:
        skipped = entry.get("skipped")
        if not isinstance(skipped, list):
            continue
        skipped_total += len(skipped)
        for item in skipped:
            if isinstance(item, Mapping) and isinstance(item.get("reason"), str):
                goal_id = item.get("goal_id")
                label = (
                    f"{goal_id}:{item['reason']}"
                    if isinstance(goal_id, str) and goal_id
                    else item["reason"]
                )
                skip_reasons[label] += 1
    reasons = ", ".join(
        f"{reason} ({count})"
        for reason, count in skip_reasons.most_common(4)
    ) or "không có"
    if len(reasons) > 160:
        reasons = reasons[:157] + "..."

    rules = list(dict.fromkeys(rule for entry in run if (rule := _rule_id(entry))))
    timestamp = latest.get("timestamp")
    goal = latest.get("goal_id", "no_goal")
    oxygen = state.get("oxygen_g", state.get("oxygen_air", state.get("oxygen_avg_g")))
    food = state.get("food_kcal")
    dupes = state.get("dupe_count")
    buildings = state.get("building_count")
    step_label = (
        f"{first_step}-{last_step}"
        if isinstance(first_step, int) and isinstance(last_step, int)
        else str(len(run))
    )

    return "\n".join(
        (
            f"Lượt gần nhất: {len(run)} bước (step {step_label})",
            f"Thời điểm: {_display(timestamp)}",
            f"Goal cuối: {_display(goal)}",
            f"Actions: {actions_total} tổng, {latest_action_count} ở bước cuối",
            f"Skipped: {skipped_total}; lý do: {reasons}",
            f"State: cycle={_display(state.get('cycle'))}, oxy={_display(oxygen)} g, food={_display(food)} kcal",
            f"Dupes: {_display(dupes)}; buildings: {_display(buildings)}",
            f"Luật khớp: {', '.join(rules) if rules else 'không có'}",
        )
    ) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the latest agent run")
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOG_PATH)
    args = parser.parse_args(argv)
    try:
        print(format_summary(args.logs), end="")
    except OSError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
