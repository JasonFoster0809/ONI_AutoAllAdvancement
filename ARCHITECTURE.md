# Architecture

```text
Oxygen Not Included
  Game.Update postfix (main thread)
    ├─ poll oni_commands.json on an unscaled-time cadence
    ├─ validate and execute each action independently
    ├─ atomically publish oni_results.json
    ├─ publish oni_state.json (about every 2 seconds)
    ├─ refresh building_list / rooms / research / schedule state caches (about every 10 seconds)
    └─ respond to oni_export.flag by writing blueprint.json

Files in the ONI user data directory
  oni_state.json ────────────────┐
  oni_catalog.json ──────────────┤
  oni_commands.json ◄────────────┤ Python agent
  oni_results.json ─────────────►│
  oni_export.flag / blueprint.json┘

Python agent
  read state and check its modification time
    → load agent/config.json and update pending build-order acknowledgements
    → apply deterministic emergency rules first
    → if no emergency: planner walks research_target, then barracks
    → skip completed, pending, unconfigurable, or already-present objectives
    → if multiple plans share the best rank, Ollama may choose only a supplied goal ID
    → otherwise execute the first eligible plan deterministically
    → send one command per goal, track accepted build actions until state acknowledgement / expiry
    → append decision, skipped reasons, pending state, and result to JSON Lines log
```

The mod processes game reads and actions on the game's main thread. Its
polling and state-writing cadence uses Unity `Time.unscaledTime`, so the hook
continues servicing files while the game is paused. Results are published
through a temporary file and rename/replace to avoid exposing a partial JSON
document.

The Python package does not use a game process or a third-party service. The
Ollama client targets only `http://localhost:11434/api/generate`; a malformed,
timed-out, or out-of-list answer becomes a safe no-op. `--dry-run` prevents
command-file writes. Offline fixtures and tests exercise the Python modules
without launching ONI or Ollama.

## Important boundaries

- The agent does not infer prefab IDs. Building IDs are supplied from
  `oni_catalog.json` by command-line configuration.
- Skill functions return action plans and never send them directly.
- The C# state caches `rooms` from `Game.Instance.roomProber.rooms` for about
  10 seconds. The Barracks goal is done when a room entry has
  `type: "Barracks"`; without a valid rooms block, completion is unknown.
- The Barracks planner uses the catalog's Bed, Door, and Tile dimensions,
  builds a closed tile perimeter with a Door opening, targets 12-64 interior
  cells, and checks cumulative material mass before returning actions.
  Existing Tile pieces are reused; other occupied perimeter cells invalidate
  that candidate. It returns no plan if the Door cannot fit within the Bed
  height, construction mass is unavailable, or materials are insufficient.
- `build_bedroom` remains the separate simple bed-and-door planner and does
  not construct an enclosure.
- Configure prefab IDs in `agent/config.json`; no building prefab ID is
  hardcoded in planner logic. `goal_ranks` can give goals the same rank to
  enable LLM tie selection; default goal order gives research higher
  priority than barracks.
- Pending build acknowledgements live in agent process memory. Accepted
  orders are cleared when every planned building appears in `building_list`,
  or logged and expired after `pending_steps` iterations. Existing matching
  buildings are never re-issued by the planner.
- The mod exports cached `resources.materials` stock. Barracks planning
  depends on that inventory and catalog `mass_kg`; missing inventory returns
  `material_inventory_unavailable`, and missing construction mass is reported
  rather than guessed.
- Emergency rules run before the planner. The current loop does not configure
  emergency repair actions, so a detected emergency selects no-op and blocks
  both planner and LLM.
- C# changes have build validation only; they have not been tested in a live
  game. Python behavior has offline tests only; the live file/game and Ollama
  integration has not been exercised.
