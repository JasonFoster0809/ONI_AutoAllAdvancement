"""High-level planners that return actions without sending them to the game."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    is_liquid,
    row_col_to_xy,
    state_map,
    xy_to_row_col,
)


class SkillPlanningError(ValueError):
    """A skill could not produce a safe action list."""

    def __init__(self, reason: str, details: str | None = None) -> None:
        super().__init__(f"{reason}: {details}" if details else reason)
        self.reason = reason
        self.details = details


@dataclass(frozen=True)
class SkillPlan:
    actions: list[dict[str, Any]]
    warnings: list[str]


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


def _emergency_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _stored_element_mass(stored: Any, element: str) -> float | None:
    if isinstance(stored, Mapping):
        return _emergency_number(stored.get(element))
    if isinstance(stored, list):
        for item in stored:
            if isinstance(item, Mapping) and item.get("element") == element:
                return _emergency_number(item.get("kg"))
    return None


def _room_cells(
    state: Mapping[str, Any], center: tuple[int, int]
) -> tuple[list[str], dict[str, int], set[tuple[int, int]]]:
    try:
        rows, origin = state_map(state)
    except (KeyError, TypeError, ValueError) as error:
        raise SkillPlanningError("invalid_map") from error

    start_cell = cell_at_xy(rows, origin, center[0], center[1])
    if start_cell not in BUILDABLE_MAP_CELLS:
        raise SkillPlanningError("dupe_room_unavailable")
    start_row, start_column = xy_to_row_col(
        center[0], center[1], origin, map_height=len(rows)
    )
    pending = [(start_row, start_column)]
    visited = {pending[0]}
    cells: set[tuple[int, int]] = set()
    while pending:
        row, column = pending.pop()
        cells.add(row_col_to_xy(row, column, origin, map_height=len(rows)))
        for neighbor in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            neighbor_row, neighbor_column = neighbor
            if (
                neighbor in visited
                or not 0 <= neighbor_row < len(rows)
                or not 0 <= neighbor_column < len(rows[0])
                or rows[neighbor_row][neighbor_column] not in BUILDABLE_MAP_CELLS
            ):
                continue
            visited.add(neighbor)
            pending.append(neighbor)
    return rows, origin, cells


def _find_room_placement(
    rows: list[str],
    origin: Mapping[str, int],
    room_cells: set[tuple[int, int]],
    center: tuple[int, int],
    width: int,
    height: int,
    reserved: set[tuple[int, int]],
) -> dict[str, int] | None:
    for candidate in find_empty_rectangle_candidates(
        rows,
        origin,
        width,
        height,
        center=center,
        reserved=reserved,
    ):
        floor_row = candidate["row"] + 1
        if floor_row >= len(rows) or any(
            rows[floor_row][column] not in {"#", "F", "X"}
            for column in range(candidate["column"], candidate["column"] + width)
        ):
            continue
        footprint = {
            (candidate["left_x"] + dx, candidate["bottom_y"] + dy)
            for dx in range(width)
            for dy in range(height)
        }
        if footprint <= room_cells:
            return candidate
    return None


def _emergency_materials(
    building: Mapping[str, Any],
    state: Mapping[str, Any],
    stock_budget: dict[str, tuple[str, float]],
) -> list[str]:
    categories = material_categories(building)
    if not categories:
        return []

    budget = dict(stock_budget)
    selected: list[str] = []
    for category in categories:
        required_mass = _emergency_number(category.get("mass_kg"))
        if required_mass is None or required_mass < 0:
            raise SkillPlanningError("material_mass_unavailable")
        options = category.get("options")
        if not isinstance(options, list) or any(
            not isinstance(option, str) for option in options
        ):
            raise SkillPlanningError("invalid_material_options")
        choice = None
        for option in options:
            stock_item = budget.get(option.casefold())
            if stock_item is not None and stock_item[1] >= required_mass:
                choice = stock_item
                break
        if choice is None:
            raise SkillPlanningError("insufficient_material")
        selected.append(choice[0])
        budget[choice[0].casefold()] = (choice[0], choice[1] - required_mass)

    stock_budget.clear()
    stock_budget.update(budget)
    return selected


def _emergency_stock_budget(
    state: Mapping[str, Any],
) -> dict[str, tuple[str, float]]:
    resources = state.get("resources")
    stock = resources.get("materials") if isinstance(resources, Mapping) else None
    if not isinstance(stock, Mapping):
        raise SkillPlanningError("material_inventory_unavailable")
    return {
        name.casefold(): (name, amount)
        for name, value in stock.items()
        if isinstance(name, str)
        and (amount := _emergency_number(value)) is not None
        and amount >= 0
    }


def _live_dupes(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    dupes = state.get("dupes")
    return [dupe for dupe in dupes if isinstance(dupe, Mapping)] if isinstance(dupes, list) else []


def _known_buildings(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = state.get("building_list")
    if not isinstance(entries, list) or any(not isinstance(item, Mapping) for item in entries):
        raise SkillPlanningError("building_list_unavailable")
    return list(entries)


def _element_mass(stored: Any, element: str) -> float | None:
    if isinstance(stored, Mapping):
        value = stored.get(element, 0)
        return _emergency_number(value)
    if isinstance(stored, list):
        total = 0.0
        for item in stored:
            if not isinstance(item, Mapping):
                return None
            if item.get("element") == element:
                mass = _emergency_number(item.get("kg"))
                if mass is None or mass < 0:
                    return None
                total += mass
        return total
    return None


def build_oxygen_setup(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Build one unlocked deoxidizer or report stock status for an existing one."""
    deoxidizer = _get_building(catalog, "MineralDeoxidizer")
    existing = [
        entry
        for entry in _known_buildings(state)
        if entry.get("id") == "MineralDeoxidizer"
    ]
    for entry in existing:
        if entry.get("state") == "under_construction":
            return SkillPlan([], ["mineral_deoxidizer_pending"])
    built = [entry for entry in existing if entry.get("state") == "built"]
    if built:
        masses: list[float] = []
        for entry in built:
            if "stored" not in entry:
                return SkillPlan([], ["TODO_VERIFY_algae_stock_unavailable"])
            mass = _element_mass(entry["stored"], "Algae")
            if mass is None:
                return SkillPlan([], ["TODO_VERIFY_algae_stock_unreadable"])
            masses.append(mass)
        if sum(masses) <= 0:
            return SkillPlan([], ["supply_Algae_to_existing_MineralDeoxidizer"])
        return SkillPlan([], ["existing_MineralDeoxidizer_has_stored_Algae"])

    rows, origin, center = _map_context(state)
    width, height = building_dimensions(deoxidizer)
    placement = find_empty_rectangle(
        rows,
        origin,
        width,
        height,
        require_floor=True,
        center=center,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    action = _build_action(deoxidizer, state, placement["x"], placement["y"])
    return SkillPlan([action], ["Algae_delivery_required_after_construction"])


def build_mess_area(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Add one catalog-verified DiningTable per live dupe, up to 12 this turn."""
    table = _get_building(catalog, "DiningTable")
    entries = _known_buildings(state)
    existing_count = sum(
        entry.get("id") == "DiningTable"
        and entry.get("state") in {"built", "under_construction"}
        for entry in entries
    )
    target_count = max(1, len(_live_dupes(state)))
    shortage = max(0, target_count - existing_count)
    if shortage == 0:
        return SkillPlan([], [])

    width, height = building_dimensions(table)
    rows, origin, center = _map_context(state)
    candidates = find_empty_rectangle_candidates(
        rows,
        origin,
        width,
        height,
        center=center,
    )
    placements: list[dict[str, int]] = []
    for candidate in candidates:
        if len(placements) >= min(shortage, 12):
            break
        if candidate["row"] + 1 >= len(rows) or any(
            rows[candidate["row"] + 1][column] not in {"#", "F", "X"}
            for column in range(candidate["column"], candidate["column"] + width)
        ):
            continue
        placements.append(candidate)
    if len(placements) < min(shortage, 12):
        raise SkillPlanningError("no_valid_placement")

    materials_by_key, selected_materials = _choose_combined_materials(
        state,
        ((table, len(placements)),),
    )
    elements = _elements_for_building(table, materials_by_key, selected_materials)
    actions = [
        _build_action(table, state, placement["x"], placement["y"], elements)
        for placement in placements
    ]
    warnings = ["action_limit_12"] if shortage > len(actions) else []
    return SkillPlan(actions, warnings)


def build_toilet_room(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Build a tiled, door-enclosed Latrine footprint in batches of at most 12."""
    entries = _known_buildings(state)
    if any(
        entry.get("id") == "Outhouse"
        and entry.get("state") in {"built", "under_construction"}
        for entry in entries
    ):
        return SkillPlan([], ["existing_outhouse_left_unchanged"])

    outhouse = _get_building(catalog, "Outhouse")
    basin = _get_building(catalog, "WashBasin")
    door = _get_building(catalog, "Door")
    tile = _get_building(catalog, "Tile")
    outhouse_width, outhouse_height = building_dimensions(outhouse)
    basin_width, basin_height = building_dimensions(basin)
    door_width, door_height = building_dimensions(door)
    tile_width, tile_height = building_dimensions(tile)
    if (tile_width, tile_height) != (1, 1) or door_width != 1:
        raise SkillPlanningError("invalid_enclosure_dimensions")
    if outhouse_height != basin_height or outhouse_width + basin_width > 6:
        raise SkillPlanningError("toilet_room_layout_unavailable")

    rows, origin, center = _map_context(state)
    existing_tiles = _existing_tile_positions(state, "Tile")
    placement = _find_barracks_placement(
        rows,
        origin,
        6,
        3,
        door_height,
        existing_tiles,
        center,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")

    new_tiles = placement["new_tiles"]
    if new_tiles:
        tile_batch = new_tiles[:12]
        materials_by_key, selected_materials = _choose_combined_materials(
            state,
            ((tile, len(tile_batch)),),
        )
        elements = _elements_for_building(tile, materials_by_key, selected_materials)
        actions = [
            _build_action(tile, state, x, y, elements)
            for x, y in tile_batch
        ]
        warnings = ["enclosure_build_continues_after_state_ack"]
        if len(new_tiles) > len(tile_batch):
            warnings.append("action_limit_12")
        return SkillPlan(actions, warnings)

    outhouse_x = placement["left_x"] + 2
    basin_x = placement["left_x"]
    if placement["door_x"] == placement["left_x"] - 1:
        basin_x = placement["left_x"] + 4
    materials_by_key, selected_materials = _choose_combined_materials(
        state,
        ((outhouse, 1), (basin, 1), (door, 1)),
    )
    actions = [
        _build_action(
            outhouse,
            state,
            _pivot_x(outhouse_x, outhouse_width),
            placement["bottom_y"],
            _elements_for_building(outhouse, materials_by_key, selected_materials),
        ),
        _build_action(
            basin,
            state,
            _pivot_x(basin_x, basin_width),
            placement["bottom_y"],
            _elements_for_building(basin, materials_by_key, selected_materials),
        ),
        _build_action(
            door,
            state,
            placement["door_x"],
            placement["door_y"],
            _elements_for_building(door, materials_by_key, selected_materials),
        ),
    ]
    return SkillPlan(actions, ["Dirt_delivery_required_for_Outhouse"])


def build_power_basic(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Place a generator, its wire row, and battery on a supported clear footprint."""
    generator = _get_building(catalog, "ManualGenerator")
    wire = _get_building(catalog, "Wire")
    battery = _get_building(catalog, "Battery")
    generator_width, generator_height = building_dimensions(generator)
    wire_width, wire_height = building_dimensions(wire)
    battery_width, battery_height = building_dimensions(battery)
    if (wire_width, wire_height) != (1, 1):
        raise SkillPlanningError("invalid_wire_dimensions")

    rows, origin, center = _map_context(state)
    layout_width = generator_width + 2 + battery_width
    layout_height = max(generator_height, battery_height)
    placement = find_empty_rectangle(
        rows,
        origin,
        layout_width,
        layout_height,
        require_floor=True,
        center=center,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")

    battery_x = placement["left_x"] + generator_width + 2
    materials_by_key, selected_materials = _choose_combined_materials(
        state,
        ((generator, 1), (battery, 1), (wire, layout_width)),
    )
    actions = [
        _build_action(
            generator,
            state,
            _pivot_x(placement["left_x"], generator_width),
            placement["bottom_y"],
            _elements_for_building(generator, materials_by_key, selected_materials),
        ),
        _build_action(
            battery,
            state,
            _pivot_x(battery_x, battery_width),
            placement["bottom_y"],
            _elements_for_building(battery, materials_by_key, selected_materials),
        ),
    ]
    wire_elements = _elements_for_building(wire, materials_by_key, selected_materials)
    actions.extend(
        _build_action(wire, state, placement["left_x"] + offset, placement["bottom_y"], wire_elements)
        for offset in range(layout_width)
    )
    return SkillPlan(actions, ["basic_power_layout_not_tested_in_game"])


_FOOD_BUILDING_IDS = frozenset(
    {"PlanterBox", "FarmTile", "CookingStation", "RationBox"}
)
_BASIC_SURVIVAL_FOOD_KCAL_PER_DUPE = 1000.0
_BASIC_SURVIVAL_MAX_ACTIONS = 12


def _basic_survival_oxygen_needed(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    oxygen_min_g: float | None = None,
) -> bool | None:
    buildings = state.get("building_list")
    if (
        not isinstance(buildings, list)
        or any(
            not isinstance(item, Mapping)
            or "id" not in item
            or "state" not in item
            for item in buildings
        )
    ):
        return None
    try:
        deoxidizer = _catalog_building(catalog, "MineralDeoxidizer")
    except SkillPlanningError:
        return None

    oxygen_low: bool | None = None
    oxygen = state.get("environment")
    oxygen_value = (
        _emergency_number(oxygen.get("oxygen_avg_g"))
        if isinstance(oxygen, Mapping)
        else None
    )
    threshold = _emergency_number(oxygen_min_g)
    if oxygen_value is not None and threshold is not None:
        oxygen_low = oxygen_value < threshold

    alerts = state.get("alerts")
    oxygen_alert: bool | None = None
    if isinstance(alerts, list):
        oxygen_alert = False
        for alert in alerts:
            if not isinstance(alert, Mapping) or not isinstance(alert.get("type"), str):
                oxygen_alert = None
                continue
            alert_type = alert["type"].casefold()
            if "oxygen" in alert_type or "oxy" in alert_type:
                oxygen_alert = True
                break

    machines = [
        item
        for item in buildings
        if isinstance(item, Mapping)
        and item.get("id") == deoxidizer.get("id")
        and item.get("state") == "built"
    ]
    has_algae: bool | None
    has_powered: bool | None
    if not machines:
        has_algae = None
        has_powered = None
    else:
        masses = [
            _element_mass(item.get("stored"), "Algae")
            if "stored" in item
            else None
            for item in machines
        ]
        has_algae = (
            True if any(mass is not None and mass > 0 for mass in masses)
            else False if all(mass is not None for mass in masses)
            else None
        )
        powered_values = [item.get("powered") for item in machines]
        has_powered = (
            True if any(value is True for value in powered_values)
            else False if all(isinstance(value, bool) for value in powered_values)
            else None
        )

    algae_missing = not has_algae if has_algae is not None else None
    power_missing = not has_powered if has_powered is not None else None
    shortage_signals = (oxygen_low, oxygen_alert, algae_missing, power_missing)
    if oxygen_low is True or oxygen_alert is True:
        return True
    if algae_missing is True or power_missing is True:
        resources = state.get("resources")
        materials = resources.get("materials") if isinstance(resources, Mapping) else None
        algae = (
            _emergency_number(materials.get("Algae"))
            if isinstance(materials, Mapping)
            else None
        )
        if algae is None or algae < 0:
            return None
        return True
    return False if all(signal is False for signal in shortage_signals) else None


def _basic_survival_power_needed(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> bool | None:
    buildings = state.get("building_list")
    if not isinstance(buildings, list) or any(
        not isinstance(item, Mapping) for item in buildings
    ):
        return None
    if not buildings:
        return False
    if any(not isinstance(item.get("powered"), bool) for item in buildings):
        return None
    unpowered = [item for item in buildings if item.get("powered") is False]
    if not unpowered:
        return False
    if any("state" not in item for item in unpowered):
        return None
    needs_power = any(item.get("state") == "built" for item in unpowered)
    if not needs_power:
        return False
    power = state.get("power")
    if not isinstance(power, Mapping):
        return None
    potential = _emergency_number(power.get("watts_potential"))
    generated = _emergency_number(power.get("watts_generated"))
    if potential is None or generated is None or potential < 0 or generated < 0:
        return None
    if potential > 0 or generated > 0:
        return False
    if any(
        isinstance(item, Mapping)
        and item.get("id") == "ManualGenerator"
        and item.get("state") in {"built", "under_construction"}
        for item in buildings
    ):
        return False
    try:
        for building_id in ("ManualGenerator", "Wire", "Battery"):
            _catalog_building(catalog, building_id)
    except SkillPlanningError:
        return False
    return True


def _basic_survival_food_research(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    food_kcal_per_dupe: float,
) -> tuple[dict[str, Any] | None, str | None]:
    dupes = state.get("dupes")
    resources = state.get("resources")
    if not isinstance(dupes, list) or not dupes or not isinstance(resources, Mapping):
        return None, "food_shortage_unknown"
    food_kcal = _emergency_number(resources.get("food_kcal"))
    if food_kcal is None:
        return None, "food_shortage_unknown"
    if food_kcal >= len(dupes) * food_kcal_per_dupe:
        return None, None

    research = state.get("research")
    techs = research.get("techs") if isinstance(research, Mapping) else None
    if not isinstance(techs, list):
        return None, "food_research_unknown"
    catalog_by_id = {
        item.get("id"): item
        for item in catalog
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    known_food_ids = {
        building_id
        for building_id in _FOOD_BUILDING_IDS
        if building_id in catalog_by_id
    }
    if not known_food_ids:
        return None, "food_catalog_unknown"
    if any(
        not isinstance(catalog_by_id[building_id].get("unlocked"), bool)
        for building_id in known_food_ids
    ):
        return None, "food_catalog_unknown"
    locked_food_ids = {
        building_id
        for building_id in known_food_ids
        if catalog_by_id[building_id].get("unlocked") is False
    }
    if not locked_food_ids:
        return None, "no_locked_food_building"
    for tech in techs:
        if not isinstance(tech, Mapping):
            continue
        tech_id = tech.get("id")
        unlocks = tech.get("unlocks")
        if (
            isinstance(tech_id, str)
            and tech.get("complete") is False
            and tech.get("ready") is True
            and isinstance(unlocks, list)
            and any(building_id in unlocks for building_id in locked_food_ids)
        ):
            return {"type": "set_research", "tech": tech_id}, None
    return None, "food_tech_not_ready"


def basic_survival_needed(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    food_kcal_per_dupe: float = _BASIC_SURVIVAL_FOOD_KCAL_PER_DUPE,
    oxygen_min_g: float | None = None,
) -> bool | None:
    """Return whether a verified basic-survival shortage has a safe response."""
    signals = [
        _basic_survival_oxygen_needed(state, catalog, oxygen_min_g),
        _basic_survival_power_needed(state, catalog),
    ]
    food_action, food_reason = _basic_survival_food_research(
        state, catalog, food_kcal_per_dupe
    )
    if food_action is not None:
        return True
    if food_reason in {
        "food_shortage_unknown",
        "food_research_unknown",
        "food_catalog_unknown",
    }:
        signals.append(None)
    else:
        signals.append(False)
    if any(signal is True for signal in signals):
        return True
    return None if any(signal is None for signal in signals) else False


def build_basic_survival(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    food_kcal_per_dupe: float = _BASIC_SURVIVAL_FOOD_KCAL_PER_DUPE,
    oxygen_min_g: float | None = None,
) -> SkillPlan:
    """Plan bounded oxygen, power, and food-research actions from known data."""
    actions: list[dict[str, Any]] = []
    warnings: list[str] = []
    dupes = _live_dupes(state)
    buildings = _known_buildings(state)

    try:
        deoxidizer = _catalog_building(catalog, "MineralDeoxidizer")
        existing = [
            item
            for item in buildings
            if item.get("id") == deoxidizer.get("id")
            and item.get("state") in {"built", "under_construction"}
        ]
        oxygen_needed = _basic_survival_oxygen_needed(
            state, catalog, oxygen_min_g
        )
        if oxygen_needed is None:
            warnings.append("oxygen_status_unknown")
        elif oxygen_needed:
            if any(
                item.get("id") == deoxidizer.get("id")
                and item.get("state") == "under_construction"
                for item in existing
            ):
                warnings.append("mineral_deoxidizer_under_construction")
            else:
                resources = state.get("resources")
                materials = (
                    resources.get("materials")
                    if isinstance(resources, Mapping)
                    else None
                )
                algae = (
                    _emergency_number(materials.get("Algae"))
                    if isinstance(materials, Mapping)
                    else None
                )
                if algae is None:
                    warnings.append("algae_stock_unknown_no_deoxidizer_build")
                elif algae <= 0:
                    warnings.append("algae_stock_empty_no_deoxidizer_build")
                else:
                    try:
                        rows, origin, _ = _map_context(state)
                        wire = _catalog_building(catalog, "Wire")
                        wire_width, wire_height = building_dimensions(wire)
                        wire_cells = {
                            (entry["x"] + dx, entry["y"] + dy)
                            for entry in buildings
                            if entry.get("id") == wire.get("id")
                            and entry.get("state") == "built"
                            and isinstance(entry.get("x"), int)
                            and not isinstance(entry.get("x"), bool)
                            and isinstance(entry.get("y"), int)
                            and not isinstance(entry.get("y"), bool)
                            for dx in range(wire_width)
                            for dy in range(wire_height)
                        }
                        if not wire_cells:
                            warnings.append("no_powered_slot_TODO_VERIFY")
                        else:
                            reserved = _reserved_building_cells(state, catalog)
                            stock_budget = _emergency_stock_budget(state)
                            placement = None
                            for dupe in dupes:
                                room_x = dupe.get("room_x")
                                room_y = dupe.get("room_y")
                                if room_x is None:
                                    room_x = dupe.get("x")
                                if room_y is None:
                                    room_y = dupe.get("y")
                                if not all(
                                    isinstance(value, int) and not isinstance(value, bool)
                                    for value in (room_x, room_y)
                                ):
                                    continue
                                _, _, room_cells = _room_cells(state, (room_x, room_y))
                                width, height = building_dimensions(deoxidizer)
                                for candidate in find_empty_rectangle_candidates(
                                    rows,
                                    origin,
                                    width,
                                    height,
                                    center=(room_x, room_y),
                                    reserved=reserved,
                                ):
                                    floor_row = candidate["row"] + 1
                                    if floor_row >= len(rows) or any(
                                        rows[floor_row][column] not in {"#", "F", "X"}
                                        for column in range(
                                            candidate["column"],
                                            candidate["column"] + width,
                                        )
                                    ):
                                        continue
                                    footprint = {
                                        (candidate["left_x"] + dx, candidate["bottom_y"] + dy)
                                        for dx in range(width)
                                        for dy in range(height)
                                    }
                                    adjacent = {
                                        (x + ox, y + oy)
                                        for x, y in footprint
                                        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                                    }
                                    if footprint <= room_cells and adjacent & wire_cells:
                                        placement = candidate
                                        break
                                if placement is not None:
                                    break
                            if placement is None:
                                warnings.append("no_powered_slot_TODO_VERIFY")
                            else:
                                materials = _emergency_materials(
                                    deoxidizer, state, stock_budget
                                )
                                actions.append(
                                    _build_action(
                                        deoxidizer,
                                        state,
                                        placement["x"],
                                        placement["y"],
                                        materials,
                                    )
                                )
                                warnings.append("deoxidizer_Algae_consumption_rate_TODO_VERIFY")
                    except SkillPlanningError as error:
                        if error.reason in {"building_unavailable", "building_locked"}:
                            warnings.append("no_powered_slot_TODO_VERIFY")
                        else:
                            warnings.append(f"oxygen_build_skipped:{error.reason}")
    except SkillPlanningError as error:
        warnings.append(f"oxygen_status_unknown:{error.reason}")

    if len(actions) < _BASIC_SURVIVAL_MAX_ACTIONS:
        power_needed = _basic_survival_power_needed(state, catalog)
        if power_needed is True:
            try:
                power_plan = build_power_basic(state, catalog)
            except SkillPlanningError as error:
                warnings.append(f"power_build_skipped:{error.reason}")
            else:
                if len(actions) + len(power_plan.actions) <= _BASIC_SURVIVAL_MAX_ACTIONS:
                    actions.extend(power_plan.actions)
                    warnings.extend(power_plan.warnings)
                    warnings.append("power_output_and_layout_values_TODO_VERIFY")
                else:
                    warnings.append("power_setup_exceeds_action_limit")
        elif power_needed is None:
            warnings.append("power_status_unknown")

    if len(actions) < _BASIC_SURVIVAL_MAX_ACTIONS:
        food_action, food_warning = _basic_survival_food_research(
            state, catalog, food_kcal_per_dupe
        )
        if food_action is not None:
            actions.append(food_action)
            warnings.append(
                "food_kcal_per_dupe_threshold_TODO_VERIFY"
            )
        elif food_warning is not None:
            warnings.append(food_warning)
    if len(actions) > _BASIC_SURVIVAL_MAX_ACTIONS:
        actions = actions[:_BASIC_SURVIVAL_MAX_ACTIONS]
        warnings.append("action_limit_12")
    return SkillPlan(actions, list(dict.fromkeys(warnings)))


def build_water_setup(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Plan a liquid pump near mapped liquid and one wash basin."""
    pump = _get_building(catalog, "LiquidPumpingStation")
    basin = _get_building(catalog, "WashBasin")
    pump_width, pump_height = building_dimensions(pump)
    basin_width, basin_height = building_dimensions(basin)
    entries = _known_buildings(state)
    pump_entry = next(
        (
            entry for entry in entries
            if entry.get("id") == "LiquidPumpingStation"
            and entry.get("state") in {"built", "under_construction"}
        ),
        None,
    )
    basin_exists = any(
        entry.get("id") == "WashBasin"
        and entry.get("state") in {"built", "under_construction"}
        for entry in entries
    )
    if pump_entry is not None and basin_exists:
        return SkillPlan([], [])

    rows, origin, center = _map_context(state)
    reserved = _reserved_building_cells(state, catalog)
    pump_placement: Mapping[str, int] | None = None
    if pump_entry is None:
        liquid_cells = [
            row_col_to_xy(row, column, origin, map_height=len(rows))
            for row, map_row in enumerate(rows)
            for column, cell in enumerate(map_row)
            if is_liquid(cell)
        ]
        if not liquid_cells:
            raise SkillPlanningError("liquid_source_unavailable")
        candidates = [
            candidate
            for candidate in find_empty_rectangle_candidates(
                rows,
                origin,
                pump_width,
                pump_height,
                center=liquid_cells[0],
                reserved=reserved,
            )
            if candidate["row"] + 1 < len(rows)
            and all(
                rows[candidate["row"] + 1][column] in {"#", "F", "X"}
                for column in range(
                    candidate["column"], candidate["column"] + pump_width
                )
            )
            and min(
                abs(candidate["left_x"] + dx - liquid_x)
                + abs(candidate["bottom_y"] + dy - liquid_y)
                for liquid_x, liquid_y in liquid_cells
                for dx in range(pump_width)
                for dy in range(pump_height)
            ) <= 1
        ]
        if not candidates:
            raise SkillPlanningError("no_pump_placement_near_liquid")
        pump_placement = candidates[0]
        pump_center = (pump_placement["x"], pump_placement["y"])
        for dx in range(pump_width):
            for dy in range(pump_height):
                reserved.add(
                    (
                        pump_placement["left_x"] + dx,
                        pump_placement["bottom_y"] + dy,
                    )
                )
    else:
        pump_x, pump_y = pump_entry.get("x"), pump_entry.get("y")
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (pump_x, pump_y)
        ):
            raise SkillPlanningError("existing_pump_position_unknown")
        pump_center = (pump_x, pump_y)

    basin_placement: Mapping[str, int] | None = None
    if not basin_exists:
        basin_candidates = [
            candidate
            for candidate in find_empty_rectangle_candidates(
                rows,
                origin,
                basin_width,
                basin_height,
                center=pump_center if pump_center else center,
                reserved=reserved,
            )
            if candidate["row"] + 1 < len(rows)
            and all(
                rows[candidate["row"] + 1][column] in {"#", "F", "X"}
                for column in range(
                    candidate["column"], candidate["column"] + basin_width
                )
            )
        ]
        if not basin_candidates:
            raise SkillPlanningError("no_basin_placement")
        basin_placement = basin_candidates[0]

    builds = []
    if pump_placement is not None:
        builds.append((pump, 1))
    if basin_placement is not None:
        builds.append((basin, 1))
    materials_by_key, selected_materials = _choose_combined_materials(
        state, builds
    )
    actions: list[dict[str, Any]] = []
    if pump_placement is not None:
        actions.append(
            _build_action(
                pump,
                state,
                pump_placement["x"],
                pump_placement["y"],
                _elements_for_building(pump, materials_by_key, selected_materials),
            )
        )
    if basin_placement is not None:
        actions.append(
            _build_action(
                basin,
                state,
                basin_placement["x"],
                basin_placement["y"],
                _elements_for_building(basin, materials_by_key, selected_materials),
            )
        )
    return SkillPlan(
        actions,
        [
            "pump_placement_uses_mapped_liquid_proximity_heuristic",
            "WashBasin_requires_water_delivery",
        ],
    )


def build_food_basic(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Plan one unlocked PlanterBox; seeds and planting remain separate."""
    planter = next(
        (item for item in catalog if item.get("id") == "PlanterBox"),
        None,
    )
    if planter is None or planter.get("unlocked") is not True:
        raise SkillPlanningError("TODO_NOT_IMPLEMENTED_food_building_unavailable")
    planter = _get_building(catalog, "PlanterBox")
    if any(
        entry.get("id") == "PlanterBox"
        and entry.get("state") in {"built", "under_construction"}
        for entry in _known_buildings(state)
    ):
        return SkillPlan([], [])
    width, height = building_dimensions(planter)
    rows, origin, center = _map_context(state)
    placement = next(
        (
            candidate
            for candidate in find_empty_rectangle_candidates(
                rows, origin, width, height, center=center
            )
            if candidate["row"] + 1 < len(rows)
            and all(
                rows[candidate["row"] + 1][column] in {"#", "F", "X"}
                for column in range(
                    candidate["column"], candidate["column"] + width
                )
            )
        ),
        None,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    action = _build_action(planter, state, placement["x"], placement["y"])
    return SkillPlan([action], ["PlanterBox_requires_crop_seed_and_planting"])


def build_recreation(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Plan one unlocked MassageTable on a supported floor."""
    table = _get_building(catalog, "MassageTable")
    if any(
        entry.get("id") == "MassageTable"
        and entry.get("state") in {"built", "under_construction"}
        for entry in _known_buildings(state)
    ):
        return SkillPlan([], [])
    width, height = building_dimensions(table)
    rows, origin, center = _map_context(state)
    placement = next(
        (
            candidate
            for candidate in find_empty_rectangle_candidates(
                rows, origin, width, height, center=center
            )
            if candidate["row"] + 1 < len(rows)
            and all(
                rows[candidate["row"] + 1][column] in {"#", "F", "X"}
                for column in range(
                    candidate["column"], candidate["column"] + width
                )
            )
        ),
        None,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    action = _build_action(table, state, placement["x"], placement["y"])
    return SkillPlan([action], ["MassageTable_requires_power"])


def build_storage_area(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> SkillPlan:
    """Plan one unlocked StorageLocker on a supported floor."""
    locker = _get_building(catalog, "StorageLocker")
    if any(
        entry.get("id") == "StorageLocker"
        and entry.get("state") in {"built", "under_construction"}
        for entry in _known_buildings(state)
    ):
        return SkillPlan([], [])
    width, height = building_dimensions(locker)
    rows, origin, center = _map_context(state)
    placement = next(
        (
            candidate
            for candidate in find_empty_rectangle_candidates(
                rows, origin, width, height, center=center
            )
            if candidate["row"] + 1 < len(rows)
            and all(
                rows[candidate["row"] + 1][column] in {"#", "F", "X"}
                for column in range(
                    candidate["column"], candidate["column"] + width
                )
            )
        ),
        None,
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    action = _build_action(locker, state, placement["x"], placement["y"])
    return SkillPlan([action], [])


def _dupe_position(dupe: Mapping[str, Any]) -> tuple[int, int] | None:
    x, y = dupe.get("x"), dupe.get("y")
    if (
        isinstance(x, bool)
        or not isinstance(x, int)
        or isinstance(y, bool)
        or not isinstance(y, int)
    ):
        return None
    return x, y


def _catalog_building(
    catalog: Sequence[Mapping[str, Any]], building_id: str
) -> Mapping[str, Any]:
    try:
        building = get_building(catalog, building_id)
    except CatalogError as error:
        raise SkillPlanningError("building_unavailable") from error
    if building.get("unlocked") is not True:
        raise SkillPlanningError("building_locked")
    building_dimensions(building)
    return building


def _building_entry_count(
    state: Mapping[str, Any], building_id: str
) -> int:
    buildings = state.get("building_list")
    if not isinstance(buildings, list):
        return 0
    return sum(
        1
        for entry in buildings
        if isinstance(entry, Mapping)
        and entry.get("id") == building_id
        and entry.get("state") in {"built", "under_construction"}
    )


def _reserved_building_cells(
    state: Mapping[str, Any], catalog: Sequence[Mapping[str, Any]]
) -> set[tuple[int, int]]:
    buildings = state.get("building_list")
    if not isinstance(buildings, list):
        return set()
    reserved: set[tuple[int, int]] = set()
    for entry in buildings:
        if (
            not isinstance(entry, Mapping)
            or entry.get("state") not in {"built", "under_construction"}
        ):
            continue
        x, y = entry.get("x"), entry.get("y")
        if (
            isinstance(x, bool)
            or not isinstance(x, int)
            or isinstance(y, bool)
            or not isinstance(y, int)
        ):
            continue
        try:
            building = get_building(catalog, str(entry.get("id", "")))
            width, height = building_dimensions(building)
        except CatalogError:
            continue
        for dx in range(width):
            for dy in range(height):
                reserved.add((x + dx, y + dy))
    return reserved


def _emergency_build_action(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    building_id: str,
    center: tuple[int, int],
    rows: list[str],
    origin: Mapping[str, int],
    room_cells: set[tuple[int, int]],
    reserved: set[tuple[int, int]],
    stock_budget: dict[str, tuple[str, float]],
) -> dict[str, Any]:
    building = _catalog_building(catalog, building_id)
    width, height = building_dimensions(building)
    placement = _find_room_placement(
        rows, origin, room_cells, center, width, height, reserved
    )
    if placement is None:
        raise SkillPlanningError("no_valid_placement")
    trial_budget = dict(stock_budget)
    materials = _emergency_materials(building, state, trial_budget)
    stock_budget.clear()
    stock_budget.update(trial_budget)
    for dx in range(width):
        for dy in range(height):
            reserved.add((placement["left_x"] + dx, placement["bottom_y"] + dy))
    return _build_action(building, state, placement["x"], placement["y"], materials)


def _priority_actions(
    dupes: Sequence[Mapping[str, Any]],
    groups: Sequence[str],
    desired_priority: int,
    *,
    lower_only: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    actions: list[dict[str, Any]] = []
    skipped: list[str] = []
    for dupe in dupes:
        name = dupe.get("name")
        priorities = dupe.get("job_priorities")
        if not isinstance(name, str) or not name or not isinstance(priorities, Mapping):
            skipped.append("dupe_job_priorities_unavailable")
            continue
        for group in groups:
            current = priorities.get(group)
            if not isinstance(current, int) or isinstance(current, bool):
                skipped.append(f"priority_group_unavailable:{group}")
                continue
            if current == desired_priority or (lower_only and current < desired_priority):
                continue
            actions.append(
                {
                    "type": "set_dupe_priority",
                    "dupe": name,
                    "group": group,
                    "priority": desired_priority,
                }
            )
    return actions, skipped


def plan_emergency_actions(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    category: str,
    reason: str,
) -> dict[str, Any]:
    """Create bounded emergency actions using only current state/catalog data."""
    plan: dict[str, Any] = {"actions": [], "skipped": [], "reason": reason}
    dupes = _live_dupes(state)

    if category == "oxygen":
        existing = [
            entry
            for entry in state.get("building_list", [])
            if isinstance(entry, Mapping)
            and entry.get("id") == "MineralDeoxidizer"
            and entry.get("state") in {"built", "under_construction"}
        ] if isinstance(state.get("building_list"), list) else []
        if existing:
            built = [entry for entry in existing if entry.get("state") == "built"]
            algae_values = [
                _stored_element_mass(entry.get("stored"), "Algae")
                for entry in built
            ]
            if not built:
                warning = "mineral_deoxidizer_pending"
            elif any(value is not None and value > 0 for value in algae_values):
                warning = "mineral_deoxidizer_algae_present"
            elif all(value is not None for value in algae_values):
                warning = "thiếu_algae"
            else:
                warning = "thiếu_dữ_liệu_algae"
            plan["skipped"].append({"reason": warning})
            return plan
        if not dupes:
            plan["skipped"].append({"reason": "no_dupe_position"})
            return plan
        center = next((_dupe_position(dupe) for dupe in dupes if _dupe_position(dupe)), None)
        if center is None:
            plan["skipped"].append({"reason": "no_dupe_position"})
            return plan
        try:
            rows, origin, room_cells = _room_cells(state, center)
            action = _emergency_build_action(
                state,
                catalog,
                "MineralDeoxidizer",
                center,
                rows,
                origin,
                room_cells,
                _reserved_building_cells(state, catalog),
                _emergency_stock_budget(state),
            )
        except SkillPlanningError as error:
            plan["skipped"].append({"reason": error.reason})
        else:
            plan["actions"].append(action)
        return plan

    if category == "food":
        actions, skipped = _priority_actions(
            dupes, ("Farming", "Cook", "Ranching"), 4, lower_only=False
        )
        plan["actions"] = actions
        plan["skipped"].extend({"reason": item} for item in skipped)
        return plan

    if category == "stress":
        stressed = [
            dupe
            for dupe in dupes
            if (_emergency_number(dupe.get("stress")) or 0) >= 90
        ]
        priorities, skipped = _priority_actions(
            stressed, ("Dig", "Build"), 2, lower_only=True
        )
        plan["actions"].extend(priorities)
        plan["skipped"].extend({"reason": item} for item in skipped)
        if not dupes:
            plan["skipped"].append({"reason": "no_dupes"})
            return plan
        if not stressed:
            plan["skipped"].append({"reason": "stressed_dupe_unavailable"})
            return plan
        center = next((_dupe_position(dupe) for dupe in stressed if _dupe_position(dupe)), None)
        if center is None:
            plan["skipped"].append({"reason": "no_dupe_position"})
            return plan
        try:
            rows, origin, room_cells = _room_cells(state, center)
            stock_budget = _emergency_stock_budget(state)
        except SkillPlanningError as error:
            plan["skipped"].append({"reason": error.reason})
            return plan

        reserved = _reserved_building_cells(state, catalog)
        for building_id in ("Bed", "Outhouse", "WashBasin"):
            shortage = max(0, len(dupes) - _building_entry_count(state, building_id))
            for _ in range(shortage):
                try:
                    action = _emergency_build_action(
                        state,
                        catalog,
                        building_id,
                        center,
                        rows,
                        origin,
                        room_cells,
                        reserved,
                        stock_budget,
                    )
                except SkillPlanningError as error:
                    plan["skipped"].append(
                        {"reason": error.reason, "building": building_id}
                    )
                    break
                plan["actions"].append(action)
        return plan

    if category == "temperature":
        plan["skipped"].append({"reason": "temperature_warning_only"})
    return plan


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
