"""Repetition-counting state machine.

Driven only by ``update(angle_or_None, timestamp_ms)``; no camera or model
dependencies. Internally the angle is normalized so that "towards target" is
always increasing, which lets one machine handle e.g. curls (flexion rises)
and sit-to-stands (knee flexion falls).

Phases::

    WAITING_FOR_START ──in start zone──▶ READY ──leaves start zone──▶ MOVING
          ▲                                ▲                          │
          │ timeout / tracking lost        │ back to start            │ reaches target zone
          │ (from any active phase)        │ (TARGET_NOT_REACHED)     ▼
          │                                │                      AT_TARGET
          │                       counted ◀┴── RETURNING ◀── leaves target zone
          │                       (or TOO_FAST)             (after min hold; otherwise
          └────────────────────────────────────────────────  HOLD_TOO_SHORT → MOVING)

Robustness:
* Zone entry uses the threshold; zone exit needs the threshold ± hysteresis,
  so jitter on a boundary cannot chatter between phases.
* Every phase change must be observed continuously for ``confirm_ms``; a
  single noisy frame never changes phase. Missing samples cancel a pending
  change.
* An uncounted rep's final event keeps its real reason: returning to start
  after reaching (but not holding) the target reports HOLD_TOO_SHORT, not
  TARGET_NOT_REACHED.
* Blocking form rules (``FormCheck``): a rep during which a blocking rule was
  violated for at least its ``sustain_ms`` *and* at least ``BLOCK_FRACTION``
  of the rep, in total (adding up interrupted stretches, so tracking flicker
  cannot hide a real violation, while brief noise cannot fail a good rep), is
  reported as FORM_BROKEN, and one where a blocking rule's joint
  could not be checked for more than ``UNVERIFIED_LIMIT`` of the rep as
  FORM_UNVERIFIED. Neither is counted, so an exercise cannot be "completed"
  with the wrong joint or by hiding a joint from the camera.
* A short tracking gap freezes the machine; a gap longer than
  ``max_signal_gap_ms`` abandons the current rep (never counted).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.exercises.phases import RepEventKind, RepPhase
from app.exercises.schema import RepCountingConfig
from app.feedback.rules import FormCheck

__all__ = ["RepCounter", "RepCounterState", "RepEvent", "RepEventKind", "RepPhase"]


_ACTIVE = frozenset({RepPhase.MOVING, RepPhase.AT_TARGET, RepPhase.RETURNING})
UNVERIFIED_LIMIT = 0.5  # fraction of a rep a blocking rule's joint may be unverifiable
BLOCK_FRACTION = 0.2  # share of a rep a blocking rule must be broken for to fail it
_MAX_FRAME_GAP_MS = 250  # cap per-frame time credited to "unverified"


@dataclass(frozen=True, slots=True)
class RepEvent:
    seq: int
    kind: RepEventKind
    timestamp_ms: int
    peak_deg: float | None = None
    duration_ms: int | None = None
    hold_ms: int | None = None
    detail: str | None = None  # e.g. id of the broken form rule


@dataclass(frozen=True, slots=True)
class RepCounterState:
    phase: RepPhase
    reps: int
    signal_deg: float | None
    progress: float | None  # 0 at start threshold … 1 at target threshold
    hold_ms: int  # time spent in the target zone during the current rep
    last_event: RepEvent | None


class RepCounter:
    def __init__(self, config: RepCountingConfig) -> None:
        self._cfg = config
        self._sign = 1.0 if config.increasing else -1.0
        self._start = self._sign * config.start_deg
        self._target = self._sign * config.target_deg
        self._h = config.hysteresis_deg

        self.phase = RepPhase.WAITING_FOR_START
        self.reps = 0
        self._last_event: RepEvent | None = None
        self._seq = 0
        self._last_valid_ms: int | None = None
        self._pending: RepPhase | None = None
        self._pending_since = 0
        self._rep_start_ms = 0
        self._target_since_ms = 0
        self._peak = -float("inf")
        self._hold_ms = 0
        self._reached_target = False  # this rep entered the target zone at least once
        self._violated_ms: dict[str, int] = {}  # per blocking rule, total violated time this rep
        self._rule_sustain: dict[str, int] = {}
        self._unverified_ms = 0
        self._last_ts: int | None = None

    @property
    def config(self) -> RepCountingConfig:
        return self._cfg

    def update(self, angle_deg: float | None, timestamp_ms: int, form: FormCheck | None = None) -> RepCounterState:
        """``form`` summarises blocking form rules for this frame (None = no
        blocking rules)."""
        dt = 0 if self._last_ts is None else min(_MAX_FRAME_GAP_MS, max(0, timestamp_ms - self._last_ts))
        self._last_ts = timestamp_ms
        if form is not None and self.phase in _ACTIVE:
            for rule_id, sustain_ms in form.violated:
                self._violated_ms[rule_id] = self._violated_ms.get(rule_id, 0) + dt
                self._rule_sustain[rule_id] = sustain_ms
            if form.unverified:
                self._unverified_ms += dt
        self._check_gap(timestamp_ms)
        if angle_deg is None:
            self._pending = None
            return self._state(None, timestamp_ms)

        self._last_valid_ms = timestamp_ms
        x = self._sign * angle_deg
        if self.phase in _ACTIVE:
            self._peak = max(self._peak, x)
            if timestamp_ms - self._rep_start_ms > self._cfg.max_rep_ms:
                self._abandon(RepEventKind.TIMED_OUT, timestamp_ms)
                return self._state(angle_deg, timestamp_ms)

        candidate = self._candidate(x)
        if candidate is None:
            self._pending = None
        elif candidate is not self._pending:
            self._pending, self._pending_since = candidate, timestamp_ms
        if self._pending is not None and timestamp_ms - self._pending_since >= self._cfg.confirm_ms:
            self._transition(self._pending, self._pending_since)
            self._pending = None
        return self._state(angle_deg, timestamp_ms)

    # ---------------------------------------------------------------- internals
    def _candidate(self, x: float) -> RepPhase | None:
        """Phase the current sample argues for, or None to stay put."""
        in_start = x <= self._start
        left_start = x > self._start + self._h
        in_target = x >= self._target
        left_target = x < self._target - self._h
        match self.phase:
            case RepPhase.WAITING_FOR_START:
                return RepPhase.READY if in_start else None
            case RepPhase.READY:
                return RepPhase.MOVING if left_start else None
            case RepPhase.MOVING:
                if in_target:
                    return RepPhase.AT_TARGET
                return RepPhase.READY if in_start else None
            case RepPhase.AT_TARGET:
                return RepPhase.RETURNING if left_target else None
            case RepPhase.RETURNING:
                return RepPhase.READY if in_start else None

    def _transition(self, to: RepPhase, at_ms: int) -> None:
        frm = self.phase
        if frm is RepPhase.READY and to is RepPhase.MOVING:
            self._rep_start_ms = at_ms
            self._peak = -float("inf")
            self._hold_ms = 0
            self._reached_target = False
            self._violated_ms = {}
            self._unverified_ms = 0
        elif frm is RepPhase.MOVING and to is RepPhase.READY:
            # Final outcome of an uncounted rep: keep the real reason.
            kind = RepEventKind.HOLD_TOO_SHORT if self._reached_target else RepEventKind.TARGET_NOT_REACHED
            self._emit(kind, at_ms)
        elif to is RepPhase.AT_TARGET:
            self._target_since_ms = at_ms
            self._reached_target = True
        elif frm is RepPhase.AT_TARGET:
            self._hold_ms = max(self._hold_ms, at_ms - self._target_since_ms)
            if self._hold_ms < self._cfg.min_hold_ms:
                self._emit(RepEventKind.HOLD_TOO_SHORT, at_ms)
                to = RepPhase.MOVING
        elif frm is RepPhase.RETURNING:
            duration = at_ms - self._rep_start_ms
            if duration < self._cfg.min_rep_ms:
                self._emit(RepEventKind.TOO_FAST, at_ms)
            elif (broken := self._broken_rule(duration)) is not None:
                self._emit(RepEventKind.FORM_BROKEN, at_ms, detail=broken)
            elif self._unverified_ms > UNVERIFIED_LIMIT * duration:
                self._emit(RepEventKind.FORM_UNVERIFIED, at_ms)
            else:
                self.reps += 1
                self._emit(RepEventKind.REP_COMPLETED, at_ms)
        self.phase = to

    def _broken_rule(self, duration_ms: int) -> str | None:
        """The blocking rule violated long enough to fail this rep, if any."""
        for rule_id, ms in self._violated_ms.items():
            if ms >= self._rule_sustain.get(rule_id, 0) and ms >= BLOCK_FRACTION * duration_ms:
                return rule_id
        return None

    def _check_gap(self, now_ms: int) -> None:
        if self._last_valid_ms is None or now_ms - self._last_valid_ms <= self._cfg.max_signal_gap_ms:
            return
        if self.phase in _ACTIVE:
            self._abandon(RepEventKind.TRACKING_LOST, now_ms)
        else:
            self.phase = RepPhase.WAITING_FOR_START
        self._pending = None
        self._last_valid_ms = None

    def _abandon(self, kind: RepEventKind, at_ms: int) -> None:
        self._emit(kind, at_ms)
        self.phase = RepPhase.WAITING_FOR_START
        self._pending = None

    def _emit(self, kind: RepEventKind, at_ms: int, detail: str | None = None) -> None:
        self._seq += 1
        has_rep = self._peak > -float("inf")
        self._last_event = RepEvent(
            seq=self._seq,
            kind=kind,
            timestamp_ms=at_ms,
            peak_deg=round(self._sign * self._peak, 1) if has_rep else None,
            duration_ms=at_ms - self._rep_start_ms if has_rep else None,
            hold_ms=self._hold_ms if has_rep else None,
            detail=detail,
        )

    def _state(self, angle_deg: float | None, now_ms: int) -> RepCounterState:
        progress = None
        if angle_deg is not None:
            x = self._sign * angle_deg
            progress = min(1.0, max(0.0, (x - self._start) / (self._target - self._start)))
        hold = now_ms - self._target_since_ms if self.phase is RepPhase.AT_TARGET else 0
        return RepCounterState(
            phase=self.phase,
            reps=self.reps,
            signal_deg=angle_deg,
            progress=progress,
            hold_ms=max(0, hold),
            last_event=self._last_event,
        )
