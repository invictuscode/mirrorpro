"""Blocking form rules: reps done with the wrong joint (or with the joint hidden)
must not count. Plus the new coaching cues."""

from __future__ import annotations

import pytest

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.library import ExerciseLibrary
from app.exercises.phases import RepEventKind, RepPhase
from app.exercises.rep_counter import RepCounter
from app.exercises.schema import RepCountingConfig
from app.exercises.tracker import ExerciseTracker
from app.feedback.config import FeedbackConfig, MessageKey
from app.feedback.engine import Category, FeedbackEngine, FeedbackInput
from app.feedback.rules import FormCheck

DT = 33


def cfg() -> RepCountingConfig:
    return RepCountingConfig(start_deg=30, target_deg=110, hysteresis_deg=8, confirm_ms=100, min_rep_ms=600)


def curl_values(high: float = 130) -> list[float]:
    up = [10 + (high - 10) * i / 30 for i in range(31)]
    return [10.0] * 6 + up + [high] * 6 + up[::-1] + [10.0] * 6


# --- counter ----------------------------------------------------------------------
def run_counter(form_at: dict[int, FormCheck]) -> RepCounter:
    c = RepCounter(cfg())
    for i, v in enumerate(curl_values()):
        c.update(v, i * DT, form_at.get(i, FormCheck((), False)))
    return c


def test_clean_form_counts() -> None:
    c = run_counter({})
    assert c.reps == 1


def test_a_single_noisy_frame_does_not_fail_a_rep() -> None:
    c = run_counter({25: FormCheck((("elbows_straight", 0),), False)})
    assert c.reps == 1, "brief noise must not cost the patient a repetition"


def test_sustained_blocking_violation_is_not_counted() -> None:
    broken = {i: FormCheck((("elbows_straight", 400),), False) for i in range(20, 60)}  # ~1.3 s of the rep
    c = run_counter(broken)
    assert c.reps == 0
    e = c.update(10, 10_000).last_event
    assert e is not None and e.kind is RepEventKind.FORM_BROKEN and e.detail == "elbows_straight"


def test_short_violation_below_share_of_rep_is_tolerated() -> None:
    # ~0.3 s of a ~1.8 s rep: longer than the rule's 0.2 s minimum but under
    # 20% of the rep, so a slight wobble, not a different movement.
    c = run_counter({i: FormCheck((("elbows_straight", 200),), False) for i in range(30, 39)})
    assert c.reps == 1


def test_violation_before_the_rep_does_not_carry_over() -> None:
    # Broken while still resting at the start (frame 2): the rep starts later, clean.
    c = run_counter({2: FormCheck((("elbows_straight", 0),), False)})
    assert c.reps == 1


def test_hiding_the_checked_joint_for_much_of_the_rep_is_not_counted() -> None:
    unverified = {i: FormCheck((), True) for i in range(6, 74)}  # nearly the whole rep
    c = run_counter(unverified)
    assert c.reps == 0
    assert c.update(10, 10_000).last_event.kind is RepEventKind.FORM_UNVERIFIED  # type: ignore[union-attr]


def test_brief_unverifiable_moments_are_tolerated() -> None:
    c = run_counter({i: FormCheck((), True) for i in range(20, 26)})  # ~0.2 s
    assert c.reps == 1


def test_counter_without_form_input_is_unchanged() -> None:
    c = RepCounter(cfg())
    for i, v in enumerate(curl_values()):
        c.update(v, i * DT)
    assert c.reps == 1


# --- tracker: real rule evaluation -------------------------------------------------
def ok(id_: str, v: float) -> AngleResult:
    return AngleResult(id_, AngleStatus.OK, v, v, 0.9)


def drive_curl(t: ExerciseTracker, shoulder: float | None, start_ms: int = 0) -> int:
    ts = start_ms
    for v in curl_values():
        angles = [ok("right_elbow_flexion", v)]
        if shoulder is not None:
            angles.append(ok("right_shoulder_elevation", shoulder))
        else:
            angles.append(AngleResult("right_shoulder_elevation", AngleStatus.LOW_VISIBILITY, None, None, 0.1))
        t.update(angles, ts)
        ts += DT
    return ts


def curl_tracker() -> ExerciseTracker:
    d = ExerciseLibrary.from_directory().get("biceps_curl")
    assert d is not None and any(r.blocks_rep for r in d.feedback.form_rules)
    return ExerciseTracker(d)


def test_curl_swinging_the_upper_arm_does_not_count() -> None:
    t = curl_tracker()
    ts = drive_curl(t, shoulder=15)  # upper arm still
    ts = drive_curl(t, shoulder=70, start_ms=ts)  # upper arm swung forward (> 40°)
    frame = t.update([ok("right_elbow_flexion", 10), ok("right_shoulder_elevation", 15)], ts)
    assert frame.counter.reps == 1
    assert frame.counter.last_event is not None and frame.counter.last_event.kind is RepEventKind.FORM_BROKEN


def test_curl_with_upper_arm_hidden_does_not_count() -> None:
    t = curl_tracker()
    ts = drive_curl(t, shoulder=None)
    frame = t.update([ok("right_elbow_flexion", 10)], ts)
    assert frame.counter.reps == 0
    assert frame.counter.last_event is not None and frame.counter.last_event.kind is RepEventKind.FORM_UNVERIFIED


def test_form_broken_feedback_names_the_rule() -> None:
    t = curl_tracker()
    ts = drive_curl(t, shoulder=70)
    texts = set()
    for i in range(10):
        f = t.update([ok("right_elbow_flexion", 10), ok("right_shoulder_elevation", 15)], ts + i * DT)
        if f.feedback.message:
            texts.add(f.feedback.message.text)
    assert any(x.startswith("Not counted: Keep your upper arm still") for x in texts)


