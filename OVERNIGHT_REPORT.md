# Báo cáo overnight

## Trạng thái giai đoạn 1-5

| Giai đoạn | Trạng thái | Xác minh/build |
|---|---|---|
| 1. Cancel API/action | XONG | API đã decompile; `dotnet build` thành công sau mỗi bước. |
| 2. set_priority | XONG | API đã decompile; `dotnet build` thành công sau mỗi bước. |
| 3. State mở rộng | XONG | Achievements, môi trường quanh telepad, pin/công suất đã thêm; water đã có trong state. `dotnet build` thành công sau mỗi bước. |
| 4. Tài liệu | XONG | README và playbook cập nhật; `dotnet build` thành công. |
| 5. Báo cáo | ĐANG THỰC HIỆN | Sẽ cập nhật thêm sau giai đoạn 6-11. |

Không có mục nào bị bỏ qua hoặc bị dừng do ba lần build thất bại. Trong lần build đầu tiên của action `cancel`, compiler báo `CS1503` vì `GameHashes.Cancel` là enum trong khi `Trigger` nhận `int`; đã sửa bằng ép kiểu enum đã xác minh và build tiếp theo thành công.

## Action mới

### Hủy lệnh đào hoặc xây

```json
{"id":"cancel-001","actions":[{"type":"cancel","x":12,"y":34}]}
```

Kết quả: `ok`, `nothing_to_cancel`, `out_of_bounds`, hoặc `error`. Khi `ok`,
kết quả có thêm `"cancelled":"dig"` hoặc `"cancelled":"build"`. Hủy đào khởi
động animation của game; `ok` cho biết event hủy đã được phát, không khẳng
định animation đã kết thúc.

### Đổi ưu tiên

```json
{"id":"priority-001","actions":[{"type":"set_priority","x":12,"y":34,"priority":8}]}
```

Kết quả: `ok`, `nothing_found`, `invalid_priority`, hoặc `out_of_bounds`.
Priority hợp lệ là 1-9.

## State mới

- `achievements[]`: `id`, `name`, `achieved`, `progress[]`.
- `environment`: `temperature_avg_k`, `oxygen_avg_g`, `co2_avg_g` trong vùng
  11x11 quanh telepad; bỏ qua nếu không đọc được mẫu hợp lệ.
- `power`: `battery_joules`, `battery_capacity_joules`,
  `circuit_joules_available`, `watts_used`, `watts_generated`,
  `watts_potential`, `circuits`.
- Nước sạch đã tồn tại tại `resources.clean_water_kg`.

## File đã thay đổi

- `Mod.cs`
- `README_API.md`
- `playbook.md`
- `OVERNIGHT_REPORT.md`

## Commit đã tạo tới giai đoạn 4

- `802d681` — baseline
- `210325b` — Add cancel action
- `a82b920` — Add set priority action
- `a6712b8` — Expand colony state snapshot
- `0b3f902` — Document ONI playbook and build coordinates

Tất cả code C# mới **CHƯA được test thật trong game**. Không deploy, không
copy DLL vào thư mục game và không chạy game.
