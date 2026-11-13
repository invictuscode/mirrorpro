"""Backend → frontend message contract. See docs/PROTOCOL.md.

Text WebSocket messages carry JSON :class:`StatusMessage`.
Binary WebSocket messages carry one *frame packet* (:func:`encode_frame_packet`):

    [uint32 big-endian: N][N bytes UTF-8 JSON FrameMessage][optional JPEG bytes]

Bundling the landmarks and preview image in one message keeps them exactly in
sync and avoids base64-inflating the JPEG.
"""

from __future__ import annotations

import struct
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 8
_HEADER = struct.Struct(">I")


class PipelineState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ErrorCode(StrEnum):
    MODEL_MISSING = "model_missing"
    DETECTOR_INIT_FAILED = "detector_init_failed"
    CAMERA_OPEN_FAILED = "camera_open_failed"
    CAMERA_READ_FAILED = "camera_read_failed"
    INFERENCE_FAILED = "inference_failed"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    protocol_version: int = PROTOCOL_VERSION
    state: PipelineState
    error: ErrorInfo | None = None
    camera: str | None = None
    model: str
    profile: str
    preview_enabled: bool
    angle_space: str = Field(description="Default angle space: 'image' (2D) or 'world' (3D model estimate)")


class FrameMetrics(BaseModel):
    capture_fps: float = Field(description="Frames read from the camera per second")
    inference_fps: float = Field(description="Frames run through the pose model per second")
    inference_ms: float = Field(description="Smoothed pose-model time per frame")
    latency_ms: float = Field(description="Capture → packet-ready time for this frame")
    dropped_frames: int = Field(
        description="Captured frames skipped because inference was busy (expected; "
        "the pipeline always processes the newest frame)"
    )


class AngleMeasurement(BaseModel):
    id: str = Field(description="Joint-angle definition id, see GET /api/angles/definitions")
    status: str = Field(
        description="ok | no_person | low_visibility | out_of_frame | degenerate | unavailable"
    )
    value_deg: float | None = Field(description="Smoothed estimate; null unless status is ok")
    raw_deg: float | None = Field(description="Unsmoothed estimate for this frame; null unless ok")
    confidence: float | None = Field(description="Min visibility of the three landmarks")


class RepEventMessage(BaseModel):
    seq: int = Field(description="Increases with every event; use it to detect new events")
    kind: str = Field(
        description="rep_completed | target_not_reached | hold_too_short | too_fast | timed_out | tracking_lost "
        "| form_broken | form_unverified"
    )
    timestamp_ms: int
    peak_deg: float | None = Field(description="Furthest angle reached towards the target in that rep")
    duration_ms: int | None
    hold_ms: int | None
    detail: str | None = Field(default=None, description="For form_broken: the broken rule's id")


class FeedbackMessageModel(BaseModel):
    seq: int = Field(description="Increases with every new message")
    key: str = Field(description="Message key, 'event:<key>' for rep outcomes, or 'rule:<id>' for form rules")
    text: str
    category: str = Field(description="tracking | correction | cue | positive")
    issued_ms: int


class RuleStatusMessage(BaseModel):
    id: str
    state: str = Field(description="inactive | ok | violated | uncertain")
    value_deg: float | None
    sustained: bool = Field(description="Violated for at least the rule's sustain time")
    blocks_rep: bool = Field(description="Breaking this rule (or hiding its joint) stops the rep counting")
    reason: str | None = Field(
        default=None, description="Why it is violated: 'angle' (outside bounds) or 'out_of_plane' (bent toward/away from the camera)"
    )


class FeedbackStateMessage(BaseModel):
    message: FeedbackMessageModel | None = Field(description="The one message to show now, if any")
    rules: list[RuleStatusMessage]
    tracking_ok: bool = Field(description="False while the driving angle is unreliable: no judgements are made")


class ExerciseStateMessage(BaseModel):
    exercise_id: str
    selection_id: int = Field(description="Changes whenever the exercise is selected or reset (any client)")
    side: str | None = Field(description="Selected side for single-side exercises")
    sides_used: list[str] = Field(description="Sides whose angle drove counting this frame")
    phase: str = Field(description="waiting_for_start | ready | moving | at_target | returning")
    reps: int
    signal_deg: float | None = Field(description="Angle driving the count; null when not reliably tracked")
    progress: float | None = Field(description="0 at the start threshold … 1 at the target threshold")
    hold_ms: int
    last_event: RepEventMessage | None
    feedback: FeedbackStateMessage


class FrameMessage(BaseModel):
    type: Literal["frame"] = "frame"
    frame_id: int
    timestamp_ms: int = Field(description="Monotonic capture time; not wall-clock")
    width: int = Field(description="Source frame width in pixels")
    height: int = Field(description="Source frame height in pixels")
    person_detected: bool
    landmarks: list[list[float]] | None = Field(
        default=None,
        description="33 × [x, y, z, visibility, presence]; x/y normalized to the image",
    )
    has_preview: bool
    angle_space: str = Field(description="Space used for this frame's angles (the active exercise's, if any)")
    angles: list[AngleMeasurement] = Field(default_factory=list)
    exercise: ExerciseStateMessage | None = None
    metrics: FrameMetrics


def encode_frame_packet(message: FrameMessage, jpeg: bytes | None) -> bytes:
    payload = message.model_dump_json().encode("utf-8")
    return _HEADER.pack(len(payload)) + payload + (jpeg or b"")


def decode_frame_packet(packet: bytes) -> tuple[FrameMessage, bytes]:
    """Inverse of :func:`encode_frame_packet` (used by tests and tooling)."""
    if len(packet) < _HEADER.size:
        raise ValueError("Packet shorter than header")
    (n,) = _HEADER.unpack_from(packet)
    end = _HEADER.size + n
    if end > len(packet):
        raise ValueError("Header length exceeds packet size")
    return FrameMessage.model_validate_json(packet[_HEADER.size : end]), packet[end:]
