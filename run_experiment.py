#!/usr/bin/env python3.10
"""
Run 4-strategy comparison experiment: fixed, random, webster, llm.
Outputs JSON results for paper figures.
"""
import json
import os
import sys
import time

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.webster import WebsterController
from backend.algorithms.baseline import FixedTimeController, RandomController
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine
from backend.llm.xiaomi_client import LLMClient

STEPS = 300
CONFIG = "data/grid6.sumocfg"

def run_strategy(strategy: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Running: {strategy}")
    print(f"{'='*60}")

    engine = SumoEngine()
    ctrl_map = {
        "fixed": FixedTimeController(),
        "random": RandomController(seed=42),
        "webster": WebsterController(),
    }
    controller = ctrl_map.get(strategy)
    is_llm = strategy == "llm"
    llm_client = LLMClient() if is_llm else None
    constraint_engine = SignalConstraintEngine()
    coordination = CoordinationEngine()
    timing_cache = {}

    start_time = time.time()

    try:
        engine.start(config_file=CONFIG)
        INTS = engine.intersections
        print(f"  Intersections: {INTS}")

        for step in range(STEPS):
            if not engine.step():
                break

            if step > 0 and step % 30 == 0:
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
                        print(f"  step={step} LLM decisions: {timing_cache}")
                    except Exception as e:
                        print(f"  step={step} LLM FAILED: {e}")
                        for iid in INTS:
                            timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                    # Coordination
                    try:
                        adj = coordination.compute_adjustments(queues, {})
                        timing_cache = coordination.apply_adjustments(timing_cache, adj)
                    except Exception:
                        pass

                    # Constraint + apply
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
                else:
                    for iid in INTS:
                        q = queues[iid]
                        ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                        ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                        timings = controller.compute_timing({"EW": ew, "NS": ns})
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))

        metrics = engine.metrics.summary()
        elapsed = time.time() - start_time
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = strategy
        print(f"  Done: wait={metrics.get('avg_wait_time',0):.2f}s queue={metrics.get('avg_queue_length',0):.2f} elapsed={elapsed:.1f}s")
        return metrics

    except Exception as e:
        print(f"  ERROR: {e}")
        return {"error": str(e), "strategy": strategy}
    finally:
        engine.stop()


if __name__ == "__main__":
    results = {}
    for s in ["fixed", "random", "webster", "llm"]:
        results[s] = run_strategy(s)

    # Save results
    output_path = "data/experiment_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nResults saved to {output_path}")

    # Print comparison table
    print(f"\n{'='*80}")
    print(f"{'Strategy':<12} {'Avg Wait(s)':<14} {'Avg Queue':<12} {'Throughput':<12} {'Elapsed(s)':<10}")
    print(f"{'='*80}")
    for s in ["fixed", "random", "webster", "llm"]:
        r = results.get(s, {})
        print(f"{s:<12} {r.get('avg_wait_time',0):<14.2f} {r.get('avg_queue_length',0):<12.2f} {r.get('throughput',0):<12.4f} {r.get('elapsed_seconds',0):<10.1f}")
