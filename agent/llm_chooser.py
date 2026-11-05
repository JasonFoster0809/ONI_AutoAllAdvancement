"""Constrained action selection through a local Ollama endpoint."""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any


LOGGER = logging.getLogger(__name__)
DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:3b"
NO_OP = {"id": "no_op", "category": "no_op", "actions": []}
_OMITTED_STATE_KEYS = frozenset({"map", "building_list", "research", "achievements"})


def _sanitize_summary_value(value: Any) -> Any:
    """Copy JSON-like summary values without including large/excluded sections."""
    if isinstance(value, Mapping):
        return {
            key: _sanitize_summary_value(item)
            for key, item in value.items()
            if not isinstance(key, str) or key not in _OMITTED_STATE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_summary_value(item) for item in value]
    return value


def _summarize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Extract a compact set of colony facts for the LLM prompt."""
    summary: dict[str, Any] = {}
    try:
        if "cycle" in state:
            summary["cycle"] = _sanitize_summary_value(state["cycle"])
    except Exception as error:
        LOGGER.warning("Could not summarize cycle: %s", error)

    try:
        dupes = state.get("dupes")
        if isinstance(dupes, list):
            summary["dupe_count"] = len(dupes)
    except Exception as error:
        LOGGER.warning("Could not summarize dupe count: %s", error)

    try:
        if "oxygen_air" in state:
            summary["oxygen_air"] = _sanitize_summary_value(state["oxygen_air"])
    except Exception as error:
        LOGGER.warning("Could not summarize oxygen_air: %s", error)

    try:
        resources = state.get("resources")
        if isinstance(resources, Mapping) and "food_kcal" in resources:
            summary["food_kcal"] = _sanitize_summary_value(resources["food_kcal"])
    except Exception as error:
        LOGGER.warning("Could not summarize food_kcal: %s", error)

    try:
        alerts = state.get("alerts")
        if isinstance(alerts, list):
            summary["alerts"] = _sanitize_summary_value(alerts[:10])
    except Exception as error:
        LOGGER.warning("Could not summarize alerts: %s", error)

    for section in ("environment", "power"):
        try:
            value = state.get(section)
            if isinstance(value, Mapping):
                summary[section] = _sanitize_summary_value(value)
        except Exception as error:
            LOGGER.warning("Could not summarize %s: %s", section, error)

    return summary


def choose_action(
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Ask Ollama to select one supplied candidate; failures return no-op."""
    candidate_by_id: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        candidate_id = candidate.get("id")
        actions = candidate.get("actions")
        if not isinstance(candidate_id, str) or not isinstance(actions, list):
            raise ValueError("each candidate requires a string id and actions list")
        if candidate_id in candidate_by_id:
            raise ValueError(f"duplicate candidate id: {candidate_id}")
        candidate_by_id[candidate_id] = candidate

    if "no_op" in candidate_by_id and candidate_by_id["no_op"]["actions"]:
        raise ValueError("the no_op candidate must have an empty actions list")
    safe_no_op = dict(candidate_by_id.get("no_op", NO_OP))
    if not candidate_by_id or not any(
        candidate["actions"] for candidate in candidate_by_id.values()
    ):
        LOGGER.warning("No action candidates; using safe no-op")
        return safe_no_op

    prompt_data = {
        "state": _summarize_state(state),
        "candidates": [
            {"id": candidate_id, "category": candidate.get("category"), "actions": candidate["actions"]}
            for candidate_id, candidate in candidate_by_id.items()
        ],
        "instruction": "Choose exactly one candidate id. Return only a JSON object with one string field named id.",
    }
    request_data = json.dumps(
        {
            "model": model,
            "prompt": json.dumps(prompt_data, ensure_ascii=False),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "num_predict": 40},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=request_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            ollama_result = json.loads(response.read().decode("utf-8"))
        raw_choice = ollama_result.get("response")
        if not isinstance(raw_choice, str):
            raise ValueError("Ollama response has no JSON response string")
        parsed_choice = json.loads(raw_choice)
        chosen_id = parsed_choice.get("id")
        if not isinstance(chosen_id, str) or chosen_id not in candidate_by_id:
            raise ValueError("Ollama selected an id outside the candidate list")
        return dict(candidate_by_id[chosen_id])
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
        LOGGER.warning("Ollama action selection failed; using safe no-op: %s", error)
        return safe_no_op
