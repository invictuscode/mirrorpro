"""Exercise definition schema.

Definitions are data, independent of any video. They are versioned so later
phases can store per-patient or per-therapist variants and keep history.

Clinical content (targets, safety notes) must come from a qualified
professional. Shipped presets are demonstrations: ``clinical_review.status``
is ``unreviewed_demo`` and their numbers are illustrative only.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.biomechanics import AngleSpace
from app.biomechanics.joints import JOINT_ANGLES
from app.feedback.config import FeedbackConfig, FormRule, check_prohibited_wording, check_wording
from app.pose.topology import LANDMARK_NAMES

KNOWN_JOINTS = frozenset(d.joint for d in JOINT_ANGLES)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CameraView(StrEnum):
    FRONT = "front"  # patient faces the camera
    SIDE = "side"  # patient's side (the working side, if one-sided) faces the camera


class SideMode(StrEnum):
    SINGLE = "single"  # one side, chosen when the exercise is started
    MEAN_OF_VISIBLE = "mean_of_visible"  # average of whichever sides are reliably tracked


class Side(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class ReviewStatus(StrEnum):
    UNREVIEWED_DEMO = "unreviewed_demo"  # shipped demonstration presets
    DRAFT = "draft"  # custom exercise awaiting therapist approval; never shown to patients
    APPROVED = "approved"


class CameraSetup(_Model):
    view: CameraView
    angle_space: AngleSpace = Field(description="Coordinate space used for this exercise's angles")
    guidance: str = Field(description="Placement instructions shown to the user")


class SignalConfig(_Model):
    """The angle that drives repetition counting."""

    joint: str = Field(description="Joint-angle family, e.g. 'elbow_flexion'")
    side_mode: SideMode
    default_side: Side | None = None

    @field_validator("joint")
    @classmethod
    def _known_joint(cls, v: str) -> str:
        if v not in KNOWN_JOINTS:
            raise ValueError(f"unknown joint {v!r}; expected one of {sorted(KNOWN_JOINTS)}")
        return v

    @model_validator(mode="after")
    def _side(self) -> SignalConfig:
        if self.side_mode is SideMode.SINGLE and self.default_side is None:
            raise ValueError("default_side is required when side_mode is 'single'")
        return self


class RepCountingConfig(_Model):
    """Thresholds and timing for the repetition state machine.

    A rep is: leave the start zone → reach the target zone (and optionally hold)
    → return to the start zone. ``target_deg`` may be above or below
    ``start_deg``; the direction is inferred.
    """

    start_deg: float = Field(ge=0, le=180, description="Boundary of the start zone")
    target_deg: float = Field(ge=0, le=180, description="Boundary of the target zone")
    hysteresis_deg: float = Field(default=5.0, ge=0, le=30, description="Margin to leave a zone, prevents chatter")
    confirm_ms: int = Field(default=100, ge=0, le=2000, description="A zone change must persist this long")
    min_hold_ms: int = Field(default=0, ge=0, le=60_000, description="Required time in the target zone")
    min_rep_ms: int = Field(default=600, ge=0, le=60_000, description="Faster reps are not counted")
    max_rep_ms: int = Field(default=20_000, ge=1000, le=300_000, description="Slower reps are abandoned")
    max_signal_gap_ms: int = Field(
        default=750, ge=0, le=10_000, description="Tracking loss longer than this abandons the current rep"
    )

    @property
    def increasing(self) -> bool:
        return self.target_deg > self.start_deg

    @model_validator(mode="after")
    def _separated(self) -> RepCountingConfig:
        if abs(self.target_deg - self.start_deg) <= 2 * self.hysteresis_deg:
            raise ValueError(
                "start_deg and target_deg must be more than 2 × hysteresis_deg apart "
                f"(got {self.start_deg}, {self.target_deg}, hysteresis {self.hysteresis_deg})"
            )
        if self.min_rep_ms >= self.max_rep_ms:
            raise ValueError("min_rep_ms must be less than max_rep_ms")
        return self


class Dosage(_Model):
    """Illustrative defaults; a therapist's plan (Phase 7) overrides these."""

    reps_per_set: int | None = Field(default=None, ge=1, le=200)
    sets: int | None = Field(default=None, ge=1, le=20)


class PhaseCues(_Model):
    """Short coaching line for each part of a repetition, shown on the mirror
    (and drawn next to the guide arrows during the practice repetition)."""

    start: str = "Get into the starting position."
    move: str = "Move slowly toward the green target line."
    hold: str = "Hold this position."
    back: str = "Return slowly to the start."

    @field_validator("start", "move", "hold", "back")
    @classmethod
    def _wording(cls, v: str) -> str:
        return check_wording(v)


