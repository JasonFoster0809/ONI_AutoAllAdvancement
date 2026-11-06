"""Read-only achievement catalog, report, and strategist context."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

from .oni_client import read_state


LOGGER = logging.getLogger(__name__)
PLAN_PATH = Path(__file__).with_name("achievements_plan.yaml")
TODO = "TODO_VERIFY"
REPORT_CATEGORIES = (
    "đã đạt",
    "làm được ở base game",
    "cần DLC",
    "cần tên lửa",
    "chưa rõ",
)


def _print_report(report: str) -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    try:
        print(report)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(report.encode(encoding, errors="backslashreplace").decode(encoding))


class AchievementPlanError(ValueError):
    """Raised when the achievement plan or state shape is invalid."""


def load_plan(path: str | Path = PLAN_PATH) -> dict[str, Any]:
    """Read the JSON-compatible YAML plan without requiring a YAML package."""
    plan_path = Path(path)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AchievementPlanError(
            f"achievement_plan_unavailable:{type(error).__name__}"
        ) from error
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise AchievementPlanError("achievement_plan_must_be_version_1")
    defaults = plan.get("defaults")
    entries = plan.get("entries")
    if not isinstance(defaults, dict) or not isinstance(entries, list):
        raise AchievementPlanError("achievement_plan_defaults_or_entries_invalid")
    ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AchievementPlanError(f"achievement_plan_entry_{index}_invalid")
        achievement_id = entry.get("id")
        if not isinstance(achievement_id, str) or not achievement_id:
            raise AchievementPlanError(f"achievement_plan_entry_{index}_id_invalid")
        if achievement_id in ids:
            raise AchievementPlanError(f"achievement_plan_duplicate_id:{achievement_id}")
        ids.add(achievement_id)
    return plan


def _state_achievements(state: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], bool]:
    raw = state.get("achievements")
    if not isinstance(raw, list):
        return {}, False
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        achievement_id = item.get("id")
        if isinstance(achievement_id, str) and achievement_id:
            if achievement_id in by_id:
                LOGGER.warning("Ignoring duplicate achievement state entry %s", achievement_id)
                continue
            by_id[achievement_id] = item
    return by_id, True


def _status(entry: Mapping[str, Any], state_item: Mapping[str, Any] | None) -> str:
    if state_item is None:
        return "chưa rõ"
    achieved = state_item.get("achieved")
    if achieved is True:
        return "đã đạt"
    if achieved is not False:
        return "chưa rõ"

    requires_dlc = entry.get("requires_dlc", TODO)
    requires_rocket = entry.get("requires_rocket", TODO)
    base_game = entry.get("base_game", TODO)
    difficulty = entry.get("difficulty", TODO)
    if requires_dlc is True:
        return "cần DLC"
    if requires_rocket is True:
        return "cần tên lửa"
    if base_game is True and isinstance(difficulty, (int, float)):
        return "làm được ở base game"
    return "chưa rõ"


def achievement_rows(
    state: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Merge plan metadata with observed state; missing fields remain unknown."""
    selected_plan = load_plan() if plan is None else dict(plan)
    defaults = selected_plan.get("defaults", {})
    entries = selected_plan.get("entries", [])
    if not isinstance(defaults, Mapping) or not isinstance(entries, list):
        raise AchievementPlanError("achievement_plan_defaults_or_entries_invalid")
    state_by_id, has_state_list = _state_achievements(state)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        achievement_id = entry.get("id")
        if not isinstance(achievement_id, str) or achievement_id in seen:
            continue
        seen.add(achievement_id)
        state_item = state_by_id.get(achievement_id)
        row = dict(defaults)
        row.update(entry)
        row["id"] = achievement_id
        name = state_item.get("name") if state_item is not None else None
        row["name"] = name if isinstance(name, str) and name else TODO
        achieved = state_item.get("achieved") if state_item is not None else None
        row["achieved"] = achieved if isinstance(achieved, bool) else None
        progress = state_item.get("progress") if state_item is not None else None
        row["progress"] = (
            [value for value in progress if isinstance(value, str)]
            if isinstance(progress, list)
            else None
        )
        row["state_available"] = has_state_list and state_item is not None
        row["plan_entry_found"] = True
        row["category"] = _status(row, state_item)
        rows.append(row)
    for achievement_id, state_item in state_by_id.items():
        if achievement_id in seen:
            continue
        row = dict(defaults)
        row.update(
            {
                "id": achievement_id,
                "name": state_item.get("name")
                if isinstance(state_item.get("name"), str)
                else TODO,
                "achieved": state_item.get("achieved")
                if isinstance(state_item.get("achieved"), bool)
                else None,
                "progress": state_item.get("progress")
                if isinstance(state_item.get("progress"), list)
                else None,
                "state_available": True,
                "plan_entry_found": False,
            }
        )
        row["category"] = _status(row, state_item)
        rows.append(row)
    return _suggested_order(rows)


