"""Offline stall diagnostics based on agent JSONL and a current state snapshot."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .oni_client import read_state


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _algae_mass(state: Mapping[str, Any]) -> float | None:
    buildings = state.get("building_list")
    if not isinstance(buildings, list):
        return None
    machines = [
        item
        for item in buildings
        if isinstance(item, Mapping)
        and item.get("id") == "MineralDeoxidizer"
        and item.get("state") == "built"
    ]
    if not machines or any("stored" not in item for item in machines):
        return None
    total = 0.0
    for machine in machines:
        stored = machine["stored"]
        if isinstance(stored, Mapping):
            mass = _number(stored.get("Algae", 0))
        elif isinstance(stored, list):
            matching = [
                _number(item.get("kg"))
                for item in stored
                if isinstance(item, Mapping) and item.get("element") == "Algae"
            ]
            if any(value is None for value in matching):
                return None
            mass = sum(value for value in matching if value is not None)
        else:
            return None
        if mass is None or mass < 0:
            return None
        total += mass
    return total


def _research_progress(state: Mapping[str, Any]) -> tuple[str | None, float | None]:
    research = state.get("research")
    if not isinstance(research, Mapping):
        return None, None
    active = research.get("active")
    if not isinstance(active, str) or not active:
        return None, None
    techs = research.get("techs")
    if not isinstance(techs, list):
        return active, None
    tech = next(
        (
            item
            for item in techs
            if isinstance(item, Mapping) and item.get("id") == active
        ),
        None,
    )
    costs = tech.get("cost") if isinstance(tech, Mapping) else None
    if not isinstance(costs, list) or not costs:
        return active, None
    required = 0.0
    current = 0.0
    for item in costs:
        if not isinstance(item, Mapping):
            return active, None
        required_value = _number(item.get("required"))
        current_value = _number(item.get("current"))
        if required_value is None or current_value is None or required_value < 0:
            return active, None
        required += required_value
        current += current_value
    if required <= 0:
        return active, None
    return active, current / required


def state_metrics(state: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only non-identifying measurable fields used for trend reports."""
    environment = state.get("environment")
    oxygen = (
        _number(environment.get("oxygen_avg_g"))
        if isinstance(environment, Mapping)
        else None
    )
    if oxygen is None:
        oxygen = _number(state.get("oxygen_air"))

    dupes = state.get("dupes")
    stress_values = [
        _number(dupe.get("stress"))
        for dupe in dupes
        if isinstance(dupe, Mapping)
    ] if isinstance(dupes, list) else []
    known_stress = [value for value in stress_values if value is not None]
    research_active, research_progress = _research_progress(state)
    return {
        "cycle": state.get("cycle"),
        "oxygen_g": oxygen,
        "max_stress": max(known_stress) if known_stress else None,
        "algae_kg": _algae_mass(state),
        "research_active": research_active,
        "research_progress": research_progress,
    }


def _read_logs(path: Path) -> tuple[list[Mapping[str, Any]], list[str]]:
    entries: list[Mapping[str, Any]] = []
    issues: list[str] = []
    with path.open("r", encoding="utf-8") as log_file:
        for line_number, line in enumerate(log_file, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"Line {line_number}: invalid JSON")
                continue
            if not isinstance(entry, Mapping):
                issues.append(f"Line {line_number}: entry is not an object")
                continue
            entries.append(entry)
    return entries, issues


def _trend(
    samples: Sequence[Mapping[str, Any]], key: str, *, increasing: bool
) -> bool | None:
    values = [_number(sample.get(key)) for sample in samples[-3:]]
    if len(values) < 3 or any(value is None for value in values):
        return None
    numbers = [value for value in values if value is not None]
    comparisons = zip(numbers, numbers[1:])
    return all(
        current > previous if increasing else current < previous
        for previous, current in comparisons
    )


