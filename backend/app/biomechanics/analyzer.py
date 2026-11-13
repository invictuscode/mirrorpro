"""Per-frame joint-angle estimation with reliability gating and smoothing.

Input is plain landmark arrays (see ``app.pose.PoseEstimate``); this module has
no camera, model or UI dependencies and is driven entirely by its arguments,
so it can be unit-tested with hand-built coordinates.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from app.biomechanics.filters import EmaFilter, OneEuroFilter, PassThroughFilter, ScalarFilter
from app.biomechanics.geometry import angle_at
from app.biomechanics.joints import JOINT_ANGLES, JointAngleDefinition

# Landmark array columns (same layout as app.pose.detector).
_X, _Y, _VIS = 0, 1, 3


class AngleSpace(StrEnum):
    WORLD = "world"  # MediaPipe 3D world landmarks (metres, model-estimated depth)
    IMAGE = "image"  # 2D image plane, aspect-corrected pixels


class FilterKind(StrEnum):
    ONE_EURO = "one_euro"
    EMA = "ema"
    NONE = "none"


class AngleStatus(StrEnum):
    OK = "ok"
    NO_PERSON = "no_person"
    LOW_VISIBILITY = "low_visibility"
    OUT_OF_FRAME = "out_of_frame"
    DEGENERATE = "degenerate"  # segment too short / undefined geometry
    UNAVAILABLE = "unavailable"  # required coordinate space missing from model output


@dataclass(frozen=True, slots=True)
class AngleAnalyzerConfig:
    space: AngleSpace = AngleSpace.IMAGE
    min_visibility: float = 0.5
    # Landmarks this far outside [0, 1] in image coords are treated as off-frame.
    frame_margin: float = 0.02
    filter: FilterKind = FilterKind.ONE_EURO
    one_euro_min_cutoff_hz: float = 1.0
    one_euro_beta: float = 0.02
    ema_alpha: float = 0.3
    # After this long without a valid measurement, smoothing restarts so old
    # values are never blended into a new movement.
    max_gap_ms: int = 500
    # Minimum segment lengths below which an angle is considered undefined.
    min_segment_world_m: float = 0.03
    min_segment_image_frac: float = 0.01  # fraction of the image diagonal


@dataclass(frozen=True, slots=True)
class AngleResult:
    id: str
    status: AngleStatus
    value_deg: float | None  # smoothed; None unless status is OK
    raw_deg: float | None  # unsmoothed this frame; None unless status is OK
    confidence: float | None  # min visibility of the three landmarks, if a person was detected


def make_filter(cfg: AngleAnalyzerConfig) -> ScalarFilter:
    match cfg.filter:
        case FilterKind.ONE_EURO:
            return OneEuroFilter(cfg.one_euro_min_cutoff_hz, cfg.one_euro_beta)
        case FilterKind.EMA:
            return EmaFilter(cfg.ema_alpha)
        case FilterKind.NONE:
            return PassThroughFilter()


@dataclass(slots=True)
class _Track:
    filter: ScalarFilter
    last_valid_ms: int | None = None


class AngleAnalyzer:
    """Stateful (holds filter history). Create one per tracking run and call
    :meth:`update` from a single thread."""

    def __init__(
        self,
        config: AngleAnalyzerConfig,
        definitions: Sequence[JointAngleDefinition] = JOINT_ANGLES,
        filter_factory: Callable[[AngleAnalyzerConfig], ScalarFilter] = make_filter,
    ) -> None:
        self._cfg = config
        self._defs = tuple(definitions)
        self._tracks = {d.id: _Track(filter_factory(config)) for d in self._defs}

    def update(
        self,
        landmarks: np.ndarray | None,
        world_landmarks: np.ndarray | None,
        timestamp_ms: int,
        image_size: tuple[int, int],
    ) -> list[AngleResult]:
        """``landmarks``: (33, ≥4) normalized image landmarks, or None.
        ``world_landmarks``: (33, ≥3) world landmarks, or None.
        ``image_size``: (width, height) of the frame the landmarks refer to."""
        return [self._measure(d, landmarks, world_landmarks, timestamp_ms, image_size) for d in self._defs]

    def _measure(
        self,
        d: JointAngleDefinition,
        lms: np.ndarray | None,
        world: np.ndarray | None,
        ts: int,
        image_size: tuple[int, int],
    ) -> AngleResult:
        if lms is None:
            return AngleResult(d.id, AngleStatus.NO_PERSON, None, None, None)
        idx = list(d.landmarks)
        pts = lms[idx]
        confidence = float(np.min(pts[:, _VIS]))
        if not np.isfinite(confidence) or confidence < self._cfg.min_visibility:
            return AngleResult(d.id, AngleStatus.LOW_VISIBILITY, None, None, confidence)
        m = self._cfg.frame_margin
        xy = pts[:, [_X, _Y]]
        if not np.all(np.isfinite(xy)) or np.any(xy < -m) or np.any(xy > 1 + m):
            return AngleResult(d.id, AngleStatus.OUT_OF_FRAME, None, None, confidence)

        included = self._included_angle(idx, lms, world, image_size)
        if included is None:
            status = AngleStatus.UNAVAILABLE if self._needs_world(world) else AngleStatus.DEGENERATE
            return AngleResult(d.id, status, None, None, confidence)

        raw = d.to_value(included)
        track = self._tracks[d.id]
        if track.last_valid_ms is None or ts - track.last_valid_ms > self._cfg.max_gap_ms:
            track.filter.reset()
        track.last_valid_ms = ts
        smoothed = track.filter.update(raw, ts)
        return AngleResult(d.id, AngleStatus.OK, smoothed, raw, confidence)

    def _needs_world(self, world: np.ndarray | None) -> bool:
        return self._cfg.space is AngleSpace.WORLD and world is None

    def _included_angle(
        self, idx: list[int], lms: np.ndarray, world: np.ndarray | None, image_size: tuple[int, int]
    ) -> float | None:
        if self._cfg.space is AngleSpace.WORLD:
            if world is None:
                return None
            a, b, c = (world[i, :3] for i in idx)
            return angle_at(a, b, c, self._cfg.min_segment_world_m)
        # Image space: scale normalized coords to pixels so angles are not
        # distorted by a non-square frame.
        w, h = image_size
        scale = np.array([w, h], dtype=np.float64)
        a, b, c = (lms[i, [_X, _Y]] * scale for i in idx)
        return angle_at(a, b, c, self._cfg.min_segment_image_frac * float(np.hypot(w, h)))
