"""Repeatable fake state sequences for offline multi-cycle agent tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def oxygen_sequence(values: tuple[float, ...]) -> list[dict[str, Any]]:
    seed = _fixture("emergency_oxygen_state.json")
    states = []
    for cycle, value in enumerate(values, 10):
        state = copy.deepcopy(seed)
        state["cycle"] = cycle
        state["environment"]["oxygen_avg_g"] = value
        states.append(state)
    return states


def algae_empty_sequence(cycles: int = 1) -> list[dict[str, Any]]:
    seed = _fixture("rule_engine_state_redacted.json")
    states = []
    for cycle in range(cycles):
        state = copy.deepcopy(seed)
        state["cycle"] = 20 + cycle
        state["building_list"][0]["stored"] = []
        state["resources"] = {"materials": {"ZincOre": 1000}}
        states.append(state)
    return states


def high_stress_sequence() -> list[dict[str, Any]]:
    state = _fixture("emergency_stress_state.json")
    state["cycle"] = 40
    return [state]


def unknown_sequence() -> list[dict[str, Any]]:
    return [{"cycle": 50}]
