from __future__ import annotations

import numpy as np
import pytest

from app.biomechanics.filters import EmaFilter, OneEuroFilter, PassThroughFilter


def test_one_euro_first_sample_passes_through_and_constant_stays_constant() -> None:
    f = OneEuroFilter(min_cutoff_hz=1.0, beta=0.02)
    assert f.update(42.0, 0) == 42.0
    for i in range(1, 30):
        assert f.update(42.0, i * 33) == pytest.approx(42.0)


def test_one_euro_reduces_jitter_at_rest() -> None:
    rng = np.random.default_rng(0)
    noisy = 90.0 + rng.normal(0, 3.0, 300)
    f = OneEuroFilter(min_cutoff_hz=1.0, beta=0.02)
    out = np.array([f.update(float(v), i * 33) for i, v in enumerate(noisy)])
    # Ignore the warm-up, then compare spread.
    assert np.std(out[50:]) < 0.5 * np.std(noisy[50:])
    assert np.mean(out[50:]) == pytest.approx(90.0, abs=1.0)


def test_one_euro_tracks_motion_with_less_lag_than_heavy_ema() -> None:
    # A 60°/s ramp sampled at 30 Hz.
    t = np.arange(0, 90) * 33
    ramp = 30.0 + 0.06 * t
    one_euro = OneEuroFilter(min_cutoff_hz=1.0, beta=0.05)
    ema = EmaFilter(alpha=0.1)
    oe = [one_euro.update(float(v), int(ts)) for v, ts in zip(ramp, t)]
    em = [ema.update(float(v), int(ts)) for v, ts in zip(ramp, t)]
    assert abs(ramp[-1] - oe[-1]) < abs(ramp[-1] - em[-1])


def test_one_euro_ignores_non_increasing_timestamps() -> None:
    f = OneEuroFilter(min_cutoff_hz=1.0, beta=0.0)
    f.update(10.0, 100)
    assert f.update(50.0, 100) == 10.0
    assert f.update(50.0, 90) == 10.0


def test_reset_forgets_history() -> None:
    for f in (OneEuroFilter(1.0, 0.02), EmaFilter(0.2)):
        f.update(10.0, 0)
        f.update(10.0, 33)
        f.reset()
        assert f.update(170.0, 66) == 170.0


def test_ema_and_passthrough() -> None:
    ema = EmaFilter(alpha=0.5)
    assert ema.update(0.0, 0) == 0.0
    assert ema.update(10.0, 1) == 5.0
    assert PassThroughFilter().update(7.0, 0) == 7.0


@pytest.mark.parametrize("kwargs", [{"min_cutoff_hz": 0, "beta": 0}, {"min_cutoff_hz": 1, "beta": -1}])
def test_invalid_filter_parameters(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        OneEuroFilter(**kwargs)
    with pytest.raises(ValueError):
        EmaFilter(alpha=1.5)
