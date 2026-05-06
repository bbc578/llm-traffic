#!/usr/bin/env bash
# ============================================================================
# reproduce.sh  –  Full reproducibility pipeline for LLM-Traffic
#
# Prerequisites (assumed pre-installed):
#   • Python 3.10   (python3.10)
#   • Node.js + npm
#   • SUMO 1.12.0+  (SUMO_HOME=/usr/share/sumo)
#   • pdflatex      (texlive)
#
# Usage:
#   cd /root/llm-traffic
#   bash reproduce.sh
#
# To also run the LLM-based strategy (requires API key):
#   export LLM_API_KEY="your-key-here"
#   bash reproduce.sh
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

SUMO_HOME="${SUMO_HOME:-/usr/share/sumo}"
export SUMO_HOME

echo "============================================================"
echo " LLM-Traffic Reproducibility Pipeline"
echo " Working directory: $(pwd)"
echo " Python:  $(python3.10 --version 2>&1)"
echo " Node:    $(node --version 2>&1)"
echo " SUMO:    $SUMO_HOME"
echo "============================================================"

# ── 1. Python dependencies ──────────────────────────────────────────────────
echo ""
echo ">>> [1/6] Installing Python dependencies …"
python3.10 -m pip install --quiet -r requirements.txt 2>&1 | tail -3
echo "    ✓ Python deps installed."

# ── 2. Frontend dependencies ────────────────────────────────────────────────
echo ""
echo ">>> [2/6] Installing frontend dependencies …"
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    cd frontend
    npm install --silent 2>&1 | tail -3
    cd ..
    echo "    ✓ Frontend deps installed."
else
    echo "    ⚠ frontend/package.json not found – skipping."
fi

# ── 3. Run tests ────────────────────────────────────────────────────────────
echo ""
echo ">>> [3/6] Running test suite …"
python3.10 -m pytest tests/ -v --tb=short 2>&1
echo "    ✓ Tests passed."

# ── 4. Run multi-trial experiment (without LLM) ────────────────────────────
echo ""
echo ">>> [4/6] Running multi-trial experiment (non-LLM strategies) …"

python3.10 - <<'PYEOF'
"""
Run non-LLM strategies for the multi-trial experiment.
Produces data/experiment_results.json in the format expected by generate_figures.py.
"""
import json, os, sys, time, random as rng

os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")
sys.path.insert(0, os.path.dirname(os.path.abspath(".")))

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.webster import WebsterController
from backend.algorithms.baseline import FixedTimeController, RandomController, MaxPressureController
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine

STEPS = 3600
WARMUP_STEPS = 600
NUM_TRIALS = 5
CONFIG = "data/grid6.sumocfg"
STRATEGIES = ["fixed", "random", "webster", "maxpressure"]

# If LLM_API_KEY is set, also run LLM strategy
if os.environ.get("LLM_API_KEY"):
    from backend.llm.xiaomi_client import LLMClient
    STRATEGIES.append("llm")
    print("  LLM_API_KEY detected – will also run LLM strategy.")
else:
    print("  No LLM_API_KEY set – running non-LLM strategies only.")

def run_strategy(strategy: str, seed: int = 0) -> dict:
    print(f"\n  [{strategy}] seed={seed}")
    engine = SumoEngine()
    constraint_engine = SignalConstraintEngine()
    coordination = CoordinationEngine()
    phase_directions = {"EW": ["east", "west"], "NS": ["north", "south"]}
    timing_cache = {}

    ctrl_map = {
        "fixed": lambda s: FixedTimeController(),
        "random": lambda s: RandomController(seed=s),
        "webster": lambda s: WebsterController(),
        "maxpressure": lambda s: MaxPressureController(phase_directions=phase_directions),
    }
    controller = ctrl_map[strategy](seed) if strategy in ctrl_map else None
    is_llm = strategy == "llm"
    llm_client = LLMClient() if is_llm else None

    start_time = time.time()
    try:
        engine.start(config_file=CONFIG, extra_args=["-s", str(seed)])
        INTS = engine.intersections

        for step in range(STEPS):
            if not engine.step():
                break

            if step == WARMUP_STEPS:
                for iid in INTS:
                    m = engine.metrics.per_intersection[iid]
                    m.total_wait_time = 0.0
                    m.total_queue_length = 0
                    m.total_vehicle_count = 0
                    m.sample_count = 0
                engine.metrics.total_steps = 0
                engine.metrics.vehicles_departed = 0
                engine.metrics.vehicles_arrived = 0

            if step <= WARMUP_STEPS:
                continue

            if (step - WARMUP_STEPS) % 30 == 0:
                queues = engine.get_all_queue_lengths()

                if is_llm and llm_client:
                    vehicle_counts = engine.get_all_vehicle_counts()
                    all_states = {}
                    for iid in INTS:
                        q = queues.get(iid, {})
                        vc = vehicle_counts.get(iid, {})
                        all_states[iid] = {
                            "vehicle_counts": vc,
                            "queue_lengths": q,
                            "avg_waiting_times": {d: 0 for d in q},
                            "total_vehicles": sum(vc.values()),
                            "time": step,
                            "current_phase": 0,
                        }
                    try:
                        batch_result = llm_client.get_batch_recommendation(all_states)
                        for iid in INTS:
                            pd = batch_result.get(iid, {}).get("phase_durations", {0: 30, 1: 3, 2: 30, 3: 3})
                            timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                    except Exception as e:
                        print(f"    step={step} LLM failed: {e}")
                        for iid in INTS:
                            timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                    try:
                        adj = coordination.compute_adjustments(queues, {})
                        timing_cache = coordination.apply_adjustments(timing_cache, adj)
                    except Exception:
                        pass

                    for iid in INTS:
                        timings = timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                        green_phases = [timings.get(0, 30), timings.get(2, 30)]
                        cycle_len = sum(timings.values())
                        _, _, corrected = constraint_engine.validate(green_phases, cycle_len)
                        if corrected:
                            timings[0] = corrected[0]
                            timings[2] = corrected[1] if len(corrected) > 1 else 30
                        phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                        engine.set_phase(iid, phase, duration=max(timings.get(0, 30), timings.get(2, 30)))

                elif strategy == "maxpressure":
                    for iid in INTS:
                        q = queues.get(iid, {})
                        timings = controller.compute_timing({"EW": 1, "NS": 1}, queue_data=q)
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))
                else:
                    for iid in INTS:
                        q = queues.get(iid, {})
                        ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                        ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                        timings = controller.compute_timing({"EW": ew, "NS": ns})
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))

        metrics = engine.metrics.summary()
        elapsed = time.time() - start_time
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = strategy
        print(f"    done: wait={metrics.get('avg_wait_time',0):.2f}s queue={metrics.get('avg_queue_length',0):.2f} "
              f"tp={metrics.get('throughput',0):.4f} [{elapsed:.0f}s]")
        return metrics
    except Exception as e:
        print(f"    ERROR: {e}")
        import traceback; traceback.print_exc()
        return None
    finally:
        engine.stop()

