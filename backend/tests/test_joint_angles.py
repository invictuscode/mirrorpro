from __future__ import annotations

import math

import numpy as np
import pytest

from app.biomechanics import (
    JOINT_ANGLES,
    AngleAnalyzer,
    AngleAnalyzerConfig,
    AngleSpace,
    AngleStatus,
    FilterKind,
)
from app.biomechanics.joints import JOINT_ANGLES_BY_ID, Convention
from app.pose.topology import LANDMARK_NAMES
from tests.poses import I, standing_pose
SQUARE = (1000, 1000)
NO_FILTER = AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.NONE)


def by_id(results: list) -> dict:
    return {r.id: r for r in results}


def test_definitions_are_well_formed() -> None:
    ids = [d.id for d in JOINT_ANGLES]
    assert len(ids) == len(set(ids)) == 8
    for d in JOINT_ANGLES:
        assert len(set(d.landmarks)) == 3
        assert all(0 <= i < 33 for i in d.landmarks)
        # Left definitions use only left landmarks, right only right.
        assert all(LANDMARK_NAMES[i].startswith(d.side) for i in d.landmarks)
    elbow = JOINT_ANGLES_BY_ID["left_elbow_flexion"]
    assert elbow.landmarks == (I["left_shoulder"], I["left_elbow"], I["left_wrist"])
    assert elbow.convention is Convention.FLEXION


def test_standing_pose_reads_near_zero() -> None:
    r = by_id(AngleAnalyzer(NO_FILTER).update(standing_pose(), None, 0, SQUARE))
    assert all(x.status is AngleStatus.OK for x in r.values())
    for side in ("left", "right"):
        assert r[f"{side}_elbow_flexion"].value_deg == pytest.approx(0.0, abs=1e-3)
        assert r[f"{side}_knee_flexion"].value_deg == pytest.approx(0.0, abs=1e-3)
        # Shoulders are 0.05 wider than hips, so the trunk line tilts by
        # atan(0.05/0.30) ≈ 9.5° relative to the vertical arm and thigh.
        trunk_tilt = math.degrees(math.atan2(0.05, 0.30))
        assert r[f"{side}_shoulder_elevation"].value_deg == pytest.approx(trunk_tilt, abs=1e-3)
        assert r[f"{side}_hip_flexion"].value_deg == pytest.approx(trunk_tilt, abs=1e-3)


def test_elbow_bent_to_90_degrees() -> None:
    lm = standing_pose()
    lm[I["left_wrist"], :2] = (0.75, 0.45)  # forearm horizontal
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["left_elbow_flexion"].value_deg == pytest.approx(90.0, abs=1e-3)
    assert r["right_elbow_flexion"].value_deg == pytest.approx(0.0, abs=1e-3)


def test_arm_raised_overhead_reads_near_180_shoulder_elevation() -> None:
    lm = standing_pose()
    lm[I["right_elbow"], :2] = (0.4, 0.15)
    lm[I["right_wrist"], :2] = (0.4, 0.02)
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["right_shoulder_elevation"].value_deg == pytest.approx(
        180.0 - math.degrees(math.atan2(0.05, 0.30)), abs=1e-3
    )


def test_squat_knee_flexion() -> None:
    lm = standing_pose()
    hip = lm[I["left_hip"], :2].copy()
    lm[I["left_knee"], :2] = hip + (0.15, 0.0)  # thigh horizontal
    lm[I["left_ankle"], :2] = hip + (0.15, 0.15)  # shin vertical
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["left_knee_flexion"].value_deg == pytest.approx(90.0, abs=1e-3)


def test_image_space_corrects_for_aspect_ratio() -> None:
    lm = standing_pose()
    elbow = lm[I["left_elbow"], :2]
    lm[I["left_wrist"], :2] = elbow + (0.1, 0.1)  # 45° in normalized coords…
    wide = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, (1280, 720)))
    # …but in a 16:9 frame the forearm is flatter than 45° in real pixels.
    ba = np.array([0.0, -0.15 * 720])
    bc = np.array([0.1 * 1280, 0.1 * 720])
    expected = 180.0 - math.degrees(math.acos(ba @ bc / (np.linalg.norm(ba) * np.linalg.norm(bc))))
    assert wide["left_elbow_flexion"].value_deg == pytest.approx(expected, abs=1e-3)
    assert abs(expected - 45.0) > 5  # the correction actually matters


