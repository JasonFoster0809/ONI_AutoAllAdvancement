"""Measurable run metrics derived from the agent's JSONL log."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _cycle(state: Any) -> int | None:
    if not isinstance(state, Mapping):
        return None
    value = state.get("cycle")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _dupe_count(state: Any) -> int | None:
    if not isinstance(state, Mapping):
        return None
    value = state.get("dupe_count")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _timestamp(entry: Mapping[str, Any]) -> datetime | None:
    value = entry.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def calculate_metrics(log_path: str | Path) -> dict[str, Any]:
    """Calculate cycle, command-result, elapsed-time, and dupe-count metrics."""
    entries: list[Mapping[str, Any]] = []
    malformed_lines = 0
    with Path(log_path).open("r", encoding="utf-8") as log_file:
        for line in log_file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if isinstance(entry, Mapping):
                entries.append(entry)
            else:
                malformed_lines += 1

    cycle_samples = [
        (cycle, _timestamp(entry))
        for entry in entries
        if (cycle := _cycle(entry.get("state"))) is not None
    ]
    latest_cycle = cycle_samples[-1][0] if cycle_samples else None
    valid_intervals = [
        (earlier_time, later_time, later_cycle - earlier_cycle)
        for (earlier_cycle, earlier_time), (later_cycle, later_time)
        in zip(cycle_samples, cycle_samples[1:])
        if earlier_time is not None
        and later_time is not None
        and later_time > earlier_time
        and later_cycle > earlier_cycle
    ]
    cycle_delta = sum(delta for _, _, delta in valid_intervals)
    elapsed_seconds = sum(
        (later_time - earlier_time).total_seconds()
        for earlier_time, later_time, _ in valid_intervals
    )
    avg_seconds_per_cycle = (
        elapsed_seconds / cycle_delta if cycle_delta else None
    )

    commands_ok = 0
    commands_blocked = 0
    for entry in entries:
        result = entry.get("result")
        results = result.get("results") if isinstance(result, Mapping) else None
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, Mapping):
                continue
            if item.get("ok") is True:
                commands_ok += 1
            if item.get("reason") == "blocked":
                commands_blocked += 1

    latest_dupes = next(
        (
            count
            for entry in reversed(entries)
            if (count := _dupe_count(entry.get("state"))) is not None
        ),
        None,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries_read": len(entries),
        "malformed_lines": malformed_lines,
        "cycle_survived_to": latest_cycle,
        "cycle_metric_note": "latest observed cycle, not a confirmed death cycle",
        "commands_ok": commands_ok,
        "commands_blocked": commands_blocked,
        "average_seconds_per_cycle": (
            round(avg_seconds_per_cycle, 3)
            if avg_seconds_per_cycle is not None
            else None
        ),
        "dupes_alive": latest_dupes,
    }


def write_metrics(metrics: Mapping[str, Any], output_path: str | Path) -> None:
    """Write metrics JSON atomically enough for local readers."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
