"""Goal-driven agent loop with emergency rules and file-based commands."""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import CatalogError, load_catalog
from .llm_chooser import choose_action
from .oni_client import read_state, send_command
from .planner import (
    mark_pending,
    next_step,
    registered_goal_ids,
    update_pending,
)
from .rules import choose_emergency_action, oxygen_value


LOGGER = logging.getLogger(__name__)
AGENT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = AGENT_DIR / "config.json"
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "agent.jsonl"

DEFAULT_CONFIG: dict[str, Any] = {
    "priority_techs": ["FarmingTech"],
    "pending_steps": 30,
    "bed_id": None,
    "door_id": None,
    "tile_id": None,
    "barracks_bed_count": 4,
    "oxygen_min_g": 50.0,
    "oxygen_consecutive_readings": 3,
    "goal_ranks": {},
}


def load_agent_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load goal settings over conservative defaults without inventing prefab IDs."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        supplied = json.load(config_file)
    if not isinstance(supplied, dict):
        raise ValueError("agent config must be a JSON object")
    config = {**DEFAULT_CONFIG, **supplied}
    if (
        not isinstance(config["priority_techs"], list)
        or any(not isinstance(tech_id, str) or not tech_id for tech_id in config["priority_techs"])
    ):
        raise ValueError("priority_techs must be an array of non-empty strings")
    pending_steps = config["pending_steps"]
    if isinstance(pending_steps, bool) or not isinstance(pending_steps, int) or pending_steps <= 0:
        raise ValueError("pending_steps must be a positive integer")
    for key in ("bed_id", "door_id", "tile_id"):
        if config[key] is not None and (not isinstance(config[key], str) or not config[key]):
            raise ValueError(f"{key} must be a non-empty string or null")
    bed_count = config["barracks_bed_count"]
    if isinstance(bed_count, bool) or not isinstance(bed_count, int) or bed_count <= 0:
        raise ValueError("barracks_bed_count must be a positive integer")
    oxygen_min_g = config["oxygen_min_g"]
    if (
        isinstance(oxygen_min_g, bool)
        or not isinstance(oxygen_min_g, (int, float))
        or not math.isfinite(oxygen_min_g)
        or oxygen_min_g < 0
    ):
        raise ValueError("oxygen_min_g must be a finite non-negative number")
    oxygen_readings = config["oxygen_consecutive_readings"]
    if (
        isinstance(oxygen_readings, bool)
        or not isinstance(oxygen_readings, int)
        or oxygen_readings <= 0
    ):
        raise ValueError("oxygen_consecutive_readings must be a positive integer")
    return config


def _state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    dupes = state.get("dupes")
    resources = state.get("resources")
    return {
        "cycle": state.get("cycle"),
        "dupe_count": len(dupes) if isinstance(dupes, list) else None,
        "oxygen_air": state.get("oxygen_air"),
        "food_kcal": resources.get("food_kcal") if isinstance(resources, Mapping) else None,
    }


def _append_log(entry: Mapping[str, Any], path: Path | None = None) -> None:
    destination = LOG_PATH if path is None else path
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _parse_goals(value: str) -> list[str]:
    goals = [goal.strip() for goal in value.split(",") if goal.strip()]
    if not goals:
        raise argparse.ArgumentTypeError("--goals requires at least one goal id")
    unknown = sorted(set(goals) - set(registered_goal_ids()))
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown goal id(s): {', '.join(unknown)}")
    return goals


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ONI colony file-based goal agent")
    parser.add_argument("--dry-run", action="store_true", help="print choices without sending commands")
    parser.add_argument("--max-steps", type=int, default=0, help="stop after N steps; 0 runs indefinitely")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--barracks-bed-count", type=int)
    parser.add_argument("--tile-id")
    parser.add_argument(
        "--goals",
        type=_parse_goals,
        help="comma-separated enabled goal ids; defaults to all registered goals",
    )
    args = parser.parse_args(argv)
    if args.max_steps < 0:
        parser.error("--max-steps must be non-negative")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.barracks_bed_count is not None and args.barracks_bed_count <= 0:
        parser.error("--barracks-bed-count must be positive")
    return args


