"""Persistent incident lessons and human-review-only rule proposals."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
MEMORY_PATH = Path(__file__).with_name("memory.json")
PROPOSED_RULES_PATH = Path(__file__).with_name("rules_proposed.yaml")
DEFAULT_MAX_ENTRIES = 100
DEFAULT_REJECTION_REPETITIONS = 2
PROPOSAL_VERSION = 1
INCIDENT_PROPOSALS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "dupe_death": (
        {"source": "event", "type": "dupe_died"},
        {"type": "manual_review", "suggestion": "review_colony_survival_plan"},
    ),
    "stress_persistent": (
        {"source": "state", "path": "dupes.*.stress", "operator": "gte"},
        {"type": "skill_review", "skill": "build_toilet_room", "args": {}},
    ),
    "hunger_persistent": (
        {"source": "state", "path": "dupes.*.calories_kcal", "operator": "lt"},
        {"type": "skill_review", "skill": "food_emergency", "args": {}},
    ),
    "low_oxygen_persistent": (
        {"source": "state", "path": "environment.oxygen_avg_g", "operator": "lt"},
        {"type": "skill_review", "skill": "build_oxygen_setup", "args": {}},
    ),
    "repeated_rejection": (
        {"source": "command_result", "condition": "same_action_rejected_repeatedly"},
        {"type": "manual_review", "suggestion": "review_action_preconditions"},
    ),
}


class MemoryValidationError(ValueError):
    """Raised when persisted lessons or proposed rules have an invalid shape."""


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def validate_memory(document: Any) -> dict[str, Any]:
    if (
        not isinstance(document, Mapping)
        or isinstance(document.get("version"), bool)
        or document.get("version") != 1
    ):
        raise MemoryValidationError("memory must be an object with version 1")
    lessons = document.get("lessons")
    if not isinstance(lessons, list):
        raise MemoryValidationError("memory.lessons must be an array")
    if "max_entries" in document and not _positive_int(document["max_entries"]):
        raise MemoryValidationError("memory.max_entries must be a positive integer")
    ids: set[str] = set()
    for index, lesson in enumerate(lessons):
        where = f"memory.lessons[{index}]"
        if not isinstance(lesson, Mapping):
            raise MemoryValidationError(f"{where} must be an object")
        lesson_id = lesson.get("id")
        if not isinstance(lesson_id, str) or not lesson_id or lesson_id in ids:
            raise MemoryValidationError(f"{where}.id must be unique and non-empty")
        ids.add(lesson_id)
        if lesson.get("cycle") is not None and not _nonnegative_int(lesson.get("cycle")):
            raise MemoryValidationError(f"{where}.cycle must be a non-negative integer")
        if not isinstance(lesson.get("incident_type"), str) or not lesson["incident_type"]:
            raise MemoryValidationError(f"{where}.incident_type must be non-empty")
        if not isinstance(lesson.get("evidence"), Mapping):
            raise MemoryValidationError(f"{where}.evidence must be an object")
        hypothesis = lesson.get("cause_hypothesis")
        if not isinstance(hypothesis, str) or "giả thuyết" not in hypothesis.casefold():
            raise MemoryValidationError(f"{where}.cause_hypothesis must be explicitly marked as a hypothesis")
        if not isinstance(lesson.get("proposed_rule"), Mapping):
            raise MemoryValidationError(f"{where}.proposed_rule must be an object")
        if not _positive_int(lesson.get("occurrences")):
            raise MemoryValidationError(f"{where}.occurrences must be a positive integer")
    return dict(document)


def validate_proposed_rules(document: Any) -> dict[str, Any]:
    """Validate the JSON-compatible YAML proposal format, never active rules."""
    if (
        not isinstance(document, Mapping)
        or isinstance(document.get("version"), bool)
        or document.get("version") != PROPOSAL_VERSION
    ):
        raise MemoryValidationError("proposed rules must be an object with version 1")
    proposals = document.get("proposals")
    if not isinstance(proposals, list):
        raise MemoryValidationError("proposals must be an array")
    ids: set[str] = set()
    for index, proposal in enumerate(proposals):
        where = f"proposals[{index}]"
        if not isinstance(proposal, Mapping):
            raise MemoryValidationError(f"{where} must be an object")
        proposal_id = proposal.get("id")
        if not isinstance(proposal_id, str) or not proposal_id or proposal_id in ids:
            raise MemoryValidationError(f"{where}.id must be unique and non-empty")
        ids.add(proposal_id)
        if not isinstance(proposal.get("incident_type"), str) or not proposal["incident_type"]:
            raise MemoryValidationError(f"{where}.incident_type must be non-empty")
        condition = proposal.get("condition")
        if not isinstance(condition, Mapping) or not isinstance(condition.get("source"), str):
            raise MemoryValidationError(f"{where}.condition must identify a source")
        if condition["source"] not in {"state", "event", "command_result"}:
            raise MemoryValidationError(f"{where}.condition.source is unsupported")
        if not isinstance(proposal.get("priority"), int) or isinstance(proposal.get("priority"), bool):
            raise MemoryValidationError(f"{where}.priority must be an integer")
        if (
            proposal.get("last_observed_cycle") is not None
            and not _nonnegative_int(proposal.get("last_observed_cycle"))
        ):
            raise MemoryValidationError(f"{where}.last_observed_cycle must be non-negative")
        if condition["source"] == "state":
            if (
                not isinstance(condition.get("path"), str)
                or not condition["path"]
                or condition.get("operator") not in {"lt", "lte", "gt", "gte", "eq", "ne"}
                or _number(condition.get("value")) is None
            ):
                raise MemoryValidationError(f"{where}.condition has invalid state predicate")
            if "for_reads" in condition and not _positive_int(condition["for_reads"]):
                raise MemoryValidationError(f"{where}.condition.for_reads must be positive")
        elif condition["source"] == "event":
            if not isinstance(condition.get("type"), str) or not condition["type"]:
                raise MemoryValidationError(f"{where}.condition.type must be non-empty")
        elif condition["source"] == "command_result":
            if (
                not isinstance(condition.get("condition"), str)
                or not condition["condition"]
                or not _positive_int(condition.get("minimum_occurrences"))
            ):
                raise MemoryValidationError(f"{where}.condition has invalid command-result predicate")
        action = proposal.get("action")
        if not isinstance(action, Mapping) or action.get("type") not in {"manual_review", "skill_review"}:
            raise MemoryValidationError(f"{where}.action must be manual_review or skill_review")
        if action.get("type") == "skill_review" and (
            not isinstance(action.get("skill"), str)
            or not action.get("skill")
            or not isinstance(action.get("args"), Mapping)
        ):
            raise MemoryValidationError(f"{where}.action skill_review needs skill and args")
        if action.get("type") == "manual_review" and (
            not isinstance(action.get("suggestion"), str) or not action.get("suggestion")
        ):
            raise MemoryValidationError(f"{where}.action manual_review needs a suggestion")
        if not isinstance(proposal.get("cause_hypothesis"), str) or "giả thuyết" not in proposal["cause_hypothesis"].casefold():
            raise MemoryValidationError(f"{where}.cause_hypothesis must be explicitly marked as a hypothesis")
        if proposal.get("review_required") is not True:
            raise MemoryValidationError(f"{where}.review_required must be true")
    return dict(document)


def _empty_memory(max_entries: int = DEFAULT_MAX_ENTRIES) -> dict[str, Any]:
    return {"version": 1, "max_entries": max_entries, "lessons": []}


def _read_document(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            value = json.load(source)
    except FileNotFoundError:
        return default
    if not isinstance(value, Mapping):
        raise MemoryValidationError(f"{path.name} must contain a JSON object")
    return dict(value)


def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = output.name
            json.dump(document, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                LOGGER.exception("Could not remove temporary memory file %s", temporary_path)
        raise


def load_memory(path: str | Path = MEMORY_PATH) -> dict[str, Any]:
    document = _read_document(Path(path), _empty_memory())
    return validate_memory(document)


def load_proposed_rules(path: str | Path = PROPOSED_RULES_PATH) -> dict[str, Any]:
    document = _read_document(Path(path), {"version": PROPOSAL_VERSION, "proposals": []})
    return validate_proposed_rules(document)


def _cycle(state: Mapping[str, Any]) -> int | None:
    value = state.get("cycle")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _evidence_for(
    incident_type: str,
    state: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any] | None,
    actions: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if incident_type == "dupe_death":
        return {
            "events": [
                dict(event)
                for event in events
                if event.get("type") == "dupe_died"
            ][:5]
        }
    dupes = state.get("dupes")
    if incident_type in {"stress_persistent", "hunger_persistent"}:
        field = "stress" if incident_type == "stress_persistent" else "calories_kcal"
        return {
            "dupes": [
                {"name": dupe.get("name"), field: dupe.get(field)}
                for dupe in dupes
                if isinstance(dupe, Mapping) and field in dupe
            ][:10] if isinstance(dupes, list) else []
        }
    if incident_type == "low_oxygen_persistent":
        environment = state.get("environment")
        evidence = {
            "oxygen_air": state.get("oxygen_air"),
        }
        if isinstance(environment, Mapping) and "oxygen_avg_g" in environment:
            evidence["environment.oxygen_avg_g"] = environment["oxygen_avg_g"]
        return evidence
    results = result.get("results") if isinstance(result, Mapping) else []
    rejected: list[dict[str, Any]] = []
    for index, item in enumerate(results if isinstance(results, list) else []):
        if not isinstance(item, Mapping) or item.get("ok") is not False:
            continue
        action = actions[index] if actions and index < len(actions) else None
        rejected.append({"action": dict(action) if isinstance(action, Mapping) else None, "result": dict(item)})
    return {"rejected_actions": rejected[:10]}


def _incident_subject(incident_type: str, evidence: Mapping[str, Any]) -> str:
    if incident_type == "dupe_death":
        events = evidence.get("events")
        if isinstance(events, list):
            names = sorted(
                str(data["dupe"])
                for event in events
                if isinstance(event, Mapping)
                and isinstance((data := event.get("data")), Mapping)
                and isinstance(data.get("dupe"), str)
                and data["dupe"]
            )
            if names:
                return ",".join(names)
    if incident_type in {"stress_persistent", "hunger_persistent"}:
        dupes = evidence.get("dupes")
        if isinstance(dupes, list):
            subjects = sorted(
                str(item.get("name"))
                for item in dupes
                if isinstance(item, Mapping) and item.get("name")
            )
            if subjects:
                return ",".join(subjects)
    if incident_type == "repeated_rejection":
        rejected = evidence.get("rejected_actions")
        if isinstance(rejected, list) and rejected:
            return json.dumps(rejected[0].get("action"), sort_keys=True, ensure_ascii=False)
    return incident_type


def _proposal_for(
    incident_type: str,
    cycle: int | None,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    condition_template, action = INCIDENT_PROPOSALS[incident_type]
    condition = dict(condition_template)
    thresholds = config.get("thresholds")
    thresholds = thresholds if isinstance(thresholds, Mapping) else {}
    if incident_type == "stress_persistent":
        condition.update({"value": _number(thresholds.get("stress_max")), "for_reads": thresholds.get("persistence_reads")})
    elif incident_type == "hunger_persistent":
        condition.update({"value": _number(thresholds.get("dupe_calories_min_kcal")), "for_reads": thresholds.get("persistence_reads")})
    elif incident_type == "low_oxygen_persistent":
        condition.update({"value": _number(thresholds.get("oxygen_min_g")), "for_reads": thresholds.get("persistence_reads")})
    elif incident_type == "repeated_rejection":
        condition["minimum_occurrences"] = config.get(
            "rejection_repetitions", DEFAULT_REJECTION_REPETITIONS
        )
    return {
        "id": f"incident-{incident_type}",
        "incident_type": incident_type,
        "priority": 0,
        "last_observed_cycle": cycle,
        "condition": condition,
        "action": dict(action),
        "cause_hypothesis": (
            f"Giả thuyết cần con người xác minh sau sự cố {incident_type} "
            f"ở cycle {cycle if cycle is not None else 'unknown'}."
        ),
        "review_required": True,
    }


class MemoryTracker:
    """Consolidate repeated incidents into bounded, reviewable lessons."""

    def __init__(
        self,
        memory: Mapping[str, Any],
        proposed_rules: Mapping[str, Any],
        *,
        config: Mapping[str, Any] | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.memory = validate_memory(memory)
        self.proposed_rules = validate_proposed_rules(proposed_rules)
        self.config = config if isinstance(config, Mapping) else {}
        self.max_entries = max(1, max_entries)
        self._reject_counts: dict[str, int] = {}

    def observe(
        self,
        state: Mapping[str, Any],
        *,
        score: Mapping[str, Any] | None,
        events: Sequence[Mapping[str, Any]] | None,
        result: Mapping[str, Any] | None,
        actions: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        cycle = _cycle(state)
        valid_events = [
            event for event in events if isinstance(event, Mapping)
        ] if isinstance(events, Sequence) and not isinstance(events, (str, bytes)) else []
        incidents: list[str] = []
        if any(event.get("type") == "dupe_died" for event in valid_events):
            incidents.append("dupe_death")
        components = score.get("components") if isinstance(score, Mapping) else None
        if isinstance(components, Mapping):
            for name in (
                "stress_persistent",
                "hunger_persistent",
                "low_oxygen_persistent",
            ):
                component = components.get(name)
                if isinstance(component, Mapping) and component.get("status") == "known" and component.get("raw") == 1:
                    incidents.append(name)

        rejected = self._repeated_rejection(state, result, actions)
        if rejected:
            incidents.append("repeated_rejection")

        observed: list[dict[str, Any]] = []
        for incident_type in incidents:
            evidence = _evidence_for(incident_type, state, valid_events, result, actions)
            subject = _incident_subject(incident_type, evidence)
            lesson_id = f"{incident_type}:{subject}"
            lesson = self._upsert_lesson(lesson_id, incident_type, cycle, evidence)
            observed.append(lesson)
            self._upsert_proposal(_proposal_for(incident_type, cycle, self.config))

        self.memory["lessons"] = self.memory["lessons"][-self.max_entries :]
        self.memory["max_entries"] = self.max_entries
        return observed

    def _repeated_rejection(
        self,
        state: Mapping[str, Any],
        result: Mapping[str, Any] | None,
        actions: Sequence[Mapping[str, Any]] | None,
    ) -> bool:
        del state
        results = result.get("results") if isinstance(result, Mapping) else None
        if not isinstance(results, list):
            return False
        repeated = False
        for index, item in enumerate(results):
            if not isinstance(item, Mapping) or item.get("ok") is not False:
                continue
            action = actions[index] if actions and index < len(actions) else None
            signature = json.dumps(
                {"action": action, "result": item},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            self._reject_counts[signature] = self._reject_counts.get(signature, 0) + 1
            minimum = self.config.get(
                "rejection_repetitions", DEFAULT_REJECTION_REPETITIONS
            )
            if not _positive_int(minimum):
                minimum = DEFAULT_REJECTION_REPETITIONS
            repeated = repeated or self._reject_counts[signature] >= minimum
        return repeated

    def _upsert_lesson(
        self,
        lesson_id: str,
        incident_type: str,
        cycle: int | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        lessons = self.memory["lessons"]
        existing = next((item for item in lessons if item.get("id") == lesson_id), None)
        hypothesis = f"Giả thuyết: sự cố {incident_type} có thể liên quan đến điều kiện đã ghi nhận; cần xác minh."
        proposal = _proposal_for(incident_type, cycle, self.config)
        if existing is None:
            existing = {
                "id": lesson_id,
                "cycle": cycle,
                "last_cycle": cycle,
                "incident_type": incident_type,
                "evidence": dict(evidence),
                "cause_hypothesis": hypothesis,
                "proposed_rule": proposal,
                "occurrences": 1,
                "recent_cycles": [cycle],
            }
            lessons.append(existing)
        else:
            same_observation = (
                existing.get("last_cycle") == cycle
                and existing.get("evidence") == evidence
            )
            existing["cycle"] = cycle
            existing["last_cycle"] = cycle
            existing["evidence"] = dict(evidence)
            existing["cause_hypothesis"] = hypothesis
            existing["proposed_rule"] = proposal
            if not same_observation:
                existing["occurrences"] = existing.get("occurrences", 1) + 1
            recent = existing.get("recent_cycles", [])
            existing["recent_cycles"] = (
                [*recent, cycle][-10:]
                if not recent or recent[-1] != cycle
                else recent[-10:]
            )
            lessons.remove(existing)
            lessons.append(existing)
        return dict(existing)

    def _upsert_proposal(self, proposal: Mapping[str, Any]) -> None:
        proposals = self.proposed_rules["proposals"]
        existing = next((item for item in proposals if item.get("id") == proposal["id"]), None)
        if existing is None:
            proposals.append(dict(proposal))
        else:
            existing["condition"] = dict(proposal["condition"])
            existing["cause_hypothesis"] = proposal["cause_hypothesis"]
            existing["last_observed_cycle"] = proposal["last_observed_cycle"]

    def lessons_for_log(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return [
            {
                "id": item["id"],
                "incident_type": item["incident_type"],
                "last_cycle": item.get("last_cycle", item["cycle"]),
                "occurrences": item["occurrences"],
                "proposed_rule": item["proposed_rule"],
            }
            for item in self.memory["lessons"][-max(0, limit) :]
        ]

    def save(
        self,
        memory_path: str | Path = MEMORY_PATH,
        proposed_path: str | Path = PROPOSED_RULES_PATH,
    ) -> None:
        validate_memory(self.memory)
        validate_proposed_rules(self.proposed_rules)
        _atomic_write(Path(memory_path), self.memory)
        _atomic_write(Path(proposed_path), self.proposed_rules)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate proposed ONI rules")
    parser.add_argument("--validate", action="store_true", required=True)
    parser.add_argument("--proposed", type=Path, default=PROPOSED_RULES_PATH)
    args = parser.parse_args(argv)
    try:
        document = load_proposed_rules(args.proposed)
    except (OSError, json.JSONDecodeError, MemoryValidationError) as error:
        parser.exit(2, f"memory: {error}\n")
    print(json.dumps({"valid": True, "proposals": len(document["proposals"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
