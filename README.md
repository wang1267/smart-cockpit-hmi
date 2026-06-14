# 🚗 IntelliDash · 智能座舱仪表盘

> 智能座舱 HMI 交互原型 | Python + Flask + Web 前端  
> 模拟车载中控屏，演示车速/电池/空调/语音控制

## 运行

```bash
cd backend
pip install -r requirements.txt
python app.py
```

浏览器打开 `http://localhost:5000`

## 功能

| 功能 | 操作 | 状态 |
|------|------|------|
| 🚀 数字仪表盘 | 车速环 + RPM + 档位 (P/R/N/D) | ✅ |
| 🔋 电池管理 | SOC / 续航 / 温度 / 瞬时功率 | ✅ |
| 🌡 空调控制 | 温度 ±、风量 ±、AUTO/制冷/制热 | ✅ |
| 🎙 语音控制 | Web Speech API 中文语音指令 | ✅ |
| ⌨ 键盘控制 | P/R/N/D 换挡 / ↑↓ 调温 | ✅ |

## 语音指令示例

- "打开空调" / "关闭空调"
- "温度 26 度"
- "风量 5 档"
- "导航到武汉"
- "开启自动驾驶"

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python · Flask · Flask-CORS |
| 前端 | 原生 HTML/CSS/JS · SVG 仪表盘 · Web Speech API |
| 数据 | 10Hz 实时模拟传感器数据 |
| 工具 | Claude Code · GitHub |

## 项目结构

```
smart-cockpit-hmi/
├── backend/
│   ├── app.py              # Flask API + 数据模拟
│   └── requirements.txt
├── frontend/
│   └── index.html           # 座舱 HMI 界面
└── README.md
```

---

> 🤖 本项目由王哲与 Claude Code 协作开发  
> 湖北汽车工业学院 · 智能车辆工程 · 2027 届