def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0

def std(vals):
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5

# --- Run trials ---
all_results = {}
summary = {}

print(f"\n{'='*60}")
print(f"  Multi-trial experiment: {NUM_TRIALS} trials × {len(STRATEGIES)} strategies")
print(f"  {STEPS} steps ({WARMUP_STEPS} warm-up)")
print(f"{'='*60}")

for strategy in STRATEGIES:
    trial_metrics = []
    for trial_idx, seed in enumerate(range(NUM_TRIALS)):
        result = run_strategy(strategy, seed=seed)
        if result is not None:
            trial_metrics.append(result)
    all_results[strategy] = trial_metrics

    if trial_metrics:
        metric_keys = ["avg_wait_time", "avg_queue_length", "throughput", "vehicles_arrived"]
        agg = {}
        for key in metric_keys:
            vals = [r.get(key, 0) for r in trial_metrics]
            agg[key] = {"mean": round(mean(vals), 4), "std": round(std(vals), 4)}
        agg["num_trials"] = len(trial_metrics)
        summary[strategy] = agg

# --- Save multi-trial results ---
with open("data/experiment_results_multitrial.json", "w") as f:
    json.dump({"summary": summary, "per_trial": all_results}, f, indent=2)

# --- Save single-run results (format for generate_figures.py) ---
# Use mean of first trial per strategy for the flat format
flat_results = {}
for strategy in STRATEGIES:
    trials = all_results.get(strategy, [])
    if trials:
        r = trials[0]
        flat_results[strategy] = r

with open("data/experiment_results.json", "w") as f:
    json.dump(flat_results, f, indent=2)

# --- Print table ---
print(f"\n{'='*80}")
print(f"{'Strategy':<14} {'Trials':<7} {'Wait(s)':<15} {'Queue':<15} {'Throughput':<15}")
print(f"{'='*80}")
for s in STRATEGIES:
    agg = summary.get(s, {})
    n = agg.get("num_trials", 0)
    w = agg.get("avg_wait_time", {})
    q = agg.get("avg_queue_length", {})
    t = agg.get("throughput", {})
    print(f"{s:<14} {n:<7} {w.get('mean',0):.2f}±{w.get('std',0):.2f}     "
          f"{q.get('mean',0):.2f}±{q.get('std',0):.2f}     "
          f"{t.get('mean',0):.4f}±{t.get('std',0):.4f}")
print(f"{'='*80}")
print("\nResults saved to data/experiment_results.json")
PYEOF

echo "    ✓ Experiment complete."

# ── 5. Generate figures ─────────────────────────────────────────────────────
echo ""
echo ">>> [5/6] Generating figures …"
python3.10 generate_figures.py 2>&1
echo "    ✓ Figures saved to data/fig_*.png"

# ── 6. Compile paper ────────────────────────────────────────────────────────
echo ""
echo ">>> [6/6] Compiling paper …"
if command -v pdflatex &>/dev/null; then
    cd paper
    pdflatex -interaction=nonstopmode main.tex 2>&1 | tail -5
    pdflatex -interaction=nonstopmode main.tex 2>&1 | tail -5  # second pass for refs
    cd ..
    echo "    ✓ Paper compiled → paper/main.pdf"
else
    echo "    ⚠ pdflatex not found – skipping paper compilation."
    echo "      Install with: apt-get install -y texlive-latex-base texlive-latex-extra texlive-fonts-recommended"
fi

echo ""
echo "============================================================"
echo " Reproducibility pipeline complete!"
echo ""
echo " Outputs:"
echo "   • data/experiment_results.json       – flat results for figures"
echo "   • data/experiment_results_multitrial.json – multi-trial stats"
echo "   • data/fig_comparison.png             – bar chart"
echo "   • data/fig_radar.png                  – radar chart"
echo "   • data/fig_table.png                  – summary table"
echo "   • paper/main.pdf                      – compiled paper"
echo ""
echo " To reproduce with LLM strategy:"
echo "   export LLM_API_KEY='your-key'"
echo "   bash reproduce.sh"
echo "============================================================"
