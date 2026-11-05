import json
from pathlib import Path

from agent import agent_main
from agent.planner import Goal
from agent import planner


def test_barracks_cli_overrides_bed_count_and_tile_id(tmp_path, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures"
    (tmp_path / "oni_state.json").write_text(
        (fixtures / "barracks_clear.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text(
        (fixtures / "barracks_catalog.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config_path = tmp_path / "agent-config.json"
    config_path.write_text(
        json.dumps(
            {
                "priority_techs": ["FarmingTech"],
                "pending_steps": 30,
                "bed_id": "Bed",
                "door_id": "Door",
                "tile_id": None,
                "barracks_bed_count": 1,
                "goal_ranks": {},
            }
        ),
        encoding="utf-8",
    )
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)

    assert agent_main.run(
        [
            "--dry-run",
            "--max-steps",
            "1",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
            "--goals",
            "barracks",
            "--barracks-bed-count",
            "2",
            "--tile-id",
            "Tile",
        ]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["goal_id"] == "barracks"
    assert sum(action["id"] == "Bed" for action in entry["actions"]) == 2
    assert sum(action["id"] == "Tile" for action in entry["actions"]) == 18


def test_dry_run_writes_jsonl_without_sending(tmp_path, monkeypatch, capsys):
    (tmp_path / "oni_state.json").write_text(
        json.dumps(
            {
                "cycle": 1,
                "dupes": [],
                "resources": {},
                "research": {
                    "active": None,
                    "techs": [
                        {
                            "id": "FarmingTech",
                            "complete": False,
                            "ready": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not send commands")
        ),
    )
    monkeypatch.setattr(
        agent_main,
        "choose_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a single eligible goal must not call the LLM")
        ),
    )

    assert agent_main.run(
        ["--dry-run", "--max-steps", "1", "--data-dir", str(tmp_path)]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["goal_id"] == "research_target"
    assert entry["selection_reason"] == "rule"
    assert entry["result"]["reason"] == "dry_run"
    assert entry["result"]["actions"] == [
        {"type": "set_research", "tech": "FarmingTech"}
    ]
    assert json.loads(capsys.readouterr().out)["step"] == 1


def test_emergency_rule_runs_before_catalog_or_skills(tmp_path, monkeypatch):
    (tmp_path / "oni_state.json").write_text(
        json.dumps(
            {
                "cycle": 1,
                "dupes": [],
                "oxygen_air": 10,
                "environment": {"temperature_avg_k": 295},
                "alerts": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(
        agent_main,
        "choose_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("emergency must skip the LLM")
        ),
    )
    monkeypatch.setattr(
        agent_main,
        "next_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("emergency must take priority over the planner")
        ),
    )

    assert agent_main.run(
        ["--max-steps", "1", "--data-dir", str(tmp_path)]
    ) == 0
    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["goal_id"] == "emergency"
    assert entry["selection_reason"] == "rule"
    assert entry["result"]["reason"] == "low_oxygen"


def test_llm_is_called_only_for_same_rank_goal_tie(tmp_path, monkeypatch, capsys):
    (tmp_path / "oni_state.json").write_text(
        json.dumps({"cycle": 2, "dupes": [], "oxygen_air": 900, "alerts": []}),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(
        agent_main,
        "load_agent_config",
        lambda path: {"priority_techs": ["FarmingTech"], "pending_steps": 30},
    )
    monkeypatch.setattr(
        planner,
        "GOALS",
        [
            Goal(
                "first",
                "first tied goal",
                lambda state: False,
                lambda state, catalog, config: [{"type": "dig", "x": 1, "y": 2}],
            ),
            Goal(
                "second",
                "second tied goal",
                lambda state: False,
                lambda state, catalog, config: [{"type": "dig", "x": 3, "y": 4}],
            ),
        ],
    )
    monkeypatch.setattr(planner, "_GOAL_RANKS", {"first": 0, "second": 0})
    llm_calls = []

    def choose_tied_goal(state, candidates):
        llm_calls.append([candidate["id"] for candidate in candidates])
        return next(candidate for candidate in candidates if candidate["id"] == "second")

    monkeypatch.setattr(agent_main, "choose_action", choose_tied_goal)
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not send commands")
        ),
    )

    assert agent_main.run(
        ["--dry-run", "--max-steps", "1", "--data-dir", str(tmp_path)]
    ) == 0
    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert len(llm_calls) == 1
    assert llm_calls[0] == ["first", "second", "no_op"]
    assert entry["goal_id"] == "second"
    assert entry["selection_reason"] == "llm"
