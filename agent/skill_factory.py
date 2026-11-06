"""Create untrusted, review-only Python skill drafts."""

from __future__ import annotations

import argparse
import ast
import json
import logging
import math
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .catalog import load_catalog
from .strategist import GoalProvider, create_goal_provider


LOGGER = logging.getLogger(__name__)
AGENT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = AGENT_DIR / "config.json"
GENERATED_DIR = AGENT_DIR / "skills_generated"
ALLOWED_ACTIONS = frozenset(
    {
        "dig",
        "build",
        "cancel",
        "set_priority",
        "set_dupe_priority",
        "set_research",
        "schedule",
    }
)
FORBIDDEN_IMPORTS = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "sys",
        "shutil",
        "requests",
        "urllib",
        "ctypes",
        "importlib",
    }
)
FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "open", "__import__"})
SAFE_BUILTIN_CALLS = frozenset(
    {
        "all",
        "any",
        "bool",
        "enumerate",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "range",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
    }
)
SAFE_METHOD_CALLS = frozenset(
    {"append", "extend", "get", "items", "keys", "values"}
)
MAX_SOURCE_LENGTH = 50_000
DRY_RUN_TIMEOUT_SECONDS = 15


class SkillFactoryError(ValueError):
    """A stable, user-readable skill generation or validation failure."""


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SkillFactoryError(f"{label}_unavailable:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise SkillFactoryError(f"{label}_must_be_object")
    return value


def _slugify(description: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", description.casefold()).strip("_")
    if not slug:
        slug = "generated_skill"
    if slug[0].isdigit():
        slug = f"skill_{slug}"
    if slug.startswith("test_"):
        slug = f"skill_{slug}"
    return slug[:60].rstrip("_")


def _catalog_building_ids(catalog: Sequence[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for building in catalog:
        building_id = building.get("id")
        if isinstance(building_id, str) and building_id:
            ids.add(building_id)
    if not ids:
        raise SkillFactoryError("catalog_has_no_building_ids")
    return ids


def _string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            value = ast.literal_eval(statement.value)
        except (ValueError, TypeError, SyntaxError):
            continue
        if isinstance(value, str):
            constants[target.id] = value
    return constants


def _literal_string(node: ast.expr | None, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _is_action_dict(
    node: ast.expr,
    constants: Mapping[str, str],
    catalog_ids: set[str],
) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    fields = {
        key.value: value
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    action_type = _literal_string(fields.get("type"), constants)
    if action_type not in ALLOWED_ACTIONS:
        return False
    if action_type == "build":
        building_id = _literal_string(fields.get("id"), constants)
        if building_id is None:
            raise SkillFactoryError("build_id_must_be_static_string")
        if building_id not in catalog_ids:
            raise SkillFactoryError(f"unknown_building_id:{building_id}")
    return True


def _validate_plan_returns(
    plan: ast.FunctionDef,
    constants: Mapping[str, str],
    catalog_ids: set[str],
) -> None:
    returned_lists: set[str] = set()
    returns: list[ast.Return] = []
    initialized_lists: set[str] = set()
    for node in ast.walk(plan):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.List):
                        initialized_lists.add(target.id)
                    elif target.id in initialized_lists:
                        raise SkillFactoryError(
                            "action_list_cannot_be_reassigned_from_dynamic_value"
                        )
        elif isinstance(node, ast.Return):
            returns.append(node)
            if isinstance(node.value, ast.Name):
                returned_lists.add(node.value.id)
            elif isinstance(node.value, ast.List):
                if any(
                    not _is_action_dict(item, constants, catalog_ids)
                    for item in node.value.elts
                ):
                    raise SkillFactoryError("return_must_contain_static_action_objects")
            else:
                raise SkillFactoryError("return_must_be_action_list")
    if not returns:
        raise SkillFactoryError("plan_must_return_action_list")
    if not returned_lists.issubset(initialized_lists):
        raise SkillFactoryError("returned_action_list_must_be_initialized_locally")

    def root_name(node: ast.expr) -> str | None:
        while isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    for node in ast.walk(plan):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SkillFactoryError("global_state_not_allowed")
        if isinstance(node, ast.Delete) and any(
            root_name(target) == "state" for target in node.targets
        ):
            raise SkillFactoryError("state_mutation_not_allowed")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if root_name(node) == "state":
                raise SkillFactoryError("state_mutation_not_allowed")
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            if root_name(node) == "state":
                raise SkillFactoryError("state_mutation_not_allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func.value
            if node.func.attr in {"append", "extend"}:
                if not isinstance(target, ast.Name) or target.id not in returned_lists:
                    raise SkillFactoryError("mutable_methods_only_allowed_on_action_list")
                if node.func.attr == "append":
                    if len(node.args) != 1 or node.keywords or not _is_action_dict(
                        node.args[0], constants, catalog_ids
                    ):
                        raise SkillFactoryError(
                            "action_list_append_requires_static_action_object"
                        )
                elif node.func.attr == "extend":
                    if (
                        len(node.args) != 1
                        or node.keywords
                        or not isinstance(node.args[0], ast.List)
                        or any(
                            not _is_action_dict(item, constants, catalog_ids)
                            for item in node.args[0].elts
                        )
                    ):
                        raise SkillFactoryError(
                            "action_list_extend_requires_static_action_objects"
                        )
                else:
                    raise SkillFactoryError("action_list_mutation_not_allowed")
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            target = node.value
            if isinstance(target, ast.Name) and target.id in returned_lists:
                raise SkillFactoryError("action_list_item_mutation_not_allowed")
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in returned_lists:
                raise SkillFactoryError("action_list_mutation_not_allowed")


def validate_skill_source(
    source: str,
    catalog_ids: set[str],
) -> set[str]:
    """Check a draft's restricted Python subset before it can be saved."""
    if len(source) > MAX_SOURCE_LENGTH:
        raise SkillFactoryError("source_too_large")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise SkillFactoryError(f"invalid_python:{error.msg}") from error

    imports = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    for node in imports:
        imported = (
            [alias.name.split(".", 1)[0] for alias in node.names]
            if isinstance(node, ast.Import)
            else [(node.module or "").split(".", 1)[0]]
        )
        blocked = sorted(FORBIDDEN_IMPORTS.intersection(imported))
        if blocked:
            raise SkillFactoryError(f"forbidden_import:{blocked[0]}")
    if imports:
        raise SkillFactoryError("imports_not_allowed_in_generated_skills")

    plan_functions = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name == "plan":
                plan_functions.append(statement)
            elif isinstance(statement, ast.AsyncFunctionDef):
                raise SkillFactoryError("async_functions_not_allowed")
            else:
                raise SkillFactoryError("only_plan_function_allowed")
        elif isinstance(statement, ast.Assign):
            if (
                len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)
            ):
                raise SkillFactoryError("module_constants_must_be_simple_assignments")
            try:
                ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError) as error:
                raise SkillFactoryError("module_constants_must_be_literals") from error
        elif isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ) and isinstance(statement.value.value, str):
            continue
        else:
            raise SkillFactoryError("module_level_executable_code_not_allowed")
    if len(plan_functions) != 1 or isinstance(plan_functions[0], ast.AsyncFunctionDef):
        raise SkillFactoryError("exactly_one_plan_function_required")

    plan = plan_functions[0]
    if (
        len(plan.args.args) != 1
        or plan.args.args[0].arg != "state"
        or plan.args.posonlyargs
        or plan.args.kwonlyargs
        or plan.args.vararg
        or plan.args.kwarg
        or plan.args.defaults
        or plan.args.kw_defaults
        or plan.args.args[0].annotation
        or plan.args.vararg
        or plan.args.kwarg
        or plan.returns
        or plan.decorator_list
    ):
        raise SkillFactoryError("plan_must_accept_only_state")

    constants = _string_constants(tree)
    found_build_ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            raise SkillFactoryError(f"forbidden_name:{node.id}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise SkillFactoryError(f"private_attribute_not_allowed:{node.attr}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
                if function_name in FORBIDDEN_CALLS:
                    raise SkillFactoryError(f"forbidden_call:{function_name}")
                if function_name not in SAFE_BUILTIN_CALLS:
                    raise SkillFactoryError(f"call_not_allowed:{function_name}")
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in SAFE_METHOD_CALLS:
                    raise SkillFactoryError(f"method_call_not_allowed:{node.func.attr}")
            else:
                raise SkillFactoryError("dynamic_calls_not_allowed")
        if isinstance(node, ast.Dict):
            literal_keys: dict[str, ast.expr] = {}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    literal_keys[key.value] = value
            action_type_node = literal_keys.get("type")
            if action_type_node is None:
                continue
            action_type = _literal_string(action_type_node, constants)
            if action_type not in ALLOWED_ACTIONS:
                raise SkillFactoryError(f"action_not_allowed:{action_type or 'dynamic'}")
            if action_type == "build":
                building_id = _literal_string(literal_keys.get("id"), constants)
                if building_id is None:
                    raise SkillFactoryError("build_id_must_be_static_string")
                if building_id not in catalog_ids:
                    raise SkillFactoryError(f"unknown_building_id:{building_id}")
                found_build_ids.add(building_id)
    _validate_plan_returns(plan, constants, catalog_ids)
    return found_build_ids


def _render_draft(skill_id: str, description: str) -> str:
    return (
        f'SKILL_ID = {skill_id!r}\n'
        f'DESCRIPTION = {description!r}\n\n'
        "def plan(state):\n"
        "    \"\"\"Return proposed ONI actions for the supplied state.\"\"\"\n"
        "    # TODO: inspect state and return only supported action dictionaries.\n"
        "    return []\n"
    )


def _attach_generated_metadata(source: str, skill_id: str, description: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise SkillFactoryError(f"invalid_python:{error.msg}") from error
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name)
            and target.id in {"SKILL_ID", "DESCRIPTION"}
            for target in statement.targets
        ):
            raise SkillFactoryError("generated_metadata_is_factory_managed")
    return (
        f"SKILL_ID = {skill_id!r}\n"
        f"DESCRIPTION = {description!r}\n\n"
        f"{source.lstrip()}"
    )


def _render_test(skill_id: str, building_ids: Sequence[str]) -> str:
    return (
        f"from agent.skills_generated.{skill_id} import plan\n\n"
        f"BUILDING_IDS = {sorted(building_ids)!r}\n"
        f"ALLOWED_ACTIONS = {sorted(ALLOWED_ACTIONS)!r}\n\n"
        "def test_generated_skill_dry_run_returns_supported_actions():\n"
        "    state = {\n"
        "        'cycle': 0,\n"
        "        'dupes': [],\n"
        "        'resources': {'food_kcal': 0, 'materials': {}},\n"
        "        'building_list': [],\n"
        "        'rooms': [],\n"
        "    }\n"
        "    actions = plan(state)\n"
        "    assert isinstance(actions, list)\n"
        "    for action in actions:\n"
        "        assert isinstance(action, dict)\n"
        "        assert action.get('type') in ALLOWED_ACTIONS\n"
        "        if action['type'] == 'build':\n"
        "            assert action.get('id') in BUILDING_IDS\n"
    )


def _run_staged_pytest(
    skill_id: str,
    source: str,
    test_source: str,
    timeout: int = DRY_RUN_TIMEOUT_SECONDS,
) -> None:
    with tempfile.TemporaryDirectory(prefix="oni-skill-draft-") as directory:
        root = Path(directory)
        module_dir = root / "agent" / "skills_generated"
        tests_dir = root / "tests"
        module_dir.mkdir(parents=True)
        tests_dir.mkdir()
        (root / "agent" / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / f"{skill_id}.py").write_text(source, encoding="utf-8")
        test_path = tests_dir / f"test_generated_{skill_id}.py"
        test_path.write_text(test_source, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", str(test_path)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SkillFactoryError(
                f"dry_run_failed:{type(error).__name__}"
            ) from error
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip().splitlines()
            reason = detail[-1] if detail else "pytest_failed"
            raise SkillFactoryError(f"dry_run_failed:{reason[:300]}")


def _provider_response(
    provider: GoalProvider,
    description: str,
    building_ids: Sequence[str],
    timeout: float,
) -> tuple[str, str]:
    prompt = {
        "skill_description": description,
        "available_building_ids": list(building_ids),
        "required_module_contract": (
            "Return a single Python module with exactly one function plan(state), "
            "accepting only the state argument and returning a list of action "
            "dictionaries. Do not import anything. Do not send commands. "
            "Use only literal building IDs from available_building_ids."
        ),
        "required_response": (
            "Return only JSON with exactly two string fields: code and description. "
            "The code will be statically checked and executed on a fake state before "
            "saving. Do not include markdown fences."
        ),
        "allowed_action_types": sorted(ALLOWED_ACTIONS),
    }
    try:
        raw = provider.generate(prompt, timeout=timeout)
    except (OSError, TimeoutError, RuntimeError, ValueError) as error:
        raise SkillFactoryError(f"provider_failed:{type(error).__name__}") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SkillFactoryError("provider_response_invalid_json") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"code", "description"}
        or not isinstance(value.get("code"), str)
        or not isinstance(value.get("description"), str)
        or not value["description"].strip()
    ):
        raise SkillFactoryError("provider_response_invalid_shape")
    return value["code"], value["description"].strip()


def generate_skill(
    description: str,
    *,
    catalog: Sequence[Mapping[str, Any]],
    provider: GoalProvider | None,
    output_dir: str | Path = GENERATED_DIR,
    timeout: float = 60.0,
) -> dict[str, str]:
    if not isinstance(description, str) or not description.strip():
        raise SkillFactoryError("description_required")
    building_ids = _catalog_building_ids(catalog)
    skill_id = _slugify(description)
    destination = Path(output_dir)
    module_path = destination / f"{skill_id}.py"
    test_path = destination / f"test_{skill_id}.py"
    description_path = destination / f"{skill_id}.md"
    if any(path.exists() for path in (module_path, test_path, description_path)):
        raise SkillFactoryError(f"skill_already_exists:{skill_id}")

    if provider is None:
        source = _render_draft(skill_id, description.strip())
        skill_description = (
            f"{description.strip()}\n\n"
            "Status: draft only. Fill in the TODO in plan(state), then review "
            "and validate it before manually enabling this skill."
        )
    else:
        source, skill_description = _provider_response(
            provider,
            description.strip(),
            sorted(building_ids),
            timeout,
        )
        source = _attach_generated_metadata(
            source,
            skill_id,
            skill_description,
        )

    validate_skill_source(source, building_ids)
    test_source = _render_test(skill_id, building_ids)
    _run_staged_pytest(skill_id, source, test_source)

    destination.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (module_path, source.rstrip() + "\n"),
        (test_path, test_source),
        (
            description_path,
            f"# {description.strip()}\n\n{skill_description.strip()}\n\n"
            "**Not activated.** Review the generated Python and test. To activate "
            "manually, add this skill ID to `enabled_generated_skills` in "
            "`agent/config.json` after validation.\n",
        ),
    ):
        path.write_text(content, encoding="utf-8", newline="\n")
    return {
        "skill_id": skill_id,
        "module": str(module_path),
        "test": str(test_path),
        "description": str(description_path),
        "status": "draft_not_activated",
    }


