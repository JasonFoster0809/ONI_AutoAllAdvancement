"""Ordered, state-driven colony goals with build-order deduplication."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from .catalog import CatalogError, building_dimensions, get_building
from .maputils import cell_at_xy, state_map
from .skills import (
    SkillPlanningError,
    build_barracks,
    build_bootstrap_basics,
    build_research_center_setup,
    mine_metal_ore,
)
from .rules import oxygen_rule


IsDone = Callable[[Mapping[str, Any]], bool | None]
Plan = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]], Mapping[str, Any]],
    list[dict[str, Any]],
]


@dataclass(frozen=True)
class Goal:
    id: str
    description: str
    is_done: IsDone
    plan: Plan


GOALS: list[Goal] = []
_GOAL_RANKS: dict[str, int] = {}


def _research_target_done(state: Mapping[str, Any]) -> bool | None:
    research = state.get("research")
    if not isinstance(research, Mapping) or "active" not in research:
        return None
    active = research.get("active")
    if active is None:
        return False
    if isinstance(active, str):
        return bool(active.strip())
    return None


def _plan_research_target(
    state: Mapping[str, Any],
    _catalog: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if "research_chain_order" in config:
        raise SkillPlanningError("superseded_by_research_chain")
    research = state.get("research")
    techs = research.get("techs") if isinstance(research, Mapping) else None
    if not isinstance(techs, list):
        raise SkillPlanningError("research_data_unavailable")

    ready = [
        tech
        for tech in techs
        if isinstance(tech, Mapping)
        and isinstance(tech.get("id"), str)
        and tech.get("complete") is False
        and tech.get("ready") is True
    ]
    preferred = config.get("priority_techs", ["FarmingTech"])
    if not isinstance(preferred, list) or any(not isinstance(item, str) for item in preferred):
        raise SkillPlanningError("invalid_priority_techs")

    ready_by_id = {tech["id"].casefold(): tech["id"] for tech in ready}
    tech_id = next(
        (ready_by_id[item.casefold()] for item in preferred if item.casefold() in ready_by_id),
        None,
    )
    if tech_id is None and ready:
        tech_id = ready[0]["id"]
    if tech_id is None:
        raise SkillPlanningError("no_ready_tech")
    return [{"type": "set_research", "tech": tech_id}]


def _plan_research_chain(
    state: Mapping[str, Any],
    _catalog: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    buildings = state.get("building_list")
    if not isinstance(buildings, list) or any(
        not isinstance(building, Mapping)
        or "id" not in building
        or "state" not in building
        for building in buildings
    ):
        raise SkillPlanningError("research_building_list_unknown")
    if not any(
        building.get("id") == "ResearchCenter"
        and building.get("state") == "built"
        for building in buildings
    ):
        raise SkillPlanningError("no_research_center")

    order = config.get("research_chain_order")
    if not isinstance(order, list) or any(
        not isinstance(tech_id, str) or not tech_id for tech_id in order
    ):
        raise SkillPlanningError("research_chain_order_unknown")
    if not order:
        raise SkillPlanningError("research_chain_order_empty")

    research = state.get("research")
    if not isinstance(research, Mapping) or "active" not in research:
        raise SkillPlanningError("research_status_unknown")
    if research["active"] is not None:
        raise SkillPlanningError("research_already_active")
    techs = research.get("techs")
    if not isinstance(techs, list):
        raise SkillPlanningError("research_techs_unknown")
    if any(
        not isinstance(tech, Mapping)
        or not isinstance(tech.get("id"), str)
        or not tech["id"]
        for tech in techs
    ):
        raise SkillPlanningError("research_techs_unknown")

    for tech_id in order:
        matches = [
            tech for tech in techs if tech["id"] == tech_id
        ]
        if not matches:
            continue
        if len(matches) != 1:
            raise SkillPlanningError("research_tech_data_ambiguous")
        tech = matches[0]
        complete = tech.get("complete")
        if not isinstance(complete, bool):
            raise SkillPlanningError("research_tech_status_unknown")
        if complete:
            continue
        ready = tech.get("ready")
        if not isinstance(ready, bool):
            raise SkillPlanningError("research_tech_status_unknown")
        if not ready:
            continue

        costs = tech.get("cost")
        if not isinstance(costs, list):
            raise SkillPlanningError("research_cost_unknown")
        basic_only = True
        for cost in costs:
            if not isinstance(cost, Mapping) or not isinstance(cost.get("type"), str):
                raise SkillPlanningError("research_cost_unknown")
            required, current = cost.get("required"), cost.get("current")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in (required, current)
            ):
                raise SkillPlanningError("research_cost_unknown")
            if cost["type"].casefold() != "basic":
                basic_only = False
                break
        if basic_only:
            return [{"type": "set_research", "tech": tech_id}]
    raise SkillPlanningError("no_basic_ready_tech")


def _research_center_setup_done(state: Mapping[str, Any]) -> bool | None:
    buildings = state.get("building_list")
    if not isinstance(buildings, list):
        return None
    if any(not isinstance(building, Mapping) for building in buildings):
        return None
    return any(
        building.get("id") == "ResearchCenter"
        and building.get("state") == "built"
        for building in buildings
    )


def _plan_research_center_setup(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    _config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    buildings = state.get("building_list")
    if not isinstance(buildings, list) or any(
        not isinstance(building, Mapping) for building in buildings
    ):
        raise SkillPlanningError("research_building_list_unknown")
    if any(
        building.get("id") == "ResearchCenter"
        and building.get("state") in ("built", "under_construction")
        for building in buildings
    ):
        raise SkillPlanningError("research_center_already_present")
    return build_research_center_setup(state, catalog, "ResearchCenter")


def _plan_mine_metal_ore(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    _config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return mine_metal_ore(state, catalog, "ResearchCenter")


def _bootstrap_basics_done(state: Mapping[str, Any]) -> bool | None:
    dupes = state.get("dupes")
    buildings = state.get("building_list")
    if not isinstance(dupes, list) or not isinstance(buildings, list) or any(
        not isinstance(building, Mapping) for building in buildings
    ):
        return None
    counts = {
        building_id: sum(
            building.get("id") == building_id
            and building.get("state") in {"built", "under_construction"}
            for building in buildings
        )
        for building_id in ("Bed", "Outhouse", "WashBasin", "MineralDeoxidizer")
    }
    if (
        counts["Bed"] < len(dupes)
        or counts["Outhouse"] < 1
        or counts["WashBasin"] < 1
    ):
        return False
    return oxygen_rule(state) != "low_oxygen" or counts["MineralDeoxidizer"] >= 1


def _plan_bootstrap_basics(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    threshold = config.get("oxygen_min_g", 50.0)
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or threshold < 0
    ):
        raise SkillPlanningError("oxygen_threshold_unknown")
    return build_bootstrap_basics(state, catalog, oxygen_min_g=threshold)


def barracks_done(state: Mapping[str, Any]) -> bool | None:
    if "rooms" not in state:
        return None
    rooms = state.get("rooms")
    if not isinstance(rooms, list):
        return None
    for room in rooms:
        if isinstance(room, Mapping):
            room_type = room.get("type")
            if isinstance(room_type, str) and room_type.casefold() == "barracks":
                return True
    return False


def _plan_barracks(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    bed_id = config.get("bed_id")
    door_id = config.get("door_id")
    if not isinstance(bed_id, str) or not bed_id:
        raise SkillPlanningError("bed_id_unconfigured")
    if not isinstance(door_id, str) or not door_id:
        raise SkillPlanningError("door_id_unconfigured")
    tile_id = config.get("tile_id")
    bed_count = config.get("barracks_bed_count", 4)
    if isinstance(bed_count, bool) or not isinstance(bed_count, int) or bed_count <= 0:
        raise SkillPlanningError("invalid_bed_count")
    return build_barracks(
        state,
        catalog,
        bed_id,
        door_id,
        tile_id if isinstance(tile_id, str) else None,
        bed_count,
    )


def register_goal(goal: Goal, *, rank: int | None = None) -> None:
    """Register a goal; explicit equal ranks enable safe tie arbitration."""
    if any(existing.id == goal.id for existing in GOALS):
        raise ValueError(f"goal already registered: {goal.id}")
    if not goal.id:
        raise ValueError("goal id must not be empty")
    if rank is None:
        rank = max(_GOAL_RANKS.values(), default=-1) + 1
    GOALS.append(goal)
    _GOAL_RANKS[goal.id] = rank


def registered_goal_ids() -> list[str]:
    """Return registered goals in declaration order."""
    return [goal.id for goal in GOALS]


register_goal(
    Goal(
        id="mine_metal_ore",
        description="Dig a safe route to catalog-approved raw metal ore",
        is_done=lambda _state: False,
        plan=_plan_mine_metal_ore,
    ),
    rank=-2,
)
register_goal(
    Goal(
        id="research_center_setup",
        description="Clear a reachable supported site and build a ResearchCenter",
        is_done=_research_center_setup_done,
        plan=_plan_research_center_setup,
    ),
    rank=-1,
)
register_goal(
    Goal(
        id="bootstrap_basics",
        description="Build missing beds, sanitation, and oxygen basics in nearby gas space",
        is_done=_bootstrap_basics_done,
        plan=_plan_bootstrap_basics,
    ),
    rank=0,
)
register_goal(
    Goal(
        id="research_chain",
        description="Select the next configured ready technology using basic research",
        is_done=lambda _state: False,
        plan=_plan_research_chain,
    ),
    rank=1,
)
register_goal(
    Goal(
        id="research_target",
        description="Select the highest-priority ready incomplete technology",
        is_done=_research_target_done,
        plan=_plan_research_target,
    ),
    rank=2,
)
register_goal(
    Goal(
        id="barracks",
        description="Plan an enclosed room meeting Barracks constraints",
        is_done=barracks_done,
        plan=_plan_barracks,
    ),
    rank=2,
)


def _building_list(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = state.get("building_list")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _building_matches_action(
    entry: Mapping[str, Any],
    action: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> bool:
    if entry.get("id") != action.get("id"):
        return False
    if entry.get("state") not in ("built", "under_construction"):
        return False
    entry_x, entry_y = entry.get("x"), entry.get("y")
    action_x, action_y = action.get("x"), action.get("y")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (entry_x, entry_y, action_x, action_y)):
        return False

    if action.get("orientation", "Neutral") != "Neutral":
        return (entry_x, entry_y) == (action_x, action_y)

    try:
        building = get_building(catalog, str(action.get("id", "")))
        width, _ = building_dimensions(building)
    except CatalogError:
        return (entry_x, entry_y) == (action_x, action_y)

    pivot_offset = width // 2 if width % 2 else width // 2 - 1
    return (entry_x, entry_y) == (action_x - pivot_offset, action_y)


def _remove_existing_builds(
    actions: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    existing = _building_list(state)
    filtered: list[dict[str, Any]] = []
    found_existing = False
    for action in actions:
        if action.get("type") == "build" and any(
            _building_matches_action(entry, action, catalog) for entry in existing
        ):
            found_existing = True
            continue
        filtered.append(dict(action))
    return filtered, found_existing


def _pending_action_present(
    action: Mapping[str, Any],
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> bool:
    if action.get("type") == "dig":
        x, y = action.get("x"), action.get("y")
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (x, y)
        ):
            return False
        try:
            rows, origin = state_map(state)
            cell = cell_at_xy(rows, origin, x, y)
        except (KeyError, TypeError, ValueError):
            return False
        return cell is not None and cell != "#"
    return any(
        _building_matches_action(entry, action, catalog)
        for entry in _building_list(state)
    )


def update_pending(
    state: Mapping[str, Any],
    pending: MutableMapping[str, dict[str, Any]],
    step: int,
    max_steps: int,
    catalog: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Drop acknowledged build orders and expire entries after max_steps."""
    expired: list[dict[str, Any]] = []
    for goal_id, item in list(pending.items()):
        actions = item.get("actions", [])
        remaining = [
            action
            for action in actions
            if isinstance(action, Mapping)
            and not _pending_action_present(action, state, catalog)
        ]
        if not remaining:
            del pending[goal_id]
            continue

        submitted_step = item.get("submitted_step", step)
        if not isinstance(submitted_step, int):
            submitted_step = step
        if step - submitted_step >= max_steps:
            expired.append({"goal_id": goal_id, "reason": "pending_expired"})
            del pending[goal_id]
            continue
        item["actions"] = [dict(action) for action in remaining]
    return expired


