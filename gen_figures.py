#!/usr/bin/env python3
"""Generate SCI-quality figures for the paper."""
import json, math, statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from itertools import combinations

plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 13,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 9,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'axes.spines.top': False,
    'axes.spines.right': False,
})

d = json.load(open('data/experiment_results.json'))
summary = d['summary']
per = d['per_trial']

strategies = ['fixed', 'random', 'webster', 'maxpressure', 'rl', 'llm']
labels = ['Fixed', 'Random', 'Webster', 'MaxPress', 'DQN', 'LLM']
colors = ['#c0392b', '#e67e22', '#2980b9', '#8e44ad', '#27ae60', '#e91e63']
intersections = ['A0', 'A1', 'B0', 'B1', 'C0', 'C1']

# ============================================================
# Fig 1: Box plot — wait time distribution across 10 trials
# ============================================================
fig1, axes1 = plt.subplots(1, 3, figsize=(14, 4.2))
metrics = ['avg_wait_time', 'avg_queue_length', 'throughput']
ylabels = ['Average Waiting Time (s)', 'Average Queue Length', 'Throughput (veh/step)']

for ax, metric, ylabel in zip(axes1, metrics, ylabels):
    data = [[t[metric] for t in per[s]] for s in strategies]
    bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                    medianprops=dict(color='black', linewidth=1.5),
                    whiskerprops=dict(linewidth=1),
                    capprops=dict(linewidth=1),
                    flierprops=dict(marker='o', markersize=4, markerfacecolor='gray'))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
    ax.set_xticklabels(labels, rotation=30, ha='right')
    ax.set_ylabel(ylabel)
    if metric == 'throughput':
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.3f'))

fig1.tight_layout()
fig1.savefig('paper/fig_boxplot.png')
print('fig_boxplot.png saved')
plt.close()

# ============================================================
# Fig 2: Per-intersection grouped bar chart (wait time)
# ============================================================
fig2, ax2 = plt.subplots(figsize=(10, 5))
x = np.arange(len(intersections))
n = len(strategies)
width = 0.12

for i, (s, label, color) in enumerate(zip(strategies, labels, colors)):
    means = [statistics.mean([t['per_intersection'][loc]['avg_wait_time'] for t in per[s]]) for loc in intersections]
    stds = [statistics.stdev([t['per_intersection'][loc]['avg_wait_time'] for t in per[s]]) if len(per[s]) > 1 else 0 for loc in intersections]
    bars = ax2.bar(x + i * width - (n-1)*width/2, means, width, yerr=stds,
                   label=label, color=color, alpha=0.85, capsize=2, linewidth=0.5,
                   edgecolor='white')

ax2.set_xlabel('Intersection')
ax2.set_ylabel('Average Waiting Time (s)')
ax2.set_xticks(x)
ax2.set_xticklabels(intersections)
ax2.legend(ncol=3, loc='upper left', framealpha=0.9)
fig2.tight_layout()
fig2.savefig('paper/fig_per_intersection.png')
print('fig_per_intersection.png saved')
plt.close()

# ============================================================
# Fig 3: Per-intersection grouped bar chart (queue length)
# ============================================================
fig3, ax3 = plt.subplots(figsize=(10, 5))

for i, (s, label, color) in enumerate(zip(strategies, labels, colors)):
    means = [statistics.mean([t['per_intersection'][loc]['avg_queue_length'] for t in per[s]]) for loc in intersections]
    stds = [statistics.stdev([t['per_intersection'][loc]['avg_queue_length'] for t in per[s]]) if len(per[s]) > 1 else 0 for loc in intersections]
    ax3.bar(x + i * width - (n-1)*width/2, means, width, yerr=stds,
            label=label, color=color, alpha=0.85, capsize=2, linewidth=0.5,
            edgecolor='white')

ax3.set_xlabel('Intersection')
ax3.set_ylabel('Average Queue Length')
ax3.set_xticks(x)
ax3.set_xticklabels(intersections)
ax3.legend(ncol=3, loc='upper left', framealpha=0.9)
fig3.tight_layout()
fig3.savefig('paper/fig_per_intersection_queue.png')
print('fig_per_intersection_queue.png saved')
plt.close()

# ============================================================
# Fig 4: Pairwise significance heatmap (throughput)
# ============================================================
fig4, ax4 = plt.subplots(figsize=(6, 5))
n_s = len(strategies)
p_matrix = np.ones((n_s, n_s))
t_matrix = np.zeros((n_s, n_s))

for i, s1 in enumerate(strategies):
    for j, s2 in enumerate(strategies):
        if i == j:
            continue
        d1 = [t['throughput'] for t in per[s1]]
        d2 = [t['throughput'] for t in per[s2]]
        diff = [a - b for a, b in zip(d1, d2)]
        d_mean = statistics.mean(diff)
        d_std = statistics.stdev(diff)
        n = len(diff)
        t_stat = d_mean / (d_std / math.sqrt(n)) if d_std > 0 else 0
        # Approximate p-value using t-distribution (df=n-1)
        # Use a simple approximation
        df = n - 1
        # Two-tailed p-value approximation
        x = df / (df + t_stat**2)
        p_val = 0.5 * x ** (df/2) if abs(t_stat) > 0 else 1.0
        # Clamp
        p_val = max(min(p_val, 1.0), 1e-10)
        p_matrix[i][j] = p_val
        t_matrix[i][j] = t_stat

