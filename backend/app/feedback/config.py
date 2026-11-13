"""Feedback configuration, embedded in each exercise definition.

Feedback is produced by explicit rules and fixed message text, never by a
generative model. All patient-facing wording is configurable so a therapist
can supply it; the defaults below are neutral, non-clinical placeholders.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.biomechanics.joints import JOINT_ANGLES
from app.exercises.phases import RepPhase

_KNOWN_JOINTS = frozenset(d.joint for d in JOINT_ANGLES)

# Guardrail against wording that implies clinical judgement the system cannot
# make (safety, diagnosis, treatment). Not a substitute for clinical review.
_PROHIBITED = re.compile(r"\b(safe\w*|unsafe|diagnos\w*|injur\w*|prescri\w*|cure\w*|heal\w*|treat\w*)\b", re.I)


def check_prohibited_wording(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("patient-facing text must not be empty")
    if m := _PROHIBITED.search(text):
        raise ValueError(
            f"{text!r} uses {m.group(0)!r}: patient-facing text must not make safety, diagnostic "
            "or treatment claims"
        )
    return text


def check_wording(text: str) -> str:
    """Validation for live feedback messages: guardrail plus a length limit so
    they stay readable from a distance."""
    text = check_prohibited_wording(text)
    if len(text) > 120:
        raise ValueError("feedback message must be at most 120 characters so it is readable at a distance")
    return text


class MessageKey(StrEnum):
    # Tracking (uncertainty, not a movement correction)
    NO_PERSON = "no_person"
    TRACKING_UNCLEAR = "tracking_unclear"
    # Rep outcomes
    REP_COMPLETED = "rep_completed"
    TARGET_NOT_REACHED = "target_not_reached"
    HOLD_TOO_SHORT = "hold_too_short"
    TOO_FAST = "too_fast"
    TIMED_OUT = "timed_out"
    FORM_UNVERIFIED = "form_unverified"
    # Cues
    HOLD = "hold"
    RETURN_TO_START = "return_to_start"
    KEEP_GOING = "keep_going"
    ALMOST_THERE = "almost_there"
    RETURN_NOW = "return_now"


DEFAULT_MESSAGES: dict[MessageKey, str] = {
    MessageKey.NO_PERSON: "Step into view of the camera.",
    MessageKey.TRACKING_UNCLEAR: "Your movement could not be tracked clearly. Adjust your position.",
    MessageKey.REP_COMPLETED: "Repetition completed.",
    MessageKey.TARGET_NOT_REACHED: "Try to move a little further toward the target.",
    MessageKey.HOLD_TOO_SHORT: "Hold the end position a little longer.",
    MessageKey.TOO_FAST: "Try a slower, controlled movement.",
    MessageKey.TIMED_OUT: "Return to the starting position to begin the next repetition.",
    MessageKey.FORM_UNVERIFIED: "That repetition could not be checked. Keep your whole body in view.",
    MessageKey.HOLD: "Hold this position briefly.",
    MessageKey.RETURN_TO_START: "Return to the starting position.",
    MessageKey.KEEP_GOING: "Keep going toward the target.",
    MessageKey.ALMOST_THERE: "Almost there. A little further.",
    MessageKey.RETURN_NOW: "Good. Now return slowly to the start.",
}


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleSide(StrEnum):
    SIGNAL = "signal"  # the side(s) currently driving the rep count
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"  # each reliably tracked side is checked


class FormRule(_Model):
    """A secondary-angle constraint, checked only during ``phases``. Violations
    must persist for ``sustain_ms`` before a message is considered."""

    id: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    joint: str
    side: RuleSide = RuleSide.SIGNAL
    phases: list[RepPhase] = Field(
        default_factory=lambda: [RepPhase.MOVING, RepPhase.AT_TARGET, RepPhase.RETURNING], min_length=1
    )
    min_deg: float | None = Field(default=None, ge=0, le=180)
    max_deg: float | None = Field(default=None, ge=0, le=180)
    sustain_ms: int = Field(default=400, ge=0, le=10_000)
    message: str
    out_of_plane_limit: float | None = Field(
        default=0.45,
        gt=0,
        lt=1,
        description="A 2D camera cannot see a joint bend toward/away from it, but the distal segment then looks "
        "shorter. If (distal length / proximal length) on screen falls below this fraction of its start-position "
        "value, the joint is treated as bent out of view (violated). None disables the check.",
    )
    blocks_rep: bool = Field(
        default=False,
        description="If true, a repetition during which this rule is broken, or its joint cannot be "
        "checked for much of the repetition, is not counted. Prevents doing the exercise with the wrong joint.",
    )

    @field_validator("joint")
    @classmethod
    def _known_joint(cls, v: str) -> str:
        if v not in _KNOWN_JOINTS:
            raise ValueError(f"unknown joint {v!r}; expected one of {sorted(_KNOWN_JOINTS)}")
        return v

    @field_validator("message")
    @classmethod
    def _wording(cls, v: str) -> str:
        return check_wording(v)

    @model_validator(mode="after")
    def _bounds(self) -> FormRule:
        if self.min_deg is None and self.max_deg is None:
            raise ValueError(f"form rule {self.id!r} needs min_deg and/or max_deg")
        if self.min_deg is not None and self.max_deg is not None and self.min_deg >= self.max_deg:
            raise ValueError(f"form rule {self.id!r}: min_deg must be less than max_deg")
        return self


class FeedbackConfig(_Model):
    # Minimum gap between two *different* corrections/cues: prevents rapid,
    # possibly contradictory instructions.
    cooldown_ms: int = Field(default=2500, ge=0, le=60_000)
    # Minimum gap before the *same* correction/cue is repeated.
    repeat_cooldown_ms: int = Field(default=8000, ge=0, le=300_000)
    # How long a message stays up, and how long before an equal-or-lower
    # priority message may replace it.
    display_ms: int = Field(default=3000, ge=500, le=30_000)
    min_display_ms: int = Field(default=1500, ge=0, le=30_000)
    # Driving angle unreliable this long → tracking message (shorter blips are
    # ignored; the rep counter already tolerates them).
    tracking_grace_ms: int = Field(default=700, ge=0, le=10_000)
    # Not back in the start position this long → "return to start" cue.
    start_prompt_after_ms: int = Field(default=4000, ge=500, le=60_000)
    # Moving but no progress toward the target for this long → "keep going".
    stall_ms: int = Field(default=1500, ge=300, le=20_000)
    # At the target (hold done, if any) this long → "now return".
    return_cue_after_ms: int = Field(default=700, ge=0, le=20_000)
    messages: dict[MessageKey, str] = Field(default_factory=dict, description="Overrides for DEFAULT_MESSAGES")
    form_rules: list[FormRule] = Field(default_factory=list)

    @field_validator("messages")
    @classmethod
    def _wording(cls, v: dict[MessageKey, str]) -> dict[MessageKey, str]:
        return {k: check_wording(text) for k, text in v.items()}

    @model_validator(mode="after")
    def _consistent(self) -> FeedbackConfig:
        if self.min_display_ms > self.display_ms:
            raise ValueError("min_display_ms must not exceed display_ms")
        ids = [r.id for r in self.form_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("form rule ids must be unique")
        return self

    def text(self, key: MessageKey) -> str:
        return self.messages.get(key, DEFAULT_MESSAGES[key])
