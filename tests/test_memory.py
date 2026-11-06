import json
from pathlib import Path

import pytest

from agent import agent_main
from agent.memory import (
    MemoryTracker,
    MemoryValidationError,
    _empty_memory,
    load_memory,
    load_proposed_rules,
    main,
    validate_proposed_rules,
)
from agent.scoring import DEFAULT_SCORING_CONFIG, ScoringTracker


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _tracker(max_entries=100):
    return MemoryTracker(
        _empty_memory(max_entries),
        {"version": 1, "proposals": []},
        config=DEFAULT_SCORING_CONFIG,
        max_entries=max_entries,
    )


def _observe(tracker, scorer, state, *, events=None, result=None, actions=None):
    score = scorer.score(state, events=events, result=result, actions=actions)
    return tracker.observe(
        state,
        score=score,
        events=events,
        result=result,
        actions=actions,
    )


def test_simulated_incident_sequences_capture_evidence_and_proposals():
    tracker = _tracker()
    scorer = ScoringTracker()

    oxygen = _fixture("scoring_low_oxygen.json")
    for cycle in (10, 11, 12):
        oxygen["cycle"] = cycle
        incidents = _observe(tracker, scorer, oxygen, events=[])
    assert [item["incident_type"] for item in incidents] == [
        "low_oxygen_persistent"
    ]

    hungry = _fixture("scoring_hungry.json")
    for cycle in (13, 14, 15):
        hungry["cycle"] = cycle
        incidents = _observe(tracker, scorer, hungry, events=[])
    assert [item["incident_type"] for item in incidents] == ["hunger_persistent"]

    stressed = _fixture("scoring_healthy.json")
    stressed["dupes"][0]["stress"] = 95
    for cycle in (16, 17, 18):
        stressed["cycle"] = cycle
        incidents = _observe(tracker, scorer, stressed, events=[])
    assert [item["incident_type"] for item in incidents] == ["stress_persistent"]

    dead = _fixture("scoring_dupe_dead.json")
    dead["cycle"] = 19
    death_event = {
        "cycle": 19,
        "type": "dupe_died",
        "data": {"dupe": "Fixture Dupe"},
    }
    incidents = _observe(tracker, scorer, dead, events=[death_event])
    assert [item["incident_type"] for item in incidents] == ["dupe_death"]
    assert incidents[0]["evidence"]["events"] == [death_event]

    action = {"type": "build", "id": "FixturePrefab", "x": 2, "y": 3}
    rejection = {"results": [{"type": "build", "ok": False, "reason": "blocked"}]}
    rejected_state = _fixture("scoring_healthy.json")
    rejected_state["cycle"] = 20
    assert not _observe(
        tracker, scorer, rejected_state, events=[], result=rejection, actions=[action]
    )
    rejected_state["cycle"] = 21
    incidents = _observe(
        tracker, scorer, rejected_state, events=[], result=rejection, actions=[action]
    )
    assert [item["incident_type"] for item in incidents] == ["repeated_rejection"]
    assert incidents[0]["evidence"]["rejected_actions"][0]["action"] == action

    proposal_ids = {item["id"] for item in tracker.proposed_rules["proposals"]}
    assert proposal_ids == {
        "incident-low_oxygen_persistent",
        "incident-hunger_persistent",
        "incident-stress_persistent",
        "incident-dupe_death",
        "incident-repeated_rejection",
    }
    assert all(
        "giả thuyết" in item["cause_hypothesis"].casefold()
        for item in tracker.memory["lessons"]
    )


def test_missing_or_invalid_state_fields_do_not_create_incidents():
    tracker = _tracker()
    scorer = ScoringTracker()

    for state in (
        _fixture("scoring_missing_fields.json"),
        {"cycle": 2, "dupes": [{"name": "Missing telemetry"}]},
        {"cycle": 3, "environment": None, "dupes": None},
    ):
        score = scorer.score(state, events=None)
        assert tracker.observe(
            state,
            score=score,
            events=None,
            result=None,
            actions=None,
        ) == []
    assert tracker.memory["lessons"] == []
    assert tracker.proposed_rules["proposals"] == []


def test_repeated_same_incident_is_consolidated_without_duplicate_lesson():
    tracker = _tracker()
    scorer = ScoringTracker()
    death_event = {"cycle": 4, "type": "dupe_died", "data": {"dupe": "Same Dupe"}}
    state = {"cycle": 4}

    for _ in range(3):
        _observe(tracker, scorer, state, events=[death_event])

    assert len(tracker.memory["lessons"]) == 1
    assert tracker.memory["lessons"][0]["occurrences"] == 1
    assert tracker.memory["lessons"][0]["recent_cycles"] == [4]
    assert len(tracker.proposed_rules["proposals"]) == 1


