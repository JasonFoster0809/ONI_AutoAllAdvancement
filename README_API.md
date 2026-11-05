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
`"Neutral"` orientation, `x` is the middle cell; for a two-cell-wide building,
`x` is the left cell. `y` is the bottom row. Pivot positions for orientations
other than `"Neutral"` have not been tested.
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

## Cancel API

The cancel action uses the game's `GameHashes.Cancel` event. ILSpy
decompilation of `GameHashes.cs` confirms it is `2127324410`. `CancelTool.cs`,
`OnDragTool(int, int)` (lines 38-48), loops over `Grid.Objects[cell, i]` for
layers `0` through `44` and triggers this event on objects accepted by the
cancel-tool filter. `Grid.ObjectLayerIndexer` in `Grid.cs` exposes the
`GameObject this[int cell, int layer]` indexer.

- Dig orders: `DigPlacerConfig.CreatePrefab()` (`DigPlacerConfig.cs`, lines
  15-24) attaches `Diggable` and `CancellableDig`. The player menu callback
  `Diggable.OnCancel()` (`Diggable.cs`, lines 553-560) triggers
  `GameHashes.Cancel`. `CancellableDig.OnCancel(object)` and
  `OnAnimationDone(string)` (`CancellableDig.cs`, lines 6-37) play the
  cancellation animation and delete the dig order when that animation
  completes. `Diggable.GetDiggable(int)` (`Diggable.cs`, lines 409-417) looks
  up the order through `Grid.Objects[cell, 7]`.
- Construction orders: `Constructable.OnSpawn()` (`Constructable.cs`, line
  342) subscribes to the same event. Its user-menu callback
  `OnPressCancel()` (`Constructable.cs`, lines 856-859) triggers it, and
  `Constructable.OnCancel(object)` (lines 861-865) clears material needs and
  pending uproots. `BuildingLoader.CreateBuildingUnderConstruction()`
  (`BuildingLoader.cs`, lines 157-174) adds the generic `Cancellable`
  component when the definition is cancellable; `Cancellable.OnCancel(object)`
  (`Cancellable.cs`, lines 14-18) deletes the order.
- Materials: `Storage` subscribes to queued destruction
  (`Storage.cs`, line 287). Its `OnQueueDestroyObject(object)` and
  `DropAll(...)` (`Storage.cs`, lines 1332-1340 and 739-783) drop stored
  construction materials into the world when the construction order is
  deleted; they are not returned directly to inventory.
- Cell lookup: `Grid.Objects` is the verified `Grid.ObjectLayerIndexer`
  field/indexer. The lookup scans the cell's object layers using the same
  `0..44` range used by the game's `CancelTool`, then checks for a
  `Constructable` component. `Diggable.GetDiggable(int)` is used first for a
  dig order. Active-world bounds are checked using the already documented
  `WorldContainer` and `Grid` APIs.

The action only triggers the game's cancellation event on the main thread.
For dig orders, the event starts a cancellation animation; a successful result
means the cancellation event was handled, not that the animation has already
finished.

Command shape: `{"type":"cancel","x":12,"y":34}`. Results use
`ok`/`nothing_to_cancel`/`out_of_bounds`/`error`; successful results also
include `"cancelled":"dig"` or `"cancelled":"build"`. Missing coordinates and
unexpected API errors return `error`.

## Set priority API

`Prioritizable.GetMasterPriority()` and `SetMasterPriority(PrioritySetting)`
are public methods in `Prioritizable.cs` (lines 125-140).
`Prioritizable.IsPrioritizable()` (line 182) confirms that the component is
currently registered for prioritization. The game's `AttackTool.OnDragTool`
(`AttackTool.cs`, lines 25-35) changes a target's priority through
`SetMasterPriority(ToolMenu.Instance.PriorityScreen.GetLastSelectedPriority())`.

`PrioritySetting` (`PrioritySetting.cs`, line 78) has a constructor accepting
`PriorityScreen.PriorityClass` and an integer priority value.
`PriorityScreen.InstantiateButtons()` (`PriorityScreen.cs`, lines 53-61)
creates the standard `basic` priority buttons numbered 1 through 9. The
action uses `new PrioritySetting(PriorityScreen.PriorityClass.basic, value)`.
The code locates prioritizable objects in the specified active-world cell via
the verified `Grid.Objects[cell, layer]` indexer, considering layers `0..44`
as in the game's `CancelTool.OnDragTool`.

