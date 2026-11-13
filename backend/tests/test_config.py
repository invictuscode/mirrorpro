from __future__ import annotations

import pytest

from app.config import PROJECT_ROOT, CameraBackend, ConfigError, load_settings


def test_defaults_are_loopback_and_full_model() -> None:
    s = load_settings({})
    assert s.profile == "dev"
    assert s.host == "127.0.0.1"
    assert s.model_path.name == "pose_landmarker_full.task"
    assert s.preview_enabled is True


def test_pi_profile_uses_lite_model_and_lower_budget() -> None:
    s = load_settings({"PTM_PROFILE": "pi"})
    assert s.model_path.name == "pose_landmarker_lite.task"
    assert s.max_inference_fps == 15.0
    assert s.capture_width == 640


def test_env_overrides_profile() -> None:
    s = load_settings(
        {
            "PTM_PROFILE": "pi",
            "PTM_MAX_INFERENCE_FPS": "10",
            "PTM_CAMERA_BACKEND": "v4l2",
            "PTM_PREVIEW_ENABLED": "false",
        }
    )
    assert s.max_inference_fps == 10.0
    assert s.camera_backend is CameraBackend.V4L2
    assert s.preview_enabled is False


def test_relative_model_path_resolves_against_project_root() -> None:
    s = load_settings({"PTM_MODEL_PATH": "models/x.task"})
    assert s.model_path == PROJECT_ROOT / "models" / "x.task"


@pytest.mark.parametrize(
    "env",
    [
        {"PTM_PROFILE": "toaster"},
        {"PTM_PORT": "0"},
        {"PTM_CAMERA_INDEX": "-1"},
        {"PTM_PREVIEW_JPEG_QUALITY": "100"},
        {"PTM_CAMERA_BACKEND": "directshow"},
        {"PTM_MIN_TRACKING_CONFIDENCE": "1.5"},
        {"PTM_CAPTURE_WIDTH": "wide"},
    ],
)
def test_invalid_values_raise_config_error(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_settings(env)


def test_angle_settings_flow_into_analyzer_config() -> None:
    from app.biomechanics import AngleSpace, FilterKind

    s = load_settings({"PTM_ANGLE_SPACE": "image", "PTM_ANGLE_FILTER": "ema", "PTM_ANGLE_FILTER_EMA_ALPHA": "0.5"})
    cfg = s.angle_config()
    assert cfg.space is AngleSpace.IMAGE and cfg.filter is FilterKind.EMA and cfg.ema_alpha == 0.5


@pytest.mark.parametrize(
    "env",
    [{"PTM_ANGLE_SPACE": "4d"}, {"PTM_ANGLE_FILTER": "kalman"}, {"PTM_ANGLE_FILTER_MIN_CUTOFF_HZ": "0"}],
)
def test_invalid_angle_settings(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_settings(env)
