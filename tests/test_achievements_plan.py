from agent.achievements_plan import (
    AchievementPlanError,
    achievement_rows,
    load_plan,
    main,
    render_report,
    strategist_context,
)


def test_missing_achievement_fields_remain_unknown():
    rows = achievement_rows({})

    assert len(rows) == 51
    assert rows[0]["name"] == "TODO_VERIFY"
    assert rows[0]["achieved"] is None
    assert rows[0]["category"] == "chưa rõ"
    assert rows[0]["requirement"] == ""
    assert rows[0]["requires_dlc"] == "TODO_VERIFY"
    assert rows[0]["suggested_order"] == 1


def test_state_names_progress_and_achievements_are_merged_without_guessing():
    state = {
        "achievements": [
            {
                "id": "Thriving",
                "name": "Name from state",
                "achieved": True,
                "progress": ["Progress text from state"],
            },
            {"id": "ReachedSpace", "name": "Rocket name", "achieved": False},
        ]
    }

    rows = achievement_rows(state)
    by_id = {row["id"]: row for row in rows}

    assert by_id["Thriving"]["name"] == "Name from state"
    assert by_id["Thriving"]["category"] == "đã đạt"
    assert by_id["Thriving"]["suggested_order"] is None
    assert by_id["Thriving"]["progress"] == ["Progress text from state"]
    assert by_id["ReachedSpace"]["category"] == "chưa rõ"
    assert by_id["ReachedSpace"]["requires_rocket"] == "TODO_VERIFY"
    unachieved_orders = [
        row["suggested_order"] for row in rows if row["achieved"] is not True
    ]
    assert unachieved_orders == list(range(1, len(unachieved_orders) + 1))


def test_non_boolean_achieved_and_malformed_progress_are_unknown():
    rows = achievement_rows(
        {
            "achievements": [
                {"id": "Thriving", "name": "Observed", "achieved": "yes", "progress": "bad"}
            ]
        }
    )
    thriving = next(row for row in rows if row["id"] == "Thriving")

    assert thriving["achieved"] is None
    assert thriving["category"] == "chưa rõ"
    assert thriving["progress"] is None


def test_report_has_required_categories_and_does_not_infer_game_requirements():
    state = {
        "achievements": [
            {"id": "Thriving", "name": "Observed title", "achieved": True},
            {"id": "ReachedSpace", "name": "Rocket title", "achieved": False},
        ]
    }

    report = render_report(state)

    assert "đã đạt: 1" in report
    assert "làm được ở base game: 0" in report
    assert "cần DLC: 0" in report
    assert "cần tên lửa: 0" in report
    assert "chưa rõ: 50" in report
    assert "Observed title" in report
    assert "TODO_VERIFY" in report


def test_strategist_context_contains_only_goal_metadata_no_actions():
    goals = strategist_context(
        {
            "achievements": [
                {"id": "Thriving", "name": "Already completed", "achieved": True},
                {"id": "ReachedSpace", "name": "State title", "achieved": False},
            ]
        }
    )

    assert all("actions" not in goal for goal in goals)
    assert all(goal["id"] != "Thriving" for goal in goals)
    assert len(goals) == 1
    assert any(
        goal["id"] == "ReachedSpace"
        and goal["description"] == "State title"
        and goal["status"] == "chưa rõ"
        for goal in goals
    )


def test_strategist_context_omits_achievements_missing_from_state():
    goals = strategist_context({})

    assert goals == []


def test_plan_has_unique_ids_and_unverified_requirements_are_explicit():
    plan = load_plan()
    ids = [entry["id"] for entry in plan["entries"]]

    assert len(ids) == 51
    assert len(ids) == len(set(ids))
    assert plan["defaults"]["requirement_status"] == "TODO_VERIFY"
    assert plan["suggested_order"]["status"] == "TODO_VERIFY"


def test_verified_base_game_and_difficulty_sort_before_unverified_and_dlc():
    plan = load_plan()
    plan["entries"] = [
        {
            "id": "dlc",
            "base_game": False,
            "requires_dlc": True,
            "difficulty": 1,
        },
        {
            "id": "hard_base",
            "base_game": True,
            "requires_dlc": False,
            "requires_rocket": False,
            "difficulty": 5,
        },
        {
            "id": "rocket",
            "base_game": True,
            "requires_dlc": False,
            "requires_rocket": True,
            "difficulty": 2,
        },
        {
            "id": "easy_base",
            "base_game": True,
            "requires_dlc": False,
            "requires_rocket": False,
            "difficulty": 1,
        },
        {"id": "unknown"},
    ]
    state = {
        "achievements": [
            {"id": item["id"], "name": item["id"], "achieved": False}
            for item in plan["entries"]
        ]
    }

    rows = achievement_rows(state, plan)

    assert [row["id"] for row in rows] == [
        "easy_base",
        "hard_base",
        "rocket",
        "unknown",
        "dlc",
    ]
    assert rows[2]["category"] == "cần tên lửa"
    assert rows[-1]["category"] == "cần DLC"


def test_unknown_state_achievements_are_included_with_todo_metadata():
    rows = achievement_rows(
        {"achievements": [{"id": "NewGameAchievement", "name": "New title", "achieved": False}]}
    )
    new_entry = next(row for row in rows if row["id"] == "NewGameAchievement")

    assert new_entry["plan_entry_found"] is False
    assert new_entry["name"] == "New title"
    assert new_entry["requires_dlc"] == "TODO_VERIFY"
    assert new_entry["category"] == "chưa rõ"


def test_invalid_plan_file_fails_explicitly(tmp_path):
    invalid = tmp_path / "bad.yaml"
    invalid.write_text("not: [valid json", encoding="utf-8")

    try:
        load_plan(invalid)
    except AchievementPlanError as error:
        assert "achievement_plan_unavailable" in str(error)
    else:
        raise AssertionError("invalid plan must be reported")


def test_report_cli_reads_a_fixture_and_prints_table(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "oni_state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "agent.achievements_plan.read_state",
        lambda _root: {
            "achievements": [
                {"id": "Thriving", "name": "Fixture title", "achieved": True}
            ]
        },
    )

    assert main(["--report", "--data-dir", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "id" in output and "name" in output and "description" in output
    assert "Fixture title" in output
    assert "đã đạt: 1" in output


def test_report_output_reconfigures_windows_stream_to_utf8(monkeypatch):
    from agent.achievements_plan import _print_report

    calls = []

    class Output:
        encoding = "cp1252"

        def reconfigure(self, *, encoding):
            calls.append(encoding)

        def write(self, text):
            text.encode("utf-8")
            return len(text)

        def flush(self):
            return None

    monkeypatch.setattr("agent.achievements_plan.sys.stdout", Output())

    _print_report("đã đạt")

    assert calls == ["utf-8"]
