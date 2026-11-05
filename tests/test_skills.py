import json
from pathlib import Path

import pytest

from agent.skills import (
    SkillPlanningError,
    build_mess_area,
    build_oxygen_setup,
    build_power_basic,
    build_toilet_room,
    build_bedroom,
    build_ladder_shaft,
    build_research_area,
    dig_corridor,
    plan_emergency_actions,
)


FIXTURES = Path(__file__).parent / "fixtures"


def load_empty_map():
    return json.loads((FIXTURES / "empty_map.json").read_text(encoding="utf-8"))


def load_emergency_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def supported_state():
    state = load_empty_map()
    state["world"]["map"][-1] = "#" * 41
    return state


def building(building_id, width=1, height=1, *, unlocked=True):
    return {
        "id": building_id,
        "width": width,
        "height": height,
        "materials": [],
        "unlocked": unlocked,
    }


def load_construction_catalog():
    return load_emergency_fixture("construction_skills_catalog.json")


def supported_construction_state():
    state = supported_state()
    state["building_list"] = []
    state["resources"] = {
        "materials": {"ZincOre": 10000, "SandStone": 10000}
    }
    return state


def add_built_tiles_to_state(state, actions):
    rows = state["world"]["map"]
    origin = state["world"]["origin"]
    map_height = len(rows)
    for action in actions:
        state["building_list"].append(
            {
                "id": "Tile",
                "state": "built",
                "x": action["x"],
                "y": action["y"],
            }
        )
        row = map_height - 1 - (action["y"] - origin["y"])
        column = action["x"] - origin["x"]
        rows[row] = rows[row][:column] + "F" + rows[row][column + 1 :]


def test_bedroom_plans_valid_catalog_builds():
    actions = build_bedroom(
        supported_state(),
        [building("Bed", 2, 1), building("Door", 1, 2)],
        "Bed",
        "Door",
    )
    assert [action["id"] for action in actions] == ["Bed", "Door"]
    assert all(action["orientation"] == "Neutral" for action in actions)
    assert all(action["elements"] == [] for action in actions)
    assert actions[1]["x"] == actions[0]["x"] + 2


def test_research_area_and_ladder_shaft():
    state = supported_state()
    catalog = [building("Research", 3, 2), building("Ladder")]
    research = build_research_area(state, catalog, "Research")
    assert len(research) == 1 and research[0]["id"] == "Research"
    assert research[0]["elements"] == []
    ladder = build_ladder_shaft(state, catalog, "Ladder", height=3)
    assert len(ladder) == 3
    assert all(action["elements"] == [] for action in ladder)
    assert [action["y"] for action in ladder] == list(
        range(ladder[0]["y"], ladder[0]["y"] + 3)
    )


def test_build_skills_include_materials_selected_from_state():
    state = supported_state()
    state["resources"] = {"materials": {"SandStone": 50.0}}
    catalog = [
        {
            "id": "Research",
            "width": 1,
            "height": 1,
            "materials": [
                {"category": "Rock", "options": ["SandStone"], "mass_kg": 50}
            ],
            "unlocked": True,
        }
    ]

    action = build_research_area(state, catalog, "Research")[0]
    assert action["elements"] == ["SandStone"]


def test_corridor_only_digs_solid_cells_inside_map():
    state = load_empty_map()
    rows = state["world"]["map"]
    rows[20] = rows[20][:20] + "##" + rows[20][22:]
    actions = dig_corridor(state, 0, 0, 1, 0)
    assert actions == [
        {"type": "dig", "x": 0, "y": 0},
        {"type": "dig", "x": 1, "y": 0},
    ]


def test_skills_reject_locked_and_unplaceable_buildings():
    state = supported_state()
    with pytest.raises(SkillPlanningError, match="building_locked"):
        build_research_area(state, [building("Research", unlocked=False)], "Research")

    blocked = load_empty_map()
    blocked["world"]["map"] = ["X" * 41 for _ in range(41)]
    with pytest.raises(SkillPlanningError, match="no_valid_placement"):
        build_research_area(blocked, [building("Research")], "Research")


def test_build_oxygen_setup_uses_unlocked_catalog_and_recommends_algae_delivery():
    state = supported_construction_state()
    result = build_oxygen_setup(state, load_construction_catalog())
    assert [action["id"] for action in result.actions] == ["MineralDeoxidizer"]
    assert "Algae_delivery_required_after_construction" in result.warnings

    state["building_list"] = [
        {
            "id": "MineralDeoxidizer",
            "state": "built",
            "stored": [{"element": "Algae", "kg": 0}],
        }
    ]
    result = build_oxygen_setup(state, load_construction_catalog())
    assert result.actions == []
    assert result.warnings == ["supply_Algae_to_existing_MineralDeoxidizer"]


