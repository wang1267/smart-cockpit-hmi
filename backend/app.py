"""
IntelliDash · 智能座舱仪表盘 — Flask 后端 v3
新增：油门刹车踏板 · 电池充放电系统 · 语音唤醒「小王小王」· 断电/充电状态
"""
import math
import random
import threading
import time
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# ─── 车辆状态 ───
state = {
    # 驾驶
    "speed": 0,           # km/h
    "rpm": 0,
    "gear": "P",
    "throttle": 0,        # 油门开度 0-100%
    "brake": 0,           # 制动开度 0-100%
    "autopilot": False,

    # 电池（初始满电）
    "battery": 100.0,     # SOC %
    "battery_temp": 310,  # K
    "odometer": 18472,    # km
    "range": 433,         # 续航 km
    "power": 0,           # 瞬时功率 kW

    # 充电
    "charging": False,
    "power_off": False,   # 电量耗尽断电

    # 电池告警
    "battery_warning": None,  # "low" / "critical" / "emergency"

    # 空调
    "ac_on": False,
    "ac_temp": 24,
    "ac_fan": 3,
    "ac_mode": "auto",
    "ac_in": 26,
    "ac_out": 35,

    # 语音
    "voice_active": False,
    "voice_result": "",
    "wake_detected": False,
}


def simulate_vehicle():
    """后台线程：10Hz 传感器模拟"""
    global state
    tick = 0
    while True:
        time.sleep(0.1)
        tick += 1

        # ═══ 断电状态：全部冻结 ═══
        if state["power_off"]:
            state["speed"] = 0
            state["rpm"] = 0
            state["power"] = 0
            state["throttle"] = 0
            state["brake"] = 0
            state["autopilot"] = False
            if state["gear"] != "P":
                state["gear"] = "P"
            continue

        # ═══ 充电状态：不能挂挡 ═══
        if state["charging"]:
            if state["gear"] != "P":
                state["gear"] = "P"
            state["speed"] = max(0, state["speed"] * 0.8)
            state["rpm"] = 0
            state["power"] = 0
            state["throttle"] = 0
            state["brake"] = 0

            # 充电速度：~2%/秒
            state["battery"] = min(100, state["battery"] + 0.2)
            state["battery"] = round(state["battery"], 1)
            state["range"] = int(state["battery"] * 4.33)

            # 充满自动停
            if state["battery"] >= 99.9:
                state["battery"] = 100.0
                state["charging"] = False
                state["battery_warning"] = None
                state["power_off"] = False

            if tick % 10 == 0:
                update_battery_warning()
            continue

        # ═══ 正常驾驶 ═══
        throttle = state["throttle"] / 100
        brake = state["brake"] / 100

        if state["gear"] == "D":
            target = throttle * 140 - brake * 50
            state["speed"] += (target - state["speed"]) * 0.08
        elif state["gear"] == "R":
            target = -(throttle * 25 - brake * 15)
            state["speed"] += (target - state["speed"]) * 0.08
        else:
            state["speed"] *= 0.9

        state["speed"] = round(max(-25, min(160, state["speed"])), 1)
        state["rpm"] = max(0, int(abs(state["speed"]) * 40 + random.randint(-30, 30)))
        state["power"] = round(abs(state["speed"]) * 0.2 * (0.5 + throttle * 0.5) + random.uniform(-1, 2), 1)

        # 里程累计
        state["odometer"] += abs(state["speed"]) / 36000

        # ═══ 电池消耗 ═══
        # 基础消耗 + 速度消耗 + 空调消耗
        base_drain = 0.0005
        speed_drain = abs(state["speed"]) * 0.00005 * (1 + throttle * 2)
        ac_drain = 0.0003 if state["ac_on"] else 0
        total_drain = base_drain + speed_drain + ac_drain
        state["battery"] = max(0, state["battery"] - total_drain)
        state["battery"] = round(state["battery"], 1)
        state["range"] = int(state["battery"] * 4.33)

        # 电池温度
        state["battery_temp"] = int(310 + abs(state["speed"]) * 0.3 + random.randint(-1, 2))

        # 电量告警
        if tick % 10 == 0:
            update_battery_warning()

        # 电量耗尽 → 断电
        if state["battery"] <= 0:
            state["battery"] = 0
            state["power_off"] = True
            state["gear"] = "P"
            state["speed"] = 0
            state["throttle"] = 0
            state["brake"] = 0
            state["battery_warning"] = "emergency"

        # 空调温控
        if state["ac_on"]:
            diff = state["ac_temp"] - state["ac_in"]
            state["ac_in"] += diff * 0.02
        else:
            state["ac_in"] += (state["ac_out"] - state["ac_in"]) * 0.005
        state["ac_in"] = round(state["ac_in"], 1)


