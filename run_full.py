#!/usr/bin/env python3.10
"""
Quick experiment: 3 trials × 3600 steps, run strategies sequentially.
Each trial saves results incrementally.
"""
import json, os, sys, time, math, random as rng

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.webster import WebsterController
from backend.algorithms.baseline import FixedTimeController, RandomController, MaxPressureController
from backend.algorithms.rl_controller import RLController
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine

STEPS = 3600
WARMUP = 600
NUM_TRIALS = 10
CONFIG = "data/grid6.sumocfg"
STRATEGIES = ["fixed", "random", "webster", "maxpressure", "rl"]
OUTPUT = "data/experiment_results.json"

def _mean(v): return sum(v)/len(v) if v else 0
def _std(v):
    if len(v)<2: return 0
    m=_mean(v)
    return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))

def run_one(strategy, seed):
    print(f"\n  {strategy} seed={seed}...", end="", flush=True)
    engine = SumoEngine()
    ce = SignalConstraintEngine()
    coord = CoordinationEngine()
    tc = {}

    ctrl_map = {
        "fixed": lambda: FixedTimeController(),
        "random": lambda: RandomController(seed=seed),
        "webster": lambda: WebsterController(),
        "maxpressure": lambda: MaxPressureController(phase_directions={"EW":["east","west"],"NS":["north","south"]}),
        "rl": lambda: RLController(seed=seed),
    }
    controller = ctrl_map[strategy]() if strategy in ctrl_map else None

    is_llm = strategy == "llm"
    llm = None
    if is_llm:
        from backend.llm.xiaomi_client import LLMClient
        llm = LLMClient()

    try:
        engine.start(config_file=CONFIG, extra_args=["-s", str(seed)])
        INTS = engine.intersections
        t0 = time.time()

        for step in range(STEPS):
            if not engine.step():
                break
            if step == WARMUP:
                for iid in INTS:
                    m = engine.metrics.per_intersection[iid]
                    m.total_wait_time = 0; m.total_queue_length = 0
                    m.total_vehicle_count = 0; m.sample_count = 0
                engine.metrics.total_steps = 0
                engine.metrics.vehicles_departed = 0
                engine.metrics.vehicles_arrived = 0
            if step <= WARMUP:
                continue
            if (step - WARMUP) % 30 == 0:
                queues = engine.get_all_queue_lengths()
                if is_llm:
                    vc = engine.get_all_vehicle_counts()
                    states = {}
                    for iid in INTS:
                        q = queues.get(iid, {})
                        v = vc.get(iid, {})
                        states[iid] = {"vehicle_counts": v, "queue_lengths": q, "avg_waiting_times": {d:0 for d in q}, "total_vehicles": sum(v.values()), "time": step, "current_phase": 0}
                    try:
                        br = llm.get_batch_recommendation(states)
                        for iid in INTS:
                            pd = br.get(iid, {}).get("phase_durations", {0:30,1:3,2:30,3:3})
                            tc[iid] = {int(k):int(v) for k,v in pd.items()}
                    except Exception as e:
                        print(f" LLM_FAIL:{e}", end="", flush=True)
                        for iid in INTS: tc[iid] = {0:30,1:3,2:30,3:3}
                    try:
                        adj = coord.compute_adjustments(queues, {})
                        tc = coord.apply_adjustments(tc, adj)
                    except: pass
                    for iid in INTS:
                        t = tc.get(iid, {0:30,1:3,2:30,3:3})
                        gp = [t.get(0,30), t.get(2,30)]
                        cl = sum(t.values())
                        _, _, cor = ce.validate(gp, cl)
                        if cor: t[0]=cor[0]; t[2]=cor[1] if len(cor)>1 else 30
                        ph = 0 if t.get(0,30)>=t.get(2,30) else 2
                        engine.set_phase(iid, ph, duration=max(t.get(0,30),t.get(2,30)))
                elif strategy in ("maxpressure","rl"):
                    for iid in INTS:
                        q = queues.get(iid, {})
                        t = controller.compute_timing({"EW":1,"NS":1}, queue_data=q)
                        ph = 0 if t[0]>=t[1] else 2
                        engine.set_phase(iid, ph, duration=int(max(t)))
                else:
                    for iid in INTS:
                        q = queues.get(iid, {})
                        ew = max((q.get("east",0)+q.get("west",0))*120, 100)
                        ns = max((q.get("north",0)+q.get("south",0))*120, 100)
                        t = controller.compute_timing({"EW":ew,"NS":ns})
                        ph = 0 if t[0]>=t[1] else 2
                        engine.set_phase(iid, ph, duration=int(max(t)))

        metrics = engine.metrics.summary()
        elapsed = time.time() - t0
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = strategy
        print(f" done {elapsed:.0f}s wait={metrics.get('avg_wait_time',0):.2f}", flush=True)
        return metrics
    except Exception as e:
        print(f" ERR:{e}", flush=True)
        return None
    finally:
        engine.stop()


if __name__ == "__main__":
    all_results = {}
    summary = {}
    # Load existing results if any
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            saved = json.load(f)
            all_results = saved.get("per_trial", {})
            summary = saved.get("summary", {})

    for strategy in STRATEGIES:
        if strategy in summary and summary[strategy].get("num_trials", 0) >= NUM_TRIALS:
            print(f"Skipping {strategy} (already has {summary[strategy]['num_trials']} trials)")
            continue

        print(f"\n{'='*60}\nStrategy: {strategy} ({NUM_TRIALS} trials)\n{'='*60}", flush=True)
        trials = all_results.get(strategy, [])
        for trial_idx in range(len(trials), NUM_TRIALS):
            r = run_one(strategy, seed=trial_idx)
            if r: trials.append(r)
            # Save incrementally
            all_results[strategy] = trials
            with open(OUTPUT, "w") as f:
                json.dump({"summary": {}, "per_trial": all_results}, f, indent=2)

        # Aggregate
        if trials:
            mk = ["avg_wait_time","avg_queue_length","throughput","vehicles_arrived"]
            agg = {}
            for k in mk:
                vals = [r.get(k,0) for r in trials]
                agg[k] = {"mean":round(_mean(vals),4),"std":round(_std(vals),4),"display":f"{_mean(vals):.2f}±{_std(vals):.2f}"}
            agg["num_trials"] = len(trials)
            summary[strategy] = agg
        else:
            summary[strategy] = {"num_trials":0}

        # Save summary
        with open(OUTPUT, "w") as f:
            json.dump({"summary": summary, "per_trial": all_results}, f, indent=2)

    # Print table
    print(f"\n{'='*90}")
    print(f"{'Strategy':<14} {'Trials':<8} {'Avg Wait(s)':<22} {'Avg Queue':<22} {'Throughput':<22}")
    print(f"{'='*90}")
    for s in STRATEGIES:
        a = summary.get(s, {})
        if a.get("num_trials",0)==0:
            print(f"{s:<14} 0        FAILED")
            continue
        print(f"{s:<14} {a['num_trials']:<8} {a['avg_wait_time']['display']:<22} {a['avg_queue_length']['display']:<22} {a['throughput']['display']:<22}")
    print(f"{'='*90}")
    print("DONE")
