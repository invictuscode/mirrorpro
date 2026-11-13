"""Demonstration analysis: joint ranking, rep detection, suggestions, warnings."""

from __future__ import annotations

import numpy as np
import pytest

from app.authoring.analysis import analyze, detect_reps, rank_joints
from app.authoring.series import ANGLE_IDS, AngleSeries
from app.biomechanics import AngleResult, AngleSpace, AngleStatus
from app.exercises.schema import Side, SideMode

DT = 33


def movement(
    t: np.ndarray, rest: float, peak: float, period_ms: int = 3000, hold_frac: float = 0.25
) -> np.ndarray:
    """Rest → ramp → hold at peak → ramp → rest, repeated; starts and ends at rest."""
    ph = (t % period_ms) / period_ms
    ramp = (1 - hold_frac - 0.2) / 2
    up_end, hold_end = 0.1 + ramp, 0.1 + ramp + hold_frac
    frac = np.where(
        ph < 0.1, 0.0,
        np.where(ph < up_end, (ph - 0.1) / ramp,
                 np.where(ph < hold_end, 1.0,
                          np.where(ph < hold_end + ramp, 1 - (ph - hold_end) / ramp, 0.0))),
    )  # fmt: skip
    return rest + (peak - rest) * frac


def series(duration_ms: int = 12_000, noise: float = 2.0, seed: int = 0, **joints: np.ndarray | float) -> AngleSeries:
    t = np.arange(0, duration_ms, DT)
    rng = np.random.default_rng(seed)
    values = {a: np.full(t.size, np.nan) for a in ANGLE_IDS}
    for aid, v in joints.items():
        arr = v(t) if callable(v) else np.full(t.size, float(v))  # type: ignore[operator]
        values[aid] = arr + rng.normal(0, noise, t.size)
    return AngleSeries(t, values, AngleSpace.IMAGE)


def curl_demo(**extra: object) -> AngleSeries:
    kw: dict[str, object] = dict(
        right_elbow_flexion=lambda t: movement(t, 10, 120),
        left_elbow_flexion=5.0,
        right_shoulder_elevation=15.0,
        left_shoulder_elevation=15.0,
    )
    return series(**(kw | extra))  # type: ignore[arg-type]


def test_curl_demo_end_to_end() -> None:
    r = analyze("d", curl_demo())
    assert r.chosen is not None
    assert (r.chosen.joint, r.chosen.side_mode, r.chosen.side) == ("elbow_flexion", SideMode.SINGLE, Side.RIGHT)
    assert r.increasing is True
    assert len(r.reps) == 4
    assert r.rest_deg == pytest.approx(10, abs=4) and r.typical_peak_deg == pytest.approx(120, abs=4)
    rc = r.suggested_rep_counting
    assert rc is not None and rc.increasing
    # Start just above rest; target a little short of the typical peak.
    assert r.rest_deg < rc.start_deg < 60
    assert 90 <= rc.target_deg < r.typical_peak_deg
    assert rc.min_hold_ms >= 500  # the demo held ~0.75 s at the top
    assert [w.code for w in r.warnings] == ["single_demonstration"]
    assert r.chart is not None and len(r.chart.t_ms) <= 400


def test_steady_secondary_joint_becomes_a_blocking_rule_by_default() -> None:
    r = analyze("d", curl_demo())
    rules = {s.rule.joint: s for s in r.suggested_rules}
    assert "shoulder_elevation" in rules
    s = rules["shoulder_elevation"]
    assert s.include is True and s.rule.blocks_rep is True, "steady joints must stay steady by default"
    assert s.rule.max_deg is not None and s.rule.max_deg > s.observed_range_deg[1]
    assert s.rule.message == "Keep your upper arm by your side."


