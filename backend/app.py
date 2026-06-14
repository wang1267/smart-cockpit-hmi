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
    "cruise_on": False,   # 定速巡航
    "cruise_speed": 0,    # 巡航目标车速
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
            target = throttle * 300 - brake * 80
            state["speed"] += (target - state["speed"]) * 0.15
            state["speed"] = round(max(0, min(300, state["speed"])), 1)  # D档最低0
        elif state["gear"] == "R":
            target = -(throttle * 25 - brake * 15)
            state["speed"] += (target - state["speed"]) * 0.08
            state["speed"] = round(max(-25, min(0, state["speed"])), 1)  # R档最高0
        else:
            state["speed"] = round(state["speed"] * 0.9, 1)
            if abs(state["speed"]) < 0.5:
                state["speed"] = 0

        # 定速巡航：自动调节油门维持目标车速
        if state["cruise_on"] and state["gear"] == "D" and not state["power_off"]:
            speed_err = state["cruise_speed"] - state["speed"]
            if speed_err > 2:
                state["throttle"] = min(100, int(speed_err * 3))
                state["brake"] = 0
            elif speed_err < -2:
                state["brake"] = min(80, int(abs(speed_err) * 2))
                state["throttle"] = 0
            else:
                state["throttle"] = max(0, min(30, int(20 + speed_err * 2)))
                state["brake"] = 0
        state["rpm"] = max(0, int(abs(state["speed"]) * 40 + random.randint(-30, 30)))
        state["power"] = round(abs(state["speed"]) * 0.2 * (0.5 + throttle * 0.5) + random.uniform(-1, 2), 1)

        # 里程累计
        state["odometer"] += abs(state["speed"]) / 36000

        # ═══ 电池消耗 ═══
        # 基础消耗 + 速度消耗 + 空调消耗
        base_drain = 0.0015
        speed_drain = abs(state["speed"]) * 0.00015 * (1 + throttle * 2)
        ac_drain = 0.001 if state["ac_on"] else 0
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