Command shape: `{"type":"set_priority","x":12,"y":34,"priority":8}`.
Results use `ok`, `nothing_found`, `invalid_priority`, or `out_of_bounds`.
Unexpected exceptions are logged and reported as `nothing_found`, the closest
failure reason available in the requested result set.

## Achievement state API

`SaveGame.Instance` and its `ColonyAchievementTracker` property are confirmed
in `SaveGame.cs` (lines 146 and 185-194). `ColonyAchievementTracker.OnSpawn()`
(`ColonyAchievementTracker.cs`, lines 216-227) creates status entries for
`Db.Get().ColonyAchievements.resources`; the tracker's public
`achievements` dictionary maps achievement IDs to `ColonyAchievementStatus`.
`ColonyAchievementStatus.success` is the achieved flag, and
`Requirements` exposes the achievement's requirement list
(`ColonyAchievementStatus.cs`, lines 9-15).

Each `ColonyAchievementRequirement` exposes `GetProgress(bool)` and
`Success()` (`Database/ColonyAchievementRequirement.cs`, lines 7-14).
`AchievementWidget.ShowRequirement()` (`AchievementWidget.cs`, lines 319-331)
uses `GetProgress(flag)` for the displayed progress text. The snapshot reports
each database achievement's ID and name, its `success` value as `achieved`,
and the non-empty strings returned by each requirement's `GetProgress`.
The resulting `achievements` array contains `{id, name, achieved, progress}`,
where `progress` is an array of requirement strings.

## Environment state API

`Grid.Temperature`, `Grid.Mass`, and `Grid.Element` are public grid indexers
(`Grid.cs`, lines 744-748 and the `TemperatureIndexer` definition at line
492). `Element.id` and `Element.IsGas` distinguish gas species; the
`SimHashes.Oxygen` and `SimHashes.CarbonDioxide` values are present in
`SimHashes.cs` (lines 19 and 4). Existing code also verifies
`Grid.XYToCell`, `Grid.IsValidCell`, `Grid.IsValidCellInWorld`, and
`Grid.WorldIdx`.

These APIs support a telepad-centered 11x11 snapshot: average temperature in
Kelvin across valid active-world cells, plus oxygen and carbon-dioxide gas
mass averaged per valid cell and reported in grams.
The optional `environment` object contains `temperature_avg_k`, `oxygen_avg_g`,
and `co2_avg_g`; it is omitted if there is no valid telepad-centered sample.

## Power and water state APIs

`Components.Generators` and `Components.Batteries` are public `Cmps<T>`
collections (`Components.cs`, lines 381 and 385). `Battery.JoulesAvailable`,
`Battery.Capacity`, and `Battery.PowerCell` are public (`Battery.cs`, lines
60-70); `Generator.WattageRating`, `Generator.PowerCell`, and
`Generator.IsProducingPower()` are confirmed in `Generator.cs` (lines 64, 80,
and 122).

`CircuitManager.GetCircuitID(int)`, `GetWattsUsedByCircuit(ushort)`,
`GetWattsGeneratedByCircuit(ushort)`,
`GetPotentialWattsGeneratedByCircuit(ushort)`, and
`GetJoulesAvailableOnCircuit(ushort)` are public APIs in `CircuitManager.cs`
(lines 117, 599, 684, 701, and 715). Battery and generator power cells are
filtered to the active world before circuit totals are collected. Circuits
without a battery or generator component in the active world are not included
in these totals.
The optional `power` object contains `battery_joules`,
`battery_capacity_joules`, `circuit_joules_available`, `watts_used`,
`watts_generated`, `watts_potential`, and `circuits`.

Water is already reported in `resources.clean_water_kg` using the verified
`WorldContainer.worldInventory`, `WorldInventory.GetAmount(GameTags.Water,
false)` APIs described above; no duplicate water block is needed.

## Schedule API

