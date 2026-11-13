"""Authoring API end to end: record → analyse → draft → approve → session."""

from __future__ import annotations

import tempfile
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import CurlingDetector, FakeCamera
from tests.test_authoring_workflow import write_video


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, partial(FakeCamera, fps=60), CurlingDetector)
    with TestClient(app) as c:
        yield c


def draft_from_analysis(analysis: dict, name: str = "Recorded curl") -> dict:
    chosen = analysis["chosen"]
    return {
        "name": name,
        "description": "Demonstrated by the therapist.",
        "instructions": ["Stand side-on to the screen.", "Bend and straighten the elbow."],
        "camera_view": "side",
        "camera_guidance": "Stand side-on so the arm stays in view.",
        "signal_joint": chosen["joint"],
        "side_mode": chosen["side_mode"],
        "default_side": chosen["side"],
        "rep_counting": analysis["suggested_rep_counting"],
        "form_rules": [s["rule"] for s in analysis["suggested_rules"] if s["include"]],
    }


def test_live_recording_to_approved_exercise_to_session(client: TestClient) -> None:
    assert client.post("/api/demonstrations/live/start").status_code == 409  # camera not running
    client.post("/api/camera/start")
    assert client.post("/api/demonstrations/live/start").json()["recording"] is True
    assert client.post("/api/demonstrations/live/start").status_code == 409  # already recording
    deadline = time.monotonic() + 10
    while client.get("/api/demonstrations/live").json()["elapsed_ms"] < 4000:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    demo = client.post("/api/demonstrations/live/stop").json()
    assert demo["source"] == "live" and demo["frames"] > 50 and demo["person_fraction"] == 1.0

    # The scripted person curls continuously, so the recording starts at a
    # random point and the direction may be ambiguous; the therapist settles it.
    analysis = client.post(f"/api/demonstrations/{demo['demo_id']}/analyze", json={}).json()
    assert analysis["chosen"]["joint"] == "elbow_flexion" and analysis["chosen"]["side"] == "right"
    analysis = client.post(
        f"/api/demonstrations/{demo['demo_id']}/analyze", json={"start_position": "low"}
    ).json()
    assert analysis["increasing"] is True and len(analysis["reps"]) >= 2
    assert analysis["suggested_rep_counting"] is not None
    assert any(w["code"] == "single_demonstration" for w in analysis["warnings"])

    r = client.post("/api/custom-exercises", json={"fields": draft_from_analysis(analysis), "demo_id": demo["demo_id"]})
    assert r.status_code == 200, r.text
    draft = r.json()
    ids = {e["id"] for e in client.get("/api/exercises").json()}
    assert draft["id"] not in ids, "draft is not offered to patients"
    assert client.post("/api/session", json={"exercise_id": draft["id"]}).status_code == 404

    r = client.post(f"/api/custom-exercises/{draft['id']}/approve", json={"reviewer": "Dr Lee", "attestation": False})
    assert r.status_code == 409
    r = client.post(f"/api/custom-exercises/{draft['id']}/approve", json={"reviewer": "Dr Lee", "attestation": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    listing = {e["id"]: e for e in client.get("/api/exercises").json()}
    assert draft["id"] in listing and listing[draft["id"]]["is_demo"] is False

    s = client.post("/api/session", json={"exercise_id": draft["id"], "sets": 1, "reps_per_set": 2, "rest_s": 0, "practice": False})
    assert s.status_code == 200 and s.json()["state"] == "active"
    # Recording is blocked during a session.
    assert client.post("/api/demonstrations/live/start").status_code == 409
    client.post("/api/session/end")
    client.post("/api/camera/stop")


def test_upload_is_processed_and_the_file_deleted(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []
    real_mkstemp = tempfile.mkstemp

    def spy(*a, **kw):  # type: ignore[no-untyped-def]
        fd, name = real_mkstemp(*a, **kw)
        created.append(name)
        return fd, name

    monkeypatch.setattr("app.api.authoring.tempfile.mkstemp", spy)
    data = write_video(tmp_path / "d.mp4").read_bytes()
    r = client.post("/api/demonstrations/upload", content=data, headers={"Content-Type": "video/mp4"})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "upload"
    assert created and not any(Path(n).exists() for n in created), "uploaded video must be deleted"
    analysis = client.post(f"/api/demonstrations/{r.json()['demo_id']}/analyze", json={"joint": "elbow_flexion"}).json()
    assert analysis["chosen"]["joint"] == "elbow_flexion"

    bad = client.post("/api/demonstrations/upload", content=b"nope", headers={"Content-Type": "video/mp4"})
    assert bad.status_code == 422 and "could not be opened" in bad.json()["detail"]
    assert not any(Path(n).exists() for n in created)
    assert client.post("/api/demonstrations/upload", content=b"").status_code == 422


def test_custom_exercise_errors(client: TestClient) -> None:
    assert client.post("/api/demonstrations/demo_nope/analyze", json={}).status_code == 404
    assert client.get("/api/custom-exercises/custom_nope").status_code == 404
    fields = {
        "name": "X",
        "description": "Y",
        "instructions": ["This is safe."],
        "camera_view": "side",
        "camera_guidance": "Z",
        "signal_joint": "elbow_flexion",
        "side_mode": "single",
        "default_side": "right",
        "rep_counting": {"start_deg": 20, "target_deg": 90},
    }
    r = client.post("/api/custom-exercises", json={"fields": fields})
    assert r.status_code == 422 and "safe" in r.json()["detail"]
