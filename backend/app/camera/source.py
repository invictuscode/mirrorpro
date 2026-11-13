"""Camera frame sources.

The pipeline depends only on the :class:`FrameSource` protocol so the OpenCV
implementation can be swapped (e.g. for a Picamera2 source on Raspberry Pi, or a
fake source in tests) without touching inference or API code.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

import cv2
import numpy as np

from app.config import CameraBackend, Settings

log = logging.getLogger(__name__)

_CV_BACKENDS: dict[CameraBackend, int] = {
    CameraBackend.AUTO: cv2.CAP_ANY,
    CameraBackend.AVFOUNDATION: cv2.CAP_AVFOUNDATION,
    CameraBackend.V4L2: cv2.CAP_V4L2,
}


class CameraError(RuntimeError):
    """Camera could not be opened or stopped delivering frames."""


class FrameSource(Protocol):
    def open(self) -> None:
        """Open the device. Raises :class:`CameraError` on failure."""

    def read(self) -> np.ndarray | None:
        """Return the next BGR frame, or ``None`` if a frame could not be read."""

    def close(self) -> None:
        """Release the device. Must be safe to call more than once."""

    @property
    def description(self) -> str: ...


def _open_failure_hint() -> str:
    if sys.platform == "darwin":
        return (
            "On macOS, allow camera access for the app that launched the backend "
            "(Terminal, iTerm, VS Code, …) in System Settings → Privacy & Security → "
            "Camera, then fully quit and reopen that app. Also check that no other "
            "app is using the camera."
        )
    return (
        "Check that the camera is connected, that the index is correct, and that "
        "the current user can access /dev/video* (e.g. is in the 'video' group)."
    )


class OpenCVCamera:
    """``cv2.VideoCapture`` wrapper. Not thread-safe: use from one thread."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cap: cv2.VideoCapture | None = None

    @property
    def description(self) -> str:
        s = self._settings
        return f"OpenCV camera #{s.camera_index} ({s.camera_backend.value})"

    def open(self) -> None:
        s = self._settings
        cap = cv2.VideoCapture(s.camera_index, _CV_BACKENDS[s.camera_backend])
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Could not open camera #{s.camera_index}. {_open_failure_hint()}"
            )
        # Requests only; the driver may choose the nearest supported mode.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, s.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, s.capture_height)
        cap.set(cv2.CAP_PROP_FPS, s.capture_fps)
        # Keep the driver queue short so we always process a recent frame.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        log.info(
            "Camera opened: %dx%d @ %.0f fps requested %dx%d @ %d",
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            cap.get(cv2.CAP_PROP_FPS),
            s.capture_width,
            s.capture_height,
            s.capture_fps,
        )
        self._cap = cap

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            raise CameraError("Camera is not open")
        ok, frame = self._cap.read()
        if not ok or frame is None or frame.size == 0:
            return None
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            log.info("Camera released")
