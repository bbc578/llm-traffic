#!/usr/bin/env python3.10
"""Run LLM strategy with DeepSeek Flash API."""
import json, os, sys, time, math

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from backend.simulation.sumo_engine import SumoEngine
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine

STEPS = 3600
WARMUP = 600
NUM_TRIALS = 3
CONFIG = "data/grid6.sumocfg"
OUTPUT = "data/experiment_results.json"
API_KEY = "sk-9a26609800a94022a7d32b58349e2dd1"
API_URL = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = """You are a traffic signal optimizer. Respond ONLY with valid JSON.

Format: {"id": {"phase_durations": {"0": NS_green, "1": 3, "2": EW_green, "3": 3}, "reasoning": "<=30 words"}}
- Phase 0 = NS green, Phase 1 = NS yellow (fixed 3s), Phase 2 = EW green, Phase 3 = EW yellow (fixed 3s)
- Green range: 10-90s. Longer queues → more green for that axis."""

FEW_SHOT = """
Example 1: intersection_1: N:5veh/2q/10w S:4veh/1q/8w E:30veh/12q/45w W:25veh/10q/40w
→ {"intersection_1": {"phase_durations": {"0": 20, "1": 3, "2": 55, "3": 3}, "reasoning": "Heavy east traffic (55veh, 22q) needs extended EW green"}}

Example 2: intersection_2: N:40veh/15q/60w S:35veh/12q/50w E:8veh/3q/15w W:6veh/2q/10w
→ {"intersection_2": {"phase_durations": {"0": 65, "1": 3, "2": 15, "3": 3}, "reasoning": "North queue critical (27q, 60w wait) — prioritize NS green"}}

Example 3: intersection_3: N:20veh/8q/25w S:18veh/7q/22w E:22veh/9q/28w W:19veh/8q/24w
→ {"intersection_3": {"phase_durations": {"0": 30, "1": 3, "2": 30, "3": 3}, "reasoning": "Balanced traffic — equal green split"}}
"""


def call_llm(prompt: str) -> dict:
    """Call DeepSeek Flash API and parse response."""
    resp = requests.post(API_URL, json={
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + FEW_SHOT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.3,
    }, headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, timeout=30)
    
    if resp.status_code != 200:
        raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
    
    content = resp.json()["choices"][0]["message"]["content"]
    # Extract JSON from response
    import re
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        raise Exception(f"No JSON in response: {content[:200]}")
    return json.loads(json_match.group())


def build_prompt(intersections, queues, vehicle_counts, step):
    """Build compact prompt for all intersections."""
    lines = [f"Time: {step}s"]
    for iid in intersections:
        q = queues.get(iid, {})
        vc = vehicle_counts.get(iid, {})
        parts = []
        for d in ["north", "south", "east", "west"]:
            v = vc.get(d, 0)
            ql = q.get(d, 0)
            parts.append(f"{d[0].upper()}:{v}veh/{ql}q")
        lines.append(f"{iid}: {' '.join(parts)}")
    lines.append("Reply JSON only.")
    return "\n".join(lines)