`ScheduleManager.Instance`, `GetSchedules()`, and
`GetSchedule(Schedulable)` are public APIs in `ScheduleManager.cs` (lines 33
and 235-252). `Schedulable.GetSchedule()` (`Schedulable.cs`, line 6) returns
the schedule assigned to a duplicant. `Schedule.GetBlocks()` returns its
blocks (`Schedule.cs`, line 212), and `GetCurrentScheduleBlock()` identifies
the active block (line 44).

Each `ScheduleBlock` exposes its `name`, `GroupId`, and `allowed_types`
(`ScheduleBlock.cs`, lines 9-30). `ScheduleGroup` exposes `allowedTypes`
(`ScheduleGroup.cs`, line 15), and `Schedule.SetBlockGroup(int, ScheduleGroup)`
changes a block and notifies assigned duplicants (`Schedule.cs`, lines
191-210). `Db.Get().ScheduleGroups.Get(id)` is used by the game to resolve
block group IDs; the built-in groups are `Hygene`, `Worktime`, `Recreation`,
and `Sleep` (`Database/ScheduleGroups.cs`). `ScheduleBlockTypes` defines
`Sleep`, `Eat`, `Work`, `Hygiene`, and `Recreation` (`Database/ScheduleBlockTypes.cs`,
lines 21-25). State can safely report each duplicant's assigned schedule and
its block group IDs; the state array reports schedule names, all block group
IDs, and assigned duplicant names. The `schedule` state cache refreshes every
10 seconds.

The action uses a schedule-name selector because schedules are shared by all
assigned duplicants:
`{"type":"schedule","schedule":"Default","blocks":[...]}`. The `blocks` array
must contain exactly 24 known schedule-group IDs (`Hygene`, `Worktime`,
`Recreation`, or `Sleep`). A selected schedule with other than 24 blocks is
unavailable and is left unchanged. Reasons are `ok`, `invalid_blocks`,
`unavailable`, or `error`.

Valid example using the game's default group counts:

```json
{"id":"schedule-001","actions":[{"type":"schedule","schedule":"Default","blocks":["Hygene","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Recreation","Recreation","Sleep","Sleep","Sleep"]}]}
```

## Dupe job-priority API

`ChoreConsumer` is attached to minion prefabs by `BaseMinionConfig` (`line
90`). It exposes `GetPersonalPriority(ChoreGroup)` and
`SetPersonalPriority(ChoreGroup, int)` (`ChoreConsumer.cs`, lines 537-560).
The implementation clamps values to the verified constants
`MIN_PERSONAL_PRIORITY = 0` and `MAX_PERSONAL_PRIORITY = 5` (lines 51-53);
the action validates this range before calling the setter.

`Database.ChoreGroups.resources` contains the real group resources;
`ChoreGroup.Id`, `choreTypes`, and `userPrioritizable` are defined in
`ChoreGroup.cs`. The Jobs screen obtains each duplicant's
`ChoreConsumer` and invokes `SetPersonalPriority` for its selected
`ChoreGroup` (`JobsTableScreen.cs`, lines 305-306 and 450). State exposes
`dupes[].job_priorities` as an object keyed by chore-group ID for
user-prioritizable groups with chore types.

Action example:

```json
{"id":"dupe-priority-001","actions":[{"type":"set_dupe_priority","dupe":"Ada","group":"Dig","priority":4}]}
```

Supported results are `ok`, `unknown_dupe`, `unknown_group`,
`invalid_priority`, `unavailable`, or `error`.

## Python agent

The offline Python package is under `agent/`. `oni_client.py` reads
`oni_state.json`, warns if its modification time is older than 10 seconds,
writes one command with a unique ID, and waits for a matching result. The data
directory can be set with `ONI_DATA_DIR`; otherwise it uses
`%USERPROFILE%\Documents\Klei\OxygenNotIncluded`.

`maputils.py` treats `world.map` as top-to-bottom rows and `world.origin` as
the lower-left coordinate. Building pivot conventions match the mod:
three-cell widths use the middle cell and two-cell widths use the left cell;
the y coordinate is the bottom row. `catalog.py` uses only prefab IDs and
material options from `oni_catalog.json`.

