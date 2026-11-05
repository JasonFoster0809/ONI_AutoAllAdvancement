import json
from pathlib import Path

from agent.rules import (
    alert_rule,
    choose_emergency_action,
    hunger_rule,
    oxygen_rule,
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


def test_hunger_rule():
    state = load_fixture("hungry.json")
    assert hunger_rule(state) == "dupe_hungry"
    assert choose_emergency_action(state, [])["reason"] == "dupe_hungry"


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