def test_memory_keeps_only_recent_entries_and_refresh_moves_duplicate_to_end():
    tracker = _tracker(max_entries=2)
    scorer = ScoringTracker()
    death_a = {"cycle": 1, "type": "dupe_died", "data": {"dupe": "A"}}
    death_b = {"cycle": 2, "type": "dupe_died", "data": {"dupe": "B"}}
    death_c = {"cycle": 3, "type": "dupe_died", "data": {"dupe": "C"}}

    _observe(tracker, scorer, {"cycle": 1}, events=[death_a])
    _observe(tracker, scorer, {"cycle": 2}, events=[death_b])
    _observe(tracker, scorer, {"cycle": 3}, events=[death_a])
    _observe(tracker, scorer, {"cycle": 4}, events=[death_c])

    assert [lesson["id"] for lesson in tracker.memory["lessons"]] == [
        "dupe_death:A",
        "dupe_death:C",
    ]


def test_memory_and_proposals_persist_atomically_and_validate(tmp_path):
    tracker = _tracker()
    _observe(
        tracker,
        ScoringTracker(),
        {"cycle": 0},
        events=[{"type": "dupe_died", "data": {"dupe": "Zero Cycle"}}],
    )
    memory_path = tmp_path / "memory.json"
    proposal_path = tmp_path / "rules_proposed.yaml"

    tracker.save(memory_path, proposal_path)

    loaded_memory = load_memory(memory_path)
    loaded_proposals = load_proposed_rules(proposal_path)
    assert len(loaded_memory["lessons"]) == 1
    assert loaded_memory["lessons"][0]["cycle"] == 0
    assert len(loaded_proposals["proposals"]) == 1
    assert main(["--validate", "--proposed", str(proposal_path)]) == 0


def test_proposed_rule_validator_rejects_invalid_entries():
    invalid = {
        "version": 1,
        "proposals": [
            {
                "id": "bad",
                "incident_type": "dupe_death",
                "priority": 1,
                "last_observed_cycle": 1,
                "condition": {
                    "source": "state",
                    "path": "dupes.0.calories_kcal",
                    "operator": "lt",
                    "value": 100,
                },
                "action": {"type": "skill_review", "skill": "", "args": {}},
                "cause_hypothesis": "Giả thuyết cần duyệt",
                "review_required": True,
            }
        ],
    }
    with pytest.raises(MemoryValidationError, match="skill_review"):
        validate_proposed_rules(invalid)


def test_cli_validates_the_committed_empty_proposal_file(capsys):
    assert main(["--validate"]) == 0
    assert json.loads(capsys.readouterr().out) == {"valid": True, "proposals": 0}


def test_agent_logs_lessons_without_changing_planner_actions(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "oni_state.json").write_text(
        json.dumps({"cycle": 5, "dupes": [], "alerts": []}),
        encoding="utf-8",
    )
    (data_dir / "oni_catalog.json").write_text("[]", encoding="utf-8")
    memory_dir = tmp_path / "agent"
    memory_dir.mkdir()
    memory_path = memory_dir / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "max_entries": 100,
                "lessons": [
                    {
                        "id": "dupe_death:Prior Dupe",
                        "cycle": 2,
                        "last_cycle": 2,
                        "incident_type": "dupe_death",
                        "evidence": {"events": [{"type": "dupe_died"}]},
                        "cause_hypothesis": "Giả thuyết cần xác minh",
                        "proposed_rule": {
                            "id": "incident-dupe_death",
                            "incident_type": "dupe_death",
                            "priority": 0,
                            "last_observed_cycle": 2,
                            "condition": {"source": "event", "type": "dupe_died"},
                            "action": {
                                "type": "manual_review",
                                "suggestion": "review_colony_survival_plan",
                            },
                            "cause_hypothesis": "Giả thuyết cần xác minh",
                            "review_required": True,
                        },
                        "occurrences": 1,
                        "recent_cycles": [2],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    proposed_path = memory_dir / "rules_proposed.yaml"
    proposed_path.write_text('{"version":1,"proposals":[]}', encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "AGENT_DIR", memory_dir)
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    action = {"type": "dig", "x": 4, "y": 5}
    monkeypatch.setattr(
        agent_main,
        "next_step",
        lambda *args, **kwargs: {
            "goal_id": "unchanged_goal",
            "actions": [action],
            "skipped": [],
        },
    )

    assert agent_main.run(
        ["--dry-run", "--manager", "none", "--max-steps", "1", "--data-dir", str(data_dir)]
    ) == 0

    log_entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert log_entry["actions"] == [action]
    assert log_entry["goal_id"] == "unchanged_goal"
    assert log_entry["memory_lessons"][0]["id"] == "dupe_death:Prior Dupe"
