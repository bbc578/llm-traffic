#!/usr/bin/env python3
"""
Run LLM strategy 10 trials for llm-traffic experiment.
"""
import json, os, sys, time, math, random as rng

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, "/root/llm-traffic")

from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine

STEPS = 3600
WARMUP = 600
NUM_TRIALS = 10
CONFIG = "/root/llm-traffic/data/grid6.sumocfg"
OUTPUT = "/root/llm-traffic/data/experiment_results.json"

def _mean(v): return sum(v)/len(v) if v else 0
def _std(v):
    if len(v)<2: return 0
    m=_mean(v)
    return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))

def run_one(seed):
    print(f"\n  LLM seed={seed}...", end="", flush=True)
    engine = SumoEngine()
    ce = SignalConstraintEngine()
    coord = CoordinationEngine()
    tc = {}
    
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
        
        metrics = engine.metrics.summary()
        elapsed = time.time() - t0
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = "llm"
        print(f" done {elapsed:.0f}s wait={metrics.get('avg_wait_time',0):.2f}", flush=True)
        return metrics
    except Exception as e:
        print(f" ERR:{e}", flush=True)
        return None
    finally:
        engine.stop()

if __name__ == "__main__":
    # Load existing results
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            saved = json.load(f)
            all_results = saved.get("per_trial", {})
            summary = saved.get("summary", {})
    else:
        all_results = {}
        summary = {}
    
    # Check if LLM already has enough trials
    existing = all_results.get("llm", [])
    if len(existing) >= NUM_TRIALS:
        print(f"LLM already has {len(existing)} trials, skipping")
    else:
        print(f"\n{'='*60}\nStrategy: LLM ({NUM_TRIALS} trials)\n{'='*60}", flush=True)
        trials = existing
        for trial_idx in range(len(trials), NUM_TRIALS):
            r = run_one(seed=trial_idx)
            if r: trials.append(r)
            all_results["llm"] = trials
            with open(OUTPUT, "w") as f:
                json.dump({"summary": summary, "per_trial": all_results}, f, indent=2)
    
    # Aggregate LLM
    trials = all_results.get("llm", [])
    if trials:
        mk = ["avg_wait_time","avg_queue_length","throughput","vehicles_arrived"]
        agg = {}
        for k in mk:
            vals = [r.get(k,0) for r in trials]
            agg[k] = {"mean":round(_mean(vals),4),"std":round(_std(vals),4),"display":f"{_mean(vals):.2f}±{_std(vals):.2f}"}
        agg["num_trials"] = len(trials)
        summary["llm"] = agg
    
    # Save final
    with open(OUTPUT, "w") as f:
        json.dump({"summary": summary, "per_trial": all_results}, f, indent=2)
    
    # Print all results
    print(f"\n{'='*90}")
    print(f"{'Strategy':<14} {'Trials':<8} {'Avg Wait(s)':<22} {'Avg Queue':<22} {'Throughput':<22}")
    print(f"{'='*90}")
    for s in ["fixed","random","webster","maxpressure","rl","llm"]:
        a = summary.get(s, {})
        if a.get("num_trials",0)==0:
            print(f"{s:<14} 0        FAILED")
            continue
        print(f"{s:<14} {a['num_trials']:<8} {a['avg_wait_time']['display']:<22} {a['avg_queue_length']['display']:<22} {a['throughput']['display']:<22}")
    print(f"{'='*90}")
    print("DONE")
