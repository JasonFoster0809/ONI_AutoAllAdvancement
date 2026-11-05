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
- `agent.agent_main`: hỗ trợ `--dry-run`, `--max-steps`, cấu hình prefab ID từ
  catalog, corridor coordinates và log JSON Lines trong `logs/`.

Ví dụ chạy offline/dry-run một bước:

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --data-dir <thu-muc-fixture>
```

Ví dụ bật planner bằng ID lấy từ `oni_catalog.json`:

```powershell
python -m agent.agent_main --dry-run --max-steps 1 --research-center-id <id>
python -m agent.agent_main --dry-run --max-steps 1 --bed-id <bed-id> --door-id <door-id>
python -m agent.agent_main --dry-run --max-steps 1 --corridor 1,2,8,2
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

**XONG — `python -m pytest -q`: 28 passed; `dotnet build`: thành công, 0
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

**CHƯA THỰC HIỆN.** Chỉ sau khi hoàn tất xác minh và build của Phần 1 mới thêm
`mass_kg` vào catalog và áp dụng ngưỡng theo category trong Python. Test/pytest
sẽ được ghi bổ sung sau khi triển khai.
