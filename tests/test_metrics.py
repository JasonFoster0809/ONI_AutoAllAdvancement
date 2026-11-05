import json
from datetime import datetime, timedelta, timezone

from agent import agent_main
from agent.metrics import calculate_metrics


def test_metrics_calculate_commands_cycles_elapsed_time_and_live_dupes(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    first = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
    entries = [
        {
            "timestamp": first.isoformat(),
            "state": {"cycle": 7, "dupe_count": 3},
            "result": {
                "results": [
                    {"type": "build", "ok": True, "reason": "ok"},
                    {"type": "build", "ok": False, "reason": "blocked"},
                ]
            },
        },
        {
            "timestamp": (first + timedelta(seconds=40)).isoformat(),
            "state": {"cycle": 8, "dupe_count": 2},
            "result": {"results": [{"type": "dig", "ok": True, "reason": "ok"}]},
        },
    ]
    log_path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    metrics = calculate_metrics(log_path)

    assert metrics["cycle_survived_to"] == 8
    assert metrics["commands_ok"] == 2
    assert metrics["commands_blocked"] == 1
    assert metrics["average_seconds_per_cycle"] == 40
    assert metrics["dupes_alive"] == 2


def test_agent_report_command_writes_metrics_json(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "logs" / "agent.jsonl"
    log_path.parent.mkdir()
    log_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-11-06T00:00:00+00:00",
                "state": {"cycle": 9, "dupe_count": 1},
                "result": {"reason": "dry_run"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_main, "LOG_PATH", log_path)

    assert agent_main.run(["--report"]) == 0

    report_path = log_path.parent / "metrics.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cycle_survived_to"] == 9
    assert report["commands_ok"] == 0
    assert report["commands_blocked"] == 0
    assert json.loads(capsys.readouterr().out)["dupes_alive"] == 1


def test_metrics_report_unknown_elapsed_time_when_cycle_does_not_advance(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": f"2026-11-06T00:00:0{cycle}+00:00",
                    "state": {"cycle": 3, "dupe_count": 1},
                }
            )
            for cycle in (0, 1)
        ),
        encoding="utf-8",
    )

    metrics = calculate_metrics(log_path)

    assert metrics["average_seconds_per_cycle"] is None