def test_build_oxygen_setup_does_not_guess_stock_or_build_with_insufficient_material():
    state = supported_construction_state()
    state["resources"]["materials"]["ZincOre"] = 199
    with pytest.raises(SkillPlanningError, match="insufficient_material"):
        build_oxygen_setup(state, load_construction_catalog())

    state["resources"]["materials"]["ZincOre"] = 1000
    state["building_list"] = [
        {"id": "MineralDeoxidizer", "state": "built"}
    ]
    result = build_oxygen_setup(state, load_construction_catalog())
    assert result.actions == []
    assert result.warnings == ["TODO_VERIFY_algae_stock_unavailable"]


def test_build_toilet_room_constructs_enclosure_in_safe_batches():
    state = supported_construction_state()
    catalog = load_construction_catalog()
    first = build_toilet_room(state, catalog)
    assert len(first.actions) == 12
    assert {action["id"] for action in first.actions} == {"Tile"}
    assert "action_limit_12" in first.warnings

    add_built_tiles_to_state(state, first.actions)
    second = build_toilet_room(state, catalog)
    assert 0 < len(second.actions) <= 12
    assert {action["id"] for action in second.actions} == {"Tile"}
    add_built_tiles_to_state(state, second.actions)

    final = build_toilet_room(state, catalog)
    assert {action["id"] for action in final.actions} == {
        "Outhouse",
        "WashBasin",
        "Door",
    }
    assert len(final.actions) == 3
    assert final.warnings == ["Dirt_delivery_required_for_Outhouse"]


def test_build_toilet_room_honors_existing_building_unlock_and_stock():
    state = supported_construction_state()
    catalog = load_construction_catalog()
    state["building_list"] = [{"id": "Outhouse", "state": "built"}]
    assert build_toilet_room(state, catalog).warnings == [
        "existing_outhouse_left_unchanged"
    ]

    state["building_list"] = []
    catalog[0]["unlocked"] = False
    with pytest.raises(SkillPlanningError, match="building_locked"):
        build_oxygen_setup(state, catalog)

    catalog = load_construction_catalog()
    state["resources"]["materials"]["SandStone"] = 0
    with pytest.raises(SkillPlanningError, match="insufficient_material"):
        build_toilet_room(state, catalog)


def test_build_mess_area_uses_catalog_dining_tables_and_avoids_duplicates():
    state = supported_construction_state()
    state["dupes"] = [{"name": "Fixture 1"}, {"name": "Fixture 2"}]
    result = build_mess_area(state, load_construction_catalog())
    assert len(result.actions) == 2
    assert [action["id"] for action in result.actions] == [
        "DiningTable",
        "DiningTable",
    ]
    state["building_list"] = [
        {"id": action["id"], "state": "under_construction", "x": action["x"], "y": action["y"]}
        for action in result.actions
    ]
    assert build_mess_area(state, load_construction_catalog()).actions == []


def test_build_mess_area_checks_unlocked_building_materials_and_placement():
    state = supported_construction_state()
    catalog = load_construction_catalog()
    next(item for item in catalog if item["id"] == "DiningTable")["unlocked"] = False
    with pytest.raises(SkillPlanningError, match="building_locked"):
        build_mess_area(state, catalog)

    catalog = load_construction_catalog()
    state["resources"]["materials"]["ZincOre"] = 199
    with pytest.raises(SkillPlanningError, match="insufficient_material"):
        build_mess_area(state, catalog)

    blocked = supported_construction_state()
    blocked["world"]["map"] = ["X" * 41 for _ in range(41)]
    with pytest.raises(SkillPlanningError, match="no_valid_placement"):
        build_mess_area(blocked, load_construction_catalog())


def test_build_power_basic_plans_catalog_verified_generator_wire_and_battery():
    state = supported_construction_state()
    result = build_power_basic(state, load_construction_catalog())
    assert [action["id"] for action in result.actions[:2]] == [
        "ManualGenerator",
        "Battery",
    ]
    wires = [action for action in result.actions if action["id"] == "Wire"]
    assert len(wires) == 5
    assert len(result.actions) == 7
    assert len({action["elements"][0] for action in result.actions}) == 1
    assert result.warnings == ["basic_power_layout_not_tested_in_game"]


def test_build_power_basic_checks_unlocks_materials_and_map_support():
    state = supported_construction_state()
    catalog = load_construction_catalog()
    next(item for item in catalog if item["id"] == "Battery")["unlocked"] = False
    with pytest.raises(SkillPlanningError, match="building_locked"):
        build_power_basic(state, catalog)

    catalog = load_construction_catalog()
    state["resources"]["materials"]["ZincOre"] = 524
    with pytest.raises(SkillPlanningError, match="insufficient_material"):
        build_power_basic(state, catalog)

    blocked = supported_construction_state()
    blocked["world"]["map"] = ["X" * 41 for _ in range(41)]
    with pytest.raises(SkillPlanningError, match="no_valid_placement"):
        build_power_basic(blocked, load_construction_catalog())


