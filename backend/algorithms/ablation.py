"""
Ablation Strategies for LLM-Traffic

This module implements ablation strategies to isolate the contribution of
each component in the LLM-assisted signal control pipeline.

Ablation Strategies:
- llm_only: LLM recommendations only (no coordination, no constraints)
- llm_constraints: LLM + constraint validation (no coordination)
- llm_coord: LLM + coordination (no constraint correction)
- llm_full: LLM + coordination + constraints (complete pipeline)

Purpose:
These strategies help understand:
1. How much does the constraint engine contribute to safety?
2. How much does coordination contribute to performance?
3. What's the baseline LLM performance without safety nets?

Usage:
    from backend.algorithms.ablation import AblationStrategy
    
    strategy = AblationStrategy("llm_full")
    timings = strategy.compute_timings(llm_recommendation, queues, intersections)

Author: Yihao Tang
Date: 2024
"""

from typing import Dict, List, Optional
from backend.algorithms.constraints import SignalConstraintEngine
from backend.algorithms.coordination import CoordinationEngine


class AblationStrategy:
    """Ablation strategy controller for isolating component contributions.
    
    This class implements different combinations of LLM, coordination,
    and constraint validation to understand each component's impact.
    
    Usage:
        strategy = AblationStrategy("llm_full")
        
        # Get LLM recommendation
        llm_rec = llm_client.get_batch_recommendation(states)
        
        # Apply ablation strategy
        timings = strategy.compute_timings(
            llm_recommendation=llm_rec,
            queues=queues,
            intersections=intersections
        )
    """
    
    # Available strategies
    STRATEGIES = ["llm_only", "llm_constraints", "llm_coord", "llm_full"]
    
    def __init__(self, strategy: str):
        """Initialize ablation strategy.
        
        Args:
            strategy: Strategy name (one of STRATEGIES)
        
        Raises:
            ValueError: If strategy is not recognized
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"Unknown strategy: {strategy}. "
                f"Available: {self.STRATEGIES}"
            )
        
        self.strategy = strategy
        self.constraint_engine = SignalConstraintEngine()
        self.coordination = CoordinationEngine()
    
    def compute_timings(
        self,
        llm_recommendation: Dict[str, Dict[int, int]],
        queues: Dict[str, Dict[str, int]],
        intersections: List[str],
    ) -> Dict[str, Dict[int, int]]:
        """Compute signal timings based on ablation strategy.
        
        Args:
            llm_recommendation: LLM recommendations per intersection
                               {iid: {phase: duration}}
            queues: Queue lengths per intersection
                   {iid: {direction: count}}
            intersections: List of intersection IDs
        
        Returns:
            Adjusted timings per intersection
            {iid: {phase: duration}}
        """
        # Start with LLM recommendation
        timings = {}
        for iid in intersections:
            timings[iid] = dict(llm_recommendation.get(iid, {0: 30, 1: 3, 2: 30, 3: 3}))
        
        # Apply coordination if strategy includes it
        if self.strategy in ("llm_coord", "llm_full"):
            try:
                adj = self.coordination.compute_adjustments(queues, {})
                timings = self.coordination.apply_adjustments(timings, adj)
            except Exception:
                pass  # Coordination failure shouldn't crash
        
        # Apply constraints if strategy includes it
        if self.strategy in ("llm_constraints", "llm_full"):
            for iid in intersections:
                t = timings[iid]
                green_phases = [t.get(0, 30), t.get(2, 30)]
                cycle_len = sum(t.values())
                
                valid, violations, corrected = self.constraint_engine.validate(
                    green_phases, cycle_len
                )
                
                if not valid and corrected:
                    t[0] = corrected[0]
                    t[2] = corrected[1] if len(corrected) > 1 else 30
        
        return timings
    
    def get_description(self) -> str:
        """Get human-readable description of the strategy.
        
        Returns:
            Description string
        """
        descriptions = {
            "llm_only": (
                "LLM recommendations only. "
                "No coordination or constraint validation. "
                "Tests raw LLM performance."
            ),
            "llm_constraints": (
                "LLM + constraint validation. "
                "No upstream-downstream coordination. "
                "Tests LLM with safety guarantees."
            ),
            "llm_coord": (
                "LLM + coordination. "
                "No constraint correction. "
                "Tests LLM with network awareness."
            ),
            "llm_full": (
                "LLM + coordination + constraints. "
                "Complete pipeline. "
                "Tests full system performance."
            ),
        }
        return descriptions.get(self.strategy, "Unknown strategy")


def get_ablation_strategies() -> List[str]:
    """Get list of available ablation strategies.
    
    Returns:
        List of strategy names
    """
    return AblationStrategy.STRATEGIES


def create_ablation_strategy(strategy: str) -> AblationStrategy:
    """Create an ablation strategy instance.
    
    Args:
        strategy: Strategy name
    
    Returns:
        AblationStrategy instance
    
    Raises:
        ValueError: If strategy is not recognized
    """
    return AblationStrategy(strategy)
