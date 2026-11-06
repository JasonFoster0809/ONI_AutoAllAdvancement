# Báo cáo overnight — giai đoạn 1-11

## Tóm tắt trạng thái

| Giai đoạn | Trạng thái | Kết quả |
|---|---|---|
| 1. Cancel API/action | XONG | API được xác minh bằng ILSpy; build thành công sau khi sửa lỗi ép kiểu ban đầu. |
| 2. `set_priority` | XONG | API priority được xác minh; build thành công. |
| 3. State mở rộng | XONG | Achievements, môi trường, điện và các alert đơn giản; build thành công. |
| 4. Tài liệu nền | XONG | Orientation/pivot và playbook được ghi; build thành công. |
| 5. Báo cáo giữa chặng | XONG | Đã tạo báo cáo ban đầu; được cập nhật hoàn chỉnh ở giai đoạn 11. |
| 6. Schedule | XONG | API schedule được xác minh; state cache và action được thêm; build thành công. |
| 7. Ưu tiên theo dupe | XONG | API `ChoreConsumer` được xác minh; state/action được thêm; build thành công. |
| 8. Thư viện Python | XONG | Client, map, catalog và skill planners; kiểm tra cú pháp thành công; build thành công. |
| 9. Rules và LLM | XONG | Luật deterministic, Ollama local bị giới hạn vào candidate ID, CLI và JSONL log; build thành công. |
| 10. Kiểm thử offline | XONG | `python -m pytest -q`: **23 passed** ở lần xác minh cuối; `dotnet build` thành công. |
| 11. Tài liệu cuối | XONG | Architecture, roadmap, playbook và báo cáo được cập nhật. |

Không có mục API/build nào bị bỏ vì ba lần thất bại. Build `cancel` đầu tiên
báo `CS1503` do `GameHashes.Cancel` là enum trong khi `Trigger` nhận `int`;
đã sửa theo chữ ký đã xác minh và build tiếp theo thành công. Các lỗi ở lượt
pytest đầu tiên là lỗi giả định trong test và một default argument giữ
`LOG_PATH` cũ; đã sửa, toàn bộ 22 test sau đó đều qua. Rà soát cuối phát
hiện thứ tự luật khẩn cấp chạy sau planner; đã chuyển lên trước planner và
thêm test hồi quy, đưa tổng số test lên 23.

## Hành động C# và JSON để kiểm tra thủ công

Các ví dụ dùng envelope `id` và `actions` của `oni_commands.json`. Thay tên
dupe/schedule bằng giá trị có trong game hiện tại.

### Hủy đào hoặc xây

```json
{"id":"cancel-001","actions":[{"type":"cancel","x":12,"y":34}]}
```

Reason: `ok`, `nothing_to_cancel`, `out_of_bounds`, hoặc `error`. Khi thành
công có thêm `cancelled: "dig"` hoặc `cancelled: "build"`.

### Đổi priority công trình/việc theo ô

```json
{"id":"priority-001","actions":[{"type":"set_priority","x":12,"y":34,"priority":8}]}
```

Priority hợp lệ: 1-9. Reason: `ok`, `nothing_found`, `invalid_priority`, hoặc
`out_of_bounds`.

### Đổi schedule

Schedule được chọn theo tên và thay đổi ảnh hưởng mọi duplicant đang dùng
schedule đó. Phải gửi đúng 24 group ID hợp lệ:

```json
{"id":"schedule-001","actions":[{"type":"schedule","schedule":"Default","blocks":["Hygene","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Worktime","Recreation","Recreation","Sleep","Sleep","Sleep"]}]}
```

Reason: `ok`, `invalid_blocks`, `unavailable`, hoặc `error`.

### Ưu tiên công việc của một duplicant

```json
{"id":"dupe-priority-001","actions":[{"type":"set_dupe_priority","dupe":"Ada","group":"Dig","priority":4}]}
```

Priority hợp lệ: 0-5. Reason: `ok`, `unknown_dupe`, `unknown_group`,
`invalid_priority`, `unavailable`, hoặc `error`.

Các action C# trước đó (`dig`, `build`, `set_research`, `list_buildings`)
giữ nguyên; cú pháp và chi tiết API của chúng nằm trong `README_API.md`.
Không có action game mới nào được thêm trong giai đoạn Python 8-11.

## State và agent Python

- State C# có thêm `achievements`, `environment`, `power`, `schedule`, và
  `dupes[].job_priorities`; các khối cũ gồm `world.map`, `building_list`,
  `research`, `resources`, `alerts` và danh sách duplicant tiếp tục được
  giữ.
- `agent.oni_client`: kiểm tra `oni_state.json` cũ hơn 10 giây, gửi command
  có ID duy nhất và chờ kết quả đúng ID.
- `agent.maputils`: chuyển tọa độ map 41x41, phân loại cell và tìm footprint
  trống theo pivot.
- `agent.catalog`: đọc `oni_catalog.json`; chỉ chọn vật liệu từ
  `resources.materials`, so khớp không phân biệt hoa thường nhưng trả tên
  đúng casing trong state. Thiếu kho trả `material_inventory_unavailable`;
  nếu không option nào có lượng dương hợp lệ thì trả `insufficient_material`.
  Catalog không chỉ rõ số kg cần cho mỗi building, nên số dương chỉ chứng
  minh có tồn kho, không đảm bảo đủ toàn bộ chi phí công trình.
- `agent.skills`: `build_bedroom`, `build_research_area`, `dig_corridor`,
  `build_ladder_shaft`; các hàm chỉ trả action, không gửi. Bedroom hiện lập
  kế hoạch bed + door, không dựng tường/không đảm bảo game ghi nhận room.
- `agent.rules`: threshold 50 g/cell cho oxygen, 100 kcal cho đói, stress 90,
  và nhiệt độ 273.15-318.15 K là **heuristic của agent**, không phải ngưỡng
  nguy hiểm đã xác minh trong game. Luật được chạy trước khi tạo skill plan;
  hiện chưa cấu hình hành động sửa chữa khẩn cấp nên nguy cơ sẽ trả no-op và
  chặn LLM.
- `agent.llm_chooser`: chỉ gửi candidate cho Ollama local
  `http://localhost:11434/api/generate`, model `qwen2.5-coder:3b`,
  temperature 0; ID không hợp lệ, JSON lỗi hoặc timeout đều fallback no-op.
- `agent.agent_main`: hỗ trợ `--dry-run`, `--max-steps`, `--goals`,
  `--config`, `--data-dir` và log JSON Lines trong `logs/`.

Ví dụ chạy offline/dry-run một bước:

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --data-dir <thu-muc-co-oni_state-va-oni_catalog>
```

Ví dụ bật từng mục tiêu (ID công trình được cấu hình trong
`agent/config.json`, không qua command-line):

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --goals research_target
python -m agent.agent_main --dry-run --max-steps 1 --goals barracks
python -m agent.agent_main --dry-run --max-steps 1 --goals research_target,barracks
```

`python -m pytest -q` đã chạy offline và cho kết quả `23 passed` tại giai đoạn
11; lượt kiểm thử cập nhật sau đây có kết quả mới. Ollama được
mock trong test; chưa gọi Ollama thật.

## API game đã xác minh

