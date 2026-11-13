"""Exercise library and active-exercise selection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.exercises.library import ExerciseLibrary
from app.exercises.schema import (
    CameraView,
    Dosage,
    ExerciseDefinition,
    RepCountingConfig,
    RepCountingOverrides,
    Side,
    SideMode,
)
from app.exercises.tracker import ExerciseTracker
from app.pipeline.tracking import TrackingPipeline

router = APIRouter(prefix="/api")


class ExerciseSummary(BaseModel):
    id: str
    version: int
    name: str
    description: str
    camera_view: CameraView
    side_mode: SideMode
    default_side: Side | None
    dosage: Dosage
    is_demo: bool


class SelectExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    side: Side | None = Field(default=None, description="Only for single-side exercises; defaults to the preset's")
    overrides: RepCountingOverrides | None = None


class ActiveExercise(BaseModel):
    selection_id: int = Field(description="Matches ExerciseStateMessage.selection_id in the stream")
    exercise: ExerciseDefinition
    side: Side | None
    overrides: RepCountingOverrides
    effective_rep_counting: RepCountingConfig = Field(description="Preset thresholds with overrides applied")


def _library(request: Request) -> ExerciseLibrary:
    return request.app.state.exercises


def _pipeline(request: Request) -> TrackingPipeline:
    return request.app.state.pipeline


def _summary(d: ExerciseDefinition) -> ExerciseSummary:
    return ExerciseSummary(
        id=d.id,
        version=d.version,
        name=d.name,
        description=d.description,
        camera_view=d.camera.view,
        side_mode=d.signal.side_mode,
        default_side=d.signal.default_side,
        dosage=d.dosage,
        is_demo=d.is_demo,
    )


def _no_session(request: Request) -> None:
    """Manual selection would hijack a running session's counter."""
    if request.app.state.sessions.in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "A session is in progress; use the session controls")


def _active(t: ExerciseTracker) -> ActiveExercise:
    return ActiveExercise(
        selection_id=t.selection_id,
        exercise=t.definition, side=t.side, overrides=t.overrides, effective_rep_counting=t.rep_config
    )


@router.get("/exercises")
def list_exercises(request: Request) -> list[ExerciseSummary]:
    return [_summary(d) for d in _library(request)]


@router.get("/exercises/{exercise_id}", responses={404: {"description": "Unknown exercise"}})
def get_exercise(exercise_id: str, request: Request) -> ExerciseDefinition:
    d = _library(request).get(exercise_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown exercise {exercise_id!r}")
    return d


@router.get("/exercise/active")
def get_active(request: Request) -> ActiveExercise | None:
    t = _pipeline(request).exercise
    return _active(t) if t else None


@router.put(
    "/exercise/active",
    responses={
        404: {"description": "Unknown exercise"},
        409: {"description": "A session is in progress"},
        422: {"description": "Invalid side or overrides"},
    },
)
def select_exercise(body: SelectExercise, request: Request) -> ActiveExercise:
    """Start tracking an exercise (count starts at 0). Replaces any active one."""
    _no_session(request)
    d = _library(request).get(body.exercise_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown exercise {body.exercise_id!r}")
    try:
        tracker = ExerciseTracker(d, body.side, body.overrides)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _messages(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    _pipeline(request).set_exercise(tracker)
    return _active(tracker)


@router.post("/exercise/active/reset", responses={409: {"description": "No active exercise"}})
def reset_exercise(request: Request) -> ActiveExercise:
    """Restart the count for the active exercise with the same settings."""
    _no_session(request)
    pipeline = _pipeline(request)
    t = pipeline.exercise
    if t is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No active exercise")
    fresh = ExerciseTracker(t.definition, t.side, t.overrides)
    pipeline.set_exercise(fresh)
    return _active(fresh)


@router.delete("/exercise/active", status_code=status.HTTP_204_NO_CONTENT)
def clear_exercise(request: Request) -> Response:
    _no_session(request)
    _pipeline(request).set_exercise(None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _messages(exc: ValidationError) -> str:
    return "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