def validate_enabled_skills(
    *,
    config: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    skills_dir: str | Path = GENERATED_DIR,
) -> list[str]:
    enabled = config.get("enabled_generated_skills", [])
    if (
        not isinstance(enabled, list)
        or any(not isinstance(skill_id, str) or not skill_id for skill_id in enabled)
        or len(enabled) != len(set(enabled))
    ):
        raise SkillFactoryError("enabled_generated_skills_must_be_unique_string_list")
    catalog_ids = _catalog_building_ids(catalog)
    source_by_id: dict[str, Path] = {}
    for path in Path(skills_dir).glob("*.py"):
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as error:
            LOGGER.warning(
                "Skipping unreadable generated module %s (%s)",
                path.name,
                type(error).__name__,
            )
            continue
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "SKILL_ID"
            ):
                try:
                    skill_id = ast.literal_eval(statement.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(skill_id, str):
                    source_by_id[skill_id] = path

    validated: list[str] = []
    for skill_id in enabled:
        path = source_by_id.get(skill_id)
        if path is None:
            raise SkillFactoryError(f"enabled_skill_not_found:{skill_id}")
        validate_skill_source(path.read_text(encoding="utf-8"), catalog_ids)
        validated.append(skill_id)
    return validated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate review-only Python skill drafts; never activate them"
    )
    parser.add_argument("description", nargs="?", help="plain-language skill request")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=GENERATED_DIR)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="statically validate every skill manually listed as enabled",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate and test in a temporary directory without saving files",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = _read_json_object(args.config, "config")
        catalog = load_catalog(args.data_dir)
        if args.validate:
            if args.description:
                parser.error("--validate cannot be combined with a description")
            validated = validate_enabled_skills(
                config=config,
                catalog=catalog,
                skills_dir=args.output_dir,
            )
            print(json.dumps({"valid": True, "enabled": validated}))
            return 0
        if not args.description:
            parser.error("a description is required unless --validate is used")
        strategist_config = config.get("strategist", {})
        if not isinstance(strategist_config, Mapping):
            raise SkillFactoryError("strategist_config_must_be_object")
        timeout = strategist_config.get("timeout_seconds", 60)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
        ):
            raise SkillFactoryError("strategist.timeout_seconds_must_be_between_0_and_60")
        generated_provider = create_goal_provider(strategist_config)
        if args.dry_run:
            with tempfile.TemporaryDirectory(prefix="oni-skill-dry-run-") as directory:
                result = generate_skill(
                    args.description,
                    catalog=catalog,
                    provider=generated_provider,
                    output_dir=directory,
                    timeout=float(timeout),
                )
            LOGGER.info("Draft dry-run passed; no files saved")
            print(
                json.dumps(
                    {
                        "skill_id": result["skill_id"],
                        "status": "dry_run_passed_not_saved",
                    },
                    ensure_ascii=False,
                )
            )
        else:
            result = generate_skill(
                args.description,
                catalog=catalog,
                provider=generated_provider,
                output_dir=args.output_dir,
                timeout=float(timeout),
            )
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, SkillFactoryError, TypeError, ValueError) as error:
        LOGGER.error("Skill factory refused operation: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