# Use log scale for p-values
log_p = -np.log10(p_matrix + 1e-20)
np.fill_diagonal(log_p, 0)

im = ax4.imshow(log_p, cmap='YlOrRd', aspect='auto')
ax4.set_xticks(range(n_s))
ax4.set_yticks(range(n_s))
ax4.set_xticklabels(labels, rotation=45, ha='right')
ax4.set_yticklabels(labels)
ax4.set_title('Statistical Significance (Throughput)\n$-\\log_{10}(p)$, higher = more significant')

# Annotate
for i in range(n_s):
    for j in range(n_s):
        if i == j:
            ax4.text(j, i, '—', ha='center', va='center', fontsize=9)
        else:
            p = p_matrix[i][j]
            stars = '***' if p < 0.001 else ('**' if p < 0.01 else ('*' if p < 0.05 else 'ns'))
            ax4.text(j, i, f'{p:.1e}\n{stars}', ha='center', va='center', fontsize=7,
                     color='white' if log_p[i][j] > 5 else 'black')

plt.colorbar(im, ax=ax4, label='$-\\log_{10}(p)$', shrink=0.8)
fig4.tight_layout()
fig4.savefig('paper/fig_significance.png')
print('fig_significance.png saved')
plt.close()

# ============================================================
# Fig 5: Wait vs Throughput scatter with error bars
# ============================================================
fig5, ax5 = plt.subplots(figsize=(7, 5.5))

for s, label, color in zip(strategies, labels, colors):
    w_mean = summary[s]['avg_wait_time']['mean']
    w_std = summary[s]['avg_wait_time']['std']
    t_mean = summary[s]['throughput']['mean']
    t_std = summary[s]['throughput']['std']
    ax5.errorbar(w_mean, t_mean, xerr=w_std, yerr=t_std,
                 fmt='o', color=color, markersize=10, capsize=4,
                 linewidth=1.5, label=label, markeredgecolor='white',
                 markeredgewidth=0.8)

ax5.set_xlabel('Average Waiting Time (s)')
ax5.set_ylabel('Throughput (veh/step)')
ax5.legend(loc='upper right', framealpha=0.9)

# Add Pareto front annotation
ax5.annotate('Pareto front', xy=(120, 0.092), xytext=(160, 0.105),
             arrowprops=dict(arrowstyle='->', color='gray', lw=1),
             fontsize=9, color='gray')
ax5.plot([120, 127], [0.092, 0.115], '--', color='gray', alpha=0.5, linewidth=1)

fig5.tight_layout()
fig5.savefig('paper/fig_tradeoff.png')
print('fig_tradeoff.png saved')
plt.close()

# ============================================================
# Fig 6: Per-intersection performance heatmap (wait time)
# ============================================================
fig6, ax6 = plt.subplots(figsize=(8, 4))
matrix = np.zeros((n_s, len(intersections)))
for i, s in enumerate(strategies):
    for j, loc in enumerate(intersections):
        matrix[i][j] = statistics.mean([t['per_intersection'][loc]['avg_wait_time'] for t in per[s]])

im6 = ax6.imshow(matrix, cmap='RdYlGn_r', aspect='auto')
ax6.set_xticks(range(len(intersections)))
ax6.set_yticks(range(n_s))
ax6.set_xticklabels(intersections)
ax6.set_yticklabels(labels)
ax6.set_title('Average Waiting Time per Intersection (s)')

for i in range(n_s):
    for j in range(len(intersections)):
        ax6.text(j, i, f'{matrix[i][j]:.0f}', ha='center', va='center', fontsize=9,
                 color='white' if matrix[i][j] > 200 else 'black')

plt.colorbar(im6, ax=ax6, label='Waiting Time (s)', shrink=0.8)
fig6.tight_layout()
fig6.savefig('paper/fig_heatmap.png')
print('fig_heatmap.png saved')
plt.close()

# ============================================================
# Fig 7: Improved comparison bar chart (paper-ready)
# ============================================================
fig7, axes7 = plt.subplots(1, 3, figsize=(14, 4.5))
metrics_main = ['avg_wait_time', 'avg_queue_length', 'throughput']
ylabels_main = ['(a) Average Waiting Time (s)', '(b) Average Queue Length', '(c) Throughput (veh/step)']

for ax, metric, ylabel in zip(axes7, metrics_main, ylabels_main):
    means = [summary[s][metric]['mean'] for s in strategies]
    stds = [summary[s][metric]['std'] for s in strategies]
    bars = ax.bar(labels, means, yerr=stds, capsize=5, color=colors,
                  edgecolor='black', linewidth=0.6, alpha=0.85)
    ax.set_ylabel(ylabel.split(') ')[1] if ') ' in ylabel else ylabel)
    ax.set_title(ylabel.split(') ')[0] + ')', loc='left', fontweight='bold', fontsize=11)
    ax.tick_params(axis='x', rotation=35)
    # Highlight LLM bar
    bars[-1].set_edgecolor('#c2185b')
    bars[-1].set_linewidth(2.5)
    # Add value labels
    for bar, m, s in zip(bars, means, stds):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + s + 0.01*max(means),
                f'{m:.3f}' if metric == 'throughput' else f'{m:.1f}',
                ha='center', va='bottom', fontsize=8, rotation=0)

fig7.tight_layout()
fig7.savefig('paper/fig_comparison.png')
print('fig_comparison.png saved')
plt.close()

print('\nAll 7 figures generated.')
