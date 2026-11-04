# Verified ONI API usage

The game API references below were checked against
`D:\Oxygen Not Included\OxygenNotIncluded_Data\Managed\Assembly-CSharp.dll`
using ILSpy command-line decompilation (ilspycmd 8.2). The project was built
after each requested section was added.

| JSON data | Verified API | Verification |
|---|---|---|
| `cycle`, `time_in_cycle` | `GameClock.Instance`, `GameClock.GetCycle()`, `GameClock.GetTimeSinceStartOfCycle()` | Decompiling `GameClock` shows the singleton field and both methods; the time method returns `float`. |
| Dupe list | `Components.LiveMinionIdentities.Items` | Decompiling `Components` shows the `Cmps<MinionIdentity>` field; `Cmps<T>` exposes `Items`. |
| Dupe stress/calories | `Db.Get().Amounts.Stress`, `Db.Get().Amounts.Calories`, `Klei.AI.Amount.Lookup(Component)`, `Klei.AI.AmountInstance.value` | Decompiling `Database.Amounts`, `Klei.AI.Amount`, and `Klei.AI.AmountInstance` shows both amount fields, `Lookup`, and the numeric value. |
| Dupe health | `Health.hitPoints`, obtained from `MinionIdentity.GetComponent<Health>()` | Decompiling `Health` shows the public `hitPoints` property. |
| Current chore | `ChoreDriver.GetCurrentChore()`, `Chore.GetReportName()` | Decompiling `ChoreDriver` and `Chore` shows the methods; the chore field is omitted if no current chore exists. |
| Resources | `ClusterManager.Instance.activeWorld`, `WorldContainer.worldInventory`, `WorldInventory.GetAmount(Tag, bool)` | Decompilation shows the active-world property, inventory property, and amount method. |
| Food calories | `WorldResourceAmountTracker<RationTracker>.Get().CountAmount(null, inventory)` | Decompiling `WorldResourceAmountTracker<T>` shows `Get` and `CountAmount`; `RationTracker.GetItemData` uses `Edible.Calories`. |
| Oxygen/water inventory | `GameTags.Oxygen`, `GameTags.Water` | Decompiling `GameTags` shows both tags. `WorldInventory.GetAmount` is used with each tag. |
| Building counts | `Components.BuildingCompletes.Items`, `BuildingComplete.prefabid`, `KPrefabID.PrefabTag.Name` | Decompilation shows the registry and `prefabid`; `KPrefabID` in `Assembly-CSharp-firstpass.dll` exposes `PrefabTag`, whose `Tag.Name` is used as the key. Prefab names starting with `Prop` or ending with `POI` are excluded. |
| Simple alerts | `Calories.value`, `Stress.value` | `Database.Amounts` decompilation shows the calorie and stress ranges; stress is 0–100. A dupe alert is emitted at zero calories or stress at least 90. |
| Dupe location | `Grid.PosToCell(GameObject)`, `Grid.IsWorldValidCell(int)`, `Grid.CellToXY(int, out int, out int)`, `Grid.WorldIdx` | Decompiling `Grid` shows these methods/field and their signatures. The code only emits coordinates when the cell belongs to a valid world. |
| Active world dimensions | `WorldContainer.Width`, `WorldContainer.Height`, `WorldContainer.id` | Decompiling `WorldContainer` shows these public members. |
| Optional start location | `Components.Telepads`, `Cmps<T>.GetWorldItems(int)`, `Telepad.gameObject` | Decompiling `Components`, `Cmps<T>`, and `Telepad` confirms the registry and world-scoped lookup; the point is emitted only if a telepad resolves to a valid cell in the active world. Printing pod lookup is not included. |
| Active-world map | `ObjectLayer.Building`, `ObjectLayer.FoundationTile`, `Grid.Objects`, `Grid.Foundation`, `Grid.IsSolidCell`, `Grid.Element`, `Element.IsGas/IsLiquid/IsVacuum`, `Element.hardness` | Decompiling `ObjectLayer`, `Grid`, and `Element` confirms the layers, cell indexers, phase flags, and hardness. The map is 41×41 around the active-world telepad; out-of-world cells are `.`. |
| Local oxygen mass | `Grid.Mass`, `Grid.Element`, `Element.id`, `Element.IsGas`, `SimHashes.Oxygen`, `Grid.XYToCell`, `Grid.IsValidCell/InWorld`, `Grid.PosToCell`, `Grid.CellToXY` | ILSpy confirms these fields/indexers and method signatures. Oxygen mass is summed only for Oxygen gas cells in the 11×11 window, converted from the grid mass value to grams, then divided by the number of valid same-world cells. The JSON value is the average grams per valid cell. |
| Main-thread command polling and pause behavior | Harmony postfix on `Game.Update`; Unity `Time.timeScale`, `Time.time`, `Time.unscaledTime`; `BuildingDef.TryPlace`; `Klei.Input.MarkCellDigAction.Dig` | ILSpy decompilation of `Game.Update` shows it runs while `!isLoading` and has no pause early-return. `Game.Pause`/`OnPause` sets `Time.timeScale = 0`, which freezes scaled `Time.time`; Unity `Time.unscaledTime` continues during this pause. `TryPlace` validates and creates the under-construction object synchronously, and `MarkCellDigAction.Dig` immediately invokes `DigTool.PlaceDig`. Thus action validation/placement and result creation do not wait for simulation to resume. |
| Dig validation and marking | `ClusterManager.Instance.activeWorld`, `WorldContainer.WorldOffset/Width/Height/id`, `Grid.XYToCell`, `Grid.IsValidCell`, `Grid.IsValidCellInWorld`, `Grid.Objects[cell, 7]`, `Grid.IsSolidCell`, `Grid.Foundation[cell]`, `Grid.Element[cell].hardness` | These members and the tile/object indexes were confirmed by decompiling `Grid`, `WorldContainer`, and the player's `DigTool.PlaceDig` implementation. A cell is rejected if it is outside the active world, already has a dig-order object, is not solid, is a foundation, or has maximum hardness. |
| Player-equivalent dig order | `DigTool.Instance`, `FilteredDragTool.IsActiveLayer(string)`, `Klei.Input.MarkCellDigAction.Dig(int, int)`, `DigTool.PlaceDig(int, int)` | Decompiling `MarkCellDigAction.Dig` shows it calls `DigTool.PlaceDig` and assigns `ToolMenu.Instance.PriorityScreen.GetLastSelectedPriority()`, matching the player's priority. `PlaceDig` checks the tile filter, existing dig-order object, construction objects, and solid/foundation state before placing the game's `DigPlacer`; `Prioritizable` defaults to Basic 5. The action is rejected if the player's tile filter is disabled rather than changing tool settings. |
| Command/result files | .NET `File`, `Directory`, `File.Replace`, `File.Move`; an in-project strict JSON parser | No game JSON API or extra package is used. Commands are parsed from the documented `id`/`actions` shape; results are written to a sibling `.tmp` file and moved/replaced only after the full JSON is written. |
| Building catalog | `Assets.BuildingDefs`, `BuildingDef.PrefabID`, `WidthInCells`, `HeightInCells`, `MaterialCategory`, `IsAvailable()`, `ShouldShowInBuildMenu()`, `MaterialSelector.GetValidMaterials(Tag)`, `Tag.Name`, `Db.Get().TechItems.IsTechItemComplete(string)` | Verified by decompiling these members. The catalog uses the same `IsTechItemComplete(def.PrefabID)` unlock check called by `BuildMenu`; only available definitions shown in the build menu are listed. `materials` is an array of material-category objects, each with its category and valid element tag names. Catalog output is written to `oni_catalog.json` through a temporary file. |
| Build command validation and placement | `Assets.GetBuildingDef(string)`, `BuildingDef.DefaultElements()`, `BuildingDef.MaterialsAvailable(IList<Tag>, WorldContainer)`, `BuildingDef.IsValidBuildLocation(GameObject, int, Orientation, bool, out string)`, `BuildingDef.IsValidPlaceLocation(GameObject, int, Orientation, bool, out string, bool)`, `BuildingDef.TryPlace(GameObject, Vector3, Orientation, IList<Tag>, string, bool, int)`, `BuildingDef.BuildingComplete`, `BuildingDef.BuildingUnderConstruction`, `Grid.CellToPosCBC`, `Prioritizable.SetMasterPriority(PrioritySetting)`, `PrioritySetting`, `PriorityScreen.PriorityClass.basic` | Verified by decompiling the APIs and `BuildTool.TryBuild`/`PostProcessBuild`. The player tool uses the same build-location and placement checks, then `TryPlace`; that method creates the under-construction object using the selected element tags. The active-world restriction is enabled. Selected element names are resolved against `MaterialSelector.GetValidMaterials` before inventory checking; omitted materials use `DefaultElements()`. The game's basic priority buttons are 1–9 with 5 as the default. The `not_unlocked` check follows the same `TechItems.IsTechItemComplete(prefabID)` call made by `BuildMenu`. |
| Calories in state JSON | `Database.Amounts.Calories`; `RationTracker.GetItemData` reads `Edible.Calories`; `WorldResourceAmountTracker<RationTracker>.CountAmount` | Verified in ILSpy. Both the dupe amount and total food amount are divided by 1000 for the JSON kcal values; dupe output is named `calories_kcal` and colony food remains `food_kcal`. |
| Building list | `Components.BuildingCompletes.Items`, `BuildingComplete.creationTime`, `Grid.ObjectLayers`, `BuildingUnderConstruction`, `Building.Def.PrefabID`, `Building.GetBottomLeftCell()`, `Building.Orientation`, `Constructable.SelectedElementsTags`, `Deconstructable.constructionElements`, `PrimaryElement.Element.tag` | Verified by decompiling each type and the assembly's call sites. `Constructable.FinishConstruction` calls `BuildingDef.Build(..., GameClock.Instance.GetTime())`; `BuildingDef.Build` stores `timeBuilt` in `BuildingComplete.creationTime` and copies selected material tags to `Deconstructable.constructionElements`. Completed buildings are included only when this player-build timestamp is nonnegative. The `BuildingDef` base `Def` exposes the original `PrefabID`; `BuildingLoader.CreateBuildingUnderConstruction` appends `UnderConstruction` to its `KPrefabID`, so the list uses `Building.Def.PrefabID` to preserve the actual building id. Under-construction objects are enumerated through `Grid.ObjectLayers` and `BuildingUnderConstruction`. The JSON snapshot refreshes every ~10 seconds and is scoped to the active world. |
| Blueprint export | .NET `File.Exists`, `File.WriteAllText`, `File.Replace`, `File.Move`, `File.Delete`; `Time.unscaledTime` | No game API is involved. If `oni_export.flag` exists, the cached `building_list` JSON is written to `blueprint.json.tmp`, atomically moved/replaced as `blueprint.json`, and the flag is deleted only after a successful write. The check runs at most once every 2 unscaled seconds in the `Game.Update` postfix, including while paused. |

