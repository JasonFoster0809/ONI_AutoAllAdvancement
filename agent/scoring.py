"""Offline colony scoring for comparing agent runs; never used to choose actions."""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)

DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    "weights": {
        "cycle_survived": 1.0,
        "achievement_new": 100.0,
        "morale": 0.1,
        "food_stability": 5.0,
        "oxygen_stability": 5.0,
        "qualified_rooms": 1.0,
        "dupe_death": -100.0,
        "stress_persistent": -10.0,
        "hunger_persistent": -10.0,
        "low_oxygen_persistent": -15.0,
        "repeated_rejection": -2.0,
        "material_waste": -1.0,
    },
    "thresholds": {
        "oxygen_min_g": 50.0,
        "food_kcal_per_dupe": 1000.0,
        "dupe_calories_min_kcal": 100.0,
        "stress_max": 90.0,
        "persistence_reads": 3,
    },
    "threshold_notes": {
        "oxygen_min_g": "TODO_VERIFY; existing agent policy threshold, not a game danger limit",
        "food_kcal_per_dupe": "TODO_VERIFY; existing agent planning heuristic, not verified consumption",
        "dupe_calories_min_kcal": "TODO_VERIFY; existing agent emergency heuristic",
        "stress_max": "TODO_VERIFY; existing mod alert policy threshold",
        "persistence_reads": "TODO_VERIFY; scoring policy, not an ONI mechanic",
    },
    "optional_telemetry_notes": {
        "morale": "TODO_VERIFY; numeric morale is not currently emitted in oni_state.json",
        "material_waste_kg": "TODO_VERIFY; material waste is not currently emitted in oni_state.json",
    },
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _completed_achievements(state: Mapping[str, Any]) -> set[str] | None:
    achievements = state.get("achievements")
    if not isinstance(achievements, list):
        return None
    completed: set[str] = set()
    for item in achievements:
        if not isinstance(item, Mapping):
            return None
        achievement_id = item.get("id")
        achieved = item.get("achieved")
        if not isinstance(achievement_id, str) or not achievement_id or not isinstance(achieved, bool):
            return None
        if achieved:
            completed.add(achievement_id)
    return completed


def _oxygen_g(state: Mapping[str, Any]) -> float | None:
    environment = state.get("environment")
    oxygen = _number(environment.get("oxygen_avg_g")) if isinstance(environment, Mapping) else None
    return oxygen if oxygen is not None else _number(state.get("oxygen_air"))


