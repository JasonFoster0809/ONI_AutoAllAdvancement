"""Rate-limited, goal-only strategy proposals from configured LLM providers."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote


LOGGER = logging.getLogger(__name__)
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


class GoalProvider(Protocol):
    def generate(self, prompt: Mapping[str, Any], *, timeout: float) -> str:
        """Return the raw JSON text generated for a goal-only prompt."""


@dataclass(frozen=True)
class StrategyDecision:
    goals: tuple[dict[str, Any], ...]
    status: str
    requested: bool


class StrategyResponseError(ValueError):
    """Raised when an LLM response does not satisfy the goal-plan contract."""


def _validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    provider = config.get("provider", "none")
    if not isinstance(provider, str) or provider not in {"none", "ollama", "gemini"}:
        raise ValueError("strategist.provider must be none, ollama, or gemini")
    interval = config.get("interval_cycles", 3)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("strategist.interval_cycles must be a positive integer")
    max_goals = config.get("max_goals", 3)
    if isinstance(max_goals, bool) or not isinstance(max_goals, int) or max_goals <= 0:
        raise ValueError("strategist.max_goals must be a positive integer")
    timeout = config.get("timeout_seconds", 60.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ValueError("strategist.timeout_seconds must be greater than 0 and at most 60")
    retries = config.get("retry_attempts", 2)
    if isinstance(retries, bool) or not isinstance(retries, int) or not 1 <= retries <= 5:
        raise ValueError("strategist.retry_attempts must be between 1 and 5")
    backoff = config.get("backoff_seconds", 0.5)
    if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) or not 0 <= backoff <= 10:
        raise ValueError("strategist.backoff_seconds must be between 0 and 10")
    gemini_model = config.get("gemini_model")
    if gemini_model is not None and (
        not isinstance(gemini_model, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]+", gemini_model)
    ):
        raise ValueError("strategist.gemini_model must be a configured model name or null")
    return {
        **config,
        "provider": provider,
        "interval_cycles": interval,
        "max_goals": max_goals,
        "timeout_seconds": float(timeout),
        "retry_attempts": retries,
        "backoff_seconds": float(backoff),
        "gemini_model": gemini_model,
    }


def summarize_strategy_state(
    state: Mapping[str, Any],
    score: Mapping[str, Any] | None,
    lessons: Sequence[Mapping[str, Any]],
    active_goal: str | None,
) -> dict[str, Any]:
    """Create a small allowlisted summary; never forward map or raw building data."""
    summary: dict[str, Any] = {}
    cycle = state.get("cycle")
    if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle >= 0:
        summary["cycle"] = cycle
    dupes = state.get("dupes")
    if isinstance(dupes, list):
        summary["dupe_count"] = len(dupes)
    resources = state.get("resources")
    if isinstance(resources, Mapping):
        food = resources.get("food_kcal")
        if isinstance(food, (int, float)) and not isinstance(food, bool):
            summary["food_kcal"] = food
    environment = state.get("environment")
    if isinstance(environment, Mapping):
        oxygen = environment.get("oxygen_avg_g")
        temperature = environment.get("temperature_avg_k")
        if isinstance(oxygen, (int, float)) and not isinstance(oxygen, bool):
            summary["oxygen_avg_g"] = oxygen
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            summary["temperature_avg_k"] = temperature
    if isinstance(dupes, list):
        stress_values = [
            item.get("stress")
            for item in dupes
            if isinstance(item, Mapping)
            and isinstance(item.get("stress"), (int, float))
            and not isinstance(item.get("stress"), bool)
        ]
        if stress_values:
            summary["max_stress"] = max(stress_values)
    if isinstance(score, Mapping):
        score_summary = {
            key: score[key]
            for key in ("total", "known_components", "unknown_components")
            if key in score
        }
        if score_summary:
            summary["score"] = score_summary
    recent_lessons = []
    for lesson in lessons[-3:]:
        if not isinstance(lesson, Mapping):
            continue
        recent_lessons.append(
            {
                key: lesson[key]
                for key in ("incident_type", "last_cycle", "occurrences")
                if key in lesson
            }
        )
    if recent_lessons:
        summary["recent_lessons"] = recent_lessons
    summary["active_goal"] = active_goal
    return summary


def _available_goals(
    goals: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    allowed: list[dict[str, str]] = []
    seen: set[str] = set()
    for goal in goals:
        goal_id, description = goal.get("id"), goal.get("description")
        if not isinstance(goal_id, str) or not goal_id:
            raise ValueError("available planner goals require non-empty IDs")
        if not isinstance(description, str) or not description:
            raise ValueError("available planner goals require descriptions")
        if goal_id in seen:
            raise ValueError(f"duplicate available planner goal: {goal_id}")
        seen.add(goal_id)
        allowed.append({"id": goal_id, "description": description})
    return allowed


def validate_strategy_response(
    response: Any,
    allowed_goal_ids: set[str],
    *,
    max_goals: int,
) -> list[dict[str, Any]]:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError as error:
            raise StrategyResponseError("response is not valid JSON") from error
    if not isinstance(response, Mapping) or set(response) != {"goals"}:
        raise StrategyResponseError("response must contain only a goals array")
    goals = response.get("goals")
    if not isinstance(goals, list):
        raise StrategyResponseError("goals must be an array")
    if len(goals) > max_goals:
        raise StrategyResponseError("goal count exceeds configured limit")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in goals:
        if not isinstance(item, Mapping) or set(item) != {"id", "horizon_cycles", "reason"}:
            raise StrategyResponseError("each goal must have id, horizon_cycles, and reason only")
        goal_id = item.get("id")
        horizon = item.get("horizon_cycles")
        reason = item.get("reason")
        if not isinstance(goal_id, str) or goal_id not in allowed_goal_ids:
            raise StrategyResponseError("response contains an unknown goal ID")
        if goal_id in seen:
            raise StrategyResponseError("response contains a duplicate goal ID")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise StrategyResponseError("horizon_cycles must be a positive integer")
        if not isinstance(reason, str) or not reason.strip():
            raise StrategyResponseError("reason must be a non-empty string")
        seen.add(goal_id)
        parsed.append(
            {"id": goal_id, "horizon_cycles": horizon, "reason": reason.strip()}
        )
    return parsed


class OllamaGoalProvider:
    """Goal-only Ollama provider using the configured local model."""

    def __init__(
        self,
        *,
        model: str = "qwen2.5-coder:3b",
        endpoint: str = OLLAMA_ENDPOINT,
    ) -> None:
        if not isinstance(model, str) or not model:
            raise ValueError("strategist Ollama model must be configured")
        self.model = model
        self.endpoint = endpoint

    def generate(self, prompt: Mapping[str, Any], *, timeout: float) -> str:
        request_data = json.dumps(
            {
                "model": self.model,
                "prompt": json.dumps(prompt, ensure_ascii=False),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("response") if isinstance(payload, Mapping) else None
        if not isinstance(raw, str):
            raise StrategyResponseError("Ollama response has no JSON response string")
        return raw


class GeminiGoalProvider:
    """Gemini provider; model is mandatory configuration and key is env-only."""

    def __init__(self, *, model: str, api_key: str | None = None) -> None:
        if not isinstance(model, str) or not model:
            raise ValueError("strategist Gemini model must be configured")
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")

    def generate(self, prompt: Mapping[str, Any], *, timeout: float) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        schema = {
            "type": "OBJECT",
            "properties": {
                "goals": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "id": {"type": "STRING"},
                            "horizon_cycles": {"type": "INTEGER"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["id", "horizon_cycles", "reason"],
                    },
                }
            },
            "required": ["goals"],
        }
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0,
            },
        }
        request = urllib.request.Request(
            f"{GEMINI_ENDPOINT}/{quote(self.model, safe='')}:generateContent",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candidates = payload.get("candidates") if isinstance(payload, Mapping) else None
        try:
            text = candidates[0]["content"]["parts"][0]["text"]
        except (IndexError, KeyError, TypeError) as error:
            raise StrategyResponseError("Gemini response has no text candidate") from error
        if not isinstance(text, str):
            raise StrategyResponseError("Gemini response text is not a string")
        return text


def create_goal_provider(config: Mapping[str, Any]) -> GoalProvider | None:
    provider = config.get("provider", "none")
    if provider == "none":
        return None
    if provider == "ollama":
        return OllamaGoalProvider(
            model=config.get("ollama_model", "qwen2.5-coder:3b"),
            endpoint=config.get("ollama_endpoint", OLLAMA_ENDPOINT),
        )
    if provider == "gemini":
        model = config.get("gemini_model")
        if not isinstance(model, str) or not model:
            raise ValueError("strategist.gemini_model must be configured for Gemini")
        return GeminiGoalProvider(model=model)
    raise ValueError("unsupported strategist provider")


class Strategist:
    """Request bounded goal rankings at a configured cycle cadence."""

    def __init__(
        self,
        config: Mapping[str, Any],
        provider: GoalProvider | None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = _validate_config(config)
        self.provider = provider
        self.sleeper = sleeper
        self.last_attempt_cycle: int | None = None
        self.cached: StrategyDecision | None = None

    def advise(
        self,
        *,
        cycle: int | None,
        state: Mapping[str, Any],
        score: Mapping[str, Any] | None,
        lessons: Sequence[Mapping[str, Any]],
        active_goal: str | None,
        available_goals: Sequence[Mapping[str, Any]],
        rules: Sequence[Mapping[str, Any]] = (),
    ) -> StrategyDecision | None:
        if self.config["provider"] == "none":
            return None
        if self.provider is None or cycle is None:
            LOGGER.warning("Strategist unavailable without provider or current cycle; using no-op")
            return StrategyDecision((), "unavailable", False)
        if self.last_attempt_cycle is not None and (
            cycle - self.last_attempt_cycle < self.config["interval_cycles"]
        ):
            if self.cached is None:
                return StrategyDecision((), "not_due", False)
            return StrategyDecision(self.cached.goals, self.cached.status, False)

        self.last_attempt_cycle = cycle
        try:
            goals = _available_goals(available_goals)
        except ValueError as error:
            LOGGER.warning("Strategist goal list invalid; using no-op (%s)", type(error).__name__)
            self.cached = StrategyDecision((), "invalid_goals", True)
            return self.cached
        prompt = {
            "state_summary": summarize_strategy_state(state, score, lessons, active_goal),
            "available_goals": goals,
            "rule_context": [
                {
                    key: rule[key]
                    for key in ("id", "priority", "then")
                    if key in rule
                }
                for rule in rules
                if isinstance(rule, Mapping)
            ],
            "instruction": (
                "Return only JSON {\"goals\":[{\"id\":\"...\",\"horizon_cycles\":N,"
                "\"reason\":\"...\"}]}. Select only available_goals IDs. "
                "Do not return actions or create game commands."
            ),
        }
        allowed = {goal["id"] for goal in goals}
        last_error: Exception | None = None
        for attempt in range(self.config["retry_attempts"]):
            try:
                raw = self.provider.generate(
                    prompt,
                    timeout=self.config["timeout_seconds"],
                )
                parsed = validate_strategy_response(
                    raw,
                    allowed,
                    max_goals=self.config["max_goals"],
                )
                self.cached = StrategyDecision(tuple(parsed), "ok", True)
                return self.cached
            except (
                json.JSONDecodeError,
                StrategyResponseError,
                TypeError,
                ValueError,
                urllib.error.HTTPError,
                urllib.error.URLError,
                socket.timeout,
                TimeoutError,
                OSError,
                RuntimeError,
            ) as error:
                last_error = error
                if attempt + 1 < self.config["retry_attempts"]:
                    delay = self.config["backoff_seconds"] * (2**attempt)
                    if delay:
                        self.sleeper(delay)

        LOGGER.warning(
            "Strategist request failed; using no-op (%s)",
            type(last_error).__name__ if last_error else "unknown_error",
        )
        self.cached = StrategyDecision((), "provider_error", True)
        return self.cached
