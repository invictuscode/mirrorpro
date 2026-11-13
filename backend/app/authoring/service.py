"""Custom-exercise workflow: draft → (edit) → approve → offered to patients.

Rules enforced here:
* Suggestions from a demonstration only ever become a **draft**.
* Only an explicit approval (named reviewer + attestation) publishes an
  exercise to the library, marked ``approved`` with the reviewer's name.
* Editing an approved exercise creates a new draft version; patients keep the
  last approved version until the new one is approved.
* Angle data from a demonstration is stored only with explicit consent.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from app.authoring.recorder import DemonstrationCache
from app.authoring.store import CustomExerciseStore
from app.biomechanics.joints import JOINT_ANGLES
from app.exercises.library import ExerciseLibrary
from app.exercises.schema import (
    CameraSetup,
    ClinicalReview,
    ExerciseDefinition,
    ReviewStatus,
    SignalConfig,
    SideMode,
)
from app.feedback.config import FeedbackConfig, MessageKey
from app.pose.topology import LANDMARK_NAMES
from app.schemas.authoring import (
    ApproveRequest,
    CreateDraft,
    CustomExercise,
    DemonstrationRecord,
    DraftFields,
)


class AuthoringError(Exception):
    """Request conflicts with the exercise's state (HTTP 409)."""


class NotFound(Exception):
    """Unknown exercise or demonstration (HTTP 404)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:40] or "exercise"


def build_definition(
    exercise_id: str,
    version: int,
    f: DraftFields,
    status: ReviewStatus,
    reviewer: str | None = None,
    note: str | None = None,
) -> ExerciseDefinition:
    """Assemble and fully validate an exercise definition (same rules and
    wording guardrail as presets). Raises ValueError/ValidationError."""
    joints = list(dict.fromkeys([f.signal_joint, *(r.joint for r in f.form_rules)]))
    landmarks = sorted({LANDMARK_NAMES[i] for d in JOINT_ANGLES if d.joint in joints for i in d.landmarks})
    messages = {MessageKey.TARGET_NOT_REACHED: f.target_not_reached_message} if f.target_not_reached_message else {}
    return ExerciseDefinition(
        id=exercise_id,
        version=version,
        name=f.name,
        description=f.description,
        instructions=f.instructions,
        camera=CameraSetup(view=f.camera_view, angle_space=f.angle_space, guidance=f.camera_guidance),
        relevant_landmarks=landmarks,
        display_angles=joints,
        signal=SignalConfig(
            joint=f.signal_joint,
            side_mode=f.side_mode,
            default_side=f.default_side if f.side_mode is SideMode.SINGLE else None,
        ),
        rep_counting=f.rep_counting,
        dosage=f.dosage,
        feedback=FeedbackConfig(messages=messages, form_rules=f.form_rules),
        safety_notes=[],
        clinical_review=ClinicalReview(status=status, reviewed_by=reviewer, note=note),
    )



class CustomExerciseService:
    def __init__(self, store: CustomExerciseStore, library: ExerciseLibrary, demos: DemonstrationCache) -> None:
        self._store = store
        self._library = library
        self._demos = demos

    def load_approved_into_library(self) -> int:
        """At startup: offer every exercise's last approved version."""
        n = 0
        for rec in self._store.list():
            if rec.status != "archived" and rec.approved_definition is not None:
                self._library.upsert(rec.approved_definition)
                n += 1
        return n

    def list(self) -> list[CustomExercise]:
        return self._store.list()

    def get(self, exercise_id: str) -> CustomExercise:
        rec = self._store.get(exercise_id)
        if rec is None:
            raise NotFound(f"Unknown custom exercise {exercise_id!r}")
        return rec

    def create(self, req: CreateDraft) -> CustomExercise:
        exercise_id = f"custom_{_slug(req.fields.name)}_{secrets.token_hex(2)}"
        build_definition(exercise_id, 1, req.fields, ReviewStatus.DRAFT)  # validate now
        demos: list[DemonstrationRecord] = []
        if req.demo_id is not None:
            cached = self._demos.get(req.demo_id)
            if cached is None:
                raise NotFound(f"Demonstration {req.demo_id!r} is no longer available; record it again")
            info, series = cached
            demos.append(
                DemonstrationRecord(
                    demo_id=info.demo_id,
                    source=info.source,
                    duration_ms=info.duration_ms,
                    frames=info.frames,
                    angle_data_stored=req.store_angle_data,
                )
            )
            if req.store_angle_data:
                self._store.save_angle_data(exercise_id, info.demo_id, series)
        now = _now()
        rec = CustomExercise(
            id=exercise_id, status="draft", version=1, fields=req.fields, demonstrations=demos, created_at=now, updated_at=now
        )
        self._store.save(rec)
        return rec

    def update(self, exercise_id: str, fields: DraftFields) -> CustomExercise:
        rec = self.get(exercise_id)
        if rec.status == "archived":
            raise AuthoringError("Archived exercises cannot be edited")
        # Editing an approved exercise starts a new version that needs approval;
        # patients keep the approved one meanwhile.
        version = rec.version + 1 if rec.status == "approved" else rec.version
        build_definition(exercise_id, version, fields, ReviewStatus.DRAFT)
        rec = rec.model_copy(update={"fields": fields, "status": "draft", "version": version, "updated_at": _now()})
        self._store.save(rec)
        return rec

    def approve(self, exercise_id: str, req: ApproveRequest) -> CustomExercise:
        rec = self.get(exercise_id)
        if rec.status != "draft":
            raise AuthoringError(f"Only drafts can be approved (this exercise is {rec.status})")
        if not req.attestation:
            raise AuthoringError("Approval requires confirming that you reviewed the parameters")
        definition = build_definition(
            exercise_id,
            rec.version,
            rec.fields,
            ReviewStatus.APPROVED,
            reviewer=req.reviewer.strip(),
            note="Parameters derived from a demonstration and reviewed by the named therapist.",
        )
        now = _now()
        rec = rec.model_copy(
            update={
                "status": "approved",
                "approved_by": req.reviewer.strip(),
                "approved_at": now,
                "updated_at": now,
                "live_version": rec.version,
                "approved_definition": definition,
            }
        )
        self._store.save(rec)
        self._library.upsert(definition)
        return rec

    def archive(self, exercise_id: str) -> CustomExercise:
        rec = self.get(exercise_id)
        rec = rec.model_copy(update={"status": "archived", "updated_at": _now(), "live_version": None})
        self._store.save(rec)
        self._library.remove(exercise_id)
        return rec

    def delete(self, exercise_id: str) -> None:
        rec = self.get(exercise_id)
        if rec.approved_definition is not None and rec.status != "archived":
            raise AuthoringError("This exercise has been offered to patients; archive it instead of deleting")
        self._store.delete(exercise_id)
