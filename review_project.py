#!/usr/bin/env python3.10
"""
Send llm-traffic project to DeepSeek for expert review.
Gathers all key files and sends them as context.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

DEEPSEEK_KEY = "sk-9a26609800a94022a7d32b58349e2dd1"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Gather project files
FILES_TO_REVIEW = [
    "README.md",
    "backend/main.py",
    "backend/llm/xiaomi_client.py",
    "backend/algorithms/constraints.py",
    "backend/algorithms/coordination.py",
    "backend/algorithms/webster.py",
    "backend/algorithms/baseline.py",
    "backend/simulation/sumo_engine.py",
    "backend/config/settings.py",
    "frontend/src/App.tsx",
    "frontend/src/hooks/useSimulationSocket.ts",
    "frontend/src/components/LLMPanel.tsx",
    "paper/main.tex",
    "tests/test_all.py",
    "run_experiment.py",
    "run_ablation.py",
]

def gather_context():
    parts = []
    for fpath in FILES_TO_REVIEW:
        full = os.path.join(os.path.dirname(__file__), fpath)
        if os.path.exists(full):
            with open(full) as f:
                content = f.read()
            # Truncate very long files
            if len(content) > 8000:
                content = content[:8000] + "\n... [truncated]"
            parts.append(f"=== FILE: {fpath} ===\n{content}")
    return "\n\n".join(parts)


REVIEWER_PROMPT = """You are an objective, rigorous project review expert for an academic research project. Your job is to evaluate the "LLM-Traffic" project — an LLM-guided adaptive traffic signal control system — and determine whether it is ready for:

1. Academic publication at a top-tier conference (IEEE ITSC / CICTP)
2. Open-source release on GitHub
3. Real-world deployment consideration

You must be HONEST and CRITICAL. Do not be nice. Do not give participation trophies. If something is broken, say so. If something is missing, say so. If something is wrong, say so.

Evaluate the project across these dimensions:

**1. Technical Correctness**
- Is the code correct? Any bugs, race conditions, edge cases?
- Is the SUMO integration correct?
- Is the LLM integration robust?
- Are the algorithms (Webster, coordination, constraints) implemented correctly?

**2. Experimental Rigor**
- Is the experimental design sound?
- Are the baselines fair and sufficient?
- Is the statistical analysis adequate?
- Are the results reproducible?

**3. Paper Quality**
- Is the paper well-written and well-structured?
- Are the claims supported by evidence?
- Are the limitations honestly discussed?
- Is the related work comprehensive?

**4. Code Quality**
- Is the code well-organized and maintainable?
- Are there adequate tests?
- Is the documentation sufficient?
- Is it easy for someone else to set up and run?

**5. Novelty and Impact**
- Is the contribution novel enough for a top conference?
- Is the practical impact clear?
- Are the results strong enough to publish?

For each dimension, give:
- A score from 1-10 (10 = perfect)
- Specific issues (be concrete, cite file names and line numbers if possible)
- Required fixes (what MUST be fixed before publication)
- Suggested improvements (what WOULD make it better)

At the end, give an overall verdict:
- PUBLISH_READY: Ready for submission
- NEEDS_MINOR_REVISION: A few issues to fix
- NEEDS_MAJOR_REVISION: Significant problems
- NOT_READY: Fundamental issues

Be thorough. Read every file carefully. This is a real project that will be submitted to a real conference."""

def call_deepseek(context: str, prompt: str, user_msg: str) -> str:
    resp = httpx.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
            "max_tokens": 8000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


if __name__ == "__main__":
    print("Gathering project files...")
    context = gather_context()
    print(f"Context size: {len(context)} chars")

    user_msg = f"""Please review the LLM-Traffic project thoroughly. Here are all the key files:

{context}

Also, here are the experimental results from our latest run:

**Grid6 (3×2, 6 intersections, 300 steps):**
| Strategy | Avg Wait (s) | Avg Queue | Throughput |
|----------|-------------|-----------|------------|
| Fixed    | 47.20       | 17.75     | 0.090      |
| Random   | 8.00        | 7.78      | 0.357      |
| Webster  | 4.52        | 6.42      | 0.413      |
| LLM+Coord| 2.27        | 3.81      | 0.493      |

**Ablation (Grid6):**
| Configuration | Wait (s) | Queue | Throughput |
|---------------|----------|-------|------------|
| Webster       | 4.52     | 6.42  | 0.413      |
| LLM Only      | 1.93     | 3.81  | 0.493      |
| LLM+Constraint| 2.10     | 3.90  | 0.480      |
| LLM+Coord     | 2.27     | 3.81  | 0.493      |

**LLM Latency:** 55.6s avg (Grid6), 68.2s avg (Grid4x3)

Please give your complete review now."""

    print("\nCalling DeepSeek for review...")
    review = call_deepseek(context, REVIEWER_PROMPT, user_msg)

    # Save review
    output_path = os.path.join(os.path.dirname(__file__), "data", "deepseek_review.md")
    with open(output_path, "w") as f:
        f.write(review)
    print(f"\nReview saved to {output_path}")
    print("\n" + "=" * 80)
    print(review)