class Guidance(_Model):
    setup: list[str] = Field(default_factory=list, description="Positioning and equipment, before starting")
    cues: PhaseCues = PhaseCues()
    key_points: list[str] = Field(default_factory=list, description="What to keep in mind during every repetition")
    tempo: str | None = Field(default=None, max_length=120)

    @field_validator("setup", "key_points")
    @classmethod
    def _lines(cls, v: list[str]) -> list[str]:
        return [check_prohibited_wording(line) for line in v]

    @field_validator("tempo")
    @classmethod
    def _tempo(cls, v: str | None) -> str | None:
        return None if v is None else check_prohibited_wording(v)


class ClinicalReview(_Model):
    status: ReviewStatus
    reviewed_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _approved_needs_reviewer(self) -> ClinicalReview:
        if self.status is ReviewStatus.APPROVED and not self.reviewed_by:
            raise ValueError("approved definitions must name the reviewer")
        return self


class ExerciseDefinition(_Model):
    id: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    description: str
    instructions: list[str] = Field(min_length=1)
    camera: CameraSetup
    relevant_landmarks: list[str] = Field(min_length=1)
    display_angles: list[str] = Field(min_length=1, description="Joint families shown during the exercise")
    signal: SignalConfig
    rep_counting: RepCountingConfig
    dosage: Dosage = Dosage()
    feedback: FeedbackConfig = FeedbackConfig()
    guidance: Guidance = Guidance()
    safety_notes: list[str] = Field(
        default_factory=list, description="Must be supplied or approved by a qualified professional"
    )
    clinical_review: ClinicalReview
    reference_demonstration: str | None = Field(default=None, description="Reserved for Phase 6")

    @field_validator("relevant_landmarks")
    @classmethod
    def _known_landmarks(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(LANDMARK_NAMES))
        if unknown:
            raise ValueError(f"unknown landmarks: {unknown}")
        return v

    @field_validator("instructions")
    @classmethod
    def _instruction_wording(cls, v: list[str]) -> list[str]:
        # Instructions are patient-facing too: same wording guardrail, but no
        # distance-readability length limit (they are read before starting).
        return [check_prohibited_wording(line) for line in v]

    @field_validator("display_angles")
    @classmethod
    def _known_display(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - KNOWN_JOINTS)
        if unknown:
            raise ValueError(f"unknown joints in display_angles: {unknown}")
        return v

    @property
    def is_demo(self) -> bool:
        return self.clinical_review.status is ReviewStatus.UNREVIEWED_DEMO


class RuleOverride(_Model):
    """Per-session adjustment of one form rule (only the fields provided)."""

    min_deg: float | None = Field(default=None, ge=0, le=180)
    max_deg: float | None = Field(default=None, ge=0, le=180)
    blocks_rep: bool | None = None


def apply_rule_overrides(rules: list[FormRule], overrides: dict[str, RuleOverride]) -> list[FormRule]:
    """Return ``rules`` with overrides applied and re-validated (e.g. a rule
    must keep at least one bound, and min < max). Unknown rule ids are errors."""
    unknown = sorted(set(overrides) - {r.id for r in rules})
    if unknown:
        raise ValueError(f"unknown form rule(s): {unknown}")
    out = []
    for r in rules:
        o = overrides.get(r.id)
        out.append(r if o is None else FormRule.model_validate(r.model_dump() | o.model_dump(exclude_unset=True)))
    return out


class RepCountingOverrides(_Model):
    """Therapist adjustments applied when an exercise is started."""

    start_deg: float | None = Field(default=None, ge=0, le=180)
    target_deg: float | None = Field(default=None, ge=0, le=180)
    min_hold_ms: int | None = Field(default=None, ge=0, le=60_000)

    def apply(self, base: RepCountingConfig) -> RepCountingConfig:
        """Return ``base`` with overrides applied. Raises ``ValueError`` (via
        validation) if the result is inconsistent, e.g. thresholds too close or
        the direction flipped."""
        updates = self.model_dump(exclude_none=True)
        merged = RepCountingConfig.model_validate(base.model_dump() | updates)
        if merged.increasing != base.increasing:
            raise ValueError(
                "overrides would reverse the movement direction "
                f"(start {merged.start_deg}°, target {merged.target_deg}°)"
            )
        return merged
