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
from . import planner as planner_module
from .llm_chooser import choose_action
from .gemini_manager import plan_goals
from .oni_client import read_state, send_command
from .planner import (
    mark_pending,
    next_step,
    registered_goal_ids,
    update_pending,
)
from .rule_engine import explain_rules, load_rules
from .rules import detect_emergency, oxygen_value
from .skills import (
    SkillPlan,
    SkillPlanningError,
    build_barracks,
    build_mess_area,
    build_oxygen_setup,
    build_power_basic,
    build_toilet_room,
    plan_emergency_actions,
)


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
    "emergency_food_kcal_per_dupe": 1000.0,
    "emergency_max_actions_per_turn": 12,
    "emergency_cooldown_cycles": 1,
    "emergency_pending_cycles": 2,
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
    food_kcal_per_dupe = config["emergency_food_kcal_per_dupe"]
    if (
        isinstance(food_kcal_per_dupe, bool)
        or not isinstance(food_kcal_per_dupe, (int, float))
        or not math.isfinite(food_kcal_per_dupe)
        or food_kcal_per_dupe < 0
    ):
        raise ValueError("emergency_food_kcal_per_dupe must be a finite non-negative number")
    for key in ("emergency_max_actions_per_turn", "emergency_cooldown_cycles", "emergency_pending_cycles"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
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
    parser.add_argument(
        "--manager",
        choices=("none", "qwen", "gemini"),
        default="qwen",
        help="goal manager; qwen preserves the existing tie-break behavior",
    )
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


def _state_cycle(state: Mapping[str, Any]) -> int | None:
    cycle = state.get("cycle")
    return cycle if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle >= 0 else None


def _emergency_action_satisfied(
    action: Mapping[str, Any], state: Mapping[str, Any]
) -> bool:
    if action.get("type") == "build":
        buildings = state.get("building_list")
        if not isinstance(buildings, list):
            return False
        return any(
            isinstance(building, Mapping)
            and building.get("id") == action.get("id")
            and building.get("x") == action.get("x")
            and building.get("y") == action.get("y")
            and building.get("state") in {"built", "under_construction"}
            for building in buildings
        )
    if action.get("type") == "set_dupe_priority":
        dupes = state.get("dupes")
        if not isinstance(dupes, list):
            return False
        return any(
            isinstance(dupe, Mapping)
            and isinstance(dupe.get("name"), str)
            and dupe["name"].casefold() == str(action.get("dupe", "")).casefold()
            and isinstance(dupe.get("job_priorities"), Mapping)
            and dupe["job_priorities"].get(action.get("group")) == action.get("priority")
            for dupe in dupes
        )
    return False


def _update_emergency_pending(
    state: Mapping[str, Any],
    pending: dict[str, dict[str, Any]],
    cycle: int | None,
    max_pending_cycles: int,
) -> list[dict[str, str]]:
    expired: list[dict[str, str]] = []
    for category, item in list(pending.items()):
        actions = item.get("actions", [])
        remaining = [
            action
            for action in actions
            if isinstance(action, Mapping)
            and not _emergency_action_satisfied(action, state)
        ]
        if not remaining:
            del pending[category]
            continue
        submitted_cycle = item.get("submitted_cycle")
        if (
            cycle is not None
            and isinstance(submitted_cycle, int)
            and cycle - submitted_cycle >= max_pending_cycles
        ):
            expired.append({"category": category, "reason": "pending_expired"})
            del pending[category]
            continue
        item["actions"] = [dict(action) for action in remaining]
    return expired


def _accepted_emergency_actions(
    actions: Sequence[Mapping[str, Any]], result: Mapping[str, Any]
) -> list[dict[str, Any]]:
    results = result.get("results")
    if not isinstance(results, list):
        return []
    return [
        dict(action)
        for action, action_result in zip(actions, results)
        if isinstance(action_result, Mapping) and action_result.get("ok") is True
    ]


def _rule_skill_executors(config: Mapping[str, Any]) -> dict[str, Any]:
    def run_skill(
        skill_name: str,
        skill: Any,
        state: Mapping[str, Any],
        catalog: Sequence[Mapping[str, Any]],
        _args: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            if skill_name == "build_barracks":
                actions = skill(
                    state,
                    catalog,
                    config.get("bed_id"),
                    config.get("door_id"),
                    config.get("tile_id"),
                    config.get("barracks_bed_count", 4),
                )
                return list(actions)
            if skill_name == "food_emergency":
                plan = plan_emergency_actions(state, catalog, "food", "dupe_hungry")
                for item in plan["skipped"]:
                    LOGGER.warning("Skill %s skipped: %s", skill_name, item["reason"])
                return list(plan["actions"])
            plan = skill(state, catalog)
            if isinstance(plan, SkillPlan):
                for warning in plan.warnings:
                    LOGGER.warning("Skill %s: %s", skill_name, warning)
                return list(plan.actions)
            return list(plan)
        except SkillPlanningError as error:
            LOGGER.warning("Skill %s skipped: %s", skill_name, error.reason)
            return []

    skills = {
        "build_barracks": build_barracks,
        "build_oxygen_setup": build_oxygen_setup,
        "build_mess_area": build_mess_area,
        "build_toilet_room": build_toilet_room,
        "build_power_basic": build_power_basic,
    }
    executors = {
        name: (
            lambda state, catalog, args, skill_name=name, skill=skill:
                run_skill(skill_name, skill, state, catalog, args)
        )
        for name, skill in skills.items()
    }
    executors["food_emergency"] = lambda state, catalog, args: run_skill(
        "food_emergency", None, state, catalog, args
    )
    return executors


def _update_rule_pending(
    state: Mapping[str, Any],
    pending: dict[str, dict[str, Any]],
    cycle: int | None,
    rules_document: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    expired: list[dict[str, str]] = []
    if cycle is None:
        return expired

    pending_cycles = {
        rule["id"]: rule["pending"]
        for rule in rules_document["rules"]
    }
    for rule_id, item in list(pending.items()):
        submitted_cycle = item.get("submitted_step")
        if not isinstance(submitted_cycle, int) or cycle < submitted_cycle:
            del pending[rule_id]
            expired.append({"rule_id": rule_id, "reason": "cycle_unavailable_or_rewound"})
            continue
        one_rule = {rule_id: item}
        expired_items = update_pending(
            state,
            one_rule,
            cycle,
            pending_cycles.get(rule_id, 1),
            catalog,
        )
        if rule_id not in one_rule:
            del pending[rule_id]
        else:
            pending[rule_id] = one_rule[rule_id]
        if expired_items:
            expired.append({"rule_id": rule_id, "reason": "pending_expired"})
    return expired


def run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = {**DEFAULT_CONFIG, **load_agent_config(args.config)}
    if args.barracks_bed_count is not None:
        config["barracks_bed_count"] = args.barracks_bed_count
    if args.tile_id is not None:
        config["tile_id"] = args.tile_id
    enabled_goals = args.goals or registered_goal_ids()
    rules_document = load_rules()
    rule_executors = _rule_skill_executors(config)
    oxygen_history: deque[bool] = deque(
        maxlen=config["oxygen_consecutive_readings"]
    )
    rule_history: deque[Mapping[str, Any]] = deque(maxlen=3)
    pending: dict[str, dict[str, Any]] = {}
    rule_pending: dict[str, dict[str, Any]] = {}
    rule_cooldowns: dict[str, int] = {}
    emergency_pending: dict[str, dict[str, Any]] = {}
    emergency_cooldowns: dict[str, int] = {}
    cached_manager_goals: list[dict[str, Any]] | None = None
    manager_plan_expires_cycle: int | None = None
    step = 0

    while args.max_steps == 0 or step < args.max_steps:
        step += 1
        state: dict[str, Any] = {}
        summary: dict[str, Any] = {}
        selected: dict[str, Any] = {"goal_id": "no_goal", "actions": [], "skipped": []}
        selection_reason = "rule"
        result: Mapping[str, Any] = {"reason": "no_goal"}
        pending_expired: list[dict[str, Any]] = []
        rule_pending_expired: list[dict[str, str]] = []
        emergency_pending_expired: list[dict[str, str]] = []
        rule_decision: Mapping[str, Any] | None = None
        manager_plan: list[dict[str, Any]] | None = None
        catalog: list[dict[str, Any]] = []
        cycle: int | None = None

        try:
            state = read_state(args.data_dir)
            cycle = _state_cycle(state)
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
            emergency_pending_expired = _update_emergency_pending(
                state,
                emergency_pending,
                cycle,
                config["emergency_pending_cycles"],
            )
            rule_pending_expired = _update_rule_pending(
                state,
                rule_pending,
                cycle,
                rules_document,
                catalog,
            )
            rule_history.append(state)
            for expired in pending_expired:
                LOGGER.warning(
                    "Pending goal %s expired after %d steps",
                    expired["goal_id"],
                    config["pending_steps"],
                )
            for expired in emergency_pending_expired:
                LOGGER.warning(
                    "Emergency %s pending actions expired", expired["category"]
                )
            for expired in rule_pending_expired:
                LOGGER.warning(
                    "Rule %s pending actions expired: %s",
                    expired["rule_id"],
                    expired["reason"],
                )

            emergency = detect_emergency(
                state,
                oxygen_history=tuple(oxygen_history),
                oxygen_min_g=config["oxygen_min_g"],
                oxygen_consecutive_readings=config["oxygen_consecutive_readings"],
                food_kcal_per_dupe=config["emergency_food_kcal_per_dupe"],
            )
            if emergency is not None:
                category = emergency["category"]
                reason = emergency["reason"]
                if category in emergency_pending:
                    emergency_plan = {
                        "actions": [],
                        "skipped": [{"reason": "emergency_pending"}],
                    }
                elif cycle is None:
                    emergency_plan = {
                        "actions": [],
                        "skipped": [{"reason": "cycle_unavailable"}],
                    }
                elif cycle < emergency_cooldowns.get(category or "", -1):
                    emergency_plan = {
                        "actions": [],
                        "skipped": [{"reason": "emergency_cooldown"}],
                    }
                else:
                    emergency_plan = plan_emergency_actions(
                        state, catalog, category or "", reason or "emergency"
                    )
                planned_actions = emergency_plan["actions"]
                max_actions = config["emergency_max_actions_per_turn"]
                if len(planned_actions) > max_actions:
                    emergency_plan["skipped"].append(
                        {"reason": "emergency_action_limit"}
                    )
                    planned_actions = planned_actions[:max_actions]
                for skipped_item in emergency_plan["skipped"]:
                    LOGGER.warning(
                        "Emergency %s skipped: %s",
                        category,
                        skipped_item["reason"],
                    )
                selected = {
                    "goal_id": "emergency",
                    "actions": planned_actions,
                    "skipped": emergency_plan["skipped"],
                    "reason": reason or "emergency",
                    "emergency_category": category,
                }
                selection_reason = "rule"
            else:
                manager_goal_ids = enabled_goals
                manager_config = config
                if args.manager == "gemini":
                    if cycle is None:
                        LOGGER.warning("Gemini manager skipped: cycle is unavailable")
                    elif (
                        cached_manager_goals is not None
                        and manager_plan_expires_cycle is not None
                        and cycle < manager_plan_expires_cycle
                    ):
                        manager_plan = cached_manager_goals
                    else:
                        goal_descriptions = [
                            {"id": goal.id, "description": goal.description}
                            for goal in planner_module.GOALS
                            if goal.id in enabled_goals
                        ]
                        manager_plan = plan_goals(state, goal_descriptions)
                        cached_manager_goals = manager_plan
                        if manager_plan is not None:
                            horizons = [
                                item["horizon_cycles"]
                                for item in manager_plan
                            ]
                            manager_plan_expires_cycle = cycle + min(horizons, default=5)

                    if manager_plan is not None:
                        manager_goal_ids = [item["id"] for item in manager_plan]
                        manager_config = {
                            **config,
                            "goal_ranks": {
                                goal_id: rank
                                for rank, goal_id in enumerate(manager_goal_ids)
                            },
                        }

                rule_decision = explain_rules(
                    state,
                    catalog=catalog,
                    document=rules_document,
                    history=tuple(rule_history),
                    pending=rule_pending,
                    cooldowns=rule_cooldowns,
                    executors=rule_executors,
                )
                chosen_rule = rule_decision["selected"]
                if chosen_rule is not None:
                    rule_id = chosen_rule["rule_id"]
                    actions = list(chosen_rule.get("actions", []))
                    reason = chosen_rule["reason"]
                    if cycle is None:
                        actions = []
                        reason = "cycle_unavailable"
                    else:
                        rule_cooldowns[rule_id] = cycle
                    skipped = []
                    if chosen_rule["status"] != "matched":
                        skipped.append({"rule_id": rule_id, "reason": reason})
                    elif not actions:
                        reason = "skill_planned_no_actions"
                        skipped.append({"rule_id": rule_id, "reason": reason})
                    selected = {
                        "goal_id": f"rule:{rule_id}",
                        "rule_id": rule_id,
                        "actions": actions,
                        "skipped": skipped,
                        "reason": reason,
                    }
                    selection_reason = "rule_engine"
                else:
                    tied_steps: list[dict[str, Any]] = []
                    selected = next_step(
                        state,
                        catalog,
                        manager_config,
                        pending,
                        enabled_goals=manager_goal_ids,
                        alternatives=tied_steps,
                    )
                if chosen_rule is None and tied_steps:
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
                    if args.manager == "qwen":
                        llm_choice = choose_action(state, candidates)
                        selection_reason = "qwen"
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
                elif chosen_rule is None and args.manager == "gemini" and manager_plan is not None:
                    selection_reason = "gemini"
                elif chosen_rule is None:
                    selection_reason = "planner"

            actions = selected["actions"]
            emergency_category = selected.get("emergency_category")
            if emergency_category is not None and cycle is not None:
                emergency_cooldowns[emergency_category] = (
                    cycle + config["emergency_cooldown_cycles"]
                )
            if not actions:
                result = {
                    "reason": selected.get("reason", "no_goal"),
                    "skipped": selected.get("skipped", []),
                }
            elif args.dry_run:
                result = {"reason": "dry_run", "actions": actions}
            else:
                command_result = send_command(actions, args.data_dir)
                result = command_result
                if emergency_category is not None and cycle is not None:
                    accepted = _accepted_emergency_actions(actions, command_result)
                    if accepted:
                        emergency_pending[emergency_category] = {
                            "actions": accepted,
                            "submitted_cycle": cycle,
                        }
                elif (
                    selected.get("rule_id") is not None
                    and cycle is not None
                    and isinstance(command_result.get("results"), list)
                    and all(
                        isinstance(item, Mapping)
                        for item in command_result["results"]
                    )
                ):
                    mark_pending(
                        rule_pending,
                        selected["rule_id"],
                        actions,
                        cycle,
                        command_result["results"],
                    )
                elif isinstance(command_result.get("results"), list) and all(
                    isinstance(item, Mapping)
                    for item in command_result["results"]
                ):
                    mark_pending(
                        pending,
                        selected["goal_id"],
                        actions,
                        step,
                        command_result["results"],
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
            "rule_evaluation": rule_decision,
            "rule_pending": _copy_pending(rule_pending),
            "rule_pending_expired": rule_pending_expired,
            "rule_cooldowns": rule_cooldowns,
            "manager": args.manager,
            "manager_plan": manager_plan,
            "manager_plan_expires_cycle": manager_plan_expires_cycle,
            "emergency_pending": _copy_pending(emergency_pending),
            "emergency_pending_expired": emergency_pending_expired,
            "emergency_cooldowns": emergency_cooldowns,
            "result": result,
        }
        _append_log(entry)
        print(json.dumps(entry, ensure_ascii=False, default=str))
        if args.max_steps == 0 or step < args.max_steps:
            time.sleep(args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