# --- coaching cues -------------------------------------------------------------------
def engine_run(phase: RepPhase, progress: list[float], hold_ms: int = 0, min_hold: int = 0) -> set[str]:
    e = FeedbackEngine(FeedbackConfig(cooldown_ms=0, repeat_cooldown_ms=0, min_display_ms=0), min_hold)
    keys = set()
    for i, p in enumerate(progress):
        s = e.update(
            FeedbackInput(
                timestamp_ms=i * DT, phase=phase, hold_ms=hold_ms, last_event_seq=None, last_event_kind=None,
                angles=[ok("right_elbow_flexion", 50)], sides_used=("right",), signal_valid=True, progress=p,
            )  # fmt: skip
        )
        if s.message:
            keys.add(s.message.key)
    return keys


@pytest.mark.parametrize(("stalled_at", "expected"), [(0.4, MessageKey.KEEP_GOING), (0.85, MessageKey.ALMOST_THERE)])
def test_stalled_progress_gets_encouragement(stalled_at: float, expected: MessageKey) -> None:
    ramp = [stalled_at * i / 10 for i in range(11)]
    keys = engine_run(RepPhase.MOVING, ramp + [stalled_at] * 60)  # stalled ~2 s
    assert expected.value in keys


def test_steady_progress_gets_no_nagging() -> None:
    keys = engine_run(RepPhase.MOVING, [i / 60 for i in range(60)])
    assert not keys & {MessageKey.KEEP_GOING.value, MessageKey.ALMOST_THERE.value}


def test_return_cue_after_hold_is_done() -> None:
    assert MessageKey.RETURN_NOW.value in engine_run(RepPhase.AT_TARGET, [1.0] * 40)
    # Hold still required: the hold cue, not "return".
    keys = engine_run(RepPhase.AT_TARGET, [1.0] * 40, hold_ms=200, min_hold=2000)
    assert MessageKey.RETURN_NOW.value not in keys and MessageKey.HOLD.value in keys


def test_form_unverified_is_shown_as_uncertainty_not_correction() -> None:
    e = FeedbackEngine(FeedbackConfig(), 0)
    s = e.update(
        FeedbackInput(
            timestamp_ms=0, phase=RepPhase.READY, hold_ms=0, last_event_seq=1,
            last_event_kind=RepEventKind.FORM_UNVERIFIED, angles=[ok("right_elbow_flexion", 10)],
            sides_used=("right",), signal_valid=True,
        )  # fmt: skip
    )
    assert s.message is not None and s.message.category is Category.TRACKING
    # It is an event message, so it stays up even though tracking is fine.
    s = e.update(
        FeedbackInput(
            timestamp_ms=500, phase=RepPhase.READY, hold_ms=0, last_event_seq=1,
            last_event_kind=RepEventKind.FORM_UNVERIFIED, angles=[ok("right_elbow_flexion", 10)],
            sides_used=("right",), signal_valid=True,
        )  # fmt: skip
    )
    assert s.message is not None


# --- end to end: demonstration → suggested rules → patient can't cheat -------------
def test_authored_jumping_jack_arms_rejects_bent_elbow_reps() -> None:
    from app.authoring.analysis import analyze
    from app.authoring.service import build_definition
    from app.exercises.schema import ReviewStatus
    from app.schemas.authoring import DraftFields
    from tests.test_authoring_analysis import movement, series

    demo = series(
        left_shoulder_elevation=lambda t: movement(t, 20, 150),
        right_shoulder_elevation=lambda t: movement(t, 20, 150),
        left_elbow_flexion=8.0, right_elbow_flexion=8.0,
        left_knee_flexion=5.0, right_knee_flexion=5.0,
    )  # fmt: skip
    a = analyze("d", demo)
    assert a.chosen is not None and a.suggested_rep_counting is not None
    fields = DraftFields(
        name="Jumping jack arms", description="d", instructions=["Sweep your arms up and down."],
        camera_view="front", camera_guidance="Face the camera.", signal_joint=a.chosen.joint,
        side_mode=a.chosen.side_mode, default_side=a.chosen.side, rep_counting=a.suggested_rep_counting,
        form_rules=[s.rule for s in a.suggested_rules if s.include],
    )  # fmt: skip
    t = ExerciseTracker(build_definition("custom_jj_0000", 1, fields, ReviewStatus.APPROVED, reviewer="Dr T"))

    def rep(elbow_at_top: float, start: int) -> int:
        ts = start
        up = [20 + 130 * i / 30 for i in range(31)]
        # Hold ~1 s at the top, as the demonstration did (the analysis learned a hold).
        for i, sh in enumerate([20.0] * 8 + up + [150.0] * 30 + up[::-1] + [20.0] * 8):
            # Cheating version: bend the elbows while the arms are up.
            elbow = elbow_at_top if 20 <= i <= 80 else 8.0
            angles = [ok(f"{side}_shoulder_elevation", sh) for side in ("left", "right")]
            angles += [ok(f"{side}_elbow_flexion", elbow) for side in ("left", "right")]
            angles += [ok(f"{side}_knee_flexion", 5.0) for side in ("left", "right")]
            t.update(angles, ts)
            ts += DT
        return ts

    ts = rep(elbow_at_top=8.0, start=0)  # proper rep
    ts = rep(elbow_at_top=90.0, start=ts)  # elbows bent: shoulder angle alone would "count"
    final = t.update([ok("left_shoulder_elevation", 20), ok("right_shoulder_elevation", 20)], ts)
    assert final.counter.reps == 1
    assert final.counter.last_event is not None and final.counter.last_event.kind is RepEventKind.FORM_BROKEN
    assert final.counter.last_event.detail == "steady_elbow_flexion"
