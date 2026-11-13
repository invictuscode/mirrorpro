"""Repetition state machine: clean reps and every rejection/robustness path."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pytest

from app.exercises.rep_counter import RepCounter, RepCounterState, RepEventKind, RepPhase
from app.exercises.schema import RepCountingConfig

DT = 33  # ~30 fps


def cfg(**kw: object) -> RepCountingConfig:
    base: dict[str, object] = dict(
        start_deg=30, target_deg=110, hysteresis_deg=8, confirm_ms=100,
        min_hold_ms=0, min_rep_ms=600, max_rep_ms=15_000, max_signal_gap_ms=750,
    )  # fmt: skip
    return RepCountingConfig.model_validate(base | kw)


class Clock:
    def __init__(self) -> None:
        self.t = 0

    def feed(self, counter: RepCounter, values: Iterable[float | None]) -> RepCounterState:
        state = None
        for v in values:
            state = counter.update(v, self.t)
            self.t += DT
        assert state is not None
        return state


def ramp(a: float, b: float, n: int) -> list[float]:
    return list(np.linspace(a, b, n))


def hold(v: float | None, n: int) -> list[float | None]:
    return [v] * n


def curl(low: float = 10, high: float = 130, frames_each_way: int = 30) -> list[float | None]:
    return hold(low, 6) + ramp(low, high, frames_each_way) + hold(high, 6) + ramp(high, low, frames_each_way) + hold(low, 6)


def test_counts_clean_reps() -> None:
    c, clk = RepCounter(cfg()), Clock()
    state = clk.feed(c, curl() * 3)
    assert state.reps == 3
    assert state.phase is RepPhase.READY
    assert state.last_event is not None and state.last_event.kind is RepEventKind.REP_COMPLETED
    assert state.last_event.peak_deg == pytest.approx(130, abs=0.5)


def test_waits_for_start_position_before_counting() -> None:
    c, clk = RepCounter(cfg()), Clock()
    # Starts mid-movement at the target: must not count a half rep.
    state = clk.feed(c, hold(120, 10) + ramp(120, 10, 30) + hold(10, 6))
    assert state.reps == 0 and state.phase is RepPhase.READY
    assert clk.feed(c, curl()).reps == 1


def test_oscillation_around_thresholds_does_not_count() -> None:
    c, clk = RepCounter(cfg()), Clock()
    clk.feed(c, hold(10, 6))
    # Jitter ±5° around the start threshold (inside the hysteresis band) never
    # starts a rep …
    state = clk.feed(c, [30 + (5 if i % 2 else -5) for i in range(60)])
    assert state.phase is RepPhase.READY
    # … and once the target is reached, ±5° jitter around the target threshold
    # never leaves it (exit needs < target − hysteresis).
    clk.feed(c, ramp(30, 115, 20) + hold(115, 6))
    state = clk.feed(c, [110 + (5 if i % 2 else -5) for i in range(60)])
    assert state.reps == 0
    assert state.phase is RepPhase.AT_TARGET
    assert state.last_event is None
    assert clk.feed(c, ramp(110, 10, 30) + hold(10, 6)).reps == 1


def test_single_frame_spikes_are_ignored() -> None:
    c, clk = RepCounter(cfg()), Clock()
    state = clk.feed(c, hold(10, 10) + [150] + hold(10, 10) + [150] + hold(10, 10))
    assert state.reps == 0
    assert state.phase is RepPhase.READY
    assert state.last_event is None


def test_partial_rep_reports_target_not_reached() -> None:
    c, clk = RepCounter(cfg()), Clock()
    state = clk.feed(c, curl(high=90))
    assert state.reps == 0
    assert state.last_event is not None
    assert state.last_event.kind is RepEventKind.TARGET_NOT_REACHED
    assert state.last_event.peak_deg == pytest.approx(90, abs=0.5)


def test_short_tracking_gap_mid_rep_is_tolerated() -> None:
    c, clk = RepCounter(cfg()), Clock()
    seq = curl()
    seq[40:50] = [None] * 10  # 330 ms dropout near the top
    assert clk.feed(c, seq).reps == 1


def test_long_tracking_gap_abandons_rep() -> None:
    c, clk = RepCounter(cfg()), Clock()
    seq = curl()
    seq[30:60] = [None] * 30  # ~1 s dropout
    state = clk.feed(c, seq)
    assert state.reps == 0
    kinds = state.last_event.kind if state.last_event else None
    assert kinds is RepEventKind.TRACKING_LOST
    # Recovers normally afterwards.
    assert clk.feed(c, curl()).reps == 1


def test_gap_without_any_frames_is_detected_on_next_sample() -> None:
    c, clk = RepCounter(cfg()), Clock()
    clk.feed(c, hold(10, 6) + ramp(10, 80, 10))
    assert c.phase is RepPhase.MOVING
    clk.t += 2000  # no frames at all for 2 s (e.g. pipeline stalled)
    state = clk.feed(c, [80])
    assert state.phase is RepPhase.WAITING_FOR_START
    assert state.last_event is not None and state.last_event.kind is RepEventKind.TRACKING_LOST


def test_too_fast_rep_is_not_counted() -> None:
    c, clk = RepCounter(cfg(min_rep_ms=2000)), Clock()
    state = clk.feed(c, curl(frames_each_way=12))  # ~1 s total
    assert state.reps == 0
    assert state.last_event is not None and state.last_event.kind is RepEventKind.TOO_FAST


def test_rep_timeout_abandons() -> None:
    c, clk = RepCounter(cfg(max_rep_ms=2000)), Clock()
    state = clk.feed(c, hold(10, 6) + ramp(10, 120, 20) + hold(120, 90))
    assert state.phase is RepPhase.WAITING_FOR_START
    assert state.last_event is not None and state.last_event.kind is RepEventKind.TIMED_OUT
    assert clk.feed(c, ramp(120, 10, 20) + hold(10, 6)).reps == 0


def test_required_hold() -> None:
    c, clk = RepCounter(cfg(min_hold_ms=1000)), Clock()
    # Brief touch of the target (~200 ms) then back down.
    state = clk.feed(c, hold(10, 6) + ramp(10, 120, 20) + hold(120, 6) + ramp(120, 10, 20) + hold(10, 6))
    assert state.reps == 0
    # The rep's final outcome keeps the real reason: the target WAS reached,
    # but not held (regression: this used to be reported as target_not_reached).
    assert state.last_event is not None and state.last_event.kind is RepEventKind.HOLD_TOO_SHORT
    assert state.last_event.peak_deg == pytest.approx(120, abs=0.5)

    c2, clk2 = RepCounter(cfg(min_hold_ms=1000)), Clock()
    mid = clk2.feed(c2, hold(10, 6) + ramp(10, 120, 20) + hold(120, 20))
    assert mid.phase is RepPhase.AT_TARGET and 500 < mid.hold_ms < 1000
    state = clk2.feed(c2, hold(120, 20) + ramp(120, 10, 20) + hold(10, 6))
    assert state.reps == 1
    assert state.last_event is not None and state.last_event.hold_ms is not None
    assert state.last_event.hold_ms >= 1000


def test_hold_too_short_event_is_emitted_on_leaving_target() -> None:
    c, clk = RepCounter(cfg(min_hold_ms=1000)), Clock()
    state = clk.feed(c, hold(10, 6) + ramp(10, 120, 20) + hold(120, 6) + ramp(120, 80, 8) + hold(80, 4))
    assert state.last_event is not None and state.last_event.kind is RepEventKind.HOLD_TOO_SHORT
    assert state.phase is RepPhase.MOVING


def test_decreasing_direction_sit_to_stand() -> None:
    # Knee flexion: seated ~90 (start) → standing ~5 (target) → seated.
    c, clk = RepCounter(cfg(start_deg=65, target_deg=20, min_rep_ms=1200)), Clock()
    sit_stand_sit = hold(90, 10) + ramp(90, 5, 40) + hold(5, 10) + ramp(5, 90, 40) + hold(90, 10)
    state = clk.feed(c, sit_stand_sit * 2)
    assert state.reps == 2
    assert state.last_event is not None and state.last_event.peak_deg == pytest.approx(5, abs=0.5)


def test_progress_is_normalized_in_both_directions() -> None:
    up = RepCounter(cfg(start_deg=30, target_deg=110))
    assert up.update(70, 0).progress == pytest.approx(0.5)
    assert up.update(200, 33).progress == 1.0
    down = RepCounter(cfg(start_deg=65, target_deg=20))
    assert down.update(42.5, 0).progress == pytest.approx(0.5)
    assert down.update(None, 33).progress is None


def test_noisy_realistic_signal_counts_exactly() -> None:
    rng = np.random.default_rng(3)
    c, clk = RepCounter(cfg()), Clock()
    seq = [v + rng.normal(0, 3.0) if v is not None else None for v in curl() * 5]
    for i in rng.choice(len(seq), 25, replace=False):  # scattered single-frame dropouts
        seq[i] = None
    assert clk.feed(c, seq).reps == 5


def test_event_sequence_numbers_increase() -> None:
    c, clk = RepCounter(cfg()), Clock()
    clk.feed(c, curl())
    first = c.update(10, clk.t).last_event
    clk.feed(c, curl(high=80))
    second = c.update(10, clk.t).last_event
    assert first is not None and second is not None and second.seq == first.seq + 1


@pytest.mark.parametrize(
    "kw",
    [
        {"start_deg": 30, "target_deg": 40},  # closer than 2×hysteresis
        {"min_rep_ms": 5000, "max_rep_ms": 4000},
        {"target_deg": 200},
    ],
)
def test_invalid_configs_rejected(kw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        cfg(**kw)
