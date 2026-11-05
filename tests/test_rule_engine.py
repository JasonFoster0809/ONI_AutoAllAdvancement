import json
from pathlib import Path

import pytest

from agent.rule_engine import (
    RuleValidationError,
    explain_rules,
    load_rules,
    main,
    phase_for_cycle,
    validate_rules,
)


FIXTURES = Path(__file__).parent / "fixtures"


def document_with(when, *, priority=10, skill="existing"):
    return {
        "phases": [{"id": "early", "start_cycle": 0, "end_cycle": 10, "goals": []}],
        "rules": [
            {
                "id": "test-rule",
                "priority": priority,
                "when": when,
                "then": {"skill": skill, "args": {}},
                "cooldown_cycles": 2,
                "pending": 2,
                "requires": [skill],
            }
        ],
    }


def test_rules_file_has_requested_cycle_phases_and_validates():
    rules = load_rules()
    assert [phase["start_cycle"] for phase in rules["phases"]] == [0, 10, 30]
    assert [phase["end_cycle"] for phase in rules["phases"]] == [10, 30, 100]
    assert phase_for_cycle(rules, 0) == "early"
    assert phase_for_cycle(rules, 10) == "growth"
    assert phase_for_cycle(rules, 30) == "midgame"
    assert phase_for_cycle(rules, 100) is None


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", 20, True),
        ("ne", 19, True),
        ("lt", 21, True),
        ("lte", 20, True),
        ("gt", 19, True),
        ("gte", 20, True),
    ],
)
def test_numeric_comparisons(operator, value, expected):
    explanation = explain_rules(
        {"temperature": 20},
        document=document_with({"op": operator, "path": "temperature", "value": value}),
        executors={"existing": lambda *_: []},
    )
    assert explanation["selected"]["status"] == "matched"
    assert explanation["reasons"][0]["reason"] == "condition_true"


def test_missing_or_invalid_comparison_data_is_unknown():
    condition = {"op": "lt", "path": "environment.oxygen_avg_g", "value": 50}
    for state in ({}, {"environment": {}}, {"environment": {"oxygen_avg_g": "low"}}):
        result = explain_rules(state, document=document_with(condition))
        assert result["selected"] is None
        assert result["reasons"][0]["status"] == "unknown"


def test_building_count_filters_by_id_and_state():
    condition = {
        "op": "count",
        "building": "Outhouse",
        "state": "built",
        "comparison": "lt",
        "value": 2,
    }
    state = {
        "building_list": [
            {"id": "Outhouse", "state": "built"},
            {"id": "Outhouse", "state": "under_construction"},
            {"id": "Bed", "state": "built"},
        ]
    }
    assert explain_rules(
        state,
        document=document_with(condition),
        executors={"existing": lambda *_: []},
    )["selected"]["status"] == "matched"
    assert explain_rules({}, document=document_with(condition))["reasons"][0]["status"] == "unknown"


def test_for_n_reads_requires_complete_known_history():
    condition = {
        "op": "for",
        "reads": 3,
        "condition": {"op": "lt", "path": "oxygen", "value": 50},
    }
    document = document_with(condition)
    assert explain_rules(
        {"oxygen": 30},
        document=document,
        history=[{"oxygen": 30}, {"oxygen": 40}],
    )["reasons"][0]["status"] == "unknown"
    assert explain_rules(
        {"oxygen": 30},
        document=document,
        history=[{"oxygen": 30}, {"oxygen": 40}, {"oxygen": 30}],
        executors={"existing": lambda *_: []},
    )["selected"]["status"] == "matched"
    mixed = [{"oxygen": 30}, {}, {"oxygen": 30}]
    assert explain_rules(
        {"oxygen": 30}, document=document, history=mixed
    )["reasons"][0]["status"] == "unknown"
    assert explain_rules(
        {"oxygen": 30},
        document=document,
        history=[{"oxygen": 30}, {"oxygen": 60}, {"oxygen": 30}],
    )["reasons"][0]["status"] == "not_matched"


def test_exists_is_unknown_when_path_is_missing_and_true_when_present():
    document = document_with({"op": "exists", "path": "dupes.0.bed_id"})
    assert explain_rules({}, document=document)["reasons"][0]["status"] == "unknown"
    matched = explain_rules(
        {"dupes": [{"bed_id": 123}]},
        document=document,
        executors={"existing": lambda *_: []},
    )
    assert matched["selected"]["status"] == "matched"


def test_highest_priority_matched_rule_is_selected():
    document = document_with({"op": "lt", "path": "value", "value": 10})
    document["rules"].append(
        {
            **document["rules"][0],
            "id": "higher-priority",
            "priority": 20,
            "then": {"skill": "not-implemented", "args": {}},
            "requires": ["not-implemented"],
        }
    )
    result = explain_rules(
        {"value": 1},
        document=document,
        executors={"existing": lambda *_: []},
    )
    assert result["selected"]["rule_id"] == "higher-priority"
    assert result["selected"]["status"] == "TODO_NOT_IMPLEMENTED"


def test_cooldown_and_pending_prevent_duplicate_skill_calls():
    calls = []
    executor = lambda *_: calls.append("called") or []
    document = document_with({"op": "lt", "path": "value", "value": 10})
    state = {"cycle": 5, "value": 1}
    pending = explain_rules(state, document=document, pending={"test-rule": {}})
    assert pending["reasons"][0]["reason"] == "pending"
    cooldown = explain_rules(
        state,
        document=document,
        cooldowns={"test-rule": 4},
    )
    assert cooldown["reasons"][0]["reason"] == "cooldown"
    assert explain_rules(
        state,
        document=document,
        cooldowns={"test-rule": 4},
        executors={"existing": executor},
    )["selected"] is None
    assert calls == []


def test_skill_plan_is_capped_at_twelve_actions():
    document = document_with({"op": "lt", "path": "value", "value": 10})
    result = explain_rules(
        {"value": 1},
        document=document,
        executors={"existing": lambda *_: [{"type": "dig", "x": i, "y": 0} for i in range(20)]},
    )
    assert len(result["selected"]["actions"]) == 12
    assert result["selected"]["truncated"] is True
    assert result["selected"]["reason"] == "action_limit_12"


def test_rule_validation_rejects_duplicate_ids_and_nested_for():
    document = document_with(
        {"op": "for", "reads": 2, "condition": {"op": "for", "reads": 2, "condition": {"op": "exists", "path": "x"}}}
    )
    with pytest.raises(RuleValidationError, match="cannot nest"):
        validate_rules(document)
    document = document_with({"op": "exists", "path": "x"})
    document["rules"].append(dict(document["rules"][0]))
    with pytest.raises(RuleValidationError, match="unique"):
        validate_rules(document)


def test_cli_validate_and_explain(tmp_path, capsys):
    assert main(["--validate"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    state_path = tmp_path / "state.json"
    state_path.write_text('{"cycle":2,"environment":{"oxygen_avg_g":40}}', encoding="utf-8")
    assert main(["--explain", "--state", str(state_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phase"] == "early"
    assert result["reasons"][0]["status"] == "unknown"