def _component(
    name: str,
    raw: float | int | None,
    weights: Mapping[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    weight = _number(weights.get(name))
    raw_number = _number(raw)
    if raw_number is None or weight is None:
        return {
            "status": "unknown",
            "raw": None,
            "weight": weight,
            "points": None,
            "reason": reason or "data_unavailable",
        }
    points = raw_number * weight
    if not math.isfinite(points):
        return {
            "status": "unknown",
            "raw": None,
            "weight": weight,
            "points": None,
            "reason": "score_out_of_range",
        }
    return {
        "status": "known",
        "raw": raw,
        "weight": weight,
        "points": round(points, 3),
    }


class ScoringTracker:
    """Track consecutive policy conditions and repeated rejected actions."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        supplied = config if isinstance(config, Mapping) else {}
        self.weights = {
            **DEFAULT_SCORING_CONFIG["weights"],
            **(supplied.get("weights", {}) if isinstance(supplied.get("weights"), Mapping) else {}),
        }
        self.thresholds = {
            **DEFAULT_SCORING_CONFIG["thresholds"],
            **(supplied.get("thresholds", {}) if isinstance(supplied.get("thresholds"), Mapping) else {}),
        }
        self._consecutive = {
            "stress_persistent": 0,
            "hunger_persistent": 0,
            "low_oxygen_persistent": 0,
        }
        self._rejected_signatures: dict[str, int] = {}

    def score(
        self,
        state: Mapping[str, Any],
        *,
        previous_state: Mapping[str, Any] | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
        result: Mapping[str, Any] | None = None,
        actions: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return weighted score components, preserving unavailable data as unknown."""
        components: dict[str, dict[str, Any]] = {}
        cycle = _count(state.get("cycle"))
        previous_cycle = _count(previous_state.get("cycle")) if previous_state is not None else None
        cycle_delta = None
        cycle_reason = "previous_cycle_unavailable"
        if cycle is not None and previous_cycle is not None:
            if cycle >= previous_cycle:
                cycle_delta = cycle - previous_cycle
            else:
                cycle_reason = "cycle_rewound_or_new_save"
        components["cycle_survived"] = _component(
            "cycle_survived",
            cycle_delta,
            self.weights,
            reason=cycle_reason,
        )

        current_achievements = _completed_achievements(state)
        previous_achievements = (
            _completed_achievements(previous_state)
            if previous_state is not None
            else None
        )
        new_achievements = (
            len(current_achievements - previous_achievements)
            if current_achievements is not None and previous_achievements is not None
            else None
        )
        components["achievement_new"] = _component(
            "achievement_new",
            new_achievements,
            self.weights,
            reason="achievement_baseline_unavailable",
        )

        morale = _number(state.get("morale"))
        components["morale"] = _component(
            "morale",
            morale,
            self.weights,
            reason="morale_not_in_state",
        )

        resources = state.get("resources")
        food_kcal = _number(resources.get("food_kcal")) if isinstance(resources, Mapping) else None
        dupes = state.get("dupes")
        food_threshold = _number(self.thresholds.get("food_kcal_per_dupe"))
        if food_kcal is None or not isinstance(dupes, list) or food_threshold is None:
            food_stability = None
        else:
            food_stability = 1 if food_kcal >= len(dupes) * food_threshold else -1
        components["food_stability"] = _component(
            "food_stability",
            food_stability,
            self.weights,
            reason="food_or_dupe_data_unavailable",
        )

        oxygen = _oxygen_g(state)
        oxygen_threshold = _number(self.thresholds.get("oxygen_min_g"))
        oxygen_stability = (
            (1 if oxygen >= oxygen_threshold else -1)
            if oxygen is not None and oxygen_threshold is not None
            else None
        )
        components["oxygen_stability"] = _component(
            "oxygen_stability",
            oxygen_stability,
            self.weights,
            reason="oxygen_data_unavailable",
        )

        rooms = state.get("rooms")
        qualified_rooms: int | None = None
        if isinstance(rooms, list):
            room_types = [room.get("type") for room in rooms if isinstance(room, Mapping)]
            if len(room_types) == len(rooms) and all(isinstance(item, str) for item in room_types):
                qualified_rooms = sum(item.casefold() != "neutral" for item in room_types)
        components["qualified_rooms"] = _component(
            "qualified_rooms",
            qualified_rooms,
            self.weights,
            reason="room_data_unavailable",
        )

        deaths = (
            sum(event.get("type") == "dupe_died" for event in events)
            if events is not None and all(isinstance(event, Mapping) for event in events)
            else None
        )
        components["dupe_death"] = _component(
            "dupe_death",
            deaths,
            self.weights,
            reason="event_data_unavailable",
        )

        stress_limit = _number(self.thresholds.get("stress_max"))
        stress_values = (
            [_number(dupe.get("stress")) for dupe in dupes if isinstance(dupe, Mapping)]
            if isinstance(dupes, list)
            else []
        )
        stress_known = (
            len(stress_values) == len(dupes)
            and all(value is not None for value in stress_values)
            and stress_limit is not None
        ) if isinstance(dupes, list) else False
        stress_high = any(value >= stress_limit for value in stress_values if value is not None) if stress_known else None
        self._consecutive["stress_persistent"] = (
            self._consecutive["stress_persistent"] + 1 if stress_high else 0
        ) if stress_high is not None else 0
        hunger_limit = _number(self.thresholds.get("dupe_calories_min_kcal"))
        calories = (
            [_number(dupe.get("calories_kcal")) for dupe in dupes if isinstance(dupe, Mapping)]
            if isinstance(dupes, list)
            else []
        )
        hunger_known = (
            len(calories) == len(dupes)
            and all(value is not None for value in calories)
            and hunger_limit is not None
        ) if isinstance(dupes, list) else False
        hungry = any(value < hunger_limit for value in calories if value is not None) if hunger_known else None
        self._consecutive["hunger_persistent"] = (
            self._consecutive["hunger_persistent"] + 1 if hungry else 0
        ) if hungry is not None else 0
        low_oxygen = oxygen < oxygen_threshold if oxygen is not None and oxygen_threshold is not None else None
        self._consecutive["low_oxygen_persistent"] = (
            self._consecutive["low_oxygen_persistent"] + 1 if low_oxygen else 0
        ) if low_oxygen is not None else 0

        reads = _count(self.thresholds.get("persistence_reads"))
        if reads is not None and reads <= 0:
            reads = None
        for name, condition in (
            ("stress_persistent", stress_high),
            ("hunger_persistent", hungry),
            ("low_oxygen_persistent", low_oxygen),
        ):
            raw = (
                1
                if condition is not None
                and reads is not None
                and self._consecutive[name] >= reads
                else 0
                if condition is not None and reads is not None
                else None
            )
            components[name] = _component(
                name,
                raw,
                self.weights,
                reason="condition_data_unavailable",
            )

        components["repeated_rejection"] = _component(
            "repeated_rejection",
            self._repeated_rejections(result, actions),
            self.weights,
            reason="command_result_unavailable",
        )
        material_waste = _number(state.get("material_waste_kg"))
        components["material_waste"] = _component(
            "material_waste",
            material_waste if material_waste is not None and material_waste >= 0 else None,
            self.weights,
            reason="material_waste_telemetry_unavailable",
        )

        known_points = [
            item["points"]
            for item in components.values()
            if item["status"] == "known"
        ]
        total = sum(known_points)
        return {
            "cycle": cycle,
            "total": round(total, 3) if math.isfinite(total) else None,
            "known_components": len(known_points),
            "unknown_components": len(components) - len(known_points),
            "components": components,
        }

    def _repeated_rejections(
        self,
        result: Mapping[str, Any] | None,
        actions: Sequence[Mapping[str, Any]] | None,
    ) -> int | None:
        results = result.get("results") if isinstance(result, Mapping) else None
        if not isinstance(results, list):
            return None
        repeated = 0
        for index, item in enumerate(results):
            if not isinstance(item, Mapping) or item.get("ok") is not False:
                continue
            action = (
                actions[index]
                if actions is not None
                and index < len(actions)
                and isinstance(actions[index], Mapping)
                else None
            )
            signature = json.dumps(
                {"action": action, "result": item},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            self._rejected_signatures[signature] = self._rejected_signatures.get(signature, 0) + 1
            if self._rejected_signatures[signature] > 1:
                repeated += 1
            if len(self._rejected_signatures) > 512:
                self._rejected_signatures.pop(next(iter(self._rejected_signatures)))
        return repeated


class EventJournalReader:
    """Read newly appended complete JSONL events, tolerating log rotation."""

    def __init__(self, path: str | Path, *, start_at_end: bool = False) -> None:
        self.path = Path(path)
        try:
            self.offset = self.path.stat().st_size if start_at_end else 0
        except FileNotFoundError:
            self.offset = 0
        except OSError:
            LOGGER.exception("Could not initialize event journal reader for %s", self.path)
            self.offset = 0

    def read_new(self) -> list[dict[str, Any]] | None:
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset = 0
            with self.path.open("rb") as event_file:
                event_file.seek(self.offset)
                data = event_file.read()
        except FileNotFoundError:
            return None
        except OSError:
            LOGGER.exception("Could not read event journal %s", self.path)
            return None

        last_newline = data.rfind(b"\n")
        if last_newline < 0:
            return []
        complete_data = data[: last_newline + 1]
        self.offset += len(complete_data)
        events: list[dict[str, Any]] = []
        for line in complete_data.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                LOGGER.warning("Skipping malformed event journal line in %s", self.path)
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


def current_commit_hash(repository: str | Path) -> str:
    """Return the checked-out agent commit, or an explicit unknown marker."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        LOGGER.exception("Could not determine agent commit hash")
        return "unknown"
    value = completed.stdout.strip()
    return value if value else "unknown"


def write_score_record(record: Mapping[str, Any], path: str | Path) -> None:
    """Append one self-contained JSON score record."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8", newline="\n") as score_file:
        score_file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def make_score_record(
    score: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    commit_hash: str,
    step: int,
) -> dict[str, Any]:
    """Attach reproducibility metadata without assuming it exists in game state."""
    save_name = state.get("save_name")
    if not isinstance(save_name, str) or not save_name:
        save_name = os.environ.get("ONI_SAVE_NAME")
    seed = state.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, (str, int)):
        seed = os.environ.get("ONI_SEED")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "cycle": score.get("cycle"),
        "agent_commit": commit_hash,
        "save_name": save_name,
        "seed": seed,
        "total": score.get("total"),
        "known_components": score.get("known_components"),
        "unknown_components": score.get("unknown_components"),
        "components": score.get("components"),
    }
