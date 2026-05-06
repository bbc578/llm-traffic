# IEEE T-ITS Review

## 1. SUMMARY

This paper proposes a framework that uses large language models (LLMs) for adaptive traffic signal control across multiple intersections, combined with a rule-based constraint engine and upstream-downstream coordination logic. The system processes real-time traffic states from all intersections in a single batch LLM call, generates signal timing recommendations, validates them against safety constraints, and adjusts them based on queue spillover detection. Experiments on a 3×2 grid network in SUMO show the LLM+Coordination strategy achieving 50% lower waiting time and 41% lower queue length compared to Webster's method.

## 2. STRENGTHS

1. **Novel application domain**: Applying LLMs to traffic signal control is a genuinely new idea that explores an underexamined intersection of large language models and transportation engineering. The paper identifies a plausible niche where LLMs might offer advantages over traditional RL approaches (interpretability, generalization without retraining).

2. **Clean modular architecture**: The framework's separation into perception, LLM decision, constraint engine, and coordination engine is well-designed. Each component has clear responsibilities, and the ablation study design follows naturally from this decomposition.

3. **Reproducibility infrastructure**: The inclusion of a complete codebase, `reproduce.sh` script, test suite, and clear dependency specifications is commendable. This sets a high standard for reproducibility that many T-ITS papers fail to meet.

4. **Honest reporting of limitations**: The paper reports LLM latency (55.6s for 6 intersections, 68.2s for 12) and acknowledges that this is currently impractical for real-time deployment. The ablation study shows that coordination actually *increases* wait time slightly (1.93s → 2.27s), which is reported transparently.