The state includes `resources.materials`, refreshed on the same approximately
10-second cadence as the building-list cache. `catalog.choose_materials`
uses the positive amounts in this object together with each catalog material
category's options. It matches names case-insensitively but returns the name
exactly as written in the state. The catalog does not specify a required kg
amount, so any positive finite stock is treated as available; this does not
guarantee that a building's full construction cost is covered. Skill planners
return action lists without sending them. The bedroom planner places a bed and
door in a clear supported footprint; it does not build or verify room walls.

## Construction mass API

Verified against the installed
`D:\Oxygen Not Included\OxygenNotIncluded_Data\Managed\Assembly-CSharp.dll`
by decompiling `BuildingDef`, `Recipe`, `Pickupable`, `PrimaryElement`, and
`GameUtil` with `ilspycmd 8.2`:

- `BuildingDef.MaterialCategory` is `string[]`; `BuildingDef.Mass` is
  `float[]`. In `BuildingDef.PostProcess()`, the game loops from index zero to
  `MaterialCategory.Length` and creates
  `new Recipe.Ingredient(MaterialCategory[i], (int)Mass[i])`. Therefore the
  construction mass for category `i` is aligned by the same array index:
  `MaterialCategory[i]` ↔ `Mass[i]`. The value used for the construction
  recipe is the integer truncation `(int)Mass[i]`, not a rounded value.
- `BuildingDef.MaterialsAvailable(selected_elements, world)` calls
  `CraftRecipe.GetAllIngredients(selected_elements)`; `Recipe.GetAllIngredients`
  substitutes the selected material tag at the corresponding ingredient
  index and preserves that ingredient's amount. The game then compares
  `world.worldInventory.GetAmount(ingredient.tag, true)` against
  `ingredient.amount`.
- `Recipe.Ingredient.amount` is the required material quantity. The stock
  amount path is `WorldInventory` → `Pickupable.TotalAmount` →
  `PrimaryElement.Units`; `PrimaryElement.Mass` is
  `Units * MassPerUnit`. `GameUtil.MassUnit` has `Kilograms` and `Pounds`
  display modes and `GetFormattedMass` formats these quantities using the
  configured mass unit. Construction categories in the catalog are solid
  materials, for which the recipe amount is used as the game's construction
  material mass. The construction requirement is therefore recorded in the
  game's mass amount, conventionally kg; displayed unit formatting can
  depend on the user's `GameUtil.massUnit` setting.
- `BuildingDef.PostProcess()` is the source of the category-to-mass mapping;
  `BuildingDef.MaterialsAvailable()` is the source of the material sufficiency
  check. `MaterialsAvailable` passes `includeRelatedWorlds: true`, so its
  live build check may count related-world inventory. The agent's
  `resources.materials` snapshot uses `GetAmount(tag, false)` for the active
  world only; a Python stock comparison can consequently be more
  conservative than the game's build-tool check.

The existing catalog shape has one object per category:

```json
{
  "materials": [
    {
      "category": "Metal",
      "options": ["Copper", "Gold"],
      "mass_kg": 100
    }
  ]
}
```

`mass_kg` should reflect the game's recipe amount `(int)BuildingDef.Mass[i]`.
Only emit it when the index exists and the value can be read; otherwise omit
the field and retain the category/options entry. The catalog field names
`category` and `options` preserve the existing `MaterialCategory` and
`MaterialSelector.GetValidMaterials` output.

`agent.catalog.choose_materials` compares each candidate option's inventory
amount with that category's `mass_kg` and chooses only options meeting or
exceeding the requirement. It matches case-insensitively and returns the
inventory key's original casing. An older catalog without `mass_kg` logs a
warning and uses the prior positive-stock behavior. A present but invalid
`mass_kg` is rejected as `invalid_material_mass`; no available option with
enough stock yields `insufficient_material`.

## Material inventory API

Verified against the installed
`D:\Oxygen Not Included\OxygenNotIncluded_Data\Managed\Assembly-CSharp.dll`
by decompiling `WorldInventory`, `ElementLoader`, and `Element` with
`ilspycmd 8.2`:

