"""Runtime configuration.

All settings come from environment variables prefixed with ``PTM_`` so the same
code runs on a MacBook and a Raspberry Pi with different values. A *profile*
(``PTM_PROFILE``) supplies a coherent set of defaults for a hardware class;
individual ``PTM_*`` variables override the profile.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.biomechanics import AngleAnalyzerConfig, AngleSpace, FilterKind

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PREFIX = "PTM_"


class CameraBackend(StrEnum):
    """OpenCV capture backend. ``auto`` lets OpenCV choose (AVFoundation on
    macOS, V4L2 on Linux)."""

    AUTO = "auto"
    AVFOUNDATION = "avfoundation"
    V4L2 = "v4l2"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str = "dev"

    # Server. Bind to loopback by default: camera-derived data must not be
    # reachable from the network unless deliberately configured.
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # Camera
    camera_index: int = Field(default=0, ge=0)
    camera_backend: CameraBackend = CameraBackend.AUTO
    capture_width: int = Field(default=1280, ge=160, le=3840)
    capture_height: int = Field(default=720, ge=120, le=2160)
    capture_fps: int = Field(default=30, ge=1, le=120)
    # Consecutive failed reads tolerated before the camera is declared lost.
    # macOS commonly returns a few empty frames while the device warms up.
    max_consecutive_read_failures: int = Field(default=60, ge=1)

    # Pose model
    model_path: Path = PROJECT_ROOT / "models" / "pose_landmarker_full.task"
    min_pose_detection_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    min_pose_presence_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    min_tracking_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # Processing budget. Frames are downscaled to ``inference_width`` (aspect
    # preserved) before inference; ``max_inference_fps`` = 0 means unlimited.
    inference_width: int = Field(default=640, ge=128, le=1920)
    max_inference_fps: float = Field(default=30.0, ge=0.0, le=120.0)

    # Preview video sent to the local UI. Disable on a real mirror, where the
    # reflection replaces the video and only landmarks are needed.
    preview_enabled: bool = True
    preview_width: int = Field(default=640, ge=160, le=1920)
    preview_jpeg_quality: int = Field(default=70, ge=10, le=95)

    # Joint-angle estimation (experimental; see docs/JOINT_ANGLES.md).
    angle_space: AngleSpace = AngleSpace.IMAGE
    angle_min_visibility: float = Field(default=0.5, ge=0.0, le=1.0)
    angle_filter: FilterKind = FilterKind.ONE_EURO
    angle_filter_min_cutoff_hz: float = Field(default=1.0, gt=0.0, le=30.0)
    angle_filter_beta: float = Field(default=0.02, ge=0.0, le=10.0)
    angle_filter_ema_alpha: float = Field(default=0.3, gt=0.0, le=1.0)
    angle_max_gap_ms: int = Field(default=500, ge=0, le=10_000)

    # Directory of exercise definition JSON files; None = built-in presets.
    exercise_dir: Path | None = None
    # Local data (custom exercises; later the SQLite database). Git-ignored.
    data_dir: Path = PROJECT_ROOT / "data"

    def angle_config(self) -> AngleAnalyzerConfig:
        return AngleAnalyzerConfig(
            space=self.angle_space,
            min_visibility=self.angle_min_visibility,
            filter=self.angle_filter,
            one_euro_min_cutoff_hz=self.angle_filter_min_cutoff_hz,
            one_euro_beta=self.angle_filter_beta,
            ema_alpha=self.angle_filter_ema_alpha,
            max_gap_ms=self.angle_max_gap_ms,
        )


# Defaults per hardware class. Values for "pi" are conservative starting points
# for CPU-constrained boards, NOT measured results; tune them on real hardware.
PROFILES: dict[str, dict[str, Any]] = {
    "dev": {},
    "pi": {
        "model_path": PROJECT_ROOT / "models" / "pose_landmarker_lite.task",
        "capture_width": 640,
        "capture_height": 480,
        "inference_width": 480,
        "max_inference_fps": 15.0,
        "preview_width": 480,
        "preview_jpeg_quality": 60,
    },
}


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    profile = env.get(f"{ENV_PREFIX}PROFILE", "dev")
    if profile not in PROFILES:
        raise ConfigError(
            f"Unknown {ENV_PREFIX}PROFILE={profile!r}; expected one of {sorted(PROFILES)}"
        )

    values: dict[str, Any] = {"profile": profile, **PROFILES[profile]}
    for name in Settings.model_fields:
        raw = env.get(f"{ENV_PREFIX}{name.upper()}")
        if raw is not None and name != "profile":
            values[name] = raw

    try:
        settings = Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc

    for name in ("model_path", "data_dir"):
        path: Path = getattr(settings, name)
        if not path.is_absolute():
            settings = settings.model_copy(update={name: (PROJECT_ROOT / path).resolve()})
    return settings
