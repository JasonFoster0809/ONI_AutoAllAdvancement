import json
import socket

from agent.gemini_manager import (
    DEFAULT_MODEL,
    main,
    plan_goals,
    validate_goal_plan,
)


AVAILABLE_GOALS = [
    {"id": "research_target", "description": "Choose a ready research target"},
    {"id": "barracks", "description": "Build an enclosed sleeping room"},
]


class MockResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def gemini_response(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_request_sends_only_summary_and_validates_allowlisted_goals(monkeypatch):
    captured = {}
    plan = {"goals": [{"id": "barracks", "horizon_cycles": 7}]}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("X-goog-api-key")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return MockResponse(gemini_response(json.dumps(plan)))

    monkeypatch.setattr("agent.gemini_manager.urllib.request.urlopen", fake_urlopen)
    result = plan_goals(
        {
            "cycle": 12,
            "dupes": [{"name": "Fixture", "stress": 20}],
            "world": {"map": ["large"]},
            "building_list": [{"id": "excluded"}],
        },
        AVAILABLE_GOALS,
        api_key="fixture-secret",
    )

    assert result == plan["goals"]
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{DEFAULT_MODEL}:generateContent"
    )
    assert captured["key"] == "fixture-secret"
    assert "fixture-secret" not in captured["url"]
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["responseJsonSchema"]["required"] == ["goals"]
    prompt = json.loads(captured["body"]["contents"][0]["parts"][0]["text"])
    assert prompt["state_summary"] == {"cycle": 12, "dupe_count": 1}
    assert [goal["id"] for goal in prompt["available_goals"]] == [
        "research_target",
        "barracks",
    ]
    assert captured["timeout"] == 30.0
    assert "world" not in json.dumps(prompt)


def test_goal_schema_rejects_unknown_extra_duplicate_and_out_of_range_data():
    assert validate_goal_plan(
        {"goals": [{"id": "research_target", "horizon_cycles": 5}]},
        {"research_target"},
    ) == [{"id": "research_target", "horizon_cycles": 5}]
    assert validate_goal_plan({"goals": []}, {"research_target"}) == []
    assert validate_goal_plan(
        {"goals": [{"id": "not_allowed", "horizon_cycles": 5}]},
        {"research_target"},
    ) is None
    assert validate_goal_plan(
        {"goals": [{"id": "research_target", "horizon_cycles": 4}]},
        {"research_target"},
    ) is None
    assert validate_goal_plan(
        {"goals": [{"id": "research_target", "horizon_cycles": True}]},
        {"research_target"},
    ) is None
    assert validate_goal_plan(
        {"goals": [
            {"id": "research_target", "horizon_cycles": 5},
            {"id": "research_target", "horizon_cycles": 6},
        ]},
        {"research_target"},
    ) is None
    assert validate_goal_plan(
        {"goals": [{"id": "research_target", "horizon_cycles": 5, "action": "build"}]},
        {"research_target"},
    ) is None
    assert validate_goal_plan({"goals": [], "actions": []}, set()) is None


def test_mock_mode_never_uses_network_and_accepts_explicit_fixture(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("mock mode must not make a network request")

    monkeypatch.setattr("agent.gemini_manager.urllib.request.urlopen", unexpected_call)
    assert plan_goals({}, AVAILABLE_GOALS, mock=True) == [
        {"id": "research_target", "horizon_cycles": 5}
    ]
    assert plan_goals(
        {},
        AVAILABLE_GOALS,
        mock=True,
        mock_response='{"goals":[{"id":"barracks","horizon_cycles":10}]}',
    ) == [{"id": "barracks", "horizon_cycles": 10}]
    assert plan_goals({}, AVAILABLE_GOALS, mock=True, mock_response="{bad") is None


def test_missing_key_skips_request_without_logging_key(monkeypatch, caplog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def unexpected_call(*args, **kwargs):
        raise AssertionError("missing key must skip network")

    monkeypatch.setattr("agent.gemini_manager.urllib.request.urlopen", unexpected_call)
    assert plan_goals({}, AVAILABLE_GOALS) is None
    assert "GEMINI_API_KEY is not set" in caplog.text


def test_invalid_response_and_network_errors_are_skipped(monkeypatch, caplog):
    monkeypatch.setattr(
        "agent.gemini_manager.urllib.request.urlopen",
        lambda request, timeout: MockResponse(gemini_response('{"goals":[{"id":"bad"}]}')),
    )
    assert plan_goals({}, AVAILABLE_GOALS, api_key="not-logged") is None
    assert "not-logged" not in caplog.text

    def timeout(*args, **kwargs):
        raise socket.timeout("fixture timeout")

    monkeypatch.setattr("agent.gemini_manager.urllib.request.urlopen", timeout)
    assert plan_goals({}, AVAILABLE_GOALS, api_key="not-logged") is None
    assert "not-logged" not in caplog.text


def test_module_mock_cli_runs_without_a_key_or_network(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert main(["--mock"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "goals": [{"id": "research_target", "horizon_cycles": 5}]
    }
