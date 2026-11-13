"""Therapist authoring endpoints: demonstrations, analysis, custom exercises.

No authentication yet: acceptable only while the backend listens on
127.0.0.1. Must be protected before any networked deployment (Phase 7+).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError

from app.authoring.analysis import analyze
from app.authoring.recorder import DemonstrationCache, LiveRecorder, RecordingError
from app.authoring.service import AuthoringError, CustomExerciseService, NotFound
from app.authoring.video import VideoError, process_video
from app.biomechanics import AngleSpace
from app.schemas.authoring import (
    AnalysisResult,
    AnalyzeRequest,
    ApproveRequest,
    CreateDraft,
    CustomExercise,
    DemonstrationInfo,
    DraftFields,
    LiveRecordingStatus,
)
from app.schemas.messages import PipelineState

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
_ERRORS = {404: {"description": "Not found"}, 409: {"description": "Not allowed now"}, 422: {"description": "Invalid"}}


def _recorder(request: Request) -> LiveRecorder:
    return request.app.state.recorder


def _service(request: Request) -> CustomExerciseService:
    return request.app.state.custom_exercises


def _validation_detail(exc: ValidationError) -> str:
    return "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())


# --- demonstrations ----------------------------------------------------------
@router.get("/demonstrations/live")
def live_status(request: Request) -> LiveRecordingStatus:
    return _recorder(request).status()


@router.post("/demonstrations/live/start", responses=_ERRORS)
def live_start(request: Request) -> LiveRecordingStatus:
    if request.app.state.pipeline.state is not PipelineState.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start the camera before recording")
    if request.app.state.sessions.in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "End the exercise session before recording a demonstration")
    try:
        return _recorder(request).start()
    except RecordingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/demonstrations/live/stop", responses=_ERRORS)
def live_stop(request: Request) -> DemonstrationInfo:
    rec = _recorder(request)
    if not rec.recording:
        raise HTTPException(status.HTTP_409_CONFLICT, "No recording in progress")
    try:
        return rec.stop()
    except RecordingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/demonstrations/live/cancel", status_code=status.HTTP_204_NO_CONTENT)
def live_cancel(request: Request) -> Response:
    _recorder(request).cancel()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/demonstrations/upload",
    responses={413: {"description": "File too large"}, **_ERRORS},
    openapi_extra={"requestBody": {"content": {"video/*": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def upload_demonstration(request: Request, angle_space: AngleSpace = AngleSpace.IMAGE) -> DemonstrationInfo:
    """Body: the raw video file. It is processed locally and deleted
    immediately afterwards; only the extracted angles are kept (in memory)."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Video is larger than 300 MB")
    fd, tmp_name = tempfile.mkstemp(prefix="ptm-demo-", suffix=".video")
    tmp = Path(tmp_name)
    try:
        size = 0
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Video is larger than 300 MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The upload was empty")
        app = request.app
        try:
            series, frac = await asyncio.to_thread(
                process_video, tmp, app.state.settings, app.state.detector_factory, angle_space
            )
        except VideoError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        cache: DemonstrationCache = app.state.demonstrations
        return cache.add("upload", series, frac)
    finally:
        tmp.unlink(missing_ok=True)  # never keep the video


@router.post("/demonstrations/{demo_id}/analyze", responses=_ERRORS)
def analyze_demonstration(demo_id: str, body: AnalyzeRequest, request: Request) -> AnalysisResult:
    cached = request.app.state.demonstrations.get(demo_id)
    if cached is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demonstration not found (it may have expired); record it again")
    _, series = cached
    try:
        return analyze(demo_id, series, body.joint, body.side_mode, body.side, body.start_position)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


# --- custom exercises --------------------------------------------------------
def _call(fn, *args):  # type: ignore[no-untyped-def]
    try:
        return fn(*args)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except AuthoringError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _validation_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/custom-exercises")
def list_custom(request: Request) -> list[CustomExercise]:
    return _service(request).list()


@router.post("/custom-exercises", responses=_ERRORS)
def create_custom(body: CreateDraft, request: Request) -> CustomExercise:
    return _call(_service(request).create, body)


@router.get("/custom-exercises/{exercise_id}", responses=_ERRORS)
def get_custom(exercise_id: str, request: Request) -> CustomExercise:
    return _call(_service(request).get, exercise_id)


@router.put("/custom-exercises/{exercise_id}", responses=_ERRORS)
def update_custom(exercise_id: str, body: DraftFields, request: Request) -> CustomExercise:
    return _call(_service(request).update, exercise_id, body)


@router.post("/custom-exercises/{exercise_id}/approve", responses=_ERRORS)
def approve_custom(exercise_id: str, body: ApproveRequest, request: Request) -> CustomExercise:
    return _call(_service(request).approve, exercise_id, body)


@router.post("/custom-exercises/{exercise_id}/archive", responses=_ERRORS)
def archive_custom(exercise_id: str, request: Request) -> CustomExercise:
    return _call(_service(request).archive, exercise_id)


@router.delete("/custom-exercises/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
def delete_custom(exercise_id: str, request: Request) -> Response:
    _call(_service(request).delete, exercise_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
