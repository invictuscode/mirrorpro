"""Exercise sessions: sets, rest, pause/resume, timing and a summary.

One session at a time, held in memory (persistence is Phase 7). The manager
owns the active :class:`ExerciseTracker` while a session runs and installs it
in the pipeline via ``set_exercise``. Pausing detaches the tracker (nothing is
counted) and resuming re-attaches the same one, so the rep count survives.

Thread safety: API calls and the rest timer run on other threads than
``on_frame`` (inference thread); all state is guarded by one lock.

States::

    PRACTICE ──one rep done / advance (skip)──▶ ACTIVE (set 1)
    ACTIVE ──set reaches reps──▶ RESTING ──rest elapses / advance──▶ ACTIVE (next set)
      │  └──last set done──▶ COMPLETED
      ├─ pause ─▶ PAUSED ─ resume ─▶ (back to ACTIVE or RESTING)
      └─ end (any in-progress state) ─▶ ENDED
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.exercises.library import ExerciseLibrary
from app.exercises.phases import RepEventKind
from app.exercises.schema import ExerciseDefinition, RepCountingConfig, RepCountingOverrides, RuleOverride, Side
from app.feedback.config import FormRule
from app.exercises.tracker import ExerciseFrame, ExerciseTracker
from app.feedback.engine import Category
from app.schemas.session import (
    CorrectionCount,
    PeakStats,
    SessionMessage,
    SessionPlan,
    SessionSummary,
    SessionView,
    SetRecordView,
    StartSession,
)

log = logging.getLogger(__name__)

DEFAULT_REPS = 10
DEFAULT_REST_S = 30


class SessionState(StrEnum):
    PRACTICE = "practice"  # one guided rep before set 1; never counted
    ACTIVE = "active"
    RESTING = "resting"
    PAUSED = "paused"
    COMPLETED = "completed"
    ENDED = "ended"


_IN_PROGRESS = frozenset({SessionState.PRACTICE, SessionState.ACTIVE, SessionState.RESTING, SessionState.PAUSED})


class SessionConflict(Exception):
    """The request does not fit the current session state (HTTP 409)."""


class SessionNotFound(Exception):
    """Unknown exercise (HTTP 404)."""


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass(slots=True)
class _SetRecord:
    number: int
    reps: int
    active_ms: int
    ended_early: bool


@dataclass(slots=True)
class _Stats:
    peaks: list[float] = field(default_factory=list)
    rep_ms: list[int] = field(default_factory=list)
    uncounted: Counter[str] = field(default_factory=Counter)
    feedback: Counter[str] = field(default_factory=Counter)
    corrections: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _Session:
    id: int
    definition: ExerciseDefinition
    side: Side | None
    overrides: RepCountingOverrides | None
    plan: SessionPlan
    rep_config: RepCountingConfig
    form_rules: list[FormRule]
    rule_overrides: dict[str, RuleOverride]
    started_ms: int
    state: SessionState = SessionState.ACTIVE
    paused_from: SessionState | None = None
    state_since_ms: int = 0
    tracker: ExerciseTracker | None = None
    set_number: int = 0
    current_reps: int = 0
    set_active_ms: int = 0
    sets: list[_SetRecord] = field(default_factory=list)
    active_ms: int = 0
    rest_ms: int = 0
    rest_ends_ms: int | None = None
    rest_remaining_ms: int | None = None  # while paused during rest
    ended_ms: int | None = None
    stats: _Stats = field(default_factory=_Stats)
    practice: str | None = None  # "pending" | "completed" | "skipped" | None (not offered)
    last_event_seq: int = 0
    last_feedback_seq: int = 0


class SessionManager:
    def __init__(
        self,
        library: ExerciseLibrary,
        set_exercise: Callable[[ExerciseTracker | None], None],
        publish: Callable[[str], None],
        clock: Callable[[], int] = _monotonic_ms,
        schedule: Callable[[float, Callable[[], None]], threading.Timer] | None = None,
    ) -> None:
        self._library = library
        self._set_exercise = set_exercise
        self._publish = publish
        self._clock = clock
        self._schedule = schedule or _start_timer
        self._lock = threading.RLock()
        self._session: _Session | None = None
        self._next_id = 1
        self._timer: threading.Timer | None = None

    # ------------------------------------------------------------- queries
    @property
    def in_progress(self) -> bool:
        with self._lock:
            return self._session is not None and self._session.state in _IN_PROGRESS

    def view(self) -> SessionView | None:
        with self._lock:
            self._tick()
            return self._view() if self._session else None

    def message_json(self) -> str:
        return SessionMessage(session=self.view()).model_dump_json()

    # ------------------------------------------------------------ commands
    def start(self, req: StartSession) -> SessionView:
        with self._lock:
            if self.in_progress:
                raise SessionConflict("A session is already in progress; end it first")
            d = self._library.get(req.exercise_id)
            if d is None:
                raise SessionNotFound(f"Unknown exercise {req.exercise_id!r}")
            # Validate side/overrides up front (raises ValueError → 422).
            probe = ExerciseTracker(d, req.side, req.overrides, req.rule_overrides)
            plan = SessionPlan(
                sets=req.sets or d.dosage.sets or 1,
                reps_per_set=req.reps_per_set or d.dosage.reps_per_set or DEFAULT_REPS,
                rest_s=req.rest_s if req.rest_s is not None else DEFAULT_REST_S,
            )
            now = self._clock()
            self._session = _Session(
                id=self._next_id,
                definition=d,
                side=req.side,
                overrides=req.overrides,
                plan=plan,
                rep_config=probe.rep_config,
                form_rules=list(probe.definition.feedback.form_rules),
                rule_overrides=dict(req.rule_overrides),
                started_ms=now,
                state=SessionState.PRACTICE if req.practice else SessionState.ACTIVE,
                state_since_ms=now,
            )
            self._next_id += 1
            if req.practice:
                self._start_practice()
            else:
                self._begin_set(now)
            return self._changed()

    def pause(self) -> SessionView:
        with self._lock:
            s = self._require_in_progress()
            if s.state is SessionState.PAUSED:
                return self._view()
            now = self._clock()
            if s.state in (SessionState.ACTIVE, SessionState.PRACTICE):
                self._set_exercise(None)  # stop counting; keep the tracker
            else:  # RESTING
                assert s.rest_ends_ms is not None
                s.rest_remaining_ms = max(0, s.rest_ends_ms - now)
                self._cancel_timer()
            s.paused_from = s.state
            self._enter(SessionState.PAUSED, now)
            return self._changed()

    def resume(self) -> SessionView:
        with self._lock:
            s = self._require_in_progress()
            if s.state is not SessionState.PAUSED:
                return self._view()
            now = self._clock()
            if s.paused_from in (SessionState.ACTIVE, SessionState.PRACTICE):
                self._set_exercise(s.tracker)
                self._enter(s.paused_from, now)
            else:
                assert s.rest_remaining_ms is not None
                self._start_rest(now, s.rest_remaining_ms)
            s.paused_from = None
            s.rest_remaining_ms = None
            return self._changed()

    def advance(self) -> SessionView:
        """PRACTICE: skip the practice rep. ACTIVE: finish the current set now.
        RESTING: skip the rest."""
        with self._lock:
            s = self._require_in_progress()
            now = self._clock()
            if s.state is SessionState.PAUSED:
                raise SessionConflict("Resume the session before moving on")
            if s.state is SessionState.PRACTICE:
                s.practice = "skipped"
                self._begin_set(now)
            elif s.state is SessionState.ACTIVE:
                self._finish_set(now, ended_early=True)
            else:
                self._cancel_timer()
                self._begin_set(now)
            return self._changed()

    def end(self) -> SessionView:
        with self._lock:
            s = self._require_in_progress()
            now = self._clock()
            counting = s.state is SessionState.ACTIVE or s.paused_from is SessionState.ACTIVE
            if counting and s.current_reps > 0:
                self._record_set(now, ended_early=True)
            self._finish(now, SessionState.ENDED)
            return self._changed()

    def dismiss(self) -> None:
        """Clear a completed or ended session (e.g. back to the home screen)."""
        with self._lock:
            if self.in_progress:
                raise SessionConflict("End the session before dismissing it")
            self._session = None
            self._publish(SessionMessage(session=None).model_dump_json())

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer()

    # ------------------------------------------------------ inference thread
    def on_frame(self, frame: ExerciseFrame) -> None:
        with self._lock:
            s = self._session
            if (
                s is None
                or s.state not in (SessionState.ACTIVE, SessionState.PRACTICE)
                or s.tracker is None
                or frame.selection_id != s.tracker.selection_id
            ):
                return  # stale frame (paused, resting, or from a previous set)
            if s.state is SessionState.PRACTICE:
                # The practice rep is coaching only: nothing is recorded. It ends
                # after one full movement, even if a steady-joint check flagged it
                # (the patient has seen the reminder; nobody gets stuck practising).
                e = frame.counter.last_event
                full_attempt = e is not None and e.kind in (RepEventKind.FORM_BROKEN, RepEventKind.FORM_UNVERIFIED)
                if frame.counter.reps >= 1 or full_attempt:
                    s.practice = "completed"
                    self._begin_set(self._clock())
                    self._changed()
                return
            self._collect(s, frame)
            reps_changed = frame.counter.reps != s.current_reps
            s.current_reps = frame.counter.reps
            if s.current_reps >= s.plan.reps_per_set:
                self._finish_set(self._clock(), ended_early=False)
                self._changed()
            elif reps_changed:
                self._changed()

    # ------------------------------------------------------------ internals
    def _require_in_progress(self) -> _Session:
        s = self._session
        if s is None or s.state not in _IN_PROGRESS:
            raise SessionConflict("No session in progress")
        self._tick()
        return s

    def _tick(self) -> None:
        """Advance time-based transitions (rest ending) lazily."""
        s = self._session
        if s and s.state is SessionState.RESTING and s.rest_ends_ms is not None:
            if self._clock() >= s.rest_ends_ms:
                self._cancel_timer()
                # The set began when the rest ended, not when we noticed.
                self._begin_set(s.rest_ends_ms)

    def _enter(self, state: SessionState, now: int) -> None:
        s = self._session
        assert s is not None
        elapsed = now - s.state_since_ms
        if s.state is SessionState.ACTIVE:
            s.active_ms += elapsed
            s.set_active_ms += elapsed
        elif s.state is SessionState.RESTING:
            s.rest_ms += elapsed
        s.state = state
        s.state_since_ms = now

    def _begin_set(self, now: int) -> None:
        s = self._session
        assert s is not None
        s.set_number += 1
        s.current_reps = 0
        s.set_active_ms = 0
        s.last_event_seq = 0
        s.last_feedback_seq = 0
        s.rest_ends_ms = None
        s.tracker = ExerciseTracker(s.definition, s.side, s.overrides, s.rule_overrides)
        self._set_exercise(s.tracker)
        self._enter(SessionState.ACTIVE, now)

    def _start_practice(self) -> None:
        s = self._session
        assert s is not None
        s.practice = "pending"
        s.tracker = ExerciseTracker(s.definition, s.side, s.overrides, s.rule_overrides)
        self._set_exercise(s.tracker)

    def _record_set(self, now: int, *, ended_early: bool) -> None:
        s = self._session
        assert s is not None
        live = now - s.state_since_ms if s.state is SessionState.ACTIVE else 0
        s.sets.append(_SetRecord(s.set_number, s.current_reps, s.set_active_ms + live, ended_early))

    def _finish_set(self, now: int, *, ended_early: bool) -> None:
        s = self._session
        assert s is not None
        self._record_set(now, ended_early=ended_early)
        self._set_exercise(None)
        s.tracker = None
        if s.set_number >= s.plan.sets:
            self._finish(now, SessionState.COMPLETED)
        elif s.plan.rest_s == 0:
            self._begin_set(now)
        else:
            self._enter(SessionState.RESTING, now)
            self._start_rest(now, s.plan.rest_s * 1000)

    def _start_rest(self, now: int, duration_ms: int) -> None:
        s = self._session
        assert s is not None
        if s.state is not SessionState.RESTING:
            self._enter(SessionState.RESTING, now)
        s.rest_ends_ms = now + duration_ms
        self._cancel_timer()
        self._timer = self._schedule(duration_ms / 1000, self._on_rest_timer)

    def _on_rest_timer(self) -> None:
        with self._lock:
            s = self._session
            if s and s.state is SessionState.RESTING:
                self._tick()
                if s.state is SessionState.ACTIVE:
                    self._changed()

    def _finish(self, now: int, state: SessionState) -> None:
        s = self._session
        assert s is not None
        self._cancel_timer()
        self._set_exercise(None)
        if s.state is SessionState.PAUSED:
            # Close the pause without crediting it to active or rest time
            # (_enter only adds time for ACTIVE/RESTING, measured from now).
            s.state = s.paused_from or SessionState.ACTIVE
            s.state_since_ms = now
        self._enter(state, now)
        s.paused_from = None
        s.tracker = None
        s.ended_ms = now

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _collect(self, s: _Session, frame: ExerciseFrame) -> None:
        e = frame.counter.last_event
        if e is not None and e.seq > s.last_event_seq:
            s.last_event_seq = e.seq
            if e.kind is RepEventKind.REP_COMPLETED:
                if e.peak_deg is not None:
                    s.stats.peaks.append(e.peak_deg)
                if e.duration_ms is not None:
                    s.stats.rep_ms.append(e.duration_ms)
            else:
                s.stats.uncounted[e.kind.value] += 1
        m = frame.feedback.message
        if m is not None and m.seq > s.last_feedback_seq:
            s.last_feedback_seq = m.seq
            s.stats.feedback[m.category.value] += 1
            if m.category is Category.CORRECTION:
                s.stats.corrections[m.text] += 1

    def _changed(self) -> SessionView:
        view = self._view()
        self._publish(SessionMessage(session=view).model_dump_json())
        return view

    def _view(self) -> SessionView:
        s = self._session
        assert s is not None
        now = s.ended_ms if s.ended_ms is not None else self._clock()
        live = now - s.state_since_ms
        active = s.active_ms + (live if s.state is SessionState.ACTIVE else 0)
        rest = s.rest_ms + (live if s.state is SessionState.RESTING else 0)
        rest_remaining = None
        if s.state is SessionState.RESTING and s.rest_ends_ms is not None:
            rest_remaining = max(0, s.rest_ends_ms - now)
        elif s.state is SessionState.PAUSED and s.paused_from is SessionState.RESTING:
            rest_remaining = s.rest_remaining_ms
        sets = [SetRecordView(number=r.number, reps=r.reps, active_ms=r.active_ms, ended_early=r.ended_early) for r in s.sets]
        return SessionView(
            session_id=s.id,
            state=s.state.value,  # type: ignore[arg-type]
            paused_from=s.paused_from.value if s.paused_from else None,  # type: ignore[arg-type]
            exercise_id=s.definition.id,
            exercise_name=s.definition.name,
            exercise_version=s.definition.version,
            is_demo=s.definition.is_demo,
            side=s.tracker.side if s.tracker else s.side or s.definition.signal.default_side,
            selection_id=s.tracker.selection_id if s.tracker else None,
            plan=s.plan,
            practice=s.practice,  # type: ignore[arg-type]
            rep_counting=s.rep_config,
            form_rules=s.form_rules,
            current_set=s.set_number,
            current_set_reps=s.current_reps,
            sets=sets,
            active_ms=active,
            rest_ms=rest,
            elapsed_ms=now - s.started_ms,
            rest_remaining_ms=rest_remaining,
            summary=self._summary(s, sets, active, now) if s.state not in _IN_PROGRESS else None,
        )

    @staticmethod
    def _summary(s: _Session, sets: list[SetRecordView], active_ms: int, now: int) -> SessionSummary:
        st = s.stats
        return SessionSummary(
            total_reps=sum(r.reps for r in sets),
            sets_completed=sum(1 for r in sets if not r.ended_early),
            sets=sets,
            active_ms=active_ms,
            elapsed_ms=now - s.started_ms,
            uncounted=dict(st.uncounted),
            peak_deg=PeakStats(
                min_deg=round(min(st.peaks), 1),
                max_deg=round(max(st.peaks), 1),
                mean_deg=round(statistics.fmean(st.peaks), 1),
            )
            if st.peaks
            else None,
            mean_rep_ms=round(statistics.fmean(st.rep_ms)) if st.rep_ms else None,
            feedback_counts=dict(st.feedback),
            top_corrections=[CorrectionCount(text=t, count=c) for t, c in st.corrections.most_common(3)],
        )


def _start_timer(delay_s: float, fn: Callable[[], None]) -> threading.Timer:
    t = threading.Timer(delay_s, fn)
    t.daemon = True
    t.start()
    return t
