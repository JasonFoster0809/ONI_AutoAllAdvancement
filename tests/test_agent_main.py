import json

from agent import agent_main


def test_dry_run_writes_jsonl_without_sending(tmp_path, monkeypatch, capsys):
    (tmp_path / "oni_state.json").write_text(
        json.dumps({"cycle": 1, "dupes": [], "resources": {}, "world": {}}),
        encoding="utf-8",
    )
    (tmp_path / "oni_catalog.json").write_text("[]", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)
    monkeypatch.setattr(
        agent_main,
        "build_candidates",
        lambda *args, **kwargs: [
            {"id": "no_op", "category": "no_op", "actions": []},
            {
                "id": "test_dig",
                "category": "dig",
                "actions": [{"type": "dig", "x": 1, "y": 2}],
            },
        ],
    )
    monkeypatch.setattr(
        agent_main,
        "choose_action",
        lambda state, candidates: dict(candidates[1]),
    )
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
    assert entry["action_id"] == "test_dig"
    assert entry["result"]["reason"] == "dry_run"
    assert entry["result"]["actions"] == [{"type": "dig", "x": 1, "y": 2}]
    assert json.loads(capsys.readouterr().out)["step"] == 1
