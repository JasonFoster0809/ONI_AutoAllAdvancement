import json
import socket

from agent.llm_chooser import _summarize_state, choose_action


class MockResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def candidates():
    return [
        {"id": "no_op", "category": "no_op", "actions": []},
        {"id": "dig", "category": "dig", "actions": [{"type": "dig", "x": 1, "y": 2}]},
    ]


def test_llm_selects_only_supplied_candidate(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return MockResponse({"response": json.dumps({"id": "dig"})})

    monkeypatch.setattr("agent.llm_chooser.urllib.request.urlopen", fake_urlopen)
    selected = choose_action({"cycle": 1}, candidates())
    assert selected["id"] == "dig"
    assert captured["body"]["model"] == "qwen2.5-coder:3b"
    assert captured["body"]["options"]["temperature"] == 0
    assert captured["body"]["options"]["num_predict"] == 40
    prompt_data = json.loads(captured["body"]["prompt"])
    assert prompt_data["state"] == {"cycle": 1}
    assert captured["timeout"] == 60.0


def test_summarize_state_omits_large_sections_and_limits_alerts():
    state = {
        "cycle": 42,
        "dupes": [{"name": f"dupe-{index}"} for index in range(3)],
        "oxygen_air": 123.5,
        "resources": {"food_kcal": 4567, "materials": {"Sand": 100000}},
        "alerts": [{"type": f"alert-{index}"} for index in range(12)],
        "environment": {"temperature_avg_k": 295, "map": ["large"] * 1000},
        "power": {"watts_used": 20},
        "world": {"map": ["large"] * 10000},
        "building_list": [{"id": "LargeBuildingList"}],
        "research": {"techs": [{"id": "LargeResearchList"}]},
        "achievements": [{"id": "LargeAchievementList"}],
    }

    summary = _summarize_state(state)
    encoded = json.dumps(summary)

    assert summary["cycle"] == 42
    assert summary["dupe_count"] == 3
    assert summary["oxygen_air"] == 123.5
    assert summary["food_kcal"] == 4567
    assert len(summary["alerts"]) == 10
    assert summary["environment"] == {"temperature_avg_k": 295}
    assert summary["power"] == {"watts_used": 20}
    assert "map" not in encoded
    assert "building_list" not in encoded
    assert "research" not in encoded
    assert "achievements" not in encoded
    assert len(encoded) < 2000


def test_invalid_json_and_unknown_id_fall_back_to_noop(monkeypatch):
    monkeypatch.setattr(
        "agent.llm_chooser.urllib.request.urlopen",
        lambda request, timeout: MockResponse({"response": "{broken"}),
    )
    assert choose_action({}, candidates())["id"] == "no_op"

    monkeypatch.setattr(
        "agent.llm_chooser.urllib.request.urlopen",
        lambda request, timeout: MockResponse({"response": '{"id":"not_allowed"}'}),
    )
    assert choose_action({}, candidates())["actions"] == []


def test_timeout_falls_back_to_noop(monkeypatch):
    def timeout(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr("agent.llm_chooser.urllib.request.urlopen", timeout)
    assert choose_action({}, candidates())["id"] == "no_op"


def test_empty_actions_do_not_call_ollama(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Ollama should not be called for an empty plan")

    monkeypatch.setattr("agent.llm_chooser.urllib.request.urlopen", unexpected_call)
    assert choose_action({}, [{"id": "no_op", "actions": []}])["id"] == "no_op"
