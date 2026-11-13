"""Repetition phases and event kinds, shared by the counter and the feedback
engine (kept separate so feedback configuration can reference them without
importing the counter)."""

from __future__ import annotations

from enum import StrEnum


class RepPhase(StrEnum):
    WAITING_FOR_START = "waiting_for_start"
    READY = "ready"
    MOVING = "moving"
    AT_TARGET = "at_target"
    RETURNING = "returning"


class RepEventKind(StrEnum):
    REP_COMPLETED = "rep_completed"
    TARGET_NOT_REACHED = "target_not_reached"
    HOLD_TOO_SHORT = "hold_too_short"
    TOO_FAST = "too_fast"
    TIMED_OUT = "timed_out"
    TRACKING_LOST = "tracking_lost"
    FORM_BROKEN = "form_broken"  # a blocking form rule was broken during the rep
    FORM_UNVERIFIED = "form_unverified"  # a blocking rule's joint was not visible for much of the rep