Các API ONI dùng trong giai đoạn C# đã được decompile từ
`Assembly-CSharp.dll`/`Assembly-CSharp-firstpass.dll` với `ilspycmd 8.2`;
chi tiết class, member, tệp code và cách kiểm tra nằm trong
`README_API.md`, gồm `GameHashes.Cancel`, `Grid.Objects`,
`Prioritizable`, `ScheduleManager`, `Schedule`, `ChoreConsumer`,
`ChoreGroup`, các API môi trường/điện và các API state đã ghi trước đó.
Giai đoạn 8-11 không thêm hoặc đoán API game mới.

Các phần không được thêm do thiếu API/state đã xác minh hoặc vì an toàn:

- Không xuất tổng than hoặc tổng năng lượng từ `WorldInventory`; không xác
  minh được tag than phù hợp. Điện hiện tại chỉ là snapshot circuit/battery.
- C# alert không suy đoán ngưỡng đói: chỉ báo calories bằng 0; ngưỡng 100
  kcal của Python là heuristic riêng.
- Tại giai đoạn 11, state chưa xuất `resources.materials`; field này được thêm
  trong phần bổ sung bên dưới.
- Rule khẩn cấp không tự suy diễn một hành động sửa chữa nếu không có
  candidate được cấu hình.

## File đã sửa/thêm

- C#: `Mod.cs`
- API/tài liệu: `README_API.md`, `playbook.md`, `OVERNIGHT_REPORT.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`
- Python package: `agent/__init__.py`, `agent/oni_client.py`,
  `agent/maputils.py`, `agent/catalog.py`, `agent/skills.py`,
  `agent/rules.py`, `agent/llm_chooser.py`, `agent/agent_main.py`
- Offline tests: `tests/fixtures/*.json`, `tests/test_*.py`
- Ignore rules: `.gitignore`
- `agent.py` và `agent_rule.py` cũ không được sửa.

## Commit đã tạo (không push)

- `802d681` — baseline
- `210325b` — Add cancel action
- `a82b920` — Add set priority action
- `a6712b8` — Expand colony state snapshot
- `0b3f902` — Document ONI playbook and build coordinates
- `355ecbd` — Report completed overnight stages 1-5
- `d3368a4` — Add schedule state and action
- `fb4540f` — Add per-dupe job priorities
- `1560f03` — Add offline ONI agent library
- `84403b5` — Add rule-based local action agent
- `f34a707` — Add offline Python test coverage
- `3736e01` — Document agent architecture and roadmap
- `46d31b7` — Prioritize emergency rules before planning
- `ddaae16` — Expose cached material inventory in state (Phần 1)
- `e13fb6e` — Select build materials from inventory state (Phần 2)

**Tất cả code C# mới CHƯA được test thật trong game.** Python chỉ được test
offline bằng fixture/mocks; chưa xác thực trao đổi file với game thật hoặc
Ollama thật. Không copy DLL vào thư mục game, không chạy deploy và không
khởi động ONI.

## Bổ sung: kho vật liệu cho chọn vật liệu xây

### Phần 1 — C# state `resources.materials`

**XONG — `dotnet build` thành công.** Thêm cache vật liệu theo active world,
làm mới khoảng 10 giây; mỗi lần refresh duyệt `ElementLoader.elements`, gọi
`WorldInventory.GetAmount(element.tag, false)`, bỏ lượng không dương và làm
tròn tới 1 chữ số thập phân. Khi refresh lỗi, chỉ bỏ `resources.materials`;
các trường resource khác vẫn được giữ. Không thay đổi action game nào.

Ví dụ cấu trúc state:

```json
{
  "resources": {
    "materials": {
      "SandStone": 1234.5,
      "Dirt": 250.0
    }
  }
}
```

Trong lần build đầu có lỗi `CS1503` vì helper JSON nhận `float` nhưng giá trị
làm tròn ban đầu là `double`; đã đổi sang `float` sau khi làm tròn. Build kế
tiếp thành công với 0 warning, 0 error.

### Phần 2 — Python `catalog.choose_materials`

**XONG — `python -m pytest -q`: 29 passed; `dotnet build`: thành công, 0
warning, 0 error.** Hàm chọn option của từng category chỉ khi tag tồn kho có
lượng dương và hữu hạn; so khớp tên không phân biệt hoa thường nhưng action
giữ đúng casing của key trong state. Thiếu `resources.materials` trả
`material_inventory_unavailable`; kho có nhưng không có option hợp lệ trả
`insufficient_material`. Các skill build chuyển lựa chọn vào `elements` của
action. Đã thêm `tests/fixtures/material_inventory.json` cùng các test đủ
vật liệu, thiếu vật liệu, không có kho, casing, và action build.

Do schema catalog chỉ liệt kê category và options, không khai báo kg yêu cầu,
không tự đặt lượng tối thiểu cho từng công trình. Lượng dương là mức duy nhất
có thể xác nhận từ state hiện tại; game vẫn là nguồn cuối cùng để xác định
có đủ chi phí xây thực tế hay không.

Ví dụ action để kiểm tra thủ công (thay prefab ID bằng ID trong catalog):

```json
{"id":"material-build-001","actions":[{"type":"build","id":"<catalog-prefab-id>","x":20,"y":10,"orientation":"Neutral","elements":["SandStone"],"priority":5}]}
```

Hai phần đã được commit riêng; không push.

## Bổ sung: Construction mass API

### Phần 1 — Xác minh API

**XONG — API xác minh được bằng `ilspycmd 8.2`; `dotnet build` sau bước tài
liệu thành công.** `BuildingDef.MaterialCategory` và `BuildingDef.Mass` là
các mảng song song theo index: `BuildingDef.PostProcess()` tạo từng
`Recipe.Ingredient` bằng `MaterialCategory[i]` và `(int)Mass[i]`.
`BuildingDef.MaterialsAvailable()` gọi `CraftRecipe.GetAllIngredients()`,
thay tag đã chọn ở đúng index rồi so `ingredient.amount` với
`WorldInventory.GetAmount`. `Recipe.Ingredient.amount` là lượng construction
mass; cơ chế inventory đi qua `Pickupable.TotalAmount` và
`PrimaryElement.Units`, còn `PrimaryElement.Mass = Units * MassPerUnit`.
`GameUtil` có cấu hình hiển thị Kilograms/Pounds; catalog sẽ gọi trường
`mass_kg` theo khối lượng construction chuẩn trong game. Chi tiết xác minh và
cảnh báo active-world vs related-world được ghi trong `README_API.md`.

### Phần 2 — Trường `mass_kg` và chọn kho theo chi phí

**XONG — `python -m pytest -q`: 28 passed; `dotnet build`: thành công, 0
warning, 0 error.** Action `list_buildings` thêm `mass_kg` theo index từ
`(int)BuildingDef.Mass[i]`; nếu không có phần tử/giá trị hợp lệ, chỉ bỏ field
khỏi category đó. Mỗi category độc lập được bảo vệ bằng `try/catch`.
`choose_materials` chỉ chọn option có stock lớn hơn hoặc bằng `mass_kg`.
Catalog cũ thiếu field sẽ log warning và dùng lại cách cũ (stock dương).
Kho thiếu số lượng cần thiết trả `insufficient_material`; state không có
`resources.materials` vẫn trả `material_inventory_unavailable`.

Đã thêm fixture `catalog_with_masses.json`,
`catalog_without_masses.json`, và test cho đủ/thiếu lượng, fallback catalog
cũ, đồng thời xác nhận build skill gửi phần tử vào `elements`. Kết quả kiểm
thử cuối: `python -m pytest -q` — **29 passed**; `dotnet build` — **Build
succeeded, 0 Warning(s), 0 Error(s)**.

