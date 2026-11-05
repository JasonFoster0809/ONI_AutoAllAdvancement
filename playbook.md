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
- `resources.materials` is not present in the current mod state. Do not expect
  the Python material chooser to select construction elements until an
  inventory field is added or supplied by another trusted source.
- The Python bedroom planner currently places a bed and a door; it does not
  guarantee that the surrounding tiles form an enclosed room.

## Cần kiểm chứng

- Exact oxygen and calorie consumption for each duplicant, since traits and
  game conditions may change effective rates.
- Exact Research Center Dirt consumption in the currently installed game
  version and any modifiers that affect research rate.
- Mineral Deoxidizer throughput and algae consumption under current settings.
