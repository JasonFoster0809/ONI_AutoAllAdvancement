import json

import pytest

from agent.strategist import (
    GeminiGoalProvider,
    OllamaGoalProvider,
    Strategist,
    StrategyResponseError,
    create_goal_provider,
    summarize_strategy_state,
    validate_strategy_response,
)


GOALS = [
    {"id": "research_target", "description": "Choose a ready research target"},
    {"id": "barracks", "description": "Build an enclosed sleeping room"},
]


class FakeProvider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate(self, prompt, *, timeout):
        self.calls.append((prompt, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def _strategy_config(**overrides):
    return {
        "provider": "ollama",
        "interval_cycles": 3,
        "max_goals": 2,
        "timeout_seconds": 60,
        "retry_attempts": 1,
        "backoff_seconds": 0,
        **overrides,
    }


def test_valid_plan_is_allowlisted_and_summary_is_compact():
    response = {
        "goals": [
            {
                "id": "barracks",
                "horizon_cycles": 4,
                "reason": "A sleeping room is not reported yet",
            }
        ]
    }
    provider = FakeProvider(json.dumps(response))
    strategist = Strategist(_strategy_config(), provider)

    decision = strategist.advise(
        cycle=3,
        state={
            "cycle": 3,
            "dupes": [{"stress": 20}, {"stress": 55}],
            "resources": {"food_kcal": 3000},
            "environment": {"oxygen_avg_g": 270},
            "map": ["large"],
            "building_list": [{"id": "private-detail"}],
        },
        score={"total": 12, "known_components": 2, "unknown_components": 1},
        lessons=[{"incident_type": "low_oxygen_persistent", "last_cycle": 2}],
        active_goal="research_target",
        available_goals=GOALS,
        rules=[{"id": "critical-dupe-hunger", "priority": 95}],
    )

    assert decision is not None
    assert decision.status == "ok"
    assert decision.goals == (
        {
            "id": "barracks",
            "horizon_cycles": 4,
            "reason": "A sleeping room is not reported yet",
        },
    )
    prompt, timeout = provider.calls[0]
    assert timeout == 60
    assert prompt["state_summary"]["max_stress"] == 55
    assert prompt["state_summary"]["recent_lessons"][0]["incident_type"] == (
        "low_oxygen_persistent"
    )
    assert [goal["id"] for goal in prompt["available_goals"]] == [
        "research_target",
        "barracks",
    ]
    assert prompt["rule_context"] == [
        {"id": "critical-dupe-hunger", "priority": 95}
    ]
    assert "map" not in json.dumps(prompt)
    assert "private-detail" not in json.dumps(prompt)


@pytest.mark.parametrize(
    "raw",
    [
        "{broken-json",
        '{"goals":[{"id":"unknown","horizon_cycles":3,"reason":"invented"}]}',
        (
            '{"goals":['
            '{"id":"research_target","horizon_cycles":3,"reason":"first"},'
            '{"id":"barracks","horizon_cycles":3,"reason":"second"},'
            '{"id":"third","horizon_cycles":3,"reason":"too many"}]}'
        ),
    ],
)
def test_invalid_json_unknown_id_and_excess_goals_return_no_op(raw, caplog):
    provider = FakeProvider(raw)
    strategist = Strategist(_strategy_config(max_goals=2), provider)

    decision = strategist.advise(
        cycle=0,
        state={},
        score=None,
        lessons=[],
        active_goal=None,
        available_goals=GOALS,
    )

    assert decision is not None
    assert decision.status == "provider_error"
    assert decision.goals == ()
    assert "using no-op" in caplog.text


def test_timeout_retries_with_backoff_then_returns_no_op():
    provider = FakeProvider(error=TimeoutError("fixture timeout"))
    delays = []
    strategist = Strategist(
        _strategy_config(retry_attempts=2, backoff_seconds=0.25),
        provider,
        sleeper=delays.append,
    )

    decision = strategist.advise(
        cycle=0,
        state={},
        score=None,
        lessons=[],
        active_goal=None,
        available_goals=GOALS,
    )

    assert decision is not None
    assert decision.status == "provider_error"
    assert not decision.goals
    assert len(provider.calls) == 2
    assert delays == [0.25]


def test_disabled_provider_is_noop_without_calling_provider():
    provider = FakeProvider("{}")
    strategist = Strategist({"provider": "none"}, provider)

    assert (
        strategist.advise(
            cycle=0,
            state={},
            score=None,
            lessons=[],
            active_goal=None,
            available_goals=GOALS,
        )
        is None
    )
    assert provider.calls == []


def test_plan_is_cached_and_provider_is_rate_limited_by_cycle():
    provider = FakeProvider(
        '{"goals":[{"id":"research_target","horizon_cycles":2,"reason":"ready"}]}'
    )
    strategist = Strategist(_strategy_config(), provider)
    kwargs = {
        "state": {},
        "score": None,
        "lessons": [],
        "active_goal": None,
        "available_goals": GOALS,
    }

    first = strategist.advise(cycle=1, **kwargs)
    cached = strategist.advise(cycle=2, **kwargs)
    refreshed = strategist.advise(cycle=4, **kwargs)

    assert first is not None and first.status == "ok"
    assert cached is not None and cached.goals == first.goals
    assert cached.requested is False
    assert refreshed is not None and refreshed.goals == first.goals
    assert refreshed.requested is True
    assert len(provider.calls) == 2


def test_response_validation_rejects_malformed_goal_fields():
    with pytest.raises(StrategyResponseError):
        validate_strategy_response(
            {"goals": [{"id": "research_target", "horizon_cycles": 2}]},
            {"research_target"},
            max_goals=2,
        )


def test_provider_configuration_does_not_guess_gemini_model(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="gemini_model must be configured"):
        create_goal_provider({"provider": "gemini", "gemini_model": None})


def test_gemini_api_key_is_only_sent_as_header_and_never_logged(monkeypatch, caplog):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": (
                                            '{"goals":[{"id":"research_target",'
                                            '"horizon_cycles":2,"reason":"ready"}]}'
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("X-goog-api-key")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("agent.strategist.urllib.request.urlopen", fake_urlopen)
    provider = GeminiGoalProvider(model="configured-model", api_key="private-fixture-key")
    raw = provider.generate({"available_goals": GOALS}, timeout=15)

    assert json.loads(raw)["goals"][0]["id"] == "research_target"
    assert captured["key"] == "private-fixture-key"
    assert "private-fixture-key" not in captured["url"]
    assert captured["timeout"] == 15
    assert "private-fixture-key" not in caplog.text


def test_ollama_provider_uses_json_format_temperature_zero_and_configured_timeout(
    monkeypatch,
):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"response": '{"goals":[]}'}).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("agent.strategist.urllib.request.urlopen", fake_urlopen)
    provider = OllamaGoalProvider(model="qwen2.5-coder:3b")

    assert provider.generate({"available_goals": GOALS}, timeout=60) == '{"goals":[]}'
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["temperature"] == 0
    assert captured["timeout"] == 60


def test_state_summary_handles_missing_fields():
    assert summarize_strategy_state({}, None, [], None) == {"active_goal": None}