Kiểm tra lại ngày 2026-11-05: `python -m pytest -q` — **53 passed in 0.52s**;
`dotnet build` — **Build succeeded, 0 Warning(s), 0 Error(s)**. C# mới
**CHƯA test thật trong game**.

Cú pháp `list_buildings` hiện có:

```json
{"id":"catalog-mass-001","actions":[{"type":"list_buildings"}]}
```

Sau khi catalog chứa `mass_kg`, build action có thể gửi vật liệu đáp ứng
chi phí:

```json
{"id":"mass-build-001","actions":[{"type":"build","id":"<catalog-prefab-id>","x":20,"y":10,"orientation":"Neutral","elements":["SandStone"],"priority":5}]}
```

Kết quả C# mới **CHƯA được test thật trong game**. Không deploy, không copy
DLL và không chạy ONI. Phần 1 và Phần 2 được commit riêng; không push.

- `75c18f8` — Document construction mass API (Phần 1)
- `24ccb3f` — Include construction mass in building catalog (Phần 2)

## Bổ sung: Goal planner (các giai đoạn 1-4)

### Giai đoạn 1 — Planner và pending build

**XONG — `python -m pytest -q`: 38 passed; `dotnet build`: thành công, 0
warning, 0 error.** `agent.planner` có dataclass `Goal`, registry mở rộng qua
`register_goal`, hai mục tiêu mặc định theo thứ tự `research_target` rồi
`barracks`, và `next_step` chọn tối đa một mục tiêu. Research chọn tech ready,
chưa complete, ưu tiên `priority_techs` (mặc định `FarmingTech`). Mục tiêu
barracks lập kế hoạch sàn cần thiết, bed và door; prefab ID được lấy từ
`agent/config.json`, không hardcode.

Mục tiêu đã hoàn tất, pending hoặc lỗi khi kiểm tra/kế hoạch sẽ được ghi vào
`skipped`. Các build đã được mod chấp nhận được theo dõi tới khi hiện trong
`building_list` ở trạng thái `built` hoặc `under_construction`; khi hết
`pending_steps` (mặc định 30) thì pending hết hạn và được log. Planner bỏ
qua build trùng với công trình cùng ID/vị trí đã có trong state. Nếu không
còn kế hoạch phù hợp trả `goal_id: "no_goal"`.

Giới hạn tại thời điểm triển khai planner ban đầu: C# chưa xuất `rooms` và
skill chỉ đặt bed/door. Hai điểm này đã được cập nhật trong phần
"Bổ sung phòng Barracks" bên dưới; các hành vi Barracks mới vẫn chỉ được
kiểm thử offline.

### Giai đoạn 2 — Vòng lặp và lựa chọn mục tiêu

**XONG — `python -m pytest -q`: 38 passed; `dotnet build`: thành công, 0
warning, 0 error.** Mỗi vòng chạy emergency rules trước planner. Nếu có
candidate mục tiêu cùng thứ hạng cao nhất, chỉ khi đó mới gọi Ollama chooser;
chooser bị giới hạn vào ID candidate và có lựa chọn `no_op`. Nếu không có
đồng hạng, planner chọn theo thứ hạng xác định. Mỗi vòng gửi nhiều nhất một
lệnh.

`--goals` nhận danh sách phân cách bằng dấu phẩy; mặc định bật mọi mục tiêu
đã đăng ký. `--dry-run` không gửi lệnh; `--max-steps 0` chạy liên tục. Log
JSON Lines bổ sung `goal_id`, `skipped`, `selection_reason`, `pending` và
`pending_expired`. Cấu hình trong `agent/config.json`: `priority_techs`,
`pending_steps`, `bed_id`, `door_id`, `tile_id` và `goal_ranks`. Các prefab
ID mặc định là `null`; `goal_ranks` mặc định rỗng nên thứ tự chuẩn là
research trước barracks. Gán cùng rank cho hai mục tiêu để bật phân xử LLM.

Ví dụ chạy thử (thư mục dữ liệu phải có `oni_state.json` và
`oni_catalog.json`):

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --goals research_target,barracks --data-dir <data-dir> --config agent/config.json
```

### Giai đoạn 3 — Kiểm thử offline

**XONG — `python -m pytest -q`: 38 passed.** Thêm các fixture cho research
ready, barracks đã/chưa xây, pending build, catalog và thiếu vật liệu; test
thứ tự mục tiêu, mục tiêu đã xong/pending/lỗi, chống gửi build trùng,
`no_goal`, emergency-first và LLM chỉ được gọi khi có nhiều mục tiêu cùng
rank. LLM được mock; không gọi Ollama thật.

### Giai đoạn 4 — Tài liệu

**XONG.** Cập nhật `ARCHITECTURE.md`, `ROADMAP.md`, báo cáo này và mặc định
`goal_ranks` trong `agent/config.json`/`agent_main.py`. Roadmap ghi rõ việc
còn chờ kiểm thử game, cấu hình prefab ID thật, state `rooms`, hành động
khẩn cấp và xác nhận Ollama local.

### Commit goal planner (không push)

- `349419b` — Add ordered colony goal planner
- `76fbaca` — Connect planner to goal agent loop
- `1a7b2d9` — Test goal planning and pending behavior offline
- Giai đoạn 4 gồm tài liệu, báo cáo và mặc định `goal_ranks`, được commit
  cùng thay đổi này.

Toàn bộ planner và code C# **CHƯA test thật trong game**; kiểm thử planner
chỉ offline. Không chạy game/deploy, không copy DLL, không push.

## Bổ sung: Tính năng phòng Barracks

### Giai đoạn 1 — Xác minh Room API

**XONG — API xác minh bằng `ilspycmd 8.2`; `dotnet build` thành công, 0
warning, 0 error.** `Game.roomProber`, `RoomProber.rooms`, `Room.roomType`,
`Room.cavity`, `CavityInfo.NumCells`, `CavityInfo.cells`, `Grid.CellToXY`,
`RoomType.isSatisfactory`, `Database.RoomTypes.Barracks` và các
`RoomConstraints` được decompile từ Assembly-CSharp (Resource.Id/Name đối
chiếu Assembly-CSharp-firstpass). Barracks trong code cần ít nhất một
building có tag BedType (không phải Clinic), cấm IndustrialMachinery, và
`cavity.NumCells` từ 12 đến 64 inclusive. Game tìm cavity bằng flood fill;
solid/foundation cells và door cells là biên. Đã ghi source details, ví dụ
JSON và chi phí O(R + C) mỗi lần cập nhật trong `README_API.md` (R là số
phòng, C là tổng số cavity cells phải duyệt).

### Giai đoạn 2 — State C#

**XONG — `dotnet build` thành công, 0 warning, 0 error.** State thêm `rooms`
với `{type, size, x, y}`; cache theo world ID khoảng 10 giây như
`building_list`. `x,y` được chọn theo y nhỏ nhất rồi x nhỏ nhất từ các cell
thực của cavity; lỗi refresh bỏ toàn bộ khối rooms, entry riêng lẻ không
hợp lệ được log và bỏ qua. Mọi đọc chạy trong hook `Game.Update` trên main
thread. Chưa chạy game.

Ví dụ state:

```json
{"rooms":[{"type":"Barracks","size":12,"x":4,"y":7}]}
```

### Giai đoạn 3 — Planner Python

**XONG — `python -m pytest -q`: 46 passed; `dotnet build`: thành công, 0
warning, 0 error.** Skill cũ chỉ đặt Bed/Door được giữ dưới tên
`build_bedroom`. `build_barracks` mới dùng dimensions từ catalog, tìm vùng
trống gần telepad, tạo perimeter Tile ở sàn/trần/hai tường, chừa opening cho
Door và đặt số Bed cấu hình được. Kích thước trong nhà được giữ ở chiều cao
Bed và ít nhất 12 ô, không vượt 64. Tile đang có được tái sử dụng chỉ khi
`building_list` xác nhận đúng prefab Tile; công trình khác làm candidate đó
không hợp lệ. Build action dùng orientation `"Neutral"`, pivot theo quy ước
2 ô trái/3 ô giữa, và y là hàng dưới.

Trước khi trả action, planner cộng `mass_kg` theo nhóm vật liệu cho Bed, Door
và số Tile mới, rồi gọi `catalog.choose_materials` với chi phí tổng hợp.
Thiếu kho trả `material_inventory_unavailable`; thiếu lượng trả
`insufficient_material` kèm required/available/missing kg. Thiếu `mass_kg`
hoặc Door không vừa chiều cao Bed thì dừng với lý do riêng, không đoán.
`planner.barracks_done` dùng `rooms[].type == "Barracks"`; không có block
rooms thì trạng thái chưa xác định.

Đã thêm fixtures/test cho vùng trống, không gian không hợp lệ, thiếu vật
liệu, Tile đã có, công trình khác chiếm tường, planner tích hợp và
`build_bedroom` cũ. CLI hỗ trợ `--barracks-bed-count` và `--tile-id`; Bed và
Door prefab IDs tiếp tục lấy từ `agent/config.json`.

Ví dụ dry-run (cấu hình `bed_id`/`door_id` trong config và dùng data dir có
state/catalog):

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --goals barracks --barracks-bed-count 4 --tile-id <tile-prefab-id> --config agent/config.json --data-dir <data-dir>
```

