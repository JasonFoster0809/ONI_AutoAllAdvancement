import json
from collections import deque
from pathlib import Path

from agent.rules import (
    alert_rule,
    choose_emergency_action,
    detect_emergency,
    hunger_rule,
    oxygen_rule,
    oxygen_value,
    stress_rule,
    temperature_rule,
)


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_oxygen_rule_and_highest_priority_selection():
    state = load_fixture("low_oxygen.json")
    state["dupes"][0]["calories_kcal"] = 0
    candidates = [
        {"id": "food", "category": "food", "actions": [{"type": "build"}]},
        {"id": "oxygen", "category": "oxygen", "actions": [{"type": "build"}]},
        {"id": "no_op", "category": "no_op", "actions": []},
    ]
    assert oxygen_rule(state) == "low_oxygen"
    assert choose_emergency_action(state, candidates)["id"] == "oxygen"


def _evaluate_oxygen_samples(states, consecutive=3, threshold=50.0):
    history = deque(maxlen=consecutive)
    decision = None
    for state in states:
        oxygen = oxygen_value(state)
        history.append(oxygen is not None and oxygen < threshold)
        decision = choose_emergency_action(
            state,
            [],
            oxygen_history=tuple(history),
            oxygen_min_g=threshold,
            oxygen_consecutive_readings=consecutive,
        )
    return decision


def test_oxygen_fluctuation_does_not_trigger_before_consecutive_threshold():
    states = [
        {"oxygen_air": 16, "environment": {"oxygen_avg_g": 280}},
        {"oxygen_air": 288, "environment": {"oxygen_avg_g": 20}},
        {"oxygen_air": 16, "environment": {"oxygen_avg_g": 300}},
    ]

    assert _evaluate_oxygen_samples(states) is None
    assert oxygen_rule(states[0]) is None


def test_sustained_low_oxygen_triggers_after_configured_readings():
    states = [
        {"environment": {"oxygen_avg_g": value}, "alerts": []}
        for value in (45, 40, 35)
    ]

    decision = _evaluate_oxygen_samples(states)

    assert decision is not None
    assert decision["reason"] == "low_oxygen"


def test_oxygen_uses_dupe_sample_when_environment_value_is_unavailable():
    state = {"oxygen_air": 30, "environment": {"temperature_avg_k": 295}}
    assert oxygen_value(state) == 30
    assert oxygen_rule(state) == "low_oxygen"
    assert _evaluate_oxygen_samples([state] * 3)["reason"] == "low_oxygen"


def test_mod_alert_triggers_without_oxygen_reading_history():
    state = {
        "oxygen_air": 10,
        "environment": {"oxygen_avg_g": 300},
        "alerts": [{"type": "oxygen_warning"}],
    }

    decision = choose_emergency_action(
        state,
        [],
        oxygen_history=(False,),
        oxygen_consecutive_readings=3,
    )

    assert decision["reason"] == "alert:oxygen_warning"


def test_hunger_rule():
    state = load_fixture("hungry.json")
    assert hunger_rule(state) == "dupe_hungry"
    assert choose_emergency_action(state, [])["reason"] == "dupe_hungry"


def test_hunger_rule_detects_low_total_stock_without_low_dupe_calories():
    state = load_fixture("emergency_food_state.json")
    assert hunger_rule(state) == "food_stock_low"
    assert detect_emergency(state) == {
        "category": "food",
        "reason": "food_stock_low",
    }


def test_stress_rule_uses_state_or_alert():
    state = load_fixture("normal.json")
    state["dupes"][0]["stress"] = 95
    assert stress_rule(state) == "dupe_high_stress"
    state["dupes"][0]["stress"] = 20
    state["alerts"] = [{"type": "dupe_high_stress"}]
    assert stress_rule(state) == "dupe_high_stress"


def test_temperature_rule_and_candidate():
    state = load_fixture("normal.json")
    state["environment"]["temperature_avg_k"] = 320
    assert temperature_rule(state) == "temperature_high"
    decision = choose_emergency_action(
        state,
        [{"id": "cooling", "category": "temperature", "actions": [{"type": "build"}]}],
    )
    assert decision["id"] == "cooling"


def test_alert_rule_and_normal_state():
    normal = load_fixture("normal.json")
    assert all(rule(normal) is None for rule in (oxygen_rule, hunger_rule, stress_rule, temperature_rule, alert_rule))
    state = dict(normal, alerts=[{"type": "other_alert"}])
    assert alert_rule(state) == "alert:other_alert"
