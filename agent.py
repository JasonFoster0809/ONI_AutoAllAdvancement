import json, os, time, requests

STATE = os.path.expanduser(r"~\Documents\Klei\OxygenNotIncluded\oni_state.json")
MODEL = "qwen2.5-coder:3b"   # sửa theo tên trong `ollama list`

SYSTEM = """Bạn là cố vấn Oxygen Not Included. Nhận trạng thái colony dạng JSON.
Chỉ trả về JSON đúng dạng: {"action": "<một trong: build_oxygen, build_toilet, build_bed, build_food, wait>", "reason": "<1 câu tiếng Việt>"}
Chọn "wait" nếu chưa có gì khẩn cấp."""

def ask_brain(state_text):
    r = requests.post("http://localhost:11434/api/chat", json={
        "model": MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": state_text},
        ],
    }, timeout=180)
    return json.loads(r.json()["message"]["content"])

while True:
    try:
        with open(STATE, encoding="utf-8") as f:
            state = f.read()
        print(time.strftime("%H:%M:%S"), ask_brain(state))
    except Exception as e:
        print("Loi:", e)
    time.sleep(30)