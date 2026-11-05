"""Coordinate and placement helpers for the ONI 41x41 map snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


BUILDABLE_MAP_CELLS = frozenset(".GV")
SOLID_MAP_CELLS = frozenset("#FX")


def _validate_map(map_rows: Sequence[str]) -> tuple[int, int]:
    if not map_rows or any(not isinstance(row, str) for row in map_rows):
        raise ValueError("map must be a non-empty sequence of strings")
    width = len(map_rows[0])
    if width == 0 or any(len(row) != width for row in map_rows):
        raise ValueError("map rows must have the same non-zero width")
    return width, len(map_rows)


def row_col_to_xy(
    row: int,
    column: int,
    origin: Mapping[str, int],
    *,
    map_height: int = 41,
) -> tuple[int, int]:
    """Convert top-down map indexes to world coordinates."""
    if map_height <= 0 or not 0 <= row < map_height or column < 0:
        raise ValueError("row or column is outside the map")
    return origin["x"] + column, origin["y"] + map_height - 1 - row


def xy_to_row_col(
    x: int,
    y: int,
    origin: Mapping[str, int],
    *,
    map_height: int = 41,
) -> tuple[int, int]:
    """Convert world coordinates to top-down map indexes."""
    row = map_height - 1 - (y - origin["y"])
    column = x - origin["x"]
    return row, column


def cell_at_xy(
    map_rows: Sequence[str], origin: Mapping[str, int], x: int, y: int
) -> str | None:
    width, height = _validate_map(map_rows)
    row, column = xy_to_row_col(x, y, origin, map_height=height)
    if 0 <= row < height and 0 <= column < width:
        return map_rows[row][column]
    return None


def is_solid(cell: str | None) -> bool:
    return cell in SOLID_MAP_CELLS


def is_gas(cell: str | None) -> bool:
    return cell == "G"


def is_liquid(cell: str | None) -> bool:
    return cell == "L"


def is_vacuum(cell: str | None) -> bool:
    return cell == "V"


def find_empty_rectangle(
    map_rows: Sequence[str],
    origin: Mapping[str, int],
    width: int,
    height: int,
    *,
    require_floor: bool = False,
    center: tuple[int, int] | None = None,
    reserved: set[tuple[int, int]] | None = None,
) -> dict[str, int] | None:
    """Find the nearest clear rectangle and return its pivot and lower-left."""
    candidates = find_empty_rectangle_candidates(
        map_rows,
        origin,
        width,
        height,
        center=center,
        reserved=reserved,
    )
    for candidate in candidates:
        if require_floor:
            floor_row = candidate["row"] + 1
            if floor_row >= len(map_rows) or any(
                map_rows[floor_row][column] not in SOLID_MAP_CELLS
                for column in range(candidate["column"], candidate["column"] + width)
            ):
                continue
        return candidate
    return None


def find_empty_rectangle_candidates(
    map_rows: Sequence[str],
    origin: Mapping[str, int],
    width: int,
    height: int,
    *,
    center: tuple[int, int] | None = None,
    reserved: set[tuple[int, int]] | None = None,
) -> list[dict[str, int]]:
    """Return all clear rectangles ordered by distance from the optional center."""
    map_width, map_height = _validate_map(map_rows)
    if width <= 0 or height <= 0:
        raise ValueError("rectangle dimensions must be positive")
    if width > map_width or height > map_height:
        return []

    reserved_cells = reserved or set()
    candidates: list[tuple[int, int, int, dict[str, int]]] = []
    for bottom_row in range(map_height - 1, height - 2, -1):
        top_row = bottom_row - height + 1
        for left_column in range(map_width - width + 1):
            clear = True
            for row in range(top_row, bottom_row + 1):
                for column in range(left_column, left_column + width):
                    if map_rows[row][column] not in BUILDABLE_MAP_CELLS:
                        clear = False
                        break
                    x, y = row_col_to_xy(row, column, origin, map_height=map_height)
                    if (x, y) in reserved_cells:
                        clear = False
                        break
                if not clear:
                    break
            if not clear:
                continue

            left_x = origin["x"] + left_column
            bottom_y = origin["y"] + map_height - 1 - bottom_row
            pivot_offset = width // 2 if width % 2 else width // 2 - 1
            pivot_x = left_x + pivot_offset
            distance = (
                abs(pivot_x - center[0]) + abs(bottom_y - center[1])
                if center is not None
                else 0
            )
            candidates.append(
                (
                    distance,
                    bottom_row,
                    left_column,
                    {
                        "x": pivot_x,
                        "y": bottom_y,
                        "left_x": left_x,
                        "bottom_y": bottom_y,
                        "width": width,
                        "height": height,
                        "row": bottom_row,
                        "column": left_column,
                    },
                )
            )

    candidates.sort(key=lambda item: item[:3])
    return [candidate for _, _, _, candidate in candidates]


def state_map(state: Mapping[str, Any]) -> tuple[list[str], dict[str, int]]:
    world = state.get("world")
    if not isinstance(world, Mapping):
        raise ValueError("state has no world object")
    map_rows = world.get("map")
    origin = world.get("origin")
    if not isinstance(origin, Mapping) or not isinstance(map_rows, list):
        raise ValueError("state world must contain map and origin")
    _validate_map(map_rows)
    if not isinstance(origin.get("x"), int) or not isinstance(origin.get("y"), int):
        raise ValueError("map origin must have integer x and y")
    return map_rows, {"x": origin["x"], "y": origin["y"]}
