"""Client for the ONI mod's state, command, and result files."""

from __future__ import annotations

import json
import os
import threading
import time
import warnings
from itertools import count
from pathlib import Path
from typing import Any, Mapping, Sequence


DATA_DIR_ENV = "ONI_DATA_DIR"
DEFAULT_DATA_DIR = Path.home() / "Documents" / "Klei" / "OxygenNotIncluded"
_id_counter = count()
_id_lock = threading.Lock()


def get_data_dir(root: str | os.PathLike[str] | None = None) -> Path:
    """Return the configured ONI data directory."""
    if root is not None:
        return Path(root)
    configured = os.environ.get(DATA_DIR_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_DATA_DIR


def _new_command_id() -> str:
    with _id_lock:
        sequence = next(_id_counter)
    return f"{time.time_ns()}-{sequence}"


def read_state(
    root: str | os.PathLike[str] | None = None,
    *,
    max_age_seconds: float = 10.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Read state JSON and warn when its file modification time is stale."""
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")

    path = get_data_dir(root) / "oni_state.json"
    modified = path.stat().st_mtime
    age = (time.time() if now is None else now) - modified
    if age > max_age_seconds:
        warnings.warn(
            f"ONI state is stale ({age:.1f}s old; limit {max_age_seconds:.1f}s): {path}",
            RuntimeWarning,
            stacklevel=2,
        )

    with path.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)
    if not isinstance(state, dict):
        raise ValueError("oni_state.json must contain a JSON object")
    return state


def send_command(
    actions: Sequence[Mapping[str, Any]],
    root: str | os.PathLike[str] | None = None,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> dict[str, Any]:
    """Write one command and return its matching result, or raise TimeoutError."""
    if not actions or any(not isinstance(action, Mapping) for action in actions):
        raise ValueError("actions must be a non-empty sequence of mappings")
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")

    directory = get_data_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    command_path = directory / "oni_commands.json"
    result_path = directory / "oni_results.json"
    command_id = _new_command_id()
    temporary_path = directory / f"oni_commands.json.{command_id}.tmp"
    command = {"id": command_id, "actions": list(actions)}

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as command_file:
            json.dump(command, command_file, ensure_ascii=False)
        os.replace(temporary_path, command_path)

        deadline = time.monotonic() + timeout
        while True:
            try:
                with result_path.open("r", encoding="utf-8") as result_file:
                    result = json.load(result_file)
            except FileNotFoundError:
                result = None
            except json.JSONDecodeError:
                result = None

            if isinstance(result, dict) and result.get("id") == command_id:
                if not isinstance(result.get("results"), list):
                    raise ValueError("Matching oni_results.json has no results array")
                return result

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"No result received for command {command_id}")
            time.sleep(min(poll_interval, remaining))
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass

