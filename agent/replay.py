"""Replay logged rule decisions against their recorded rule inputs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import agent_main
from .catalog import load_catalog
from .rule_engine import explain_rules, load_rules


def _read_entries(path: Path) -> tuple[list[Mapping[str, Any]], list[str]]:
    entries: list[Mapping[str, Any]] = []
    issues: list[str] = []
    with path.open("r", encoding="utf-8") as log_file:
        for line_number, line in enumerate(log_file, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"line {line_number}: invalid JSON")
                continue
            if isinstance(entry, Mapping):
                entries.append(entry)
            else:
                issues.append(f"line {line_number}: entry is not an object")
    return entries, issues


def replay_log(
    log_path: str | Path,
    catalog: Sequence[Mapping[str, Any]],
    *,
    rules_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate rule-selected entries and compare selected actions."""
    entries, issues = _read_entries(Path(log_path))
    rules = load_rules(rules_path) if rules_path is not None else load_rules()
    comparisons: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("selection_reason") != "rule_engine":
            continue
        replay_input = entry.get("rule_replay_input")
        step = entry.get("step")
        rule_id = entry.get("rule_id")
        if not isinstance(replay_input, Mapping):
            comparisons.append(
                {
                    "step": step,
                    "logged_rule": rule_id,
                    "status": "unavailable",
                    "reason": "rule_input_not_recorded",
                }
            )
            continue
        state = replay_input.get("state")
        if not isinstance(state, Mapping):
            comparisons.append(
                {
                    "step": step,
                    "logged_rule": rule_id,
                    "status": "unavailable",
                    "reason": "invalid_recorded_state",
                }
            )
            continue
        history = replay_input.get("history", [])
        pending = replay_input.get("pending", {})
        cooldowns = replay_input.get("cooldowns", {})
        if (
            not isinstance(history, list)
            or any(not isinstance(item, Mapping) for item in history)
            or not isinstance(pending, Mapping)
            or not isinstance(cooldowns, Mapping)
        ):
            comparisons.append(
                {
                    "step": step,
                    "logged_rule": rule_id,
                    "status": "unavailable",
                    "reason": "invalid_rule_context",
                }
            )
            continue
        config = dict(agent_main.DEFAULT_CONFIG)
        skill_config = replay_input.get("skill_config")
        if isinstance(skill_config, Mapping):
            config.update(skill_config)
        decision = explain_rules(
            state,
            catalog=catalog,
            document=rules,
            history=history,
            pending=pending,
            cooldowns=cooldowns,
            executors=agent_main._rule_skill_executors(config),
            food_kcal_per_dupe=config[
                "basic_survival_food_kcal_per_dupe"
            ],
        )
        selected = decision.get("selected")
        replayed_rule = selected.get("rule_id") if isinstance(selected, Mapping) else None
        replayed_actions = selected.get("actions", []) if isinstance(selected, Mapping) else []
        actual_actions = entry.get("actions")
        actions_match = isinstance(actual_actions, list) and replayed_actions == actual_actions
        decision_match = replayed_rule == rule_id
        comparisons.append(
            {
                "step": step,
                "logged_rule": rule_id,
                "replayed_rule": replayed_rule,
                "actions_match": actions_match,
                "decision_match": decision_match,
                "status": "match" if actions_match and decision_match else "mismatch",
            }
        )
    counts = {
        status: sum(item["status"] == status for item in comparisons)
        for status in ("match", "mismatch", "unavailable")
    }
    return {
        "entries_read": len(entries),
        "comparisons": comparisons,
        "counts": counts,
        "issues": issues,
    }


def _markdown(result: Mapping[str, Any]) -> str:
    counts = result["counts"]
    lines = [
        "# Rule replay report",
        "",
        f"- Log entries read: {result['entries_read']}",
        f"- Matches: {counts['match']}",
        f"- Mismatches: {counts['mismatch']}",
        f"- Unavailable: {counts['unavailable']}",
        "",
        "| Step | Logged rule | Replayed rule | Status |",
        "|---:|---|---|---|",
    ]
    lines.extend(
        f"| {item.get('step', 'unknown')} | {item.get('logged_rule') or 'unknown'} "
        f"| {item.get('replayed_rule') or 'unknown'} | {item['status']} |"
        for item in result["comparisons"]
    )
    if result["issues"]:
        lines.extend(["", "## Log issues", ""])
        lines.extend(f"- {issue}" for issue in result["issues"])
    lines.extend(
        [
            "",
            "Unavailable comparisons mean the log predates recorded rule inputs or has incomplete context.",
            "Replay uses the supplied/current catalog; catalog changes can cause mismatches.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay rule decisions from agent JSONL")
    parser.add_argument("--logs", type=Path, default=Path("logs") / "agent.jsonl")
    parser.add_argument("--catalog", type=Path, help="catalog JSON file; defaults to ONI data directory")
    parser.add_argument("--rules", type=Path, help="rules JSON-compatible YAML file")
    args = parser.parse_args(argv)
    if args.catalog is None:
        catalog = load_catalog()
    else:
        data = json.loads(args.catalog.read_text(encoding="utf-8"))
        if not isinstance(data, list) or any(not isinstance(item, Mapping) for item in data):
            parser.error("catalog must be a JSON array of objects")
        catalog = data
    result = replay_log(args.logs, catalog, rules_path=args.rules)
    print(_markdown(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