### Giai đoạn 4 — Tài liệu

**XONG.** Cập nhật `playbook.md`, `ARCHITECTURE.md`, `ROADMAP.md` và báo cáo
này. Thông tin Bed/industrial machinery/12-64/Morale/Stamina trong tooltip
được ghi rõ nguồn tooltip trong game do người dùng cung cấp; ba điều kiện
đầu đối chiếu với code. Thời điểm cấp Morale lúc dupe thức dậy được ghi là
thông tin cộng đồng, cần kiểm chứng; điều kiện Mess Hall/Great Hall cũng
được đánh dấu cần kiểm chứng.

## Bổ sung: lọc và ổn định `rooms`

### Xác minh API

**XONG — `ilspycmd 8.2`.** Decompile `Room` xác nhận `Room.cavity` là
`CavityInfo`; `CavityInfo.cells` là `List<int>` và `NumCells` là số cell.
`RoomProber.RefreshModule.Visitor.VisitCell` thêm từng cell được flood-fill
vào danh sách cavity. `Grid.CellToXY` đổi từng cell index thành tọa độ.
Vì vậy kiểm tra membership dùng chính xác `cavity.cells`, không dùng bounding
box `minX/maxX/minY/maxY` có thể bao gồm cell không thuộc cavity.
`Database.RoomTypes.GetRoomType` trả `Neutral` nếu không có loại phòng nào
thỏa mãn; vì thế phòng vượt giới hạn kích thước có thể có type Neutral.

### Thay đổi C#

**XONG — `dotnet build`: thành công, 0 warning, 0 error.** Tập cell công
trình được tạo từ cùng entries đã serialize ra `building_list` (completed và
under-construction, cùng prefab filters). Phòng không-Neutral luôn được giữ.
Phòng Neutral chỉ được đưa vào state nếu một `cavity.cells` trùng chính xác
với cell của một building-list entry. Do đó Neutral tự nhiên/rỗng được bỏ,
còn phòng Neutral chứa công trình người chơi—including phòng vượt size
constraint—được giữ lại. Schema vẫn giữ `{type, size, x, y}`.

Đại diện cố định là cell hợp lệ có y nhỏ nhất, sau đó x nhỏ nhất; không phụ
thuộc thứ tự `CavityInfo.cells`. Chi phí refresh mỗi ~10 giây là O(R + C):
R phòng và C tổng số cavity cells cần duyệt cho membership/toạ độ; tra cứu
building cell dùng `HashSet<int>`. Đây là ước lượng thao tác, chưa profile
trên game. Dữ liệu save mẫu người dùng báo 951 phòng/345 KB là động lực lọc;
không có save thật được đọc hoặc kiểm thử trong lần sửa này.

### Kiểm thử/tài liệu

**XONG — `python -m pytest -q`: 46 passed; `dotnet build`: thành công, 0
warning, 0 error.** Schema không đổi, nên planner và fixture Python chỉ được
cập nhật để dùng ví dụ đủ `{type, size, x, y}`; không cần đổi logic Python.
`README_API.md` ghi cách membership, sort tọa độ, fallback Neutral và độ
phức tạp. `playbook.md` ghi chú phòng vượt constraint có thể về Neutral và
cần kiểm chứng điều này với các loại phòng khác.

Không có phần nào bị bỏ qua. Code C# mới **CHƯA test thật trong game**;
không copy DLL, không chạy deploy/game, không push.

### Commit cho lần chỉnh sửa `rooms` (không push)

- `77dc67b` — Filter and stabilize room state output (lọc cell và tọa độ)
- `647ee6c` — Cover room state coordinates in planner fixture

### Tổng kết và commits

| Giai đoạn | Trạng thái | Kiểm chứng |
|---|---|---|
| 1. Room API | XONG | ILSpy; build pass |
| 2. State `rooms` | XONG | build pass |
| 3. Barracks planner | XONG | 46 pytest pass; build pass |
| 4. Tài liệu | XONG | review tài liệu; build pass |

Không có phần nào bị bỏ qua hoặc dừng sau ba lần lỗi. Hai lỗi assertion trong
lượt test tập trung ban đầu (tọa độ Door kỳ vọng và thiếu sàn fixture cho
`build_bedroom`) được sửa; lượt test cuối cùng đều qua.

Commits riêng theo giai đoạn, không push:

- `3764bfc` — Document verified ONI room APIs
- `01bdfc5` — Expose cached room state in ONI snapshot
- `fbc3f52` — Plan complete Barracks room builds offline
- Giai đoạn 4: commit tài liệu Barracks riêng.

**Code C# mới CHƯA test thật trong game.** Planner chỉ được kiểm thử offline;
Room classification, build validity thực tế, hiệu ứng Morale/Stamina và
trao đổi file trong game vẫn cần kiểm chứng thủ công. Không chạy game hoặc
deploy, không copy DLL và không push.

## Bổ sung: retry đọc kết quả và ngưỡng oxy liên tiếp

### Việc 1 — Đọc `oni_results.json` khi bị khóa

**XONG — `python -m pytest -q`: 48 passed.** Nguyên nhân là mod có thể khóa
file kết quả trong lúc ghi. `send_command` thử đọc lại khi gặp
`PermissionError`, `FileNotFoundError` hoặc JSON chưa hoàn chỉnh, trong giới
hạn timeout hiện có. Lệnh chỉ được ghi một lần trước vòng chờ; lỗi đọc kết
quả không khiến agent gửi lại lệnh. Test xác nhận file khóa tạm rồi khả dụng,
và file khóa tới timeout, với một lần ghi lệnh duy nhất.

