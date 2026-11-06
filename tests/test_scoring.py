import json
from pathlib import Path

from agent import agent_main
from agent.scoring import (
    DEFAULT_SCORING_CONFIG,
    EventJournalReader,
    ScoringTracker,
    make_score_record,
    write_score_record,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_healthy_colony_rewards_cycle_achievement_stability_and_room():
    current = _fixture("scoring_healthy.json")
    previous = json.loads(json.dumps(current))
    previous["cycle"] = 7
    previous["achievements"][0]["achieved"] = False

    score = ScoringTracker().score(current, previous_state=previous, events=[])

    assert score["components"]["cycle_survived"]["raw"] == 1
    assert score["components"]["achievement_new"]["raw"] == 1
    assert score["components"]["food_stability"]["raw"] == 1
    assert score["components"]["oxygen_stability"]["raw"] == 1
    assert score["components"]["qualified_rooms"]["raw"] == 1
    assert score["components"]["dupe_death"]["raw"] == 0
    assert score["components"]["morale"]["status"] == "unknown"
    assert score["total"] > 0


def test_low_oxygen_and_hunger_are_penalized_after_policy_persistence_reads():
    oxygen_state = _fixture("scoring_low_oxygen.json")
    hungry_state = _fixture("scoring_hungry.json")
    tracker = ScoringTracker()

    for _ in range(2):
        score = tracker.score(oxygen_state, events=[])
    assert score["components"]["oxygen_stability"]["raw"] == -1
    assert score["components"]["low_oxygen_persistent"]["raw"] == 0
    assert score["components"]["low_oxygen_persistent"]["points"] == 0

    score = tracker.score(oxygen_state, events=[])
    assert score["components"]["low_oxygen_persistent"]["points"] < 0

    for _ in range(3):
        hungry_score = tracker.score(hungry_state, events=[])
    assert hungry_score["components"]["food_stability"]["raw"] == -1
    assert hungry_score["components"]["hunger_persistent"]["points"] < 0


def test_persistent_high_stress_receives_policy_penalty():
    state = _fixture("scoring_healthy.json")
    state["dupes"][0]["stress"] = 95
    tracker = ScoringTracker()

    for _ in range(3):
        score = tracker.score(state, events=[])

    assert score["components"]["stress_persistent"]["points"] < 0


def test_dupe_death_event_receives_configured_penalty():
    state = _fixture("scoring_dupe_dead.json")
    score = ScoringTracker().score(state, events=state["events"])

    assert score["components"]["dupe_death"]["raw"] == 1
    assert score["components"]["dupe_death"]["points"] == -100.0


def test_missing_state_fields_are_unknown_and_json_serializable():
    score = ScoringTracker().score(
        _fixture("scoring_missing_fields.json"),
        events=None,
        result=None,
    )

    assert score["components"]["cycle_survived"]["status"] == "unknown"
    assert score["components"]["achievement_new"]["status"] == "unknown"
    assert score["components"]["morale"]["status"] == "unknown"
    assert score["components"]["food_stability"]["status"] == "unknown"
    assert score["components"]["oxygen_stability"]["status"] == "unknown"
    assert score["components"]["qualified_rooms"]["status"] == "unknown"
    assert score["components"]["dupe_death"]["status"] == "unknown"
    assert score["components"]["material_waste"]["status"] == "unknown"
    json.dumps(score, allow_nan=False)


def test_only_repeated_rejected_action_signatures_are_penalized():
    tracker = ScoringTracker()
    state = _fixture("scoring_healthy.json")
    rejected_result = {
        "results": [{"type": "build", "ok": False, "reason": "blocked"}]
    }
    actions = [{"type": "build", "id": "FixtureBuilding", "x": 1, "y": 2}]

    first = tracker.score(state, events=[], result=rejected_result, actions=actions)
    second = tracker.score(state, events=[], result=rejected_result, actions=actions)

    assert first["components"]["repeated_rejection"]["raw"] == 0
    assert second["components"]["repeated_rejection"]["raw"] == 1
    assert second["components"]["repeated_rejection"]["points"] < 0


def test_score_record_writes_cycle_commit_save_and_seed(tmp_path):
    state = _fixture("scoring_healthy.json")
    score = ScoringTracker().score(state, events=[])
    record = make_score_record(score, state, commit_hash="abc123", step=4)
    path = tmp_path / "logs" / "score.jsonl"

    write_score_record(record, path)
    written = json.loads(path.read_text(encoding="utf-8").strip())

    assert written["cycle"] == 8
    assert written["agent_commit"] == "abc123"
    assert written["save_name"] == "fixture-colony"
    assert written["seed"] == 12345
    assert written["step"] == 4


def test_agent_loop_appends_score_jsonl_without_affecting_dry_run(tmp_path, monkeypatch):
    state = _fixture("scoring_healthy.json")
    (tmp_path / "oni_state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)

    assert agent_main.run(
        ["--dry-run", "--max-steps", "1", "--data-dir", str(tmp_path)]
    ) == 0

    score_path = log_path.parent / "score.jsonl"
    record = json.loads(score_path.read_text(encoding="utf-8").strip())
    assert record["cycle"] == 8
    assert isinstance(record["agent_commit"], str)
    assert record["save_name"] == "fixture-colony"
    assert record["seed"] == 12345


def test_event_reader_retries_incomplete_jsonl_line(tmp_path):
    path = tmp_path / "oni_events.jsonl"
    reader = EventJournalReader(path)
    path.write_bytes(b'{"type":"dupe_died"')

    assert reader.read_new() == []
    with path.open("ab") as event_file:
        event_file.write(b',"cycle":3}\n')

    assert reader.read_new() == [{"type": "dupe_died", "cycle": 3}]


def test_agent_event_reader_ignores_preexisting_event_history(tmp_path):
    path = tmp_path / "oni_events.jsonl"
    path.write_text('{"type":"dupe_died"}\n', encoding="utf-8")
    reader = EventJournalReader(path, start_at_end=True)

    assert reader.read_new() == []
    with path.open("a", encoding="utf-8") as event_file:
        event_file.write('{"type":"dupe_died","cycle":10}\n')
    assert reader.read_new() == [{"type": "dupe_died", "cycle": 10}]


def test_scoring_defaults_mark_all_unverified_policy_thresholds():
    notes = DEFAULT_SCORING_CONFIG["threshold_notes"]
    assert all(note.startswith("TODO_VERIFY") for note in notes.values())