## Research API

The following APIs were checked by decompiling the installed
`Assembly-CSharp.dll` and, for `Resource`/`ResourceSet<T>`,
`Assembly-CSharp-firstpass.dll` with `ilspycmd 8.2`. Line references below
refer to the ILSpy-decompiled type output, not original game source files.
The `research` state block is included in `oni_state.json`.

| Need | Verified API and code evidence |
|---|---|
| Enumerate techs and read ID/name | `Db.Get().Techs.resources` is the tech list: `Db.Techs` is declared at `Db.cs:100`; `Database.Techs` inherits `ResourceSet<Tech>` at `Database.Techs.cs:8`; `ResourceSet<T>.resources` is a public `List<T>` at `ResourceSet<T>.cs:8` (`public List<T> resources = new List<T>();`). `ResourceSet<T>` also exposes `Count` and `GetResource(int)` at lines 12–14. `Tech` inherits `Resource`; `Resource.Id` and `Resource.Name` are public fields at `Resource.cs:6–8`. `Tech` constructs its name from `Strings.Get("STRINGS.RESEARCH.TECHS." + id.ToUpper() + ".NAME")` at `Tech.cs:37–40`. `Database.Techs.Load` removes entries without a research-tree node at `Database.Techs.cs:595–600`, so the runtime list after loading contains the research-tree techs, not raw entries omitted from that tree. |
| Find unlocked buildings for each tech | `Tech.unlockedItemIDs` and `Tech.unlockedItems` are public lists at `Tech.cs:11–13`. `Database.Techs.PostProcess` resolves IDs through `Db.Get().TechItems.TryGet(unlockedItemID)` and assigns `resource.unlockedItems = list` at `Database.Techs.cs:516–529`. `ResearchEntry.SetTech` iterates `targetTech.unlockedItems` and reads each `TechItem.Name` at `ResearchEntry.cs:203–215`. These are general tech unlock items, not all necessarily buildings; test each `TechItem.Id` with the verified `Assets.GetBuildingDef(string)` API to select building unlocks. `Database.Techs.IsTechItemComplete(string)` scans unlocked items and returns the parent tech's completion state at `Database.Techs.cs:641–654`; its final `return true` means an ID not found in any tech also returns true, so this method is not an existence check. |
| Completed state | `Tech.IsComplete()` returns `Research.Instance.Get(this)?.IsComplete() ?? false` at `Tech.cs:109–115`. `TechInstance.IsComplete()` returns the private `complete` flag at `TechInstance.cs:32–35`. |
| Selected target vs active research | `Research.GetTargetResearch()` returns `queuedTech[queuedTech.Count - 1]` at `Research.cs:106–113`; this is the requested target at the end of the prerequisite queue. `Research.GetActiveResearch()` returns `activeResearch` at `Research.cs:101–104`; `Research.IsBeingResearched(Tech)` compares `activeResearch.tech == tech` at `Research.cs:60–67`. `Research.GetResearchQueue()` returns a copy of the queue at `Research.cs:323–326`. The active item and target can differ when prerequisites have been queued. |
| Remaining research-point types and progress | Each `Tech.costsByResearchTypeID` entry maps a research type ID to its required point cost (`Tech.cs:17`); `Tech.CanAfford(ResearchPointInventory)` compares each cost with `PointsByTypeID` (`Tech.cs:86–96`). Current points are in `ResearchPointInventory.PointsByTypeID` (`ResearchPointInventory.cs:6`); a tracked tech's per-tech inventory is `TechInstance.progressInventory` (`TechInstance.cs:23`), and per-type completion is calculated by `TechInstance.PercentageCompleteResearchType(string)` (`TechInstance.cs:74–80`). `Research.CheckBuyResearch` uses `UseGlobalPointInventory ? globalPointInventory : activeResearch.progressInventory` (`Research.cs:281–299`). Remaining points for a required type can be computed as `max(cost - currentPoints, 0)`. Resolve display names through `Research.Instance.researchTypes.Types` and each `ResearchType.id`/`name` (`ResearchTypes.cs:20–40`, `ResearchType.cs:17–21`): `basic` is Alpha, `advanced` Beta, `space` Gamma, `nuclear` Delta, and `orbital` Orbital. The decompiled `Techs.PostProcess` adds default tier costs to each tech at `Database.Techs.cs:568–583`. |
| Select a target tech | The public mutator is `Research.SetActiveResearch(Tech, bool clearQueue = false)` (`Research.cs:200–226`). It mutates `queuedTech`/`activeResearch`, notifies research centers, and updates research state. The decompiled UI callback `ResearchEntry.OnResearchClicked` calls `Research.Instance.SetActiveResearch(targetTech, clearQueue: true)` at `ResearchEntry.cs:300–312`. Invoke it on the Unity main thread: the game's own call is from the research UI click callback and it synchronously triggers research-center and game notifications; the method is not a background-work API. |
| Check prerequisite readiness | `Tech.ArePrerequisitesComplete()` iterates `requiredTech` and returns false if any `Tech.IsComplete()` is false (`Tech.cs:7`, `Tech.cs:118–127`). This answers whether prerequisites are complete, but it does not mean the tech cannot be selected: `Research.SetActiveResearch` calls private `AddTechToQueue`, which adds incomplete techs (`if (!orAdd.IsComplete() && !queuedTech.Contains(orAdd))`) and recursively adds `requiredTech` (`Research.cs:155–165`), then sorts the queue by `tier` and sets its first entry active (`Research.cs:200–218`). Thus unmet prerequisites are queued before the requested target rather than blocking selection. |
| `oni_state.json` research snapshot | Refreshed every ~10 seconds on the `Game.Update` postfix. `target`/`active` use `Research.GetTargetResearch()`/`GetActiveResearch()` and `TechInstance.tech.Id` (`Research.cs:101–113`, `TechInstance.cs:19`). `techs` enumerates `Db.Get().Techs.resources`; each object uses `Tech.Id`, `Name`, `IsComplete()`, `ArePrerequisitesComplete()`, `costsByResearchTypeID`, and `Research.Get(Tech)` (`Database.Techs.cs:8`, `ResourceSet<T>.cs:8`, `Resource.cs:6–8`, `Tech.cs:17`, `109–127`, `Research.cs:115–125`). `cost` is one `{type, required, current}` object per required type; `current` reads `TechInstance.progressInventory.PointsByTypeID` (`TechInstance.cs:23`, `ResearchPointInventory.cs:6`), or is 0 when `Research.Get(Tech)` returns null. `unlocks` contains only `TechItem.Id` values whose `Assets.GetBuildingDef(id)` is non-null (`Tech.cs:11–13`, `Database.Techs.cs:516–529`). If `Research.Instance` or `Db.Get()` is null, the entire `research` property is omitted rather than returning stale data. Each tech and each unlock lookup is guarded; a tech that cannot be read is logged and skipped. |
| `set_research` command | The action reads `type` and `tech` from the existing parsed command (`AgentCommandParser.Parse`). On the `Game.Update` postfix/main thread it checks `Research.Instance` and `Db.Get()`, searches `Db.Get().Techs.resources` using `Tech.Id` (case-insensitive), rejects completed techs via `Tech.IsComplete()`, then calls the verified `Research.SetActiveResearch(Tech, bool)` (`Research.cs:200–226`). `ok` is set only after that method returns. |

