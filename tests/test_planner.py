import json
from pathlib import Path

import pytest

from agent import planner
from agent.planner import (
    Goal,
    mark_pending,
    next_step,
    update_pending,
)


FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {
    "priority_techs": ["FarmingTech"],
    "pending_steps": 3,
    "bed_id": "Bed",
    "door_id": "Door",
    "tile_id": "Tile",
    "barracks_bed_count": 2,
}
RESEARCH_CHAIN_CONFIG = {
    **CONFIG,
    "research_chain_order": [
        "FineDining",
        "PowerRegulation",
        "LiquidPiping",
        "GasPiping",
        "MedicineI",
        "BasicRefinement",
        "InteriorDecor",
    ],
}


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_catalog():
    return json.loads((FIXTURES / "goal_catalog.json").read_text(encoding="utf-8"))


def research_center_setup_state(*, clear_footprint=False):
    rows = ["." * 12 for _ in range(10)]
    rows[8] = "..##" + "." * 8
    footprint_row = "..GG" + "." * 8 if clear_footprint else ".G##" + "." * 8
    rows[7] = footprint_row
    rows[6] = footprint_row
    return {
        "cycle": 0,
        "building_list": [],
        "resources": {"materials": {"Cuprite": 400}},
        "world": {
            "start": {"type": "telepad", "x": 1, "y": 2},
            "origin": {"x": 0, "y": 0},
            "map": rows,
        },
    }


def load_research_center_catalog():
    return json.loads(
        (FIXTURES / "research_center_setup_catalog.json").read_text(
            encoding="utf-8"
        )
    )


def test_research_goal_has_priority_over_barracks():
    step = next_step(
        load_fixture("goal_research_ready.json"),
        load_catalog(),
        CONFIG,
        {},
    )
    assert step["goal_id"] == "research_target"
    assert step["actions"] == [{"type": "set_research", "tech": "FarmingTech"}]


def test_research_chain_selects_first_configured_ready_basic_tech():
    state = load_fixture("research_chain_finedining.json")
    state["building_list"] = [
        {"id": "ResearchCenter", "state": "built"}
    ]

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )

    assert step["goal_id"] == "research_chain"
    assert step["actions"] == [{"type": "set_research", "tech": "FineDining"}]
    assert set(step["actions"][0]) == {"type", "tech"}


def test_research_chain_without_built_center_skips_and_planner_checks_barracks():
    state = load_fixture("goal_barracks_unbuilt.json")
    state["research"] = load_fixture("research_chain_finedining.json")["research"]
    state["research"]["active"] = None

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
    )

    assert step["goal_id"] == "barracks"
    assert any(
        item["goal_id"] == "research_chain"
        and item["reason"] == "no_research_center"
        for item in step["skipped"]
    )


@pytest.mark.parametrize(
    ("building_list", "expected_reason"),
    [
        ([], "no_research_center"),
        (
            [{"id": "ResearchCenter", "state": "under_construction"}],
            "no_research_center",
        ),
    ],
)
def test_research_chain_requires_built_research_center(
    building_list, expected_reason
):
    state = load_fixture("research_chain_finedining.json")
    state["building_list"] = building_list

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": expected_reason,
    } in step["skipped"]


def test_research_chain_missing_building_list_is_unknown():
    state = load_fixture("research_chain_finedining.json")
    del state["building_list"]

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": "research_building_list_unknown",
    } in step["skipped"]


def test_research_chain_order_is_read_from_agent_config():
    config = json.loads(
        (Path(__file__).parent.parent / "agent" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["research_chain_order"] == RESEARCH_CHAIN_CONFIG["research_chain_order"]


def test_research_chain_skips_while_another_tech_is_active():
    state = load_fixture("research_chain_finedining.json")
    state["research"]["active"] = "SomeCurrentTech"

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": "research_already_active",
    } in step["skipped"]


def test_research_chain_empty_order_is_a_noop_with_reason():
    state = load_fixture("research_chain_finedining.json")
    config = {**RESEARCH_CHAIN_CONFIG, "research_chain_order": []}

    step = next_step(
        state, load_catalog(), config, {}, enabled_goals=["research_chain"]
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": "research_chain_order_empty",
    } in step["skipped"]


def test_research_chain_skips_non_basic_costs():
    state = load_fixture("research_chain_finedining.json")
    state["research"]["techs"][0]["cost"][0]["type"] = "advanced"

    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )

    assert step["goal_id"] == "no_goal"
    assert step["actions"] == []
    assert {
        "goal_id": "research_chain",
        "reason": "no_basic_ready_tech",
    } in step["skipped"]


def test_research_chain_missing_data_is_unknown_and_never_sends():
    state = load_fixture("research_chain_finedining.json")
    del state["research"]["active"]
    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )
    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": "research_status_unknown",
    } in step["skipped"]

    state = load_fixture("research_chain_finedining.json")
    del state["research"]["techs"][0]["cost"]
    step = next_step(
        state,
        load_catalog(),
        RESEARCH_CHAIN_CONFIG,
        {},
        enabled_goals=["research_chain"],
    )
    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_chain",
        "reason": "research_cost_unknown",
    } in step["skipped"]


