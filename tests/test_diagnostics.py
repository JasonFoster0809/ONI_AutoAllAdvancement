import json

from agent.diagnostics import diagnose


def _entry(cycle, oxygen, stress, algae, progress, blocked=False):
    action = {"type": "build", "id": "FixtureBuilding", "x": 4, "y": 5}
    result = {
        "reason": "command_result",
        "results": [
            {"type": "build", "ok": False, "reason": "blocked"}
            if blocked
            else {"type": "build", "ok": True, "reason": "ok"}
        ],
    }
    return {
        "state": {
            "cycle": cycle,
            "oxygen_g": oxygen,
            "max_stress": stress,
            "algae_kg": algae,
            "research_active": "FixtureTech",
            "research_progress": progress,
        },
        "actions": [action],
        "result": result,
    }


def test_diagnostics_detect_stall_signals_from_logs_and_current_state(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    entries = [
        _entry(1, 200, 30, 2, 0.1, blocked=True),
        _entry(2, 150, 40, 1, 0.1, blocked=True),
        _entry(3, 100, 50, 0, 0.1),
    ]
    log_path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )
    state = {
        "cycle": 4,
        "environment": {"oxygen_avg_g": 80},
        "dupes": [{"stress": 60}],
        "building_list": [
            {"id": "MineralDeoxidizer", "state": "built", "stored": []}
        ],
        "research": {
            "active": "FixtureTech",
            "techs": [{"id": "FixtureTech", "cost": [{"required": 10, "current": 1}]}],
        },
    }

    report = diagnose(log_path, state)

    assert "Stress steigt in mindestens drei aufeinanderfolgenden Messungen | increasing" in report
    assert "Sauerstoff sinkt in mindestens drei aufeinanderfolgenden Messungen | falling" in report
    assert "Algae im MineralDeoxidizer-Speicher | 0 kg" in report
    assert "Wiederholt blockierte Bauaufträge (gleiche ID/Koordinate, mindestens zweimal) | 1" in report
    assert "Forschungsfortschritt unverändert in mindestens drei Messungen | stalled" in report
    assert "FixtureBuilding" in report


def test_diagnostics_mark_missing_historical_data_unknown(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text('{"state":{"cycle":1}}\n', encoding="utf-8")

    report = diagnose(log_path, {"cycle": 2})

    assert " | unknown" in report
    assert "Death causality is not inferable" in report


def test_diagnostics_reports_malformed_lines_without_stopping(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text('not-json\n{"state":{"cycle":1}}\n', encoding="utf-8")

    report = diagnose(log_path, {"cycle": 2})

    assert "Line 1: invalid JSON" in report
    assert "Agent log entries read: 1" in report
