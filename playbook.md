# ONI Colony Playbook

These are high-level planning notes, not guarantees. Use current state and
catalog data before issuing an action; verify values in the running game when
they depend on traits, building configuration, or game version.

## Early colony priorities

1. **Oxygen**
   - Maintain an oxygen supply before expanding the colony.
   - A duplicant consumes approximately 100 g of oxygen per second of game
     time. Treat this as a planning estimate; actual demand can vary.
   - A Mineral Deoxidizer uses Algae as its input. The installed game code
     configures 0.55 kg/s Algae consumption, 0.5 kg/s Oxygen output, and
     120 W active power use. These are configured rates, not a guarantee of
     live throughput; check the building's status and stored Algae before
     relying on it.
   - Monitor breathable oxygen around duplicants, not only oxygen stored in
     the world inventory.

2. **Food**
   - Keep edible food available and account for production, spoilage, and
     travel time.
   - A duplicant's food consumption is approximately 1,000 kcal per cycle.
     Use the colony's actual food stock and consumption trend rather than
     treating this estimate as exact.

3. **Power**
   - A generator, a connected power circuit, and batteries address generation,
     distribution, and storage respectively; a battery alone does not
     generate power.
   - Compare circuit load with the currently available generation. A connected
     circuit can still be overloaded or short on stored energy.
   - The state snapshot reports battery charge and selected circuit power
     totals; it may omit circuits that have no battery or generator in the
     active world.

4. **Research**
   - Research Center basic research uses Dirt; the reference rate is 50 kg of
     Dirt per basic research point. Confirm that the research station has the
     required material and that the desired tech is available.
   - Check the `research` state for prerequisites, target, active research,
     and remaining point types before changing the target.

5. **Barracks**
   - The user's in-game tooltip reports that a Barracks needs one or more
     beds, no industrial machinery, and room size 12-64 cells; it lists
     Morale +1 and Stamina +100%/cycle. The bed, machinery, and size
     requirements were cross-checked against the decompiled
     `Database.RoomTypes.Barracks` and `RoomConstraints` implementation.
   - Community information says the Morale effect is applied when a
     duplicant wakes after sleeping; **cần kiểm chứng** in the installed game.
   - Mess Hall and Great Hall are separate morale-related room types. Their
     exact requirements and effects are **cần kiểm chứng** before planning
     around them.
   - The planner creates a perimeter from Tile pieces, leaves a wall opening
     for one Door, and places the configured number of beds. It uses catalog
     dimensions and construction masses and does not send actions when
     placement or material checks fail.

## Planning safeguards

- Prefer small, reversible actions and inspect the next state before issuing
  more work.
- Use `oni_catalog.json` for valid building IDs, size, materials, and unlock
  state; do not infer IDs or material tags.
- Confirm coordinates and map cells before digging or building.
- Exact consumption, research rates, and behavior can vary by game version,
  configuration, and duplicant traits; treat approximate values as estimates
  and mark uncertain details **cần kiểm chứng**.

## Hành động khẩn cấp

The following inventory is a read-only review of the local
`oni_state.json`/`oni_catalog.json` at cycle 4. Unlocked status and counts can
change with the colony; always use the current catalog and state before
planning.

| Case | State signals available | Unlocked catalog options | Missing/limits |
|---|---|---|---|
| Low oxygen | `environment.oxygen_avg_g`, `oxygen_air`, `resources.materials.Algae`, `building_list`, `world.map`/`origin`/`start`, and dupe positions. Current sample: 267.87 g average local oxygen, 769.2 kg Algae, two built `MineralDeoxidizer` entries. | `MineralDeoxidizer` (1x2; 200 kg `Metal`), `Electrolyzer` (2x2; 200 kg `Metal`). Current stock includes 18,663.9 kg `Cuprite`, an option for the Deoxidizer's Metal category. | Current state entries contain only the old building fields: no per-building `operational`, `powered`, or `stored`; therefore stored Algae/operating state for existing Deoxidizers is unknown. State has no explicit dupe-to-room ID/bounds. Nearest clear floor placement can be selected from the local map but same-room placement is **cần kiểm chứng**. `oxygen_air` and `environment.oxygen_avg_g` are local samples, not colony-wide supply. |
| Hungry dupe/low food stock | `dupes[].calories_kcal`, `resources.food_kcal`, and `alerts`. Current sample: 19,358.32 kcal total food; four dupes at 1,710-3,897 kcal. `job_priorities` contains `Farming`, `Cook`, and `Ranching`. | Unlocked IDs include `FarmTile` (1x1; 100 kg Farmable), `HydroponicFarm` (1x1; 100 kg Metal), `FarmStation` (2x3; 400 kg Metal), `CookingStation` (3x2; 400 kg Metal), and `RanchStation` (2x3; 400 kg Metal). These establish build availability, not that a specific crop/recipe is ready. | State has aggregate kcal and dupe calories but no food-consumption trend, edible item breakdown, crop/recipe readiness, or reliable food-production rate. Existing rule detects dupe calories below 100 kcal or mod alert; no low-total-stock threshold exists yet. Chosen policy for a future action: one estimated cycle of food per dupe (1,000 kcal each) as the low-stock cutoff; it is a planning threshold, not an ONI danger threshold. |
| High stress | `dupes[].stress`, names/positions, `alerts`, `job_priorities`, and built `building_list`. Current sample: four dupes, stress 0, with `Dig`/`Build` priorities present. | `Bed` (2x2; 200 kg BuildableRaw&BuildingWood), `Outhouse` (2x3; same category, 200 kg), and `WashBasin` (2x3; 50 kg BuildableRaw&Metal) are unlocked. Current stock has 32,563.3 kg SandStone, which is an option for those categories. | Current counts: seven Beds, three Outhouses, one WashBasin. State does not say which dupe is assigned to/served by each amenity or encode an amenity capacity/usage policy. Safe planner assumption: target at least one of each per live dupe, count built plus under-construction entries, and build only the shortage. Exact bathroom scheduling/room rules remain **cần kiểm chứng**. |
| Temperature outside policy band | `environment.temperature_avg_k`; current sample is 296.24 K. Existing Python rule uses 273.15-318.15 K as policy limits. | Catalog includes unlocked `IceCooledFan`, `IceMachine`, and `SpaceHeater`, among other thermal-related entries. No build action is selected for temperature emergencies. | Temperature is an 11x11 telepad-area average, not a per-dupe reading or map; spatial extremes and safe limits are unavailable. Thresholds are agent policy only. The response remains warning-only. |

