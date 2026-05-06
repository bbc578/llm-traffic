#!/usr/bin/env python3.10
"""
Ablation + scalability experiment.
Tests: LLM-only, LLM+Constraint, LLM+Coord on both grid6 and grid4x3.
Also runs baseline comparisons (fixed, webster) on both networks.
"""
import json
import os
import sys
import time

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.webster import WebsterController
from backend.algorithms.baseline import FixedTimeController
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine
from backend.llm.xiaomi_client import LLMClient

STEPS = 300

def run_experiment(strategy: str, config: str, label: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    engine = SumoEngine()
    llm_client = LLMClient()
    constraint = SignalConstraintEngine()
    coordination = CoordinationEngine()
    webster = WebsterController()
    fixed = FixedTimeController()
    timing_cache = {}

    # Parse strategy flags
    use_llm = strategy.startswith("llm")
    use_constraint = "constraint" in strategy or strategy == "llm_full"
    use_coord = "coord" in strategy or strategy == "llm_full"
    is_baseline = strategy in ("fixed", "webster")

    start_time = time.time()
    llm_call_count = 0
    llm_total_time = 0

    try:
        engine.start(config_file=config)
        INTS = engine.intersections
        print(f"  Intersections ({len(INTS)}): {INTS}")

        for step in range(STEPS):
            if not engine.step():
                break

            if step > 0 and step % 30 == 0:
                queues = engine.get_all_queue_lengths()

                if is_baseline:
                    if strategy == "webster":
                        for iid in INTS:
                            q = queues[iid]
                            ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                            ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                            timings = webster.compute_timing({"EW": ew, "NS": ns})
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))
                    elif strategy == "fixed":
                        for iid in INTS:
                            engine.set_phase(iid, 0, duration=30)
                else:
                    # LLM-based strategies
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

                    llm_start = time.time()
                    try:
                        batch_result = llm_client.get_batch_recommendation(all_states)
                        for iid in INTS:
                            pd = batch_result.get(iid, {}).get("phase_durations", {0: 30, 1: 3, 2: 30, 3: 3})
                            timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        llm_call_count += 1
                        llm_total_time += time.time() - llm_start
                    except Exception as e:
                        print(f"  step={step} LLM FAILED: {e}")
                        for iid in INTS:
                            timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                    # Coordination (only if enabled)
                    if use_coord:
                        try:
                            adj = coordination.compute_adjustments(queues, {})
                            timing_cache = coordination.apply_adjustments(timing_cache, adj)
                        except Exception:
                            pass

                    # Constraint (only if enabled)
                    for iid in INTS:
                        timings = timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})

                        if use_constraint:
                            green_phases = [timings.get(0, 30), timings.get(2, 30)]
                            cycle_len = sum(timings.values())
                            _, _, corrected = constraint.validate(green_phases, cycle_len)
                            if corrected:
                                timings[0] = corrected[0]
                                timings[2] = corrected[1] if len(corrected) > 1 else 30

                        phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                        engine.set_phase(iid, phase, duration=max(timings.get(0, 30), timings.get(2, 30)))

        metrics = engine.metrics.summary()
        elapsed = time.time() - start_time
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = strategy
        metrics["label"] = label
        metrics["llm_calls"] = llm_call_count
        metrics["llm_avg_latency"] = round(llm_total_time / max(llm_call_count, 1), 2)
        metrics["num_intersections"] = len(INTS)

        print(f"  Done: wait={metrics.get('avg_wait_time',0):.2f}s queue={metrics.get('avg_queue_length',0):.2f} "
              f"throughput={metrics.get('throughput',0):.4f} elapsed={elapsed:.1f}s "
              f"LLM_calls={llm_call_count} LLM_avg={metrics['llm_avg_latency']:.1f}s")
        return metrics

    except Exception as e:
        print(f"  ERROR: {e}")
        return {"error": str(e), "strategy": strategy, "label": label}
    finally:
        engine.stop()


if __name__ == "__main__":
    results = {}

    # ── Grid6 (3×2, 6 intersections) ──
    grid6_config = "data/grid6.sumocfg"
    grid6_experiments = [
        ("fixed", "Fixed (baseline)"),
        ("webster", "Webster (baseline)"),
        ("llm", "LLM only"),
        ("llm+constraint", "LLM + Constraint"),
        ("llm_full", "LLM + Constraint + Coord"),
    ]

    for strategy, label in grid6_experiments:
        key = f"grid6_{strategy}"
        results[key] = run_experiment(strategy, grid6_config, f"Grid6: {label}")

    # ── Grid4x3 (4×3, 12 intersections) ──
    grid4x3_config = "data/grid4x3.sumocfg"
    grid4x3_experiments = [
        ("fixed", "Fixed (baseline)"),
        ("webster", "Webster (baseline)"),
        ("llm_full", "LLM + Constraint + Coord"),
    ]

    for strategy, label in grid4x3_experiments:
        key = f"grid4x3_{strategy}"
        results[key] = run_experiment(strategy, grid4x3_config, f"Grid4x3: {label}")

    # Save
    output_path = "data/ablation_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nResults saved to {output_path}")

    # ── Print tables ──
    print(f"\n{'='*90}")
    print("ABLATION STUDY (Grid6, 6 intersections)")
    print(f"{'='*90}")
    print(f"{'Strategy':<30} {'Wait(s)':<10} {'Queue':<10} {'Throughput':<12} {'LLM Lat(s)':<12}")
    print(f"{'-'*90}")
    for strategy, label in grid6_experiments:
        key = f"grid6_{strategy}"
        r = results.get(key, {})
        print(f"{label:<30} {r.get('avg_wait_time',0):<10.2f} {r.get('avg_queue_length',0):<10.2f} "
              f"{r.get('throughput',0):<12.4f} {r.get('llm_avg_latency',0):<12.1f}")

    print(f"\n{'='*90}")
    print("SCALABILITY (Grid4x3, 12 intersections)")
    print(f"{'='*90}")
    print(f"{'Strategy':<30} {'Wait(s)':<10} {'Queue':<10} {'Throughput':<12} {'LLM Lat(s)':<12}")
    print(f"{'-'*90}")
    for strategy, label in grid4x3_experiments:
        key = f"grid4x3_{strategy}"
        r = results.get(key, {})
        print(f"{label:<30} {r.get('avg_wait_time',0):<10.2f} {r.get('avg_queue_length',0):<10.2f} "
              f"{r.get('throughput',0):<12.4f} {r.get('llm_avg_latency',0):<12.1f}")