def test_low_oxygen_builds_deoxidizer_near_dupe_with_available_catalog_materials():
    state = load_emergency_fixture("emergency_oxygen_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")

    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")

    assert plan["actions"] == [
        {
            "type": "build",
            "id": "MineralDeoxidizer",
            "x": 0,
            "y": -3,
            "orientation": "Neutral",
            "elements": ["Cuprite"],
            "priority": 5,
        }
    ]
    assert plan["skipped"] == []


def test_low_oxygen_skips_locked_or_insufficiently_stocked_building():
    state = load_emergency_fixture("emergency_oxygen_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    state["resources"]["materials"]["Cuprite"] = 199
    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")
    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "insufficient_material"}]

    state["resources"]["materials"]["Cuprite"] = 500
    catalog[0]["unlocked"] = False
    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")
    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "building_locked"}]


def test_existing_deoxidizer_warns_without_building_duplicate():
    state = load_emergency_fixture("emergency_oxygen_existing.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")
    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "thiếu_algae"}]

    state["building_list"][0]["stored"] = {"Algae": 0}
    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")
    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "thiếu_algae"}]

    del state["building_list"][0]["stored"]
    plan = plan_emergency_actions(state, catalog, "oxygen", "low_oxygen")
    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "thiếu_dữ_liệu_algae"}]


def test_low_food_raises_available_job_priorities_without_building():
    state = load_emergency_fixture("emergency_food_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    plan = plan_emergency_actions(state, catalog, "food", "food_stock_low")

    assert plan["actions"] == [
        {
            "type": "set_dupe_priority",
            "dupe": "Hungry Dupe",
            "group": group,
            "priority": 4,
        }
        for group in ("Farming", "Cook", "Ranching")
    ]
    assert all(action["type"] != "build" for action in plan["actions"])

    for action in plan["actions"]:
        state["dupes"][0]["job_priorities"][action["group"]] = action["priority"]
    assert plan_emergency_actions(state, catalog, "food", "food_stock_low")["actions"] == []


def test_high_stress_lowers_priorities_and_builds_only_facility_shortage():
    state = load_emergency_fixture("emergency_stress_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    plan = plan_emergency_actions(state, catalog, "stress", "dupe_high_stress")

    assert plan["actions"][:2] == [
        {
            "type": "set_dupe_priority",
            "dupe": "Stressed Dupe",
            "group": "Dig",
            "priority": 2,
        },
        {
            "type": "set_dupe_priority",
            "dupe": "Stressed Dupe",
            "group": "Build",
            "priority": 2,
        },
    ]
    builds = [action for action in plan["actions"] if action["type"] == "build"]
    assert [action["id"] for action in builds] == [
        "Bed",
        "Outhouse",
        "Outhouse",
        "WashBasin",
        "WashBasin",
    ]
    assert len({(action["x"], action["y"]) for action in builds}) == len(builds)
    assert all(action["elements"] == ["SandStone"] for action in builds)


def test_high_stress_skips_builds_when_material_budget_is_insufficient():
    state = load_emergency_fixture("emergency_stress_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    state["resources"]["materials"]["SandStone"] = 300

    plan = plan_emergency_actions(state, catalog, "stress", "dupe_high_stress")

    assert [action["id"] for action in plan["actions"] if action["type"] == "build"] == [
        "Bed",
        "WashBasin",
        "WashBasin",
    ]
    assert {
        (item.get("building"), item["reason"]) for item in plan["skipped"]
    } == {("Outhouse", "insufficient_material")}


def test_high_stress_does_not_repeat_existing_amenities_or_lowered_priorities():
    state = load_emergency_fixture("emergency_stress_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")
    for building_id in ("Bed", "Outhouse", "WashBasin"):
        state["building_list"].extend(
            [
                {"id": building_id, "x": 1, "y": 1, "state": "built"},
                {"id": building_id, "x": 2, "y": 1, "state": "under_construction"},
            ]
        )
    state["dupes"][0]["job_priorities"]["Dig"] = 1
    state["dupes"][0]["job_priorities"]["Build"] = 2

    plan = plan_emergency_actions(state, catalog, "stress", "dupe_high_stress")

    assert plan["actions"] == []


def test_temperature_emergency_is_warning_only():
    state = load_emergency_fixture("emergency_temperature_state.json")
    catalog = load_emergency_fixture("emergency_catalog.json")

    plan = plan_emergency_actions(
        state, catalog, "temperature", "temperature_high"
    )

    assert plan["actions"] == []
    assert plan["skipped"] == [{"reason": "temperature_warning_only"}]
