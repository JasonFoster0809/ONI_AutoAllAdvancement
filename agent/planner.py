"""Ordered, state-driven colony goals with build-order deduplication."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from .catalog import CatalogError, building_dimensions, get_building
from .skills import SkillPlanningError, build_barracks


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
        id="research_chain",
        description="Select the next configured ready technology using basic research",
        is_done=lambda _state: False,
        plan=_plan_research_chain,
    ),
    rank=0,
)
register_goal(
    Goal(
        id="research_target",
        description="Select the highest-priority ready incomplete technology",
        is_done=_research_target_done,
        plan=_plan_research_target,
    ),
    rank=1,
)
register_goal(
    Goal(
        id="barracks",
        description="Plan an enclosed room meeting Barracks constraints",
        is_done=barracks_done,
        plan=_plan_barracks,
    ),
    rank=1,
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
            skipped.append({"goal_id": goal.id, "reason": error.reason})
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
    """Track only build actions the mod reported as accepted."""
    accepted: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if action.get("type") != "build":
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
