# LLM-Traffic: LLM-Assisted Adaptive Traffic Signal Control

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![SUMO](https://img.shields.io/badge/SUMO-1.12+-green.svg)](https://sumo.dlr.de/)

## Overview

LLM-Traffic is an exploratory research framework that applies Large Language Models (LLMs) to multi-intersection traffic signal control. The system uses LLMs to generate candidate signal timing recommendations, which are then validated through a constraint engine and coordinated across neighboring intersections.

**Key characteristics:**
- LLM-assisted phase selection and green duration adjustment
- Constraint-validated signal timing recommendations
- Multi-intersection coordination under a grid benchmark
- Simulation-based evaluation using SUMO/TraCI

> **Note:** This is a research prototype. Results are exploratory and require validation on more networks, demand patterns, and random seeds.

## Key Features

- **LLM-Guided Signal Control**: Uses LLMs to generate candidate timing recommendations based on current traffic state
- **Safety Constraint Engine**: Validates all LLM decisions against safety rules before execution
- **Upstream-Downstream Coordination**: Adjusts neighboring signals to prevent queue spillover
- **Multiple Baseline Strategies**: Fixed-time, Random, Webster, MaxPressure, and RL controllers
- **Comprehensive Metrics**: Wait time, queue length, throughput, delay, and stops
- **Reproducible Experiments**: Standardized experiment framework with warm-up and multiple trials

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend Server                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   SUMO       │    │  Perception  │    │  LLM         │      │
│  │   Simulation │───▶│  Layer       │───▶│  Decision    │      │
│  │   (TraCI)    │    │  (State)     │    │  Layer       │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                  │               │
│                    ┌──────────────┐    ┌─────────▼────────┐     │
│                    │  Coordination│◀───│  Constraint      │     │
│                    │  Engine      │    │  Engine          │     │
│                    └──────┬───────┘    └──────────────────┘     │
│                           │                                      │
│                    ┌──────▼───────┐                             │
│                    │  Signal      │                             │
│                    │  Execution   │                             │
│                    └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

## Method

### SUMO/TraCI Simulation

The system uses SUMO (Simulation of Urban Mobility) with TraCI (Traffic Control Interface) for microscopic traffic simulation. The simulation engine automatically discovers traffic lights and approach edges from the network configuration.

### Traffic State Perception

At each control interval, the system collects:
- Queue lengths per approach (vehicles with speed < 0.1 m/s)
- Vehicle counts per approach
- Current signal phase and timing

### LLM-Guided Timing Recommendation

The LLM receives a structured prompt containing:
- Current traffic state for all intersections
- Upstream/downstream queue information
- Safety constraints (min/max green times)

The LLM returns candidate phase durations in JSON format.

### Constraint Validation

All LLM decisions are validated against safety constraints:
- Minimum green time: 10s (pedestrian safety)
- Maximum green time: 60s (prevent starvation)
- Minimum cycle: 30s
- Maximum cycle: 180s

Violations are automatically corrected to safe values.

### Upstream-Downstream Coordination

The coordination engine detects queue spillover from upstream intersections and adjusts downstream green times:
- If upstream queue > threshold: boost green time for incoming direction
- If upstream queue > critical threshold: force phase switch

### Baseline Controllers

- **Fixed**: Static equal green splits
- **Random**: Randomized green durations within constraints
- **Webster**: Queue-based adaptive timing using Webster's formula
- **MaxPressure**: Selects phase with maximum queue pressure
- **RL**: Reinforcement learning-based controller

### Ablation Strategies

To isolate the contribution of each component, the following ablation strategies are provided:

- **llm_only**: LLM recommendations only (no coordination, no constraints)
- **llm_constraints**: LLM + constraint validation (no coordination)
- **llm_coord**: LLM + coordination (no constraint correction)
- **llm_full**: LLM + coordination + constraints (complete pipeline)

These strategies help understand:
1. How much does the constraint engine contribute to safety?
2. How much does coordination contribute to performance?
3. What's the baseline LLM performance without safety nets?

## Project Structure

```
llm-traffic/
├── backend/
│   ├── main.py                    # FastAPI server (REST + WebSocket)
│   ├── simulation/
│   │   └── sumo_engine.py         # SUMO simulation engine
│   ├── llm/
│   │   └── xiaomi_client.py       # LLM API client
│   ├── algorithms/
│   │   ├── baseline.py            # Fixed/Random controllers
│   │   ├── webster.py             # Webster's formula
│   │   ├── constraints.py         # Safety constraint engine
│   │   ├── coordination.py        # Multi-intersection coordination
│   │   └── rl_controller.py       # RL controller
│   └── experiment/
│       └── runner.py              # Experiment framework
├── frontend/
│   └── src/
│       ├── App.tsx                # Main UI
│       └── components/            # React components
├── data/
│   ├── grid6.net.xml              # Network definition
│   ├── grid6.rou.xml              # Traffic routes
│   └── experiment_results.json    # Experiment data
├── tests/
│   ├── test_constraints.py        # Constraint engine tests
│   ├── test_webster.py            # Webster controller tests
│   ├── test_llm_parser.py         # LLM response parser tests
│   └── test_coordination.py       # Coordination engine tests
├── ARCHITECTURE.md                # System architecture doc
├── INTERVIEW_GUIDE.md             # Interview preparation
└── run_experiment.py              # Standalone experiment runner
```

## Installation

### Prerequisites

- Python 3.10+
- SUMO 1.12.0+ (`apt install sumo sumo-tools`)
- Node.js 18+ (for frontend)

### Python Dependencies

```bash
pip install -r requirements.txt
```

### SUMO Configuration

```bash
export SUMO_HOME=/usr/share/sumo
```

### LLM Configuration (Optional)

LLM configuration is only required for the LLM strategy. Non-LLM strategies work without this.

```bash
cp .env.example .env
# Edit .env with your API key
```

Or set environment variables:

```bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=your-openai-compatible-url
export LLM_MODEL=your-model-name
```

**Note:** If `LLM_API_KEY` is not set, non-LLM baselines still work. The LLM strategy will fallback to default timing if the API call fails.

## Configuration

All configuration is centralized in `backend/config/settings.py`:

- **SUMO**: Network file, simulation duration, step length
- **LLM**: API key, base URL, model name
- **Algorithm**: Min/max green times, cycle lengths, saturation flow
- **Experiment**: Steps, warm-up, trials, strategies

## Quick Start

### Backend

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Run Demo

```bash
python demo.py --strategy llm --steps 300
```

## Reproduce Experiments

### Experiment Settings

The following settings are used across the project:

| Parameter | Value |
|-----------|-------|
| Network | `data/grid6.sumocfg` |
| Intersections | 6 (3×2 grid) |
| Simulation steps | 3600 |
| Warm-up steps | 600 |
| Trials | 10 |
| Strategies | fixed, random, webster, maxpressure, rl, llm |

### Run Experiments

```bash
python run_experiment.py
```

Results are saved to `data/experiment_results.json`.

### Run Tests

```bash
pytest
```

Tests do not require SUMO and test pure Python modules only.

## Results

The following table is generated from the provided `data/experiment_results.json` file.

**Experiment Setup:**
- Network: `data/grid6.sumocfg` (3×2 grid, 6 intersections)
- Simulation steps: 3600 (600 warm-up + 3000 measured)
- Trials: 10 per strategy
- Metrics collected after warm-up period

| Strategy | Avg Wait (s) | Avg Queue | Throughput (veh/step) |
|----------|-------------|-----------|----------------------|
| Fixed | 249.2 ± 0.0 | 112.8 ± 0.0 | 0.053 ± 0.000 |
| Random | 124.9 ± 4.2 | 108.0 ± 1.1 | 0.085 ± 0.008 |
| Webster | 213.9 ± 0.0 | 112.1 ± 0.0 | 0.060 ± 0.000 |
| MaxPressure | 191.6 ± 0.0 | 110.3 ± 0.0 | 0.078 ± 0.000 |
| RL | 120.5 ± 6.2 | 106.9 ± 1.1 | 0.092 ± 0.009 |
| LLM+Coord | 127.0 ± 6.0 | 103.6 ± 1.1 | 0.115 ± 0.008 |

**Interpretation:**

The provided grid benchmark suggests that the LLM-assisted controller can achieve competitive queue and throughput performance under the current simulation setup. However, the results should be interpreted as exploratory and require validation on more networks, demand patterns, and random seeds.

**Note:** The LLM strategy includes coordination and constraint validation. Ablation studies are provided to isolate the contribution of each component.

## Limitations

1. **Single network**: Results are based on a 3×2 grid benchmark only
2. **Coordination scope**: The coordination module is currently implemented for the provided grid benchmark
3. **Webster baseline**: Uses a simplified queue-to-flow proxy (queue_length × 120), not strict engineering calibration
4. **LLM latency**: API calls add 100-500ms per decision cycle
5. **Cost**: LLM API calls incur costs (mitigated by batch processing)
6. **Reliability**: LLM responses can be inconsistent (mitigated by constraint engine)

## Roadmap

- [ ] Validate on more networks (real-world, larger grids)
- [ ] Fine-tune smaller model for traffic-specific tasks
- [ ] Implement hierarchical coordination for scalability
- [ ] Add real-time data integration (cameras, GPS)
- [ ] Systematic evaluation of LLM latency and cost

## License

MIT
