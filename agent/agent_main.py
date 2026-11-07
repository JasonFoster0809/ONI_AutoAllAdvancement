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
from .achievements_plan import strategist_context as achievement_strategist_context
from .diagnostics import state_metrics
from .llm_chooser import choose_action
from .gemini_manager import plan_goals
from .metrics import calculate_metrics, write_metrics
from .memory import (
    MemoryTracker,
    load_memory,
    load_proposed_rules,
)
from .oni_client import get_data_dir, read_state, send_command
from .planner import (
    mark_pending,
    next_step,
    registered_goal_ids,
    update_pending,
)
from .rule_engine import explain_rules, load_rules
from .rules import detect_emergency, oxygen_value
from .scoring import (
    DEFAULT_SCORING_CONFIG,
    EventJournalReader,
    ScoringTracker,
    current_commit_hash,
    make_score_record,
    write_score_record,
)
from .strategist import Strategist, create_goal_provider
from .skills import (
    SkillPlan,
    SkillPlanningError,
    build_barracks,
    build_basic_survival,
    build_food_basic,
    build_mess_area,
    build_oxygen_setup,
    build_power_basic,
    build_recreation,
    build_storage_area,
    build_toilet_room,
    build_water_setup,
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
    "basic_survival_food_kcal_per_dupe": 1000.0,
    "basic_survival_notes": {
        "deoxidizer_per_dupe": "TODO_VERIFY; conservative agent policy assumption",
        "food_kcal_per_dupe": "TODO_VERIFY; agent policy threshold, not verified consumption",
        "power_output_and_layout": "TODO_VERIFY; electrical sizing and layout are not verified",
    },
    "emergency_max_actions_per_turn": 12,
    "emergency_cooldown_cycles": 1,
    "emergency_pending_cycles": 2,
    "scoring": DEFAULT_SCORING_CONFIG,
    "strategist": {
        "provider": "none",
        "interval_cycles": 3,
        "max_goals": 3,
        "timeout_seconds": 60,
        "retry_attempts": 2,
        "backoff_seconds": 0.5,
        "ollama_model": "qwen2.5-coder:3b",
        "gemini_model": None,
    },
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
    if "research_chain_order" in config and (
        not isinstance(config["research_chain_order"], list)
        or any(
            not isinstance(tech_id, str) or not tech_id
            for tech_id in config["research_chain_order"]
        )
    ):
        raise ValueError("research_chain_order must be an array of non-empty strings")
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
    basic_survival_food_kcal = config["basic_survival_food_kcal_per_dupe"]
    if (
        isinstance(basic_survival_food_kcal, bool)
        or not isinstance(basic_survival_food_kcal, (int, float))
        or not math.isfinite(basic_survival_food_kcal)
        or basic_survival_food_kcal < 0
    ):
        raise ValueError(
            "basic_survival_food_kcal_per_dupe must be a finite non-negative number"
        )
    for key in ("emergency_max_actions_per_turn", "emergency_cooldown_cycles", "emergency_pending_cycles"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    return config


def _state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    dupes = state.get("dupes")
    resources = state.get("resources")
    buildings = state.get("building_list")
    metrics = state_metrics(state)
    return {
        "cycle": metrics["cycle"],
        "dupe_count": len(dupes) if isinstance(dupes, list) else None,
        "building_count": len(buildings) if isinstance(buildings, list) else None,
        "oxygen_air": metrics["oxygen_g"],
        "oxygen_g": metrics["oxygen_g"],
        "food_kcal": resources.get("food_kcal") if isinstance(resources, Mapping) else None,
        "max_stress": metrics["max_stress"],
        "algae_kg": metrics["algae_kg"],
        "research_active": metrics["research_active"],
        "research_progress": metrics["research_progress"],
    }


def _rule_replay_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a compact metrics snapshot instead of copying the full game state."""
    dupes = state.get("dupes")
    resources = state.get("resources")
    environment = state.get("environment")
    research = state.get("research")
    buildings = state.get("building_list")
    active_tech = research.get("active") if isinstance(research, Mapping) else None
    techs = research.get("techs") if isinstance(research, Mapping) else None
    compact_techs = []
    if isinstance(techs, list):
        compact_techs = [
            {
                key: tech[key]
                for key in ("id", "ready", "complete", "unlocks")
                if key in tech
            }
            for tech in techs
            if isinstance(tech, Mapping)
            and (
                tech.get("ready") is True
                or (
                    isinstance(active_tech, str)
                    and tech.get("id") == active_tech
                )
            )
        ]

    oxygen = (
        environment.get("oxygen_avg_g")
        if isinstance(environment, Mapping)
        else None
    )
    if oxygen is None:
        oxygen = state_metrics(state)["oxygen_g"]
    food_kcal = resources.get("food_kcal") if isinstance(resources, Mapping) else None
    compact_dupes = []
    if isinstance(dupes, list):
        dupe_fields = ("calories_kcal", "stress", "room_type", "bed_x", "bed_y")
        compact_dupes = [
            {key: dupe[key] for key in dupe_fields if key in dupe}
            for dupe in dupes
            if isinstance(dupe, Mapping)
        ]

    snapshot: dict[str, Any] = {
        "cycle": state.get("cycle"),
        "oxygen_air": oxygen,
        "environment": {"oxygen_avg_g": oxygen},
        "resources": {"food_kcal": food_kcal},
        "dupe_count": len(dupes) if isinstance(dupes, list) else None,
        "dupes": compact_dupes,
        "building_count": len(buildings) if isinstance(buildings, list) else None,
        "research": {"active": active_tech, "techs": compact_techs},
        "alerts": [
            {"type": alert["type"]}
            for alert in state.get("alerts", [])
            if isinstance(alert, Mapping) and isinstance(alert.get("type"), str)
        ] if isinstance(state.get("alerts"), list) else [],
    }
    return snapshot


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
    parser.add_argument(
        "--report",
        action="store_true",
        help="calculate offline metrics from logs/agent.jsonl and exit",
    )
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
            if skill_name == "build_basic_survival":
                plan = skill(
                    state,
                    catalog,
                    config.get(
                        "basic_survival_food_kcal_per_dupe",
                        DEFAULT_CONFIG["basic_survival_food_kcal_per_dupe"],
                    ),
                    oxygen_min_g=config.get("oxygen_min_g"),
                )
                for warning in plan.warnings:
                    if warning == "no_powered_slot_TODO_VERIFY":
                        LOGGER.warning("Skill %s skipped: %s", skill_name, warning)
                    else:
                        LOGGER.warning("Skill %s: %s", skill_name, warning)
                return list(plan.actions)
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
        "build_basic_survival": build_basic_survival,
        "build_barracks": build_barracks,
        "build_oxygen_setup": build_oxygen_setup,
        "build_mess_area": build_mess_area,
        "build_toilet_room": build_toilet_room,
        "build_power_basic": build_power_basic,
        "build_water_setup": build_water_setup,
        "build_food_basic": build_food_basic,
        "build_recreation": build_recreation,
        "build_storage_area": build_storage_area,
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
    if args.report:
        metrics = calculate_metrics(LOG_PATH)
        write_metrics(metrics, LOG_PATH.parent / "metrics.json")
        print(json.dumps(metrics, ensure_ascii=False))
        return 0
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
    goal_cooldowns: dict[str, int] = {}
    rule_pending: dict[str, dict[str, Any]] = {}
    rule_cooldowns: dict[str, int] = {}
    emergency_pending: dict[str, dict[str, Any]] = {}
    emergency_cooldowns: dict[str, int] = {}
    scoring_tracker = ScoringTracker(config.get("scoring"))
    strategist: Strategist | None = None
    strategist_settings = config.get("strategist", {})
    if isinstance(strategist_settings, Mapping):
        try:
            strategist_provider = create_goal_provider(strategist_settings)
            strategist = Strategist(strategist_settings, strategist_provider)
        except ValueError as error:
            LOGGER.error("Strategist configuration is invalid; disabled (%s)", error)
    else:
        LOGGER.error("Strategist configuration is invalid; disabled")
    event_reader = EventJournalReader(
        get_data_dir(args.data_dir) / "oni_events.jsonl",
        start_at_end=True,
    )
    memory_path = AGENT_DIR / "memory.json"
    proposed_rules_path = AGENT_DIR / "rules_proposed.yaml"
    memory_tracker: MemoryTracker | None
    try:
        memory_document = load_memory(memory_path)
        proposed_rules = load_proposed_rules(proposed_rules_path)
        memory_config = config.get("memory")
        max_memory_entries = (
            memory_config.get("max_entries", memory_document.get("max_entries", 100))
            if isinstance(memory_config, Mapping)
            else memory_document.get("max_entries", 100)
        )
        if isinstance(max_memory_entries, bool) or not isinstance(max_memory_entries, int) or max_memory_entries <= 0:
            raise ValueError("memory.max_entries must be a positive integer")
        memory_tracker = MemoryTracker(
            memory_document,
            proposed_rules,
            config={
                "thresholds": (
                    config.get("scoring", {}).get("thresholds", {})
                    if isinstance(config.get("scoring"), Mapping)
                    else {}
                ),
                "rejection_repetitions": (
                    memory_config.get("rejection_repetitions", 2)
                    if isinstance(memory_config, Mapping)
                    else 2
                ),
            },
            max_entries=max_memory_entries,
        )
    except (OSError, ValueError) as error:
        LOGGER.exception("Incident memory is unavailable: %s", error)
        memory_tracker = None
    agent_commit = current_commit_hash(Path(__file__).resolve().parent.parent)
    previous_score_state: dict[str, Any] | None = None
    latest_score: dict[str, Any] | None = None
    active_goal: str | None = None
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
        rule_replay_input: Mapping[str, Any] | None = None
        manager_plan: list[dict[str, Any]] | None = None
        strategist_decision: dict[str, Any] | None = None
        strategy_active = False
        strategy_no_op = False
        catalog: list[dict[str, Any]] = []
        cycle: int | None = None
        score_events: list[dict[str, Any]] | None = None
        score: dict[str, Any] | None = None
        memory_incidents: list[dict[str, Any]] = []

        try:
            state = read_state(args.data_dir)
            score_events = event_reader.read_new()
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
                strategist_enabled = (
                    strategist is not None
                    and strategist.config["provider"] != "none"
                )
                if args.manager == "gemini" and not strategist_enabled:
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
                    food_kcal_per_dupe=config[
                        "basic_survival_food_kcal_per_dupe"
                    ],
                    oxygen_min_g=config["oxygen_min_g"],
                )
                rule_replay_input = {
                    "summary_only": True,
                    "state": _rule_replay_state(state),
                    "pending": _copy_pending(rule_pending),
                    "cooldowns": dict(rule_cooldowns),
                    "skill_config": {
                        key: config.get(key)
                        for key in (
                            "bed_id",
                            "door_id",
                            "tile_id",
                            "barracks_bed_count",
                            "basic_survival_food_kcal_per_dupe",
                            "oxygen_min_g",
                        )
                    },
                }
                chosen_rule = rule_decision["selected"]
                if chosen_rule is None and strategist is not None:
                    strategy_lessons: list[dict[str, Any]] = []
                    if memory_tracker is not None:
                        try:
                            strategy_lessons = memory_tracker.lessons_for_log(limit=3)
                        except (TypeError, ValueError) as error:
                            LOGGER.warning(
                                "Could not read strategist lessons (%s)",
                                type(error).__name__,
                            )
                    available_goals = [
                        {"id": goal.id, "description": goal.description}
                        for goal in planner_module.GOALS
                        if goal.id in enabled_goals
                    ]
                    rule_items = rules_document.get("rules", [])
                    strategy_rules = (
                        rule_items
                        if isinstance(rule_items, list)
                        else []
                    )
                    achievement_context: list[dict[str, Any]] = []
                    try:
                        achievement_context = achievement_strategist_context(state)
                    except (OSError, TypeError, ValueError) as error:
                        LOGGER.warning(
                            "Could not read achievement planning context (%s)",
                            type(error).__name__,
                        )
                    decision = strategist.advise(
                        cycle=cycle,
                        state=state,
                        score=latest_score,
                        lessons=strategy_lessons,
                        active_goal=active_goal,
                        available_goals=available_goals,
                        rules=strategy_rules,
                        achievement_context=achievement_context,
                    )
                    if decision is not None:
                        strategy_active = True
                        manager_plan = [dict(goal) for goal in decision.goals]
                        strategist_decision = {
                            "status": decision.status,
                            "requested": decision.requested,
                            "goals": manager_plan,
                        }
                        strategy_no_op = not decision.goals
                        if decision.goals:
                            manager_goal_ids = [goal["id"] for goal in decision.goals]
                            manager_config = {
                                **config,
                                "goal_ranks": {
                                    goal_id: rank
                                    for rank, goal_id in enumerate(manager_goal_ids)
                                },
                            }
                tied_steps: list[dict[str, Any]] = []
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
                elif strategy_no_op:
                    selected = {
                        "goal_id": "no_goal",
                        "actions": [],
                        "skipped": [{"reason": f"strategist_{strategist_decision['status']}"}],
                        "reason": "strategist_no_op",
                    }
                    selection_reason = "strategist"
                else:
                    selected = next_step(
                        state,
                        catalog,
                        {**manager_config, "goal_cooldowns": goal_cooldowns},
                        pending,
                        enabled_goals=manager_goal_ids,
                        alternatives=tied_steps,
                    )
                    if cycle is not None and any(
                        item.get("goal_id") == "bootstrap_basics"
                        and item.get("reason") not in {
                            "pending", "already_done", "cooldown"
                        }
                        for item in selected.get("skipped", [])
                        if isinstance(item, Mapping)
                    ):
                        goal_cooldowns["bootstrap_basics"] = cycle + 1
                if chosen_rule is None and tied_steps and not strategy_active:
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
                elif chosen_rule is None and strategy_active and not strategy_no_op:
                    selection_reason = "strategist"
                elif chosen_rule is None and args.manager == "gemini" and manager_plan is not None:
                    selection_reason = "gemini"
                elif chosen_rule is None:
                    selection_reason = "planner"

            actions = selected["actions"]
            if selected.get("goal_id") not in {None, "no_goal"}:
                active_goal = selected["goal_id"]
            if (
                selected.get("goal_id") == "bootstrap_basics"
                and actions
                and cycle is not None
            ):
                goal_cooldowns["bootstrap_basics"] = cycle + 1
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

        try:
            score = scoring_tracker.score(
                state,
                previous_state=previous_score_state,
                events=score_events,
                result=result,
                actions=selected.get("actions", []),
            )
            latest_score = score
            score_record = make_score_record(
                score,
                state,
                commit_hash=agent_commit,
                step=step,
            )
            write_score_record(score_record, LOG_PATH.parent / "score.jsonl")
            if state:
                previous_score_state = dict(state)
        except (OSError, TypeError, ValueError) as error:
            LOGGER.exception("Could not record score for step %d: %s", step, error)

        memory_lessons: list[dict[str, Any]] = []
        if memory_tracker is not None:
            try:
                memory_incidents = memory_tracker.observe(
                    state,
                    score=score,
                    events=score_events,
                    result=result,
                    actions=selected.get("actions", []),
                )
                if memory_incidents:
                    memory_tracker.save(memory_path, proposed_rules_path)
                memory_lessons = memory_tracker.lessons_for_log()
            except (OSError, TypeError, ValueError) as error:
                LOGGER.exception("Could not update incident memory at step %d: %s", step, error)

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
            "rule_replay_input": rule_replay_input,
            "rule_pending": _copy_pending(rule_pending),
            "rule_pending_expired": rule_pending_expired,
            "rule_cooldowns": rule_cooldowns,
            "manager": args.manager,
            "manager_plan": manager_plan,
            "manager_plan_expires_cycle": manager_plan_expires_cycle,
            "strategist": strategist_decision,
            "emergency_pending": _copy_pending(emergency_pending),
            "emergency_pending_expired": emergency_pending_expired,
            "emergency_cooldowns": emergency_cooldowns,
            "memory_lessons": memory_lessons,
            "memory_incidents": memory_incidents,
            "result": result,
        }
        _append_log(entry)
        print(json.dumps(entry, ensure_ascii=False, default=str))
        if args.max_steps == 0 or step < args.max_steps:
            time.sleep(args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
