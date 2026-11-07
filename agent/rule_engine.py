"""Validated, three-valued state rule evaluation and selection."""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .skills import basic_survival_needed


LOGGER = logging.getLogger(__name__)
DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")
MAX_ACTIONS_PER_TURN = 12
UNKNOWN = None
OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte"}
RuleExecutor = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]], Mapping[str, Any]],
    Sequence[Mapping[str, Any]],
]


class RuleValidationError(ValueError):
    """Raised when a rule document is malformed."""


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_condition(condition: Any, location: str) -> None:
    if not isinstance(condition, Mapping):
        raise RuleValidationError(f"{location} must be an object")

    operator = condition.get("op")
    if operator in OPERATORS:
        if not isinstance(condition.get("path"), str) or not condition["path"]:
            raise RuleValidationError(f"{location}.path must be a non-empty string")
        value = condition.get("value")
        if operator in {"eq", "ne"}:
            if not (
                _is_number(value)
                or isinstance(value, str)
                or value is None
            ):
                raise RuleValidationError(f"{location}.value must be a scalar")
        elif not _is_number(value):
            raise RuleValidationError(f"{location}.value must be a finite number")
        return
    if operator == "exists":
        if not isinstance(condition.get("path"), str) or not condition["path"]:
            raise RuleValidationError(f"{location}.path must be a non-empty string")
        return
    if operator == "count":
        if not isinstance(condition.get("building"), str) or not condition["building"]:
            raise RuleValidationError(f"{location}.building must be a non-empty string")
        if "state" in condition and not isinstance(condition["state"], str):
            raise RuleValidationError(f"{location}.state must be a string")
        if condition.get("comparison") not in OPERATORS:
            raise RuleValidationError(f"{location}.comparison is invalid")
        if not _is_number(condition.get("value")):
            raise RuleValidationError(f"{location}.value must be a finite number")
        return
    if operator == "stored_mass":
        if not isinstance(condition.get("building"), str) or not condition["building"]:
            raise RuleValidationError(f"{location}.building must be a non-empty string")
        if not isinstance(condition.get("element"), str) or not condition["element"]:
            raise RuleValidationError(f"{location}.element must be a non-empty string")
        if "state" in condition and not isinstance(condition["state"], str):
            raise RuleValidationError(f"{location}.state must be a string")
        if condition.get("comparison") not in OPERATORS:
            raise RuleValidationError(f"{location}.comparison is invalid")
        if not _is_number(condition.get("value")):
            raise RuleValidationError(f"{location}.value must be a finite number")
        return
    if operator == "is_null":
        if not isinstance(condition.get("path"), str) or not condition["path"]:
            raise RuleValidationError(f"{location}.path must be a non-empty string")
        return
    if operator == "basic_survival_needed":
        return
    if operator == "any_item":
        if not isinstance(condition.get("path"), str) or not condition["path"]:
            raise RuleValidationError(f"{location}.path must be a non-empty string")
        _validate_condition(condition.get("where"), f"{location}.where")
        return
    if operator == "for":
        reads = condition.get("reads")
        if isinstance(reads, bool) or not isinstance(reads, int) or reads <= 0:
            raise RuleValidationError(f"{location}.reads must be a positive integer")
        _validate_condition(condition.get("condition"), f"{location}.condition")
        if condition["condition"].get("op") == "for":
            raise RuleValidationError(f"{location} cannot nest for operators")
        return
    if operator in {"all", "any"}:
        conditions = condition.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise RuleValidationError(f"{location}.conditions must be a non-empty array")
        for index, item in enumerate(conditions):
            _validate_condition(item, f"{location}.conditions[{index}]")
        return
    if operator == "not":
        _validate_condition(condition.get("condition"), f"{location}.condition")
        return
    raise RuleValidationError(f"{location}.op is unsupported")


