# LLM-Traffic: LLM-Guided Adaptive Traffic Signal Control

A framework that uses large language models for multi-intersection traffic signal optimization, with upstream-downstream coordination and safety constraint enforcement.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  SUMO (TraCI)│────▶│  Perception  │────▶│  LLM Decision   │
│  Simulation  │     │  Layer       │     │  Layer (MiMo)   │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                    ┌──────────────┐     ┌─────────▼────────┐
                    │  Coordination│◀────│  Constraint      │
                    │  Engine      │     │  Engine          │
                    └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Signal      │
                    │  Execution   │
                    └──────────────┘
```

## Quick Start

### Prerequisites
- Python 3.10+
- SUMO 1.12.0+ (`apt install sumo sumo-tools`)
- Node.js 18+

### Backend
```bash
cd /root/llm-traffic
pip install httpx fastapi uvicorn websockets pydantic
export SUMO_HOME=/usr/share/sumo
python3.10 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd /root/llm-traffic/frontend
npm install
npx vite --host 0.0.0.0 --port 5180
```

### Run Experiment
```bash
cd /root/llm-traffic
python3.10 run_experiment.py
```

## Strategies

| Strategy | Description |
|----------|-------------|
| **Fixed** | Static 30s+3s+30s+3s cycle |
| **Random** | Randomized green durations [10, 60]s |
| **Webster** | Queue-based adaptive timing (classical formula) |
| **LLM+Coord** | LLM recommendations + coordination engine + constraint validation |

## Results (3×2 Grid, 6 Intersections, 300 Steps)

| Strategy | Avg Wait (s) | Avg Queue | Throughput |
|----------|-------------|-----------|------------|
| Fixed | 47.20 | 17.75 | 0.09 |
| Random | 8.00 | 7.78 | 0.36 |
| Webster | 4.52 | 6.42 | 0.41 |
| **LLM+Coord** | **2.27** | **3.81** | **0.49** |

LLM+Coord achieves 50% lower wait time and 41% lower queue length vs Webster.

## Project Structure

```
llm-traffic/
├── backend/
│   ├── main.py              # FastAPI server (REST + WebSocket)
│   ├── simulation/
│   │   └── sumo_engine.py   # Network-agnostic SUMO engine
│   ├── llm/
│   │   └── xiaomi_client.py # LLM API client (batch mode)
│   ├── algorithms/
│   │   ├── webster.py       # Webster formula controller
│   │   ├── baseline.py      # Fixed/Random baselines
│   │   ├── constraints.py   # Safety constraint engine
│   │   └── coordination.py  # Multi-intersection coordination
│   └── experiment/
│       └── runner.py        # Experiment framework
├── frontend/
│   └── src/
│       ├── App.tsx           # Main UI
│       ├── components/
│       │   ├── GridCanvas.tsx       # Network visualization
│       │   ├── LLMPanel.tsx         # LLM decision display
│       │   ├── SignalTimingChart.tsx # Phase timeline
│       │   └── ExperimentComparison.tsx # Results chart
│       └── hooks/
│           └── useSimulationSocket.ts # WebSocket hook
├── data/
│   ├── grid6.net.xml        # 3×2 grid network
│   ├── grid6.rou.xml        # Traffic routes
│   ├── grid6.sumocfg        # SUMO config
│   └── experiment_results.json
├── paper/
│   └── main.tex             # IEEE conference paper
└── run_experiment.py        # Standalone experiment runner
```

## LLM Configuration

Default: MiMo v2.5 Pro via Xiaomi API. Configure in `backend/config/settings.py`:

```python
LLM_BASE_URL = "https://api.xiaomi.com/v1"
LLM_MODEL = "mimo-v2.5-pro"
LLM_API_KEY = "your-key-here"
```

Supports any OpenAI-compatible API. For reasoning models (like MiMo), results are extracted from `reasoning_content` field.

## License

MIT