def run_llm_trial(seed):
    """Run one LLM trial."""
    print(f"\n  LLM seed={seed}...", end="", flush=True)
    engine = SumoEngine()
    ce = SignalConstraintEngine()
    coord = CoordinationEngine()
    tc = {}
    latencies = []
    failures = 0
    total_calls = 0

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
                prompt = build_prompt(INTS, queues, vc, step)
                
                total_calls += 1
                t_start = time.time()
                try:
                    result = call_llm(prompt)
                    latencies.append(time.time() - t_start)
                    for iid in INTS:
                        pd = result.get(iid, {}).get("phase_durations", {0: 30, 1: 3, 2: 30, 3: 3})
                        tc[iid] = {int(k): int(v) for k, v in pd.items()}
                except Exception as e:
                    failures += 1
                    print(f" FAIL:{e}", end="", flush=True)
                    for iid in INTS:
                        tc[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                try:
                    adj = coord.compute_adjustments(queues, {})
                    tc = coord.apply_adjustments(tc, adj)
                except:
                    pass

                for iid in INTS:
                    t = tc.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                    gp = [t.get(0, 30), t.get(2, 30)]
                    cl = sum(t.values())
                    _, _, cor = ce.validate(gp, cl)
                    if cor:
                        t[0] = cor[0]
                        t[2] = cor[1] if len(cor) > 1 else 30
                    ph = 0 if t.get(0, 30) >= t.get(2, 30) else 2
                    engine.set_phase(iid, ph, duration=max(t.get(0, 30), t.get(2, 30)))

        metrics = engine.metrics.summary()
        elapsed = time.time() - t0
        metrics["elapsed_seconds"] = round(elapsed, 1)
        metrics["strategy"] = "llm"
        metrics["llm_latency_mean"] = round(sum(latencies)/len(latencies), 3) if latencies else 0
        metrics["llm_latency_p95"] = round(sorted(latencies)[int(len(latencies)*0.95)], 3) if latencies else 0
        metrics["llm_failure_rate"] = round(failures/total_calls, 4) if total_calls else 0
        metrics["llm_total_calls"] = total_calls
        print(f" done {elapsed:.0f}s wait={metrics.get('avg_wait_time',0):.2f} latency={metrics.get('llm_latency_mean',0):.2f}s failures={metrics.get('llm_failure_rate',0):.1%}", flush=True)
        return metrics
    except Exception as e:
        print(f" ERR:{e}", flush=True)
        return None
    finally:
        engine.stop()


def _mean(v): return sum(v)/len(v) if v else 0
def _std(v):
    if len(v)<2: return 0
    m=_mean(v)
    return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))


if __name__ == "__main__":
    # Load existing results
    with open(OUTPUT) as f:
        data = json.load(f)
    
    per_trial = data.get("per_trial", {})
    summary = data.get("summary", {})
    
    # Check if LLM already done
    if "llm" in summary and summary["llm"].get("num_trials", 0) >= NUM_TRIALS:
        print("LLM already done!")
    else:
        trials = per_trial.get("llm", [])
        for trial_idx in range(len(trials), NUM_TRIALS):
            r = run_llm_trial(seed=trial_idx)
            if r:
                trials.append(r)
            per_trial["llm"] = trials
            with open(OUTPUT, "w") as f:
                json.dump({"summary": summary, "per_trial": per_trial}, f, indent=2)
        
        # Aggregate
        if trials:
            mk = ["avg_wait_time", "avg_queue_length", "throughput", "vehicles_arrived"]
            agg = {}
            for k in mk:
                vals = [r.get(k, 0) for r in trials]
                agg[k] = {"mean": round(_mean(vals), 4), "std": round(_std(vals), 4), "display": f"{_mean(vals):.2f}±{_std(vals):.2f}"}
            agg["num_trials"] = len(trials)
            # Add LLM-specific metrics
            lat_mean = [r.get("llm_latency_mean", 0) for r in trials]
            lat_p95 = [r.get("llm_latency_p95", 0) for r in trials]
            fail_rates = [r.get("llm_failure_rate", 0) for r in trials]
            agg["llm_latency_mean"] = round(_mean(lat_mean), 3)
            agg["llm_latency_p95"] = round(_mean(lat_p95), 3)
            agg["llm_failure_rate"] = round(_mean(fail_rates), 4)
            summary["llm"] = agg
        else:
            summary["llm"] = {"num_trials": 0}
        
        with open(OUTPUT, "w") as f:
            json.dump({"summary": summary, "per_trial": per_trial}, f, indent=2)
    
    # Print final table
    print(f"\n{'='*100}")
    print(f"{'Strategy':<14} {'Trials':<8} {'Avg Wait(s)':<22} {'Avg Queue':<22} {'Throughput':<22}")
    print(f"{'='*100}")
    for s in ["fixed", "random", "webster", "maxpressure", "rl", "llm"]:
        a = summary.get(s, {})
        if a.get("num_trials", 0) == 0:
            print(f"{s:<14} 0        FAILED")
            continue
        print(f"{s:<14} {a['num_trials']:<8} {a['avg_wait_time']['display']:<22} {a['avg_queue_length']['display']:<22} {a['throughput']['display']:<22}")
    print(f"{'='*100}")
    
    if "llm" in summary and summary["llm"].get("num_trials", 0) > 0:
        llm = summary["llm"]
        print(f"\nLLM Stats: latency_mean={llm.get('llm_latency_mean',0):.2f}s, latency_p95={llm.get('llm_latency_p95',0):.2f}s, failure_rate={llm.get('llm_failure_rate',0):.1%}")
    print("DONE")
