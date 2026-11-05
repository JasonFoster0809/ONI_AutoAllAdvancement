import copy
import json
from pathlib import Path

from agent import agent_main
from sim_state import (
    algae_empty_sequence,
    high_stress_sequence,
    oxygen_sequence,
    unknown_sequence,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _run_simulation(states, tmp_path, monkeypatch):
    remaining = iter(copy.deepcopy(states))
    log_path = tmp_path / "logs" / "agent.jsonl"
    catalog = json.loads(
        (FIXTURES / "emergency_catalog.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(agent_main, "read_state", lambda _data_dir: next(remaining))
    monkeypatch.setattr(agent_main, "load_catalog", lambda _data_dir: catalog)
    monkeypatch.setattr(
        agent_main,
        "load_agent_config",
        lambda _path: dict(agent_main.DEFAULT_CONFIG),
    )
    monkeypatch.setattr(agent_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        agent_main,
        "send_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run simulation must not send commands")
        ),
    )

    assert agent_main.run(
        [
            "--dry-run",
            "--manager",
            "none",
            "--max-steps",
            str(len(states)),
            "--data-dir",
            str(tmp_path),
        ]
    ) == 0
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]


def test_simulated_sustained_oxygen_decline_triggers_build_plan(
    tmp_path, monkeypatch
):
    entries = _run_simulation(oxygen_sequence((45, 40, 35)), tmp_path, monkeypatch)

    assert entries[-1]["goal_id"] == "emergency"
    assert entries[-1]["result"]["reason"] == "dry_run"
    assert any(
        action.get("type") == "build"
        and action.get("id") == "MineralDeoxidizer"
        for action in entries[-1]["actions"]
    )


def test_simulated_oxygen_recovery_prevents_emergency(tmp_path, monkeypatch):
    entries = _run_simulation(oxygen_sequence((45, 60, 45)), tmp_path, monkeypatch)

    assert all(entry["goal_id"] != "emergency" for entry in entries)
    assert entries[-1]["rule_evaluation"]["selected"] is None


def test_simulated_empty_algae_warns_without_adding_second_machine(
    tmp_path, monkeypatch
):
    entries = _run_simulation(algae_empty_sequence(), tmp_path, monkeypatch)
    entry = entries[-1]

    assert entry["goal_id"] == "rule:deoxidizer-algae-empty"
    assert entry["actions"] == []
    assert any(
        item.get("reason") == "skill_planned_no_actions"
        for item in entry["skipped"]
    )


def test_simulated_high_stress_lowers_job_priorities(tmp_path, monkeypatch):
    entries = _run_simulation(high_stress_sequence(), tmp_path, monkeypatch)

    assert entries[-1]["goal_id"] == "emergency"
    assert any(
        action.get("type") == "set_dupe_priority"
        and action.get("group") in {"Dig", "Build"}
        and action.get("priority") == 2
        for action in entries[-1]["actions"]
    )


def test_simulated_missing_telemetry_remains_unknown(tmp_path, monkeypatch):
    entries = _run_simulation(unknown_sequence(), tmp_path, monkeypatch)
    entry = entries[-1]

    assert entry["goal_id"] != "emergency"
    assert entry["rule_evaluation"]["selected"] is None
    assert any(item["status"] == "unknown" for item in entry["rule_evaluation"]["reasons"])
