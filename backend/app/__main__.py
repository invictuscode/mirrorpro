"""Entry point: ``python -m app`` (run from ``backend/``)."""

from __future__ import annotations

import logging
import sys

import uvicorn

from app.config import ConfigError, load_settings
from app.exercises.library import ExerciseLibraryError
from app.main import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        settings = load_settings()
        app = create_app(settings)
    except (ConfigError, ExerciseLibraryError) as exc:
        sys.exit(str(exc))
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        # Bounded so open WebSockets can't hold shutdown (and the camera) hostage.
        timeout_graceful_shutdown=3,
        log_level="info",
    )


if __name__ == "__main__":
    main()
