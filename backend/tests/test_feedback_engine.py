"""Feedback engine: rules, uncertainty handling, and message arbitration."""

from __future__ import annotations

import pytest

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.phases import RepEventKind, RepPhase
from app.feedback.config import FeedbackConfig, FormRule, MessageKey
from app.feedback.engine import Category, FeedbackEngine, FeedbackInput, FeedbackState, RuleState
from app.feedback.rules import RuleEvaluator

UPPER_ARM = FormRule(
    id="upper_arm_still", joint="shoulder_elevation", max_deg=40, sustain_ms=300,
    phases=[RepPhase.MOVING, RepPhase.AT_TARGET], message="Keep your upper arm still.",
)  # fmt: skip
WRIST_RULE = FormRule(
    id="elbow_out", joint="elbow_flexion", side="left", min_deg=20, sustain_ms=300,
    phases=[RepPhase.MOVING, RepPhase.AT_TARGET], message="Bend the other elbow slightly.",
)  # fmt: skip


def config(**kw: object) -> FeedbackConfig:
    base: dict[str, object] = dict(
        cooldown_ms=2000, repeat_cooldown_ms=6000, display_ms=3000, min_display_ms=1000,
        tracking_grace_ms=500, start_prompt_after_ms=3000, form_rules=[UPPER_ARM],
    )  # fmt: skip
    return FeedbackConfig.model_validate(base | kw)


def angles(shoulder: float | None = 20.0, elbow_left: float | None = 30.0, person: bool = True) -> list[AngleResult]:
    def a(id_: str, v: float | None) -> AngleResult:
        if not person:
            return AngleResult(id_, AngleStatus.NO_PERSON, None, None, None)
        if v is None:
            return AngleResult(id_, AngleStatus.LOW_VISIBILITY, None, None, 0.2)
        return AngleResult(id_, AngleStatus.OK, v, v, 0.9)

    return [
        a("right_shoulder_elevation", shoulder),
        a("left_elbow_flexion", elbow_left),
        a("right_elbow_flexion", 90.0),
    ]


class Driver:
    """Feeds the engine at 30 fps with a configurable scenario."""

    def __init__(self, engine: FeedbackEngine, evaluator: RuleEvaluator) -> None:
        self.engine = engine
        self.evaluator = evaluator
        self.t = 0
        self.event: tuple[int, RepEventKind] | None = None

    def run(
        self,
        ms: int,
        *,
        phase: RepPhase = RepPhase.MOVING,
        hold_ms: int = 0,
        valid: bool = True,
        progress: float | None = None,
        **angle_kw: object,
    ) -> FeedbackState:
        end = self.t + ms
        state = None
        while self.t <= end:
            frame_angles = angles(**angle_kw)  # type: ignore[arg-type]
            state = self.engine.update(
                FeedbackInput(
                    timestamp_ms=self.t,
                    phase=phase,
                    hold_ms=hold_ms,
                    last_event_seq=self.event[0] if self.event else None,
                    last_event_kind=self.event[1] if self.event else None,
                    angles=frame_angles,
                    sides_used=("right",),
                    signal_valid=valid,
                    rules=self.evaluator.evaluate(phase, frame_angles, ("right",), self.t),
                    progress=progress,
                )
            )
            self.t += 33
        assert state is not None
        return state

    def emit(self, kind: RepEventKind) -> None:
        seq = (self.event[0] + 1) if self.event else 1
        self.event = (seq, kind)


def driver(**kw: object) -> Driver:
    min_hold = int(kw.pop("min_hold_ms", 0))  # type: ignore[call-overload]
    cfg = config(**kw)
    return Driver(FeedbackEngine(cfg, min_hold_ms=min_hold), RuleEvaluator(cfg.form_rules))


def key(state: FeedbackState) -> str | None:
    return state.message.key if state.message else None


# --- form rules --------------------------------------------------------------
def test_good_form_gives_no_message() -> None:
    s = driver().run(2000, shoulder=20)
    assert s.message is None
    assert s.rules[0].state is RuleState.OK and s.tracking_ok


def test_sustained_violation_gives_correction() -> None:
    d = driver()
    assert d.run(200, shoulder=55).message is None  # not yet sustained
    s = d.run(200, shoulder=55)
    assert key(s) == "rule:upper_arm_still"
    assert s.message is not None and s.message.category is Category.CORRECTION
    assert s.message.text == "Keep your upper arm still."
    assert s.rules[0].state is RuleState.VIOLATED and s.rules[0].value_deg == 55


def test_brief_blips_never_trigger_a_correction() -> None:
    d = driver()
    for _ in range(10):
        d.run(200, shoulder=55)  # violation shorter than sustain_ms…
        d.run(100, shoulder=20)  # …then back within bounds
    assert d.run(0, shoulder=20).message is None


def test_unreliable_rule_joint_is_uncertain_not_violated() -> None:
    d = driver()
    d.run(200, shoulder=55)
    s = d.run(2000, shoulder=None)  # shoulder becomes untrackable
    assert s.rules[0].state is RuleState.UNCERTAIN
    assert s.message is None, "uncertainty must not be reported as a deviation"


def test_rules_are_inactive_outside_their_phases() -> None:
    s = driver().run(2000, phase=RepPhase.READY, shoulder=80)
    assert s.rules[0].state is RuleState.INACTIVE and s.message is None


