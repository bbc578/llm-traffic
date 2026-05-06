"""
Statistical analysis for experiment results.
Computes 95% confidence intervals and paired t-tests between strategies.
"""
import json
import math
import sys
from typing import Dict, List, Tuple


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def confidence_interval(values: List[float], confidence: float = 0.95) -> Tuple[float, float]:
    """95% CI using t-distribution approximation for small samples."""
    n = len(values)
    if n < 2:
        m = mean(values)
        return (m, m)
    m = mean(values)
    se = std(values) / math.sqrt(n)
    # t-value for 95% CI with n-1 df (approximation)
    t_vals = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
              8: 2.365, 9: 2.306, 10: 2.262}
    t = t_vals.get(n, 2.262)  # default to n=10 value
    return (round(m - t * se, 4), round(m + t * se, 4))


def paired_t_test(values_a: List[float], values_b: List[float]) -> Tuple[float, float]:
    """Paired t-test: is mean(A-B) significantly different from 0?
    Returns (t_statistic, p_value_approx).
    """
    n = min(len(values_a), len(values_b))
    if n < 2:
        return (0.0, 1.0)
    diffs = [a - b for a, b in zip(values_a[:n], values_b[:n])]
    d_mean = mean(diffs)
    d_std = std(diffs)
    if d_std == 0:
        return (float('inf') if d_mean != 0 else 0.0, 0.0 if d_mean != 0 else 1.0)
    t_stat = d_mean / (d_std / math.sqrt(n))
    # Rough p-value approximation for small df
    df = n - 1
    t_abs = abs(t_stat)
    if t_abs > 4.0:
        p = 0.001
    elif t_abs > 3.0:
        p = 0.01
    elif t_abs > 2.5:
        p = 0.02
    elif t_abs > 2.0:
        p = 0.05
    elif t_abs > 1.5:
        p = 0.1
    else:
        p = 0.5
    return (round(t_stat, 4), round(p, 4))


def analyze_results(filepath: str):
    """Analyze experiment results and print statistical summary."""
    with open(filepath) as f:
        data = json.load(f)

    per_trial = data.get("per_trial", {})
    strategies = list(per_trial.keys())

    print("\n" + "=" * 80)
    print("STATISTICAL ANALYSIS")
    print("=" * 80)

    # Extract per-trial metrics
    metrics = {}
    for strat in strategies:
        trials = per_trial[strat]
        metrics[strat] = {
            "wait": [t.get("avg_wait_time", 0) for t in trials],
            "queue": [t.get("avg_queue_length", 0) for t in trials],
            "throughput": [t.get("throughput", 0) for t in trials],
        }

    # Confidence intervals
    print("\n--- 95% Confidence Intervals ---")
    for strat in strategies:
        m = metrics[strat]
        wait_ci = confidence_interval(m["wait"])
        queue_ci = confidence_interval(m["queue"])
        tp_ci = confidence_interval(m["throughput"])
        print(f"\n{strat}:")
        print(f"  Wait:    {mean(m['wait']):.2f}  95% CI [{wait_ci[0]:.2f}, {wait_ci[1]:.2f}]")
        print(f"  Queue:   {mean(m['queue']):.2f}  95% CI [{queue_ci[0]:.2f}, {queue_ci[1]:.2f}]")
        print(f"  Through: {mean(m['throughput']):.4f}  95% CI [{tp_ci[0]:.4f}, {tp_ci[1]:.4f}]")

    # Paired t-tests: compare LLM to each baseline
    llm_key = "llm" if "llm" in strategies else None
    if llm_key:
        print("\n--- Paired t-tests (LLM vs baselines) ---")
        for strat in strategies:
            if strat == llm_key:
                continue
            for metric_name in ["wait", "queue", "throughput"]:
                t_stat, p_val = paired_t_test(
                    metrics[llm_key][metric_name],
                    metrics[strat][metric_name]
                )
                sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else "n.s."
                print(f"  LLM vs {strat} ({metric_name}): t={t_stat:.3f}, p={p_val:.4f} {sig}")

    # Improvement percentages
    print("\n--- Improvement over baselines ---")
    for strat in strategies:
        if strat == llm_key:
            continue
        for metric_name in ["wait", "queue"]:
            base_val = mean(metrics[strat][metric_name])
            llm_val = mean(metrics[llm_key][metric_name]) if llm_key else 0
            if base_val > 0 and llm_key:
                improvement = (base_val - llm_val) / base_val * 100
                print(f"  LLM vs {strat} ({metric_name}): {improvement:+.1f}%")

    return metrics


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "data/experiment_results.json"
    analyze_results(filepath)
