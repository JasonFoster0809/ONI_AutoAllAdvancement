import json
from pathlib import Path

import pytest

from agent.skill_factory import (
    SkillFactoryError,
    generate_skill,
    main,
    validate_enabled_skills,
    validate_skill_source,
)


CATALOG = [{"id": "KnownBuilding"}, {"id": "OtherBuilding"}]
CATALOG_IDS = {"KnownBuilding", "OtherBuilding"}


class FakeProvider:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def generate(self, prompt, *, timeout):
        self.calls.append((prompt, timeout))
        return self.value


def _provider_response(source):
    return json.dumps(
        {
            "code": source,
            "description": "A generated example skill.",
        }
    )


def test_valid_generated_code_is_dry_run_tested_and_saved_only_as_draft(tmp_path):
    provider = FakeProvider(
        _provider_response(
            "BUILDING_ID = 'KnownBuilding'\n"
            "def plan(state):\n"
            "    if state.get('build'):\n"
            "        return [{'type': 'build', 'id': BUILDING_ID, 'x': 1, 'y': 2}]\n"
            "    return []\n"
        )
    )

    result = generate_skill(
        "Build known fixture",
        catalog=CATALOG,
        provider=provider,
        output_dir=tmp_path,
    )

    assert result["skill_id"] == "build_known_fixture"
    assert result["status"] == "draft_not_activated"
    assert Path(result["module"]).exists()
    assert Path(result["test"]).exists()
    assert Path(result["description"]).exists()
    assert "Not activated" in Path(result["description"]).read_text(encoding="utf-8")
    assert provider.calls
    assert validate_enabled_skills(
        config={"enabled_generated_skills": [result["skill_id"]]},
        catalog=CATALOG,
        skills_dir=tmp_path,
    ) == [result["skill_id"]]


def test_forbidden_import_is_rejected_before_any_file_is_saved(tmp_path):
    source = "import os\ndef plan(state):\n    return []\n"

    with pytest.raises(SkillFactoryError, match="forbidden_import:os"):
        generate_skill(
            "Forbidden import",
            catalog=CATALOG,
            provider=FakeProvider(_provider_response(source)),
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_action_outside_whitelist_is_rejected(tmp_path):
    source = (
        "def plan(state):\n"
        "    return [{'type': 'launch_missile', 'id': 'KnownBuilding'}]\n"
    )

    with pytest.raises(SkillFactoryError, match="action_not_allowed"):
        generate_skill(
            "Unsupported action",
            catalog=CATALOG,
            provider=FakeProvider(_provider_response(source)),
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_unknown_building_id_is_rejected(tmp_path):
    source = (
        "def plan(state):\n"
        "    return [{'type': 'build', 'id': 'UnknownBuilding', 'x': 0, 'y': 0}]\n"
    )

    with pytest.raises(SkillFactoryError, match="unknown_building_id:UnknownBuilding"):
        generate_skill(
            "Unknown building",
            catalog=CATALOG,
            provider=FakeProvider(_provider_response(source)),
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_disabled_provider_generates_todo_skeleton_without_calling_llm(tmp_path):
    result = generate_skill(
        "Empty draft",
        catalog=CATALOG,
        provider=None,
        output_dir=tmp_path,
    )

    source = Path(result["module"]).read_text(encoding="utf-8")
    description = Path(result["description"]).read_text(encoding="utf-8")
    assert "TODO" in source
    assert "return []" in source
    assert "Not activated" in description


def test_cli_dry_run_uses_fake_catalog_and_saves_nothing(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"strategist":{"provider":"none"}}', encoding="utf-8")
    output_dir = tmp_path / "generated"

    def fake_load_catalog(root):
        assert root == tmp_path
        return CATALOG

    monkeypatch.setattr("agent.skill_factory.load_catalog", fake_load_catalog)

    assert main(
        [
            "--dry-run",
            "offline smoke test",
            "--config",
            str(config_path),
            "--data-dir",
            str(tmp_path),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "skill_id": "offline_smoke_test",
        "status": "dry_run_passed_not_saved",
    }
    assert not output_dir.exists()


def test_static_validator_checks_import_builtins_and_nonliteral_build_ids():
    with pytest.raises(SkillFactoryError, match="forbidden_import:socket"):
        validate_skill_source("import socket\ndef plan(state):\n    return []\n", CATALOG_IDS)
    with pytest.raises(SkillFactoryError, match="forbidden_call:exec|forbidden_name:exec"):
        validate_skill_source(
            "def plan(state):\n    exec('pass')\n    return []\n",
            CATALOG_IDS,
        )
    with pytest.raises(SkillFactoryError, match="build_id_must_be_static_string"):
        validate_skill_source(
            "def plan(state):\n"
            "    return [{'type': 'build', 'id': state.get('building')}]\n",
            CATALOG_IDS,
        )


def test_validate_checks_only_manually_enabled_draft_ids(tmp_path):
    source = (
        "SKILL_ID = 'enabled_sample'\n"
        "def plan(state):\n"
        "    return [{'type': 'build', 'id': 'KnownBuilding', 'x': 0, 'y': 0}]\n"
    )
    (tmp_path / "enabled_sample.py").write_text(source, encoding="utf-8")

    assert validate_enabled_skills(
        config={"enabled_generated_skills": ["enabled_sample"]},
        catalog=CATALOG,
        skills_dir=tmp_path,
    ) == ["enabled_sample"]
    with pytest.raises(SkillFactoryError, match="enabled_skill_not_found:missing"):
        validate_enabled_skills(
            config={"enabled_generated_skills": ["missing"]},
            catalog=CATALOG,
            skills_dir=tmp_path,
        )


def test_validate_cli_checks_config_enabled_skills(tmp_path, monkeypatch, capsys):
    skill_id = "enabled_sample"
    source = (
        f"SKILL_ID = {skill_id!r}\n"
        "def plan(state):\n"
        "    return [{'type': 'build', 'id': 'KnownBuilding', 'x': 0, 'y': 0}]\n"
    )
    (tmp_path / f"{skill_id}.py").write_text(source, encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"enabled_generated_skills": [skill_id]}),
        encoding="utf-8",
    )

    def fake_load_catalog(root):
        assert root == tmp_path
        return CATALOG

    monkeypatch.setattr("agent.skill_factory.load_catalog", fake_load_catalog)

    assert main(
        [
            "--validate",
            "--config",
            str(config_path),
            "--data-dir",
            str(tmp_path),
            "--output-dir",
            str(tmp_path),
        ]
    ) == 0

    assert json.loads(capsys.readouterr().out) == {
        "valid": True,
        "enabled": [skill_id],
    }
