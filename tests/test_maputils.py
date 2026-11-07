import json
from pathlib import Path

import pytest

from agent.maputils import (
    cell_at_xy,
    find_empty_rectangle,
    is_gas,
    is_liquid,
    is_solid,
    is_vacuum,
    row_col_to_xy,
    state_metal_ores,
    state_map,
    xy_to_row_col,
)


FIXTURES = Path(__file__).parent / "fixtures"


def load_empty_map():
    return json.loads((FIXTURES / "empty_map.json").read_text(encoding="utf-8"))


def test_coordinate_conversion_uses_top_down_rows():
    origin = {"x": -20, "y": -20}
    assert row_col_to_xy(0, 0, origin) == (-20, 20)
    assert row_col_to_xy(40, 40, origin) == (20, -20)
    assert xy_to_row_col(0, 0, origin) == (20, 20)


def test_cell_classification_and_out_of_bounds():
    rows = ["#FGLVX."]
    origin = {"x": 0, "y": 0}
    assert [cell_at_xy(rows, origin, x, 0) for x in range(7)] == list("#FGLVX.")
    assert is_solid("#") and is_solid("F") and is_solid("X")
    assert is_gas("G")
    assert is_liquid("L")
    assert is_vacuum("V")
    assert cell_at_xy(rows, origin, 7, 0) is None


def test_find_empty_rectangle_returns_pivot_for_even_width():
    state = load_empty_map()
    rows, origin = state_map(state)
    assert len(rows) == 41 and all(len(row) == 41 for row in rows)
    placement = find_empty_rectangle(rows, origin, 2, 1)
    assert placement is not None
    assert placement["x"] == placement["left_x"]
    assert placement["width"] == 2


def test_find_rectangle_respects_floor_and_reserved_cells():
    state = load_empty_map()
    rows, origin = state_map(state)
    rows[-1] = "#" * 41
    assert find_empty_rectangle(rows, origin, 2, 1, require_floor=True) is not None
    assert find_empty_rectangle(rows, origin, 2, 1, reserved={(0, -19)}) is not None
    reserved = {(-20, -19), (-19, -19)}
    placement = find_empty_rectangle(rows, origin, 2, 1, reserved=reserved)
    assert placement is not None
    assert not all(
        (placement["left_x"] + offset, placement["bottom_y"]) in reserved
        for offset in range(placement["width"])
    )
    assert find_empty_rectangle(
        [".."], {"x": 0, "y": 0}, 2, 1, reserved={(0, 0), (1, 0)}
    ) is None


def test_invalid_map_is_rejected():
    with pytest.raises(ValueError, match="same non-zero width"):
        find_empty_rectangle(["..", "."], {"x": 0, "y": 0}, 1, 1)


def test_state_metal_ores_validates_map_and_element_legend():
    state = load_empty_map()
    state["world"]["map"][20] = state["world"]["map"][20][:20] + "#" + state["world"]["map"][20][21:]
    element_rows = ["." * 41 for _ in range(41)]
    element_rows[20] = element_rows[20][:20] + "a" + element_rows[20][21:]
    state["world"]["element_map"] = element_rows
    state["world"]["element_legend"] = {"a": "Cuprite"}
    state["world"]["metal_ores"] = [
        {"x": 0, "y": 0, "element": "Cuprite", "distance_from_telepad": 0},
        {"x": 1, "y": 0, "element": "Cuprite", "distance_from_telepad": 1},
    ]

    assert state_metal_ores(state) == [state["world"]["metal_ores"][0]]
