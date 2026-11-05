"""High-level planners that return actions without sending them to the game."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .catalog import (
    CatalogError,
    building_dimensions,
    choose_materials,
    get_building,
    material_categories,
)
from .maputils import (
    BUILDABLE_MAP_CELLS,
    cell_at_xy,
    find_empty_rectangle,
    find_empty_rectangle_candidates,
    state_map,
)


class SkillPlanningError(ValueError):
    """A skill could not produce a safe action list."""

    def __init__(self, reason: str, details: str | None = None) -> None:
        super().__init__(f"{reason}: {details}" if details else reason)
        self.reason = reason
        self.details = details


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
    tile_id: str | None,
    bed_count: int,
) -> list[dict[str, Any]]:
    """Plan a closed Barracks footprint without sending build actions."""
    if isinstance(bed_count, bool) or not isinstance(bed_count, int) or bed_count <= 0:
        raise SkillPlanningError("invalid_bed_count")
    if not isinstance(tile_id, str) or not tile_id:
        raise SkillPlanningError("tile_id_unconfigured")

    bed = _get_building(catalog, bed_id)
    door = _get_building(catalog, door_id)
    tile = _get_building(catalog, tile_id)
    bed_width, bed_height = building_dimensions(bed)
    door_width, door_height = building_dimensions(door)
    tile_width, tile_height = building_dimensions(tile)
    if (tile_width, tile_height) != (1, 1):
        raise SkillPlanningError("invalid_tile_dimensions")
    if door_width != 1 or door_height > bed_height:
        raise SkillPlanningError("door_does_not_fit_room")

    interior_width = max(bed_width * bed_count, math.ceil(12 / bed_height))
    room_size = interior_width * bed_height
    if room_size > 64:
        raise SkillPlanningError("barracks_size_out_of_range")

    rows, origin, center = _map_context(state)
    existing_tiles = _existing_tile_positions(state, tile_id)
    placement = _find_barracks_placement(
        rows,
        origin,
        interior_width,
        bed_height,
        door_height,
        existing_tiles,
        center,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")

    materials_by_key, selected_materials = _choose_combined_materials(
        state,
        (
            (bed, bed_count),
            (door, 1),
            (tile, len(placement["new_tiles"])),
        ),
    )

    actions = [
        _build_action(tile, state, x, y, _elements_for_building(tile, materials_by_key, selected_materials))
        for x, y in placement["new_tiles"]
    ]
    bed_left = placement["left_x"]
    bed_bottom = placement["bottom_y"]
    bed_elements = _elements_for_building(bed, materials_by_key, selected_materials)
    for bed_index in range(bed_count):
        bed_x = bed_left + bed_index * bed_width
        actions.append(
            _build_action(bed, state, _pivot_x(bed_x, bed_width), bed_bottom, bed_elements)
        )
    door_elements = _elements_for_building(door, materials_by_key, selected_materials)
    actions.append(
        _build_action(
            door,
            state,
            placement["door_x"],
            placement["door_y"],
            door_elements,
        )
    )
    return actions


def _material_group_key(category: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    name = category.get("category")
    options = category.get("options")
    if not isinstance(name, str) or not name:
        raise SkillPlanningError("invalid_material_category")
    if not isinstance(options, list) or any(not isinstance(option, str) for option in options):
        raise SkillPlanningError("invalid_material_options")
    return name.casefold(), tuple(sorted(option.casefold() for option in options))


def _choose_combined_materials(
    state: Mapping[str, Any],
    building_counts: Sequence[tuple[Mapping[str, Any], int]],
) -> tuple[dict[tuple[str, tuple[str, ...]], Mapping[str, Any]], dict[tuple[str, tuple[str, ...]], str]]:
    groups: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for building, count in building_counts:
        if count <= 0:
            continue
        for category in material_categories(building):
            key = _material_group_key(category)
            mass = category.get("mass_kg")
            if (
                isinstance(mass, bool)
                or not isinstance(mass, (int, float))
                or not math.isfinite(mass)
                or mass < 0
            ):
                raise SkillPlanningError(
                    "construction_mass_unavailable",
                    str(category.get("category", "unknown")),
                )
            group = groups.get(key)
            if group is None:
                group = {
                    "category": category["category"],
                    "options": list(category["options"]),
                    "mass_kg": 0.0,
                }
                groups[key] = group
            group["mass_kg"] += mass * count

    categories = list(groups.values())
    try:
        selected = choose_materials({"materials": categories}, state)
    except CatalogError as error:
        if error.reason == "insufficient_material":
            raise SkillPlanningError(
                error.reason,
                _material_shortfall_details(categories, state),
            ) from error
        raise SkillPlanningError(error.reason) from error

    selected_by_key = {
        key: element for key, element in zip(groups, selected)
    }
    return groups, selected_by_key


def _material_shortfall_details(
    categories: Sequence[Mapping[str, Any]], state: Mapping[str, Any]
) -> str:
    resources = state.get("resources")
    stock = resources.get("materials") if isinstance(resources, Mapping) else None
    stock_items = stock.items() if isinstance(stock, Mapping) else ()
    stock_by_name = {
        name.casefold(): amount
        for name, amount in stock_items
        if isinstance(name, str)
        and isinstance(amount, (int, float))
        and not isinstance(amount, bool)
        and math.isfinite(amount)
    }
    details: list[str] = []
    for category in categories:
        options = category.get("options", [])
        required = category.get("mass_kg", 0.0)
        best_option = max(
            options,
            key=lambda option: stock_by_name.get(option.casefold(), 0.0),
            default=None,
        )
        available = (
            stock_by_name.get(best_option.casefold(), 0.0)
            if isinstance(best_option, str)
            else 0.0
        )
        missing = max(0.0, required - available)
        details.append(
            f"{category.get('category', 'material')}: need {required:.1f} kg, "
            f"available {available:.1f} kg, missing {missing:.1f} kg"
        )
    return "; ".join(details)


def _elements_for_building(
    building: Mapping[str, Any],
    material_groups: Mapping[tuple[str, tuple[str, ...]], Mapping[str, Any]],
    selected_materials: Mapping[tuple[str, tuple[str, ...]], str],
) -> list[str]:
    elements: list[str] = []
    for category in material_categories(building):
        key = _material_group_key(category)
        if key not in material_groups or key not in selected_materials:
            raise SkillPlanningError("material_selection_incomplete")
        elements.append(selected_materials[key])
    return elements


def _existing_tile_positions(
    state: Mapping[str, Any], tile_id: str
) -> set[tuple[int, int]]:
    buildings = state.get("building_list")
    if not isinstance(buildings, list):
        return set()
    return {
        (entry["x"], entry["y"])
        for entry in buildings
        if isinstance(entry, Mapping)
        and entry.get("id") == tile_id
        and entry.get("state") in ("built", "under_construction")
        and isinstance(entry.get("x"), int)
        and not isinstance(entry.get("x"), bool)
        and isinstance(entry.get("y"), int)
        and not isinstance(entry.get("y"), bool)
    }


def _find_barracks_placement(
    rows: Sequence[str],
    origin: Mapping[str, int],
    interior_width: int,
    interior_height: int,
    door_height: int,
    existing_tiles: set[tuple[int, int]],
    center: tuple[int, int] | None,
) -> dict[str, Any] | None:
    candidates = find_empty_rectangle_candidates(
        rows,
        origin,
        interior_width,
        interior_height,
        center=center,
    )
    for candidate in candidates:
        left_x = candidate["left_x"]
        bottom_y = candidate["bottom_y"]
        right_x = left_x + interior_width - 1
        top_y = bottom_y + interior_height - 1
        door_slots = [
            (wall_x, door_y)
            for wall_x in (right_x + 1, left_x - 1)
            for door_y in range(bottom_y, top_y - door_height + 2)
        ]
        perimeter = {
            *((x, bottom_y - 1) for x in range(left_x - 1, right_x + 2)),
            *((x, top_y + 1) for x in range(left_x - 1, right_x + 2)),
            *((left_x - 1, y) for y in range(bottom_y, top_y + 1)),
            *((right_x + 1, y) for y in range(bottom_y, top_y + 1)),
        }

        for door_x, door_y in door_slots:
            door_cells = {(door_x, y) for y in range(door_y, door_y + door_height)}
            if any(cell_at_xy(rows, origin, x, y) not in BUILDABLE_MAP_CELLS for x, y in door_cells):
                continue

            new_tiles: list[tuple[int, int]] = []
            valid = True
            for x, y in sorted(perimeter):
                if (x, y) in door_cells:
                    continue
                cell = cell_at_xy(rows, origin, x, y)
                if cell in BUILDABLE_MAP_CELLS:
                    new_tiles.append((x, y))
                elif cell == "F" and (x, y) in existing_tiles:
                    continue
                else:
                    valid = False
                    break
            if valid:
                return {
                    **candidate,
                    "door_x": door_x,
                    "door_y": door_y,
                    "new_tiles": new_tiles,
                }
    return None


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
