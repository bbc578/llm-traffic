"""
Simple DQN-based traffic signal controller (numpy-only baseline).

A minimal Deep Q-Network controller that decides between NS-green and
EW-green based on observed queue lengths.  Uses a two-layer neural
network with epsilon-greedy exploration and experience replay.

This is intentionally simple – a baseline for the LLM controller to
beat, not a production-grade RL system.
"""

import random as rng
from collections import deque
from typing import Dict, List, Optional

import numpy as np


class DQNetwork:
    """Tiny 2-layer feed-forward network (NumPy only)."""

    def __init__(self, input_dim: int = 4, hidden_dim: int = 16,
                 output_dim: int = 2, lr: float = 0.001, seed: int = 0):
        rng.seed(seed)
        np.random.seed(seed)
        # Xavier-ish init
        scale1 = np.sqrt(2.0 / (input_dim + hidden_dim))
        scale2 = np.sqrt(2.0 / (hidden_dim + output_dim))
        self.w1 = np.random.randn(input_dim, hidden_dim) * scale1
        self.b1 = np.zeros(hidden_dim)
        self.w2 = np.random.randn(hidden_dim, output_dim) * scale2
        self.b2 = np.zeros(output_dim)
        self.lr = lr

    def forward(self, x: np.ndarray) -> np.ndarray:
        """Return Q-values for a single state (shape: (output_dim,))."""
        self._last_x = x
        self._h_pre = x @ self.w1 + self.b1
        self._h = np.maximum(self._h_pre, 0)  # ReLU
        q = self._h @ self.w2 + self.b2
        return q

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)

    def train_step(self, x: np.ndarray, target_q: np.ndarray) -> float:
        """One gradient step on (state -> target_q_values).  Returns loss."""
        # Forward
        q = self.forward(x)
        # MSE loss
        loss = np.mean((q - target_q) ** 2)
        # Backward
        dq = 2.0 * (q - target_q) / len(target_q) if target_q.ndim > 1 else 2.0 * (q - target_q)
        # Layer 2
        dw2 = np.outer(self._h, dq)
        db2 = dq
        # Through ReLU
        dh = dq @ self.w2.T
        dh[self._h_pre < 0] = 0
        # Layer 1
        dw1 = np.outer(self._last_x, dh)
        db1 = dh
        # Update
        self.w2 -= self.lr * dw2
        self.b2 -= self.lr * db2
        self.w1 -= self.lr * dw1
        self.b1 -= self.lr * db1
        return float(loss)


class RLController:
    """DQN-based traffic signal controller.

    State  = [q_east, q_west, q_north, q_south]  (normalised queue lengths)
    Action = 0 → NS green, 1 → EW green

    The controller exposes a ``compute_timing`` method compatible with the
    existing experiment framework.  Internally it also tracks transitions
    and learns from experience after every decision step.
    """

    def __init__(
        self,
        hidden_dim: int = 16,
        lr: float = 0.001,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.999,
        buffer_size: int = 2000,
        batch_size: int = 32,
        min_green: int = 10,
        max_green: int = 60,
        cycle_length: int = 60,
        yellow_time: int = 3,
        seed: int = 0,
    ):
        self._seed = seed
        self._rng = rng.Random(seed)
        self.net = DQNetwork(
            input_dim=4, hidden_dim=hidden_dim,
            output_dim=2, lr=lr, seed=seed,
        )
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.buffer = deque(maxlen=buffer_size)
        self.batch_size = batch_size
        self.min_green = min_green
        self.max_green = max_green
        self.cycle_length = cycle_length
        self.yellow_time = yellow_time

        # Transition memory
        self._prev_state: Optional[np.ndarray] = None
        self._prev_action: Optional[int] = None
        self._step_count = 0

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _extract_state(queue_data: Dict[str, int]) -> np.ndarray:
        """Normalise queue lengths to a 4-element vector."""
        q_e = float(queue_data.get("east", 0))
        q_w = float(queue_data.get("west", 0))
        q_n = float(queue_data.get("north", 0))
        q_s = float(queue_data.get("south", 0))
        raw = np.array([q_e, q_w, q_n, q_s], dtype=np.float64)
        # Normalise: divide by (1 + max) so values are in [0, 1]
        mx = max(raw.max(), 1.0)
        return raw / mx

    def _reward(self, queue_data: Dict[str, int]) -> float:
        """Reward = negative total queue length (lower queues → higher reward)."""
        return -float(sum(queue_data.values()))

    def _choose_action(self, state: np.ndarray) -> int:
        """Epsilon-greedy action selection."""
        if self._rng.random() < self.epsilon:
            return self._rng.randint(0, 1)
        q_values = self.net.predict(state)
        return int(np.argmax(q_values))

    def _learn(self):
        """Sample a mini-batch from the replay buffer and train."""
        if len(self.buffer) < self.batch_size:
            return
        batch = self._rng.sample(list(self.buffer), self.batch_size)

        for s, a, r, s_next, done in batch:
            q_vals = self.net.predict(s).copy()
            if done:
                q_vals[a] = r
            else:
                q_next = self.net.predict(s_next)
                q_vals[a] = r + self.gamma * np.max(q_next)
            self.net.train_step(s, q_vals)

    # -- public API --------------------------------------------------------

    def compute_timing(
        self,
        phase_flows: Dict[str, float] = None,
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
        num_phases: int = 2,
        queue_data: Optional[Dict[str, int]] = None,
    ) -> List[int]:
        """Observe queues, pick NS-green or EW-green, learn, and return timings.

        Compatible with the existing experiment framework signature.
        ``queue_data`` must be provided for RL to function; falls back to
        equal-split if absent.

        Returns:
            [green_phase_0, green_phase_1] where phase 0 = NS, phase 1 = EW
            (or vice-versa – the mapping is: action 0 → NS gets more green,
             action 1 → EW gets more green).
        """
        mg = min_green or self.min_green
        xg = max_green or self.max_green
        cl = self.cycle_length
        yt = yellow_time or self.yellow_time

        n_yellow = 2 * yt
        total_green = cl - n_yellow
        # Ensure total_green is positive
        total_green = max(total_green, 2 * mg)

        if queue_data is None:
            # No queue info – return equal split
            half = total_green // 2
            return [max(mg, min(xg, half)), max(mg, min(xg, total_green - half))]

        # --- RL decision ---
        state = self._extract_state(queue_data)
        reward = self._reward(queue_data)

        # Learn from previous transition (if any)
        if self._prev_state is not None:
            done = False
            self.buffer.append(
                (self._prev_state, self._prev_action, reward, state, done)
            )
            self._learn()

        # Pick action
        action = self._choose_action(state)

        # Store for next learning step
        self._prev_state = state
        self._prev_action = action
        self._step_count += 1

        # Decay epsilon
        self.epsilon = max(self.epsilon_end,
                           self.epsilon * self.epsilon_decay)

        # Action 0 → NS green (more green to NS), Action 1 → EW green
        dominant_green = max(mg, int(total_green * 0.7))
        minor_green = max(mg, total_green - dominant_green)

        if action == 0:
            # NS gets dominant green
            return [minor_green, dominant_green]  # [EW, NS] → phase 0=EW, phase 2=NS
        else:
            # EW gets dominant green
            return [dominant_green, minor_green]
