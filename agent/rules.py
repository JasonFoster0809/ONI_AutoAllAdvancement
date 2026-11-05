"""Deterministic emergency rules for the ONI state snapshot."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


OXYGEN_MIN_G = 50.0
HUNGRY_KCAL = 100.0
HIGH_STRESS = 90.0
TEMPERATURE_MIN_K = 273.15
TEMPERATURE_MAX_K = 318.15


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def oxygen_value(state: Mapping[str, Any]) -> float | None:
    """Return telepad-area oxygen first, falling back to the first dupe sample."""
    environment = state.get("environment")
    oxygen = (
        _number(environment.get("oxygen_avg_g"))
        if isinstance(environment, Mapping)
        else None
    )
    if oxygen is None:
        oxygen = _number(state.get("oxygen_air"))
    return oxygen


def oxygen_rule(
    state: Mapping[str, Any], minimum_g: float = OXYGEN_MIN_G
) -> str | None:
    """Flag oxygen below the agent's configured policy threshold."""
    oxygen = oxygen_value(state)
    if oxygen is not None and oxygen < minimum_g:
        return "low_oxygen"
    return None


def hunger_rule(
    state: Mapping[str, Any], food_kcal_per_dupe: float = 1000.0
) -> str | None:
    """Flag a hungry dupe or food stock below one estimated cycle's demand."""
    dupes = state.get("dupes")
    if isinstance(dupes, list):
        for dupe in dupes:
            if not isinstance(dupe, Mapping):
                continue
            calories = _number(dupe.get("calories_kcal"))
            if calories is not None and calories < HUNGRY_KCAL:
                return "dupe_hungry"
    if _has_alert(state, "dupe_no_calories"):
        return "dupe_hungry"
    resources = state.get("resources")
    food_kcal = (
        _number(resources.get("food_kcal"))
        if isinstance(resources, Mapping)
        else None
    )
    if (
        isinstance(dupes, list)
        and dupes
        and food_kcal is not None
        and food_kcal < len(dupes) * food_kcal_per_dupe
    ):
        return "food_stock_low"
    return None


def stress_rule(state: Mapping[str, Any]) -> str | None:
    """Flag high duplicant stress using the mod's 90-point alert threshold."""
    dupes = state.get("dupes")
    if isinstance(dupes, list):
        for dupe in dupes:
            if not isinstance(dupe, Mapping):
                continue
            stress = _number(dupe.get("stress"))
            if stress is not None and stress >= HIGH_STRESS:
                return "dupe_high_stress"
    if _has_alert(state, "dupe_high_stress"):
        return "dupe_high_stress"
    return None


def temperature_rule(state: Mapping[str, Any]) -> str | None:
    """Flag telepad-area averages outside the conservative 0-45 C band."""
    environment = state.get("environment")
    if not isinstance(environment, Mapping):
        return None
    temperature = _number(environment.get("temperature_avg_k"))
    if temperature is None:
        return None
    if temperature < TEMPERATURE_MIN_K:
        return "temperature_low"
    if temperature > TEMPERATURE_MAX_K:
        return "temperature_high"
    return None


def alert_rule(state: Mapping[str, Any]) -> str | None:
    """Flag any alert not already represented by a more specific rule."""
    alerts = state.get("alerts")
    if not isinstance(alerts, list):
        return None
    for alert in alerts:
        if isinstance(alert, Mapping):
            alert_type = alert.get("type")
            if isinstance(alert_type, str) and alert_type:
                return f"alert:{alert_type}"
    return None


def _has_alert(state: Mapping[str, Any], alert_type: str) -> bool:
    alerts = state.get("alerts")
    return isinstance(alerts, list) and any(
        isinstance(alert, Mapping) and alert.get("type") == alert_type
        for alert in alerts
    )


def choose_emergency_action(
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    oxygen_history: Sequence[bool] | None = None,
    oxygen_min_g: float = OXYGEN_MIN_G,
    oxygen_consecutive_readings: int = 1,
    food_kcal_per_dupe: float = 1000.0,
) -> dict[str, Any] | None:
    """Apply the highest-priority rule before any LLM choice."""
    emergency = detect_emergency(
        state,
        oxygen_history=oxygen_history,
        oxygen_min_g=oxygen_min_g,
        oxygen_consecutive_readings=oxygen_consecutive_readings,
        food_kcal_per_dupe=food_kcal_per_dupe,
    )
    if emergency is None:
        return None
    reason = emergency["reason"]
    category = emergency["category"]
    if category is not None:
        match = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("category") == category
                and isinstance(candidate.get("id"), str)
                and isinstance(candidate.get("actions"), list)
            ),
            None,
        )
        if match is not None:
            return {**match, "reason": reason}
    return {"id": "no_op", "category": "no_op", "actions": [], "reason": reason}


def detect_emergency(
    state: Mapping[str, Any],
    *,
    oxygen_history: Sequence[bool] | None = None,
    oxygen_min_g: float = OXYGEN_MIN_G,
    oxygen_consecutive_readings: int = 1,
    food_kcal_per_dupe: float = 1000.0,
) -> dict[str, str | None] | None:
    """Return the highest-priority detected emergency, independent of actions."""
    ordered_rules = (
        (
            lambda current_state: oxygen_rule(current_state, oxygen_min_g)
            if oxygen_history is None
            or (
                oxygen_consecutive_readings > 0
                and len(oxygen_history) >= oxygen_consecutive_readings
                and all(oxygen_history[-oxygen_consecutive_readings:])
            )
            else None,
            "oxygen",
        ),
        (lambda current_state: hunger_rule(current_state, food_kcal_per_dupe), "food"),
        (stress_rule, "stress"),
        (temperature_rule, "temperature"),
        (alert_rule, None),
    )
    for rule, category in ordered_rules:
        reason = rule(state)
        if reason is None:
            continue
        return {"category": category, "reason": reason}
    return None
