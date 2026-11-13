from __future__ import annotations

import threading
import time
from collections import deque


class RateMeter:
    """Events per second over a sliding window. Safe to tick and read from
    different threads."""

    def __init__(self, window_s: float = 1.0) -> None:
        self._window = window_s
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._times.append(now)
            self._trim(now)

    def rate(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(now)
            if len(self._times) < 2:
                return 0.0
            span = self._times[-1] - self._times[0]
            return (len(self._times) - 1) / span if span > 0 else 0.0

    def _trim(self, now: float) -> None:
        while self._times and now - self._times[0] > self._window:
            self._times.popleft()


class Ema:
    """Exponential moving average; ``None`` until the first sample."""

    def __init__(self, alpha: float = 0.2) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self._alpha = alpha
        self.value: float | None = None

    def update(self, sample: float) -> float:
        self.value = (
            sample if self.value is None else self.value + self._alpha * (sample - self.value)
        )
        return self.value