Decision: use only exact building IDs/unlock flags/material options from the
live catalog, build only after material selection succeeds, and never infer
that a missing per-building `stored` field means an empty store. If an
existing Deoxidizer's stored Algae is unknown, emit a missing-data warning
and do not build a duplicate or claim `thiếu_algae`. Limit emergency commands
per selection and use cycle-based cooldowns; the pending/cooldown choices
are agent safeguards, not game mechanics. No new C# state fields are required
for detecting the four emergencies, but existing-Deoxidizer algae warnings
must remain conservative until its per-building storage field is present.

## Reading the mod snapshot and agent heuristics

- `environment.temperature_avg_k`, `oxygen_avg_g`, and `co2_avg_g` are
  averages over the sampled 11x11 area around the telepad. `oxygen_air` is
  instead an average oxygen-gas mass in grams per valid cell in the 11x11
  area around the first duplicant. These values describe local samples, not
  colony-wide totals.
- The mod's simple alerts are generated at zero dupe calories and stress at
  least 90 on its 0-100 stress scale. Zero calories is a narrow alert, not a
  verified game hunger threshold.
- The Python agent uses `environment.oxygen_avg_g` as the primary oxygen
  signal, falling back to `oxygen_air` only when the environment value is
  unavailable. Oxygen below 50 g triggers the emergency rule only after 3
  consecutive state reads by default; both `oxygen_min_g` and
  `oxygen_consecutive_readings` are configurable in `agent/config.json`.
  Alerts reported by the mod still trigger immediately. The 50 g threshold is
  an agent policy threshold, **not a game-verified danger limit**; validate
  it against a live colony before enabling automatic responses.
- Other offline Python emergency heuristics include dupe calories below 100
  kcal, stress at least 90, and average temperature outside 273.15-318.15 K.
  These are agent policy thresholds, not verified ONI danger limits; **cần
  kiểm chứng** against a live colony before enabling automatic commands.
- `resources.materials` reports positive material stock in kilograms. The
  Python Barracks planner aggregates catalog `mass_kg` by material group
  before selecting elements; it refuses to plan when inventory or required
  mass data is unavailable.
- Built entries in `building_list` may include `operational`, `powered`, and
  `stored`. `operational` is the game's aggregate operational-requirements
  state, not proof the building is actively converting material.
  `powered` appears only for power-input buildings when their energy consumer
  is readable. Mineral Deoxidizer `stored.Algae` is its contained Algae mass
  in kg. These fields refresh with the existing building-list cache
  (approximately every 10 seconds) and may be absent when unavailable.
- `rooms` reports the RoomProber type, cell count, and a representative
  coordinate. It always includes non-Neutral room types and includes a
  Neutral room only when its cell list contains the cell of a building in
  `building_list`. A room that exceeds a room type's size constraints can be
  classified as Neutral by the game and is retained when it contains a listed
  player building; it does not receive that room type's bonus. Barracks
  constraints were verified in code; whether other room types similarly fall
  back to Neutral when oversized is **cần kiểm chứng**. The Barracks goal is
  considered complete only when this state contains a room with
  `type: "Barracks"`.
- `build_bedroom` remains a separate simple bed-and-door planner. It does not
  create an enclosed room; use the Barracks goal for the perimeter plan.

## Cần kiểm chứng

- Exact oxygen and calorie consumption for each duplicant, since traits and
  game conditions may change effective rates.
- Exact Research Center Dirt consumption in the currently installed game
  version and any modifiers that affect research rate.
