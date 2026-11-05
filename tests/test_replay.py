import json
from pathlib import Path

from agent.replay import replay_log


FIXTURES = Path(__file__).parent / "fixtures"


def _rule_input_and_actions():
    state = json.loads((FIXTURES / "empty_map.json").read_text(encoding="utf-8"))
    state["cycle"] = 10
    state["environment"] = {"oxygen_avg_g": 500}
    state["dupes"] = []
    state["alerts"] = []
    state["resources"] = {
        "materials": {"SandStone": 1000, "ZincOre": 1000}
    }
    state["building_list"] = []
    rows = state["world"]["map"]
    rows[10] = rows[10][:20] + "L" + rows[10][21:]
    rows[15] = "#" * 41
    return {
        "state": state,
        "history": [state],
        "pending": {},
        "cooldowns": {},
        "skill_config": {
            "bed_id": None,
            "door_id": None,
            "tile_id": None,
            "barracks_bed_count": 4,
        },
    }, [
        {
            "type": "build",
            "id": "LiquidPumpingStation",
            "x": 0,
            "y": 6,
            "orientation": "Neutral",
            "elements": ["SandStone"],
            "priority": 5,
        },
        {
            "type": "build",
            "id": "WashBasin",
            "x": -2,
            "y": 6,
            "orientation": "Neutral",
            "elements": ["SandStone"],
            "priority": 5,
        },
    ]


def test_replay_matches_logged_decision_and_actions(tmp_path):
    replay_input, actions = _rule_input_and_actions()
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "step": 4,
                "selection_reason": "rule_engine",
                "rule_id": "growth-water-setup",
                "actions": actions,
                "rule_replay_input": replay_input,
            }
        ),
        encoding="utf-8",
    )
    catalog = json.loads(
        (FIXTURES / "basic_skills_catalog.json").read_text(encoding="utf-8")
    )

    result = replay_log(log_path, catalog)

    assert result["counts"] == {"match": 1, "mismatch": 0, "unavailable": 0}
    assert result["comparisons"][0]["decision_match"] is True
    assert result["comparisons"][0]["actions_match"] is True


def test_replay_detects_different_recorded_actions(tmp_path):
    replay_input, _actions = _rule_input_and_actions()
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "step": 5,
                "selection_reason": "rule_engine",
                "rule_id": "growth-water-setup",
                "actions": [],
                "rule_replay_input": replay_input,
            }
        ),
        encoding="utf-8",
    )
    catalog = json.loads(
        (FIXTURES / "basic_skills_catalog.json").read_text(encoding="utf-8")
    )

    result = replay_log(log_path, catalog)

    assert result["counts"]["mismatch"] == 1
    assert result["comparisons"][0]["decision_match"] is True
    assert result["comparisons"][0]["actions_match"] is False


def test_replay_marks_older_logs_unavailable_and_ignores_non_rule_rows(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps(entry)
            for entry in (
                {"step": 1, "selection_reason": "rule_engine", "actions": []},
                {"step": 2, "selection_reason": "planner", "actions": []},
            )
        ),
        encoding="utf-8",
    )

    result = replay_log(log_path, [])

    assert result["counts"] == {"match": 0, "mismatch": 0, "unavailable": 1}
    assert result["comparisons"][0]["reason"] == "rule_input_not_recorded"
