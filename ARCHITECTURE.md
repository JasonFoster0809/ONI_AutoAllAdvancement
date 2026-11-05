# Architecture

```text
Oxygen Not Included
  Game.Update postfix (main thread)
    ├─ poll oni_commands.json on an unscaled-time cadence
    ├─ validate and execute each action independently
    ├─ atomically publish oni_results.json
    ├─ publish oni_state.json (about every 2 seconds)
    ├─ refresh building_list / research / schedule state caches (about every 10 seconds)
    └─ respond to oni_export.flag by writing blueprint.json

Files in the ONI user data directory
  oni_state.json ────────────────┐
  oni_catalog.json ──────────────┤
  oni_commands.json ◄────────────┤ Python agent
  oni_results.json ─────────────►│
  oni_export.flag / blueprint.json┘

Python agent
  read state and check its modification time
    → construct only configured skill plans from state + catalog
    → apply deterministic emergency rules
    → otherwise ask local Ollama to select one supplied candidate ID
    → send at most one command and wait for a result with the matching ID
    → append a JSON Lines record under logs/
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
- The bedroom skill currently plans a bed and door, not a complete enclosed
  room.
- The mod does not currently export a general
  `resources.materials` inventory. Material-dependent skills report
  `material_inventory_unavailable` until that data is available.
- The emergency rules can select a configured candidate with a matching
  category. When no such safe candidate exists, they select no-op and do not
  let the LLM override the emergency decision.
- C# changes have build validation only; they have not been tested in a live
  game. Python behavior has offline tests only; the live file/game and Ollama
  integration has not been exercised.