- `ClusterManager.Instance.activeWorld.worldInventory` returns the inventory
  for the active world; these members are also used by the existing resource
  fields in `Mod.cs`.
- `WorldInventory.GetAmount(Tag tag, bool includeRelatedWorlds)` returns a
  `float`. In the decompiled implementation, `false` uses this inventory's
  `GetTotalAmount(tag, false)` and subtracts
  `MaterialNeeds.GetAmount(tag, worldId, false)`, then clamps the result at
  zero. This is the available amount rather than the gross amount already
  committed to construction. `true` instead delegates to
  `ClusterUtil.GetAmountFromRelatedWorlds`; do not use it for an active-world
  only snapshot.
- `ElementLoader.elements` is a public `List<Element>` populated by
  `ElementLoader.Load(...)`. `ElementLoader.elementTagTable` is a public
  `Dictionary<Tag, Element>` populated from each loaded element's tag.
- `Element.tag` is a public `Tag` field on `Element`; `Tag.Name` is the tag's
  string name. Thus, for each loaded element, `element.tag` is the tag passed
  to `WorldInventory.GetAmount`, and `element.tag.Name` is the JSON key.
  Examples such as `SandStone`, `Cuprite`, `Dirt`, and `Algae` should be
  emitted only when those names occur in the loaded elements; do not form
  tags from unverified input strings.
- `WorldInventory.GetAccessibleAmounts()` returns a public
  `Dictionary<Tag, float>`, but its values are the cached accessible totals
  maintained by `WorldInventory.Update`. `GetTotalAmount` reads this cache;
  unlike `GetAmount`, the raw accessible total does not subtract
  `MaterialNeeds`. It is therefore not interchangeable with the
  reservation-aware amount when choosing construction materials.

State shape:

```json
{
  "resources": {
    "materials": {
      "SandStone": 1234.5,
      "Dirt": 250.0,
      "Algae": 50.0
    }
  }
}
```

Use each element's verified `tag.Name` as the key and its
`activeWorld.worldInventory.GetAmount(element.tag, false)` as the value.
Only positive amounts are included, rounded to one decimal place; elements
whose rounded value is zero are omitted. The example names and amounts are
illustrative, not claims about a live colony.

For a complete snapshot, the direct `ElementLoader.elements` approach makes
one `GetAmount` query per loaded element tag per cache refresh:
`ElementLoader.elements.Count` queries and O(N) tag iteration, where N is
the runtime-loaded element count. The DLL does not establish a fixed count:
the list is populated from loaded element definitions, so DLC/mod content
can affect it. No performance measurement was made. The cache refreshes
approximately every 10 seconds, rather than iterating the element list on
every approximately 2-second state write. If a refresh fails, the
`resources.materials` property is omitted until a later refresh succeeds;
other resource properties remain available.

`rules.py` uses conservative automation heuristics, not game danger
thresholds: oxygen below 50 g per sampled cell, less than 100 kcal on a dupe,
stress at least 90, or an environment average outside 273.15-318.15 K triggers
an emergency decision before skill planning. The current `agent_main.py` does
not configure emergency-specific repair candidates, so an emergency currently
selects no-op and skips the LLM. `llm_chooser.py`
contacts only the local Ollama endpoint at
`http://localhost:11434/api/generate`, with model `qwen2.5-coder:3b` and
temperature zero. Its returned ID must match a supplied candidate; failures
fall back to no-op.

Run one offline/dry-run step with:

```powershell
python -m agent.agent_main --dry-run --max-steps 1
```

For build skills, pass prefab IDs copied from `oni_catalog.json`, for example
`--research-center-id <id>` or both `--bed-id <id> --door-id <id>`. A corridor
can be supplied as `--corridor x1,y1,x2,y2`. The agent writes JSON Lines logs
to `logs/agent.jsonl`.

## Room API

Verified against `Assembly-CSharp.dll` with `ilspycmd 8.2`; the code snippets
below are from the decompiled game sources:

