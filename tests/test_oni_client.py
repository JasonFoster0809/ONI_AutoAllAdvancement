import json
import io
import warnings
from pathlib import Path

from agent import oni_client

FIXTURES = Path(__file__).parent / "fixtures"


def test_read_state_warns_when_stale(tmp_path):
    state_path = tmp_path / "oni_state.json"
    state_path.write_text('{"cycle": 1}', encoding="utf-8")
    modified = state_path.stat().st_mtime
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert oni_client.read_state(tmp_path, now=modified + 11)["cycle"] == 1
    assert any("stale" in str(item.message) for item in caught)


def test_read_state_accepts_operational_building_and_legacy_fixtures(tmp_path):
    cases = (
        ("operational_mineral_deoxidizer.json", True, True),
        ("unpowered_mineral_deoxidizer.json", False, False),
        ("legacy_building_state.json", None, None),
    )
    state_path = tmp_path / "oni_state.json"
    for fixture_name, operational, powered in cases:
        state_path.write_text(
            (FIXTURES / fixture_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        state = oni_client.read_state(tmp_path)
        assert len(state["building_list"]) == 1
        building = state["building_list"][0]
        assert building["id"] == "MineralDeoxidizer"
        if operational is None:
            assert "operational" not in building
            assert "powered" not in building
            assert "stored" not in building
        else:
            assert building["operational"] is operational
            assert building["powered"] is powered
            assert building["stored"]["Algae"] == 120.5


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


def test_send_command_retries_locked_and_partial_result_without_resending(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "oni_results.json"
    original_open = Path.open
    result_reads = 0
    sleeps = 0
    replacements = []
    original_replace = oni_client.os.replace

    def flaky_open(path, mode="r", *args, **kwargs):
        nonlocal result_reads
        if path == result_path and mode == "r":
            result_reads += 1
            if result_reads == 1:
                raise PermissionError("result file is temporarily locked")
            if result_reads == 2:
                return io.StringIO("{")
        return original_open(path, mode, *args, **kwargs)

    def publish_after_retry(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            command = json.loads(
                (tmp_path / "oni_commands.json").read_text(encoding="utf-8")
            )
            result_path.write_text(
                json.dumps(
                    {"id": command["id"], "results": [{"type": "dig", "ok": True}]}
                ),
                encoding="utf-8",
            )

    def counted_replace(source, destination):
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(oni_client.time, "sleep", publish_after_retry)
    monkeypatch.setattr(oni_client.os, "replace", counted_replace)

    result = oni_client.send_command(
        [{"type": "dig", "x": 1, "y": 2}],
        tmp_path,
        timeout=1,
        poll_interval=0.01,
    )

    assert result["results"][0]["ok"] is True
    assert result_reads == 3
    assert len(replacements) == 1


def test_send_command_times_out_if_result_remains_locked(tmp_path, monkeypatch):
    import pytest

    result_path = tmp_path / "oni_results.json"
    original_open = Path.open
    replacements = []
    original_replace = oni_client.os.replace

    def locked_open(path, mode="r", *args, **kwargs):
        if path == result_path and mode == "r":
            raise PermissionError("result file remains locked")
        return original_open(path, mode, *args, **kwargs)

    def counted_replace(source, destination):
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(Path, "open", locked_open)
    monkeypatch.setattr(oni_client.os, "replace", counted_replace)

    with pytest.raises(TimeoutError, match="No result received"):
        oni_client.send_command(
            [{"type": "dig", "x": 1, "y": 2}],
            tmp_path,
            timeout=0.03,
            poll_interval=0.005,
        )

    assert len(replacements) == 1
