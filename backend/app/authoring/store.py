"""Persistence for custom exercises (JSON files; replaced by SQLite in Phase 7).

One file per exercise. Angle data from a demonstration is written to a
separate file *only* when the therapist consented to storing it. No video is
ever stored.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from app.authoring.series import AngleSeries
from app.schemas.authoring import CustomExercise


class CustomExerciseStore(Protocol):
    def list(self) -> list[CustomExercise]: ...
    def get(self, exercise_id: str) -> CustomExercise | None: ...
    def save(self, record: CustomExercise) -> None: ...
    def delete(self, exercise_id: str) -> None: ...
    def save_angle_data(self, exercise_id: str, demo_id: str, series: AngleSeries) -> None: ...


class JsonFileStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, exercise_id: str) -> Path:
        return self._dir / f"{exercise_id}.json"

    def list(self) -> list[CustomExercise]:
        with self._lock:
            records = [
                CustomExercise.model_validate_json(p.read_text("utf-8"))
                for p in sorted(self._dir.glob("custom_*.json"))
                if not p.name.endswith(".angles.json")
            ]
        return sorted(records, key=lambda r: r.updated_at, reverse=True)

    def get(self, exercise_id: str) -> CustomExercise | None:
        path = self._path(exercise_id)
        with self._lock:
            if not path.is_file():
                return None
            return CustomExercise.model_validate_json(path.read_text("utf-8"))

    def save(self, record: CustomExercise) -> None:
        with self._lock:
            _atomic_write(self._path(record.id), record.model_dump_json(indent=2))

    def delete(self, exercise_id: str) -> None:
        with self._lock:
            for p in [self._path(exercise_id), *self._dir.glob(f"{exercise_id}.*.angles.json")]:
                p.unlink(missing_ok=True)

    def save_angle_data(self, exercise_id: str, demo_id: str, series: AngleSeries) -> None:
        with self._lock:
            _atomic_write(self._dir / f"{exercise_id}.{demo_id}.angles.json", json.dumps(series.to_json()))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
