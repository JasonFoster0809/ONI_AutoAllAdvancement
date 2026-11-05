# Roadmap

## 1. Colony state and telemetry

**Status: implemented and build-validated; in-game verification remains open.**

State includes duplicants, resources, map, buildings, research, schedules,
rooms, achievements, environment, power, and alerts. Built buildings may
include operational/powered state and stored element masses. Duplicant room
and assigned-bed fields are optional. These additions share the existing
approximately ten-second building-list cache.

The JSONL event journal records building completion, duplicant death, stress
threshold crossings, and chore changes. Its `Game.Update`, `BuildingComplete`,
and `MinionIdentity` hooks were checked with ILSpy; journal integration,
rotation, and event ordering still need testing in a disposable colony.

## 2. Safe game commands

**Status: existing actions preserved; live verification remains open.**

The file command channel supports the previously tested dig/build/research,
cancellation, priority, schedule, and per-dupe job-priority actions, plus
catalog and blueprint export. This overnight work does not change those
action implementations. Validate new skill plans in a copied test colony
before relying on automation; no game was launched for this work.

## 3. Python decision agent

**Status: implemented with offline coverage; live integration remains open.**

- `agent/rule_engine.py` validates rules, handles missing data as unknown,
  selects the highest-priority matching rule, records reasons, and applies
  read history, pending, cycle cooldown, and a 12-action rule limit.
  Validated phase metadata reports cycles 0–9 as `early`, 10–29 as `growth`,
  and 30–99 as `midgame`; it does not currently filter planner goals.
- `agent/skills.py` includes catalog- and inventory-aware plans for oxygen
  setup, an enclosed Latrine footprint, a DiningTable mess area, a basic
  ManualGenerator/Wire/Battery layout, and existing Barracks/research plans.
  Insufficient materials or unavailable catalog data do not produce build
  actions.
- Existing deterministic emergency logic stays ahead of optional managers.
  Food actions reuse the existing priority behavior; temperature remains
  warning-only. The empty-Algae rule reads stored material telemetry instead
  of calculating a burn-rate estimate.
- `agent/gemini_manager.py` accepts only schema-valid, allow-listed goal IDs
  for 5–10 cycle horizons and has an offline `--mock` mode. The agent supports
  `--manager {none,qwen,gemini}`; Qwen remains the default tie-breaker.
- Gemini uses `GEMINI_API_KEY` from the environment, sends a minimal state
  summary and predefined goals, and does not log the key. Current free-tier
  quotas are **TODO_VERIFY**.

Remaining work is to test generated build layouts, storage status, event
logging, power connections, and file exchange in a disposable live colony.
The user-reported MineralDeoxidizer Algae use of approximately 0.08–0.22 kg/s
conflicts with the decompiled 0.55 kg/s configured rate; the actual runtime
throughput remains **TODO_VERIFY** and is not an agent constant.

## 4. Validation and safety

Python coverage currently passes offline, and `dotnet build` validates the
C# source against the installed game assemblies. Neither result substitutes
for an in-game test. The C# event journal is explicitly **CHƯA TEST TRONG
GAME**. No game launch, deployment, save modification, game DLL copy, or push
is part of this work.
