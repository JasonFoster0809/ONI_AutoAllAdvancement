using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using HarmonyLib;
using KMod;
using UnityEngine;

namespace OniAgent
{
    public class Mod : UserMod2
    {
        public override void OnLoad(Harmony harmony)
        {
            base.OnLoad(harmony);
            Debug.Log("[OniAgent] Mod da duoc nap!");
        }
    }

    // Chạy mỗi frame, nhưng chỉ ghi file mỗi 2 giây thực
    [HarmonyPatch(typeof(Game), "Update")]
    public class Game_Update_Patch
    {
        static float nextWrite = 0f;
        static float nextCommandRead = 0f;
        static float nextResultWrite = 0f;
        static float nextBlueprintExportCheck = 0f;
        static float nextBuildingListUpdate = 0f;
        static float nextResearchUpdate = 0f;
        static int cachedBuildingWorldId = int.MinValue;
        static string cachedBuildingListJson = "[]";
        static string cachedResearchJson;
        static string lastProcessedCommandId = string.Empty;
        static AgentCommand pendingCommand;
        static readonly Queue<AgentCommandResult> pendingResults = new Queue<AgentCommandResult>();
        static readonly string OutPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "oni_state.json");
        static readonly string CommandPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "oni_commands.json");
        static readonly string ResultsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "oni_results.json");
        static readonly string ResultsTempPath = ResultsPath + ".tmp";
        static readonly string ExportFlagPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "oni_export.flag");
        static readonly string BlueprintPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "blueprint.json");
        static readonly string BlueprintTempPath = BlueprintPath + ".tmp";
        static readonly string CatalogPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Klei", "OxygenNotIncluded", "oni_catalog.json");
        static readonly string CatalogTempPath = CatalogPath + ".tmp";

        public static void Postfix()
        {
            PollCommandFile();
            ProcessPendingCommand();
            WritePendingResults();

            var sb = new StringBuilder();
            sb.Append("{");
            bool hasRootProperty = false;

            try
            {
                AppendNumberProperty(sb, ref hasRootProperty, "cycle", GameClock.Instance.GetCycle());
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read cycle: " + e);
            }

            try
            {
                AppendNumberProperty(sb, ref hasRootProperty, "time_in_cycle", GameClock.Instance.GetTimeSinceStartOfCycle());
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read time_in_cycle: " + e);
            }

            AppendPropertyPrefix(sb, ref hasRootProperty, "resources");
            sb.Append("{");
            bool hasResourceProperty = false;

            try
            {
                var inventory = ClusterManager.Instance.activeWorld.worldInventory;
                AppendNumberProperty(sb, ref hasResourceProperty, "food_kcal",
                    WorldResourceAmountTracker<RationTracker>.Get().CountAmount(null, inventory) / 1000f);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read food_kcal: " + e);
            }

            try
            {
                var inventory = ClusterManager.Instance.activeWorld.worldInventory;
                AppendNumberProperty(sb, ref hasResourceProperty, "oxygen_inventory_kg",
                    inventory.GetAmount(GameTags.Oxygen, false));
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read oxygen inventory: " + e);
            }

            try
            {
                var inventory = ClusterManager.Instance.activeWorld.worldInventory;
                AppendNumberProperty(sb, ref hasResourceProperty, "clean_water_kg",
                    inventory.GetAmount(GameTags.Water, false));
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read clean water: " + e);
            }
            sb.Append("}");

            AppendPropertyPrefix(sb, ref hasRootProperty, "world");
            sb.Append("{");
            bool hasWorldProperty = false;
            WorldContainer activeWorld = null;
            bool hasStartPosition = false;
            int startX = 0;
            int startY = 0;
            try
            {
                activeWorld = ClusterManager.Instance.activeWorld;
                AppendNumberProperty(sb, ref hasWorldProperty, "width", activeWorld.Width);
                AppendNumberProperty(sb, ref hasWorldProperty, "height", activeWorld.Height);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read active world dimensions: " + e);
            }

            if (activeWorld != null)
            {
                try
                {
                    var telepads = Components.Telepads.GetWorldItems(activeWorld.id);
                    for (int i = 0; i < telepads.Count; i++)
                    {
                        var telepadCell = Grid.PosToCell(telepads[i].gameObject);
                        if (!Grid.IsWorldValidCell(telepadCell) ||
                            !Grid.IsValidCellInWorld(telepadCell, activeWorld.id))
                        {
                            continue;
                        }

                        int telepadX;
                        int telepadY;
                        Grid.CellToXY(telepadCell, out telepadX, out telepadY);
                        startX = telepadX;
                        startY = telepadY;
                        hasStartPosition = true;
                        AppendPropertyPrefix(sb, ref hasWorldProperty, "start");
                        sb.Append("{");
                        bool hasStartProperty = false;
                        AppendStringProperty(sb, ref hasStartProperty, "type", "telepad");
                        AppendNumberProperty(sb, ref hasStartProperty, "cell", telepadCell);
                        AppendNumberProperty(sb, ref hasStartProperty, "x", telepadX);
                        AppendNumberProperty(sb, ref hasStartProperty, "y", telepadY);
                        sb.Append("}");
                        break;
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not read active world telepad: " + e);
                }
            }

            if (activeWorld != null && hasStartPosition)
            {
                try
                {
                    AppendMap(sb, ref hasWorldProperty, activeWorld, startX, startY);
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not read active world map: " + e);
                }
            }
            sb.Append("}");

            try
            {
                UpdateBuildingListCache(activeWorld, hasStartPosition, startX, startY);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not update building list cache: " + e);
            }

            try
            {
                UpdateResearchCache();
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not update research cache: " + e);
                cachedResearchJson = null;
            }

            ExportBlueprintIfRequested();
            AppendPropertyPrefix(sb, ref hasRootProperty, "building_list");
            sb.Append(cachedBuildingListJson);

            if (cachedResearchJson != null)
            {
                AppendPropertyPrefix(sb, ref hasRootProperty, "research");
                sb.Append(cachedResearchJson);
            }

            AppendPropertyPrefix(sb, ref hasRootProperty, "buildings");
            sb.Append("{");
            bool hasBuildingProperty = false;
            try
            {
                var buildingCounts = new Dictionary<string, int>(StringComparer.Ordinal);
                var buildings = Components.BuildingCompletes.Items;
                for (int i = 0; i < buildings.Count; i++)
                {
                    try
                    {
                        var prefabId = buildings[i].prefabid.PrefabTag.Name;
                        if (prefabId.StartsWith("Prop", StringComparison.Ordinal) ||
                            prefabId.EndsWith("POI", StringComparison.Ordinal))
                        {
                            continue;
                        }

                        if (buildingCounts.ContainsKey(prefabId))
                        {
                            buildingCounts[prefabId]++;
                        }
                        else
                        {
                            buildingCounts.Add(prefabId, 1);
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read building type: " + e);
                    }
                }

                var buildingIds = new List<string>(buildingCounts.Keys);
                buildingIds.Sort(StringComparer.Ordinal);
                foreach (var buildingId in buildingIds)
                {
                    AppendNumberProperty(sb, ref hasBuildingProperty, buildingId, buildingCounts[buildingId]);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read buildings: " + e);
            }
            sb.Append("}");

            AppendPropertyPrefix(sb, ref hasRootProperty, "dupes");
            sb.Append("[");
            bool hasDupe = false;
            try
            {
                var dupes = Components.LiveMinionIdentities.Items;
                for (int i = 0; i < dupes.Count; i++)
                {
                    if (hasDupe)
                    {
                        sb.Append(",");
                    }
                    hasDupe = true;

                    var dupe = dupes[i];
                    var hasDupeProperty = false;
                    sb.Append("{");

                    try
                    {
                        AppendStringProperty(sb, ref hasDupeProperty, "name", dupe.name);
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe name: " + e);
                    }

                    try
                    {
                        AppendNumberProperty(sb, ref hasDupeProperty, "stress", Db.Get().Amounts.Stress.Lookup(dupe).value);
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe stress: " + e);
                    }

                    try
                    {
                        AppendNumberProperty(sb, ref hasDupeProperty, "calories_kcal",
                            Db.Get().Amounts.Calories.Lookup(dupe).value / 1000f);
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe calories: " + e);
                    }

                    try
                    {
                        var health = dupe.GetComponent<Health>();
                        if (health != null)
                        {
                            AppendNumberProperty(sb, ref hasDupeProperty, "health", health.hitPoints);
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe health: " + e);
                    }

                    try
                    {
                        var choreDriver = dupe.GetComponent<ChoreDriver>();
                        if (choreDriver != null)
                        {
                            var chore = choreDriver.GetCurrentChore();
                            if (chore != null)
                            {
                                AppendStringProperty(sb, ref hasDupeProperty, "chore", chore.GetReportName());
                            }
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe chore: " + e);
                    }

                    try
                    {
                        int cell = Grid.PosToCell(dupe.gameObject);
                        if (!Grid.IsWorldValidCell(cell))
                        {
                            throw new InvalidOperationException("Dupe position is not in a valid world cell.");
                        }

                        int x;
                        int y;
                        Grid.CellToXY(cell, out x, out y);
                        int worldId = Grid.WorldIdx[cell];
                        AppendNumberProperty(sb, ref hasDupeProperty, "cell", cell);
                        AppendNumberProperty(sb, ref hasDupeProperty, "x", x);
                        AppendNumberProperty(sb, ref hasDupeProperty, "y", y);
                        AppendNumberProperty(sb, ref hasDupeProperty, "world_id", worldId);
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read dupe position: " + e);
                    }

                    sb.Append("}");
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read dupe list: " + e);
            }
            sb.Append("]");

            try
            {
                var dupes = Components.LiveMinionIdentities.Items;
                if (dupes.Count > 0)
                {
                    var firstDupeCell = Grid.PosToCell(dupes[0].gameObject);
                    if (Grid.IsWorldValidCell(firstDupeCell))
                    {
                        int centerX;
                        int centerY;
                        Grid.CellToXY(firstDupeCell, out centerX, out centerY);
                        int worldId = Grid.WorldIdx[firstDupeCell];
                        float oxygenMassKg = 0f;
                        int validCellCount = 0;

                        for (int y = centerY - 5; y <= centerY + 5; y++)
                        {
                            for (int x = centerX - 5; x <= centerX + 5; x++)
                            {
                                int cell = Grid.XYToCell(x, y);
                                if (!Grid.IsValidCell(cell) || !Grid.IsValidCellInWorld(cell, worldId))
                                {
                                    continue;
                                }

                                validCellCount++;
                                var element = Grid.Element[cell];
                                if (element.id == SimHashes.Oxygen && element.IsGas)
                                {
                                    oxygenMassKg += Grid.Mass[cell];
                                }
                            }
                        }

                        if (validCellCount > 0)
                        {
                            AppendNumberProperty(sb, ref hasRootProperty, "oxygen_air",
                                oxygenMassKg * 1000f / validCellCount);
                        }
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read oxygen_air around first dupe: " + e);
            }

            AppendPropertyPrefix(sb, ref hasRootProperty, "alerts");
            sb.Append("[");
            bool hasAlert = false;
            try
            {
                var dupes = Components.LiveMinionIdentities.Items;
                for (int i = 0; i < dupes.Count; i++)
                {
                    var dupe = dupes[i];
                    string dupeName = null;
                    try
                    {
                        dupeName = dupe.name;
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not read alert dupe name: " + e);
                    }

                    try
                    {
                        if (Db.Get().Amounts.Calories.Lookup(dupe).value <= 0f)
                        {
                            AppendAlert(sb, ref hasAlert, "dupe_no_calories", dupeName);
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not check dupe calories alert: " + e);
                    }

                    try
                    {
                        if (Db.Get().Amounts.Stress.Lookup(dupe).value >= 90f)
                        {
                            AppendAlert(sb, ref hasAlert, "dupe_high_stress", dupeName);
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not check dupe stress alert: " + e);
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not evaluate alerts: " + e);
            }
            sb.Append("]");
            sb.Append("}");

            try
            {
                if (Time.unscaledTime >= nextWrite)
                {
                    nextWrite = Time.unscaledTime + 2f;
                    try
                    {
                        File.WriteAllText(OutPath, sb.ToString());
                    }
                    catch (Exception e)
                    {
                        Debug.LogError("[OniAgent] Lỗi khi ghi file: " + e);
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogError("[OniAgent] Could not check write interval: " + e);
            }
        }

        private static void PollCommandFile()
        {
            try
            {
                if (Time.unscaledTime < nextCommandRead)
                {
                    return;
                }

                nextCommandRead = Time.unscaledTime + 2f;
                if (!File.Exists(CommandPath))
                {
                    return;
                }

                var command = AgentCommandParser.Parse(File.ReadAllText(CommandPath));
                if (command.Id == lastProcessedCommandId ||
                    (pendingCommand != null && command.Id == pendingCommand.Id))
                {
                    return;
                }

                pendingCommand = command;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read command file: " + e);
            }
        }

        private static void ProcessPendingCommand()
        {
            if (pendingCommand == null)
            {
                return;
            }

            var command = pendingCommand;
            pendingCommand = null;
            if (command.Id == lastProcessedCommandId)
            {
                return;
            }

            var results = new List<AgentActionResult>();
            foreach (var action in command.Actions)
            {
                results.Add(ExecuteAction(action));
            }

            pendingResults.Enqueue(new AgentCommandResult
            {
                Id = command.Id,
                Results = results
            });
            lastProcessedCommandId = command.Id;
        }

        private static void WritePendingResults()
        {
            try
            {
                if (pendingResults.Count == 0 || Time.unscaledTime < nextResultWrite)
                {
                    return;
                }

                nextResultWrite = Time.unscaledTime + 2f;
                var commandResult = pendingResults.Peek();
                var sb = new StringBuilder();
                sb.Append("{");
                bool hasRootProperty = false;
                AppendStringProperty(sb, ref hasRootProperty, "id", commandResult.Id);
                AppendPropertyPrefix(sb, ref hasRootProperty, "results");
                sb.Append("[");

                for (int i = 0; i < commandResult.Results.Count; i++)
                {
                    if (i > 0)
                    {
                        sb.Append(",");
                    }

                    var result = commandResult.Results[i];
                    sb.Append("{");
                    bool hasResultProperty = false;
                    AppendStringProperty(sb, ref hasResultProperty, "type", result.Type);
                    if (!string.IsNullOrEmpty(result.Id))
                    {
                        AppendStringProperty(sb, ref hasResultProperty, "id", result.Id);
                    }
                    if (result.X.HasValue)
                    {
                        AppendNumberProperty(sb, ref hasResultProperty, "x", result.X.Value);
                    }
                    if (result.Y.HasValue)
                    {
                        AppendNumberProperty(sb, ref hasResultProperty, "y", result.Y.Value);
                    }
                    if (!string.IsNullOrEmpty(result.Cancelled))
                    {
                        AppendStringProperty(sb, ref hasResultProperty, "cancelled", result.Cancelled);
                    }
                    AppendPropertyPrefix(sb, ref hasResultProperty, "ok");
                    sb.Append(result.Ok ? "true" : "false");
                    AppendStringProperty(sb, ref hasResultProperty, "reason", result.Reason);
                    sb.Append("}");
                }

                sb.Append("]}");
                Directory.CreateDirectory(Path.GetDirectoryName(ResultsPath));
                File.WriteAllText(ResultsTempPath, sb.ToString(), new UTF8Encoding(false));
                if (File.Exists(ResultsPath))
                {
                    File.Replace(ResultsTempPath, ResultsPath, null);
                }
                else
                {
                    File.Move(ResultsTempPath, ResultsPath);
                }
                pendingResults.Dequeue();
            }
            catch (Exception e)
            {
                Debug.LogError("[OniAgent] Could not write command results: " + e);
            }
            finally
            {
                try
                {
                    if (File.Exists(ResultsTempPath))
                    {
                        File.Delete(ResultsTempPath);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not clean temporary results file: " + e);
                }
            }
        }

        private static AgentActionResult ExecuteAction(AgentAction action)
        {
            var result = new AgentActionResult
            {
                Type = action.Type,
                Id = action.BuildingId,
                X = action.X,
                Y = action.Y
            };

            if (action.Type == "list_buildings")
            {
                string reason;
                result.Ok = TryWriteBuildingCatalog(out reason);
                result.Reason = reason;
                return result;
            }

            if (action.Type == "build")
            {
                return ExecuteBuildAction(action, result);
            }

            if (action.Type == "set_research")
            {
                return ExecuteSetResearchAction(action, result);
            }

            if (action.Type == "cancel")
            {
                return ExecuteCancelAction(action, result);
            }

            if (action.Type != "dig")
            {
                result.Reason = "unsupported";
                return result;
            }
            if (!action.X.HasValue || !action.Y.HasValue)
            {
                result.Reason = "invalid_coordinates";
                return result;
            }

            try
            {
                var world = ClusterManager.Instance.activeWorld;
                if (world == null)
                {
                    result.Reason = "world_unavailable";
                    return result;
                }

                int x = action.X.Value;
                int y = action.Y.Value;
                var offset = world.WorldOffset;
                if (x < offset.x || y < offset.y ||
                    x >= offset.x + world.Width || y >= offset.y + world.Height)
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }

                int cell = Grid.XYToCell(x, y);
                if (!Grid.IsValidCell(cell) || !Grid.IsValidCellInWorld(cell, world.id))
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }
                if (Grid.Objects[cell, 7] != null)
                {
                    result.Reason = "already_marked";
                    return result;
                }
                if (!Grid.IsSolidCell(cell))
                {
                    result.Reason = "not_solid";
                    return result;
                }
                if (Grid.Foundation[cell] || Grid.Element[cell].hardness == byte.MaxValue)
                {
                    result.Reason = "undiggable";
                    return result;
                }
                if (DigTool.Instance == null)
                {
                    result.Reason = "dig_tool_unavailable";
                    return result;
                }
                if (!DigTool.Instance.IsActiveLayer(ToolParameterMenu.FILTERLAYERS.TILES))
                {
                    result.Reason = "dig_tool_tiles_filter_disabled";
                    return result;
                }

                new Klei.Input.MarkCellDigAction().Dig(cell, 0);
                if (Grid.Objects[cell, 7] == null)
                {
                    result.Reason = "undiggable";
                    return result;
                }

                result.Ok = true;
                result.Reason = "ok";
                return result;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not execute dig action: " + e);
                result.Reason = "game_state_error";
                return result;
            }
        }

        private static AgentActionResult ExecuteCancelAction(AgentAction action, AgentActionResult result)
        {
            try
            {
                if (!action.X.HasValue || !action.Y.HasValue)
                {
                    result.Reason = "error";
                    return result;
                }

                var world = ClusterManager.Instance.activeWorld;
                if (world == null)
                {
                    result.Reason = "error";
                    return result;
                }

                int x = action.X.Value;
                int y = action.Y.Value;
                var offset = world.WorldOffset;
                if (x < offset.x || y < offset.y ||
                    x >= offset.x + world.Width || y >= offset.y + world.Height)
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }

                int cell = Grid.XYToCell(x, y);
                if (!Grid.IsValidCell(cell) || !Grid.IsValidCellInWorld(cell, world.id))
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }

                var diggable = Diggable.GetDiggable(cell);
                if (diggable != null)
                {
                    diggable.gameObject.Trigger((int)GameHashes.Cancel);
                    result.Cancelled = "dig";
                    result.Ok = true;
                    result.Reason = "ok";
                    return result;
                }

                for (int layer = 0; layer < 45; layer++)
                {
                    var gameObject = Grid.Objects[cell, layer];
                    if (gameObject == null || gameObject.GetComponent<Constructable>() == null)
                    {
                        continue;
                    }

                    gameObject.Trigger((int)GameHashes.Cancel);
                    result.Cancelled = "build";
                    result.Ok = true;
                    result.Reason = "ok";
                    return result;
                }

                result.Reason = "nothing_to_cancel";
                return result;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not execute cancel action: " + e);
                result.Reason = "error";
                return result;
            }
        }

        private static AgentActionResult ExecuteSetResearchAction(AgentAction action, AgentActionResult result)
        {
            try
            {
                var research = Research.Instance;
                var database = Db.Get();
                if (research == null || database == null)
                {
                    result.Reason = "research_unavailable";
                    return result;
                }

                if (string.IsNullOrEmpty(action.ResearchTechId) || database.Techs.resources == null)
                {
                    result.Reason = "unknown_tech";
                    return result;
                }

                Tech selectedTech = null;
                foreach (var tech in database.Techs.resources)
                {
                    if (tech != null && string.Equals(
                        tech.Id, action.ResearchTechId, StringComparison.OrdinalIgnoreCase))
                    {
                        selectedTech = tech;
                        break;
                    }
                }

                if (selectedTech == null)
                {
                    result.Reason = "unknown_tech";
                    return result;
                }
                if (selectedTech.IsComplete())
                {
                    result.Reason = "already_complete";
                    return result;
                }

                research.SetActiveResearch(selectedTech, true);
                result.Ok = true;
                result.Reason = "ok";
                return result;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not set active research: " + e);
                result.Reason = "research_unavailable";
                return result;
            }
        }

        private static AgentActionResult ExecuteBuildAction(AgentAction action, AgentActionResult result)
        {
            try
            {
                if (string.IsNullOrEmpty(action.BuildingId))
                {
                    result.Reason = "unknown_building";
                    return result;
                }

                var definition = Assets.GetBuildingDef(action.BuildingId);
                if (definition == null)
                {
                    result.Reason = "unknown_building";
                    return result;
                }
                if (!definition.IsAvailable() || !definition.ShouldShowInBuildMenu())
                {
                    result.Reason = "not_buildable";
                    return result;
                }
                if (!Db.Get().TechItems.IsTechItemComplete(action.BuildingId))
                {
                    result.Reason = "not_unlocked";
                    return result;
                }

                if (!action.X.HasValue || !action.Y.HasValue)
                {
                    result.Reason = "invalid_coordinates";
                    return result;
                }

                int priority = action.Priority ?? 5;
                if (priority < 1 || priority > 9)
                {
                    result.Reason = "invalid_priority";
                    return result;
                }

                Orientation orientation;
                if (!TryParseBuildingOrientation(action.Orientation, out orientation))
                {
                    result.Reason = "invalid_orientation";
                    return result;
                }

                var world = ClusterManager.Instance.activeWorld;
                if (world == null)
                {
                    result.Reason = "world_unavailable";
                    return result;
                }

                int x = action.X.Value;
                int y = action.Y.Value;
                var offset = world.WorldOffset;
                if (x < offset.x || y < offset.y ||
                    x >= offset.x + world.Width || y >= offset.y + world.Height)
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }

                int cell = Grid.XYToCell(x, y);
                if (!Grid.IsValidCell(cell) || !Grid.IsValidCellInWorld(cell, world.id))
                {
                    result.Reason = "out_of_bounds";
                    return result;
                }

                var selectedElements = new List<Tag>();
                string[] materialCategories = definition.MaterialCategory ?? Array.Empty<string>();
                if (action.Elements == null)
                {
                    selectedElements = definition.DefaultElements();
                }
                else
                {
                    if (action.Elements.Count != materialCategories.Length)
                    {
                        result.Reason = "bad_element";
                        return result;
                    }

                    for (int categoryIndex = 0; categoryIndex < materialCategories.Length; categoryIndex++)
                    {
                        var validMaterials = MaterialSelector.GetValidMaterials(materialCategories[categoryIndex]);
                        Tag selectedMaterial = default(Tag);
                        bool foundMaterial = false;
                        for (int materialIndex = 0; materialIndex < validMaterials.Count; materialIndex++)
                        {
                            if (string.Equals(validMaterials[materialIndex].Name,
                                action.Elements[categoryIndex], StringComparison.Ordinal))
                            {
                                selectedMaterial = validMaterials[materialIndex];
                                foundMaterial = true;
                                break;
                            }
                        }

                        if (!foundMaterial)
                        {
                            result.Reason = "bad_element";
                            return result;
                        }
                        selectedElements.Add(selectedMaterial);
                    }
                }

                if (selectedElements.Count != materialCategories.Length)
                {
                    result.Reason = "bad_element";
                    return result;
                }

                if (!definition.MaterialsAvailable(selectedElements, world))
                {
                    result.Reason = "insufficient_material";
                    return result;
                }

                string failureReason;
                if (!definition.IsValidBuildLocation(definition.BuildingComplete, cell, orientation, false, out failureReason) ||
                    !definition.IsValidPlaceLocation(definition.BuildingComplete, cell, orientation, false,
                        out failureReason, true))
                {
                    result.Reason = "blocked";
                    return result;
                }

                if (definition.BuildingUnderConstruction == null ||
                    definition.BuildingUnderConstruction.GetComponent<Prioritizable>() == null)
                {
                    result.Reason = "not_buildable";
                    return result;
                }

                var position = Grid.CellToPosCBC(cell, Grid.SceneLayer.Building);
                var placedBuilding = definition.TryPlace(definition.BuildingComplete, position, orientation,
                    selectedElements, "DEFAULT_FACADE", true);
                if (placedBuilding == null)
                {
                    result.Reason = "blocked";
                    return result;
                }

                var prioritizable = placedBuilding.GetComponent<Prioritizable>();
                if (prioritizable == null)
                {
                    Debug.LogWarning("[OniAgent] Placed building has no Prioritizable component.");
                }
                else
                {
                    prioritizable.SetMasterPriority(
                        new PrioritySetting(PriorityScreen.PriorityClass.basic, priority));
                }

                result.Ok = true;
                result.Reason = "ok";
                return result;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not execute build action: " + e);
                result.Reason = "game_state_error";
                return result;
            }
        }

        private static bool TryParseBuildingOrientation(string value, out Orientation orientation)
        {
            switch (value ?? "Neutral")
            {
                case "Neutral":
                    orientation = Orientation.Neutral;
                    return true;
                case "R90":
                    orientation = Orientation.R90;
                    return true;
                case "R180":
                    orientation = Orientation.R180;
                    return true;
                case "R270":
                    orientation = Orientation.R270;
                    return true;
                case "FlipH":
                    orientation = Orientation.FlipH;
                    return true;
                case "FlipV":
                    orientation = Orientation.FlipV;
                    return true;
                default:
                    orientation = Orientation.Neutral;
                    return false;
            }
        }

        private static bool TryWriteBuildingCatalog(out string reason)
        {
            string temporaryPath = CatalogTempPath;
            try
            {
                var definitions = Assets.BuildingDefs;
                if (definitions == null)
                {
                    reason = "building_catalog_unavailable";
                    return false;
                }

                var sortedDefinitions = new List<BuildingDef>(definitions);
                sortedDefinitions.Sort((left, right) =>
                    string.CompareOrdinal(left == null ? null : left.PrefabID,
                        right == null ? null : right.PrefabID));

                var sb = new StringBuilder();
                sb.Append("[");
                bool hasBuilding = false;
                foreach (var definition in sortedDefinitions)
                {
                    try
                    {
                        if (definition == null)
                        {
                            continue;
                        }

                        string prefabId = definition.PrefabID;
                        if (string.IsNullOrEmpty(prefabId) ||
                            prefabId.StartsWith("Prop", StringComparison.Ordinal) ||
                            prefabId.EndsWith("POI", StringComparison.Ordinal) ||
                            prefabId.IndexOf("Gravitas", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            !definition.IsAvailable() ||
                            !definition.ShouldShowInBuildMenu())
                        {
                            continue;
                        }

                        bool unlocked = Db.Get().TechItems.IsTechItemComplete(prefabId);
                        var entryBuilder = new StringBuilder();
                        bool hasProperty = false;
                        entryBuilder.Append("{");
                        AppendStringProperty(entryBuilder, ref hasProperty, "id", prefabId);
                        AppendNumberProperty(entryBuilder, ref hasProperty, "width", definition.WidthInCells);
                        AppendNumberProperty(entryBuilder, ref hasProperty, "height", definition.HeightInCells);
                        AppendPropertyPrefix(entryBuilder, ref hasProperty, "materials");
                        entryBuilder.Append("[");

                        string[] materialCategories = definition.MaterialCategory ?? Array.Empty<string>();
                        for (int categoryIndex = 0; categoryIndex < materialCategories.Length; categoryIndex++)
                        {
                            if (categoryIndex > 0)
                            {
                                entryBuilder.Append(",");
                            }

                            entryBuilder.Append("{");
                            bool hasCategoryProperty = false;
                            AppendStringProperty(entryBuilder, ref hasCategoryProperty, "category",
                                materialCategories[categoryIndex]);
                            AppendPropertyPrefix(entryBuilder, ref hasCategoryProperty, "options");
                            entryBuilder.Append("[");

                            var validMaterials = MaterialSelector.GetValidMaterials(materialCategories[categoryIndex]);
                            for (int materialIndex = 0; materialIndex < validMaterials.Count; materialIndex++)
                            {
                                if (materialIndex > 0)
                                {
                                    entryBuilder.Append(",");
                                }
                                entryBuilder.Append("\"")
                                    .Append(EscapeJsonString(validMaterials[materialIndex].Name)).Append("\"");
                            }

                            entryBuilder.Append("]}");
                        }

                        entryBuilder.Append("]");
                        AppendPropertyPrefix(entryBuilder, ref hasProperty, "unlocked");
                        entryBuilder.Append(unlocked ? "true" : "false");
                        entryBuilder.Append("}");

                        if (hasBuilding)
                        {
                            sb.Append(",");
                        }
                        hasBuilding = true;
                        sb.Append(entryBuilder);
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning("[OniAgent] Could not add building to catalog: " + e);
                    }
                }
                sb.Append("]");

                Directory.CreateDirectory(Path.GetDirectoryName(CatalogPath));
                File.WriteAllText(temporaryPath, sb.ToString(), new UTF8Encoding(false));
                if (File.Exists(CatalogPath))
                {
                    File.Replace(temporaryPath, CatalogPath, null);
                }
                else
                {
                    File.Move(temporaryPath, CatalogPath);
                }

                reason = "catalog_written";
                return true;
            }
            catch (Exception e)
            {
                Debug.LogError("[OniAgent] Could not write building catalog: " + e);
                reason = "catalog_write_failed";
                return false;
            }
            finally
            {
                try
                {
                    if (File.Exists(temporaryPath))
                    {
                        File.Delete(temporaryPath);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not clean temporary catalog file: " + e);
                }
            }
        }

        private static void UpdateBuildingListCache(WorldContainer activeWorld, bool hasTelepad, int telepadX, int telepadY)
        {
            try
            {
                if (activeWorld == null)
                {
                    cachedBuildingListJson = "[]";
                    cachedBuildingWorldId = int.MinValue;
                    nextBuildingListUpdate = Time.unscaledTime + 10f;
                    return;
                }

                if (activeWorld.id == cachedBuildingWorldId && Time.unscaledTime < nextBuildingListUpdate)
                {
                    return;
                }

                nextBuildingListUpdate = Time.unscaledTime + 10f;
                cachedBuildingListJson = BuildBuildingListJson(activeWorld, hasTelepad, telepadX, telepadY);
                cachedBuildingWorldId = activeWorld.id;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not refresh building list: " + e);
                cachedBuildingListJson = "[]";
                cachedBuildingWorldId = activeWorld != null ? activeWorld.id : int.MinValue;
                nextBuildingListUpdate = Time.unscaledTime + 10f;
            }
        }

        private static void UpdateResearchCache()
        {
            if (Time.unscaledTime < nextResearchUpdate)
            {
                return;
            }

            nextResearchUpdate = Time.unscaledTime + 10f;
            try
            {
                var research = Research.Instance;
                var database = Db.Get();
                if (research == null || database == null)
                {
                    Debug.LogWarning("[OniAgent] Research or database is unavailable; omitting research state.");
                    cachedResearchJson = null;
                    return;
                }

                cachedResearchJson = BuildResearchJson(research, database);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not refresh research state: " + e);
                cachedResearchJson = null;
            }
        }

        private static string BuildResearchJson(Research research, Db database)
        {
            var sb = new StringBuilder();
            sb.Append("{");
            bool hasProperty = false;

            try
            {
                var target = research.GetTargetResearch();
                AppendPropertyPrefix(sb, ref hasProperty, "target");
                if (target == null || target.tech == null)
                {
                    sb.Append("null");
                }
                else
                {
                    sb.Append("\"").Append(EscapeJsonString(target.tech.Id)).Append("\"");
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read research target: " + e);
            }

            try
            {
                var active = research.GetActiveResearch();
                AppendPropertyPrefix(sb, ref hasProperty, "active");
                if (active == null || active.tech == null)
                {
                    sb.Append("null");
                }
                else
                {
                    sb.Append("\"").Append(EscapeJsonString(active.tech.Id)).Append("\"");
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read active research: " + e);
            }

            var techs = database.Techs.resources;
            if (techs == null)
            {
                throw new InvalidOperationException("The technology list is unavailable.");
            }

            AppendPropertyPrefix(sb, ref hasProperty, "techs");
            sb.Append("[");
            bool hasTech = false;
            for (int i = 0; i < techs.Count; i++)
            {
                try
                {
                    var tech = techs[i];
                    if (tech == null)
                    {
                        continue;
                    }

                    var techInstance = research.Get(tech);
                    var techBuilder = new StringBuilder();
                    techBuilder.Append("{");
                    bool hasTechProperty = false;
                    AppendStringProperty(techBuilder, ref hasTechProperty, "id", tech.Id);
                    AppendStringProperty(techBuilder, ref hasTechProperty, "name",
                        Regex.Replace(tech.Name, "<[^>]*>", string.Empty));

                    AppendPropertyPrefix(techBuilder, ref hasTechProperty, "complete");
                    techBuilder.Append(tech.IsComplete() ? "true" : "false");

                    AppendPropertyPrefix(techBuilder, ref hasTechProperty, "ready");
                    techBuilder.Append(tech.ArePrerequisitesComplete() ? "true" : "false");

                    AppendPropertyPrefix(techBuilder, ref hasTechProperty, "cost");
                    techBuilder.Append("[");
                    bool hasCost = false;
                    foreach (var cost in tech.costsByResearchTypeID)
                    {
                        float current = 0f;
                        if (techInstance != null)
                        {
                            current = techInstance.progressInventory.PointsByTypeID[cost.Key];
                        }

                        if (hasCost)
                        {
                            techBuilder.Append(",");
                        }
                        hasCost = true;
                        techBuilder.Append("{");
                        bool hasCostProperty = false;
                        AppendStringProperty(techBuilder, ref hasCostProperty, "type", cost.Key);
                        AppendNumberProperty(techBuilder, ref hasCostProperty, "required", cost.Value);
                        AppendNumberProperty(techBuilder, ref hasCostProperty, "current", current);
                        techBuilder.Append("}");
                    }
                    techBuilder.Append("]");

                    AppendPropertyPrefix(techBuilder, ref hasTechProperty, "unlocks");
                    techBuilder.Append("[");
                    bool hasUnlock = false;
                    foreach (var item in tech.unlockedItems)
                    {
                        try
                        {
                            if (item == null || Assets.GetBuildingDef(item.Id) == null)
                            {
                                continue;
                            }

                            if (hasUnlock)
                            {
                                techBuilder.Append(",");
                            }
                            hasUnlock = true;
                            techBuilder.Append("\"").Append(EscapeJsonString(item.Id)).Append("\"");
                        }
                        catch (Exception e)
                        {
                            Debug.LogWarning("[OniAgent] Could not read research unlock for " + tech.Id + ": " + e);
                        }
                    }
                    techBuilder.Append("]");
                    techBuilder.Append("}");

                    if (hasTech)
                    {
                        sb.Append(",");
                    }
                    hasTech = true;
                    sb.Append(techBuilder);
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not read research tech at index " + i + ": " + e);
                }
            }
            sb.Append("]}");
            return sb.ToString();
        }

        private static string BuildBuildingListJson(WorldContainer activeWorld, bool hasTelepad, int telepadX, int telepadY)
        {
            var entries = new List<BuildingListEntry>();
            var seenObjects = new HashSet<GameObject>();
            var completedBuildings = Components.BuildingCompletes.Items;

            for (int i = 0; i < completedBuildings.Count; i++)
            {
                var building = completedBuildings[i];
                try
                {
                    if (building.creationTime < 0f || !seenObjects.Add(building.gameObject))
                    {
                        continue;
                    }

                    var entry = CreateBuildingListEntry(building, "built", activeWorld, hasTelepad, telepadX, telepadY);
                    if (entry != null)
                    {
                        entries.Add(entry);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not add completed building to list: " + e);
                }
            }

            var objectLayers = Grid.ObjectLayers;
            for (int layer = 0; layer < objectLayers.Length; layer++)
            {
                try
                {
                    foreach (var gameObject in objectLayers[layer].Values)
                    {
                        try
                        {
                            if (gameObject == null || !seenObjects.Add(gameObject))
                            {
                                continue;
                            }

                            var building = gameObject.GetComponent<BuildingUnderConstruction>();
                            if (building == null)
                            {
                                continue;
                            }

                            var entry = CreateBuildingListEntry(building, "under_construction",
                                activeWorld, hasTelepad, telepadX, telepadY);
                            if (entry != null)
                            {
                                entries.Add(entry);
                            }
                        }
                        catch (Exception e)
                        {
                            Debug.LogWarning("[OniAgent] Could not add construction to building list: " + e);
                        }
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not read building object layer: " + e);
                }
            }

            entries.Sort((left, right) =>
            {
                int cellOrder = left.Cell.CompareTo(right.Cell);
                return cellOrder != 0 ? cellOrder : string.CompareOrdinal(left.Id, right.Id);
            });

            var sb = new StringBuilder();
            sb.Append("[");
            for (int i = 0; i < entries.Count; i++)
            {
                if (i > 0)
                {
                    sb.Append(",");
                }

                var entry = entries[i];
                sb.Append("{");
                bool hasProperty = false;
                AppendStringProperty(sb, ref hasProperty, "id", entry.Id);
                AppendNumberProperty(sb, ref hasProperty, "x", entry.X);
                AppendNumberProperty(sb, ref hasProperty, "y", entry.Y);
                AppendNumberProperty(sb, ref hasProperty, "cell", entry.Cell);
                AppendStringProperty(sb, ref hasProperty, "orientation", entry.Orientation);
                AppendPropertyPrefix(sb, ref hasProperty, "elements");
                sb.Append("[");
                for (int elementIndex = 0; elementIndex < entry.Elements.Count; elementIndex++)
                {
                    if (elementIndex > 0)
                    {
                        sb.Append(",");
                    }
                    sb.Append("\"").Append(EscapeJsonString(entry.Elements[elementIndex])).Append("\"");
                }
                sb.Append("]");
                AppendStringProperty(sb, ref hasProperty, "state", entry.State);
                if (entry.HasRelativePosition)
                {
                    AppendNumberProperty(sb, ref hasProperty, "rel_x", entry.RelativeX);
                    AppendNumberProperty(sb, ref hasProperty, "rel_y", entry.RelativeY);
                }
                sb.Append("}");
            }
            sb.Append("]");
            return sb.ToString();
        }

        private static BuildingListEntry CreateBuildingListEntry(
            Building building, string state, WorldContainer activeWorld,
            bool hasTelepad, int telepadX, int telepadY)
        {
            try
            {
                var prefabId = building.Def.PrefabID;
                if (string.IsNullOrEmpty(prefabId) ||
                    prefabId.StartsWith("Prop", StringComparison.Ordinal) ||
                    prefabId.EndsWith("POI", StringComparison.Ordinal) ||
                    prefabId.IndexOf("Gravitas", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return null;
                }

                int cell = building.GetBottomLeftCell();
                if (!Grid.IsWorldValidCell(cell) || !Grid.IsValidCellInWorld(cell, activeWorld.id))
                {
                    return null;
                }

                int x;
                int y;
                Grid.CellToXY(cell, out x, out y);
                var entry = new BuildingListEntry
                {
                    Id = prefabId,
                    X = x,
                    Y = y,
                    Cell = cell,
                    Orientation = building.Orientation.ToString(),
                    State = state,
                    Elements = GetBuildingElements(building)
                };
                if (hasTelepad)
                {
                    entry.HasRelativePosition = true;
                    entry.RelativeX = x - telepadX;
                    entry.RelativeY = y - telepadY;
                }
                return entry;
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read building details: " + e);
                return null;
            }
        }

        private static List<string> GetBuildingElements(Building building)
        {
            var elements = new List<string>();
            try
            {
                var constructable = building.GetComponent<Constructable>();
                if (constructable != null && constructable.SelectedElementsTags != null)
                {
                    foreach (var tag in constructable.SelectedElementsTags)
                    {
                        if (tag != null)
                        {
                            elements.Add(tag.Name);
                        }
                    }
                }

                if (elements.Count == 0)
                {
                    var deconstructable = building.GetComponent<Deconstructable>();
                    if (deconstructable != null && deconstructable.constructionElements != null)
                    {
                        foreach (var tag in deconstructable.constructionElements)
                        {
                            if (tag != null)
                            {
                                elements.Add(tag.Name);
                            }
                        }
                    }
                }

                if (elements.Count == 0)
                {
                    var primaryElement = building.GetComponent<PrimaryElement>();
                    if (primaryElement != null && primaryElement.Element != null && primaryElement.Element.tag != null)
                    {
                        elements.Add(primaryElement.Element.tag.Name);
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[OniAgent] Could not read building materials: " + e);
            }
            return elements;
        }

        private static void ExportBlueprintIfRequested()
        {
            string temporaryPath = BlueprintTempPath;
            try
            {
                if (Time.unscaledTime < nextBlueprintExportCheck)
                {
                    return;
                }

                nextBlueprintExportCheck = Time.unscaledTime + 2f;
                if (!File.Exists(ExportFlagPath))
                {
                    return;
                }

                Directory.CreateDirectory(Path.GetDirectoryName(BlueprintPath));
                File.WriteAllText(temporaryPath, cachedBuildingListJson, new UTF8Encoding(false));
                if (File.Exists(BlueprintPath))
                {
                    File.Replace(temporaryPath, BlueprintPath, null);
                }
                else
                {
                    File.Move(temporaryPath, BlueprintPath);
                }

                File.Delete(ExportFlagPath);
            }
            catch (Exception e)
            {
                Debug.LogError("[OniAgent] Could not export building blueprint: " + e);
            }
            finally
            {
                try
                {
                    if (File.Exists(temporaryPath))
                    {
                        File.Delete(temporaryPath);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[OniAgent] Could not clean temporary blueprint file: " + e);
                }
            }
        }

        private static void AppendNumberProperty(StringBuilder sb, ref bool hasProperty, string name, float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
            {
                throw new ArgumentOutOfRangeException(nameof(value), "JSON numbers must be finite.");
            }

            AppendPropertyPrefix(sb, ref hasProperty, name);
            sb.Append(value.ToString("0.##", CultureInfo.InvariantCulture));
        }

        private static void AppendMap(StringBuilder sb, ref bool hasWorldProperty, WorldContainer world, int centerX, int centerY)
        {
            const int radius = 20;
            int originX = centerX - radius;
            int originY = centerY - radius;

            AppendPropertyPrefix(sb, ref hasWorldProperty, "origin");
            sb.Append("{");
            bool hasOriginProperty = false;
            AppendNumberProperty(sb, ref hasOriginProperty, "x", originX);
            AppendNumberProperty(sb, ref hasOriginProperty, "y", originY);
            sb.Append("}");

            AppendPropertyPrefix(sb, ref hasWorldProperty, "map");
            sb.Append("[");
            for (int row = 0; row < 41; row++)
            {
                if (row > 0)
                {
                    sb.Append(",");
                }

                int y = originY + (40 - row);
                var mapRow = new StringBuilder(41);
                for (int column = 0; column < 41; column++)
                {
                    int x = originX + column;
                    mapRow.Append(GetMapCell(world, x, y));
                }
                sb.Append("\"").Append(mapRow).Append("\"");
            }
            sb.Append("]");
        }

        private static char GetMapCell(WorldContainer world, int x, int y)
        {
            var offset = world.WorldOffset;
            if (x < offset.x || y < offset.y ||
                x >= offset.x + world.Width || y >= offset.y + world.Height)
            {
                return '.';
            }

            int cell = Grid.XYToCell(x, y);
            if (!Grid.IsValidCell(cell) || !Grid.IsValidCellInWorld(cell, world.id))
            {
                return '.';
            }
            if (Grid.Foundation[cell] ||
                Grid.Objects[cell, (int)ObjectLayer.Building] != null ||
                Grid.Objects[cell, (int)ObjectLayer.FoundationTile] != null)
            {
                return 'F';
            }

            var element = Grid.Element[cell];
            if (element.IsVacuum)
            {
                return 'V';
            }
            if (element.IsGas)
            {
                return 'G';
            }
            if (element.IsLiquid)
            {
                return 'L';
            }
            if (element.IsSolid)
            {
                if (element.hardness == byte.MaxValue)
                {
                    return 'X';
                }
                return Grid.IsSolidCell(cell) ? '#' : '.';
            }

            return '.';
        }

        private static void AppendNumberProperty(StringBuilder sb, ref bool hasProperty, string name, int value)
        {
            AppendPropertyPrefix(sb, ref hasProperty, name);
            sb.Append(value.ToString(CultureInfo.InvariantCulture));
        }

        private static void AppendStringProperty(StringBuilder sb, ref bool hasProperty, string name, string value)
        {
            AppendPropertyPrefix(sb, ref hasProperty, name);
            sb.Append("\"").Append(EscapeJsonString(value)).Append("\"");
        }

        private static void AppendAlert(StringBuilder sb, ref bool hasAlert, string type, string dupeName)
        {
            if (hasAlert)
            {
                sb.Append(",");
            }
            hasAlert = true;

            sb.Append("{");
            bool hasAlertProperty = false;
            AppendStringProperty(sb, ref hasAlertProperty, "type", type);
            if (dupeName != null)
            {
                AppendStringProperty(sb, ref hasAlertProperty, "name", dupeName);
            }
            sb.Append("}");
        }

        private static void AppendPropertyPrefix(StringBuilder sb, ref bool hasProperty, string name)
        {
            if (hasProperty)
            {
                sb.Append(",");
            }

            hasProperty = true;
            sb.Append("\"").Append(EscapeJsonString(name)).Append("\":");
        }

        private static string EscapeJsonString(string value)
        {
            if (value == null)
            {
                return string.Empty;
            }

            var escaped = new StringBuilder(value.Length);
            foreach (char character in value)
            {
                switch (character)
                {
                    case '"':
                        escaped.Append("\\\"");
                        break;
                    case '\\':
                        escaped.Append("\\\\");
                        break;
                    case '\b':
                        escaped.Append("\\b");
                        break;
                    case '\f':
                        escaped.Append("\\f");
                        break;
                    case '\n':
                        escaped.Append("\\n");
                        break;
                    case '\r':
                        escaped.Append("\\r");
                        break;
                    case '\t':
                        escaped.Append("\\t");
                        break;
                    default:
                        if (character < 0x20)
                        {
                            escaped.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            escaped.Append(character);
                        }
                        break;
                }
            }

            return escaped.ToString();
        }
    }

    internal sealed class AgentCommand
    {
        public string Id;
        public List<AgentAction> Actions;
    }

    internal sealed class BuildingListEntry
    {
        public string Id;
        public int X;
        public int Y;
        public int Cell;
        public string Orientation;
        public List<string> Elements;
        public string State;
        public bool HasRelativePosition;
        public int RelativeX;
        public int RelativeY;
    }

    internal sealed class AgentAction
    {
        public string Type;
        public string BuildingId;
        public string ResearchTechId;
        public int? X;
        public int? Y;
        public string Orientation;
        public List<string> Elements;
        public int? Priority;
    }

    internal sealed class AgentCommandResult
    {
        public string Id;
        public List<AgentActionResult> Results;
    }

    internal sealed class AgentActionResult
    {
        public string Type;
        public string Id;
        public int? X;
        public int? Y;
        public string Cancelled;
        public bool Ok;
        public string Reason;
    }

    internal sealed class AgentCommandParser
    {
        public static AgentCommand Parse(string json)
        {
            var root = JsonValueReader.Parse(json) as Dictionary<string, object>;
            if (root == null ||
                !root.TryGetValue("id", out var idValue) ||
                !(idValue is string id) ||
                string.IsNullOrEmpty(id) ||
                !root.TryGetValue("actions", out var actionsValue) ||
                !(actionsValue is List<object> actionValues))
            {
                throw new FormatException("Command must contain a string id and an actions array.");
            }

            var actions = new List<AgentAction>();
            foreach (var actionValue in actionValues)
            {
                var actionObject = actionValue as Dictionary<string, object>;
                if (actionObject == null ||
                    !actionObject.TryGetValue("type", out var typeValue) ||
                    !(typeValue is string type))
                {
                    throw new FormatException("Each action must contain a string type.");
                }

                var action = new AgentAction { Type = type };
                if (actionObject.TryGetValue("id", out var buildingIdValue))
                {
                    if (!(buildingIdValue is string buildingId))
                    {
                        throw new FormatException("Action building id must be a string.");
                    }
                    action.BuildingId = buildingId;
                }
                if (actionObject.TryGetValue("tech", out var researchTechIdValue))
                {
                    if (!(researchTechIdValue is string researchTechId))
                    {
                        throw new FormatException("Action research tech id must be a string.");
                    }
                    action.ResearchTechId = researchTechId;
                }
                if (actionObject.TryGetValue("x", out var xValue))
                {
                    action.X = ReadInteger(xValue, "x");
                }
                if (actionObject.TryGetValue("y", out var yValue))
                {
                    action.Y = ReadInteger(yValue, "y");
                }
                if (actionObject.TryGetValue("orientation", out var orientationValue))
                {
                    if (!(orientationValue is string orientation))
                    {
                        throw new FormatException("Action orientation must be a string.");
                    }
                    action.Orientation = orientation;
                }
                if (actionObject.TryGetValue("elements", out var elementsValue))
                {
                    if (!(elementsValue is List<object> elementValues))
                    {
                        throw new FormatException("Action elements must be an array of strings.");
                    }

                    action.Elements = new List<string>(elementValues.Count);
                    foreach (var elementValue in elementValues)
                    {
                        if (!(elementValue is string element))
                        {
                            throw new FormatException("Each action element must be a string.");
                        }
                        action.Elements.Add(element);
                    }
                }
                if (actionObject.TryGetValue("priority", out var priorityValue))
                {
                    action.Priority = ReadInteger(priorityValue, "priority");
                }
                actions.Add(action);
            }

            return new AgentCommand { Id = id, Actions = actions };
        }

        private static int ReadInteger(object value, string name)
        {
            if (!(value is double number) ||
                number < int.MinValue ||
                number > int.MaxValue ||
                number != Math.Truncate(number))
            {
                throw new FormatException("Action coordinate '" + name + "' must be a 32-bit integer.");
            }

            return (int)number;
        }
    }

    internal sealed class JsonValueReader
    {
        private readonly string json;
        private int position;

        private JsonValueReader(string json)
        {
            this.json = json ?? throw new ArgumentNullException(nameof(json));
        }

        public static object Parse(string json)
        {
            var reader = new JsonValueReader(json);
            var value = reader.ReadValue();
            reader.SkipWhitespace();
            if (reader.position != reader.json.Length)
            {
                throw new FormatException("Unexpected content after JSON value.");
            }
            return value;
        }

        private object ReadValue()
        {
            SkipWhitespace();
            if (position >= json.Length)
            {
                throw new FormatException("Unexpected end of JSON.");
            }

            switch (json[position])
            {
                case '{':
                    return ReadObject();
                case '[':
                    return ReadArray();
                case '"':
                    return ReadString();
                case 't':
                    ReadLiteral("true");
                    return true;
                case 'f':
                    ReadLiteral("false");
                    return false;
                case 'n':
                    ReadLiteral("null");
                    return null;
                default:
                    if (json[position] == '-' || IsDigit(json[position]))
                    {
                        return ReadNumber();
                    }
                    throw new FormatException("Unexpected JSON token.");
            }
        }

        private Dictionary<string, object> ReadObject()
        {
            position++;
            SkipWhitespace();
            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            if (TryConsume('}'))
            {
                return result;
            }

            while (true)
            {
                SkipWhitespace();
                if (position >= json.Length || json[position] != '"')
                {
                    throw new FormatException("Expected an object property name.");
                }

                var name = ReadString();
                SkipWhitespace();
                Require(':');
                result.Add(name, ReadValue());
                SkipWhitespace();
                if (TryConsume('}'))
                {
                    return result;
                }
                Require(',');
            }
        }

        private List<object> ReadArray()
        {
            position++;
            SkipWhitespace();
            var result = new List<object>();
            if (TryConsume(']'))
            {
                return result;
            }

            while (true)
            {
                result.Add(ReadValue());
                SkipWhitespace();
                if (TryConsume(']'))
                {
                    return result;
                }
                Require(',');
            }
        }

        private string ReadString()
        {
            Require('"');
            var result = new StringBuilder();
            while (position < json.Length)
            {
                char character = json[position++];
                if (character == '"')
                {
                    return result.ToString();
                }
                if (character < 0x20)
                {
                    throw new FormatException("Unescaped control character in JSON string.");
                }
                if (character != '\\')
                {
                    result.Append(character);
                    continue;
                }
                if (position >= json.Length)
                {
                    throw new FormatException("Incomplete JSON escape sequence.");
                }

                switch (json[position++])
                {
                    case '"': result.Append('"'); break;
                    case '\\': result.Append('\\'); break;
                    case '/': result.Append('/'); break;
                    case 'b': result.Append('\b'); break;
                    case 'f': result.Append('\f'); break;
                    case 'n': result.Append('\n'); break;
                    case 'r': result.Append('\r'); break;
                    case 't': result.Append('\t'); break;
                    case 'u': result.Append(ReadUnicodeEscape()); break;
                    default: throw new FormatException("Invalid JSON escape sequence.");
                }
            }

            throw new FormatException("Unterminated JSON string.");
        }

        private char ReadUnicodeEscape()
        {
            if (position + 4 > json.Length)
            {
                throw new FormatException("Incomplete Unicode escape sequence.");
            }

            int value = 0;
            for (int i = 0; i < 4; i++)
            {
                char digit = json[position++];
                int hex;
                if (digit >= '0' && digit <= '9')
                {
                    hex = digit - '0';
                }
                else if (digit >= 'a' && digit <= 'f')
                {
                    hex = digit - 'a' + 10;
                }
                else if (digit >= 'A' && digit <= 'F')
                {
                    hex = digit - 'A' + 10;
                }
                else
                {
                    throw new FormatException("Invalid hexadecimal digit in Unicode escape.");
                }
                value = value * 16 + hex;
            }
            return (char)value;
        }

        private double ReadNumber()
        {
            int start = position;
            TryConsume('-');
            if (TryConsume('0'))
            {
                if (position < json.Length && IsDigit(json[position]))
                {
                    throw new FormatException("Leading zero in JSON number.");
                }
            }
            else
            {
                ReadDigits();
            }

            if (TryConsume('.'))
            {
                ReadDigits();
            }
            if (TryConsume('e') || TryConsume('E'))
            {
                if (!TryConsume('+'))
                {
                    TryConsume('-');
                }
                ReadDigits();
            }

            if (!double.TryParse(json.Substring(start, position - start),
                    NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ||
                double.IsNaN(value) ||
                double.IsInfinity(value))
            {
                throw new FormatException("Invalid JSON number.");
            }
            return value;
        }

        private void ReadDigits()
        {
            int start = position;
            while (position < json.Length && IsDigit(json[position]))
            {
                position++;
            }
            if (position == start)
            {
                throw new FormatException("Expected a digit in JSON number.");
            }
        }

        private void ReadLiteral(string literal)
        {
            if (position + literal.Length > json.Length ||
                string.CompareOrdinal(json, position, literal, 0, literal.Length) != 0)
            {
                throw new FormatException("Invalid JSON literal.");
            }
            position += literal.Length;
        }

        private void SkipWhitespace()
        {
            while (position < json.Length &&
                   (json[position] == ' ' || json[position] == '\t' ||
                    json[position] == '\r' || json[position] == '\n'))
            {
                position++;
            }
        }

        private void Require(char expected)
        {
            if (!TryConsume(expected))
            {
                throw new FormatException("Expected '" + expected + "'.");
            }
        }

        private bool TryConsume(char expected)
        {
            if (position < json.Length && json[position] == expected)
            {
                position++;
                return true;
            }
            return false;
        }

        private static bool IsDigit(char value)
        {
            return value >= '0' && value <= '9';
        }
    }
}