"""Pure vector maths for joint angles. No MediaPipe, camera or UI dependencies."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike


def _as_point(p: ArrayLike) -> np.ndarray | None:
    arr = np.asarray(p, dtype=np.float64)
    if arr.shape not in ((2,), (3,)) or not np.all(np.isfinite(arr)):
        return None
    return arr if arr.shape == (3,) else np.append(arr, 0.0)


def angle_at(a: ArrayLike, b: ArrayLike, c: ArrayLike, min_segment_length: float = 1e-9) -> float | None:
    """Angle ABC in degrees (0–180) at vertex ``b``, in 2D or 3D.

    Returns ``None`` instead of a misleading number when any point is
    malformed or non-finite, when the points mix 2D and 3D, or when either
    segment BA / BC is shorter than ``min_segment_length`` (the angle is
    undefined or dominated by noise).

    Uses ``atan2(|BA × BC|, BA · BC)``, which stays accurate near 0° and 180°
    where ``acos`` of a dot product loses precision.
    """
    shapes = {np.shape(a), np.shape(b), np.shape(c)}
    if len(shapes) != 1:
        return None
    pa, pb, pc = _as_point(a), _as_point(b), _as_point(c)
    if pa is None or pb is None or pc is None:
        return None
    ba, bc = pa - pb, pc - pb
    if np.linalg.norm(ba) < min_segment_length or np.linalg.norm(bc) < min_segment_length:
        return None
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(ba, bc))), float(np.dot(ba, bc))))
