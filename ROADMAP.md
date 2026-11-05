# Roadmap

## 1. Colony state and telemetry

**Status: implemented and build-validated; waiting for in-game verification.**

State includes duplicants, resources, map, buildings, research, schedules,
rooms, achievements, environment, power, and simple alerts. Remaining work
is to compare these readings with a running colony and check their cost and
correctness across game updates.

## 2. Safe game commands

**Status: implemented and build-validated; waiting for in-game verification.**

The file command channel supports the documented dig/build/research,
cancellation, priority, schedule, and per-dupe job-priority actions, plus the
building catalog and blueprint export flag. Validate each action in a copied
test colony before relying on automation. No action has been tested in-game
as part of this work.

## 3. Python decision agent

**Status: goal planner and offline tests complete; live integration waiting.**

The client, map helpers, catalog handling, skill planners, deterministic
rules, constrained local Ollama chooser, ordered `research_target` / `barracks`
goal planner, pending build tracking, CLI loop, and JSON Lines logging are
implemented. Remaining work:

- Populate `agent/config.json` with prefab IDs copied from `oni_catalog.json`.
- Test room snapshots and generated Barracks construction in a disposable
  game colony; this implementation is currently verified only by decompilation,
  build, and offline fixtures.
- Decide which safe actions should address oxygen, food, stress, and
  temperature emergencies; currently the hard rules stop at no-op.
- Verify the selected Ollama model and local endpoint on the user's machine.
- Test file exchange and action results with ONI running; offline tests are
  not a substitute for game integration.
- Check the configured Door dimensions against the Bed height; the planner
  safely rejects a Door that cannot fit in the requested room height.

## 4. Validation, safety, and documentation

**Status: offline tests and documentation complete; live validation open.**

`python -m pytest -q` currently passes 46 offline tests. `dotnet build`
passes. The C# mod and Python file exchange have not been tested in the game,
and no deployment, DLL copy, or live command test was performed. Re-run the
API verification and build after game updates.
