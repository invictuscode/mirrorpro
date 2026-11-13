"""Pose detection behind a small interface.

:class:`MediaPipePoseDetector` wraps the official MediaPipe Tasks
``PoseLandmarker`` in VIDEO running mode (which uses temporal tracking between
frames). Nothing outside this module imports MediaPipe, so the model or runtime
can be replaced without touching the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.config import Settings

log = logging.getLogger(__name__)

NUM_LANDMARKS = 33
# Columns of a landmark array.
X, Y, Z, VISIBILITY, PRESENCE = range(5)


@dataclass(frozen=True, slots=True)
class PoseEstimate:
    """Pose for one frame.

    ``landmarks``: (33, 5) float32 of normalized image coords
        [x, y, z, visibility, presence]. x/y are in [0, 1] relative to the image
        but may fall slightly outside when a joint is estimated off-frame. z is
        relative depth with the hip midpoint as origin (same scale as x); it is a
        rough estimate, not a metric depth.
    ``world_landmarks``: (33, 5) float32 in approximate metres, hip-centred.
        Retained for later joint-angle work; not sent to the UI.
    Both are ``None`` when no person is detected.
    """

    landmarks: np.ndarray | None
    world_landmarks: np.ndarray | None

    @property
    def person_detected(self) -> bool:
        return self.landmarks is not None


class ModelNotFoundError(FileNotFoundError):
    pass


class PoseDetector(Protocol):
    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> PoseEstimate:
        """Detect a pose in an RGB uint8 frame. ``timestamp_ms`` must strictly
        increase between calls."""

    def close(self) -> None: ...


def _to_array(landmarks: list) -> np.ndarray:  # list[NormalizedLandmark | Landmark]
    # visibility/presence can be None for some model outputs; treat as 0
    # (unknown) rather than inventing confidence.
    return np.array(
        [
            (lm.x, lm.y, lm.z, lm.visibility or 0.0, lm.presence or 0.0)
            for lm in landmarks
        ],
        dtype=np.float32,
    )


class MediaPipePoseDetector:
    def __init__(self, settings: Settings) -> None:
        # Imported lazily so tests and tools that never run inference don't pay
        # MediaPipe's import cost.
        from mediapipe.tasks.python import BaseOptions, vision

        if not settings.model_path.is_file():
            raise ModelNotFoundError(
                f"Pose model not found at {settings.model_path}. "
                "Run: backend/.venv/bin/python scripts/download_model.py"
            )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(settings.model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=settings.min_pose_detection_confidence,
            min_pose_presence_confidence=settings.min_pose_presence_confidence,
            min_tracking_confidence=settings.min_tracking_confidence,
            output_segmentation_masks=False,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        log.info("Loaded pose model %s", settings.model_path.name)

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> PoseEstimate:
        import mediapipe as mp

        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.pose_landmarks:
            return PoseEstimate(None, None)
        world = result.pose_world_landmarks[0] if result.pose_world_landmarks else None
        return PoseEstimate(
            landmarks=_to_array(result.pose_landmarks[0]),
            world_landmarks=_to_array(world) if world else None,
        )

    def close(self) -> None:
        self._landmarker.close()
