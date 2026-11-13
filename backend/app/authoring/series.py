"""Joint-angle time series extracted from a demonstration.

This is *derived* data (angles per frame), never video. It is kept in memory
for the review step and is only persisted when the therapist explicitly
consents (see ``CustomExerciseStore``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.biomechanics import AngleResult, AngleSpace, AngleStatus
from app.biomechanics.joints import JOINT_ANGLES

ANGLE_IDS: tuple[str, ...] = tuple(d.id for d in JOINT_ANGLES)


@dataclass(frozen=True)
class AngleSeries:
    timestamps_ms: np.ndarray  # int64, strictly increasing
    values: dict[str, np.ndarray]  # angle id → float64 degrees; NaN where unreliable
    angle_space: AngleSpace

    @property
    def n_frames(self) -> int:
        return int(self.timestamps_ms.size)

    @property
    def duration_ms(self) -> int:
        return int(self.timestamps_ms[-1] - self.timestamps_ms[0]) if self.n_frames > 1 else 0

    @classmethod
    def from_frames(cls, frames: Sequence[tuple[int, Sequence[AngleResult]]], space: AngleSpace) -> AngleSeries:
        """Build from (timestamp_ms, angle results) pairs. Only angles with
        status OK become numbers; anything else is NaN (unknown, not zero)."""
        ts = np.array([t for t, _ in frames], dtype=np.int64)
        values = {aid: np.full(len(frames), np.nan) for aid in ANGLE_IDS}
        for i, (_, angles) in enumerate(frames):
            for a in angles:
                if a.id in values and a.status is AngleStatus.OK and a.value_deg is not None:
                    values[a.id][i] = a.value_deg
        return cls(ts, values, space)

    # Persistence (consented storage only) ---------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            "angle_space": self.angle_space.value,
            "timestamps_ms": self.timestamps_ms.tolist(),
            "values": {k: [None if np.isnan(v) else round(float(v), 1) for v in arr] for k, arr in self.values.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AngleSeries:
        ts = np.array(data["timestamps_ms"], dtype=np.int64)
        values = {k: np.array([np.nan if v is None else v for v in arr], dtype=np.float64) for k, arr in data["values"].items()}
        return cls(ts, values, AngleSpace(data["angle_space"]))
