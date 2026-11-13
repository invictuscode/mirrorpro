"""The 2D blind spot: joints bending toward the camera. Reproduces the user's
report ("elbows super flexed, still counting") with the real analyzer, tracker
and jumping-jack-arms preset."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.biomechanics import AngleAnalyzer, AngleAnalyzerConfig, AngleResult, AngleSpace, AngleStatus, FilterKind
from app.exercises.library import ExerciseLibrary
from app.exercises.phases import RepEventKind
from app.exercises.tracker import ExerciseTracker
from app.feedback.rules import ViolationReason, segment_ratios
from tests.poses import I, standing_pose

DT = 33
SIZE = (640, 480)
UPPER, FORE = 0.13, 0.12


def arms(phi_deg: float, toward_camera_bend_deg: float = 0.0, arm_turn: float = 1.0) -> np.ndarray:
    """Jumping-jack arm pose. ``toward_camera_bend_deg`` bends the elbows toward
    the camera: in 2D the forearm stays in line with the upper arm and only
    its projected length shrinks (cos of the bend). ``arm_turn`` < 1 turns the
    whole arm toward the camera (both segments shrink alike)."""
    lm = standing_pose()
    phi = math.radians(phi_deg)
    fore = FORE * math.cos(math.radians(toward_camera_bend_deg))
    for side, out in (("left", 1), ("right", -1)):
        sx, sy = lm[I[f"{side}_shoulder"], :2]
        ex = sx + out * UPPER * arm_turn * math.sin(phi)
        ey = sy + UPPER * arm_turn * math.cos(phi)
        lm[I[f"{side}_elbow"], :2] = (ex, ey)
        # small sideways jitter, as real tracking produces
        lm[I[f"{side}_wrist"], :2] = (ex + out * fore * arm_turn * math.sin(phi) + 0.003, ey + fore * arm_turn * math.cos(phi))
    return lm


def run_rep(t: ExerciseTracker, start_ms: int, bend_at_top: float = 0.0, arm_turn_at_top: float = 1.0,
            drop_every: int = 0) -> int:  # fmt: skip
    analyzer = AngleAnalyzer(AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.NONE))
    up = [3 + 147 * i / 30 for i in range(31)]
    seq = [3.0] * 12 + up + [150.0] * 30 + up[::-1] + [3.0] * 12
    ts = start_ms
    for i, phi in enumerate(seq):
        frac = max(0.0, (phi - 60) / 90)  # bend/turn grows as the arms rise
        lm = arms(phi, bend_at_top * frac, 1 - (1 - arm_turn_at_top) * frac)
        angles = analyzer.update(lm, None, ts, SIZE)
        if drop_every and i % drop_every == 0:
            # tracking flicker on the elbows
            angles = [
                AngleResult(a.id, AngleStatus.LOW_VISIBILITY, None, None, 0.2) if "elbow" in a.id else a for a in angles
            ]
        t.update(angles, ts, lm, SIZE)
        ts += DT
    return ts


@pytest.fixture
def tracker() -> ExerciseTracker:
    d = ExerciseLibrary.from_directory().get("jumping_jack_arms")
    assert d is not None
    return ExerciseTracker(d)


def last(t: ExerciseTracker, ts: int):  # type: ignore[no-untyped-def]
    lm = arms(3)
    a = AngleAnalyzer(AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.NONE)).update(lm, None, ts, SIZE)
    return t.update(a, ts, lm, SIZE)


def test_2d_angle_alone_misses_a_bend_toward_the_camera() -> None:
    # The blind spot this module fixes: 90° real bend, small 2D angle.
    lm = arms(150, toward_camera_bend_deg=75)
    r = {a.id: a for a in AngleAnalyzer(AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.NONE)).update(lm, None, 0, SIZE)}
    value = r["left_elbow_flexion"].value_deg
    assert value is not None and value < 30, "2D reads this bent elbow as nearly straight"


def test_clean_rep_counts(tracker: ExerciseTracker) -> None:
    ts = run_rep(tracker, 0)
    assert last(tracker, ts).counter.reps == 1


def test_elbows_bent_toward_camera_do_not_count(tracker: ExerciseTracker) -> None:
    ts = run_rep(tracker, 0)
    ts = run_rep(tracker, ts, bend_at_top=75)
    frame = last(tracker, ts)
    assert frame.counter.reps == 1, "the bent-elbow rep must not count"
    e = frame.counter.last_event
    assert e is not None and e.kind is RepEventKind.FORM_BROKEN and e.detail == "elbows_straight"


def test_reason_is_reported_as_out_of_plane(tracker: ExerciseTracker) -> None:
    ts = run_rep(tracker, 0)
    analyzer = AngleAnalyzer(AngleAnalyzerConfig(space=AngleSpace.IMAGE, filter=FilterKind.NONE))
    lm = arms(150, toward_camera_bend_deg=80)
    # Move into the rep first so the rule is active.
    for i, phi in enumerate([3 + 147 * k / 30 for k in range(31)]):
        lm = arms(phi, toward_camera_bend_deg=80 * max(0.0, (phi - 60) / 90))
        f = tracker.update(analyzer.update(lm, None, ts + i * DT, SIZE), ts + i * DT, lm, SIZE)
    rule = next(r for r in f.feedback.rules if r.id == "elbows_straight")
    assert rule.reason is ViolationReason.OUT_OF_PLANE
    assert rule.value_deg is not None and rule.value_deg < 30  # angle looked fine; length gave it away


def test_turning_the_whole_straight_arm_toward_the_camera_is_not_flagged(tracker: ExerciseTracker) -> None:
    ts = run_rep(tracker, 0)
    ts = run_rep(tracker, ts, arm_turn_at_top=0.5)  # whole arm foreshortened, elbow straight
    assert last(tracker, ts).counter.reps == 2


def test_tracking_flicker_cannot_hide_the_bend(tracker: ExerciseTracker) -> None:
    ts = run_rep(tracker, 0)
    ts = run_rep(tracker, ts, bend_at_top=75, drop_every=3)  # elbow angle drops out every 3rd frame
    frame = last(tracker, ts)
    assert frame.counter.reps == 1
    assert frame.counter.last_event is not None and frame.counter.last_event.kind is RepEventKind.FORM_BROKEN


def test_segment_ratios_need_visible_landmarks() -> None:
    lm = arms(3)
    assert segment_ratios(lm, SIZE)["left_elbow_flexion"] == pytest.approx(FORE / UPPER, rel=0.05)
    lm[I["left_wrist"], 3] = 0.1
    assert "left_elbow_flexion" not in segment_ratios(lm, SIZE)
    assert segment_ratios(None, SIZE) == {}


def test_extreme_bend_that_hides_the_forearm_still_does_not_count(tracker: ExerciseTracker) -> None:
    # Bent so far toward the camera that the forearm all but disappears in 2D:
    # the angle becomes unmeasurable, which (for a blocking rule) also fails the rep.
    ts = run_rep(tracker, 0)
    ts = run_rep(tracker, ts, bend_at_top=88)
    frame = last(tracker, ts)
    assert frame.counter.reps == 1
    assert frame.counter.last_event is not None
    assert frame.counter.last_event.kind in (RepEventKind.FORM_BROKEN, RepEventKind.FORM_UNVERIFIED)