def validate_rules(document: Any) -> dict[str, Any]:
    """Validate and return a rule document loaded from JSON-compatible YAML."""
    if not isinstance(document, Mapping):
        raise RuleValidationError("rules document must be an object")
    phases = document.get("phases")
    if not isinstance(phases, list):
        raise RuleValidationError("phases must be an array")
    previous_end = -1
    for index, phase in enumerate(phases):
        if not isinstance(phase, Mapping):
            raise RuleValidationError(f"phases[{index}] must be an object")
        start, end = phase.get("start_cycle"), phase.get("end_cycle")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or start < previous_end
        ):
            raise RuleValidationError(f"phases[{index}] has invalid cycle bounds")
        if not isinstance(phase.get("id"), str) or not phase["id"]:
            raise RuleValidationError(f"phases[{index}].id must be a non-empty string")
        if not isinstance(phase.get("goals"), list):
            raise RuleValidationError(f"phases[{index}].goals must be an array")
        previous_end = end

    rules = document.get("rules")
    if not isinstance(rules, list):
        raise RuleValidationError("rules must be an array")
    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        location = f"rules[{index}]"
        if not isinstance(rule, Mapping):
            raise RuleValidationError(f"{location} must be an object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in rule_ids:
            raise RuleValidationError(f"{location}.id must be unique and non-empty")
        rule_ids.add(rule_id)
        priority = rule.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise RuleValidationError(f"{location}.priority must be an integer")
        _validate_condition(rule.get("when"), f"{location}.when")
        then = rule.get("then")
        if (
            not isinstance(then, Mapping)
            or not isinstance(then.get("skill"), str)
            or not then["skill"]
            or not isinstance(then.get("args", {}), Mapping)
        ):
            raise RuleValidationError(f"{location}.then must name a skill and object args")
        for key in ("cooldown_cycles", "pending"):
            value = rule.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise RuleValidationError(f"{location}.{key} must be a positive integer")
        requires = rule.get("requires", [])
        if not isinstance(requires, list) or any(
            not isinstance(item, str) or not item for item in requires
        ):
            raise RuleValidationError(f"{location}.requires must be an array of skill names")
    return dict(document)


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """Load JSON-compatible YAML using the standard-library JSON parser."""
    with Path(path).open("r", encoding="utf-8") as rule_file:
        document = json.load(rule_file)
    return validate_rules(document)


def _path_value(state: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = state
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return False, None
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if not 0 <= index < len(current):
                return False, None
            current = current[index]
            continue
        else:
            return False, None
    return True, current


def _compare(actual: Any, operator: str, expected: Any) -> bool | None:
    if operator == "eq":
        if _is_number(actual) and _is_number(expected):
            return actual == expected
        if type(actual) is not type(expected):
            return UNKNOWN
        return actual == expected if isinstance(actual, (int, float, str, bool)) or actual is None else UNKNOWN
    if operator == "ne":
        if _is_number(actual) and _is_number(expected):
            return actual != expected
        if type(actual) is not type(expected):
            return UNKNOWN
        return actual != expected if isinstance(actual, (int, float, str, bool)) or actual is None else UNKNOWN
    if not _is_number(actual) or not _is_number(expected):
        return UNKNOWN
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "gt":
        return actual > expected
    return actual >= expected


def _evaluate(
    condition: Mapping[str, Any],
    state: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]] = (),
    food_kcal_per_dupe: float = 1000.0,
    oxygen_min_g: float | None = None,
) -> bool | None:
    operator = condition["op"]
    if operator in OPERATORS:
        found, value = _path_value(state, condition["path"])
        return _compare(value, operator, condition["value"]) if found else UNKNOWN
    if operator == "exists":
        found, _ = _path_value(state, condition["path"])
        return True if found else UNKNOWN
    if operator == "count":
        buildings = state.get("building_list")
        if not isinstance(buildings, list) or any(
            not isinstance(building, Mapping) for building in buildings
        ):
            return UNKNOWN
        if any("id" not in building for building in buildings):
            return UNKNOWN
        if "state" in condition and any(
            building.get("id") == condition["building"] and "state" not in building
            for building in buildings
        ):
            return UNKNOWN
        count = sum(
            building.get("id") == condition["building"]
            and ("state" not in condition or building.get("state") == condition["state"])
            for building in buildings
        )
        return _compare(count, condition["comparison"], condition["value"])
    if operator == "stored_mass":
        buildings = state.get("building_list")
        if not isinstance(buildings, list) or any(
            not isinstance(building, Mapping) for building in buildings
        ):
            return UNKNOWN
        if any("id" not in building for building in buildings):
            return UNKNOWN
        if "state" in condition and any(
            building.get("id") == condition["building"] and "state" not in building
            for building in buildings
        ):
            return UNKNOWN
        matches = [
            building
            for building in buildings
            if building.get("id") == condition["building"]
            and ("state" not in condition or building.get("state") == condition["state"])
        ]
        if not matches:
            return False
        total_mass = 0.0
        for building in matches:
            if "stored" not in building:
                return UNKNOWN
            stored = building["stored"]
            if isinstance(stored, Mapping):
                mass = stored.get(condition["element"], 0)
            elif isinstance(stored, list):
                mass = 0.0
                for item in stored:
                    if not isinstance(item, Mapping):
                        return UNKNOWN
                    if item.get("element") == condition["element"]:
                        mass = item.get("kg")
                        break
            else:
                return UNKNOWN
            if not _is_number(mass) or mass < 0:
                return UNKNOWN
            total_mass += mass
        return _compare(total_mass, condition["comparison"], condition["value"])
    if operator == "is_null":
        found, value = _path_value(state, condition["path"])
        return value is None if found else UNKNOWN
    if operator == "basic_survival_needed":
        return basic_survival_needed(
            state, catalog, food_kcal_per_dupe, oxygen_min_g
        )
    if operator == "any_item":
        found, items = _path_value(state, condition["path"])
        if not found or not isinstance(items, list):
            return UNKNOWN
        if any(not isinstance(item, Mapping) for item in items):
            return UNKNOWN
        results = [
            _evaluate(
                condition["where"], item, (), catalog, food_kcal_per_dupe,
                oxygen_min_g,
            )
            for item in items
        ]
        if any(result is True for result in results):
            return True
        return False if all(result is False for result in results) else UNKNOWN
    if operator == "for":
        reads = condition["reads"]
        if len(history) < reads:
            return UNKNOWN
        results = [
            _evaluate(
                condition["condition"], sample, (), catalog, food_kcal_per_dupe,
                oxygen_min_g,
            )
            for sample in history[-reads:]
        ]
        if any(result is False for result in results):
            return False
        return True if all(result is True for result in results) else UNKNOWN
    if operator == "all":
        results = [
            _evaluate(
                item, state, history, catalog, food_kcal_per_dupe, oxygen_min_g
            )
            for item in condition["conditions"]
        ]
        if any(result is False for result in results):
            return False
        return True if all(result is True for result in results) else UNKNOWN
    if operator == "any":
        results = [
            _evaluate(
                item, state, history, catalog, food_kcal_per_dupe, oxygen_min_g
            )
            for item in condition["conditions"]
        ]
        if any(result is True for result in results):
            return True
        return False if all(result is False for result in results) else UNKNOWN
    result = _evaluate(
        condition["condition"], state, history, catalog, food_kcal_per_dupe,
        oxygen_min_g,
    )
    return not result if result is not None else UNKNOWN


