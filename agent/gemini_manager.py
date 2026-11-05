"""Schema-validated, goal-only planning through the Gemini REST API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from .llm_chooser import _summarize_state


LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GOALS = [
    {"id": "research_target", "description": "Choose a ready research target"}
]
GOAL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "horizon_cycles": {"type": "integer", "minimum": 5, "maximum": 10},
                },
                "required": ["id", "horizon_cycles"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["goals"],
    "additionalProperties": False,
}


def _available_goals(
    goals: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for goal in goals:
        if not isinstance(goal, Mapping):
            raise ValueError("available goals must be objects")
        goal_id = goal.get("id")
        description = goal.get("description")
        if (
            not isinstance(goal_id, str)
            or not goal_id
            or not isinstance(description, str)
            or not description
        ):
            raise ValueError("available goals require non-empty id and description")
        if goal_id in result:
            raise ValueError(f"duplicate available goal id: {goal_id}")
        result[goal_id] = description
    return result


def validate_goal_plan(
    value: Any,
    allowed_goal_ids: set[str],
) -> list[dict[str, Any]] | None:
    """Return a strictly validated list, or None when the response is invalid."""
    if not isinstance(value, Mapping) or set(value) != {"goals"}:
        return None
    goals = value.get("goals")
    if not isinstance(goals, list):
        return None

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in goals:
        if not isinstance(item, Mapping) or set(item) != {"id", "horizon_cycles"}:
            return None
        goal_id = item.get("id")
        horizon = item.get("horizon_cycles")
        if (
            not isinstance(goal_id, str)
            or goal_id not in allowed_goal_ids
            or goal_id in seen
            or isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or not 5 <= horizon <= 10
        ):
            return None
        seen.add(goal_id)
        validated.append({"id": goal_id, "horizon_cycles": horizon})
    return validated


def _mock_goal_plan(goal_ids: Sequence[str]) -> dict[str, Any]:
    if not goal_ids:
        return {"goals": []}
    return {"goals": [{"id": goal_ids[0], "horizon_cycles": 5}]}


def _goal_state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    summary = _summarize_state(state)
    return {
        key: summary[key]
        for key in ("cycle", "dupe_count", "oxygen_air", "food_kcal")
        if key in summary
    }


def _response_text(response: Any) -> str:
    if not isinstance(response, Mapping):
        raise ValueError("Gemini response must be an object")
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response has no candidates")
    content = candidates[0].get("content") if isinstance(candidates[0], Mapping) else None
    parts = content.get("parts") if isinstance(content, Mapping) else None
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], Mapping):
        raise ValueError("Gemini response has no text part")
    text = parts[0].get("text")
    if not isinstance(text, str):
        raise ValueError("Gemini response text is missing")
    return text


def plan_goals(
    state: Mapping[str, Any],
    available_goals: Sequence[Mapping[str, Any]],
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout: float = 30.0,
    mock: bool = False,
    mock_response: Any = None,
) -> list[dict[str, Any]] | None:
    """Ask Gemini for allow-listed goals; invalid or unavailable responses are skipped."""
    descriptions = _available_goals(available_goals)
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("model must contain only letters, digits, dot, underscore, or hyphen")
    allowed_ids = set(descriptions)

    if mock:
        response_value = _mock_goal_plan(list(descriptions)) if mock_response is None else mock_response
        if isinstance(response_value, str):
            try:
                response_value = json.loads(response_value)
            except json.JSONDecodeError:
                LOGGER.warning("Mock Gemini response is not valid JSON")
                return None
        result = validate_goal_plan(response_value, allowed_ids)
        if result is None:
            LOGGER.warning("Mock Gemini response failed goal-plan schema validation")
        return result

    key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
    if not isinstance(key, str) or not key:
        LOGGER.warning("Gemini manager skipped: GEMINI_API_KEY is not set")
        return None

    prompt = {
        "state_summary": _goal_state_summary(state),
        "available_goals": [
            {"id": goal_id, "description": description}
            for goal_id, description in descriptions.items()
        ],
        "instruction": (
            "Return a JSON object with a goals array. Select only supplied goal IDs. "
            "Each goal must have id and horizon_cycles from 5 through 10. "
            "Do not return actions or invent goals."
        ),
    }
    request_body = {
        "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": GOAL_PLAN_SCHEMA,
        },
    }
    endpoint = f"{DEFAULT_ENDPOINT}/{quote(model, safe='')}:generateContent"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_value = json.loads(response.read().decode("utf-8"))
        raw_text = _response_text(response_value)
        parsed = json.loads(raw_text)
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        OSError,
    ) as error:
        LOGGER.warning("Gemini manager request skipped (%s)", type(error).__name__)
        return None

    result = validate_goal_plan(parsed, allowed_ids)
    if result is None:
        LOGGER.warning("Gemini response failed goal-plan schema validation")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test the Gemini goal manager")
    parser.add_argument("--mock", action="store_true", help="use a local mock response without network access")
    parser.add_argument("--state-json", default="{}", help="JSON state object to summarize")
    parser.add_argument(
        "--goals-json",
        default=json.dumps(DEFAULT_GOALS),
        help="JSON array of available goal objects",
    )
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state_json)
        goals = json.loads(args.goals_json)
        if not isinstance(state, Mapping) or not isinstance(goals, list):
            raise ValueError("state-json must be an object and goals-json must be an array")
        result = plan_goals(state, goals, mock=args.mock)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"goals": result}, ensure_ascii=False))
    return 0 if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