def test_jumping_jack_arms_keep_elbows_and_knees_steady() -> None:
    # Both shoulders sweep 20→150°; elbows stay straight (~8°); knees straight (~5°).
    r = analyze(
        "d",
        series(
            left_shoulder_elevation=lambda t: movement(t, 20, 150),
            right_shoulder_elevation=lambda t: movement(t, 20, 150),
            left_elbow_flexion=8.0, right_elbow_flexion=8.0,
            left_knee_flexion=5.0, right_knee_flexion=5.0,
            left_hip_flexion=5.0, right_hip_flexion=5.0,
        ),  # fmt: skip
    )
    assert r.chosen is not None and r.chosen.joint == "shoulder_elevation"
    assert r.chosen.side_mode is SideMode.MEAN_OF_VISIBLE
    rules = {s.rule.joint: s.rule for s in r.suggested_rules}
    # Arm exercise: only arm joints are checked, never knees or hips.
    assert set(rules) == {"elbow_flexion"}
    assert rules["elbow_flexion"].message == "Keep your elbows straight."
    assert all(rule.blocks_rep for rule in rules.values())
    assert rules["elbow_flexion"].max_deg is not None and 20 <= rules["elbow_flexion"].max_deg <= 30


def test_held_bend_gets_a_band_on_both_sides() -> None:
    # Seated knee extension: the knee moves; the hip is held at ~90° (seated).
    r = analyze("d", series(right_knee_flexion=lambda t: movement(t, 90, 10), right_hip_flexion=90.0, left_knee_flexion=90.0))
    rule = next(s.rule for s in r.suggested_rules if s.rule.joint == "hip_flexion")
    assert rule.min_deg is not None and rule.max_deg is not None
    assert rule.min_deg < 90 < rule.max_deg
    assert rule.message == "Keep your hip position steady."


def test_leg_exercise_does_not_check_arm_joints() -> None:
    r = analyze("d", series(right_knee_flexion=lambda t: movement(t, 90, 10), right_elbow_flexion=5.0, right_hip_flexion=90.0))
    assert {s.rule.joint for s in r.suggested_rules} == {"hip_flexion"}


def test_moving_or_poorly_tracked_joints_get_no_steady_rule() -> None:
    s = curl_demo(right_shoulder_elevation=lambda t: movement(t, 10, 60))  # upper arm moved too
    assert "shoulder_elevation" not in {x.rule.joint for x in analyze("d", s).suggested_rules}


def test_decreasing_movement_is_recognised() -> None:
    # Seated knee extension: rest at 90°, straightens to 10°.
    r = analyze("d", series(right_knee_flexion=lambda t: movement(t, 90, 10), left_knee_flexion=90.0))
    assert r.chosen is not None and r.chosen.joint == "knee_flexion"
    assert r.increasing is False and len(r.reps) == 4
    rc = r.suggested_rep_counting
    assert rc is not None and not rc.increasing
    assert 10 < rc.target_deg < rc.start_deg < 90


def test_both_sides_moving_gives_mean_of_visible() -> None:
    r = analyze("d", series(left_shoulder_elevation=lambda t: movement(t, 20, 130), right_shoulder_elevation=lambda t: movement(t, 25, 125)))
    assert r.chosen is not None and r.chosen.side_mode is SideMode.MEAN_OF_VISIBLE and r.chosen.side is None
    assert len(r.reps) == 4


def test_short_tracking_gaps_do_not_split_reps_but_long_ones_drop_a_rep() -> None:
    s = curl_demo()
    x = s.values["right_elbow_flexion"]
    x[40:48] = np.nan  # ~260 ms gap mid-rep: interpolated
    assert len(analyze("d", s).reps) == 4
    x[150:190] = np.nan  # ~1.3 s gap covering a whole peak: that rep is lost
    r = analyze("d", s)
    assert len(r.reps) == 3


def test_noise_does_not_create_extra_reps() -> None:
    r = analyze("d", curl_demo(right_elbow_flexion=lambda t: movement(t, 10, 120) + 6 * np.sin(t / 37.0)))
    assert len(r.reps) == 4


def test_low_tracking_and_few_reps_are_warned() -> None:
    s = series(duration_ms=3500, right_elbow_flexion=lambda t: movement(t, 10, 120))
    x = s.values["right_elbow_flexion"]
    x[::3] = np.nan  # isolated dropouts → only ~67% valid
    r = analyze("d", s)
    codes = {w.code for w in r.warnings}
    assert {"few_reps", "low_tracking"} <= codes


