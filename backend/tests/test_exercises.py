from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.library import PRESETS_DIR, ExerciseLibrary, ExerciseLibraryError
from app.exercises.schema import (
    ExerciseDefinition,
    RepCountingOverrides,
    ReviewStatus,
    Side,
    SideMode,
    SignalConfig,
)
from app.exercises.tracker import ExerciseTracker, extract_signal


def load(exercise_id: str) -> ExerciseDefinition:
    d = ExerciseLibrary.from_directory().get(exercise_id)
    assert d is not None
    return d


def angle(id_: str, value: float | None, status: AngleStatus = AngleStatus.OK) -> AngleResult:
    return AngleResult(id_, status, value if status is AngleStatus.OK else None, value, 0.9)


# --- presets ---------------------------------------------------------------
def test_presets_load_and_are_labelled_as_unreviewed_demos() -> None:
    lib = ExerciseLibrary.from_directory()
    assert {d.id for d in lib} == {"jumping_jack_arms", "standing_arm_raise", "biceps_curl", "sit_to_stand", "mini_squat", "seated_knee_extension", "shoulder_flexion", "standing_march", "wall_pushup"}
    for d in lib:
        assert d.clinical_review.status is ReviewStatus.UNREVIEWED_DEMO
        assert d.is_demo
        # No invented clinical content in shipped demos.
        assert d.safety_notes == []
        assert d.clinical_review.reviewed_by is None


def test_preset_camera_views_match_their_movement_plane() -> None:
    assert load("biceps_curl").camera.view == "side"
    assert load("sit_to_stand").camera.view == "side"
    assert load("standing_arm_raise").camera.view == "front"
    # Movements in the sagittal plane are filmed side-on.
    for exercise_id in ("mini_squat", "seated_knee_extension", "shoulder_flexion", "standing_march", "wall_pushup"):
        assert load(exercise_id).camera.view == "side", exercise_id
    # Decreasing-angle exercises are recognised as such.
    assert not load("seated_knee_extension").rep_counting.increasing
    assert load("seated_knee_extension").rep_counting.min_hold_ms > 0
    assert not load("sit_to_stand").rep_counting.increasing


# --- library errors --------------------------------------------------------
def _write(dir_: Path, name: str, data: object) -> None:
    (dir_ / name).write_text(json.dumps(data) if not isinstance(data, str) else data)


def _preset_json(exercise_id: str) -> dict:
    return json.loads((PRESETS_DIR / f"{exercise_id}.json").read_text())


def test_invalid_file_is_a_loud_error_naming_the_file(tmp_path: Path) -> None:
    bad = _preset_json("biceps_curl") | {"signal": {"joint": "ankle_wiggle", "side_mode": "single", "default_side": "left"}}
    _write(tmp_path, "bad.json", bad)
    with pytest.raises(ExerciseLibraryError, match="bad.json"):
        ExerciseLibrary.from_directory(tmp_path)


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "broken.json", "{ not json")
    with pytest.raises(ExerciseLibraryError, match="broken.json"):
        ExerciseLibrary.from_directory(tmp_path)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "a.json", _preset_json("biceps_curl"))
    _write(tmp_path, "b.json", _preset_json("biceps_curl"))
    with pytest.raises(ExerciseLibraryError, match="duplicate"):
        ExerciseLibrary.from_directory(tmp_path)


@pytest.mark.parametrize(
    "patch",
    [
        {"relevant_landmarks": ["left_tail"]},
        {"clinical_review": {"status": "approved", "reviewed_by": None}},
        {"signal": {"joint": "elbow_flexion", "side_mode": "single"}},  # no default side
        {"id": "Has Spaces"},
        {"instructions": []},
        {"unexpected_field": 1},
    ],
)
def test_schema_rejects_invalid_definitions(patch: dict) -> None:
    with pytest.raises(ValueError):
        ExerciseDefinition.model_validate(_preset_json("biceps_curl") | patch)


# --- overrides -------------------------------------------------------------
def test_overrides_apply_and_validate() -> None:
    base = load("biceps_curl").rep_counting
    merged = RepCountingOverrides(target_deg=95, min_hold_ms=500).apply(base)
    assert (merged.start_deg, merged.target_deg, merged.min_hold_ms) == (base.start_deg, 95, 500)
    with pytest.raises(ValueError, match="2 × hysteresis"):
        RepCountingOverrides(target_deg=base.start_deg + 5).apply(base)
    with pytest.raises(ValueError, match="reverse"):
        RepCountingOverrides(target_deg=10).apply(base)  # below start: flips direction


# --- signal extraction -----------------------------------------------------
def test_single_side_signal_uses_only_that_side() -> None:
    sig = SignalConfig(joint="elbow_flexion", side_mode=SideMode.SINGLE, default_side=Side.RIGHT)
    angles = [angle("left_elbow_flexion", 100), angle("right_elbow_flexion", 40)]
    s = extract_signal(sig, Side.RIGHT, angles)
    assert s.value_deg == 40 and s.sides_used == (Side.RIGHT,)
    hidden = [angle("left_elbow_flexion", 100), angle("right_elbow_flexion", 40, AngleStatus.LOW_VISIBILITY)]
    assert extract_signal(sig, Side.RIGHT, hidden).value_deg is None, "never falls back to the other side"


def test_mean_of_visible_uses_whichever_sides_are_reliable() -> None:
    sig = SignalConfig(joint="knee_flexion", side_mode=SideMode.MEAN_OF_VISIBLE)
    both = [angle("left_knee_flexion", 80), angle("right_knee_flexion", 90)]
    assert extract_signal(sig, None, both).value_deg == 85
    one = [angle("left_knee_flexion", 80), angle("right_knee_flexion", 0, AngleStatus.OUT_OF_FRAME)]
    s = extract_signal(sig, None, one)
    assert s.value_deg == 80 and s.sides_used == (Side.LEFT,)
    none = [angle("left_knee_flexion", 0, AngleStatus.LOW_VISIBILITY)]
    assert extract_signal(sig, None, none).value_deg is None


# --- tracker ---------------------------------------------------------------
def test_tracker_side_rules() -> None:
    assert ExerciseTracker(load("biceps_curl")).side is Side.RIGHT  # preset default
    assert ExerciseTracker(load("biceps_curl"), Side.LEFT).side is Side.LEFT
    with pytest.raises(ValueError, match="both sides"):
        ExerciseTracker(load("sit_to_stand"), Side.LEFT)


def test_tracker_counts_from_angle_results() -> None:
    t = ExerciseTracker(load("biceps_curl"), Side.LEFT)
    ts = 0
    frame = None
    for v in [10] * 6 + list(range(10, 131, 4)) + [130] * 6 + list(range(130, 9, -4)) + [10] * 6:
        frame = t.update([angle("left_elbow_flexion", float(v)), angle("left_shoulder_elevation", 15.0)], ts)
        ts += 33
    assert frame is not None and frame.counter.reps == 1
    assert frame.exercise_id == "biceps_curl" and frame.sides_used == (Side.LEFT,)
