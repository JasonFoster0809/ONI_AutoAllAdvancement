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
        "load_agent_config",
        lambda _path: {
            "priority_techs": ["FarmingTech"],
            "pending_steps": 30,
            "oxygen_min_g": 50.0,
            "oxygen_consecutive_readings": 1,
        },
    )
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
        "load_agent_config",
        lambda _path: {
            "priority_techs": ["FarmingTech"],
            "pending_steps": 30,
            "oxygen_min_g": 50.0,
            "oxygen_consecutive_readings": 1,
        },
    )
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


def test_agent_requires_three_consecutive_low_environment_samples(
    tmp_path, monkeypatch
):
    states = [
        {
            "cycle": index,
            "dupes": [],
            "oxygen_air": 15,
            "environment": {"oxygen_avg_g": 30},
            "alerts": [],
        }
        for index in range(1, 4)
    ]
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _root: states.pop(0))
    monkeypatch.setattr(agent_main, "time", type("NoSleep", (), {"sleep": staticmethod(lambda _: None)})())
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("all returned actions should be no-op in this test")
        ),
    )

    assert agent_main.run(
        ["--max-steps", "3", "--data-dir", str(tmp_path)]
    ) == 0

    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["goal_id"] for entry in entries] == [
        "no_goal",
        "no_goal",
        "emergency",
    ]
    assert entries[-1]["result"]["reason"] == "low_oxygen"


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
        lambda path: {
            "priority_techs": ["FarmingTech"],
            "pending_steps": 30,
            "oxygen_min_g": 50.0,
            "oxygen_consecutive_readings": 3,
        },
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


def _write_emergency_inputs(tmp_path, state_name="emergency_oxygen_state.json"):
    fixtures = Path(__file__).parent / "fixtures"
    (tmp_path / "oni_state.json").write_text(
        (fixtures / state_name).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text(
        (fixtures / "emergency_catalog.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = {
        **agent_main.DEFAULT_CONFIG,
        "oxygen_consecutive_readings": 1,
        "emergency_cooldown_cycles": 1,
        "emergency_pending_cycles": 2,
    }
    config_path = tmp_path / "agent-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _no_sleep_time():
    return type("NoSleep", (), {"sleep": staticmethod(lambda _: None)})()


def test_accepted_emergency_build_is_pending_and_not_resent(tmp_path, monkeypatch):
    config_path = _write_emergency_inputs(tmp_path)
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    sent = []

    def accept_actions(actions, _root):
        sent.append(list(actions))
        return {
            "results": [{"type": action["type"], "ok": True} for action in actions]
        }

    monkeypatch.setattr(agent_main, "send_command", accept_actions)

    assert agent_main.run(
        [
            "--max-steps",
            "3",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
        ]
    ) == 0

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(sent) == 1
    assert sent[0][0]["id"] == "MineralDeoxidizer"
    assert entries[1]["skipped"][0]["reason"] == "emergency_pending"
    assert entries[2]["skipped"][0]["reason"] == "emergency_pending"


def test_accepted_emergency_priorities_are_pending_and_not_resent(tmp_path, monkeypatch):
    config_path = _write_emergency_inputs(tmp_path, "emergency_stress_state.json")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    sent = []

    def accept_actions(actions, _root):
        sent.append(list(actions))
        return {
            "results": [{"type": action["type"], "ok": True} for action in actions]
        }

    monkeypatch.setattr(agent_main, "send_command", accept_actions)

    assert agent_main.run(
        [
            "--max-steps",
            "2",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
        ]
    ) == 0

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(sent) == 1
    assert any(action["type"] == "set_dupe_priority" for action in sent[0])
    assert any(action["type"] == "build" for action in sent[0])
    assert entries[1]["skipped"][0]["reason"] == "emergency_pending"


def test_emergency_cooldown_limits_retries_when_command_is_rejected(
    tmp_path, monkeypatch
):
    config_path = _write_emergency_inputs(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["emergency_cooldown_cycles"] = 2
    config_path.write_text(json.dumps(config), encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    sent = []

    def reject_actions(actions, _root):
        sent.append(list(actions))
        return {
            "results": [{"type": action["type"], "ok": False} for action in actions]
        }

    monkeypatch.setattr(agent_main, "send_command", reject_actions)

    assert agent_main.run(
        [
            "--max-steps",
            "3",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
        ]
    ) == 0

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(sent) == 1
    assert entries[1]["skipped"][0]["reason"] == "emergency_cooldown"
    assert entries[2]["skipped"][0]["reason"] == "emergency_cooldown"


def test_emergency_action_limit_caps_food_priority_actions(tmp_path, monkeypatch):
    config_path = _write_emergency_inputs(tmp_path, "emergency_food_state.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["emergency_max_actions_per_turn"] = 4
    config_path.write_text(json.dumps(config), encoding="utf-8")
    state = json.loads((tmp_path / "oni_state.json").read_text(encoding="utf-8"))
    state["dupes"] = [
        {
            **state["dupes"][0],
            "name": f"Hungry Dupe {index}",
        }
        for index in range(5)
    ]
    state["resources"]["food_kcal"] = 1000
    (tmp_path / "oni_state.json").write_text(json.dumps(state), encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("emergency dry-run must not send commands")
        ),
    )

    assert agent_main.run(
        [
            "--dry-run",
            "--max-steps",
            "1",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
        ]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert len(entry["actions"]) == 4
    assert all(action["type"] == "set_dupe_priority" for action in entry["actions"])
    assert any(item["reason"] == "emergency_action_limit" for item in entry["skipped"])
