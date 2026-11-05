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