- `Game.roomProber` is a public `RoomProber` field. `Game` constructs it with
  `roomProber = new RoomProber()` and registers it with the simulation
  scheduler. `RoomProber.rooms` is the public `List<Room>` containing the
  room objects currently known to that prober. The prober's flood fill uses
  the current `Grid`; this is the runtime room list for the active simulation
  grid.
- Each `Room` exposes `roomType` and `cavity`. `RoomType` derives from
  `Resource`, whose public `Id` and `Name` members are defined in
  `Assembly-CSharp-firstpass.dll`. `RoomType.isSatisfactory(Room)` evaluates
  its primary and additional constraints; the prober assigns the result using
  `Db.Get().RoomTypes.GetRoomType(room)`.
- `CavityInfo.NumCells` returns `cells == null ? 0 : cells.Count`;
  `CavityInfo.cells` is a `List<int>` of the actual cells visited by the
  RoomProber flood fill. `RefreshModule.Visitor.VisitCell` assigns the cavity
  handle to a visited cell and adds that cell to `cavityCells`; the builder
  stores that list on `CavityInfo.cells`. Thus membership is checked by
  comparing a grid-cell index against this list, not by using only the
  `minX/minY/maxX/maxY` bounding rectangle (which could include cells outside
  an irregular cavity).
- A stable representative is the actual cavity cell with the smallest y,
  then the smallest x. Convert every valid `cavity.cells` entry through
  `Grid.CellToXY(int, out int, out int)` and compare coordinates. Do not rely
  on the list's iteration order; the game does not guarantee that it is
  sorted. This avoids reporting a different coordinate when the cavity's
  internal cell ordering changes.
- The database type is `Database.RoomTypes`; its `Barracks` field is
  initialized as `new RoomType("Barracks", ...)`. The constructor passes
  `RoomConstraints.HAS_BED` as the primary constraint and
  `NO_INDUSTRIAL_MACHINERY`, `MINIMUM_SIZE_12`, and `MAXIMUM_SIZE_64` as
  additional constraints. The decompiled predicates verify that a Barracks
  has at least one building tagged `BedType` and not `Clinic`, contains no
  building tagged `IndustrialMachinery`, and has `cavity.NumCells` from 12
  through 64 inclusive. This agrees with the user's tooltip for these
  constraints.
- `Database.RoomTypes.GetRoomType(Room)` iterates non-Neutral room types and
  returns the first unambiguous type whose `isSatisfactory(room)` result is
  `all_satisfied`; if none qualifies, it returns `Neutral`. Thus the verified
  implementation can report an oversized room as Neutral when its room type
  constraints fail.
- `RoomProber.IsCavityBoundary(int)` treats a cell as a boundary when its
  `Grid.BuildMasks` includes `Grid.BuildFlags.Solid` or `Foundation`; if
  neither is present, `Grid.HasDoor[cell]` decides the boundary. The
  `RefreshModule` then invokes `FloodFill.DepthTraverse` with this boundary
  predicate. A room is therefore an enclosed cavity according to these
  grid rules, not merely an arbitrary rectangle.

Representative decompiled source:

```csharp
// RoomProber.CreateRoom
room.roomType = Db.Get().RoomTypes.GetRoomType(room);

// RoomConstraints
MINIMUM_SIZE_12 = new Constraint(null,
    (Room room) => room.cavity.NumCells >= 12, ...);
MAXIMUM_SIZE_64 = new Constraint(null,
    (Room room) => room.cavity.NumCells <= 64, ...);
HAS_BED = new Constraint((KPrefabID bc) =>
    bc.HasTag(ConstraintTags.BedType) && !bc.HasTag(ConstraintTags.Clinic), ...);
```

Recommended state representation:

```json
{
  "rooms": [
    {"type": "Barracks", "size": 20, "x": 12, "y": 8}
  ]
}
```

