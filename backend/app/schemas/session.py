"""Exercise-session contract (REST responses and the WebSocket ``session``
text message). See docs/SESSIONS.md."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.exercises.schema import RepCountingConfig, RepCountingOverrides, RuleOverride, Side
from app.feedback.config import FormRule


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    side: Side | None = None
    overrides: RepCountingOverrides | None = None
    sets: int | None = Field(default=None, ge=1, le=20, description="Default: the exercise's dosage, else 1")
    reps_per_set: int | None = Field(default=None, ge=1, le=200, description="Default: dosage, else 10")
    rest_s: int | None = Field(default=None, ge=0, le=600, description="Rest between sets; default 30")
    practice: bool = Field(default=True, description="Start with one guided practice rep that is not counted")
    rule_overrides: dict[str, RuleOverride] = Field(
        default_factory=dict,
        description="Per form-rule adjustments for this session, e.g. a looser elbow allowance or reminder-only",
    )


class SessionPlan(BaseModel):
    sets: int
    reps_per_set: int
    rest_s: int


class SetRecordView(BaseModel):
    number: int
    reps: int
    active_ms: int
    ended_early: bool = Field(description="Set ended before reaching reps_per_set")


class PeakStats(BaseModel):
    min_deg: float
    max_deg: float
    mean_deg: float


class CorrectionCount(BaseModel):
    text: str
    count: int


class SessionSummary(BaseModel):
    total_reps: int
    sets_completed: int = Field(description="Sets that reached reps_per_set")
    sets: list[SetRecordView]
    active_ms: int
    elapsed_ms: int
    uncounted: dict[str, int] = Field(description="Uncounted attempts by reason (rep event kind)")
    peak_deg: PeakStats | None = Field(description="Furthest angle reached per counted rep (camera estimate)")
    mean_rep_ms: int | None
    feedback_counts: dict[str, int] = Field(description="Feedback messages shown, by category")
    top_corrections: list[CorrectionCount]


class SessionView(BaseModel):
    session_id: int
    state: Literal["practice", "active", "resting", "paused", "completed", "ended"]
    paused_from: Literal["practice", "active", "resting"] | None
    exercise_id: str
    exercise_name: str
    exercise_version: int
    is_demo: bool
    side: Side | None
    selection_id: int | None = Field(description="Active tracker (matches frames' exercise.selection_id)")
    plan: SessionPlan
    practice: Literal["pending", "completed", "skipped"] | None = Field(
        description="Practice rep status; null when the session started without one"
    )
    rep_counting: RepCountingConfig = Field(description="Effective thresholds (preset + overrides)")
    form_rules: list[FormRule] = Field(description="Effective form rules (preset + rule overrides)")
    current_set: int = Field(description="1-based number of the current (or last) set")
    current_set_reps: int
    sets: list[SetRecordView] = Field(description="Finished sets")
    active_ms: int = Field(description="Time spent exercising (excludes rest and pauses), as of this message")
    rest_ms: int
    elapsed_ms: int
    rest_remaining_ms: int | None
    summary: SessionSummary | None = Field(description="Present once the session is completed or ended")


class SessionMessage(BaseModel):
    type: Literal["session"] = "session"
    session: SessionView | None
