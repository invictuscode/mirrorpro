"""Custom-exercise authoring contract: demonstrations, analysis, drafts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.biomechanics import AngleSpace
from app.exercises.schema import CameraView, Dosage, ExerciseDefinition, RepCountingConfig, Side, SideMode
from app.feedback.config import FormRule


class DemonstrationInfo(BaseModel):
    demo_id: str
    source: Literal["live", "upload"]
    angle_space: AngleSpace
    duration_ms: int
    frames: int
    person_fraction: float = Field(description="Fraction of frames in which a person was detected")


class LiveRecordingStatus(BaseModel):
    recording: bool
    elapsed_ms: int
    frames: int
    max_ms: int


class JointCandidate(BaseModel):
    joint: str
    side_mode: SideMode
    side: Side | None = Field(description="Moving side for single-side candidates")
    range_deg: float = Field(description="Robust range of motion (5th–95th percentile) in the demonstration")
    valid_fraction: float = Field(description="Fraction of frames where this angle was reliably tracked")
    score: float


class DetectedRep(BaseModel):
    start_ms: int
    end_ms: int
    peak_deg: float
    hold_ms: int = Field(description="Time spent near the peak")


class AnalysisWarning(BaseModel):
    code: str
    message: str


class SuggestedRule(BaseModel):
    include: bool = Field(description="Suggested rules are off until the therapist opts in")
    rule: FormRule
    observed_range_deg: tuple[float, float]


class ChartSeries(BaseModel):
    t_ms: list[int]
    deg: list[float | None]


class AnalysisResult(BaseModel):
    demo_id: str
    joint_candidates: list[JointCandidate]
    chosen: JointCandidate | None
    increasing: bool | None = Field(description="Whether the angle rises from start to target")
    rest_deg: float | None
    typical_peak_deg: float | None
    reps: list[DetectedRep]
    suggested_rep_counting: RepCountingConfig | None
    suggested_rules: list[SuggestedRule]
    warnings: list[AnalysisWarning]
    chart: ChartSeries | None = Field(description="Driving angle over time, downsampled for display")


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joint: str | None = Field(default=None, description="Override the driving joint")
    side_mode: SideMode | None = None
    side: Side | None = None
    start_position: Literal["low", "high"] | None = Field(
        default=None, description="Override where the start position is (low or high end of the angle range)"
    )


class DraftFields(BaseModel):
    """Everything a therapist edits. Validated as a full exercise definition."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    instructions: list[str] = Field(min_length=1)
    camera_view: CameraView
    camera_guidance: str = Field(min_length=1, max_length=300)
    angle_space: AngleSpace = AngleSpace.IMAGE
    signal_joint: str
    side_mode: SideMode
    default_side: Side | None = None
    rep_counting: RepCountingConfig
    dosage: Dosage = Dosage(reps_per_set=10, sets=2)
    target_not_reached_message: str | None = None
    form_rules: list[FormRule] = Field(default_factory=list)


class CreateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: DraftFields
    demo_id: str | None = Field(default=None, description="Demonstration the parameters were derived from")
    store_angle_data: bool = Field(
        default=False, description="Explicit consent to save the demonstration's angle series (never video)"
    )


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=2, max_length=120)
    attestation: bool = Field(description="Reviewer confirms they reviewed and accept the parameters")


class DemonstrationRecord(BaseModel):
    demo_id: str
    source: Literal["live", "upload"]
    duration_ms: int
    frames: int
    angle_data_stored: bool
    analysis_summary: str | None = None


class CustomExercise(BaseModel):
    id: str
    status: Literal["draft", "approved", "archived"]
    version: int
    fields: DraftFields
    demonstrations: list[DemonstrationRecord]
    created_at: str
    updated_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    live_version: int | None = Field(
        default=None, description="Approved version currently offered to patients (may lag behind a newer draft)"
    )
    approved_definition: ExerciseDefinition | None = None
