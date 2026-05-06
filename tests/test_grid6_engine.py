#!/usr/bin/env python3
"""
Test script for the multi-intersection SUMO engine.
Starts grid6 simulation, runs 200 steps, prints metrics.
"""
import os
import sys

# Ensure project root is on path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")

from backend.simulation.sumo_engine import SumoEngine, INTERSECTIONS


def main():
    engine = SumoEngine()

    print("=" * 70)
    print("Multi-Intersection SUMO Engine Test (grid6, 200 steps)")
    print("=" * 70)

    # Start simulation
    engine.start(
        config_file=os.path.join(PROJECT_ROOT, "data", "grid6.sumocfg"),
        step_length=1,
    )

    print(f"\nSimulation started. Intersections: {INTERSECTIONS}\n")

    # Run 200 steps
    for step in range(1, 201):
        ok = engine.step()
        if not ok:
            print(f"Simulation ended early at step {step}")
            break

        # Print a snapshot every 50 steps
        if step % 50 == 0:
            snap = engine.get_snapshot()
            print(f"--- Step {step} (t={snap['time']}s) ---")
            print(f"  Total vehicles in sim: {snap['total_vehicles']}")

            # Signal states
            print("  Signals:")
            for sig in snap["signals"]:
                print(f"    {sig['intersection']}: program={sig['program']} "
                      f"phase={sig['phase']} state={sig['state']}")

            # Queue lengths
            print("  Queue lengths (per approach):")
            for iid, queues in snap["queue_lengths"].items():
                total_q = sum(queues.values())
                detail = ", ".join(f"{d}={v}" for d, v in queues.items())
                print(f"    {iid}: total={total_q} ({detail})")

            print()

    # Final metrics
    print("=" * 70)
    print("FINAL METRICS (200 steps)")
    print("=" * 70)
    summary = engine.metrics.summary()

    print(f"\nAggregate:")
    print(f"  Total steps:         {summary['total_steps']}")
    print(f"  Vehicles departed:   {summary['vehicles_departed']}")
    print(f"  Vehicles arrived:    {summary['vehicles_arrived']}")
    print(f"  Throughput:          {summary['throughput']:.4f} veh/step")
    print(f"  Avg wait time:       {summary['avg_wait_time']:.4f}")
    print(f"  Avg queue length:    {summary['avg_queue_length']:.4f}")

    print(f"\nPer-intersection:")
    for iid in INTERSECTIONS:
        m = summary["per_intersection"][iid]
        print(f"  {iid}: avg_wait={m['avg_wait_time']:.4f}  "
              f"avg_queue={m['avg_queue_length']:.4f}  "
              f"avg_vehicles={m['avg_vehicle_count']:.4f}")

    # Test signal switching
    print(f"\n--- Testing signal program switch ---")
    print("Switching all intersections to program 1 (NS green)...")
    for iid in INTERSECTIONS:
        engine.set_signal_program(iid, 1)

    signals = engine.get_all_signal_states()
    for sig in signals:
        print(f"  {sig['intersection']}: program={sig['program']} state={sig['state']}")

    # Switch back
    print("Switching all intersections back to program 0 (EW green)...")
    for iid in INTERSECTIONS:
        engine.set_signal_program(iid, 0)

    signals = engine.get_all_signal_states()
    for sig in signals:
        print(f"  {sig['intersection']}: program={sig['program']} state={sig['state']}")

    # Test speed factor
    print(f"\n--- Testing speed factor ---")
    engine.set_speed_factor(0.5)
    print("Set speed factor to 0.5 for all vehicles.")
    engine.step()
    print("  One step completed with reduced speed.")

    # Cleanup
    engine.stop()
    print(f"\nSimulation stopped. Test complete.")


if __name__ == "__main__":
    main()
