"""Rule-based real-time feedback with arbitration.

Per frame the engine gathers *candidate* messages and issues at most one,
subject to priority, cooldowns and minimum display time:

==========  ========  =====================================================
Category    Priority  Source
==========  ========  =====================================================
tracking    3         Driving angle unreliable for ``tracking_grace_ms``
correction  2         Sustained form-rule violation; uncounted rep outcome
cue         1         Hold at target; return now; keep going / almost there
                      (progress stalled); not back at start for a while
positive    1         Rep counted
==========  ========  =====================================================

Uncertainty is never presented as a movement deviation: while tracking is
poor, *only* the tracking message can be shown, and a form rule whose own
joint is not reliably tracked reports ``uncertain`` and stays silent.

Pure: no I/O, no clocks; time comes from ``timestamp_ms``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.biomechanics import AngleResult, AngleStatus
from app.exercises.phases import RepEventKind, RepPhase
from app.feedback.config import FeedbackConfig, MessageKey
from app.feedback.rules import RuleState, RuleStatus

__all__ = ["Category", "FeedbackEngine", "FeedbackInput", "FeedbackMessage", "FeedbackState", "RuleState", "RuleStatus"]


class Category(StrEnum):
    TRACKING = "tracking"
    CORRECTION = "correction"
    CUE = "cue"
    POSITIVE = "positive"


PRIORITY: dict[Category, int] = {
    Category.TRACKING: 3,
    Category.CORRECTION: 2,
    Category.CUE: 1,
    Category.POSITIVE: 1,
}
_RATE_LIMITED = frozenset({Category.CORRECTION, Category.CUE})

_EVENT_MESSAGES: dict[RepEventKind, tuple[MessageKey, Category]] = {
    RepEventKind.REP_COMPLETED: (MessageKey.REP_COMPLETED, Category.POSITIVE),
    RepEventKind.TARGET_NOT_REACHED: (MessageKey.TARGET_NOT_REACHED, Category.CORRECTION),
    RepEventKind.HOLD_TOO_SHORT: (MessageKey.HOLD_TOO_SHORT, Category.CORRECTION),
    RepEventKind.TOO_FAST: (MessageKey.TOO_FAST, Category.CORRECTION),
    RepEventKind.TIMED_OUT: (MessageKey.TIMED_OUT, Category.CUE),
    # Uncertainty, not a deviation: shown in the neutral tracking style.
    RepEventKind.FORM_UNVERIFIED: (MessageKey.FORM_UNVERIFIED, Category.TRACKING),
    # FORM_BROKEN: text comes from the broken rule (see _new_event).
    # TRACKING_LOST: covered by the tracking message itself.
}


@dataclass(frozen=True, slots=True)
class FeedbackMessage:
    seq: int
    key: str  # MessageKey value, or "rule:<id>"
    text: str
    category: Category
    issued_ms: int


@dataclass(frozen=True, slots=True)
class FeedbackState:
    message: FeedbackMessage | None
    rules: tuple[RuleStatus, ...]
    tracking_ok: bool


@dataclass(frozen=True, slots=True)
class FeedbackInput:
    timestamp_ms: int
    phase: RepPhase
    hold_ms: int
    last_event_seq: int | None
    last_event_kind: RepEventKind | None
    angles: Sequence[AngleResult]
    sides_used: tuple[str, ...]  # sides driving the rep count this frame
    signal_valid: bool
    rules: tuple[RuleStatus, ...] = ()  # evaluated by RuleEvaluator for this frame
    progress: float | None = None  # 0 at start threshold … 1 at target
    last_event_detail: str | None = None  # e.g. the broken rule's id


@dataclass(slots=True)
class _Candidate:
    key: str
    text: str
    category: Category
    concludes: str | None = None  # key of the message this one follows up on


@dataclass(slots=True)
class _Memory:
    last_issued: dict[str, int] = field(default_factory=dict)
    last_rate_limited_ms: int | None = None


class FeedbackEngine:
    def __init__(self, config: FeedbackConfig, min_hold_ms: int) -> None:
        self._cfg = config
        self._min_hold_ms = min_hold_ms
        self._rule_messages = {r.id: r.message for r in config.form_rules}
        self._mem = _Memory()
        self._seq = 0
        self._current: FeedbackMessage | None = None
        self._last_event_seq: int | None = None
        self._bad_since: int | None = None
        self._waiting_since: int | None = None
        self._best_progress = 0.0
        self._last_progress_ms: int | None = None
        self._at_target_ok_since: int | None = None

    def update(self, inp: FeedbackInput) -> FeedbackState:
        ts = inp.timestamp_ms
        rule_statuses = inp.rules
        event = self._new_event(inp)

        # 1. Tracking: overrides everything and suppresses all judgements.
        self._bad_since = None if inp.signal_valid else (self._bad_since if self._bad_since is not None else ts)
        tracking_bad = self._bad_since is not None and ts - self._bad_since >= self._cfg.tracking_grace_ms
        if tracking_bad:
            person = any(a.status is not AngleStatus.NO_PERSON for a in inp.angles)
            key = MessageKey.TRACKING_UNCLEAR if person else MessageKey.NO_PERSON
            if self._current is None or self._current.key != key.value:
                self._issue(_Candidate(key.value, self._cfg.text(key), Category.TRACKING), ts)
            return FeedbackState(self._current, rule_statuses, tracking_ok=False)

        # 2. Retire messages whose time or condition has passed.
        cues = self._cue_candidates(inp)
        if self._current is not None and self._should_retire(self._current, cues, ts):
            self._current = None

        # Within the grace period the tracking message is held back, but no
        # judgement is made on unreliable data either.
        if not inp.signal_valid:
            return FeedbackState(self._current, rule_statuses, tracking_ok=False)

        # 3. Pick the best allowed candidate.
        candidates: list[_Candidate] = []
        if event is not None:
            candidates.append(event)
        for status in rule_statuses:
            if status.state is RuleState.VIOLATED and status.sustained:
                candidates.append(_Candidate(f"rule:{status.id}", self._rule_messages[status.id], Category.CORRECTION))
        candidates.extend(cues)
        candidates.sort(key=lambda c: PRIORITY[c.category], reverse=True)  # stable: config order breaks ties
        for c in candidates:
            if self._allowed(c, ts):
                self._issue(c, ts)
                break
        return FeedbackState(self._current, rule_statuses, tracking_ok=True)

    # ---------------------------------------------------------------- internals
    def _new_event(self, inp: FeedbackInput) -> _Candidate | None:
        """Each rep outcome is considered exactly once, on the frame it appears."""
        if inp.last_event_seq is None or inp.last_event_seq == self._last_event_seq:
            return None
        self._last_event_seq = inp.last_event_seq
        assert inp.last_event_kind is not None
        if inp.last_event_kind is RepEventKind.FORM_BROKEN:
            rule_text = self._rule_messages.get(inp.last_event_detail or "", "Keep the other joints steady.")
            # Concludes the rule's own live correction, so it may follow it at once.
            return _Candidate(
                "event:form_broken",
                f"Not counted: {rule_text}",
                Category.CORRECTION,
                concludes=f"rule:{inp.last_event_detail}",
            )
        mapped = _EVENT_MESSAGES.get(inp.last_event_kind)
        if mapped is None:
            return None
        key, category = mapped
        # Event-driven messages are keyed "event:<key>" so they are not retired
        # by the cue-condition check, but share the key's repeat cooldown.
        return _Candidate(f"event:{key.value}", self._cfg.text(key), category)

    def _cue_candidates(self, inp: FeedbackInput) -> list[_Candidate]:
        ts = inp.timestamp_ms
        cues: list[_Candidate] = []
        if inp.phase is RepPhase.AT_TARGET and self._min_hold_ms > 0 and inp.hold_ms < self._min_hold_ms:
            cues.append(_Candidate(MessageKey.HOLD.value, self._cfg.text(MessageKey.HOLD), Category.CUE))
        if inp.phase is RepPhase.WAITING_FOR_START:
            self._waiting_since = self._waiting_since if self._waiting_since is not None else ts
            if ts - self._waiting_since >= self._cfg.start_prompt_after_ms:
                key = MessageKey.RETURN_TO_START
                cues.append(_Candidate(key.value, self._cfg.text(key), Category.CUE))
        else:
            self._waiting_since = None
        cues.extend(self._progress_cues(inp))
        return cues

    def _progress_cues(self, inp: FeedbackInput) -> list[_Candidate]:
        """Coaching while moving and at the target. Condition cues: they vanish
        as soon as the situation changes."""
        ts = inp.timestamp_ms
        out: list[_Candidate] = []
        if inp.phase is RepPhase.MOVING and inp.progress is not None:
            if self._last_progress_ms is None or inp.progress > self._best_progress + 0.03:
                self._best_progress = max(self._best_progress, inp.progress)
                self._last_progress_ms = ts
            elif ts - self._last_progress_ms >= self._cfg.stall_ms and self._best_progress < 1.0:
                key = MessageKey.ALMOST_THERE if self._best_progress >= 0.75 else MessageKey.KEEP_GOING
                out.append(_Candidate(key.value, self._cfg.text(key), Category.CUE))
        elif inp.phase is not RepPhase.MOVING:
            self._best_progress, self._last_progress_ms = 0.0, None
        hold_done = self._min_hold_ms == 0 or inp.hold_ms >= self._min_hold_ms
        if inp.phase is RepPhase.AT_TARGET and hold_done:
            if self._at_target_ok_since is None:
                self._at_target_ok_since = ts
            if ts - self._at_target_ok_since >= self._cfg.return_cue_after_ms:
                out.append(_Candidate(MessageKey.RETURN_NOW.value, self._cfg.text(MessageKey.RETURN_NOW), Category.CUE))
        else:
            self._at_target_ok_since = None
        return out

    def _should_retire(self, cur: FeedbackMessage, cues: list[_Candidate], ts: int) -> bool:
        if cur.category is Category.TRACKING and not cur.key.startswith("event:"):
            return True  # tracking has recovered (we only get here when it is OK)
        if ts - cur.issued_ms >= self._cfg.display_ms:
            return True
        # A condition-based cue ("hold", "return to start") disappears as soon as
        # its condition ends; event-driven messages just time out.
        is_condition_cue = cur.category is Category.CUE and not cur.key.startswith("event:")
        return is_condition_cue and cur.key not in {c.key for c in cues}

    def _allowed(self, c: _Candidate, ts: int) -> bool:
        cur = self._current
        if cur is not None and cur.key == c.key:
            return False
        # A rep outcome that concludes the correction currently shown is the
        # same instruction, not a new or contradictory one: skip the cooldowns.
        if c.concludes is not None and cur is not None and cur.key == c.concludes:
            return True
        if c.category in _RATE_LIMITED:
            last = self._mem.last_rate_limited_ms
            if last is not None and ts - last < self._cfg.cooldown_ms:
                return False
            prev = self._mem.last_issued.get(_base_key(c.key))
            if prev is not None and ts - prev < self._cfg.repeat_cooldown_ms:
                return False
        if (
            cur is not None
            and ts - cur.issued_ms < self._cfg.min_display_ms
            and PRIORITY[c.category] <= PRIORITY[cur.category]
        ):
            return False
        return True

    def _issue(self, c: _Candidate, ts: int) -> None:
        self._seq += 1
        self._current = FeedbackMessage(self._seq, c.key, c.text, c.category, ts)
        self._mem.last_issued[_base_key(c.key)] = ts
        if c.category in _RATE_LIMITED:
            self._mem.last_rate_limited_ms = ts


def _base_key(key: str) -> str:
    return key.removeprefix("event:")