def _copy_pending(pending: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return json.loads(json.dumps(pending, ensure_ascii=False))


def run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_agent_config(args.config)
    if args.barracks_bed_count is not None:
        config["barracks_bed_count"] = args.barracks_bed_count
    if args.tile_id is not None:
        config["tile_id"] = args.tile_id
    enabled_goals = args.goals or registered_goal_ids()
    oxygen_history: deque[bool] = deque(
        maxlen=config["oxygen_consecutive_readings"]
    )
    pending: dict[str, dict[str, Any]] = {}
    step = 0

    while args.max_steps == 0 or step < args.max_steps:
        step += 1
        state: dict[str, Any] = {}
        summary: dict[str, Any] = {}
        selected: dict[str, Any] = {"goal_id": "no_goal", "actions": [], "skipped": []}
        selection_reason = "rule"
        result: Mapping[str, Any] = {"reason": "no_goal"}
        pending_expired: list[dict[str, Any]] = []
        catalog: list[dict[str, Any]] = []

        try:
            state = read_state(args.data_dir)
            oxygen = oxygen_value(state)
            oxygen_history.append(
                oxygen is not None and oxygen < config["oxygen_min_g"]
            )
            summary = _state_summary(state)
            catalog = load_catalog(args.data_dir)
            pending_expired = update_pending(
                state,
                pending,
                step,
                config["pending_steps"],
                catalog,
            )
            for expired in pending_expired:
                LOGGER.warning(
                    "Pending goal %s expired after %d steps",
                    expired["goal_id"],
                    config["pending_steps"],
                )

            emergency = choose_emergency_action(
                state,
                [],
                oxygen_history=tuple(oxygen_history),
                oxygen_min_g=config["oxygen_min_g"],
                oxygen_consecutive_readings=config["oxygen_consecutive_readings"],
            )
            if emergency is not None:
                selected = {
                    "goal_id": "emergency",
                    "actions": emergency.get("actions", []),
                    "skipped": [],
                    "reason": emergency.get("reason", "emergency"),
                }
                selection_reason = "rule"
            else:
                tied_steps: list[dict[str, Any]] = []
                selected = next_step(
                    state,
                    catalog,
                    config,
                    pending,
                    enabled_goals=enabled_goals,
                    alternatives=tied_steps,
                )
                if tied_steps:
                    candidates = [
                        {
                            "id": selected["goal_id"],
                            "category": "goal",
                            "actions": selected["actions"],
                        },
                        *[
                            {
                                "id": tied["goal_id"],
                                "category": "goal",
                                "actions": tied["actions"],
                            }
                            for tied in tied_steps
                        ],
                        {"id": "no_op", "category": "no_op", "actions": []},
                    ]
                    llm_choice = choose_action(state, candidates)
                    selection_reason = "llm"
                    if llm_choice.get("id") == "no_op":
                        selected = {
                            "goal_id": "no_goal",
                            "actions": [],
                            "skipped": selected["skipped"],
                            "reason": "llm_no_op",
                        }
                    else:
                        chosen_goal = next(
                            candidate
                            for candidate in [selected, *tied_steps]
                            if candidate["goal_id"] == llm_choice.get("id")
                        )
                        selected = {**chosen_goal, "skipped": selected["skipped"]}

            actions = selected["actions"]
            if not actions:
                result = {"reason": selected.get("reason", "no_goal")}
            elif args.dry_run:
                result = {"reason": "dry_run", "actions": actions}
            else:
                command_result = send_command(actions, args.data_dir)
                result = command_result
                command_results = command_result.get("results")
                if isinstance(command_results, list) and all(
                    isinstance(item, Mapping) for item in command_results
                ):
                    mark_pending(
                        pending,
                        selected["goal_id"],
                        actions,
                        step,
                        command_results,
                    )
        except (OSError, ValueError, TimeoutError, CatalogError) as error:
            LOGGER.exception("Agent step %d failed", step)
            result = {"reason": "error", "error": str(error)}
            selection_reason = "error"
            selected["skipped"].append(
                {"goal_id": "agent", "reason": f"error:{error}"}
            )

        skipped = [*selected.get("skipped", []), *pending_expired]
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "state": summary,
            "goal_id": selected.get("goal_id", "no_goal"),
            "actions": selected.get("actions", []),
            "skipped": skipped,
            "selection_reason": selection_reason,
            "pending": _copy_pending(pending),
            "pending_expired": pending_expired,
            "result": result,
        }
        _append_log(entry)
        print(json.dumps(entry, ensure_ascii=False, default=str))
        if args.max_steps == 0 or step < args.max_steps:
            time.sleep(args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