`set_research` command format:

```json
{"id":"research-1","actions":[{"type":"set_research","tech":"FarmingTech"}]}
```

The `tech` value must be a string matching a technology `Id`; matching is
case-insensitive. The action result uses these reasons:

- `ok` — the requested tech was found, was not complete, and
  `SetActiveResearch(tech, true)` returned successfully.
- `unknown_tech` — the `tech` value is missing/empty or no tech with that ID
  exists.
- `already_complete` — the matching tech is already complete.
- `research_unavailable` — `Research.Instance` or `Db.Get()` is null, or
  setting research raised an exception. Errors are logged.

Game-state reads are individually guarded. A failed read is logged and its
field is omitted; command processing and file writes are guarded, and string
values are escaped before being written as JSON. Command actions are processed
from the `Game.Update` postfix on the game's main thread. All mod cadence
timers (command polling, result writing, state writing, building-list refresh,
and blueprint-flag checks) use `Time.unscaledTime`; state, map, and
`building_list` output therefore continue updating while the game is paused.

The `list_buildings` action writes entries with `id`, `width`, `height`,
`materials` (an array of `{category, options}` objects), and `unlocked`.
The `build` action accepts `id`, `x`, `y`, optional `orientation`, optional
`elements` (one tag name per material category), and optional `priority`.
Orientation defaults to `Neutral`, omitted elements use the game's
`BuildingDef.DefaultElements()`, and priority defaults to Basic 5.

