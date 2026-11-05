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

## Cần kiểm chứng

- Exact oxygen and calorie consumption for each duplicant, since traits and
  game conditions may change effective rates.
- Exact Research Center Dirt consumption in the currently installed game
  version and any modifiers that affect research rate.
- Mineral Deoxidizer throughput and algae consumption under current settings.
