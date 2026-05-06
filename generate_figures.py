#!/usr/bin/env python3.10
"""
Generate paper figures from experiment results.
"""
import json
import os
import sys

os.environ["SUMO_HOME"] = "/usr/share/sumo"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# Load experiment results
with open("data/experiment_results.json") as f:
    results = json.load(f)

strategies = ["fixed", "random", "webster", "llm"]
labels = ["Fixed Time", "Random", "Webster", "LLM+Coord"]
colors = ['#e74c3c', '#f39c12', '#27ae60', '#3498db']

# Extract metrics
wait_times = [results[s]["avg_wait_time"] for s in strategies]
queue_lengths = [results[s]["avg_queue_length"] for s in strategies]
throughputs = [results[s].get("throughput", 0) for s in strategies]
vehicles_arrived = [results[s].get("vehicles_arrived", 0) for s in strategies]

# Figure 1: Bar chart comparison (avg wait + avg queue)
fig, axes = plt.subplots(1, 3, figsize=(14, 5))

# Wait time
bars = axes[0].bar(labels, wait_times, color=colors, edgecolor='white', linewidth=1.5)
axes[0].set_ylabel('Average Wait Time (s)', fontsize=12)
axes[0].set_title('(a) Average Waiting Time', fontsize=13, fontweight='bold')
for bar, val in zip(bars, wait_times):
    axes[0].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5,
                f'{val:.1f}s', ha='center', va='bottom', fontsize=10, fontweight='bold')
axes[0].set_ylim(0, max(wait_times) * 1.2)
axes[0].grid(axis='y', alpha=0.3)

# Queue length
bars = axes[1].bar(labels, queue_lengths, color=colors, edgecolor='white', linewidth=1.5)
axes[1].set_ylabel('Average Queue Length (vehicles)', fontsize=12)
axes[1].set_title('(b) Average Queue Length', fontsize=13, fontweight='bold')
for bar, val in zip(bars, queue_lengths):
    axes[1].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.2,
                f'{val:.1f}', ha='center', va='bottom', fontsize=10, fontweight='bold')
axes[1].set_ylim(0, max(queue_lengths) * 1.2)
axes[1].grid(axis='y', alpha=0.3)

# Vehicles arrived
bars = axes[2].bar(labels, vehicles_arrived, color=colors, edgecolor='white', linewidth=1.5)
axes[2].set_ylabel('Total Vehicles Arrived', fontsize=12)
axes[2].set_title('(c) Throughput', fontsize=13, fontweight='bold')
for bar, val in zip(bars, vehicles_arrived):
    axes[2].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                f'{val}', ha='center', va='bottom', fontsize=10, fontweight='bold')
axes[2].set_ylim(0, max(max(vehicles_arrived) * 1.2, 1))
axes[2].grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('data/fig_comparison.png', dpi=200, bbox_inches='tight')
print("Saved: data/fig_comparison.png")

# Figure 2: Radar chart
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

# Normalize metrics for radar (lower is better for wait/queue, higher for throughput)
def normalize(values, invert=False):
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    if invert:
        return [(mx - v) / (mx - mn) for v in values]
    return [(v - mn) / (mx - mn) for v in values]

metrics_for_radar = {
    'Wait Time': normalize(wait_times, invert=True),
    'Queue Length': normalize(queue_lengths, invert=True),
    'Throughput': normalize(vehicles_arrived, invert=False),
}

categories = list(metrics_for_radar.keys())
N = len(categories)
angles = [n / float(N) * 2 * np.pi for n in range(N)]
angles += angles[:1]

for i, (strategy, label) in enumerate(zip(strategies, labels)):
    values = [metrics_for_radar[cat][i] for cat in categories]
    values += values[:1]
    ax.plot(angles, values, 'o-', linewidth=2, label=label, color=colors[i])
    ax.fill(angles, values, alpha=0.1, color=colors[i])

ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories, fontsize=12)
ax.set_ylim(0, 1.1)
ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=11)
ax.set_title('Strategy Performance Comparison', fontsize=14, fontweight='bold', pad=20)

plt.savefig('data/fig_radar.png', dpi=200, bbox_inches='tight')
print("Saved: data/fig_radar.png")

# Figure 3: Per-intersection heatmap for LLM strategy
# (Shows queue lengths per intersection from experiment data)
fig, ax = plt.subplots(figsize=(10, 6))

# Create summary table
cell_text = []
for s in strategies:
    r = results[s]
    row = [
        f"{r['avg_wait_time']:.1f}",
        f"{r['avg_queue_length']:.1f}",
        str(r.get('vehicles_arrived', 0)),
        f"{r.get('elapsed_seconds', 0):.0f}",
    ]
    cell_text.append(row)

table = ax.table(
    cellText=cell_text,
    rowLabels=labels,
    colLabels=['Avg Wait (s)', 'Avg Queue', 'Vehicles Arrived', 'Runtime (s)'],
    loc='center',
    cellLoc='center',
)
table.auto_set_font_size(False)
table.set_fontsize(11)
table.scale(1.2, 1.8)

# Color rows by strategy
for i, color in enumerate(colors):
    for j in range(4):
        table[i+1, j].set_facecolor(color + '33')

ax.axis('off')
ax.set_title('Experiment Results Summary (300 steps, 6 intersections)', fontsize=14, fontweight='bold', pad=20)

plt.savefig('data/fig_table.png', dpi=200, bbox_inches='tight')
print("Saved: data/fig_table.png")

print("\nAll figures generated.")
