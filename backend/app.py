"""
智能座舱 HMI 仪表盘 — Flask 后端
模拟车速、电池、空调、导航、语音指令处理
"""
import math
import random
import threading
import time
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# ─── 车辆状态模拟 ───
state = {
    "speed": 0,          # km/h
    "rpm": 800,          # 发动机转速
    "battery": 72,       # SOC %
    "temperature": 340,  # 电池温度 K
    "gear": "P",         # P/R/N/D
    "ac_on": False,
    "ac_temp": 24,       # 设定温度 ℃
    "ac_fan": 3,         # 风量 1-7
    "ac_mode": "auto",   # auto/cool/heat/vent
    "ac_in": 22,         # 车内温度
    "ac_out": 35,        # 车外温度
    "odometer": 18472,   # 总里程 km
    "range": 312,        # 续航 km
    "power": 0,          # 瞬时功率 kW
    "autopilot": False,
    "voice_active": False,
    "voice_result": "",
}


def simulate_vehicle():
    """后台线程：模拟车辆传感器数据变化"""
    global state
    while True:
        time.sleep(0.1)  # 10Hz 更新

        # 车速平滑变化
        target_speed = state["speed"]
        if state["gear"] == "D":
            target_speed = min(120, target_speed + random.uniform(-2, 3))
        elif state["gear"] == "R":
            target_speed = max(-20, target_speed + random.uniform(-3, 1))
        else:
            target_speed *= 0.95  # 怠速衰减

        state["speed"] = round(target_speed, 1)
        state["rpm"] = max(0, int(800 + abs(state["speed"]) * 35 + random.randint(-50, 50)))
        state["power"] = round(abs(state["speed"]) * 0.15 + random.uniform(-2, 5), 1)
        state["odometer"] += abs(state["speed"]) / 36000  # 10Hz → odometer

        # 电池 SOC
        state["battery"] = max(5, min(100, state["battery"] - abs(state["speed"]) * 0.0003
                                      + random.uniform(-0.02, 0.02)))
        state["battery"] = round(state["battery"], 1)
        state["range"] = int(state["battery"] * 4.33)

        # 空调效果：车内温度缓慢趋近设定温度
        if state["ac_on"]:
            diff = state["ac_temp"] - state["ac_in"]
            state["ac_in"] += diff * 0.02
        else:
            state["ac_in"] += (state["ac_out"] - state["ac_in"]) * 0.005
        state["ac_in"] = round(state["ac_in"], 1)


# ─── API ───

@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")


@app.route("/api/state")
def get_state():
    return jsonify(state)


@app.route("/api/gear", methods=["POST"])
def set_gear():
    g = request.json.get("gear", "P")
    if g in ("P", "R", "N", "D"):
        if g == "P":
            state["speed"] = 0
        state["gear"] = g
    return jsonify({"ok": True, "gear": state["gear"]})


@app.route("/api/ac", methods=["POST"])
def set_ac():
    data = request.json
    if "on" in data:
        state["ac_on"] = bool(data["on"])
    if "temp" in data:
        state["ac_temp"] = max(16, min(32, int(data["temp"])))
    if "fan" in data:
        state["ac_fan"] = max(1, min(7, int(data["fan"])))
    if "mode" in data:
        state["ac_mode"] = data["mode"]
    return jsonify({"ok": True, "ac": {k: state[k] for k in ("ac_on","ac_temp","ac_fan","ac_mode","ac_in","ac_out")}})


@app.route("/api/voice", methods=["POST"])
def voice_command():
    text = request.json.get("text", "").strip()
    result = process_voice(text)
    return jsonify({"ok": True, "result": result})


def process_voice(text):
    """简单语音指令解析"""
    t = text.lower()
    if any(w in t for w in ("开空调", "打开空调", "空调打开")):
        state["ac_on"] = True
        return "空调已打开"
    if any(w in t for w in ("关空调", "关闭空调", "空调关闭")):
        state["ac_on"] = False
        return "空调已关闭"
    if "温度" in t:
        for word in t.split():
            if word.replace("度", "").replace("℃", "").isdigit():
                temp = int(word.replace("度", "").replace("℃", ""))
                state["ac_temp"] = max(16, min(32, temp))
                return f"温度已调至 {state['ac_temp']}℃"
    if "风量" in t:
        for word in t.split():
            if word.replace("档", "").isdigit():
                fan = int(word.replace("档", ""))
                state["ac_fan"] = max(1, min(7, fan))
                return f"风量已调至 {state['ac_fan']} 档"
    if any(w in t for w in ("导航", "去", "我要去")):
        return f"导航指令已接收：「{text}」，正在规划路线"
    if any(w in t for w in ("自动驾驶", "辅助驾驶")):
        state["autopilot"] = not state["autopilot"]
        return f"自动驾驶已{'开启' if state['autopilot'] else '关闭'}"
    return f"指令已接收：{text}"


if __name__ == "__main__":
    threading.Thread(target=simulate_vehicle, daemon=True).start()
    print(" 智能座舱 HMI 已启动 → http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
