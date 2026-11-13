"""Session manager: sets, rest, pause/resume, timing, summary, conflicts."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.library import ExerciseLibrary
from app.exercises.tracker import ExerciseTracker
from app.schemas.session import StartSession
from app.sessions.manager import SessionConflict, SessionManager, SessionNotFound

DT = 33


class FakeTimer:
    def __init__(self, delay_s: float, fn: Callable[[], None]) -> None:
        self.delay_s, self.fn, self.cancelled = delay_s, fn, False

    def cancel(self) -> None:
        self.cancelled = True


class Harness:
    def __init__(self) -> None:
        self.now = 0
        self.installed: ExerciseTracker | None = None
        self.published: list[dict] = []
        self.timers: list[FakeTimer] = []
        self.m = SessionManager(
            ExerciseLibrary.from_directory(),
            set_exercise=self._install,
            publish=lambda p: self.published.append(json.loads(p)),
            clock=lambda: self.now,
            schedule=self._schedule,  # type: ignore[arg-type]
        )

    def _install(self, t: ExerciseTracker | None) -> None:
        self.installed = t

    def _schedule(self, delay_s: float, fn: Callable[[], None]) -> FakeTimer:
        t = FakeTimer(delay_s, fn)
        self.timers.append(t)
        return t

    def start(self, **kw: object) -> None:
        # Set-logic tests skip the practice rep unless they ask for it.
        self.m.start(StartSession.model_validate({"exercise_id": "biceps_curl", "practice": False} | kw))

    def feed(self, values: list[float | None], tracker: ExerciseTracker | None = None) -> None:
        """Drive the installed tracker (or a given one) like the pipeline does."""
        for v in values:
            t = tracker or self.installed
            if t is not None:
                status = AngleStatus.OK if v is not None else AngleStatus.LOW_VISIBILITY
                angle = AngleResult("right_elbow_flexion", status, v, v, 0.9)
                # The curl's upper-arm rule blocks reps it cannot verify, so
                # supply a still, visible upper arm as a real person would.
                upper_arm = AngleResult("right_shoulder_elevation", AngleStatus.OK, 15.0, 15.0, 0.9)
                self.m.on_frame(t.update([angle, upper_arm], self.now))
            self.now += DT

    def rep(self, high: float = 130) -> None:
        up = [10 + (high - 10) * i / 30 for i in range(31)]
        self.feed([10.0] * 6 + up + [high] * 6 + up[::-1] + [10.0] * 6)

    def wait(self, ms: int) -> None:
        self.now += ms


@pytest.fixture
def h() -> Harness:
    return Harness()


def test_defaults_come_from_dosage(h: Harness) -> None:
    h.start()
    v = h.m.view()
    assert v is not None and (v.plan.sets, v.plan.reps_per_set, v.plan.rest_s) == (2, 10, 30)
    assert v.state == "active" and v.current_set == 1 and v.side == "right"
    assert h.installed is not None and v.selection_id == h.installed.selection_id


def test_full_session_with_rest_and_summary(h: Harness) -> None:
    h.start(sets=2, reps_per_set=2, rest_s=10)
    h.rep()
    assert h.m.view().current_set_reps == 1  # type: ignore[union-attr]
    h.rep()
    v = h.m.view()
    # The set finished partway through the last rep() (the harness keeps feeding
    # a few hundred ms of frames afterwards), so a little rest has elapsed.
    assert v is not None and v.state == "resting"
    assert v.rest_remaining_ms is not None and 9_500 < v.rest_remaining_ms <= 10_000
    assert h.installed is None, "nothing is counted during rest"
    assert [s.reps for s in v.sets] == [2]

    h.wait(10_000)
    v = h.m.view()  # rest ends lazily on the next query…
    assert v is not None and v.state == "active" and v.current_set == 2 and v.current_set_reps == 0
    h.rep()
    h.rep()
    v = h.m.view()
    assert v is not None and v.state == "completed" and v.summary is not None
    s = v.summary
    assert s.total_reps == 4 and s.sets_completed == 2
    assert [r.reps for r in s.sets] == [2, 2] and not any(r.ended_early for r in s.sets)
    assert s.peak_deg is not None and s.peak_deg.max_deg == pytest.approx(130, abs=1)
    assert s.mean_rep_ms is not None and s.mean_rep_ms > 1000
    assert s.feedback_counts.get("positive", 0) >= 1
    assert v.rest_ms == 10_000, "rest ends when scheduled, not when next observed"
    assert h.published[-1]["session"]["state"] == "completed"


def test_rest_timer_starts_next_set_without_frames(h: Harness) -> None:
    h.start(sets=2, reps_per_set=1, rest_s=5)
    h.rep()
    timer = h.timers[-1]
    assert timer.delay_s == 5 and not timer.cancelled
    h.wait(5000)
    timer.fn()  # what threading.Timer would do
    assert h.published[-1]["session"]["state"] == "active"
    assert h.published[-1]["session"]["current_set"] == 2


def test_zero_rest_goes_straight_to_next_set(h: Harness) -> None:
    h.start(sets=3, reps_per_set=1, rest_s=0)
    h.rep()
    v = h.m.view()
    assert v is not None and v.state == "active" and v.current_set == 2


def test_pause_stops_counting_and_time_then_resume_keeps_count(h: Harness) -> None:
    h.start(sets=1, reps_per_set=5, rest_s=0)
    h.rep()
    tracker = h.installed
    active_before = h.m.view().active_ms  # type: ignore[union-attr]
    h.m.pause()
    assert h.installed is None
    h.feed([10.0] * 10, tracker=tracker)  # stale frames while paused are ignored
    h.wait(60_000)
    v = h.m.view()
    assert v is not None and v.state == "paused" and v.paused_from == "active"
    assert v.active_ms == active_before, "time while paused is not active time"
    h.m.resume()
    assert h.installed is tracker, "the same counter resumes"
    assert h.m.view().current_set_reps == 1  # type: ignore[union-attr]
    h.rep()
    assert h.m.view().current_set_reps == 2  # type: ignore[union-attr]


def test_paused_time_is_not_active_time(h: Harness) -> None:
    h.start(sets=1, reps_per_set=5, rest_s=0)
    h.wait(1000)
    h.m.pause()
    h.wait(30_000)
    h.m.resume()
    h.wait(500)
    v = h.m.view()
    assert v is not None and v.active_ms == 1500 and v.elapsed_ms == 31_500


def test_pause_during_rest_freezes_countdown(h: Harness) -> None:
    h.start(sets=2, reps_per_set=1, rest_s=20)
    h.rep()
    h.wait(5000)
    remaining = h.m.view().rest_remaining_ms  # type: ignore[union-attr]
    assert remaining is not None and 14_000 < remaining < 15_000
    h.m.pause()
    assert h.timers[-1].cancelled
    h.wait(60_000)
    v = h.m.view()
    assert v is not None and v.state == "paused" and v.rest_remaining_ms == remaining
    h.m.resume()
    v = h.m.view()
    assert v is not None and v.state == "resting" and v.rest_remaining_ms == remaining
    assert h.timers[-1].delay_s == remaining / 1000


def test_advance_ends_set_early_or_skips_rest(h: Harness) -> None:
    h.start(sets=2, reps_per_set=5, rest_s=30)
    h.rep()
    v = h.m.advance()
    assert v.state == "resting" and v.sets[0].reps == 1 and v.sets[0].ended_early
    v = h.m.advance()
    assert v.state == "active" and v.current_set == 2
    h.m.pause()
    with pytest.raises(SessionConflict, match="Resume"):
        h.m.advance()


def test_end_records_partial_set_and_dismiss(h: Harness) -> None:
    h.start(sets=3, reps_per_set=5, rest_s=0)
    h.rep()
    h.rep()
    v = h.m.end()
    assert v.state == "ended" and h.installed is None
    assert v.summary is not None and v.summary.total_reps == 2 and v.summary.sets_completed == 0
    assert v.summary.sets[0].ended_early
    with pytest.raises(SessionConflict):
        h.m.pause()
    h.m.dismiss()
    assert h.m.view() is None and h.published[-1] == {"type": "session", "session": None}


def test_end_while_paused_does_not_count_pause_as_active(h: Harness) -> None:
    h.start(sets=1, reps_per_set=5, rest_s=0)
    h.wait(2000)
    h.m.pause()
    h.wait(50_000)
    v = h.m.end()
    assert v.summary is not None and v.summary.active_ms == 2000


def test_frames_from_previous_set_are_ignored(h: Harness) -> None:
    h.start(sets=2, reps_per_set=1, rest_s=0)
    old = h.installed
    h.rep()
    assert h.installed is not old
    h.feed([10.0] * 6 + [130.0] * 30 + [10.0] * 30, tracker=old)  # old tracker keeps counting…
    assert h.m.view().current_set_reps == 0  # type: ignore[union-attr]  …but is ignored


def test_uncounted_attempts_and_corrections_are_summarised(h: Harness) -> None:
    h.start(sets=1, reps_per_set=5, rest_s=0)
    h.rep(high=80)  # target 110 not reached
    v = h.m.end()
    assert v.summary is not None
    assert v.summary.uncounted == {"target_not_reached": 1}
    assert [c.text for c in v.summary.top_corrections] == ["Bend your elbow a little further."]
    assert v.summary.peak_deg is None


def test_conflicts_and_validation(h: Harness) -> None:
    with pytest.raises(SessionConflict):
        h.m.pause()
    with pytest.raises(SessionNotFound):
        h.start(exercise_id="nope")
    with pytest.raises(ValueError, match="both sides"):
        h.start(exercise_id="sit_to_stand", side="left")
    h.start()
    with pytest.raises(SessionConflict, match="already in progress"):
        h.start()
    with pytest.raises(SessionConflict):
        h.m.dismiss()
    assert h.m.in_progress


def test_custom_settings_apply_to_every_set(h: Harness) -> None:
    h.start(sets=2, reps_per_set=1, rest_s=0, overrides={"target_deg": 90, "min_hold_ms": 500})
    v = h.m.view()
    assert v is not None and v.rep_counting.target_deg == 90 and v.rep_counting.min_hold_ms == 500
    assert h.installed is not None and h.installed.rep_config.target_deg == 90
    # Quick touch of the target: above 84° (target − hysteresis) for ~230 ms < 500 ms hold.
    quick = [10.0 + 18 * i for i in range(6)] + [100.0] * 2 + [100.0 - 18 * i for i in range(6)]
    h.feed([10.0] * 6 + quick + [10.0] * 10)
    assert h.m.view().current_set_reps == 0  # type: ignore[union-attr]
    h.feed([10.0] * 6 + [100.0] * 30 + [10.0] * 30)  # held ~1 s at 100°
    v = h.m.view()
    assert v is not None and v.current_set == 2, "second set uses the same custom settings"
    assert h.installed is not None and h.installed.rep_config.min_hold_ms == 500


# --- practice rep -------------------------------------------------------------------
def test_practice_rep_comes_first_and_is_not_counted(h: Harness) -> None:
    h.start(practice=True, sets=1, reps_per_set=2, rest_s=0)
    v = h.m.view()
    assert v is not None and v.state == "practice" and v.practice == "pending"
    practice_tracker = h.installed
    assert practice_tracker is not None, "the practice rep is tracked (for guidance)"
    h.rep()
    v = h.m.view()
    assert v is not None and v.state == "active" and v.practice == "completed"
    assert v.current_set == 1 and v.current_set_reps == 0, "set 1 starts fresh"
    assert h.installed is not practice_tracker
    h.rep()
    h.rep()
    v = h.m.view()
    assert v is not None and v.state == "completed" and v.summary is not None
    assert v.summary.total_reps == 2, "the practice rep is not in the totals"
    assert v.active_ms > 0


def test_practice_can_be_skipped(h: Harness) -> None:
    h.start(practice=True)
    v = h.m.advance()
    assert v.state == "active" and v.practice == "skipped" and v.current_set == 1


def test_practice_can_be_paused_and_resumed(h: Harness) -> None:
    h.start(practice=True)
    tracker = h.installed
    h.m.pause()
    assert h.installed is None and h.m.view().paused_from == "practice"  # type: ignore[union-attr]
    h.m.resume()
    v = h.m.view()
    assert v is not None and v.state == "practice" and h.installed is tracker


def test_failed_practice_attempts_do_not_start_the_set(h: Harness) -> None:
    h.start(practice=True)
    h.rep(high=80)  # target not reached: still practising
    assert h.m.view().state == "practice"  # type: ignore[union-attr]


def test_ending_during_practice_records_no_sets(h: Harness) -> None:
    h.start(practice=True)
    v = h.m.end()
    assert v.state == "ended" and v.summary is not None and v.summary.sets == [] and v.summary.total_reps == 0


def test_practice_time_is_not_exercise_time(h: Harness) -> None:
    h.start(practice=True)
    h.wait(30_000)
    h.m.advance()
    h.wait(1000)
    assert h.m.view().active_ms == 1000  # type: ignore[union-attr]


def test_practice_ends_after_a_full_attempt_even_if_a_steady_joint_was_flagged(h: Harness) -> None:
    h.start(practice=True)
    tracker = h.installed
    assert tracker is not None
    # Curl with the upper arm swung far forward for the whole rep: a blocking rule breaks.
    for v in [10.0] * 6 + [10 + 120 * i / 30 for i in range(31)] + [130.0] * 6 + [130 - 120 * i / 30 for i in range(31)] + [10.0] * 6:
        elbow = AngleResult("right_elbow_flexion", AngleStatus.OK, v, v, 0.9)
        swung = AngleResult("right_shoulder_elevation", AngleStatus.OK, 80.0, 80.0, 0.9)
        h.m.on_frame(tracker.update([elbow, swung], h.now))
        h.now += DT
    v = h.m.view()
    assert v is not None and v.state == "active" and v.practice == "completed"


def test_rule_overrides_loosen_or_relax_a_check_for_the_session(h: Harness) -> None:
    h.start(sets=1, reps_per_set=5, rest_s=0, rule_overrides={"upper_arm_still": {"max_deg": 90}})
    v = h.m.view()
    assert v is not None and v.form_rules[0].max_deg == 90 and v.form_rules[0].blocks_rep
    assert h.installed is not None and h.installed.definition.feedback.form_rules[0].max_deg == 90
    # A swing to 80° is now within the allowance: the rep counts.
    tracker = h.installed
    for x in [10.0] * 6 + [10 + 120 * i / 30 for i in range(31)] + [130.0] * 6 + [130 - 120 * i / 30 for i in range(31)] + [10.0] * 6:
        elbow = AngleResult("right_elbow_flexion", AngleStatus.OK, x, x, 0.9)
        swung = AngleResult("right_shoulder_elevation", AngleStatus.OK, 80.0, 80.0, 0.9)
        h.m.on_frame(tracker.update([elbow, swung], h.now))
        h.now += DT
    assert h.m.view().current_set_reps == 1  # type: ignore[union-attr]


def test_rule_overrides_are_validated(h: Harness) -> None:
    with pytest.raises(ValueError, match="unknown form rule"):
        h.start(rule_overrides={"nope": {"max_deg": 10}})
    with pytest.raises(ValueError):
        h.start(rule_overrides={"upper_arm_still": {"max_deg": None}})  # no bound left
    h.start(rule_overrides={"upper_arm_still": {"blocks_rep": False}})
    v = h.m.view()
    assert v is not None and v.form_rules[0].blocks_rep is False