def test_barracks_goal_plans_enclosed_room_when_not_built():
    state = load_fixture("goal_barracks_unbuilt.json")
    step = next_step(state, load_catalog(), CONFIG, {})
    assert step["goal_id"] == "barracks"
    assert sum(action["id"] == "Tile" for action in step["actions"]) == 18
    assert sum(action["id"] == "Bed" for action in step["actions"]) == 2
    assert sum(action["id"] == "Door" for action in step["actions"]) == 1
    assert all(action["type"] == "build" for action in step["actions"])


def test_research_center_setup_digs_only_missing_footprint_cells():
    state = research_center_setup_state()
    step = next_step(
        state,
        load_research_center_catalog(),
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )

    assert step["goal_id"] == "research_center_setup"
    assert step["actions"] == [
        {"type": "dig", "x": 2, "y": 2},
        {"type": "dig", "x": 3, "y": 2},
        {"type": "dig", "x": 2, "y": 3},
        {"type": "dig", "x": 3, "y": 3},
    ]
    assert len(step["actions"]) <= 6


def test_research_center_setup_builds_when_supported_footprint_is_gas():
    state = research_center_setup_state(clear_footprint=True)
    step = next_step(
        state,
        load_research_center_catalog(),
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )

    assert step["goal_id"] == "research_center_setup"
    assert step["actions"] == [
        {
            "type": "build",
            "id": "ResearchCenter",
            "x": 2,
            "y": 2,
            "orientation": "Neutral",
            "elements": ["Cuprite"],
            "priority": 5,
        }
    ]


def test_research_center_setup_blocks_without_metal_stock():
    state = research_center_setup_state(clear_footprint=True)
    state["resources"]["materials"] = {}
    step = next_step(
        state,
        load_research_center_catalog(),
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_center_setup",
        "reason": "research_center_metal_material_unavailable",
    } in step["skipped"]


def test_research_center_setup_rejects_vacuum_near_candidate():
    state = research_center_setup_state()
    rows = state["world"]["map"]
    rows[2] = rows[2][:7] + "V" + rows[2][8:]
    step = next_step(
        state,
        load_research_center_catalog(),
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_center_setup",
        "reason": "no_reachable_research_center_placement",
    } in step["skipped"]


def test_research_center_setup_is_done_when_center_is_built():
    state = research_center_setup_state()
    state["building_list"] = [
        {"id": "ResearchCenter", "state": "built", "x": 2, "y": 2}
    ]
    step = next_step(
        state,
        load_research_center_catalog(),
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )

    assert step["goal_id"] == "no_goal"
    assert {
        "goal_id": "research_center_setup",
        "reason": "already_done",
    } in step["skipped"]


def test_research_center_setup_pending_digs_wait_for_map_acknowledgment():
    state = research_center_setup_state()
    catalog = load_research_center_catalog()
    step = next_step(
        state,
        catalog,
        CONFIG,
        {},
        enabled_goals=["research_center_setup"],
    )
    pending = {}
    mark_pending(
        pending,
        step["goal_id"],
        step["actions"],
        submitted_step=1,
        results=[{"ok": True} for _ in step["actions"]],
    )

    repeated = next_step(
        state,
        catalog,
        CONFIG,
        pending,
        enabled_goals=["research_center_setup"],
    )
    assert repeated["goal_id"] == "no_goal"
    assert {"goal_id": "research_center_setup", "reason": "pending"} in repeated[
        "skipped"
    ]

    for action in step["actions"]:
        row = len(state["world"]["map"]) - 1 - action["y"]
        column = action["x"]
        map_row = state["world"]["map"][row]
        state["world"]["map"][row] = (
            map_row[:column] + "G" + map_row[column + 1 :]
        )
    update_pending(state, pending, step=2, max_steps=30, catalog=catalog)
    resumed = next_step(
        state,
        catalog,
        CONFIG,
        pending,
        enabled_goals=["research_center_setup"],
    )
    assert resumed["actions"][0]["type"] == "build"
    assert resumed["actions"][0]["id"] == "ResearchCenter"


def test_done_and_pending_goals_are_skipped():
    done_state = load_fixture("goal_barracks_built.json")
    done_step = next_step(done_state, load_catalog(), CONFIG, {})
    assert done_step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "already_done"} in done_step["skipped"]
    assert done_state["rooms"][0] == {
        "type": "Barracks",
        "size": 20,
        "x": -2,
        "y": 3,
    }

    pending_state = load_fixture("goal_barracks_unbuilt.json")
    pending = load_fixture("goal_pending_build.json")["pending"]
    pending_step = next_step(pending_state, load_catalog(), CONFIG, pending)
    assert pending_step["goal_id"] == "no_goal"
    assert {"goal_id": "barracks", "reason": "pending"} in pending_step["skipped"]


def test_barracks_done_requires_a_reported_barracks_room():
    assert planner.barracks_done({}) is None
    assert planner.barracks_done({"rooms": []}) is False
    assert planner.barracks_done({"rooms": [{"type": "Barracks"}]}) is True


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
