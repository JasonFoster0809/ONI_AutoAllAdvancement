import json, os, time

DOC = os.path.expanduser(r"~\Documents\Klei\OxygenNotIncluded")
STATE = os.path.join(DOC, "oni_state.json")
CMD = os.path.join(DOC, "oni_commands.json")
RES = os.path.join(DOC, "oni_results.json")

MAX_PENDING = 6      # tối đa số ô đang chờ đào
BATCH = 3            # số ô gửi mỗi lượt
MAX_TOTAL = 30       # tổng số ô tối đa agent được phép đào (chặn đào vô hạn)
SAFE_RADIUS = 4      # không đào nếu có L (lỏng) hoặc V (chân không) trong bán kính này
PENDING_TIMEOUT = 300
LOOP_SECONDS = 15

failed = set()       # ô bị mod từ chối, không thử lại
pending = {}         # (x,y) -> thời điểm gửi
total_sent = 0

def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def state_is_fresh():
    try:
        return time.time() - os.path.getmtime(STATE) < 10
    except OSError:
        return False

def cell_at(m, ox, oy, x, y):
    row = (len(m) - 1) - (y - oy)
    col = x - ox
    if 0 <= row < len(m) and 0 <= col < len(m[row]):
        return m[row][col]
    return None

def is_safe(m, ox, oy, x, y):
    for dx in range(-SAFE_RADIUS, SAFE_RADIUS + 1):
        for dy in range(-SAFE_RADIUS, SAFE_RADIUS + 1):
            if cell_at(m, ox, oy, x + dx, y + dy) in ("L", "V"):
                return False
    return True

def candidates(state):
    w = state["world"]
    m, ox, oy = w["map"], w["origin"]["x"], w["origin"]["y"]
    sx, sy = w["start"]["x"], w["start"]["y"]
    out = []
    for row, line in enumerate(m):
        for col, ch in enumerate(line):
            if ch != "#":
                continue
            x, y = ox + col, oy + (len(m) - 1 - row)
            if (x, y) in failed or (x, y) in pending:
                continue
            nb = [cell_at(m, ox, oy, x + dx, y + dy) for dx, dy in ((1,0),(-1,0),(0,1),(0,-1))]
            if "G" not in nb:
                continue
            if not is_safe(m, ox, oy, x, y):
                continue
            out.append((abs(x - sx) + abs(y - sy), x, y))
    out.sort()
    return [(x, y) for _, x, y in out]

def update_pending(state):
    w = state["world"]
    m, ox, oy = w["map"], w["origin"]["x"], w["origin"]["y"]
    for (x, y), t in list(pending.items()):
        ch = cell_at(m, ox, oy, x, y)
        if ch != "#":
            print(f"  Da dao xong ({x},{y}) -> '{ch}'")
            del pending[(x, y)]
        elif time.time() - t > PENDING_TIMEOUT:
            print(f"  Qua han ({x},{y}), bo qua")
            failed.add((x, y))
            del pending[(x, y)]

def send_dig(cells):
    cid = "rule" + str(int(time.time() * 1000))
    cmd = {"id": cid, "actions": [{"type": "dig", "x": x, "y": y} for x, y in cells]}
    tmp = CMD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cmd, f)
    os.replace(tmp, CMD)
    for _ in range(20):                      # chờ tối đa ~20 giây
        time.sleep(1)
        res = read_json(RES)
        if res and res.get("id") == cid:
            return res["results"]
    return None

while True:
    try:
        if not state_is_fresh():
            print("Game chua chay / state cu, doi...")
        else:
            state = read_json(STATE)
            if state and "map" in state.get("world", {}):
                update_pending(state)
                room = min(MAX_PENDING - len(pending), BATCH, MAX_TOTAL - total_sent)
                if room > 0:
                    picks = candidates(state)[:room]
                    if picks:
                        print("Gui lenh dig:", picks)
                        results = send_dig(picks)
                        if results is None:
                            print("  Khong nhan duoc ket qua (da bam G chua?)")
                        else:
                            for r in results:
                                key = (r["x"], r["y"])
                                total_sent += 1
                                if r["ok"]:
                                    pending[key] = time.time()
                                else:
                                    failed.add(key)
                                    print(f"  Tu choi {key}: {r['reason']}")
                    else:
                        print("Khong con o nao hop le de dao.")
                if total_sent >= MAX_TOTAL and not pending:
                    print("Da dat gioi han, dung.")
                    break
    except Exception as e:
        print("Loi:", e)
    time.sleep(LOOP_SECONDS)