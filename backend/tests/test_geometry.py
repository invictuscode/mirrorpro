from __future__ import annotations

import math

import numpy as np
import pytest

from app.biomechanics.geometry import angle_at


@pytest.mark.parametrize(
    ("a", "b", "c", "expected"),
    [
        ([1, 0], [0, 0], [0, 1], 90.0),
        ([1, 0], [0, 0], [-1, 0], 180.0),
        ([1, 0], [0, 0], [2, 0], 0.0),
        ([1, 0], [0, 0], [1, 1], 45.0),
        ([1, 0], [0, 0], [-1, 1], 135.0),
        ([1, 0], [0, 0], [0.5, math.sqrt(3) / 2], 60.0),
        # Translation and scale do not matter.
        ([12, 5], [10, 5], [10, 105], 90.0),
        # 3D
        ([1, 0, 0], [0, 0, 0], [0, 0, 1], 90.0),
        ([1, 1, 0], [0, 0, 0], [0, 0, 1], 90.0),
        ([1, 0, 0], [0, 0, 0], [1, 1, 1], math.degrees(math.acos(1 / math.sqrt(3)))),
    ],
)
def test_known_angles(a: list[float], b: list[float], c: list[float], expected: float) -> None:
    result = angle_at(a, b, c)
    assert result is not None
    assert result == pytest.approx(expected, abs=1e-9)


def test_order_of_end_points_is_irrelevant() -> None:
    assert angle_at([3, 1], [0, 0], [1, 4]) == pytest.approx(angle_at([1, 4], [0, 0], [3, 1]))


def test_accurate_near_straight_line() -> None:
    # acos-based formulas lose precision here; atan2 must not.
    result = angle_at([-1, 0], [0, 0], [1, 1e-7])
    assert result is not None
    assert 180.0 - result == pytest.approx(math.degrees(1e-7), rel=1e-3)


@pytest.mark.parametrize(
    ("a", "b", "c"),
    [
        ([0, 0], [0, 0], [1, 0]),  # A coincides with vertex
        ([1, 0], [0, 0], [0, 0]),  # C coincides with vertex
        ([0, 0, 0], [0, 0, 0], [0, 0, 0]),
    ],
)
def test_degenerate_segments_return_none(a: list[float], b: list[float], c: list[float]) -> None:
    assert angle_at(a, b, c) is None


def test_segment_shorter_than_minimum_returns_none() -> None:
    assert angle_at([0.001, 0], [0, 0], [0, 1], min_segment_length=0.01) is None
    assert angle_at([0.02, 0], [0, 0], [0, 1], min_segment_length=0.01) == pytest.approx(90.0)


@pytest.mark.parametrize(
    ("a", "b", "c"),
    [
        ([np.nan, 0], [0, 0], [0, 1]),
        ([1, 0], [np.inf, 0], [0, 1]),
        ([1, 0], [0, 0], [0, 1, 0]),  # mixed 2D / 3D
        ([1], [0], [2]),  # 1D
        ([1, 0, 0, 0], [0, 0, 0, 0], [0, 1, 0, 0]),  # 4D
        ([[1, 0]], [[0, 0]], [[0, 1]]),  # wrong rank
    ],
)
def test_invalid_coordinates_return_none(a: list[float], b: list[float], c: list[float]) -> None:
    assert angle_at(a, b, c) is None
