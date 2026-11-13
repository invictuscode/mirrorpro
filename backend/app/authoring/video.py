"""Extract an angle series from an uploaded demonstration video.

The file is read from a temporary path and the caller deletes it as soon as
processing ends (see the upload endpoint); only derived angles are kept.
Uses the same pose model and angle analyzer as live tracking.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import cv2

from app.authoring.recorder import MIN_FRAMES, person_fraction
from app.authoring.series import AngleSeries
from app.biomechanics import AngleAnalyzer, AngleResult, AngleSpace
from app.config import Settings
from app.pipeline.tracking import DetectorFactory, resize_to_width

log = logging.getLogger(__name__)

MAX_DURATION_S = 120
MAX_FPS = 30.0


class VideoError(ValueError):
    """The video could not be used (unreadable, too long, no person)."""


def process_video(
    path: Path, settings: Settings, detector_factory: DetectorFactory, space: AngleSpace
) -> tuple[AngleSeries, float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise VideoError(
            "This video could not be opened. Use a common format such as MP4 (H.264). "
            "Some phone formats (e.g. HEVC .mov) may not be supported by OpenCV on this computer."
        )
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not 1.0 <= fps <= 240.0:
            fps = 30.0  # missing/garbage metadata: assume a typical rate
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if n and n / fps > MAX_DURATION_S:
            raise VideoError(f"The video is {n / fps:.0f} s long; the limit is {MAX_DURATION_S} s.")
        stride = max(1, round(fps / MAX_FPS))  # e.g. 60 fps → every 2nd frame
        frames: list[tuple[int, Sequence[AngleResult]]] = []
        detector = detector_factory(settings)
        analyzer = AngleAnalyzer(replace(settings.angle_config(), space=space))
        try:
            i = 0
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                if i % stride == 0:
                    ts = round(i * 1000 / fps)
                    if ts > MAX_DURATION_S * 1000:
                        raise VideoError(f"The video is longer than {MAX_DURATION_S} s.")
                    h, w = image.shape[:2]
                    rgb = cv2.cvtColor(resize_to_width(image, settings.inference_width), cv2.COLOR_BGR2RGB)
                    est = detector.detect(rgb, ts)
                    frames.append((ts, analyzer.update(est.landmarks, est.world_landmarks, ts, (w, h))))
                i += 1
        finally:
            detector.close()
    finally:
        cap.release()

    if len(frames) < MIN_FRAMES:
        raise VideoError(f"The video has only {len(frames)} usable frames; record at least a few seconds.")
    frac = person_fraction(frames)
    if frac < 0.5:
        raise VideoError(
            f"A person was detected in only {frac:.0%} of the video. The whole body should be visible and well lit."
        )
    log.info("Processed demonstration video: %d frames, person in %.0f%%", len(frames), 100 * frac)
    return AngleSeries.from_frames(frames, space), frac
