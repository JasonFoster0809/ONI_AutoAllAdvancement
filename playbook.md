# ONI Colony Playbook

These are high-level planning notes, not guarantees. Use current state and
catalog data before issuing an action; verify values in the running game when
they depend on traits, building configuration, or game version.

## Early colony priorities

1. **Oxygen**
   - Maintain an oxygen supply before expanding the colony.
   - A duplicant consumes approximately 100 g of oxygen per second of game
     time. Treat this as a planning estimate; actual demand can vary.
   - A Mineral Deoxidizer uses Algae as its input. Check available Algae and
     the building's operating status before relying on it.
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

## Reading the mod snapshot and agent heuristics

- `environment.temperature_avg_k`, `oxygen_avg_g`, and `co2_avg_g` are
  averages over the sampled 11x11 area around the telepad. `oxygen_air` is
  instead an average oxygen-gas mass in grams per valid cell in the 11x11
  area around the first duplicant. These values describe local samples, not
  colony-wide totals.
- The mod's simple alerts are generated at zero dupe calories and stress at
  least 90 on its 0-100 stress scale. Zero calories is a narrow alert, not a
  verified game hunger threshold.
- The offline Python agent currently treats oxygen below 50 g per sampled
  cell, dupe calories below 100 kcal, stress at least 90, or average
  temperature outside 273.15-318.15 K as emergency heuristics. These are
  agent policy thresholds, not verified ONI danger limits; **cần kiểm chứng**
  against a live colony before enabling automatic commands.
- `resources.materials` reports positive material stock in kilograms. The
  Python Barracks planner aggregates catalog `mass_kg` by material group
  before selecting elements; it refuses to plan when inventory or required
  mass data is unavailable.
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
- Mineral Deoxidizer throughput and algae consumption under current settings.
- Whether Barracks Morale is applied on waking and the exact behavior in the
  installed game version.
- The Morale requirements and effects for Mess Hall and Great Hall.
- Whether other room types also fall back to Neutral when they exceed their
  size limits; Barracks is the only type whose constraints were checked here.
- Construction validation of the generated Barracks, especially if the
  configured Door is taller than the Bed or a perimeter tile is already
  under construction.
