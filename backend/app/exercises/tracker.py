"""Runs one selected exercise against per-frame joint angles."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.rep_counter import RepCounter, RepCounterState
from app.exercises.schema import (
    ExerciseDefinition,
    RepCountingConfig,
    RepCountingOverrides,
    RuleOverride,
    Side,
    apply_rule_overrides,
    SideMode,
    SignalConfig,
)
from app.exercises.phases import RepPhase
from app.feedback.engine import FeedbackEngine, FeedbackInput, FeedbackState
from app.feedback.rules import RuleEvaluator, segment_ratios


@dataclass(frozen=True, slots=True)
class SignalSample:
    value_deg: float | None
    sides_used: tuple[Side, ...]


def extract_signal(signal: SignalConfig, side: Side | None, angles: Sequence[AngleResult]) -> SignalSample:
    """Pick the angle(s) that drive counting. Unreliable angles are never used;
    if none are usable the value is None (the counter treats it as a gap)."""
    valid = {
        a.id: a.value_deg
        for a in angles
        if a.status is AngleStatus.OK and a.value_deg is not None
    }
    if signal.side_mode is SideMode.SINGLE:
        assert side is not None
        v = valid.get(f"{side.value}_{signal.joint}")
        return SignalSample(v, (side,) if v is not None else ())
    used = tuple(s for s in Side if f"{s.value}_{signal.joint}" in valid)
    if not used:
        return SignalSample(None, ())
    return SignalSample(sum(valid[f"{s.value}_{signal.joint}"] for s in used) / len(used), used)


_selection_ids = itertools.count(1)


@dataclass(frozen=True, slots=True)
class ExerciseFrame:
    exercise_id: str
    selection_id: int
    side: Side | None
    sides_used: tuple[Side, ...]
    counter: RepCounterState
    feedback: FeedbackState


class ExerciseTracker:
    """Immutable selection + mutable counter. Create a new tracker to switch
    exercises or reset; ``update`` must be called from one thread."""

    def __init__(
        self,
        definition: ExerciseDefinition,
        side: Side | None = None,
        overrides: RepCountingOverrides | None = None,
        rule_overrides: dict[str, RuleOverride] | None = None,
    ) -> None:
        if rule_overrides:
            # e.g. a looser elbow allowance chosen on the settings screen
            rules = apply_rule_overrides(definition.feedback.form_rules, rule_overrides)
            definition = definition.model_copy(
                update={"feedback": definition.feedback.model_copy(update={"form_rules": rules})}
            )
        self.rule_overrides = dict(rule_overrides or {})
        if definition.signal.side_mode is SideMode.SINGLE:
            side = side or definition.signal.default_side
        elif side is not None:
            raise ValueError(f"exercise {definition.id!r} uses both sides; do not pass a side")
        self.definition = definition
        self.side = side
        self.overrides = overrides or RepCountingOverrides()
        self.rep_config: RepCountingConfig = self.overrides.apply(definition.rep_counting)
        self._counter = RepCounter(self.rep_config)
        self._feedback = FeedbackEngine(definition.feedback, self.rep_config.min_hold_ms)
        self._rules = RuleEvaluator(definition.feedback.form_rules)
        self._has_blocking = any(r.blocks_rep for r in definition.feedback.form_rules)
        self._has_rules = bool(definition.feedback.form_rules)
        self._phase = RepPhase.WAITING_FOR_START  # previous frame's phase, for rule activity
        # Unique per tracker (i.e. per selection or reset), so clients can tell
        # when the selection changed elsewhere and refetch its settings.
        self.selection_id = next(_selection_ids)

    def update(
        self,
        angles: Sequence[AngleResult],
        timestamp_ms: int,
        landmarks: np.ndarray | None = None,
        image_size: tuple[int, int] = (1, 1),
    ) -> ExerciseFrame:
        """``landmarks`` (normalized image landmarks) enable the out-of-plane
        check for form rules; without them only angles are checked."""
        sample = extract_signal(self.definition.signal, self.side, angles)
        # Single-side exercises judge form on the selected side even while it
        # is momentarily untracked (the rule then reports "uncertain" instead
        # of switching sides).
        sides = tuple(s.value for s in (sample.sides_used or ((self.side,) if self.side else ())))
        # Rules are evaluated once and shared: the counter uses blocking rules
        # to refuse reps done with the wrong joint; feedback uses all rules.
        ratios = segment_ratios(landmarks, image_size) if self._has_rules else None
        statuses = self._rules.evaluate(self._phase, angles, sides, timestamp_ms, ratios)
        form = self._rules.form_check(statuses) if self._has_blocking else None
        state = self._counter.update(sample.value_deg, timestamp_ms, form)
        self._phase = state.phase
        event = state.last_event
        feedback = self._feedback.update(
            FeedbackInput(
                timestamp_ms=timestamp_ms,
                phase=state.phase,
                hold_ms=state.hold_ms,
                last_event_seq=event.seq if event else None,
                last_event_kind=event.kind if event else None,
                angles=angles,
                sides_used=sides,
                signal_valid=sample.value_deg is not None,
                rules=statuses,
                progress=state.progress,
                last_event_detail=event.detail if event else None,
            )
        )
        return ExerciseFrame(self.definition.id, self.selection_id, self.side, sample.sides_used, state, feedback)
