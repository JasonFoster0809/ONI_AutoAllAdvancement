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


def choose_action(
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout: float = 10.0,
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

    safe_no_op = dict(candidate_by_id.get("no_op", NO_OP))
    if not candidate_by_id:
        LOGGER.warning("No action candidates; using safe no-op")
        return safe_no_op

    prompt_data = {
        "state": state,
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
            "options": {"temperature": 0},
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