# 记录已触发的告警（每个阈值只触发一次）
_triggered_warnings = set()

def update_battery_warning():
    b = state["battery"]

    if b <= 0:
        level = "emergency"
    elif b <= 2:
        level = "emergency"
    elif b <= 10:
        level = "critical"
    elif b <= 20:
        level = "low"
    else:
        # 电量回升到阈值以上，重置对应告警
        if b > 20:
            _triggered_warnings.discard("low")
        if b > 10:
            _triggered_warnings.discard("critical")
        if b > 2:
            _triggered_warnings.discard("emergency")
        state["battery_warning"] = None
        return

    # 仅在首次到达该阈值时告警
    if level not in _triggered_warnings:
        _triggered_warnings.add(level)
        state["battery_warning"] = level
    else:
        state["battery_warning"] = None


# ═══════════════ API ═══════════════

@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")


@app.route("/api/state")
def get_state():
    return jsonify(state)


@app.route("/api/gear", methods=["POST"])
def set_gear():
    if state["power_off"]:
        return jsonify({"ok": False, "msg": "电量耗尽，请充电"})
    if state["charging"]:
        return jsonify({"ok": False, "msg": "充电中，请断开充电枪"})
    g = request.json.get("gear", "P")
    if g in ("P", "R", "N", "D"):
        if g == "P":
            state["speed"] = 0
            state["throttle"] = 0
            state["brake"] = 0
        state["gear"] = g
    return jsonify({"ok": True, "gear": state["gear"]})


@app.route("/api/throttle", methods=["POST"])
def set_throttle():
    if state["power_off"]:
        return jsonify({"ok": False, "msg": "电量耗尽"})
    if state["charging"]:
        return jsonify({"ok": False, "msg": "充电中不可操作"})
    val = request.json.get("value", 0)
    state["throttle"] = max(0, min(100, int(val)))
    # 踩油门时自动释放刹车
    if state["throttle"] > 0:
        state["brake"] = 0
    return jsonify({"ok": True, "throttle": state["throttle"], "brake": state["brake"]})


@app.route("/api/brake", methods=["POST"])
def set_brake():
    if state["power_off"]:
        return jsonify({"ok": False, "msg": "电量耗尽"})
    val = request.json.get("value", 0)
    state["brake"] = max(0, min(100, int(val)))
    if state["brake"] > 0:
        state["throttle"] = 0
    return jsonify({"ok": True, "brake": state["brake"], "throttle": state["throttle"]})


@app.route("/api/charge", methods=["POST"])
def toggle_charge():
    """开始/停止充电"""
    action = request.json.get("action", "toggle")

    if action == "start":
        if state["power_off"] or state["battery"] < 100:
            state["charging"] = True
            state["gear"] = "P"
            state["speed"] = 0
            state["throttle"] = 0
            state["brake"] = 0
            state["power_off"] = False
            state["battery_warning"] = None
            _triggered_warnings.clear()  # 重置所有告警记录
            return jsonify({"ok": True, "charging": True})
        return jsonify({"ok": False, "msg": "电量已满"})

    if action == "stop":
        state["charging"] = False
        return jsonify({"ok": True, "charging": False})

    # toggle
    if state["charging"]:
        state["charging"] = False
    else:
        if state["battery"] < 100:
            state["charging"] = True
            state["gear"] = "P"
            state["speed"] = 0
            state["throttle"] = 0
            state["brake"] = 0
            state["power_off"] = False
            state["battery_warning"] = None
            _triggered_warnings.clear()
        else:
            return jsonify({"ok": False, "msg": "电量已满"})
    return jsonify({"ok": True, "charging": state["charging"]})


