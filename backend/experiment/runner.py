"""
Experiment runner for traffic signal controllers.
Runs a controller over a simulated traffic scenario and collects metrics.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class Controller(Protocol):
    """Protocol that all signal controllers must satisfy."""

    def compute_timing(
        self,
        phase_flows: Dict[str, float],
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
    ) -> List[int]:
        """Compute green durations for each phase."""
        ...


@dataclass
class StepMetrics:
    """Metrics collected at a single simulation step."""

    step: int = 0
    time: float = 0.0
    avg_wait: float = 0.0
    throughput: float = 0.0
    avg_queue: float = 0.0
    total_vehicles: int = 0
    green_durations: List[int] = field(default_factory=list)


@dataclass
class ExperimentResult:
    """Aggregated results from an experiment run."""

    controller_name: str = ""
    steps: int = 0
    total_time: float = 0.0
    avg_wait: float = 0.0
    throughput: float = 0.0
    avg_queue: float = 0.0
    total_vehicles: int = 0
    step_metrics: List[StepMetrics] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SimpleTrafficModel:
    """
    Simple analytical traffic model for testing controllers without SUMO.
    Models queue buildup and discharge at a signalized intersection.
    """

    def __init__(
        self,
        phase_names: List[str],
        arrival_rates: Dict[str, float] = None,
        saturation_flow: float = 1800,
        rng_seed: int = None,
    ):
        self.phase_names = phase_names
        self.saturation_flow = saturation_flow
        self.rng = random.Random(rng_seed)

        # Default arrival rates (veh/hr) if not specified
        if arrival_rates is None:
            self.arrival_rates = {name: 600.0 for name in phase_names}
        else:
            self.arrival_rates = arrival_rates

        # State
        self.queues = {name: 0.0 for name in phase_names}
        self.total_served = 0
        self.total_wait = 0.0
        self.step_count = 0

    def step(self, green_durations: List[int]) -> StepMetrics:
        """
        Advance the model by one signal cycle.

        During green: serve vehicles at saturation_flow rate.
        During the cycle: new vehicles arrive at arrival_rate.
        """
        cycle_time = sum(green_durations)
        if cycle_time == 0:
            cycle_time = 1

        total_queue = 0.0
        total_wait = 0.0
        total_served = 0
        total_arrived = 0

        for i, name in enumerate(self.phase_names):
            green = green_durations[i] if i < len(green_durations) else 10
            red = cycle_time - green

            # Vehicles arriving during the full cycle
            rate = self.arrival_rates.get(name, 600.0)
            arrivals = (rate / 3600.0) * cycle_time
            arrivals *= self.rng.uniform(0.8, 1.2)  # stochastic variation
            total_arrived += arrivals

            # Queue at start of red = previous queue + arrivals during red
            # Queue builds during red, vehicles arrive throughout
            queue_at_red_end = self.queues[name] + (rate / 3600.0) * red
            queue_at_red_end *= self.rng.uniform(0.9, 1.1)

            # Vehicles served during green
            can_serve = (self.saturation_flow / 3600.0) * green
            served = min(queue_at_red_end, can_serve)
            total_served += served

            # Remaining queue
            remaining = max(0.0, queue_at_red_end - served)

            # Add arrivals during green to remaining queue
            green_arrivals = (rate / 3600.0) * green
            self.queues[name] = remaining + green_arrivals * 0.5

            total_queue += self.queues[name]

            # Approximate wait: half the cycle time for queued vehicles
            avg_wait_phase = cycle_time * 0.5 * (self.queues[name] / max(served, 1))
            total_wait += avg_wait_phase

        self.total_served += total_served
        self.step_count += 1

        n_phases = len(self.phase_names)
        return StepMetrics(
            step=self.step_count,
            time=self.step_count * cycle_time,
            avg_wait=total_wait / max(n_phases, 1),
            throughput=total_served,
            avg_queue=total_queue / max(n_phases, 1),
            total_vehicles=sum(int(q) for q in self.queues.values()),
            green_durations=list(green_durations),
        )


class ExperimentRunner:
    """
    Runs a traffic signal controller over N cycles using a traffic model,
    collecting metrics at each step.
    """

    def __init__(
        self,
        model: SimpleTrafficModel = None,
        phase_names: List[str] = None,
        arrival_rates: Dict[str, float] = None,
    ):
        if model is not None:
            self.model = model
        else:
            names = phase_names or ["north_south", "east_west"]
            self.model = SimpleTrafficModel(
                phase_names=names,
                arrival_rates=arrival_rates,
            )

    def run(
        self,
        controller: Any,
        steps: int = 500,
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
    ) -> ExperimentResult:
        """
        Run the controller for N steps and collect aggregated metrics.

        Args:
            controller: object with compute_timing(phase_flows, ...) method
            steps: number of simulation cycles to run
            saturation_flow: saturation flow rate for controller
            min_green: minimum green time for controller
            max_green: maximum green time for controller
            yellow_time: yellow time for controller

        Returns:
            ExperimentResult with aggregated metrics
        """
        logger.info(f"Running experiment with {controller.__class__.__name__} for {steps} steps")
        start_time = time.time()

        all_metrics: List[StepMetrics] = []
        phase_flows = dict(self.model.arrival_rates)

        for step_idx in range(steps):
            # Get green durations from controller
            greens = controller.compute_timing(
                phase_flows=phase_flows,
                saturation_flow=saturation_flow,
                min_green=min_green,
                max_green=max_green,
                yellow_time=yellow_time,
            )

            # Step the traffic model
            metrics = self.model.step(greens)
            all_metrics.append(metrics)

            # Update phase_flows based on current queues (feedback)
            for i, name in enumerate(self.model.phase_names):
                base = self.model.arrival_rates.get(name, 600.0)
                queue_factor = 1.0 + self.model.queues[name] * 0.01
                phase_flows[name] = base * min(queue_factor, 2.0)

        elapsed = time.time() - start_time

        # Aggregate metrics
        if all_metrics:
            avg_wait = sum(m.avg_wait for m in all_metrics) / len(all_metrics)
            throughput = sum(m.throughput for m in all_metrics)
            avg_queue = sum(m.avg_queue for m in all_metrics) / len(all_metrics)
            total_vehicles = all_metrics[-1].total_vehicles if all_metrics else 0
        else:
            avg_wait = throughput = avg_queue = total_vehicles = 0

        result = ExperimentResult(
            controller_name=controller.__class__.__name__,
            steps=steps,
            total_time=elapsed,
            avg_wait=round(avg_wait, 3),
            throughput=round(throughput, 1),
            avg_queue=round(avg_queue, 3),
            total_vehicles=total_vehicles,
            step_metrics=all_metrics,
            metadata={
                "phase_names": self.model.phase_names,
                "arrival_rates": self.model.arrival_rates,
                "saturation_flow": saturation_flow,
                "min_green": min_green,
                "max_green": max_green,
                "yellow_time": yellow_time,
            },
        )

        logger.info(
            f"Experiment done: {result.controller_name} | "
            f"avg_wait={result.avg_wait}s | throughput={result.throughput} | "
            f"avg_queue={result.avg_queue} | time={result.total_time:.2f}s"
        )

        return result
