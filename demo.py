#!/usr/bin/env python3
"""
LLM-Traffic Demo Script

This script demonstrates the LLM-Traffic system by:
1. Running a quick simulation with different strategies
2. Comparing performance metrics
3. Generating visualization
4. Showing real-time decision making

Usage:
    python3.10 demo.py [--strategy STRATEGY] [--steps STEPS] [--visualize]

Options:
    --strategy STRATEGY  Control strategy: fixed, random, webster, llm (default: llm)
    --steps STEPS        Number of simulation steps (default: 300)
    --visualize          Generate visualization charts
    --compare            Run all strategies and compare

Examples:
    # Quick demo with LLM strategy
    python3.10 demo.py --strategy llm --steps 100
    
    # Compare all strategies
    python3.10 demo.py --compare --steps 300
    
    # Generate visualization
    python3.10 demo.py --visualize

Author: Yihao Tang
Date: 2024
"""

import argparse
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set SUMO_HOME
os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")


def run_demo(strategy: str, steps: int, visualize: bool = False):
    """Run a single strategy demo.
    
    Args:
        strategy: Control strategy name
        steps: Number of simulation steps
        visualize: Whether to generate visualization
    """
    print(f"\n{'='*60}")
    print(f"🚦 LLM-Traffic Demo: {strategy.upper()} Strategy")
    print(f"{'='*60}")
    
    try:
        from backend.simulation.sumo_engine import SumoEngine
        from backend.algorithms.webster import WebsterController
        from backend.algorithms.baseline import FixedTimeController, RandomController
        from backend.algorithms.constraints import SignalConstraintEngine
        from backend.algorithms.coordination import CoordinationEngine
        from backend.llm.xiaomi_client import LLMClient
        
        # Initialize components
        print("\n📦 Initializing components...")
        engine = SumoEngine()
        constraint_engine = SignalConstraintEngine()
        coordination = CoordinationEngine()
        
        # Initialize controller based on strategy
        if strategy == "fixed":
            controller = FixedTimeController()
        elif strategy == "random":
            controller = RandomController(seed=42)
        elif strategy == "webster":
            controller = WebsterController()
        elif strategy == "llm":
            controller = LLMClient()
        else:
            print(f"❌ Unknown strategy: {strategy}")
            return None
        
        print(f"✓ Controller initialized: {strategy}")
        
        # Start simulation
        print("\n🚀 Starting SUMO simulation...")
        engine.start()
        intersections = engine.intersections
        print(f"✓ Discovered {len(intersections)} intersections: {intersections}")
        
        # Run simulation
        print(f"\n⏱️  Running {steps} steps...")
        start_time = time.time()
        timing_cache = {}
        
        for step in range(steps):
            if not engine.step():
                break
            
            # Control logic at each interval
            if step > 0 and step % 30 == 0:
                queues = engine.get_all_queue_lengths()
                
                if strategy == "llm":
                    # LLM strategy
                    vehicle_counts = engine.get_all_vehicle_counts()
                    all_states = {}
                    for iid in intersections:
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
                        batch_result = controller.get_batch_recommendation(all_states)
                        for iid in intersections:
                            pd = batch_result.get(iid, {}).get(
                                "phase_durations", 
                                {0: 30, 1: 3, 2: 30, 3: 3}
                            )
                            timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                    except Exception as e:
                        print(f"⚠️  LLM call failed at step {step}: {e}")
                        for iid in intersections:
                            timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}
                    
                    # Apply coordination
                    adj = coordination.compute_adjustments(queues, {})
                    timing_cache = coordination.apply_adjustments(timing_cache, adj)
                    
                    # Validate and apply
                    for iid in intersections:
                        timings = timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                        green_phases = [timings.get(0, 30), timings.get(2, 30)]
                        cycle_len = sum(timings.values())
                        _, _, corrected = constraint_engine.validate(green_phases, cycle_len)
                        if corrected:
                            timings[0] = corrected[0]
                            timings[2] = corrected[1] if len(corrected) > 1 else 30
                        phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                        engine.set_phase(iid, phase, duration=max(timings.get(0, 30), timings.get(2, 30)))
                
                elif strategy == "webster":
                    # Webster strategy
                    for iid in intersections:
                        q = queues[iid]
                        ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                        ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                        timings = controller.compute_timing({"EW": ew, "NS": ns})
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))
                
                else:
                    # Fixed/Random strategies
                    for iid in intersections:
                        q = queues[iid]
                        ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                        ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                        timings = controller.compute_timing({"EW": ew, "NS": ns})
                        phase = 0 if timings[0] >= timings[1] else 2
                        engine.set_phase(iid, phase, duration=int(max(timings)))
            
            # Print progress
            if step % 50 == 0:
                print(f"  Step {step}/{steps}")
        
        elapsed = time.time() - start_time
        
        # Get results
        metrics = engine.metrics.summary()
        engine.stop()
        
        # Print results
        print(f"\n{'='*60}")
        print(f"📊 Results for {strategy.upper()}")
        print(f"{'='*60}")
        print(f"  Steps completed: {metrics['total_steps']}")
        print(f"  Elapsed time: {elapsed:.1f}s")
        print(f"  Throughput: {metrics['throughput']:.4f} veh/step")
        print(f"  Avg wait time: {metrics['avg_wait_time']:.2f}s")
        print(f"  Avg queue length: {metrics['avg_queue_length']:.2f}")
        print(f"  Vehicles arrived: {metrics['vehicles_arrived']}")
        
        # Per-intersection breakdown
        print(f"\n  Per-Intersection Breakdown:")
        for iid, data in metrics['per_intersection'].items():
            print(f"    {iid}: wait={data['avg_wait_time']:.1f}s, queue={data['avg_queue_length']:.1f}")
        
        return metrics
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_comparison(steps: int):
    """Run all strategies and compare.
    
    Args:
        steps: Number of simulation steps per strategy
    """
    print(f"\n{'='*60}")
    print(f"🏁 Strategy Comparison")
    print(f"{'='*60}")
    
    strategies = ["fixed", "random", "webster", "llm"]
    results = {}
    
    for strategy in strategies:
        metrics = run_demo(strategy, steps)
        if metrics:
            results[strategy] = metrics
    
    # Print comparison table
    print(f"\n{'='*60}")
    print(f"📊 Comparison Summary")
    print(f"{'='*60}")
    print(f"{'Strategy':<12} {'Throughput':<12} {'Wait Time':<12} {'Queue Len':<12}")
    print("-" * 48)
    
    for strategy in strategies:
        if strategy in results:
            m = results[strategy]
            print(f"{strategy:<12} {m['throughput']:<12.4f} {m['avg_wait_time']:<12.2f} {m['avg_queue_length']:<12.2f}")
    
    # Find best strategy
    best = max(results.items(), key=lambda x: x[1]['throughput'])
    print(f"\n🏆 Best strategy: {best[0].upper()} (throughput: {best[1]['throughput']:.4f})")
    
    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="LLM-Traffic Demo")
    parser.add_argument(
        "--strategy", 
        type=str, 
        default="llm",
        choices=["fixed", "random", "webster", "llm"],
        help="Control strategy (default: llm)"
    )
    parser.add_argument(
        "--steps", 
        type=int, 
        default=300,
        help="Number of simulation steps (default: 300)"
    )
    parser.add_argument(
        "--compare", 
        action="store_true",
        help="Run all strategies and compare"
    )
    parser.add_argument(
        "--visualize", 
        action="store_true",
        help="Generate visualization charts"
    )
    
    args = parser.parse_args()
    
    print("🚦 LLM-Traffic Demo")
    print("=" * 60)
    
    if args.compare:
        results = run_comparison(args.steps)
    else:
        results = run_demo(args.strategy, args.steps, args.visualize)
    
    if args.visualize and results:
        print("\n📊 Generating visualization...")
        try:
            import subprocess
            subprocess.run(["python3.10", "gen_figures.py"], check=True)
            print("✓ Visualization generated in paper/")
        except Exception as e:
            print(f"⚠️  Visualization failed: {e}")
    
    print("\n✓ Demo complete!")


if __name__ == "__main__":
    main()