Commit riêng, không push:

- `c89d017` — Retry transient result file read failures

### Việc 2 — Oxy thấp cần nhiều lần đọc liên tiếp

**XONG — `python -m pytest -q`: 53 passed.** Tín hiệu chính là
`environment.oxygen_avg_g`; khi trường này vắng hoặc không hợp lệ mới dùng
`oxygen_air`. Mặc định dưới 50 g phải xuất hiện trong 3 lần đọc state liên
tiếp trước khi luật oxy kích hoạt. `oxygen_min_g` và
`oxygen_consecutive_readings` có mặc định tương ứng trong code và cấu hình
agent. Thiếu dữ liệu hoặc một lần đọc không thấp sẽ ngắt chuỗi. Alert từ mod
vẫn kích hoạt ngay, không chờ đủ chuỗi oxy. Test bao gồm dao động, tụt kéo
dài, fallback và alert tức thời.

Ví dụ cấu hình:

```json
{"oxygen_min_g":50.0,"oxygen_consecutive_readings":3}
```

Ví dụ state dùng để kiểm tra tín hiệu môi trường:

```json
{"environment":{"oxygen_avg_g":45.0},"oxygen_air":280.0,"alerts":[]}
```

Ví dụ fallback khi thiếu `environment.oxygen_avg_g`:

```json
{"oxygen_air":45.0,"alerts":[]}
```

`playbook.md` ghi rõ 50 g là ngưỡng chính sách agent, chưa phải ngưỡng nguy
hiểm đã được xác minh của game. `ROADMAP.md` ghi nhận người dùng báo rằng
Barracks do agent lập kế hoạch đã được xây và game công nhận từ cycle 3 sang
4; đây là báo cáo người dùng, không phải kiểm chứng mới trong lần chạy này.

Kết quả cuối: `python -m pytest -q` — **53 passed**. Chỉ chạy kiểm thử
offline bằng fixture/mocks; không chạy game, deploy hoặc build C#.

## Bổ sung: trạng thái vận hành công trình

| Giai đoạn | Trạng thái | Kết quả |
|---|---|---|
| 1. Xác minh API | XONG | `Operational.IsOperational`, `IEnergyConsumer.IsPowered`, `Storage.items`, `PrimaryElement.Mass`, và cấu hình Mineral Deoxidizer được decompile từ Assembly-CSharp. |
| 2. State C# | XONG | Chỉ thêm trường tùy chọn cho công trình built; mỗi trường có `try/catch` và log riêng; dùng k-cache `building_list` ~10 giây hiện có. |
| 3. Python tương thích | XONG | 3 fixture mới cho hoạt động, mất điện và state cũ; `read_state` đọc cả ba dạng. |
| 4. Tài liệu | XONG | README_API.md, playbook.md và ROADMAP.md được cập nhật. |

**Xác minh code game:** `Operational.IsOperational` phản ánh điều kiện
operational tổng hợp, `IsActive` là trạng thái khác nên không dùng thay cho
field `operational`. Công trình có `RequiresPowerInput` sẽ được xuất
`powered` khi `IEnergyConsumer` đọc được. Mineral Deoxidizer yêu cầu điện,
tiêu thụ Algae và cấu hình 120 W, 0.55 kg/s Algae, 0.5 kg/s Oxygen; các
rate này là thông số cấu hình trong code, chưa xác minh throughput thật
trong game.

**BỎ QUA:** không diễn giải `Storage.GetAmountAvailable(Tag)` trực tiếp là
kg; API trả tổng `PrimaryElement.Units`, và tương đương kg của Units không
được xác minh cho Algae. Trường `stored.Algae` dùng tổng
`PrimaryElement.Mass` của các Algae trong `Storage.items` thay thế. Không
thêm `IsActive`; nó không đồng nghĩa với `IsOperational`. Không triển khai
stored cho các loại công trình khác ngoài Mineral Deoxidizer vì chưa xác
minh nhu cầu/loại vật liệu của chúng.

Kiểm thử cuối: `python -m pytest -q` — **54 passed in 0.37s**;
`dotnet build` — **Build succeeded, 0 Warning(s), 0 Error(s)**.

Cú pháp PowerShell để xem trạng thái hiện tại (state được cập nhật qua luồng
thường, không cần action mới):

```powershell
Get-Content "$env:USERPROFILE\Documents\Klei\OxygenNotIncluded\oni_state.json" -Raw |
  ConvertFrom-Json |
  Select-Object -ExpandProperty building_list |
  Where-Object { $_.id -eq "MineralDeoxidizer" } |
  Select-Object id, state, operational, powered, stored
```

Commit riêng từng giai đoạn, không push:

- `9a20293` — xác minh API và README
- `058f005` — C# telemetry và README
- `c5b4cf6` — fixture và pytest
- giai đoạn 4: commit tài liệu riêng

C# mới **CHƯA test thật trong game**. Không deploy, không copy DLL, không
chạy ONI; các action đã test thật không bị sửa. Chưa có lỗi build/pytest nào
lặp ba lần.

## Bổ sung: hành động sửa khẩn cấp Python

| Bước | Trạng thái | Kết quả |
|---|---|---|
| 0. Kiểm kê state/catalog | XONG | Đã đọc state/catalog cục bộ và ghi dữ liệu hiện có, công trình unlocked, cùng giới hạn vào `playbook.md`. |
| 1. Kế hoạch hành động | XONG | Python tạo hành động oxy/thức ăn/stress, cảnh báo-only cho nhiệt; giới hạn 12 action/lượt, cooldown 1 cycle, pending tối đa 2 cycle. |
| 2. Fixtures/pytest/dry-run | XONG | **67 passed**; dry-run một bước trên state thật không phát lệnh. |

### Chính sách an toàn đã chọn

- Thức ăn thấp là tổng `resources.food_kcal` dưới 1,000 kcal nhân số dupes
  (ước tính nhu cầu một cycle); priority `Farming`, `Cook`, `Ranching` đặt
  về 4. Đây là ngưỡng lập kế hoạch, không phải ngưỡng nguy hiểm ONI.
- Stress đặt `Dig`/`Build` của từng dupe stress cao về 2. Số Bed, Outhouse
  và WashBasin được so với tổng live dupes; mục tiêu an toàn là tối thiểu
  một công trình mỗi loại mỗi dupe. Đếm cả `under_construction`; không suy
  đoán phân công/công suất tiện ích.
- Oxy: chỉ xây đúng catalog ID `MineralDeoxidizer` nếu chưa có built hoặc
  under-construction, ID unlocked, vật liệu đủ theo `mass_kg`, và có ô nền
  hợp lệ trong connected map area của dupe. Nếu công trình đã có, `stored`
  Algae bằng 0 cho cảnh báo `thiếu_algae`; trường storage vắng/không đọc
  được cho `thiếu_dữ_liệu_algae`, không giả định kho trống và không xây
  trùng. Local state trên đĩa hiện có hai deoxidizer nhưng chưa có các field
  `operational`/`powered`/`stored`.
- Ưu tiên chỉ được gửi nếu nhóm đó tồn tại trong `job_priorities` của state.
  Build bị bỏ qua khi thiếu `mass_kg`, vật liệu, tọa độ/phòng suy ra được,
  hoặc ô hợp lệ; không gửi build action dự đoán sẽ trả `insufficient_material`.
