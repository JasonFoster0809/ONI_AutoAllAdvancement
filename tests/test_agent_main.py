import json

from agent import agent_main


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

    assert agent_main.run(
        ["--max-steps", "1", "--data-dir", str(tmp_path)]
    ) == 0
    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["goal_id"] == "emergency"
    assert entry["selection_reason"] == "rule"
    assert entry["result"]["reason"] == "low_oxygen"
