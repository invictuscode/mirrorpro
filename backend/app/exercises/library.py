"""Loads exercise definitions from JSON files.

Every file must validate; a bad file is a startup error naming the file,
never silently skipped. (Phase 7 moves definitions into SQLite.)
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from app.exercises.schema import ExerciseDefinition, ReviewStatus

PRESETS_DIR = Path(__file__).resolve().parent / "presets"


class ExerciseLibraryError(ValueError):
    pass


class ExerciseLibrary:
    """Exercises available to patients: shipped presets plus approved custom
    exercises (added at runtime). Drafts are never accepted."""

    def __init__(self, definitions: list[ExerciseDefinition]) -> None:
        self._lock = threading.Lock()
        by_id: dict[str, ExerciseDefinition] = {}
        for d in definitions:
            _check_publishable(d)
            if d.id in by_id:
                raise ExerciseLibraryError(f"duplicate exercise id {d.id!r}")
            by_id[d.id] = d
        self._by_id = by_id

    @classmethod
    def from_directory(cls, directory: Path = PRESETS_DIR) -> ExerciseLibrary:
        if not directory.is_dir():
            raise ExerciseLibraryError(f"exercise directory not found: {directory}")
        definitions = []
        for path in sorted(directory.glob("*.json")):
            try:
                definitions.append(ExerciseDefinition.model_validate(json.loads(path.read_text("utf-8"))))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ExerciseLibraryError(f"invalid exercise file {path.name}: {exc}") from exc
        return cls(definitions)

    def get(self, exercise_id: str) -> ExerciseDefinition | None:
        with self._lock:
            return self._by_id.get(exercise_id)

    def upsert(self, definition: ExerciseDefinition) -> None:
        """Add or replace (e.g. a newly approved custom exercise version)."""
        _check_publishable(definition)
        with self._lock:
            self._by_id[definition.id] = definition

    def remove(self, exercise_id: str) -> None:
        with self._lock:
            self._by_id.pop(exercise_id, None)

    def __iter__(self) -> Iterator[ExerciseDefinition]:
        with self._lock:
            items = sorted(self._by_id.values(), key=lambda d: d.name)
        return iter(items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)


def _check_publishable(d: ExerciseDefinition) -> None:
    if d.clinical_review.status is ReviewStatus.DRAFT:
        raise ExerciseLibraryError(f"exercise {d.id!r} is a draft and cannot be offered to patients")
