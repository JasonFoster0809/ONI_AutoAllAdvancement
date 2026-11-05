import json
from pathlib import Path

import pytest

from agent.skills import (
    SkillPlanningError,
    build_bedroom,
    build_ladder_shaft,
    build_research_area,
    dig_corridor,
)


FIXTURES = Path(__file__).parent / "fixtures"


def load_empty_map():
    return json.loads((FIXTURES / "empty_map.json").read_text(encoding="utf-8"))


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
            "materials": [{"category": "Rock", "options": ["SandStone"]}],
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
