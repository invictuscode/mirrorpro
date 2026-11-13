"""Capture demonstrations as angle series, and keep recent ones for review.

Live recording listens to the tracking pipeline's per-frame angles; no image
data is ever retained. Demonstrations live in memory only (lost on restart)
unless the therapist consents to store the angle data with a draft.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Literal

from app.authoring.series import AngleSeries
from app.biomechanics import AngleResult, AngleSpace, AngleStatus
from app.schemas.authoring import DemonstrationInfo, LiveRecordingStatus

MIN_FRAMES = 15
DEFAULT_MAX_MS = 60_000


class RecordingError(Exception):
    """Recording request not possible in the current state (HTTP 409/422)."""


def person_fraction(frames: Sequence[tuple[int, Sequence[AngleResult]]]) -> float:
    if not frames:
        return 0.0
    seen = sum(1 for _, angles in frames if any(a.status is not AngleStatus.NO_PERSON for a in angles))
    return seen / len(frames)


class DemonstrationCache:
    """Most recent demonstrations, bounded so memory cannot grow without limit."""

    def __init__(self, capacity: int = 8) -> None:
        self._capacity = capacity
        self._items: OrderedDict[str, tuple[DemonstrationInfo, AngleSeries]] = OrderedDict()
        self._lock = threading.Lock()

    def add(
        self,
        source: Literal["live", "upload"],
        series: AngleSeries,
        person_frac: float,
    ) -> DemonstrationInfo:
        info = DemonstrationInfo(
            demo_id=f"demo_{secrets.token_hex(6)}",
            source=source,
            angle_space=series.angle_space,
            duration_ms=series.duration_ms,
            frames=series.n_frames,
            person_fraction=round(person_frac, 3),
        )
        with self._lock:
            self._items[info.demo_id] = (info, series)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return info

    def get(self, demo_id: str) -> tuple[DemonstrationInfo, AngleSeries] | None:
        with self._lock:
            return self._items.get(demo_id)


class LiveRecorder:
    def __init__(
        self,
        cache: DemonstrationCache,
        max_ms: int = DEFAULT_MAX_MS,
        clock: Callable[[], int] = lambda: time.monotonic_ns() // 1_000_000,
    ) -> None:
        self._cache = cache
        self._max_ms = max_ms
        self._clock = clock
        self._lock = threading.Lock()
        self._recording = False
        self._started_ms = 0
        self._frames: list[tuple[int, Sequence[AngleResult]]] = []
        self._space = AngleSpace.IMAGE

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> LiveRecordingStatus:
        with self._lock:
            if self._recording:
                raise RecordingError("A recording is already in progress")
            self._recording = True
            self._started_ms = self._clock()
            self._frames = []
            return self._status()

    def status(self) -> LiveRecordingStatus:
        with self._lock:
            return self._status()

    def cancel(self) -> None:
        with self._lock:
            self._recording = False
            self._frames = []

    def stop(self) -> DemonstrationInfo:
        with self._lock:
            if not self._recording:
                raise RecordingError("No recording in progress")
            self._recording = False
            frames, self._frames = self._frames, []
        if len(frames) < MIN_FRAMES:
            raise RecordingError(
                f"Only {len(frames)} frames were captured. Is the camera running? Record for at least a few seconds."
            )
        frac = person_fraction(frames)
        if frac < 0.5:
            raise RecordingError(
                f"A person was detected in only {frac:.0%} of the recording. Stand fully in view and try again."
            )
        return self._cache.add("live", AngleSeries.from_frames(frames, self._space), frac)

    # Inference thread ------------------------------------------------------
    def on_frame(self, timestamp_ms: int, angles: Sequence[AngleResult], space: AngleSpace) -> None:
        with self._lock:
            if not self._recording or self._clock() - self._started_ms > self._max_ms:
                return  # capped at max length; stop() still returns what was captured
            self._space = space
            self._frames.append((timestamp_ms, list(angles)))

    def _status(self) -> LiveRecordingStatus:
        elapsed = min(self._clock() - self._started_ms, self._max_ms) if self._recording else 0
        return LiveRecordingStatus(recording=self._recording, elapsed_ms=elapsed, frames=len(self._frames), max_ms=self._max_ms)