- Nhiệt độ ngoài band chỉ ghi cảnh báo; không đặt công trình nhiệt.
- Pending chỉ giữ các action được mod trả `ok`; build/priority được đối chiếu
  với state kế tiếp. Pending hết hạn sau 2 cycle; cooldown là 1 cycle. Với
  state cũ thiếu room/storage/job fields, lựa chọn an toàn là bỏ qua action
  phụ thuộc trường đó và ghi `skipped`.
- Không sửa action C# đã test thật. Chỉ thêm khóa mới vào `agent/config.json`:
  `emergency_food_kcal_per_dupe`, `emergency_max_actions_per_turn`,
  `emergency_cooldown_cycles`, `emergency_pending_cycles`.

### Fixtures và xác minh

Fixtures `emergency_oxygen_state.json`, `emergency_oxygen_existing.json`,
`emergency_food_state.json`, `emergency_stress_state.json`,
`emergency_temperature_state.json`, và `emergency_catalog.json` kiểm tra:
vật liệu đủ/thiếu, catalog locked, deoxidizer có kho trống/kho chưa biết,
priority changes, amenities thiếu/đủ, map placement, cảnh báo nhiệt, action
limit, cooldown, pending và không gửi lệnh trùng.

`python -m pytest -q` — **67 passed in 0.44s**.