def phase_for_cycle(document: Mapping[str, Any], cycle: int | None) -> str | None:
    """Return the configured phase for a known cycle."""
    if cycle is None:
        return None
    for phase in document["phases"]:
        if phase["start_cycle"] <= cycle < phase["end_cycle"]:
            return phase["id"]
    return None


def explain_rules(
    state: Mapping[str, Any],
    *,
    catalog: Sequence[Mapping[str, Any]] = (),
    document: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, Any]] = (),
    pending: Mapping[str, Any] | None = None,
    cooldowns: Mapping[str, int] | None = None,
    executors: Mapping[str, RuleExecutor] | None = None,
    food_kcal_per_dupe: float = 1000.0,
    oxygen_min_g: float | None = None,
) -> dict[str, Any]:
    """Return per-rule decision reasons without executing skill plans."""
    rules_document = validate_rules(document) if document is not None else load_rules()
    current_cycle = state.get("cycle")
    if isinstance(current_cycle, bool) or not isinstance(current_cycle, int):
        current_cycle = None
    explanations: list[dict[str, Any]] = []
    ordered = sorted(
        enumerate(rules_document["rules"]),
        key=lambda item: (-item[1]["priority"], item[0]),
    )
    for _, rule in ordered:
        condition = _evaluate(
            rule["when"], state, history, catalog, food_kcal_per_dupe,
            oxygen_min_g,
        )
        if condition is None:
            status, reason = "unknown", "condition_unknown"
        elif not condition:
            status, reason = "not_matched", "condition_false"
        elif pending and rule["id"] in pending:
            status, reason = "skipped", "pending"
        elif rule["id"] in (cooldowns or {}):
            previous_cycle = (cooldowns or {})[rule["id"]]
            if current_cycle is None:
                status, reason = "skipped", "cycle_unknown"
            elif current_cycle - previous_cycle < rule["cooldown_cycles"]:
                status, reason = "skipped", "cooldown"
            else:
                status, reason = "matched", "condition_true"
        else:
            status, reason = "matched", "condition_true"
        explanations.append(
            {
                "rule_id": rule["id"],
                "priority": rule["priority"],
                "status": status,
                "reason": reason,
            }
        )
        LOGGER.info("Rule %s: %s (%s)", rule["id"], status, reason)

    selected_reason = next(
        (item for item in explanations if item["status"] == "matched"), None
    )
    if selected_reason is None:
        return {
            "phase": phase_for_cycle(rules_document, current_cycle),
            "selected": None,
            "reasons": explanations,
        }

    selected_rule = next(
        rule for rule in rules_document["rules"]
        if rule["id"] == selected_reason["rule_id"]
    )
    skill = selected_rule["then"]["skill"]
    executor_map = executors or {}
    required = selected_rule.get("requires", [])
    missing_skills = [
        name for name in [skill, *required] if name not in executor_map
    ]
    if executors is None:
        selected = {
            "rule_id": selected_rule["id"],
            "priority": selected_rule["priority"],
            "status": "matched",
            "reason": "skill_preview_not_requested",
            "then": dict(selected_rule["then"]),
            "actions": [],
        }
    elif missing_skills:
        selected = {
            "rule_id": selected_rule["id"],
            "priority": selected_rule["priority"],
            "status": "TODO_NOT_IMPLEMENTED",
            "reason": "TODO_NOT_IMPLEMENTED",
            "missing_skills": sorted(set(missing_skills)),
            "then": dict(selected_rule["then"]),
            "actions": [],
        }
    else:
        actions = list(
            executor_map[skill](
                state,
                catalog,
                selected_rule["then"].get("args", {}),
            )
        )
        selected = {
            "rule_id": selected_rule["id"],
            "priority": selected_rule["priority"],
            "status": "matched",
            "reason": "condition_true",
            "then": dict(selected_rule["then"]),
            "actions": actions[:MAX_ACTIONS_PER_TURN],
            "truncated": len(actions) > MAX_ACTIONS_PER_TURN,
        }
        if selected["truncated"]:
            selected["reason"] = "action_limit_12"
    return {
        "phase": phase_for_cycle(rules_document, current_cycle),
        "selected": selected,
        "reasons": explanations,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and explain ONI rules")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="validate rules.yaml")
    mode.add_argument("--explain", action="store_true", help="explain rules for a state JSON file")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args(argv)
    try:
        document = load_rules(args.rules)
        if args.validate:
            print(json.dumps({"valid": True, "rules": len(document["rules"])}))
            return 0
        if args.state is None:
            parser.error("--explain requires --state")
        with args.state.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
        if not isinstance(state, Mapping):
            raise ValueError("state JSON must be an object")
        print(json.dumps(explain_rules(state, document=document), ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, RuleValidationError, ValueError) as error:
        parser.exit(2, f"rule_engine: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
