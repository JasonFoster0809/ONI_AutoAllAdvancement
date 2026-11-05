import json
from pathlib import Path

import pytest

from agent.maputils import xy_to_row_col
from agent.skills import SkillPlanningError, build_barracks, build_bedroom


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_catalog():
    return load_fixture("barracks_catalog.json")


def plan(state, bed_count=2):
    return build_barracks(state, load_catalog(), "Bed", "Door", "Tile", bed_count)


def set_cell(state, x, y, value):
    rows = state["world"]["map"]
    row, column = xy_to_row_col(x, y, state["world"]["origin"], map_height=len(rows))
    rows[row] = rows[row][:column] + value + rows[row][column + 1 :]


def confine_to_footprint(state, obstacle_x, obstacle_y, obstacle_id):
    baseline = plan(state)
    interior_bed = next(action for action in baseline if action["id"] == "Bed")
    bed = next(item for item in load_catalog() if item["id"] == "Bed")
    room_width = max(bed["width"] * 2, 12 // bed["height"])
    left_x = interior_bed["x"] - (bed["width"] // 2)
    bottom_y = interior_bed["y"]
    right_x = left_x + room_width - 1
    top_y = bottom_y + bed["height"] - 1
    rows = ["X" * len(state["world"]["map"][0]) for _ in state["world"]["map"]]
    state["world"]["map"] = rows
    for y in range(bottom_y - 1, top_y + 2):
        for x in range(left_x - 1, right_x + 2):
            set_cell(state, x, y, ".")
    set_cell(state, obstacle_x, obstacle_y, "F")
    state["building_list"] = [
        {"id": obstacle_id, "x": obstacle_x, "y": obstacle_y, "state": "built"}
    ]


def test_empty_map_plans_room_with_size_valid_perimeter_and_pivots():
    actions = plan(load_fixture("barracks_clear.json"))
    tiles = [action for action in actions if action["id"] == "Tile"]
    beds = [action for action in actions if action["id"] == "Bed"]
    doors = [action for action in actions if action["id"] == "Door"]

    assert len(tiles) == 18
    assert len(beds) == 2
    assert len(doors) == 1
    assert all(action["orientation"] == "Neutral" for action in actions)
    assert all(action["elements"] == ["SandStone"] for action in actions)
    assert beds[1]["x"] - beds[0]["x"] == 3
    assert doors[0]["x"] in {beds[0]["x"] - 2, beds[1]["x"] + 2}


def test_barracks_rejects_map_without_enough_room():
    with pytest.raises(SkillPlanningError, match="no_valid_placement"):
        plan(load_fixture("barracks_no_space.json"))


def test_barracks_reports_aggregate_material_shortfall():
    with pytest.raises(SkillPlanningError, match="insufficient_material") as error:
        plan(load_fixture("barracks_insufficient_material.json"))
    assert "missing 220.0 kg" in str(error.value)


def test_existing_tile_is_reused_and_not_rebuilt():
    state = load_fixture("barracks_existing_tile.json")
    baseline = plan(state)
    existing = next(action for action in baseline if action["id"] == "Tile")
    set_cell(state, existing["x"], existing["y"], "F")
    state["building_list"].append(
        {
            "id": "Tile",
            "x": existing["x"],
            "y": existing["y"],
            "state": "built",
        }
    )

    updated = plan(state)
    assert sum(action["id"] == "Tile" for action in updated) == 17
    assert not any(
        action["id"] == "Tile"
        and (action["x"], action["y"]) == (existing["x"], existing["y"])
        for action in updated
    )


def test_non_tile_building_blocks_only_that_footprint():
    state = load_fixture("barracks_other_wall_building.json")
    baseline = plan(state)
    existing = next(action for action in baseline if action["id"] == "Tile")
    confine_to_footprint(state, existing["x"], existing["y"], "OtherBuilding")
    with pytest.raises(SkillPlanningError, match="no_valid_placement"):
        plan(state)


def test_bedroom_skill_remains_available():
    state = load_fixture("barracks_clear.json")
    state["world"]["map"][-1] = "#" * 20
    actions = build_bedroom(state, load_catalog(), "Bed", "Door")
    assert [action["id"] for action in actions] == ["Bed", "Door"]
