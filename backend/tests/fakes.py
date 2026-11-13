"""Test doubles for the camera and pose detector."""

from __future__ import annotations

import threading
import time

import numpy as np

from app.camera import CameraError
from app.config import Settings
from app.pose.detector import PoseEstimate


class FakeCamera:
    """Produces synthetic BGR frames at ``fps``. ``fail_after`` makes every read
    after that many frames return ``None`` (simulates a disconnected camera)."""

    instances: list[FakeCamera] = []

    def __init__(
        self,
        settings: Settings,
        *,
        fps: float = 100.0,
        fail_open: bool = False,
        fail_after: int | None = None,
        size: tuple[int, int] = (480, 640),
    ) -> None:
        self.settings = settings
        self.fps = fps
        self.fail_open = fail_open
        self.fail_after = fail_after
        self.size = size
        self.is_open = False
        self.close_calls = 0
        self.reads = 0
        FakeCamera.instances.append(self)

    @property
    def description(self) -> str:
        return "fake camera"

    def open(self) -> None:
        if self.fail_open:
            raise CameraError("fake camera refused to open")
        self.is_open = True

    def read(self) -> np.ndarray | None:
        time.sleep(1.0 / self.fps)
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return None
        frame = np.zeros((*self.size, 3), np.uint8)
        frame[:, :, 1] = self.reads % 255
        return frame

    def close(self) -> None:
        self.is_open = False
        self.close_calls += 1


def landmark_array(visibility: float = 0.9) -> np.ndarray:
    lm = np.zeros((33, 5), np.float32)
    lm[:, 0] = np.linspace(0.3, 0.7, 33)
    lm[:, 1] = np.linspace(0.1, 0.9, 33)
    lm[:, 3] = visibility
    lm[:, 4] = visibility
    return lm


class FakeDetector:
    """Detects a person on even calls and nobody on odd calls; records timestamps."""

    def __init__(self, settings: Settings, *, raise_on_call: int | None = None) -> None:
        self.calls = 0
        self.timestamps: list[int] = []
        self.shapes: list[tuple[int, ...]] = []
        self.closed = False
        self.raise_on_call = raise_on_call
        self._lock = threading.Lock()

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> PoseEstimate:
        with self._lock:
            self.calls += 1
            self.timestamps.append(timestamp_ms)
            self.shapes.append(rgb.shape)
            if self.raise_on_call is not None and self.calls >= self.raise_on_call:
                raise RuntimeError("fake inference failure")
            if self.calls % 2 == 0:
                return PoseEstimate(None, None)
            lm = landmark_array()
            return PoseEstimate(lm, lm.copy())

    def close(self) -> None:
        self.closed = True


class CurlingDetector:
    """Synthetic person doing continuous right-arm curls (elbow flexion swings
    between ~5° and ~125° in normalized coordinates every ``period_ms``), driven
    by the frame timestamp. After aspect correction the peak is ~120°."""

    def __init__(self, settings: Settings, *, period_ms: float = 1200.0) -> None:
        self.period_ms = period_ms

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> PoseEstimate:
        import math

        from tests.poses import standing_pose, with_elbow_flexion

        flexion = 65.0 - 60.0 * math.cos(2 * math.pi * timestamp_ms / self.period_ms)
        lm = with_elbow_flexion(standing_pose(), "right", flexion)
        return PoseEstimate(lm, lm.copy())

    def close(self) -> None:
        pass
