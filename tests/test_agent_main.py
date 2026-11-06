import json
from pathlib import Path

import pytest

from agent import agent_main
from agent.planner import Goal
from agent import planner


@pytest.fixture(autouse=True)
def isolate_persistent_agent_memory(tmp_path, monkeypatch):
    memory_dir = tmp_path / "agent"
    memory_dir.mkdir()
    (memory_dir / "memory.json").write_text(
        '{"version":1,"max_entries":100,"lessons":[]}',
        encoding="utf-8",
    )
    (memory_dir / "rules_proposed.yaml").write_text(
        '{"version":1,"proposals":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_main, "AGENT_DIR", memory_dir)


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
    assert entry["selection_reason"] == "planner"
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
        "plan_goals",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("emergency must skip the Gemini manager")
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
        ["--max-steps", "1", "--data-dir", str(tmp_path), "--manager", "gemini"]
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
    assert entry["selection_reason"] == "qwen"


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


def test_emergency_rules_run_before_strategist_provider(tmp_path, monkeypatch):
    config_path = _write_emergency_inputs(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strategist"]["provider"] = "ollama"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    provider_calls = []

    class Provider:
        def generate(self, *_args, **_kwargs):
            provider_calls.append(True)
            return '{"goals":[]}'

    monkeypatch.setattr(agent_main, "create_goal_provider", lambda _config: Provider())
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
    assert entry["goal_id"] == "emergency"
    assert entry["selection_reason"] == "rule"
    assert provider_calls == []


def test_strategist_goal_order_is_applied_by_planner(tmp_path, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures"
    state = json.loads((fixtures / "barracks_clear.json").read_text(encoding="utf-8"))
    state.update(
        {
            "cycle": 0,
            "dupes": [],
            "research": {
                "active": None,
                "techs": [
                    {"id": "FarmingTech", "complete": False, "ready": True}
                ],
            },
            "achievements": [
                {
                    "id": "ReachedSpace",
                    "name": "Fixture rocket achievement",
                    "achieved": False,
                }
            ],
        }
    )
    (tmp_path / "oni_state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "oni_catalog.json").write_text(
        (fixtures / "barracks_catalog.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = {
        **agent_main.DEFAULT_CONFIG,
        "bed_id": "Bed",
        "door_id": "Door",
        "tile_id": "Tile",
        "barracks_bed_count": 1,
        "strategist": {
            **agent_main.DEFAULT_CONFIG["strategist"],
            "provider": "ollama",
        },
    }
    config_path = tmp_path / "agent-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())

    captured_prompts = []

    class Provider:
        def generate(self, *_args, **_kwargs):
            captured_prompts.append(_args[0])
            return (
                '{"goals":[{"id":"barracks","horizon_cycles":3,'
                '"reason":"A barracks is not reported"}]}'
            )

    monkeypatch.setattr(agent_main, "create_goal_provider", lambda _config: Provider())

    assert agent_main.run(
        [
            "--dry-run",
            "--manager",
            "none",
            "--max-steps",
            "1",
            "--data-dir",
            str(tmp_path),
            "--config",
            str(config_path),
        ]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["goal_id"] == "barracks"
    assert entry["selection_reason"] == "strategist"
    assert entry["strategist"]["goals"][0]["reason"] == (
        "A barracks is not reported"
    )
    assert all(action["type"] == "build" for action in entry["actions"])
    assert captured_prompts[0]["achievement_context"][0]["id"] == "ReachedSpace"
    assert [goal["id"] for goal in captured_prompts[0]["available_goals"]] == [
        "research_target",
        "barracks",
    ]


def _rule_test_state():
    rows = ["." * 41 for _ in range(40)] + ["#" * 41]
    return {
        "cycle": 10,
        "trigger": 1,
        "dupes": [],
        "resources": {
            "food_kcal": 10000,
            "materials": {"ZincOre": 1000, "SandStone": 10000},
        },
        "oxygen_air": 1000,
        "alerts": [],
        "building_list": [],
        "world": {
            "map": rows,
            "origin": {"x": -20, "y": -20},
            "start": {"x": 0, "y": 0},
        },
    }


def _one_oxygen_rule():
    return {
        "phases": [],
        "rules": [
            {
                "id": "test-oxygen",
                "priority": 100,
                "when": {"op": "eq", "path": "trigger", "value": 1},
                "then": {"skill": "build_oxygen_setup", "args": {}},
                "cooldown_cycles": 2,
                "pending": 2,
                "requires": ["build_oxygen_setup"],
            }
        ],
    }


def _one_basic_survival_rule():
    return {
        "phases": [],
        "rules": [
            {
                "id": "test-basic-survival",
                "priority": 90,
                "when": {"op": "basic_survival_needed"},
                "then": {"skill": "build_basic_survival", "args": {}},
                "cooldown_cycles": 2,
                "pending": 2,
                "requires": ["build_basic_survival"],
            }
        ],
    }


def _run_skill_config():
    return {
        **agent_main.DEFAULT_CONFIG,
        "bed_id": "Bed",
        "door_id": "Door",
        "tile_id": "Tile",
        "oxygen_consecutive_readings": 3,
    }


def test_rule_engine_executes_skill_with_live_catalog_and_dry_run(tmp_path, monkeypatch):
    state = _rule_test_state()
    fixture_path = Path(__file__).parent / "fixtures" / "construction_skills_catalog.json"
    catalog = json.loads(fixture_path.read_text(encoding="utf-8"))
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _root: state)
    monkeypatch.setattr(agent_main, "load_catalog", lambda _root: catalog)
    monkeypatch.setattr(agent_main, "load_agent_config", lambda _path: _run_skill_config())
    monkeypatch.setattr(agent_main, "load_rules", _one_oxygen_rule)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not send rule-engine actions")
        ),
    )

    assert agent_main.run(
        ["--dry-run", "--max-steps", "1", "--manager", "none"]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["selection_reason"] == "rule_engine"
    assert entry["rule_evaluation"]["selected"]["rule_id"] == "test-oxygen"
    assert [action["id"] for action in entry["actions"]] == ["MineralDeoxidizer"]
    assert entry["rule_cooldowns"] == {"test-oxygen": 10}


def test_basic_survival_rule_dry_run_does_not_send_and_keeps_cooldown(
    tmp_path, monkeypatch
):
    state = _rule_test_state()
    state["dupes"] = [{"name": "Fixture Dupe", "x": 0, "y": -19}]
    state["resources"]["materials"]["Algae"] = 1000
    catalog = json.loads(
        (Path(__file__).parent / "fixtures" / "construction_skills_catalog.json")
        .read_text(encoding="utf-8")
    )
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _root: state)
    monkeypatch.setattr(agent_main, "load_catalog", lambda _root: catalog)
    monkeypatch.setattr(
        agent_main, "load_agent_config", lambda _path: _run_skill_config()
    )
    monkeypatch.setattr(agent_main, "load_rules", _one_basic_survival_rule)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not send basic-survival actions")
        ),
    )

    assert agent_main.run(
        ["--dry-run", "--max-steps", "1", "--manager", "none"]
    ) == 0

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["selection_reason"] == "rule_engine"
    assert entry["rule_evaluation"]["selected"]["rule_id"] == "test-basic-survival"
    assert [action["id"] for action in entry["actions"]] == ["MineralDeoxidizer"]
    assert entry["rule_cooldowns"] == {"test-basic-survival": 10}