- Whether live Mineral Deoxidizer throughput matches its configured rates,
  including the effects of game conditions and user settings.
- Whether Barracks Morale is applied on waking and the exact behavior in the
  installed game version.
- The Morale requirements and effects for Mess Hall and Great Hall.
- Whether other room types also fall back to Neutral when they exceed their
  size limits; Barracks is the only type whose constraints were checked here.
- Construction validation of the generated Barracks, especially if the
  configured Door is taller than the Bed or a perimeter tile is already
  under construction.

## Implemented skill plans (offline only)

- `build_oxygen_setup` uses an unlocked `MineralDeoxidizer`, catalog mass,
  available `resources.materials`, and a supported clear map footprint. It
  does not add a second machine when one is already present. If an existing
  machine's `stored` data is readable and Algae is empty, the plan warns that
  Algae delivery is needed; if storage is missing or unreadable, it reports
  unknown rather than assuming zero. The configured 0.55 kg/s rate is not
  used as a rule constant. The user-reported 0.08–0.22 kg/s live loss remains
  **TODO_VERIFY** against the decompiled configuration.
- Food emergencies use the existing `Farming`, `Cook`, and `Ranching` dupe
  priority actions. `build_mess_area` places the catalog's `DiningTable`; it
  is not a food-production or food-delivery skill.
- The high-stress emergency lowers `Dig`/`Build` priorities and plans catalog
  shortages of `Bed`, `Outhouse`, and `WashBasin`. Temperature remains a
  warning only. All material-consuming build actions use actual catalog
  masses and current `resources.materials`.
- `build_toilet_room` plans a six-by-three-cell interior with Tile perimeter
  and a Door opening, then adds `Outhouse` and `WashBasin` in a later batch.
  The decompiled `Database.RoomTypes.Latrine` constraints require a toilet,
  wash station, no industrial machinery, and 12–64 room cells; 18 interior
  cells satisfy the size bound. `OuthouseConfig` tags the building as
  `ToiletType` and requests 200 kg Dirt for a refill. `WashBasinConfig` tags
  it as `WashStation` and requests Water. These code facts do not prove that
  the room will be recognized or usable after construction in a live colony.
- `build_power_basic` lays out one unlocked `ManualGenerator`, a contiguous
  Wire row, and one unlocked `Battery`, after checking material stock. Its
  circuit connection and operation are **CHƯA TEST TRONG GAME**.
- Rule-generated batches are capped at 12 actions. The existing Barracks
  planner's behavior is unchanged; its multi-step layout can exceed that cap.
- `--manager gemini` receives only a compact state summary and the predefined
  goal list. Its response is restricted to allow-listed IDs and a 5–10 cycle
  horizon. `GEMINI_API_KEY` is environment-only; free-tier quota is
  **TODO_VERIFY**. Emergency detection stays ahead of any manager.

All new build plans and event logging are offline/build validated only. Do
not rely on room recognition, circuit power, delivery timing, or event
ordering until they are tested in a disposable colony.

## Part 2: water, food, recreation, and storage plans

- `build_water_setup` uses the catalog's unlocked `LiquidPumpingStation` and
  `WashBasin`, checks their construction masses against `resources.materials`,
  and only plans a pump when the map contains a liquid (`L`) cell. It places
  the pump footprint near that cell as a conservative map heuristic, then
  finds floor-supported space for the basin. This adjacency rule is not a
  verified guarantee of liquid pumping; test it in a disposable colony.
  WashBasin also needs a delivery of Water. No fixed source rate or required
  water supply quantity is assumed.
- `build_food_basic` selects the unlocked, catalog-listed `PlanterBox`.
  The decompiled `PlanterBoxConfig` identifies it as a 1x1 Farmable floor
  building with `PlantablePlot` and crop-seed deposit tags. The plan does not
  choose seeds, plant, or guarantee harvest; seed/crop readiness is
  **TODO_VERIFY**. If PlanterBox is missing or locked, the skill reports
  `TODO_NOT_IMPLEMENTED_food_building_unavailable`.
- `build_recreation` plans one unlocked `MassageTable` after inventory and
  floor checks. `MassageTableConfig` marks it as requiring power and tags it
  as a de-stressing building; power connection and actual use are
  **CHƯA TEST TRONG GAME**.
- `build_storage_area` plans one unlocked `StorageLocker`; it does not set
  accepted materials or assign duplicant storage priorities.
- The new rules schedule water and planter plans during cycles 10–29 and
  recreation/storage during cycles 30–99. They are count/phase policies,
  not needs-based production-rate calculations.
- To generate a read-only diagnosis, run
  `python -m agent.diagnostics --logs logs/agent.jsonl --state <state.json>`.
  To compare recorded rule decisions, run
  `python -m agent.replay --logs logs/agent.jsonl --catalog <oni_catalog.json>`.
  Older logs without recorded rule inputs cannot be replayed. Run
  `python -m agent.agent_main --report` to write `logs/metrics.json`; observed
  cycle is not a confirmed death cycle.