# --- tracking ----------------------------------------------------------------
def test_no_judgement_and_no_message_during_tracking_grace() -> None:
    d = driver()
    s = d.run(400, valid=False, shoulder=80)  # < 500 ms grace, rule violated
    assert s.message is None and not s.tracking_ok


def test_tracking_message_after_grace_and_cleared_on_recovery() -> None:
    d = driver()
    s = d.run(600, valid=False)
    assert key(s) == MessageKey.TRACKING_UNCLEAR.value
    assert s.message is not None and s.message.category is Category.TRACKING
    s = d.run(0, valid=True)
    assert s.message is None and s.tracking_ok


def test_no_person_has_its_own_message() -> None:
    s = driver().run(600, valid=False, person=False)
    assert key(s) == MessageKey.NO_PERSON.value
    assert s.message is not None and s.message.text == "Step into view of the camera."


def test_tracking_replaces_a_correction_immediately() -> None:
    d = driver()
    assert key(d.run(400, shoulder=55)) == "rule:upper_arm_still"
    s = d.run(600, valid=False, shoulder=55)
    assert key(s) == MessageKey.TRACKING_UNCLEAR.value


# --- arbitration ---------------------------------------------------------------
def test_cooldown_prevents_rapid_successive_corrections() -> None:
    d = driver(form_rules=[UPPER_ARM, WRIST_RULE])
    s = d.run(400, shoulder=55, elbow_left=5)  # both rules violated
    assert key(s) == "rule:upper_arm_still"  # config order breaks the tie
    first_seq = s.message.seq if s.message else -1
    # Fix the first issue; second is still violated but cooldown (2 s) holds it back.
    s = d.run(1000, shoulder=20, elbow_left=5)
    assert s.message is not None and s.message.seq == first_seq
    s = d.run(1200, shoulder=20, elbow_left=5)
    assert key(s) == "rule:elbow_out"


def test_same_correction_is_not_repeated_within_repeat_cooldown() -> None:
    d = driver()
    seqs = set()
    for _ in range(5):
        s = d.run(1000, shoulder=55)
        if s.message:
            seqs.add(s.message.seq)
    assert len(seqs) == 1  # 5 s of continuous violation: shown once (repeat cooldown 6 s)
    s = d.run(2000, shoulder=55)
    assert s.message is not None and s.message.seq not in seqs  # repeated after 6 s


def test_messages_expire_after_display_time() -> None:
    d = driver()
    d.run(400, shoulder=55)
    assert d.run(1000, shoulder=20).message is not None
    assert d.run(2000, shoulder=20).message is None


# --- rep outcomes and cues ---------------------------------------------------
def test_rep_outcomes_map_to_messages_once() -> None:
    d = driver(messages={"target_not_reached": "Bend a little further."})
    d.emit(RepEventKind.REP_COMPLETED)
    s = d.run(0)
    assert key(s) == "event:rep_completed" and s.message is not None
    assert s.message.category is Category.POSITIVE and s.message.text == "Repetition completed."
    first = s.message.seq
    s = d.run(500)  # same event seen again on later frames: no new message
    assert s.message is not None and s.message.seq == first

    d.run(3000)
    d.emit(RepEventKind.TARGET_NOT_REACHED)
    s = d.run(0)
    assert s.message is not None and s.message.text == "Bend a little further."
    assert s.message.category is Category.CORRECTION


def test_tracking_lost_event_adds_no_extra_message() -> None:
    d = driver()
    d.emit(RepEventKind.TRACKING_LOST)
    assert d.run(0).message is None


def test_positive_does_not_interrupt_a_fresh_correction_and_is_not_replayed() -> None:
    d = driver()
    correction = d.run(400, shoulder=55).message
    assert correction is not None
    d.emit(RepEventKind.REP_COMPLETED)
    s = d.run(0, shoulder=20)
    assert s.message is not None and s.message.seq == correction.seq
    s = d.run(3000, shoulder=20)
    assert s.message is None, "a dropped event must not pop up later"


def test_hold_cue_shown_at_target_and_retired_when_leaving() -> None:
    d = driver(min_hold_ms=1000)
    s = d.run(100, phase=RepPhase.AT_TARGET, hold_ms=100)
    assert key(s) == MessageKey.HOLD.value and s.message is not None and s.message.category is Category.CUE
    assert d.run(0, phase=RepPhase.RETURNING).message is None


def test_no_hold_cue_without_required_hold() -> None:
    assert driver().run(500, phase=RepPhase.AT_TARGET).message is None


def test_return_to_start_cue_after_waiting() -> None:
    d = driver()
    assert d.run(2500, phase=RepPhase.WAITING_FOR_START).message is None
    s = d.run(600, phase=RepPhase.WAITING_FOR_START)
    assert key(s) == MessageKey.RETURN_TO_START.value
    assert d.run(0, phase=RepPhase.READY).message is None  # condition ended


@pytest.mark.parametrize("rule_side", ["both", "left"])
def test_rule_sides(rule_side: str) -> None:
    rule = FormRule(id="elbow_limit", joint="elbow_flexion", side=rule_side, max_deg=60, sustain_ms=0, message="Straighten.")  # type: ignore[arg-type]
    # right elbow is 90 (violates), left is 30 (fine)
    s = driver(form_rules=[rule]).run(100)
    expected = RuleState.VIOLATED if rule_side == "both" else RuleState.OK
    assert s.rules[0].state is expected
