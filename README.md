# LLM-Traffic

基于大语言模型的单路口交通信号优化平台。

## 项目简介

利用 LLM 分析实时交通状态，自动生成信号配时方案，并通过 SUMO 仿真验证效果。

**核心特性：**
- SUMO 微观交通仿真（单路口四方向）
- LLM 通过 API 调用分析拥堵并推荐信号配时
- Web 前端实时展示仿真动画、指标图表、LLM 决策理由
- 内置基线对比（固定配时 vs LLM 优化）

## 技术栈

| 层 | 技术 |
|---|---|
| 仿真引擎 | SUMO + TraCI |
| 后端 | Python + FastAPI + WebSocket |
| LLM | 小米 API（OpenAI 兼容格式） |
| 前端 | React + TypeScript + Vite + ECharts |
| 数据库 | SQLite（实验结果存储） |

## 快速开始

### 1. 安装依赖

```bash
# 系统依赖
sudo apt install sumo sumo-tools

# Python 依赖
pip install fastapi uvicorn traci sumolib websockets openai pydantic

# 前端依赖
cd frontend && npm install
```

### 2. 配置 LLM API

编辑 `backend/config/settings.py`，填入你的 API Key：

```python
LLM_API_KEY = "your-api-key-here"
LLM_BASE_URL = "https://api.xiaomi.com/v1"  # 或其他 OpenAI 兼容 API
LLM_MODEL = "mimo-v2-pro"
```

### 3. 启动后端

```bash
cd /root/llm-traffic
SUMO_HOME=/usr/share/sumo python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm run dev
```

访问 http://localhost:5173

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/simulation/start` | 启动仿真 |
| POST | `/api/simulation/stop` | 停止仿真 |
| GET | `/api/simulation/state` | 获取当前状态 |
| POST | `/api/simulation/set-phase` | 手动设置信号相位 |
| WS | `/ws/simulation` | 实时数据推送 |

## 项目结构

```
llm-traffic/
├── backend/
│   ├── main.py              # FastAPI 主入口
│   ├── simulation/
│   │   └── sumo_engine.py   # SUMO 仿真引擎封装
│   ├── llm/
│   │   └── xiaomi_client.py # LLM API 调用
│   ├── models/
│   │   └── schemas.py       # Pydantic 数据模型
│   └── config/
│       └── settings.py      # 配置
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── IntersectionCanvas.tsx  # Canvas 路口动画
│       │   ├── ControlPanel.tsx        # 控制面板
│       │   ├── MetricsDisplay.tsx      # 实时指标
│       │   ├── QueueChart.tsx          # 排队图表
│       │   └── LLMPanel.tsx           # LLM 决策展示
│       └── App.tsx
├── data/                    # SUMO 路网文件
└── README.md
```

## License

MIT