### Build command coordinate and orientation rules

`orientation` must be a JSON **string** with one of these exact values:
`"Neutral"`, `"R90"`, `"R180"`, `"R270"`, `"FlipH"`, or `"FlipV"`.
Do not send a number or enum ordinal. The command parser requires a string;
an invalid type makes parsing of the whole `oni_commands.json` fail, so no
action from that file is processed and `oni_results.json` is not refreshed.

For `build`, `x` and `y` identify the building's placement pivot cell, not a
generic bounding-box corner. For a three-cell-wide `MedicalCot` placed with
`"Neutral"` orientation, `x` is the middle cell and `y` is the bottom row.
Example:

```json
{"id":"build-1","actions":[{"type":"build","id":"MedicalCot","x":20,"y":10,"orientation":"Neutral"}]}
```

The action converts this `(x, y)` cell with `Grid.XYToCell` and passes it to
the game's `BuildingDef` placement checks and `TryPlace`; dimensions and
orientation determine the footprint around that pivot.

## Not included

- `oxygen_inventory_kg` is the oxygen-tagged amount in `WorldInventory`; it is
  **not** a measurement of breathable oxygen in the world atmosphere. No
  atmospheric oxygen total or low-oxygen alert is reported.
- Coal and stored energy are omitted. No `GameTags.Coal` tag was found, and
  battery charge was not added without verifying a suitable API.
- The game does not provide a confirmed hunger threshold in the APIs used
  here, so the dupe warning is limited to exactly zero calories. The
  high-stress threshold of 90 is a simple heuristic on the verified 0–100
  stress scale.
- The optional `world.start` uses a valid `Telepad` found in the active
  world; a printing-pod-specific lookup is not included.
- A `dig` request is not applied if the DigTool singleton is unavailable or
  its tiles filter is off. The mod does not change player tool settings.
- Missing dig coordinates return `invalid_coordinates`; unsupported action
  types return `unsupported`. Other dig failures use `out_of_bounds`,
  `already_marked`, `not_solid`, `undiggable`, `world_unavailable`,
  `dig_tool_unavailable`, `dig_tool_tiles_filter_disabled`, or
  `game_state_error`.
