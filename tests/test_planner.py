import json
from pathlib import Path

import pytest

from agent import planner
from agent.planner import Goal, mark_pending, next_step, update_pending


FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {
    "priority_techs": ["FarmingTech"],
    "pending_steps": 3,
    "bed_id": "Bed",
    "door_id": "Door",
    "tile_id": "Tile",
}


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_catalog():
    return json.loads((FIXTURES / "goal_catalog.json").read_text(encoding="utf-8"))


def test_research_goal_has_priority_over_barracks():
    step = next_step(
        load_fixture("goal_research_ready.json"),
        load_catalog(),
        CONFIG,
        {},
    )
    assert step["goal_id"] == "research_target"
    assert step["actions"] == [{"type": "set_research", "tech": "FarmingTech"}]


def test_barracks_goal_plans_tile_bed_door_when_room_not_built():
    state = load_fixture("goal_barracks_unbuilt.json")
    step = next_step(state, load_catalog(), CONFIG, {})
    assert step["goal_id"] == "barracks"
    assert [action["id"] for action in step["actions"]] == ["Tile", "Tile", "Tile", "Bed", "Door"]
    assert all(action["type"] == "build" for action in step["actions"])


def test_done_and_pending_goals_are_skipped():
    done_state = load_fixture("goal_barracks_built.json")
    done_step = next_step(done_state, load_catalog(), CONFIG, {})
    assert done_step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "already_done"} in done_step["skipped"]

    pending_state = load_fixture("goal_barracks_unbuilt.json")
    pending = load_fixture("goal_pending_build.json")["pending"]
    pending_step = next_step(pending_state, load_catalog(), CONFIG, pending)
    assert pending_step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "pending"} in pending_step["skipped"]


def test_plan_errors_are_skipped_and_later_goals_are_considered():
    state = load_fixture("goal_barracks_unbuilt.json")
    config = {**CONFIG, "bed_id": None}
    step = next_step(state, load_catalog(), config, {})
    assert step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "bed_id_unconfigured"} in step["skipped"]

    state["research"] = {
        "active": None,
        "techs": [{"id": "LockedTech", "complete": False, "ready": False}],
    }
    step = next_step(state, load_catalog(), CONFIG, {})
    assert step["goal_id"] == "barracks"
    assert {"goal_id": "research_target", "reason": "no_ready_tech"} in step["skipped"]


def test_pending_is_cleared_when_building_list_reflects_order_or_expires():
    state = load_fixture("goal_barracks_unbuilt.json")
    pending = {}
    pending_actions = [
        {"type": "build", "id": "Tile", "x": 1, "y": -1},
    ]
    mark_pending(
        pending,
        "barracks",
        pending_actions,
        1,
        [{"type": "build", "ok": True}],
    )
    state["building_list"] = [
        {"id": "Tile", "x": 1, "y": -1, "state": "under_construction"}
    ]
    assert update_pending(state, pending, 2, 3, load_catalog()) == []
    assert pending == {}

    pending = {
        "barracks": {
            "actions": [
                {"type": "build", "id": "Tile", "x": 1, "y": -1},
            ],
            "submitted_step": 1,
        }
    }
    state["building_list"] = []
    expired = update_pending(state, pending, 4, 3, load_catalog())
    assert expired == [{"goal_id": "barracks", "reason": "pending_expired"}]
    assert pending == {}


def test_existing_building_action_is_not_planned_twice():
    state = load_fixture("goal_barracks_unbuilt.json")
    planned = next_step(state, load_catalog(), CONFIG, {})
    tile = next(action for action in planned["actions"] if action["id"] == "Tile")
    state["building_list"] = [
        {
            "id": tile["id"],
            "x": tile["x"],
            "y": tile["y"],
            "state": "built",
        }
    ]
    updated = next_step(state, load_catalog(), CONFIG, {})
    assert not any(
        action["id"] == tile["id"] and action["x"] == tile["x"] and action["y"] == tile["y"]
        for action in updated["actions"]
    )


def test_insufficient_material_plan_is_skipped():
    state = load_fixture("goal_barracks_unbuilt.json")
    catalog = load_catalog()
    catalog[0]["materials"] = [
        {"category": "Rock", "options": ["SandStone"], "mass_kg": 100}
    ]
    state["resources"] = load_fixture("goal_insufficient_material.json")["resources"]
    config = {**CONFIG, "tile_id": "Tile"}
    step = next_step(state, catalog, config, {})
    assert step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "insufficient_material"} in step["skipped"]


def test_registered_goal_can_be_added_for_future_objectives(monkeypatch):
    monkeypatch.setattr(planner, "GOALS", [])
    monkeypatch.setattr(planner, "_GOAL_RANKS", {})
    planner.register_goal(
        Goal(
            id="future",
            description="future test goal",
            is_done=lambda state: False,
            plan=lambda state, catalog, config: [{"type": "dig", "x": 0, "y": 0}],
        )
    )
    step = next_step({}, [], {}, {})
    assert step["goal_id"] == "future"
