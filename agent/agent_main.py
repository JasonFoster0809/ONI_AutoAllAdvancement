"""Offline-testable agent loop; game communication is file-based."""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import CatalogError, load_catalog
from .llm_chooser import choose_action
from .oni_client import read_state, send_command
from .rules import choose_emergency_action
from .skills import (
    SkillPlanningError,
    build_bedroom,
    build_ladder_shaft,
    build_research_area,
    dig_corridor,
)


LOGGER = logging.getLogger(__name__)
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "agent.jsonl"


def _candidate(
    candidate_id: str, category: str, actions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "category": category,
        "actions": [dict(action) for action in actions],
    }


def build_candidates(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    *,
    bed_id: str | None = None,
    door_id: str | None = None,
    research_center_id: str | None = None,
    ladder_id: str | None = None,
    corridor: tuple[int, int, int, int] | None = None,
) -> list[dict[str, Any]]:
    """Build only configured skill plans; prefab IDs come from caller/catalog."""
    candidates = [_candidate("no_op", "no_op", [])]
    plans = (
        ("bedroom", "housing", bed_id is not None and door_id is not None,
         lambda: build_bedroom(state, catalog, bed_id, door_id)),
        ("research_area", "research", research_center_id is not None,
         lambda: build_research_area(state, catalog, research_center_id)),
        ("ladder_shaft", "mobility", ladder_id is not None,
         lambda: build_ladder_shaft(state, catalog, ladder_id)),
        ("corridor", "dig", corridor is not None,
         lambda: dig_corridor(state, *corridor)),
    )
    for candidate_id, category, enabled, create_plan in plans:
        if not enabled:
            continue
        try:
            candidates.append(_candidate(candidate_id, category, create_plan()))
        except (CatalogError, SkillPlanningError, KeyError, TypeError, ValueError) as error:
            LOGGER.warning("Could not plan %s: %s", candidate_id, error)
    return candidates


def _state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    dupes = state.get("dupes")
    return {
        "cycle": state.get("cycle"),
        "dupe_count": len(dupes) if isinstance(dupes, list) else None,
        "oxygen_air": state.get("oxygen_air"),
        "food_kcal": (state.get("resources") or {}).get("food_kcal")
        if isinstance(state.get("resources"), Mapping)
        else None,
    }


def _append_log(entry: Mapping[str, Any], path: Path | None = None) -> None:
    destination = LOG_PATH if path is None else path
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _parse_corridor(value: str) -> tuple[int, int, int, int]:
    try:
        coordinates = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("corridor must be x1,y1,x2,y2 integers") from error
    if len(coordinates) != 4:
        raise argparse.ArgumentTypeError("corridor must be x1,y1,x2,y2 integers")
    return coordinates[0], coordinates[1], coordinates[2], coordinates[3]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ONI colony file-based agent")
    parser.add_argument("--dry-run", action="store_true", help="print choices without sending commands")
    parser.add_argument("--max-steps", type=int, default=0, help="stop after N steps; 0 runs indefinitely")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--bed-id", help="catalog prefab ID for the bed skill")
    parser.add_argument("--door-id", help="catalog prefab ID for the door skill")
    parser.add_argument("--research-center-id", help="catalog prefab ID for the research skill")
    parser.add_argument("--ladder-id", help="catalog prefab ID for the ladder skill")
    parser.add_argument("--corridor", type=_parse_corridor, help="dig coordinates x1,y1,x2,y2")
    args = parser.parse_args(argv)
    if args.max_steps < 0:
        parser.error("--max-steps must be non-negative")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if (args.bed_id is None) != (args.door_id is None):
        parser.error("--bed-id and --door-id must be supplied together")
    return args


def run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    step = 0
    while args.max_steps == 0 or step < args.max_steps:
        step += 1
        state: dict[str, Any] = {}
        summary: dict[str, Any] = {}
        selected: Mapping[str, Any] = {"id": "no_op", "actions": []}
        result: Mapping[str, Any] = {"reason": "no_action"}
        try:
            state = read_state(args.data_dir)
            summary = _state_summary(state)
            selected = choose_emergency_action(state, [])
            if selected is None:
                catalog = load_catalog(args.data_dir)
                candidates = build_candidates(
                    state,
                    catalog,
                    bed_id=args.bed_id,
                    door_id=args.door_id,
                    research_center_id=args.research_center_id,
                    ladder_id=args.ladder_id,
                    corridor=args.corridor,
                )
                selected = choose_action(state, candidates)
            actions = selected.get("actions")
            if not isinstance(actions, list) or not actions:
                result = {"reason": selected.get("reason", "no_action")}
            elif args.dry_run:
                result = {"reason": "dry_run", "actions": actions}
            else:
                result = send_command(actions, args.data_dir)
        except (OSError, ValueError, TimeoutError, CatalogError) as error:
            LOGGER.exception("Agent step %d failed", step)
            result = {"reason": "error", "error": str(error)}

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "state": summary,
            "action_id": selected.get("id"),
            "actions": selected.get("actions", []),
            "result": result,
        }
        _append_log(entry)
        print(json.dumps(entry, ensure_ascii=False, default=str))
        if args.max_steps == 0 or step < args.max_steps:
            time.sleep(args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
