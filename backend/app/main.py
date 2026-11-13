from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.authoring import router as authoring_router
from app.api.exercises import router as exercises_router
from app.api.sessions import router as sessions_router
from app.api.routes import api, ws
from app.api.stream_hub import StreamHub
from app.authoring.recorder import DemonstrationCache, LiveRecorder
from app.authoring.service import CustomExerciseService
from app.authoring.store import JsonFileStore
from app.camera import OpenCVCamera
from app.config import Settings, load_settings
from app.exercises.library import PRESETS_DIR, ExerciseLibrary
from app.pipeline.tracking import DetectorFactory, SourceFactory, TrackingPipeline
from app.pose.detector import MediaPipePoseDetector
from app.sessions.manager import SessionManager

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    source_factory: SourceFactory = OpenCVCamera,
    detector_factory: DetectorFactory = MediaPipePoseDetector,
    exercises: ExerciseLibrary | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    # Invalid exercise files fail startup loudly (ExerciseLibraryError).
    exercises = exercises or ExerciseLibrary.from_directory(settings.exercise_dir or PRESETS_DIR)
    hub = StreamHub()
    pipeline = TrackingPipeline(
        settings,
        on_status=hub.publish_status,
        on_frame=hub.publish_frame,
        source_factory=source_factory,
        detector_factory=detector_factory,
    )

    sessions = SessionManager(
        exercises, pipeline.set_exercise, publish=lambda payload: hub.publish_text("session", payload)
    )
    pipeline.set_exercise_listener(sessions.on_frame)

    demonstrations = DemonstrationCache()
    recorder = LiveRecorder(demonstrations)
    pipeline.set_angle_listener(recorder.on_frame)
    custom_exercises = CustomExerciseService(
        JsonFileStore(settings.data_dir / "custom_exercises"), exercises, demonstrations
    )
    n_custom = custom_exercises.load_approved_into_library()
    if n_custom:
        log.info("Loaded %d approved custom exercise(s)", n_custom)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.bind_loop(asyncio.get_running_loop())
        if not settings.model_path.is_file():
            log.warning("Pose model missing at %s — run scripts/download_model.py", settings.model_path)
        try:
            yield
        finally:
            # Always release the camera on shutdown (Ctrl+C, reload, SIGTERM).
            sessions.shutdown()
            await asyncio.to_thread(pipeline.stop)

    app = FastAPI(title="PT Smart Mirror backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.hub = hub
    app.state.pipeline = pipeline
    app.state.exercises = exercises
    app.state.sessions = sessions
    app.state.detector_factory = detector_factory
    app.state.demonstrations = demonstrations
    app.state.recorder = recorder
    app.state.custom_exercises = custom_exercises
    # Extra text messages sent to every new WebSocket client.
    app.state.initial_messages = lambda: [sessions.message_json()]
    app.include_router(api)
    app.include_router(exercises_router)
    app.include_router(sessions_router)
    app.include_router(authoring_router)
    app.include_router(ws)
    return app