@app.route("/api/cruise", methods=["POST"])
def set_cruise():
    data = request.json
    if state["power_off"]:
        return jsonify({"ok": False, "msg": "电量耗尽"})
    if state["charging"]:
        return jsonify({"ok": False, "msg": "充电中不可驾驶"})
    if "on" in data:
        state["cruise_on"] = bool(data["on"])
        if not data["on"]:
            state["cruise_speed"] = 0
    if "speed" in data:
        state["cruise_speed"] = max(10, min(300, int(data["speed"])))
        state["cruise_on"] = True
        if state["gear"] != "D":
            state["gear"] = "D"
        if state["cruise_speed"] > state["speed"]:
            state["throttle"] = 80
        else:
            state["throttle"] = 20
        state["brake"] = 0
    return jsonify({"ok": True, "cruise_on": state["cruise_on"], "cruise_speed": state["cruise_speed"]})


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
    import re
    original = text
    t = text.lower().replace(" ", "").replace("　", "")

    # ─── 中文数字 → 阿拉伯数字 ───
    cn_num_map = {
        "零":0,"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,
        "十":10,"二十":20,"三十":30,"四十":40,"五十":50,"六十":60,"七十":70,"八十":80,"九十":90,
        "百":100,
    }
    # 替换形如"六十"→"60"
    for cn, val in sorted(cn_num_map.items(), key=lambda x: -len(x[0])):
        t = t.replace(cn, str(val))

    # ─── 口音容错 + 同义词扩展 ───
    accent_fix = {
        # 挂挡
        "挂机档":"挂d档","g大档":"挂d档","瓜d档":"挂d档","皮档":"p档","批档":"p档",
        "二档":"r档","倒档":"r档","空档":"n档","嗯档":"n档",
        # 定速/巡航
        "订书":"定速","定数":"定速","钉速":"定速","顶速":"定速","匀速":"定速",
        "循环":"巡航","虚荣":"巡航","徐航":"巡航","寻航":"巡航",
        # 驾驶
        "家属":"加速","佳速":"加速","碱素":"减速","减书":"减速",
        "走":"加速","冲":"加速","停":"减速","刹":"刹车","杀":"刹车",
        # 空调
        "空投":"空调","空条":"空调","空头":"空调","恐高":"空调",
        "文都":"温度","问度":"温度","冷风":"制冷","热风":"制热",
        # 充电
        "冲电":"充电","通电":"充电","补充电量":"充电",
        # 唤醒
        "小王同学":"小王小王","小旺小旺":"小王小王",
    }
    for wrong, right in sorted(accent_fix.items(), key=lambda x: -len(x[0])):
        if wrong in t:
            t = t.replace(wrong, right)

    nums = re.findall(r'\d+', t)
    num = int(nums[0]) if nums else None

    # ─── 1. 空调温度（优先级最高，避免"调到18度"被当定速） ───
    if num and 16 <= num <= 32 and ("空调" in t or "温度" in t or ("度" in t and ("调" in t or "冷" in t or "热" in t or "设" in t))):
        state["ac_temp"] = num
        if not state["ac_on"]: state["ac_on"] = True
        return f"空调温度已调到 {num} 度"

    # ─── 2. 定速巡航（语义：数字 + 速度/行驶/保持/定速/巡航/开到/跑到） ───
    speed_context = ("定速" in t or "巡航" in t or "保持" in t or "开到" in t
        or "跑到" in t or "设定" in t or "速度" in t or "车速" in t
        or "行驶" in t or "限速" in t or (num and num > 32 and num <= 300 and ("开" in t or "走" in t or "跑" in t)))
    if speed_context and num and 0 <= num <= 300:
        if state["charging"]: return "充电中不可驾驶，请先停止充电"
        if state["power_off"]: return "电量耗尽，请先充电"
        state["cruise_speed"] = num
        state["cruise_on"] = True
        if num > state["speed"]:
            state["throttle"] = 80  # 立即给油加速
        else:
            state["throttle"] = 20
        state["brake"] = 0
        if state["gear"] != "D":
            state["gear"] = "D"
        return f"好的，定速巡航 {num} km/h"

    if "取消定速" in t or "退出定速" in t or "关闭定速" in t or "关闭巡航" in t or "退出巡航" in t:
        state["cruise_on"] = False; state["cruise_speed"] = 0
        return "定速巡航已取消"

    # ─── 2. 挂挡 ───
    gear_map = [
        (["p档","p挡","p","停车","驻车"], "P"),
        (["r档","r挡","r","倒车","倒挡"], "R"),
        (["n档","n挡","n","空挡","空档"], "N"),
        (["d档","d挡","d","前进","开车","走","起步"], "D"),
    ]
    for keywords, gear in gear_map:
        for kw in keywords:
            if t == kw or t.startswith(kw) or t.endswith(kw) or kw in t:
                if gear != "P":
                    if state["charging"]: return "充电中，请先断开充电枪"
                    if state["power_off"]: return "电量耗尽，请先充电"
                state["gear"] = gear
                if gear == "P":
                    state["speed"] = 0; state["throttle"] = 0; state["brake"] = 0
                    state["cruise_on"] = False
                state["throttle"] = 0; state["brake"] = 0
                return f"已挂入 {gear} 档"
                break

    # ─── 3. 速度控制 ───
    if "油门加满" in t or "地板油" in t or "全速" in t:
        if state["charging"]: return "充电中不可驾驶"
        if state["power_off"]: return "电量耗尽"
        state["cruise_on"] = False
        state["throttle"] = 100; state["brake"] = 0
        if state["gear"] != "D": state["gear"] = "D"
        return "油门踩到底！"

    if "踩刹车" in t or "急刹" in t or "刹停" in t:
        state["cruise_on"] = False
        state["brake"] = 100; state["throttle"] = 0
        return "急刹车！"

    if "加速" in t or "快" in t or "提速" in t or "踩油门" in t or "冲" in t or "加油门" in t:
        if state["charging"]: return "充电中不可驾驶"
        if state["power_off"]: return "电量耗尽"
        state["cruise_on"] = False
        state["throttle"] = min(100, state["throttle"] + 40)
        state["brake"] = 0
        if state["gear"] not in ("D","R"):
            state["gear"] = "D"
            return f"已挂D档，油门 {state['throttle']}"
        return f"油门 {state['throttle']}"

    if "减速" in t or "慢" in t or "刹车" in t or "刹" in t or "制动" in t:
        state["cruise_on"] = False
        state["brake"] = min(100, state["brake"] + 40)
        state["throttle"] = 0
        return f"刹车 {state['brake']}"

    if "松油门" in t or "松掉油门" in t:
        state["throttle"] = 0; state["cruise_on"] = False
        return "油门已松开"
    if "松刹车" in t:
        state["brake"] = 0
        return "刹车已松开"

    # ─── 4. 空调 ───
    if num and 16 <= num <= 32 and ("空调" in t or "温度" in t or "度" in t or "调" in t or "设" in t or "冷" in t or "热" in t):
        state["ac_temp"] = num
        if not state["ac_on"]:
            state["ac_on"] = True
        return f"空调温度已调到 {num} 度"

    if "开空调" in t or "启动空调" in t or "空调打开" in t:
        state["ac_on"] = True; return "空调已打开"
    if "关空调" in t or "空调关闭" in t or "空调关掉" in t:
        state["ac_on"] = False; return "空调已关闭"

    if "制冷" in t or "冷气" in t or "冷风" in t or "空调冷" in t:
        state["ac_mode"] = "cool"; state["ac_on"] = True; return "制冷模式已开启"
    if "制热" in t or "暖气" in t or "热风" in t or "空调热" in t:
        state["ac_mode"] = "heat"; state["ac_on"] = True; return "制热模式已开启"
    if "自动空调" in t or "auto" in t.lower():
        state["ac_mode"] = "auto"; state["ac_on"] = True; return "自动空调已开启"

    if num and 1 <= num <= 7 and ("风量" in t or "风速" in t or "风力" in t):
        state["ac_fan"] = num
        return f"风量调到 {num} 档"

    # ─── 5. 充电 ───
    if "充电" in t or "补电" in t:
        if state["battery"] >= 100: return "电量已满，无需充电"
        state["charging"] = True; state["gear"] = "P"
        state["speed"] = 0; state["throttle"] = 0; state["brake"] = 0
        state["power_off"] = False
        return "开始充电"
    if "停止充电" in t or "断开充电" in t or "不充了" in t:
        state["charging"] = False
        return "充电已停止"

    # ─── 6. 自动驾驶 ───
    if "自动驾驶" in t or "辅助驾驶" in t:
        state["autopilot"] = not state["autopilot"]
        return f"自动驾驶已{'开启' if state['autopilot'] else '关闭'}"

    # ─── 7. 听不懂时给建议 ───
    hints = [
        "「定速60」设巡航",
        "「挂D档」换挡",
        "「加速」「减速」控车速",
        "「空调24度」调温度",
        "「充电」开始充电",
        "「制冷」「制热」切换模式",
    ]
    return f"抱歉没听懂「{original}」。试试：" + "、".join(hints)


if __name__ == "__main__":
    threading.Thread(target=simulate_vehicle, daemon=True).start()
    print(" IntelliDash v3 启动 → http://localhost:5000")
    print(" 语音唤醒：说「小王小王」开始控制")
    app.run(host="0.0.0.0", port=5000, debug=False)
