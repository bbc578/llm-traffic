#!/usr/bin/env python3.10
"""
Multi-trial experiment runner.

Runs each strategy 10 times with different random seeds, 3600-step
simulation with 600-step warm-up (metrics only collected after warm-up).
Reports mean ± std across trials.
"""
import json
import os
import sys
import time
import math
import random as rng

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.webster import WebsterController
from backend.algorithms.baseline import (
    FixedTimeController,
    RandomController,
    MaxPressureController,
)
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine
from backend.llm.xiaomi_client import LLMClient

# ---------------------------------------------------------------------------
# Experiment configuration
# ---------------------------------------------------------------------------
STEPS = 3600
WARMUP_STEPS = 600
NUM_TRIALS = 5
CONFIG = "data/grid6.sumocfg"
STRATEGIES = ["fixed", "random", "webster", "maxpressure", "llm"]


# ---------------------------------------------------------------------------
# Single-trial runner
# ---------------------------------------------------------------------------
def run_strategy(strategy: str, seed: int = 0) -> dict:
    """Run one trial of *strategy* with the given RNG *seed*.

    Returns metrics dict or None on failure.
    """
    print(f"\n{'='*60}")
    print(f"Running: {strategy}  (seed={seed})")
    print(f"{'='*60}")

    engine = SumoEngine()
    constraint_engine = SignalConstraintEngine()
    coordination = CoordinationEngine()
    timing_cache = {}

    # --- Controller setup ------------------------------------------------
    ctrl_map = {
        "fixed": lambda s: FixedTimeController(),
        "random": lambda s: RandomController(seed=s),
        "webster": lambda s: WebsterController(),
        "maxpressure": lambda s: MaxPressureController(
            phase_directions={
                "EW": ["east", "west"],
                "NS": ["north", "south"],
            }
        ),
    }
    controller = ctrl_map[strategy](seed) if strategy in ctrl_map else None
    is_llm = strategy == "llm"
    llm_client = LLMClient() if is_llm else None

    # --- Phase directions (for non-LLM strategies) ----------------------
    phase_directions = {
        "EW": ["east", "west"],
        "NS": ["north", "south"],
    }

    start_time = time.time()

    try:
        # Pass the seed to SUMO so each trial gets different vehicle insertion
        engine.start(config_file=CONFIG, extra_args=["-s", str(seed)])
        INTS = engine.intersections
        print(f"  Intersections: {INTS}")

        for step in range(STEPS):
            if not engine.step():
                break

            # --- Discard warm-up metrics ----------------------------------
            if step == WARMUP_STEPS:
                # Reset all accumulated metrics so only post-warm-up counts
                for iid in INTS:
                    m = engine.metrics.per_intersection[iid]
                    m.total_wait_time = 0.0
                    m.total_queue_length = 0
                    m.total_vehicle_count = 0
                    m.sample_count = 0
                engine.metrics.total_steps = 0
                engine.metrics.vehicles_departed = 0
                engine.metrics.vehicles_arrived = 0
                print(f"  [warm-up complete at step {WARMUP_STEPS}]")

            if step <= WARMUP_STEPS:
                continue  # don't make control decisions during warm-up

            # --- Signal control every 30 post-warm-up steps ---------------
            if (step - WARMUP_STEPS) % 30 == 0:
                queues = engine.get_all_queue_lengths()

                if is_llm and llm_client:
                    # LLM strategy (unchanged logic)
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
                            pd = batch_result.get(iid, {}).get(
                                "phase_durations", {0: 30, 1: 3, 2: 30, 3: 3}
                            )
                            timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        print(f"  step={step} LLM decisions: {timing_cache}")
                    except Exception as e:
                        print(f"  step={step} LLM FAILED: {e}")
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
                        engine.set_phase(
                            iid, phase, duration=max(timings.get(0, 30), timings.get(2, 30))
                        )
                elif strategy == "maxpressure":
                    # MaxPressure: use raw queue lengths for pressure calc
                    for iid in INTS:
                        q = queues.get(iid, {})
                        timings = controller.compute_timing(
                            {"EW": 1, "NS": 1},
                            queue_data=q,
                        )
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))
                else:
                    # Baseline strategies: fixed, random, webster
                    for iid in INTS:
                        q = queues.get(iid, {})
                        ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                        ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                        timings = controller.compute_timing({"EW": ew, "NS": ns})
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))

        # --- Collect results ---------------------------------------------
        metrics = engine.metrics.summary()
        elapsed = time.time() - start_time
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = strategy
        print(
            f"  Done: wait={metrics.get('avg_wait_time',0):.2f}s "
            f"queue={metrics.get('avg_queue_length',0):.2f} "
            f"throughput={metrics.get('throughput',0):.4f} "
            f"elapsed={elapsed:.1f}s"
        )
        return metrics

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        return None
    finally:
        engine.stop()


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------
def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _std(values):
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def format_stat(mean: float, std: float, decimals: int = 2) -> str:
    """Format a metric as 'mean±std'."""
    return f"{mean:.{decimals}f}±{std:.{decimals}f}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    seeds = list(range(NUM_TRIALS))
    all_results: dict = {}          # strategy -> list of per-trial metric dicts
    summary: dict = {}              # strategy -> aggregated mean±std strings

    print(f"\n{'#'*60}")
    print(f"# Multi-trial experiment: {NUM_TRIALS} trials × {len(STRATEGIES)} strategies")
    print(f"# Simulation: {STEPS} steps, warm-up: {WARMUP_STEPS} steps")
    print(f"{'#'*60}")

    for strategy in STRATEGIES:
        trial_results = []
        for trial_idx, seed in enumerate(seeds):
            result = run_strategy(strategy, seed=seed)
            if result is not None:
                trial_results.append(result)
            else:
                print(f"  [!] Trial {trial_idx} for '{strategy}' failed – skipped")

        all_results[strategy] = trial_results

        # Aggregate across trials
        if trial_results:
            metric_keys = ["avg_wait_time", "avg_queue_length", "throughput", "vehicles_arrived"]
            agg = {}
            for key in metric_keys:
                vals = [r.get(key, 0) for r in trial_results]
                agg[key] = {
                    "mean": round(_mean(vals), 4),
                    "std": round(_std(vals), 4),
                    "display": format_stat(_mean(vals), _std(vals)),
                }
            agg["num_trials"] = len(trial_results)
            summary[strategy] = agg
        else:
            summary[strategy] = {"num_trials": 0, "error": "all trials failed"}

    # --- Save results ----------------------------------------------------
    output_path = "data/experiment_results.json"
    with open(output_path, "w") as f:
        json.dump(
            {"summary": summary, "per_trial": all_results},
            f,
            indent=2,
        )
    print(f"\n\nResults saved to {output_path}")

    # --- Print comparison table ------------------------------------------
    print(f"\n{'='*90}")
    print(
        f"{'Strategy':<14} {'Trials':<8} {'Avg Wait(s)':<22} {'Avg Queue':<22} "
        f"{'Throughput':<22}"
    )
    print(f"{'='*90}")
    for s in STRATEGIES:
        agg = summary.get(s, {})
        if agg.get("num_trials", 0) == 0:
            print(f"{s:<14} {'0':<8} {'FAILED':<22} {'FAILED':<22} {'FAILED':<22}")
            continue
        wait_s = agg.get("avg_wait_time", {}).get("display", "N/A")
        queue_s = agg.get("avg_queue_length", {}).get("display", "N/A")
        tp_s = agg.get("throughput", {}).get("display", "N/A")
        print(f"{s:<14} {agg['num_trials']:<8} {wait_s:<22} {queue_s:<22} {tp_s:<22}")
    print(f"{'='*90}")
