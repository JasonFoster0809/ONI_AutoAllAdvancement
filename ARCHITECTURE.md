# Architecture

```text
Oxygen Not Included
  Game.Update postfix (main thread)
    ├─ read state and process oni_commands.json
    ├─ atomically publish oni_state.json / oni_results.json
    ├─ refresh building, room, research, schedule, and material snapshots
    ├─ queue BuildingComplete.OnSpawn and MinionIdentity.OnDied event refs
    └─ drain event refs on Game.Update and append oni_events.jsonl

Files in the ONI user data directory
  oni_state.json / oni_catalog.json ───► Python agent
  oni_commands.json ◄────────────────── Python agent
  oni_results.json / oni_events.jsonl

Python agent
  read state, catalog, and pending acknowledgements
    → detect deterministic emergencies before any manager call
    → optional Gemini manager returns allow-listed goal IDs (5–10 cycle horizon)
    → evaluate priority rules with unknown-aware state conditions
    → execute the selected rule skill, or fall back to the ordered goal planner
    → optional local Qwen tie-breaker selects only a supplied goal candidate
    → preserve --dry-run or send the selected action batch
    → track pending actions, cycle cooldowns, reasons, and results in JSONL

Offline diagnostics
  logs/agent.jsonl + current state ───► diagnostics.md
  logs/agent.jsonl + recorded rule inputs/catalog ───► replay comparison
  logs/agent.jsonl ───► --report ───► logs/metrics.json
```

The mod processes game state and command actions from the `Game.Update`
Harmony postfix. Building completion and duplicant death patches enqueue
object references only; the update postfix reads their details and writes the
event journal on the game thread. State output is approximately every two
seconds; building, room, research, schedule, and material caches are
approximately ten seconds. The event journal is bounded at 5 MiB and retains
one rotated `.1` backup.

## Python decision flow

- Oxygen, food, stress, and temperature emergency detection remains
  deterministic and runs before Gemini or Qwen. Oxygen/food repairs use the
  existing configured actions; temperature is warning-only.
- `--manager gemini` sends a compact state summary and the registered goal
  IDs/descriptions to the Gemini `generateContent` endpoint. Only schema-valid,
  allow-listed goal IDs are accepted; the plan is cached until its cycle
  horizon expires. The API key is read from `GEMINI_API_KEY`, sent in a
  request header, and never logged. Free-tier limits are **TODO_VERIFY**.
- The priority rule engine evaluates facts with three-valued unknown
  semantics, bounded read history, pending actions, and cycle cooldowns. It
  passes the real catalog to the selected skill and caps rule-generated
  actions at 12 per turn. Its validated phase metadata labels cycles 0–9 as
  `early`, 10–29 as `growth`, and 30–99 as `midgame`; the phase is reported,
  not used to filter planner goals.
- Rule cycle gates can schedule a water pump/wash basin and one PlanterBox in
  cycles 10–29, then one MassageTable and StorageLocker in cycles 30–99.
  These are catalog/inventory checked plans, not proof the colony's needs or
  room/power conditions are satisfied.
- If no rule selects a skill, the existing planner executes the highest-ranked
  enabled goal. `--manager qwen` retains the local Ollama tie-break behavior;
  `--manager none` disables both optional goal managers. The default remains
  `qwen` for compatibility.
- Skills are planning-only and use catalog IDs, unlock flags, construction
  masses, and `resources.materials`. They do not send commands directly.
  Implemented plans include oxygen setup, a tiled Latrine footprint, a
  DiningTable mess area, a ManualGenerator/Wire/Battery layout,
  LiquidPumpingStation/WashBasin water setup, PlanterBox, MassageTable,
  StorageLocker, and the existing Barracks and research planners.
- `--dry-run` prints and logs proposed actions without writing command files.
- `agent.diagnostics` emits a Markdown report from the agent log and one
  current state snapshot. Trend checks require telemetry in recent logs;
  older sparse summaries return `unknown`, and the report does not infer a
  cause of death.
- `agent.replay` recomputes rule decisions only for entries that contain the
  recorded rule state, history, pending set, and cooldown context. Old entries
  without that context are `unavailable`; replay also depends on the supplied
  catalog matching the one used for planning.
- `agent_main --report` aggregates measurable outcomes into
  `logs/metrics.json`. The reported cycle is the latest observed, not a
  confirmed death cycle; dry-run entries have no command result counts.

The Gemini manager receives only `cycle`, dupe count, local oxygen average,
food calories, and the allow-listed goal descriptions. It does not receive
dupe names, the map, building lists, or action payloads. The Qwen chooser
remains local at `http://localhost:11434/api/generate`.

## Important boundaries

- Building and material IDs come from `oni_catalog.json`; no prefab ID is
  inferred. An unavailable or locked building and insufficient inventory
  result in a skipped plan rather than an invented fallback.
- MineralDeoxidizer logic reads its actual `building_list[].stored` data. The
  code-configured `0.55 kg/s` Algae rate and `1.8 kg` pressure threshold are
  not used as automation constants; observed throughput remains
  **TODO_VERIFY**.
- `build_toilet_room` constructs its enclosure in batches of no more than 12
  tiles and requires an unlocked Outhouse, WashBasin, Door, and Tile. It warns
  that Dirt delivery is needed; it does not claim that material is already
  inside the Outhouse.
- `build_power_basic` lays out catalog-verified generator, wire, and battery
  footprints. Its runtime circuit behavior is **CHƯA TEST TRONG GAME**.
- `build_water_setup` uses `L` cells in the map as a proximity heuristic for
  the pump and warns that the WashBasin needs water delivery. Map adjacency
  is not a verified guarantee of successful pumping.
- `build_food_basic` plans only one unlocked PlanterBox; seeds, crop choice,
  planting, and harvested food are not automated. MassageTable's power
  requirement is code-verified, but this skill does not create a circuit.
- Optional `operational_flags` state is derived from verified
  `Operational.Flags` entries. Its C# serialization is build-validated only:
  **CHƯA TEST TRONG GAME**.
- Rule pending/cooldown state is kept in agent memory for the current process.
  The existing planner's pending build acknowledgements remain separate.
- The `Game.Update`, `BuildingComplete.OnSpawn`, and
  `MinionIdentity.OnDied` event hooks were verified with `ilspycmd` against
  the installed assembly. Their C# implementation is build-validated only:
  **CHƯA TEST TRONG GAME**.
- No command action, deployment, game launch, save modification, or game DLL
  copy is part of these changes. Offline tests do not replace in-game
  validation.
