"""Temporal filters for noisy scalar measurements (e.g. joint angles).

Filters take explicit timestamps because inference frame intervals vary.
Callers must :meth:`reset` a filter when the measurement becomes invalid for
longer than a tolerated gap, so stale history is never blended into new data.
"""

from __future__ import annotations

import math
from typing import Protocol


class ScalarFilter(Protocol):
    def update(self, value: float, timestamp_ms: int) -> float: ...

    def reset(self) -> None: ...


class PassThroughFilter:
    def update(self, value: float, timestamp_ms: int) -> float:
        return value

    def reset(self) -> None:
        pass


class EmaFilter:
    """Fixed-weight exponential moving average. Simple, but lags fast motion."""

    def __init__(self, alpha: float) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self._alpha = alpha
        self._value: float | None = None

    def update(self, value: float, timestamp_ms: int) -> float:
        self._value = value if self._value is None else self._value + self._alpha * (value - self._value)
        return self._value

    def reset(self) -> None:
        self._value = None


def _smoothing_factor(dt_s: float, cutoff_hz: float) -> float:
    r = 2 * math.pi * cutoff_hz * dt_s
    return r / (r + 1)


class OneEuroFilter:
    """One Euro filter (Casiez, Roussel & Vogel, CHI 2012).

    A low-pass filter whose cutoff rises with speed: heavy smoothing when the
    joint is still (suppresses jitter), light smoothing when it moves (limits
    lag). ``min_cutoff_hz`` sets jitter suppression at rest; ``beta`` (per
    unit/s of speed) sets how quickly smoothing relaxes during motion.
    """

    def __init__(self, min_cutoff_hz: float, beta: float, d_cutoff_hz: float = 1.0) -> None:
        if min_cutoff_hz <= 0 or d_cutoff_hz <= 0 or beta < 0:
            raise ValueError("cutoffs must be > 0 and beta >= 0")
        self._min_cutoff = min_cutoff_hz
        self._beta = beta
        self._d_cutoff = d_cutoff_hz
        self.reset()

    def reset(self) -> None:
        self._x: float | None = None
        self._dx = 0.0
        self._t_ms: int | None = None

    def update(self, value: float, timestamp_ms: int) -> float:
        if self._x is None or self._t_ms is None:
            self._x, self._t_ms = value, timestamp_ms
            return value
        if timestamp_ms <= self._t_ms:
            return self._x  # non-increasing timestamp: cannot integrate, ignore sample
        dt = (timestamp_ms - self._t_ms) / 1000.0
        self._t_ms = timestamp_ms
        dx = (value - self._x) / dt
        self._dx += _smoothing_factor(dt, self._d_cutoff) * (dx - self._dx)
        cutoff = self._min_cutoff + self._beta * abs(self._dx)
        self._x += _smoothing_factor(dt, cutoff) * (value - self._x)
        return self._x
