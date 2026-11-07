import json

from agent.log_summary import format_summary, main


def test_summary_reports_only_latest_run_in_eight_lines(tmp_path):
    log_path = tmp_path / "agent.jsonl"
    entries = [
        {
            "step": 1,
            "goal_id": "old-goal",
            "actions": [{"type": "build"}],
            "skipped": [],
            "state": {"cycle": 1},
        },
        {
            "step": 2,
            "goal_id": "old-goal",
            "actions": [],
            "skipped": [],
            "state": {"cycle": 2},
        },
        {
            "step": 1,
            "timestamp": "2026-11-07T10:00:00+00:00",
            "goal_id": "mine_metal_ore",
            "actions": [{"type": "dig"}, {"type": "dig"}],
            "skipped": [{"goal_id": "barracks", "reason": "no_placement"}],
            "rule_evaluation": {"selected": {"rule_id": "low-oxygen-setup"}},
            "state": {
                "cycle": 12,
                "oxygen_g": 48,
                "food_kcal": 9000,
                "dupe_count": 4,
                "building_count": 7,
            },
        },
        {
            "step": 2,
            "timestamp": "2026-11-07T10:00:02+00:00",
            "goal_id": "research_center_setup",
            "actions": [{"type": "build"}],
            "skipped": [{"goal_id": "mine_metal_ore", "reason": "pending"}],
            "rule_id": "growth-water-setup",
            "state": {
                "cycle": 12,
                "oxygen_air": 48,
                "food_kcal": 9000,
                "dupe_count": 4,
                "building_count": 7,
            },
        },
    ]
    log_path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    report = format_summary(log_path)

    assert len(report.splitlines()) == 8
    assert "2 bước (step 1-2)" in report
    assert "Goal cuối: research_center_setup" in report
    assert "Actions: 3 tổng, 1 ở bước cuối" in report
    assert "Skipped: 2" in report
    assert "no_placement" in report
    assert "pending" in report
    assert "cycle=12" in report
    assert "oxy=48 g" in report
    assert "food=9000 kcal" in report
    assert "Dupes: 4; buildings: 7" in report
    assert "low-oxygen-setup, growth-water-setup" in report
    assert "old-goal" not in report


def test_summary_cli_uses_given_log_path(tmp_path, capsys):
    log_path = tmp_path / "agent.jsonl"
    log_path.write_text(
        json.dumps({"step": 1, "goal_id": "no_goal", "actions": []}) + "\n",
        encoding="utf-8",
    )

    assert main(["--logs", str(log_path)]) == 0

    assert len(capsys.readouterr().out.splitlines()) == 8