def test_world_space_uses_3d_coordinates() -> None:
    lm = standing_pose()
    world = np.zeros((33, 5), np.float32)
    world[:, 3:5] = 0.95
    # Forearm pointing straight at the camera: invisible as a bend in 2D,
    # 90° in 3D.
    world[I["left_shoulder"], :3] = (0.2, -0.5, 0.0)
    world[I["left_elbow"], :3] = (0.2, -0.2, 0.0)
    world[I["left_wrist"], :3] = (0.2, -0.2, -0.3)
    cfg = AngleAnalyzerConfig(space=AngleSpace.WORLD, filter=FilterKind.NONE)
    r = by_id(AngleAnalyzer(cfg).update(lm, world, 0, SQUARE))
    assert r["left_elbow_flexion"].value_deg == pytest.approx(90.0, abs=1e-3)


def test_world_space_without_world_landmarks_is_unavailable() -> None:
    cfg = AngleAnalyzerConfig(space=AngleSpace.WORLD, filter=FilterKind.NONE)
    r = by_id(AngleAnalyzer(cfg).update(standing_pose(), None, 0, SQUARE))
    assert r["left_elbow_flexion"].status is AngleStatus.UNAVAILABLE
    assert r["left_elbow_flexion"].value_deg is None


def test_no_person_gives_no_values() -> None:
    results = AngleAnalyzer(NO_FILTER).update(None, None, 0, SQUARE)
    assert all(x.status is AngleStatus.NO_PERSON and x.value_deg is None for x in results)


def test_low_visibility_on_any_of_three_landmarks_suppresses_value() -> None:
    lm = standing_pose()
    lm[I["left_wrist"], 3] = 0.2
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["left_elbow_flexion"].status is AngleStatus.LOW_VISIBILITY
    assert r["left_elbow_flexion"].value_deg is None and r["left_elbow_flexion"].raw_deg is None
    assert r["left_elbow_flexion"].confidence == pytest.approx(0.2)
    assert r["left_shoulder_elevation"].status is AngleStatus.OK  # wrist not involved


def test_off_frame_landmark_suppresses_value() -> None:
    lm = standing_pose()
    lm[I["right_ankle"], 1] = 1.3  # estimated below the frame
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["right_knee_flexion"].status is AngleStatus.OUT_OF_FRAME
    assert r["right_knee_flexion"].value_deg is None


def test_coincident_landmarks_are_degenerate() -> None:
    lm = standing_pose()
    lm[I["left_wrist"], :2] = lm[I["left_elbow"], :2]
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["left_elbow_flexion"].status is AngleStatus.DEGENERATE


def test_nan_coordinates_are_rejected() -> None:
    lm = standing_pose()
    lm[I["left_elbow"], 0] = np.nan
    r = by_id(AngleAnalyzer(NO_FILTER).update(lm, None, 0, SQUARE))
    assert r["left_elbow_flexion"].value_deg is None


def test_filter_resets_after_tracking_gap_instead_of_blending_stale_values() -> None:
    cfg = AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.EMA, ema_alpha=0.1, max_gap_ms=500)
    analyzer = AngleAnalyzer(cfg)
    straight = standing_pose()
    bent = standing_pose()
    bent[I["left_wrist"], :2] = (0.75, 0.45)

    for t in range(0, 300, 33):
        analyzer.update(straight, None, t, SQUARE)
    # Short dropout (< max gap): smoothing continues, so the jump to 90° is damped.
    analyzer.update(None, None, 330, SQUARE)
    short = by_id(analyzer.update(bent, None, 400, SQUARE))["left_elbow_flexion"]
    assert short.raw_deg == pytest.approx(90.0, abs=1e-3)
    assert short.value_deg is not None and short.value_deg < 20

    # Long dropout (> max gap): smoothing restarts at the new measurement.
    for t in range(433, 1500, 33):
        r = by_id(analyzer.update(None, None, t, SQUARE))["left_elbow_flexion"]
        assert r.value_deg is None, "no stale value while the person is missing"
    fresh = by_id(analyzer.update(straight, None, 1500, SQUARE))["left_elbow_flexion"]
    assert fresh.value_deg == pytest.approx(0.0, abs=1e-3)


def test_smoothing_reduces_noise_on_real_pipeline_shape() -> None:
    rng = np.random.default_rng(1)
    cfg = AngleAnalyzerConfig(space=AngleSpace.IMAGE)  # default One Euro
    analyzer = AngleAnalyzer(cfg)
    raw, smooth = [], []
    for k in range(200):
        lm = standing_pose()
        lm[I["left_wrist"], :2] = (0.75, 0.45)
        lm[:, :2] += rng.normal(0, 0.004, (33, 2)).astype(np.float32)
        r = by_id(analyzer.update(lm, None, k * 33, SQUARE))["left_elbow_flexion"]
        raw.append(r.raw_deg)
        smooth.append(r.value_deg)
    assert np.std(smooth[50:]) < 0.6 * np.std(raw[50:])