def _config_rank(goal_id: str, config: Mapping[str, Any]) -> int:
    configured = config.get("goal_ranks")
    if isinstance(configured, Mapping):
        value = configured.get(goal_id)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return _GOAL_RANKS[goal_id]


def next_step(
    state: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    pending: Mapping[str, Mapping[str, Any]],
    *,
    enabled_goals: Sequence[str] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one highest-ranked plan plus skipped reasons.

    If ``alternatives`` is supplied, same-rank plans are appended for optional
    LLM tie-breaking. The primary return shape remains goal_id/actions/skipped.
    """
    skipped: list[dict[str, str]] = []
    choices: list[tuple[int, Goal, list[dict[str, Any]]]] = []
    enabled = set(enabled_goals) if enabled_goals is not None else None

    ordered_goals = sorted(GOALS, key=lambda item: _config_rank(item.id, config))
    for goal in ordered_goals:
        if enabled is not None and goal.id not in enabled:
            continue
        rank = _config_rank(goal.id, config)
        if choices and rank > choices[0][0]:
            break
        if goal.id in pending:
            skipped.append({"goal_id": goal.id, "reason": "pending"})
            continue
        goal_cooldowns = config.get("goal_cooldowns")
        cycle = state.get("cycle")
        cooldown_until = (
            goal_cooldowns.get(goal.id)
            if isinstance(goal_cooldowns, Mapping)
            else None
        )
        if (
            isinstance(cycle, int)
            and not isinstance(cycle, bool)
            and isinstance(cooldown_until, int)
            and not isinstance(cooldown_until, bool)
            and cycle < cooldown_until
        ):
            skipped.append({"goal_id": goal.id, "reason": "cooldown"})
            continue

        try:
            done = goal.is_done(state)
        except Exception as error:
            skipped.append({"goal_id": goal.id, "reason": f"is_done_error:{error}"})
            continue
        if done is True:
            skipped.append({"goal_id": goal.id, "reason": "already_done"})
            continue

        try:
            planned = goal.plan(state, catalog, config)
            actions, had_existing = _remove_existing_builds(planned, state, catalog)
            if not actions:
                reason = "already_present" if had_existing else "no_actions"
                skipped.append({"goal_id": goal.id, "reason": reason})
                continue
            choices.append((rank, goal, actions))
        except (SkillPlanningError, CatalogError) as error:
            reason = error.reason
            if goal.id == "bootstrap_basics" and error.details:
                reason = f"{reason}: {error.details}"
            skipped.append({"goal_id": goal.id, "reason": reason})
        except Exception as error:
            skipped.append({"goal_id": goal.id, "reason": f"plan_error:{error}"})

    if not choices:
        return {"goal_id": "no_goal", "actions": [], "skipped": skipped}

    _, selected_goal, selected_actions = choices[0]
    if alternatives is not None:
        alternatives.extend(
            {
                "goal_id": goal.id,
                "actions": actions,
            }
            for _, goal, actions in choices[1:]
        )
    return {
        "goal_id": selected_goal.id,
        "actions": selected_actions,
        "skipped": skipped,
    }


def mark_pending(
    pending: MutableMapping[str, dict[str, Any]],
    goal_id: str,
    actions: Sequence[Mapping[str, Any]],
    submitted_step: int,
    results: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Track accepted builds and research-site digs until state acknowledges them."""
    accepted: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if action.get("type") != "build" and not (
            goal_id in ("mine_metal_ore", "research_center_setup")
            and action.get("type") == "dig"
        ):
            continue
        if results is not None:
            if index >= len(results) or results[index].get("ok") is not True:
                continue
        accepted.append(dict(action))
    if accepted:
        pending[goal_id] = {
            "actions": accepted,
            "submitted_step": submitted_step,
        }