Lệnh dry-run một bước trên state/catalog thật:

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --data-dir "$env:USERPROFILE\Documents\Klei\OxygenNotIncluded"
```

Kết quả thực tế: state cycle 4, 4 dupes, food 19,358.32 kcal; snapshot file
cũ **10,513.1 giây** nên kết quả không phải quan sát colony hiện thời.
Không có emergency nào kích hoạt; planner ghi:

```json
{"goal_id":"no_goal","actions":[],"skipped":[{"goal_id":"research_target","reason":"already_done"},{"goal_id":"barracks","reason":"already_done"}],"result":{"reason":"no_goal"}}
```

Không gửi command trong dry-run. Không sửa C# vì chỉ thiếu trạng thái
per-building trong snapshot cũ; Python bỏ qua an toàn khi dữ liệu đó không
có. Thiếu dữ liệu còn lại: vị trí/ranh giới room gắn với từng dupe không có
field riêng (dùng connected cells của map làm ước lượng); xu hướng tiêu thụ
và readiness recipe thức ăn; phân công/công suất Bed/Outhouse/WashBasin;
nhiệt độ từng dupe/thành phần; tình trạng kho Algae trong state snapshot cũ.

Commits riêng theo bước, không push:

- `4ccb89c` — kiểm kê state/catalog và ghi playbook
- `afefb28` — hành động khẩn cấp Python
- bước 2: commit fixtures, pytest và báo cáo này

Không chạy game, deploy hoặc copy DLL. Không có lỗi giống nhau lặp ba lần.

## Bổ sung: trạng thái kho máy, phòng dupe và giường được gán

| Bước | Trạng thái | Kết quả |
|---|---|---|
| 1. Xác minh API | XONG | Xác minh bằng `ilspycmd 8.2` trên `Assembly-CSharp.dll`: `Storage.items`, `PrimaryElement.Element.tag.Name`, `PrimaryElement.Mass`; `Game.roomProber.GetRoomOfGameObject`, `Room.roomType.Id`, `Room.cavity.cells`; `StateMachineController.GetSMI<SleepChoreMonitor.Instance>()` và `SleepChoreMonitor.bed.Get(smi)`. |
| 2. State kho máy | XONG | Mọi công trình built có `Storage` đọc được thêm `stored: [{element, kg}]`; lỗi ở một item bỏ trường `stored` của riêng công trình đó. `operational`/`powered` tiếp tục giữ cách xuất cũ. |
| 3. State phòng/giường dupe | XONG | Thêm tùy chọn `room_type`, `room_x`, `room_y`, `bed_id`, `bed_x`, `bed_y`; `bed_id` là cell index của GameObject giường được gán. Phòng dùng cell hợp lệ thấp nhất theo y rồi x làm tọa độ đại diện. |
| 4. Tiêu thụ thức ăn theo chu kỳ | BỎ QUA | `RationTracker.GetAmountConsumed()` cộng `amountsConsumedByID`; `WorldResourceAmountTracker.OnNewDay` chỉ chuyển `currentFrame` sang `previousFrame`, không reset tổng này. Vì vậy không xuất `resources.food_consumption_kcal_per_cycle`; để **CHƯA XÁC MINH** thay vì suy diễn từ tổng tích lũy. |
| 5. Kiểm tra | XONG | `dotnet build .\OniAgent.csproj`: Build succeeded, 0 Warning(s), 0 Error(s). `python -m pytest -q`: 67 passed. |

Kho và trạng thái phòng/giường được đọc trong `Game.Update` trên main
thread. Chúng dùng chung nhịp cache `building_list` khoảng 10 giây; không
thêm tần suất lấy mẫu. Python đọc Algae tương thích cả `stored` list mới và
mapping cũ. Chọn quét các built building thực sự có `Storage` thay vì phỏng
đoán danh sách prefab máy; `stored` vắng mặt nếu không có Storage hoặc dữ
liệu kho không đọc đầy đủ.

Cú pháp PowerShell để xem dữ liệu mới:

```powershell
$state = Get-Content "$env:USERPROFILE\Documents\Klei\OxygenNotIncluded\oni_state.json" -Raw | ConvertFrom-Json
$state.dupes | Select-Object name, room_type, room_x, room_y, bed_id, bed_x, bed_y
$state.building_list | Where-Object { $_.state -eq "built" } | Select-Object id, operational, powered, stored
```

Commits riêng theo bước, không push:

- `27eeee1` — xác minh API và cập nhật README
- `e59dda3` — xuất kho theo element, giữ tương thích Python với state cũ
- `825c392` — thêm trạng thái phòng và giường được gán
- bước cuối — báo cáo kết quả

C# mới **CHƯA test thật trong game**. Không chạy game, deploy hoặc copy
DLL; không push. Không có lỗi cùng loại lặp ba lần.

## Overnight run — rule engine, skills, events, and goal managers

Thời gian của code step theo timestamp commit; hàng tài liệu ghi thời điểm
hoàn tất cập nhật, múi giờ `+07:00`. Mỗi code step được commit riêng trên
`overnight-1`; không push. Các bước Python không cần
`dotnet build`; sau bước C# đã chạy build. Xác minh cuối cùng sau toàn bộ
thay đổi: `python -m pytest -q` — **105 passed**; `dotnet build
OniAgent.csproj --no-restore` — **Build succeeded, 0 Warning(s), 0
Error(s)**.

| Thời gian | Trạng thái | Việc và kết quả kiểm thử | Commit |
|---|---|---|---|
| 2026-11-05 23:46:42 | XONG | Tạo rule engine có `--validate`, `--explain`, điều kiện unknown-aware, ưu tiên, pending/cooldown và giới hạn 12 action/lượt; phase metadata 0–10/10–30/30–100 được kiểm tra và báo cáo nhưng không lọc goal planner. Pytest cuối: **105 passed**; C# không đổi. | `1c9cfbb` |
| 2026-11-05 23:47:51 | XONG | Bổ sung ignore cho `.env`, file key và save; xác minh bằng `git check-ignore`. Pytest cuối: **105 passed**; C# không đổi. | `46f0ba1` |
| 2026-11-05 23:49:07 | XONG | Dùng `room_type`, tọa độ giường và `building_list[].stored` trong luật; state cũ/thiếu dữ liệu giữ trạng thái unknown. Pytest cuối: **105 passed**; C# không đổi. | `5cd8e9b` |
| 2026-11-05 23:54:06 | XONG | Thêm skill xây oxy, Latrine, khu ăn và nguồn điện theo catalog, unlock và kho; plan thiếu vật liệu thì không gửi build. Pytest cuối: **105 passed**; C# không đổi. | `aedebc5` |
| 2026-11-05 23:57:04 | XONG | Thêm event journal: xây xong, dupe chết, stress vượt ngưỡng, chore đổi; hook đã kiểm bằng `ilspycmd`, xử lý game/file trên `Game.Update`, xoay file khi quá 5 MiB. Build: **0 warnings, 0 errors**; pytest cuối: **105 passed**. C# mới **CHƯA TEST TRONG GAME**. | `15c3f81` |
| 2026-11-06 00:00:32 | XONG | Thêm Gemini JSON-schema manager và `--mock`; dùng `GEMINI_API_KEY`, không log key; quota miễn phí **TODO_VERIFY**. Pytest cuối: **105 passed**; C# không đổi. | `e7ddadb` |
| 2026-11-06 00:08:21 | XONG | Nối `--manager {none,qwen,gemini}`; emergency chạy trước manager, giữ Qwen mặc định và `--dry-run`. Pytest cuối: **105 passed**; C# không đổi. | `ec7dc6a` |
| 2026-11-06 00:15:04 | XONG | Đồng bộ README/API, architecture, roadmap và playbook; thêm kết quả xác minh Latrine, caveat throughput và kiểm tra cuối. Pytest: **105 passed**; build: **0 warnings, 0 errors**; `git diff --check` sạch. | `104a2c7` |

### Quyết định an toàn và phần bỏ qua

- Không thêm hằng số Algae tiêu thụ vào luật. Dùng `stored` trong state;
  khi thiếu dữ liệu kho thì không suy ra máy rỗng. Mức cấu hình `0.55 kg/s`
  và số đo thực tế người dùng báo `0.08–0.22 kg/s` còn mâu thuẫn,
  throughput thực tế **TODO_VERIFY**.
- Oxygen: nếu đã có MineralDeoxidizer mà kho không có Algae thì chỉ cảnh báo;
  không bịa lệnh giao Algae. Food dùng hành vi ưu tiên hiện có, không xây
  công trình thức ăn khi thiếu công trình đã unlock. Stress hạ ưu tiên
  Dig/Build và lập plan bổ sung Bed/Outhouse/WashBasin; nhiệt chỉ cảnh báo.
- `build_toilet_room` chia footprint thành các batch nhỏ. Code game xác nhận
  Latrine cần ToiletType, WashStation, không có industrial machinery và
  12–64 ô; Outhouse cần 200 kg Dirt để refill, WashBasin yêu cầu Water.
  Việc phòng thực sự được công nhận và việc giao vật liệu cần kiểm tra trong
  game.
- Không đọc được mức tiêu thụ thức ăn theo cycle một cách đáng tin cậy nên
  không thêm `food_consumption_kcal_per_cycle`. Gemini free-tier quota cũng
  để **TODO_VERIFY**.
- State thật có tại thời điểm dry-run nhưng đã cũ **1805.3 giây** (ngưỡng
  cho phép 10 giây), vì vậy kết quả chỉ là kiểm tra cú pháp luồng dry-run,
  không phải khuyến nghị điều khiển colony hiện tại. Kế hoạch đã in:
  cycle `5`, `3` dupes, oxygen average `721.8`, food `22125.5 kcal`,
  mục tiêu `research_target`, chọn bởi `planner`, action `set_research`,
  không có action bị skip. Luật oxy báo unknown trên snapshot này.

### Lệnh xác minh và ranh giới

```powershell
python -m pytest -q
dotnet build OniAgent.csproj --no-restore
git diff --check
```

Dry-run được gọi với `--dry-run --max-steps 1 --manager none` trên
`oni_state.json` và `oni_catalog.json` thật; log được chuyển vào thư mục tạm
để không ghi đè hay thêm log vào repo. Chưa chạy game hoặc deployment, không
copy DLL, không sửa save, không push. C# mới **CHƯA TEST TRONG GAME**; các
kiểm thử game cần người dùng làm trong colony thử nghiệm: xác nhận event
hook/order và rotation, nhận diện Latrine, giao Dirt/Water, power circuit,
Algae throughput, và hành vi action/build thực tế. Không có cùng một lỗi lặp
lại ba lần.

## PHẦN 2

Thời gian theo timestamp commit, múi giờ `+07:00`. Mỗi mục kỹ thuật có
commit riêng trên `overnight-1`; không push. Các bước Python chỉ chạy
pytest; C# mới được build, không chạy trong game.

| Thời gian | Trạng thái | Việc | Pytest | dotnet build | Commit |
|---|---|---|---|---|---|
| 2026-11-06 00:59:32 | XONG | Thêm `agent/diagnostics.py`: báo cáo Markdown về stress/oxy trends, Algae đã biết, build blocked lặp và research kẹt; thêm telemetry tối thiểu cho log mới. Log cũ thiếu trường thì báo unknown. Báo cáo không khẳng định nguyên nhân chết. | 15 passed (diagnostics + agent main) | Không áp dụng (Python-only) | `48513c5` |
| 2026-11-06 01:01:12 | XONG | Thêm `tests/sim_state.py` và 5 dry-run end-to-end: oxygen giảm liên tục, oxygen phục hồi, máy hết Algae, stress cao, thiếu telemetry. Không gửi command thật. | 5 passed | Không áp dụng (Python-only) | `5344140` |
| 2026-11-06 01:04:49 | XONG | Thêm water (LiquidPumpingStation + WashBasin), food (PlanterBox), recreation (MassageTable), storage (StorageLocker); kiểm tra catalog/unlock/mass/inventory/map; tests map giả. PlanterBox không bảo đảm có seed/thu hoạch; vị trí pump gần liquid là heuristic. | 26 passed (`test_skills.py`) | Không áp dụng (Python-only) | `540ad6f` |
| 2026-11-06 01:05:38 | XONG | Thêm growth rules cycle 10–29 cho water/food, midgame 30–99 cho recreation/storage; `--validate` và phase/skill tests. Không thêm ngưỡng tiêu thụ chưa có bằng chứng. | 22 passed (`test_rule_engine.py`) | Không áp dụng (Python-only) | `e591c05` |
| 2026-11-06 01:07:29 | XONG | Thêm `agent/replay.py`; rule log có state/history/pending/cooldown được chạy lại và so sánh action. Log cũ thiếu context được ghi unavailable; catalog có thể đã đổi. | 15 passed (replay + agent main) | Không áp dụng (Python-only) | `54ae792` |
| 2026-11-06 01:08:18 | XONG | Thêm `agent/metrics.py` và `agent_main --report`, ghi `logs/metrics.json`: cycle mới nhất quan sát được, command ok/blocked, average seconds/cycle nếu đo được, dupe count mới nhất. | 15 passed (metrics + agent main) | Không áp dụng (Python-only) | `7a04d99` |
| 2026-11-06 01:10:43 | XONG | Xác minh `Operational.Flags`, `Flag.Name`/`FlagType` bằng `ilspycmd`; thêm tùy chọn `operational_flags:[{name,satisfied}]` vào building đã xây, trên main thread, với catch riêng. Chỉ build, không chạy game. | Full suite sau đó: 125 passed | Build succeeded, 0 warnings, 0 errors sau khi sửa lỗi cú pháp ban đầu | `6e87e4e` |
| 2026-11-06 01:12:42 | XONG | Cleanup check và đồng bộ README/API, architecture, roadmap, playbook. `.gitignore` chặn `.env`, `.env.*`, `*key*`, `*.sav`; `git diff --check` sạch. Full test/build đã chạy trên commit `6e87e4e`. | 125 passed | Build succeeded, 0 warnings, 0 errors | `0cb26ee` |
| 2026-11-06 01:14:43 | XONG | Bước 9: thêm tests cho file state/rules thiếu hoặc JSON lỗi, response command thiếu `results`, dữ liệu nested/count không đầy đủ; `count`/`stored_mass` trả `unknown` khi metadata building cần thiết bị thiếu. Refactor nhỏ để log và chẩn đoán dùng chung `state_metrics`. Lượt pytest đầu có 2 test fail do thiếu import trong test và semantics count; đã sửa, không lặp cùng lỗi 3 lần. | 47 passed (nhắm mục tiêu); full `python -m pytest -q`: 129 passed | Không áp dụng (Python-only); build gần nhất: succeeded, 0 warnings, 0 errors | `412d06c` |

Yêu cầu tiếp tục tới mục 12 không thể thực hiện: danh sách được cung cấp chỉ có
mục 1–9 và không mô tả mục 12. Không tự tạo việc ngoài phạm vi.

### Xác minh ID và quyết định bảo thủ

- Các ID `LiquidPumpingStation`, `WashBasin`, `PlanterBox`, `MassageTable`
  và `StorageLocker` có trong `oni_catalog.json` cục bộ; lúc xác minh đều
  unlocked. Đã kiểm tra `PlanterBoxConfig`, `MassageTableConfig`,
  `LiquidPumpingStationConfig`, `StorageLockerConfig` bằng `ilspycmd`.
  Food skill chỉ chọn PlanterBox; nếu thiếu/locked, ghi
  `TODO_NOT_IMPLEMENTED_food_building_unavailable`.
- `PlanterBox` cần crop seed/planting để tạo cây; tự chọn seed và bảo đảm
  thu hoạch **TODO_VERIFY**. `MassageTable` cần điện theo cấu hình game;
  skill không tạo circuit. Pump đặt gần map cell `L`, nhưng hiệu quả bơm cần
  kiểm chứng trong game. WashBasin cần giao Water. Không giả định rate sản
  xuất/tiêu thụ mới.
- `diagnostics` đọc `agent.jsonl` và snapshot state truyền vào. Log cũ
  không có stress/Algae/research-progress; các xu hướng đó sẽ là unknown.
  Báo cáo không xác định nguyên nhân tử vong.
- Replay thêm `rule_replay_input` để phát lại rules, gồm history/pending/
  cooldown. Log cũ không có dữ liệu này sẽ unavailable. Catalog khi replay
  phải khớp với lúc lập kế hoạch để kỳ vọng action giống nhau.
- Metrics cycle là cycle quan sát cuối, không phải cycle tử vong. Command
  counts chỉ có khi log có kết quả; dry-run không tính thành công/thất bại.
- Step 7 có một build fail cú pháp vì đặt method trước catch hiện hữu. Đã
  sửa vị trí; build sau đó thành công 0 warning/0 error. Không có cùng lỗi
  lặp ba lần.

### Lệnh kiểm tra PHẦN 2

```powershell
python -m agent.diagnostics --logs logs/agent.jsonl --state <state.json>
python -m agent.replay --logs logs/agent.jsonl --catalog <oni_catalog.json>
python -m agent.agent_main --report
python -m agent.rule_engine --validate
python -m pytest -q
dotnet build OniAgent.csproj --no-restore
git check-ignore -v -- .env .env.local sample-key.json test.sav
```

### VIỆC CẦN NGƯỜI DÙNG TEST TRONG GAME

- Trường C# mới `operational_flags`: trong colony thử nghiệm, so sánh
  `operational` với từng `{name,satisfied}`; kiểm tra building đang hoạt động
  và không hoạt động/thiếu điện. Xác nhận lỗi đọc một field không làm mất
  building khỏi `building_list`, và cache vẫn khoảng 10 giây. Trường mới
  **CHƯA TEST TRONG GAME**.
- Event journal C# trước đó cũng **CHƯA TEST TRONG GAME**: hoàn tất một
  building và quan sát `building_completed`; trong colony bỏ đi mới kiểm
  tra `dupe_died`; vượt ngưỡng stress để quan sát `dupe_stress_threshold`;
  đổi chore để quan sát `chore_changed`; xác nhận append trên main-thread
  update và rotation sau khi file vượt 5 MiB.
- Build plans: kiểm tra LiquidPumpingStation gần liquid, giao Water cho
  WashBasin, PlanterBox từ seed tới thu hoạch, MassageTable có điện,
  StorageLocker footprint, và rules ở biên cycle 10/30/100. Không dùng save
  quan trọng để kiểm thử.
- Python item 9 đã kiểm tra offline bằng `python -m pytest -q`: **129 passed**.
  Thay đổi C# chưa được test trong game; không chạy game/deploy hoặc push.

**Không chạy game, deploy, copy DLL, sửa save hoặc push.** Không có key/token
hay save nào được thêm vào repo. Kết quả kiểm thử và thời gian ở trên là
kiểm tra offline.

## Giai đoạn 1 — Rule engine: xác minh và hiệu chỉnh CLI

Rule engine dạng khai báo, `rules.yaml`, tích hợp agent và các test đã có
trong repo, với phần lõi được commit ở `1c9cfbb` và rules giai đoạn sau ở
`e591c05`. Khi xác minh lại, `--validate` trả `{"valid":true,"rules":9}`.
Phát hiện thêm rằng `--explain` với rule khớp nhưng không được truyền executor
đã báo nhầm `TODO_NOT_IMPLEMENTED`; CLI chỉ đang giải thích điều kiện, không
được yêu cầu gọi skill. Đã đổi kết quả thành `skill_preview_not_requested`,
vẫn giữ `TODO_NOT_IMPLEMENTED` khi executor map được cung cấp rõ ràng nhưng
thiếu skill.

Kiểm chứng sau hiệu chỉnh: `python -m pytest -q` — **130 passed**;
`dotnet build` — **Build succeeded, 0 Warning(s), 0 Error(s)**;
`python -m agent.rule_engine --validate` — **9 rules hợp lệ**.
Không có API ONI mới nào được thêm; `README_API.md` không đổi. Các skill
được khai báo trong rules đều có executor hiện tại. Những điều cần kiểm tra
trong game vẫn gồm prefab có sẵn/unlocked, đủ vật liệu, và hiệu quả thực tế
của các build plan; không có tên prefab mới được đoán ở lần hiệu chỉnh này.

Kiểm tra an toàn trong game (chỉ dry-run; cần state/catalog hiện có):

```powershell
python -m agent.agent_main --dry-run --manager none --max-steps 1 --data-dir "$env:USERPROFILE\Documents\Klei\OxygenNotIncluded"
```

Chỉ đọc state/catalog và ghi log/JSONL; không gửi command khi dùng
`--dry-run`. C# không đổi; không chạy game, deploy, copy DLL hoặc push.