5. **Ablation study design**: Isolating the contributions of LLM, constraint engine, and coordination engine provides clear evidence about what each component adds (or doesn't add) to system performance.

## 3. WEAKNESSES

1. **Trivial experimental setup**: The 3×2 grid network with 6 intersections is far too simple to demonstrate meaningful traffic signal control. This is a toy problem. The paper needs experiments on realistic networks (e.g., Cologne, Luxembourg, or Manhattan subnetworks with dozens of intersections, varying road geometries, turning movements, pedestrian phases, transit priority). The 4×3 scalability experiment is still trivial.

2. **Baseline comparison is misleading**: The "Fixed" strategy result (249.22s wait time) is catastrophically bad—this suggests the fixed-time controller is poorly tuned (30s+3s+30s+3s cycle for a network where demand clearly doesn't match this). A properly tuned fixed-time controller based on historical demand would perform much better. The Random strategy outperforming Fixed by 30× is a red flag that the baselines are not implemented correctly.

3. **No comparison to state-of-the-art**: The paper compares only against Fixed, Random, and Webster—all classical methods from the 1950s-60s. There is no comparison to any modern approach: no RL (e.g., FRAP, CoLight, PressLight), no max-pressure control (despite it being mentioned in the code), no actuated control, no SCOOT/SCATS-style adaptive systems. This is a fatal omission for a T-ITS paper.

4. **LLM latency makes the approach impractical**: 55.6 seconds per decision cycle for 6 intersections means the system cannot respond to traffic changes faster than ~1 minute. Real traffic signals need to react in seconds. The paper acknowledges this but doesn't propose any solution—this isn't just a limitation, it's a fundamental barrier to deployment.

5. **Coordination engine appears counterproductive**: The ablation shows that adding coordination *increases* wait time from 1.93s to 2.27s (17% worse). The paper frames this as "robustness against queue spillover at a modest cost to average-case wait time," but no evidence of spillover events is provided. Without showing that coordination prevents catastrophic failures during high-demand scenarios, this looks like a net negative.

6. **No statistical rigor**: Results are reported as single numbers without confidence intervals, standard deviations, or statistical significance tests. The multi-trial experiment (5 trials) is mentioned but results are presented as point estimates. For a T-ITS paper, statistical analysis is essential.

7. **LLM API dependency is a reproducibility concern**: The system relies on a proprietary API (Xiaomi MiMo v2.5 Pro). The paper cannot be fully reproduced without access to this specific model, and results may not generalize to other LLMs. The paper doesn't test with open-source alternatives (e.g., Llama, Mistral) that could be run locally.

## 4. QUESTIONS FOR AUTHORS

1. **Why are the fixed-time results so poor?** A 30s+3s+30s+3s cycle with 249s average wait suggests the network is severely oversaturated under this timing. Did you attempt to optimize the fixed-time cycle length for the given demand pattern? What happens with a properly tuned fixed-time controller (e.g., using Webster's optimal cycle length formula)?

2. **Why no comparison to RL methods?** The introduction frames RL as the main alternative, yet no RL baselines are included. Can you provide results for at least one standard RL approach (e.g., DQN with phase-based actions) on the same network? If RL requires extensive training, that's a valid comparison point—but you need to show the comparison.

3. **What happens under high demand / saturation?** The current results show very low queue lengths (3.81 vehicles average). What happens when demand increases to the point where queues grow to 20-50 vehicles per approach? Does the LLM still make reasonable decisions? Does the coordination engine become useful?

4. **How sensitive are results to the LLM model?** Have you tested with other models (GPT-4, Llama 3, Mistral)? Do different models give different signal timing recommendations? Is the performance dependent on the specific MiMo model's training data?

5. **Can you provide per-intersection results?** The aggregate metrics may hide important patterns. For example, does the LLM favor certain intersections? Are there intersections where the LLM performs worse than Webster?

6. **What is the computational cost breakdown?** The 55.6s latency—how much is network latency to the API vs. model inference time vs. parsing/post-processing? Could a local model reduce this to acceptable levels?

## 5. MINOR COMMENTS

1. **Paper formatting**: The paper uses `IEEEtran` conference format, not the T-ITS journal format. This would need to be reformatted for journal submission.

2. **Missing related work**: The paper cites only 3 references in the introduction and related work sections. A T-ITS paper should have a comprehensive literature review covering at least 30-50 references, including recent RL-based methods, classical adaptive control, and LLM applications in transportation.

3. **Terminology**: "LLM-Guided" is somewhat misleading—the LLM is making the primary control decisions, not just guiding. Consider "LLM-Based" or "LLM-Driven."

4. **Figure quality**: The architecture diagram in the README is ASCII art. The paper needs proper vector graphics. No experimental result figures are included in the paper draft.

5. **Code quality**: The `xiaomi_client.py` file has a truncated method (`_parse_batch_response` cuts off mid-function). The `coordination.py` file is also truncated. This suggests the codebase is incomplete.

6. **Yellow time clamping**: The LLM client clamps yellow times to [3, 5] seconds, but the constraint engine fixes yellow at 3 seconds. These should be consistent.

7. **Missing discussion of phase structure**: The system assumes a simple two-phase (NS/EW) structure. Real intersections often have protected left turns, pedestrian phases, or more complex phasing. How would this generalize?

## 6. OVERALL RECOMMENDATION

**Major Revision**

The core idea—using LLMs for traffic signal control—is novel and potentially interesting, but the paper in its current form is not ready for T-ITS. The experimental evaluation is far too limited (toy network, weak baselines, no statistical analysis, no comparison to modern methods). The latency issue is a fundamental practical concern that needs to be addressed or at least more thoroughly characterized. The coordination engine appears to hurt performance rather than help it.

## 7. SCORE

**5/10**

The paper has a creative core idea and excellent reproducibility infrastructure, but the experimental validation is insufficient for a top journal. The contribution is currently at the level of a workshop paper or short conference paper. To reach T-ITS standards, the authors would need to:

1. Evaluate on realistic networks (Cologne, Luxembourg, or similar)
2. Compare against at least 2-3 modern RL-based methods
3. Provide proper statistical analysis with confidence intervals
4. Fix the baseline implementations (especially fixed-time)
5. Either solve the latency problem or provide a thorough analysis of its implications
6. Demonstrate that the coordination engine provides measurable benefits (e.g., during demand surges)
7. Test with multiple LLM models to show generalizability
8. Expand the literature review substantially