def diagnose(
    log_path: str | Path,
    state: Mapping[str, Any],
) -> str:
    """Return a Markdown report; missing telemetry is reported as unknown."""
    path = Path(log_path)
    entries, issues = _read_logs(path)
    samples = [
        {
            **entry["state"],
            "oxygen_g": entry["state"].get(
                "oxygen_g", entry["state"].get("oxygen_air")
            ),
        }
        for entry in entries
        if isinstance(entry.get("state"), Mapping)
    ]
    current = state_metrics(state)
    samples.append(current)

    stress_rising = _trend(samples, "max_stress", increasing=True)
    oxygen_falling = _trend(samples, "oxygen_g", increasing=False)
    algae = current.get("algae_kg")
    blocked: Counter[tuple[Any, Any, Any]] = Counter()
    for entry in entries:
        actions = entry.get("actions")
        results = entry.get("result", {}).get("results") if isinstance(entry.get("result"), Mapping) else None
        if not isinstance(actions, list) or not isinstance(results, list):
            continue
        for action, result in zip(actions, results):
            if (
                isinstance(action, Mapping)
                and action.get("type") == "build"
                and isinstance(result, Mapping)
                and result.get("ok") is False
                and result.get("reason") == "blocked"
            ):
                blocked[(action.get("id"), action.get("x"), action.get("y"))] += 1
    repeated_blocked = [
        (signature, count)
        for signature, count in blocked.items()
        if count >= 2
    ]

    research_samples = [
        sample
        for sample in samples
        if isinstance(sample.get("research_active"), str)
        and _number(sample.get("research_progress")) is not None
    ][-3:]
    research_stalled: bool | None = None
    if len(research_samples) >= 3:
        active_ids = [sample["research_active"] for sample in research_samples]
        progress = [_number(sample["research_progress"]) for sample in research_samples]
        if len(set(active_ids)) == 1 and all(value is not None for value in progress):
            research_stalled = len(set(progress)) == 1

    rows = [
        ("Stress steigt in mindestens drei aufeinanderfolgenden Messungen",
         "increasing" if stress_rising is True else "not detected" if stress_rising is False else "unknown"),
        ("Sauerstoff sinkt in mindestens drei aufeinanderfolgenden Messungen",
         "falling" if oxygen_falling is True else "not detected" if oxygen_falling is False else "unknown"),
        ("Algae im MineralDeoxidizer-Speicher", f"{algae:g} kg" if isinstance(algae, (int, float)) else "unknown"),
        ("Wiederholt blockierte Bauaufträge (gleiche ID/Koordinate, mindestens zweimal)",
         str(len(repeated_blocked))),
        ("Forschungsfortschritt unverändert in mindestens drei Messungen",
         "stalled" if research_stalled is True else "not detected" if research_stalled is False else "unknown"),
    ]
    output = [
        "# Colony stall diagnostics",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Agent log entries read: {len(entries)}",
        f"- Current cycle: {current.get('cycle') if current.get('cycle') is not None else 'unknown'}",
        "- This report identifies signals only; it cannot establish a death cause.",
        "",
        "| Signal | Observation |",
        "|---|---|",
    ]
    output.extend(f"| {name} | {value} |" for name, value in rows)
    if repeated_blocked:
        output.extend(["", "## Repeated blocked builds", ""])
        output.extend(
            f"- `{signature[0]}` at `({signature[1]}, {signature[2]})`: {count} blocked attempts"
            for signature, count in repeated_blocked
        )
    if issues:
        output.extend(["", "## Log format issues", ""])
        output.extend(f"- {issue}" for issue in issues)
    output.extend(
        [
            "",
            "## Data gaps",
            "",
            "- Historical stress, oxygen, Algae, and research trends need those fields in log snapshots; older logs may report `unknown`.",
            "- Death causality is not inferable from agent decision logs alone.",
            "- Configured machine rates are not used to infer live Algae consumption.",
        ]
    )
    return "\n".join(output) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose ONI agent stalls from logs and state")
    parser.add_argument("--logs", type=Path, default=Path("logs") / "agent.jsonl")
    parser.add_argument("--state", type=Path, help="state JSON path; defaults to the ONI data directory")
    parser.add_argument("--output", type=Path, help="write Markdown here instead of stdout")
    args = parser.parse_args(argv)
    state = (
        json.loads(args.state.read_text(encoding="utf-8"))
        if args.state is not None
        else read_state()
    )
    if not isinstance(state, Mapping):
        parser.error("state JSON must contain an object")
    report = diagnose(args.logs, state)
    if args.output is None:
        print(report, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