def test_rule_pending_blocks_resent_build_actions(tmp_path, monkeypatch):
    state = _rule_test_state()
    catalog = json.loads(
        (Path(__file__).parent / "fixtures" / "construction_skills_catalog.json")
        .read_text(encoding="utf-8")
    )
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _root: state)
    monkeypatch.setattr(agent_main, "load_catalog", lambda _root: catalog)
    monkeypatch.setattr(agent_main, "load_agent_config", lambda _path: _run_skill_config())
    monkeypatch.setattr(agent_main, "load_rules", _one_oxygen_rule)
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    monkeypatch.setattr(
        agent_main,
        "next_step",
        lambda *args, **kwargs: {"goal_id": "no_goal", "actions": [], "skipped": []},
    )
    sent = []

    def accept_actions(actions, _root):
        sent.append(list(actions))
        return {"results": [{"type": action["type"], "ok": True} for action in actions]}

    monkeypatch.setattr(agent_main, "send_command", accept_actions)

    assert agent_main.run(
        ["--max-steps", "2", "--manager", "none"]
    ) == 0

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(sent) == 1
    assert sent[0][0]["id"] == "MineralDeoxidizer"
    assert entries[1]["rule_evaluation"]["reasons"][0]["reason"] == "pending"


def test_gemini_goal_plan_controls_planner_and_is_cached_by_cycle(tmp_path, monkeypatch):
    state = {
        "cycle": 10,
        "dupes": [],
        "resources": {"food_kcal": 10000},
        "oxygen_air": 1000,
        "alerts": [],
    }
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _root: state)
    monkeypatch.setattr(agent_main, "load_catalog", lambda _root: [])
    monkeypatch.setattr(agent_main, "load_agent_config", lambda _path: _run_skill_config())
    monkeypatch.setattr(agent_main, "load_rules", lambda: {"phases": [], "rules": []})
    monkeypatch.setattr(agent_main, "time", _no_sleep_time())
    manager_calls = []

    def gemini_plan(_state, goals):
        manager_calls.append(goals)
        return [{"id": "barracks", "horizon_cycles": 5}]

    monkeypatch.setattr(agent_main, "plan_goals", gemini_plan)
    planner_calls = []

    def next_step(state, catalog, config, pending, *, enabled_goals, alternatives):
        planner_calls.append((list(enabled_goals), dict(config["goal_ranks"])))
        return {
            "goal_id": "barracks",
            "actions": [{"type": "set_research", "tech": "FixtureTech"}],
            "skipped": [],
        }

    monkeypatch.setattr(agent_main, "next_step", next_step)
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not send manager-selected actions")
        ),
    )

    assert agent_main.run(
        [
            "--dry-run",
            "--max-steps",
            "2",
            "--manager",
            "gemini",
            "--interval-seconds",
            "0.001",
        ]
    ) == 0

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(manager_calls) == 1
    assert planner_calls == [(["barracks"], {"barracks": 0})] * 2
    assert all(entry["selection_reason"] == "gemini" for entry in entries)
    assert all(entry["manager_plan"][0]["horizon_cycles"] == 5 for entry in entries)
