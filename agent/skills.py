"""High-level planners that return actions without sending them to the game."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .catalog import CatalogError, building_dimensions, choose_materials, get_building
from .maputils import BUILDABLE_MAP_CELLS, SOLID_MAP_CELLS, cell_at_xy, find_empty_rectangle, state_map


class SkillPlanningError(ValueError):
    """A skill could not produce a safe action list."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _map_context(state: Mapping[str, Any]) -> tuple[list[str], dict[str, int], tuple[int, int] | None]:
    try:
        rows, origin = state_map(state)
    except (KeyError, TypeError, ValueError) as error:
        raise SkillPlanningError("invalid_map") from error

    world = state.get("world")
    start = world.get("start") if isinstance(world, Mapping) else None
    center = None
    if isinstance(start, Mapping) and isinstance(start.get("x"), int) and isinstance(start.get("y"), int):
        center = (start["x"], start["y"])
    return rows, origin, center


def _get_building(catalog: Sequence[Mapping[str, Any]], building_id: str) -> Mapping[str, Any]:
    try:
        building = get_building(catalog, building_id)
        if not building.get("unlocked", False):
            raise SkillPlanningError("building_locked")
        return building
    except CatalogError as error:
        raise SkillPlanningError(error.reason) from error


def _get_materials(building: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    try:
        return choose_materials(building, state)
    except CatalogError as error:
        raise SkillPlanningError(error.reason) from error


def _pivot_x(left_x: int, width: int) -> int:
    return left_x + (width // 2 if width % 2 else width // 2 - 1)


def _build_action(
    building: Mapping[str, Any], state: Mapping[str, Any], x: int, y: int, elements: list[str] | None = None
) -> dict[str, Any]:
    selected_elements = _get_materials(building, state) if elements is None else elements
    return {
        "type": "build",
        "id": building["id"],
        "x": x,
        "y": y,
        "orientation": "Neutral",
        "elements": selected_elements,
        "priority": 5,
    }


def build_bedroom(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    bed_id: str,
    door_id: str,
) -> list[dict[str, Any]]:
    """Plan a bed and door in one clear, supported area; does not send actions."""
    bed = _get_building(catalog, bed_id)
    door = _get_building(catalog, door_id)
    bed_width, bed_height = building_dimensions(bed)
    door_width, door_height = building_dimensions(door)
    rows, origin, center = _map_context(state)
    placement = find_empty_rectangle(
        rows,
        origin,
        bed_width + door_width,
        max(bed_height, door_height),
        require_floor=True,
        center=center,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")

    bed_materials = _get_materials(bed, state)
    door_materials = _get_materials(door, state)
    bed_left = placement["left_x"]
    door_left = bed_left + bed_width
    bottom_y = placement["bottom_y"]
    return [
        _build_action(bed, state, _pivot_x(bed_left, bed_width), bottom_y, bed_materials),
        _build_action(door, state, _pivot_x(door_left, door_width), bottom_y, door_materials),
    ]


def build_barracks(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    bed_id: str,
    door_id: str,
    tile_id: str | None = None,
) -> list[dict[str, Any]]:
    """Plan a bed and door, adding floor tiles only where support is absent."""
    bed = _get_building(catalog, bed_id)
    door = _get_building(catalog, door_id)
    bed_width, bed_height = building_dimensions(bed)
    door_width, door_height = building_dimensions(door)
    footprint_width = bed_width + door_width
    footprint_height = max(bed_height, door_height)
    rows, origin, center = _map_context(state)
    map_width = len(rows[0])
    map_height = len(rows)
    placements: list[tuple[int, int, int, list[int]]] = []

    for bottom_row in range(map_height - 1, footprint_height - 2, -1):
        top_row = bottom_row - footprint_height + 1
        for left_column in range(map_width - footprint_width + 1):
            clear = all(
                rows[row][column] in BUILDABLE_MAP_CELLS
                for row in range(top_row, bottom_row + 1)
                for column in range(left_column, left_column + footprint_width)
            )
            if not clear:
                continue

            left_x = origin["x"] + left_column
            bottom_y = origin["y"] + map_height - 1 - bottom_row
            unsupported_columns: list[int] = []
            supported = True
            for x in range(left_x, left_x + footprint_width):
                support_cell = cell_at_xy(rows, origin, x, bottom_y - 1)
                if support_cell in SOLID_MAP_CELLS:
                    continue
                if support_cell in BUILDABLE_MAP_CELLS:
                    unsupported_columns.append(x)
                    continue
                supported = False
                break
            if not supported:
                continue

            bed_pivot = _pivot_x(left_x, bed_width)
            distance = (
                abs(bed_pivot - center[0]) + abs(bottom_y - center[1])
                if center is not None
                else 0
            )
            placements.append((distance, bottom_row, left_column, unsupported_columns))

    if not placements:
        raise SkillPlanningError("no_valid_placement")

    _, bottom_row, left_column, unsupported_columns = min(placements)
    left_x = origin["x"] + left_column
    bottom_y = origin["y"] + map_height - 1 - bottom_row
    actions: list[dict[str, Any]] = []

    if unsupported_columns:
        if not isinstance(tile_id, str) or not tile_id:
            raise SkillPlanningError("tile_id_unconfigured")
        try:
            tile = _get_building(catalog, tile_id)
            tile_width, tile_height = building_dimensions(tile)
        except CatalogError as error:
            raise SkillPlanningError(error.reason) from error
        if (tile_width, tile_height) != (1, 1):
            raise SkillPlanningError("invalid_tile_dimensions")
        tile_materials = _get_materials(tile, state)
        actions.extend(
            _build_action(tile, state, x, bottom_y - 1, tile_materials)
            for x in unsupported_columns
        )

    bed_materials = _get_materials(bed, state)
    door_materials = _get_materials(door, state)
    actions.append(
        _build_action(bed, state, _pivot_x(left_x, bed_width), bottom_y, bed_materials)
    )
    door_left = left_x + bed_width
    actions.append(
        _build_action(door, state, _pivot_x(door_left, door_width), bottom_y, door_materials)
    )
    return actions


def build_research_area(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    research_center_id: str,
) -> list[dict[str, Any]]:
    """Plan one research-center placement on a supported clear footprint."""
    building = _get_building(catalog, research_center_id)
    width, height = building_dimensions(building)
    rows, origin, center = _map_context(state)
    placement = find_empty_rectangle(
        rows, origin, width, height, require_floor=True, center=center
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    return [_build_action(building, state, placement["x"], placement["y"])]


def dig_corridor(
    state: Mapping[str, Any], x1: int, y1: int, x2: int, y2: int
) -> list[dict[str, Any]]:
    """Plan an axis-aligned or deterministic L-shaped corridor without sending it."""
    rows, origin, _ = _map_context(state)
    path: list[tuple[int, int]] = []
    step_x = 1 if x2 >= x1 else -1
    for x in range(x1, x2 + step_x, step_x):
        path.append((x, y1))
    step_y = 1 if y2 >= y1 else -1
    for y in range(y1 + step_y, y2 + step_y, step_y):
        path.append((x2, y))

    actions: list[dict[str, Any]] = []
    for x, y in path:
        cell = cell_at_xy(rows, origin, x, y)
        if cell is None:
            raise SkillPlanningError("out_of_bounds")
        if cell == "#":
            actions.append({"type": "dig", "x": x, "y": y})
        elif cell == "F":
            raise SkillPlanningError("corridor_blocked_by_building")
        elif cell == "X":
            raise SkillPlanningError("corridor_undiggable")
        elif cell == "L":
            raise SkillPlanningError("corridor_through_liquid")
        elif cell not in ".GV":
            raise SkillPlanningError("invalid_map_cell")

    if not actions:
        raise SkillPlanningError("corridor_already_clear")
    return actions


def build_ladder_shaft(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    ladder_id: str,
    *,
    height: int = 6,
) -> list[dict[str, Any]]:
    """Plan a vertical run of single-cell ladders in a clear shaft."""
    if height <= 0:
        raise SkillPlanningError("invalid_height")
    building = _get_building(catalog, ladder_id)
    width, building_height = building_dimensions(building)
    if (width, building_height) != (1, 1):
        raise SkillPlanningError("invalid_ladder_dimensions")

    rows, origin, center = _map_context(state)
    placement = find_empty_rectangle(
        rows, origin, 1, height, require_floor=False, center=center
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")

    elements = _get_materials(building, state)
    return [
        _build_action(
            building,
            state,
            placement["x"],
            placement["bottom_y"] + offset,
            elements,
        )
        for offset in range(height)
    ]
