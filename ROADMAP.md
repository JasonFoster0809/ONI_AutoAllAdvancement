# Roadmap

## 1. Colony state and telemetry

**Status: implemented and build-validated; waiting for in-game verification.**

State includes duplicants, resources, map, buildings, research, schedules,
achievements, environment, power, and simple alerts. Remaining work is to
compare these readings with a running colony and check their cost and
correctness across game updates.

## 2. Safe game commands

**Status: implemented and build-validated; waiting for in-game verification.**

The file command channel supports the documented dig/build/research,
cancellation, priority, schedule, and per-dupe job-priority actions, plus the
building catalog and blueprint export flag. Validate each action in a copied
test colony before relying on automation. No action has been tested in-game
as part of this work.

## 3. Python decision agent

**Status: offline implementation and tests complete; live integration waiting.**

The client, map helpers, catalog handling, skill planners, deterministic
rules, constrained local Ollama chooser, CLI loop, and JSON Lines logging are
implemented. Remaining work:

- Add a verified general material-stock field if material selection should be
  automatic; the current state does not include `resources.materials`.
- Configure real prefab IDs from the mod's catalog and decide which safe
  actions should address oxygen, food, stress, and temperature emergencies.
- Verify the selected Ollama model and local endpoint on the user's machine.
- Test file exchange and action results with ONI running; offline tests are
  not a substitute for game integration.
- Extend the bedroom planner if an enclosed room, rather than a bed and door
  placement plan, is required.

## 4. Validation, safety, and documentation

**Status: offline tests and documentation complete; live validation open.**

`python -m pytest -q` passes 22 tests. `dotnet build` passes. The C# mod has
not been run in the game, and no deployment, DLL copy, or live command test
was performed. Re-run the API verification and build after game updates.
