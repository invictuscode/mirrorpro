"""Tests against the real MediaPipe runtime and model asset (no camera)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import load_settings
from app.pose.detector import MediaPipePoseDetector, ModelNotFoundError
from app.pose.topology import CONNECTIONS, LANDMARK_NAMES

MODEL = load_settings({}).model_path


def test_topology_matches_installed_mediapipe() -> None:
    from mediapipe.tasks.python import vision

    assert [lm.name.lower() for lm in vision.PoseLandmark] == list(LANDMARK_NAMES)
    assert {(c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS} == set(CONNECTIONS)


def test_missing_model_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ModelNotFoundError, match="download_model.py"):
        MediaPipePoseDetector(load_settings({"PTM_MODEL_PATH": str(tmp_path / "nope.task")}))


@pytest.mark.skipif(not MODEL.is_file(), reason="model asset not downloaded")
def test_real_model_reports_no_person_on_empty_frames() -> None:
    detector = MediaPipePoseDetector(load_settings({}))
    try:
        for i in range(3):
            estimate = detector.detect(np.zeros((360, 640, 3), np.uint8), timestamp_ms=i * 33)
            assert not estimate.person_detected
            assert estimate.landmarks is None
    finally:
        detector.close()