@app.route("/api/ac", methods=["POST"])
def set_ac():
    if state["power_off"]:
        return jsonify({"ok": False, "msg": "电量耗尽"})
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
    if state["power_off"]:
        return jsonify({"ok": True, "result": "电量耗尽，请先充电"})
    text = request.json.get("text", "").strip()
    result = process_voice(text)
    return jsonify({"ok": True, "result": result})


def process_voice(text):
    t = text.lower().replace(" ", "")

    # 挂挡指令
    if "p档" in t or "p挡" in t or "停车" in t:
        state["gear"] = "P"; state["speed"] = 0; state["throttle"] = 0; state["brake"] = 0
        return "已挂入 P 档"
    if "r档" in t or "r挡" in t or "倒车" in t:
        if state["charging"]: return "充电中不可驾驶"
        if state["power_off"]: return "电量耗尽"
        state["gear"] = "R"; state["throttle"] = 0
        return "已挂入 R 档"
    if "n档" in t or "n挡" in t or "空挡" in t:
        state["gear"] = "N"; state["throttle"] = 0
        return "已挂入 N 档"
    if "d档" in t or "d挡" in t or "前进" in t:
        if state["charging"]: return "充电中不可驾驶"
        if state["power_off"]: return "电量耗尽"
        state["gear"] = "D"; state["throttle"] = 0
        return "已挂入 D 档"

    # 加速 / 减速
    if "加速" in t or "快一点" in t or "快点" in t:
        if state["charging"]: return "充电中不可驾驶"
        if state["power_off"]: return "电量耗尽"
        state["throttle"] = min(100, state["throttle"] + 30)
        state["brake"] = 0
        if state["gear"] == "P":
            state["gear"] = "D"
            return "已挂 D 档，油门 " + str(state["throttle"])
        return f"油门加至 {state['throttle']}"
    if "减速" in t or "慢一点" in t or "慢点" in t:
        state["brake"] = min(100, state["brake"] + 30)
        state["throttle"] = 0
        return f"刹车加至 {state['brake']}"
    if "松油门" in t or "松开油门" in t:
        state["throttle"] = 0
        return "油门已松开"
    if "松刹车" in t or "松开刹车" in t:
        state["brake"] = 0
        return "刹车已松开"

    # 空调
    if "开空调" in t or "打开空调" in t:
        state["ac_on"] = True; return "空调已打开"
    if "关空调" in t or "关闭空调" in t:
        state["ac_on"] = False; return "空调已关闭"
    if "温度" in t:
        import re
        nums = re.findall(r'\d+', t)
        if nums:
            temp = int(nums[0])
            state["ac_temp"] = max(16, min(32, temp))
            return f"温度已调至 {state['ac_temp']}℃"
    if "风量" in t:
        import re
        nums = re.findall(r'\d+', t)
        if nums:
            fan = int(nums[0])
            state["ac_fan"] = max(1, min(7, fan))
            return f"风量已调至 {state['ac_fan']} 档"

    # 充电
    if "充电" in t:
        if state["battery"] >= 100:
            return "电量已满，无需充电"
        state["charging"] = True
        state["gear"] = "P"; state["speed"] = 0; state["throttle"] = 0; state["brake"] = 0
        state["power_off"] = False
        return "开始充电"
    if "停止充电" in t or "断开充电" in t:
        state["charging"] = False
        return "充电已停止"

    # 自动驾驶
    if "自动驾驶" in t or "辅助驾驶" in t:
        state["autopilot"] = not state["autopilot"]
        return f"自动驾驶已{'开启' if state['autopilot'] else '关闭'}"

    return f"指令已接收：{text}"


if __name__ == "__main__":
    threading.Thread(target=simulate_vehicle, daemon=True).start()
    print(" IntelliDash v3 启动 → http://localhost:5000")
    print(" 语音唤醒：说「小王小王」开始控制")
    app.run(host="0.0.0.0", port=5000, debug=False)
