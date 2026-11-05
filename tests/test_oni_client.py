import json
import warnings

from agent import oni_client


def test_read_state_warns_when_stale(tmp_path):
    state_path = tmp_path / "oni_state.json"
    state_path.write_text('{"cycle": 1}', encoding="utf-8")
    modified = state_path.stat().st_mtime
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert oni_client.read_state(tmp_path, now=modified + 11)["cycle"] == 1
    assert any("stale" in str(item.message) for item in caught)


def test_send_command_waits_for_matching_result(tmp_path, monkeypatch):
    result_path = tmp_path / "oni_results.json"

    def make_result(_seconds):
        command = json.loads((tmp_path / "oni_commands.json").read_text(encoding="utf-8"))
        result_path.write_text(
            json.dumps({"id": command["id"], "results": [{"type": "dig", "ok": True}]}),
            encoding="utf-8",
        )

    monkeypatch.setattr(oni_client.time, "sleep", make_result)
    result = oni_client.send_command(
        [{"type": "dig", "x": 1, "y": 2}],
        tmp_path,
        timeout=1,
        poll_interval=0.001,
    )
    assert result["results"][0]["ok"] is True
    command = json.loads((tmp_path / "oni_commands.json").read_text(encoding="utf-8"))
    assert command["id"] == result["id"]


def test_send_command_validates_actions(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="non-empty"):
        oni_client.send_command([], tmp_path)