def _suggested_order(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(rows))

    def rank(item: tuple[int, Mapping[str, Any]]) -> tuple[int, float, int]:
        index, row = item
        if row.get("achieved") is True:
            return (0, 0.0, index)
        if (
            row.get("base_game") is True
            and row.get("requires_rocket") is False
            and isinstance(row.get("difficulty"), (int, float))
        ):
            difficulty = float(row["difficulty"])
            return (1, difficulty, index)
        if row.get("requires_dlc") is True:
            return (3, float("inf"), index)
        return (2, float("inf"), index)

    ordered = sorted(indexed, key=rank)
    result: list[dict[str, Any]] = []
    next_order = 1
    for _, row in ordered:
        item = dict(row)
        if row.get("achieved") is True:
            item["suggested_order"] = None
        else:
            item["suggested_order"] = next_order
            next_order += 1
        result.append(item)
    return result


def strategist_context(
    state: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return read-only achievement goal hints; never returns game actions."""
    return [
        {
            "id": row["id"],
            "description": row["name"],
            "status": row["category"],
            "suggested_order": row["suggested_order"],
        }
        for row in achievement_rows(state, plan)
        if row.get("state_available") and row.get("achieved") is not True
    ]


def render_report(
    state: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
) -> str:
    rows = achievement_rows(state, plan)
    columns = (
        "id",
        "name",
        "category",
        "description",
        "requirement",
        "requires_dlc",
        "requires_rocket",
        "requires_multiple_worlds",
        "base_game",
        "difficulty",
        "mutually_exclusive",
        "progress",
    )
    rendered = [
        {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "category": str(row["category"]),
            "description": str(row.get("description", TODO)),
            "requirement": (
                str(row.get("requirement"))
                if row.get("requirement")
                else str(row.get("requirement_status", TODO))
            ),
            "requires_dlc": str(row.get("requires_dlc", TODO)),
            "requires_rocket": str(row.get("requires_rocket", TODO)),
            "requires_multiple_worlds": str(
                row.get("requires_multiple_worlds", TODO)
            ),
            "base_game": str(row.get("base_game", TODO)),
            "difficulty": str(row.get("difficulty", TODO)),
            "mutually_exclusive": str(row.get("mutually_exclusive", TODO)),
            "progress": " | ".join(row["progress"] or [])
            if isinstance(row.get("progress"), list)
            else TODO,
        }
        for row in rows
    ]
    widths = {
        column: max(
            len(column),
            *(len(item[column]) for item in rendered),
        )
        for column in columns
    }
    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    lines = [header, separator]
    for item in rendered:
        lines.append(" | ".join(item[column].ljust(widths[column]) for column in columns))
    counts = {
        category: sum(row["category"] == category for row in rows)
        for category in REPORT_CATEGORIES
    }
    lines.extend(
        [
            "",
            " | ".join(f"{category}: {counts[category]}" for category in REPORT_CATEGORIES),
            f"Achievements listed: {len(rows)}",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report read-only ONI achievements")
    parser.add_argument("--report", action="store_true", help="print the achievement table")
    parser.add_argument("--data-dir", type=Path, help="directory containing oni_state.json")
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args(argv)
    if not args.report:
        parser.error("use --report to print the achievement table")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        plan = load_plan(args.plan)
        state = read_state(args.data_dir)
        _print_report(render_report(state, plan))
        return 0
    except (AchievementPlanError, OSError, TypeError, ValueError) as error:
        LOGGER.error("Could not report achievements: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