def test_no_movement_gives_no_suggestions() -> None:
    r = analyze("d", series(right_elbow_flexion=20.0, left_elbow_flexion=20.0))
    assert r.chosen is None and r.suggested_rep_counting is None
    assert "no_movement" in {w.code for w in r.warnings}


def test_ambiguous_joints_are_flagged() -> None:
    r = analyze("d", series(right_elbow_flexion=lambda t: movement(t, 10, 110), right_knee_flexion=lambda t: movement(t, 5, 100)))
    assert "ambiguous_joint" in {w.code for w in r.warnings}
    assert {c.joint for c in r.joint_candidates} >= {"elbow_flexion", "knee_flexion"}


def test_therapist_can_override_the_driving_joint() -> None:
    s = series(right_elbow_flexion=lambda t: movement(t, 10, 110), right_knee_flexion=lambda t: movement(t, 5, 100))
    r = analyze("d", s, joint="knee_flexion", side_mode=SideMode.SINGLE, side=Side.RIGHT)
    assert r.chosen is not None and r.chosen.joint == "knee_flexion" and len(r.reps) == 4
    with pytest.raises(ValueError):
        analyze("d", s, joint="tail_wag")


def test_tiny_movement_gives_no_thresholds_rather_than_invalid_ones() -> None:
    r = analyze("d", series(noise=0.3, right_elbow_flexion=lambda t: movement(t, 40, 58)))
    assert r.suggested_rep_counting is None or abs(r.suggested_rep_counting.target_deg - r.suggested_rep_counting.start_deg) > 2 * r.suggested_rep_counting.hysteresis_deg
    assert "small_movement" in {w.code for w in r.warnings}


def test_detect_reps_counts_hold_time() -> None:
    t = np.arange(0, 9000, DT)
    det = detect_reps(t, movement(t, 0, 100, hold_frac=0.4))
    assert len(det.reps) == 3 and all(r.hold_ms >= 1000 for r in det.reps)
    assert det.increasing is True and not det.direction_ambiguous


def test_recording_that_starts_mid_movement_is_flagged_and_can_be_overridden() -> None:
    # Continuous sine, starting at the top and ending at the bottom: no rest at either end.
    s = series(right_elbow_flexion=lambda t: 65 + 55 * np.cos(2 * np.pi * t / 2400), duration_ms=8400)
    r = analyze("d", s)
    assert "ambiguous_direction" in {w.code for w in r.warnings}
    low = analyze("d", s, start_position="low")
    high = analyze("d", s, start_position="high")
    assert low.increasing is True and high.increasing is False
    assert len(low.reps) >= 3 and len(high.reps) >= 3
    assert low.suggested_rep_counting is not None and low.suggested_rep_counting.increasing
    assert high.suggested_rep_counting is not None and not high.suggested_rep_counting.increasing


def test_rank_ignores_poorly_tracked_joints() -> None:
    s = series(right_elbow_flexion=lambda t: movement(t, 10, 120))
    s.values["right_elbow_flexion"][::2] = np.nan
    s.values["right_elbow_flexion"][1::4] = np.nan  # 25% valid
    assert rank_joints(s) == []


def test_series_from_frames_and_json_round_trip() -> None:
    frames = [
        (0, [AngleResult("right_elbow_flexion", AngleStatus.OK, 30.0, 30.0, 0.9)]),
        (33, [AngleResult("right_elbow_flexion", AngleStatus.LOW_VISIBILITY, None, None, 0.1)]),
    ]
    s = AngleSeries.from_frames(frames, AngleSpace.IMAGE)
    assert s.values["right_elbow_flexion"][0] == 30 and np.isnan(s.values["right_elbow_flexion"][1])
    assert np.isnan(s.values["left_knee_flexion"]).all()
    back = AngleSeries.from_json(s.to_json())
    assert back.n_frames == 2 and back.duration_ms == 33 and np.isnan(back.values["right_elbow_flexion"][1])