`type` is `room.roomType.Id`, `size` is `room.cavity.NumCells`, and `x,y`
are the stable representative above. Skip null or incomplete room/cavity
entries. Only non-`Neutral` room types are always included. For `Neutral`,
the mod includes the room only if one or more cell indices in
`room.cavity.cells` exactly match a `cell` from the cached `building_list`.
That list is built from completed buildings and `BuildingUnderConstruction`
objects and excludes the same Prop/POI/Gravitas prefab IDs as the existing
building-list output. This preserves player-built areas that the game labels
Neutral (including rooms whose size exceeds a type's constraints) while
excluding natural/empty Neutral cavities without listed buildings. All
non-Neutral types are retained regardless of whether a player building is
found.

The room collection pass is O(R + C), where R is the RoomProber room count
and C is the sum of the cell counts for entries traversed; it converts each
valid cavity cell once to determine the stable coordinate and Neutral
membership. The building list is indexed by a `HashSet<int>` for expected
constant-time matching. The scan is cached approximately every 10 seconds,
not every approximately 2-second state write. This is an operation-count
estimate; runtime cost was not profiled.

The current C# state implementation emits the `rooms` property only when the
RoomProber snapshot succeeds. It refreshes the serialized array approximately
every 10 seconds, keyed by active world ID; an unavailable prober or a
refresh-level error omits the property. Individual invalid room entries are
logged and skipped. The implementation uses `Game.Instance.roomProber.rooms`,
`Room.roomType.Id`, `Room.cavity.NumCells`, `Room.cavity.cells`, and
`Grid.CellToXY`. It derives the building-cell membership index from the same
completed/construction entries used to serialize `building_list`; the JSON
shape remains `type`, `size`, `x`, and `y`.

## Operational status API

Verified against the installed
`D:\Oxygen Not Included\OxygenNotIncluded_Data\Managed\Assembly-CSharp.dll`
using `ilspycmd 8.2` decompilation of `Operational`, `EnergyConsumer`,
`IEnergyConsumer`, `Storage`, `PrimaryElement`, `ElementConverter`,
`Building`, `BuildingComplete`, and `MineralDeoxidizerConfig`:

- Built entries originate from `Components.BuildingCompletes.Items`; the
  existing filter requires `BuildingComplete.creationTime >= 0`. Therefore
  operational telemetry is only applicable to entries with `state: "built"`.
- `Operational.IsOperational` is the aggregate requirements state. Its
  `Flags` dictionary maps `Operational.Flag` objects (`Name` and `FlagType`)
  to booleans. `UpdateOperational()` makes `IsOperational` false if any
  recorded flag is false. `Operational.IsActive` is a distinct state for
  actually active work; it is not a synonym for available/operational and
  should not be used for the `operational` snapshot field. An absent
  `Operational` component leaves the field unknown and should omit it.
- Power is identifiable by the building definition's
  `RequiresPowerInput`; `IEnergyConsumer.IsPowered` is available on the
  building component. `EnergyConsumer.IsPowered` returns the operational
  `PoweredFlag`. A building without a power-input requirement should omit
  `powered`; when the relevant consumer component is absent or unreadable,
  omit only that field.
- `Storage.GetAmountAvailable(Tag)` returns the sum of matching stored
  `PrimaryElement.Units`; the overload accepting forbidden tags does the same
  for non-forbidden items. `PrimaryElement.Mass` is `Units * MassPerUnit`.
  For kg-valued stored material telemetry, sum `PrimaryElement.Mass` over
  matching `Storage.items`, or use `GetAmountAvailable` only when the
  material's units are verified to equal kg. In particular,
  `MineralDeoxidizerConfig` sets the storage capacity in kg and requests
  Algae; per-item `MassPerUnit` is not established by this config alone, so
  directly labeling `GetAmountAvailable(new Tag("Algae"))` as kg is
  **CHƯA XÁC MINH**. Any stored-mass field must be omitted if the kg
  conversion cannot be verified.

The following `MineralDeoxidizerConfig` lines are verbatim from the
decompiled game code:

```csharp
private const float ALGAE_BURN_RATE = 0.55f;
private const float ALGAE_STORAGE = 330f;
private const float OXYGEN_GENERATION_RATE = 0.5f;

obj.RequiresPowerInput = true;
obj.EnergyConsumptionWhenActive = 120f;
obj.ExhaustKilowattsWhenActive = 0.5f;
obj.SelfHeatKilowattsWhenActive = 1f;

storage.capacityKg = 330f;
elementConverter.consumedElements = new ElementConverter.ConsumedElement[1]
{
    new ElementConverter.ConsumedElement(new Tag("Algae"), 0.55f)
};
elementConverter.outputElements = new ElementConverter.OutputElement[1]
{
    new ElementConverter.OutputElement(0.5f, SimHashes.Oxygen, 303.15f,
        useEntityTemperature: false, storeOutput: false, emissionOffset.x, emissionOffset.y)
};
manualDeliveryKG.RequestedItemTag = new Tag("Algae");
manualDeliveryKG.capacity = 330f;
manualDeliveryKG.refillMass = 132f;
```

`ElementConverter.ConsumedElement` and `OutputElement` constructors name their
rate parameter `kgPerSecond`; the configured rates are therefore 0.55 kg/s
Algae consumption and 0.5 kg/s Oxygen generation while operating. The
decompiled building definition requires power and specifies 120 W active
consumption. This verifies the configured operating recipe, not actual
throughput in a live colony. Other runtime constraints such as control
settings or game-state effects should be treated as **cần kiểm chứng** unless
separately confirmed from the installed game code.

The `building_list` implementation adds optional `operational` to built
entries when their `Operational` component is readable. It adds `powered`
only when `Building.Def.RequiresPowerInput` is true and an
`IEnergyConsumer` component is available. For any built entry with a readable
`Storage`, `stored` is a list of element names and masses, aggregated from
`Storage.items` using each item's `PrimaryElement.Element.tag.Name` and
`PrimaryElement.Mass`. For example:

```json
{"stored":[{"element":"Algae","kg":12.5}]}
```

An empty but readable storage is serialized as an empty list. A building
without a `Storage` component or with an unreadable storage omits `stored`.
If any item in a storage cannot be read, the entire `stored` field is omitted
to avoid presenting a partial total. Under-construction entries are
unchanged. Each telemetry field and stored item has its own exception
handling and warning, so a failed read does not discard the building entry.
These values are included in the existing `building_list` cache
refresh at approximately 10-second intervals; no additional sampling
interval was added.

## Dupe room, assigned bed, and food consumption APIs

Verified with `ilspycmd 8.2` against the installed
`D:\Oxygen Not Included\OxygenNotIncluded_Data\Managed\Assembly-CSharp.dll`:

- `Game.roomProber.GetRoomOfGameObject(GameObject)` resolves the room
  containing a duplicant. `Room.roomType.Id` is the room type ID;
  `Room.cavity.cells` supplies the actual room cells. The state reports
  optional `room_type` and a representative `room_x`, `room_y`, chosen from
  the valid cavity cell with lowest y and then lowest x. If no room or valid
  cavity cell is available, the corresponding fields are omitted.
- `StateMachineController.GetSMI<SleepChoreMonitor.Instance>()` returns the
  dupe's sleep monitor instance. `SleepChoreMonitor` exposes the `bed`
  `TargetParameter`; its `Get(smi)` value is the assigned `GameObject` passed
  directly to the `SleepChore` constructor. The state can therefore report
  `bed_id` as the assigned bed's cell index, with optional `bed_x` and
  `bed_y` coordinates derived from `Grid.PosToCell` and `Grid.CellToXY`.
  Missing monitor/target or an invalid cell omits these optional fields.
- `RationTracker` inherits `WorldResourceAmountTracker<RationTracker>`.
  `GetAmountConsumed()` sums `amountsConsumedByID`; that dictionary is
  incremented by `RegisterAmountConsumed` and is not reset by
  `WorldResourceAmountTracker.OnNewDay` (which only rolls `currentFrame`
  into `previousFrame`). Consequently, the installed API does **not** verify
  a per-cycle total for `food_consumption_kcal_per_cycle`; that field is
  **CHƯA XÁC MINH** and is omitted rather than reporting a misleading value.

All new game-object and component reads occur in the existing `Game.Update`
postfix on the main thread. Room and assigned-bed values are cached with the
existing `building_list` refresh at approximately 10-second intervals.
These are optional per-dupe fields; an error for one field or dupe is logged
and does not prevent serialization of other dupes or the separately cached
`building_list`. The agent's Algae warning reader accepts both this `stored`
list and the older mapping-shaped state.
