from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app.config import Settings, load_settings
from tests.fakes import FakeCamera


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with a placeholder model file (fakes never read it)."""
    model = tmp_path / "fake.task"
    model.write_bytes(b"")
    return load_settings(
        {"PTM_MODEL_PATH": str(model), "PTM_MAX_INFERENCE_FPS": "0", "PTM_DATA_DIR": str(tmp_path / "data")}
    )


@pytest.fixture(autouse=True)
def _reset_fake_camera() -> Iterator[None]:
    FakeCamera.instances.clear()
    yield
    FakeCamera.instances.clear()


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")
