"""Integration tests for the REST + WebSocket API (fake camera and detector)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import partial

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.messages import PROTOCOL_VERSION, decode_frame_packet
from tests.fakes import FakeCamera, FakeDetector


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, FakeCamera, FakeDetector)) as c:
        yield c


def test_health_and_initial_status(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}
    status = client.get("/api/status").json()
    assert status["state"] == "stopped"
    assert status["protocol_version"] == PROTOCOL_VERSION
    assert status["error"] is None


def test_topology(client: TestClient) -> None:
    body = client.get("/api/pose/topology").json()
    assert len(body["landmark_names"]) == 33
    assert body["landmark_names"][11] == "left_shoulder"
    assert [11, 13] in body["connections"]


def test_start_stream_stop_over_websocket(client: TestClient) -> None:
    with client.websocket_connect("/ws/stream") as ws:
        assert json.loads(ws.receive_text())["state"] == "stopped"

        assert client.post("/api/camera/start").json()["state"] == "running"

        states: list[str] = []
        frames = []
        while len(frames) < 3:
            msg = ws.receive()
            if msg.get("text"):
                states.append(json.loads(msg["text"]).get("state", "<session>"))
            elif msg.get("bytes"):
                frames.append(decode_frame_packet(msg["bytes"]))
        assert "running" in states
        assert all(m.width == 640 and m.height == 480 for m, _ in frames)

        assert client.post("/api/camera/stop").json()["state"] == "stopped"
        # Status updates arrive; stray in-flight frames may precede them.
        seen: list[str] = []
        while "stopped" not in seen:
            msg = ws.receive()
            if msg.get("text"):
                seen.append(json.loads(msg["text"]).get("state", "<session>"))
    assert FakeCamera.instances[0].close_calls == 1


def test_start_failure_returns_503_with_reason(settings: Settings) -> None:
    app = create_app(settings, partial(FakeCamera, fail_open=True), FakeDetector)
    with TestClient(app) as c:
        r = c.post("/api/camera/start")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "camera_open_failed"
        assert c.get("/api/status").json()["state"] == "error"


def test_shutdown_releases_camera(settings: Settings) -> None:
    with TestClient(create_app(settings, FakeCamera, FakeDetector)) as c:
        c.post("/api/camera/start")
    # Leaving the context runs the lifespan shutdown hook.
    assert FakeCamera.instances[0].close_calls == 1
    assert not FakeCamera.instances[0].is_open


def test_websocket_disconnect_unsubscribes(client: TestClient) -> None:
    hub = client.app.state.hub  # type: ignore[attr-defined]
    with client.websocket_connect("/ws/stream") as ws:
        ws.receive_text()
        assert hub.subscriber_count == 1
    from tests.conftest import wait_until

    wait_until(lambda: hub.subscriber_count == 0)


def test_angle_definitions(client: TestClient) -> None:
    defs = {d["id"]: d for d in client.get("/api/angles/definitions").json()}
    assert len(defs) == 8
    assert defs["left_elbow_flexion"]["landmarks"] == [11, 13, 15]
    assert defs["right_knee_flexion"]["convention"] == "flexion"
    assert client.get("/api/status").json()["angle_space"] == "image"


def test_exercise_library_endpoints(client: TestClient) -> None:
    listing = client.get("/api/exercises").json()
    assert {e["id"] for e in listing} == {"jumping_jack_arms", "standing_arm_raise", "biceps_curl", "sit_to_stand", "mini_squat", "seated_knee_extension", "shoulder_flexion", "standing_march", "wall_pushup"}
    assert all(e["dosage"]["reps_per_set"] for e in listing)
    assert all(e["is_demo"] for e in listing)
    full = client.get("/api/exercises/biceps_curl").json()
    assert full["signal"]["joint"] == "elbow_flexion"
    assert client.get("/api/exercises/nope").status_code == 404


def test_exercise_selection_validation(client: TestClient) -> None:
    assert client.get("/api/exercise/active").json() is None
    assert client.put("/api/exercise/active", json={"exercise_id": "nope"}).status_code == 404
    r = client.put("/api/exercise/active", json={"exercise_id": "sit_to_stand", "side": "left"})
    assert r.status_code == 422 and "both sides" in r.json()["detail"]
    r = client.put("/api/exercise/active", json={"exercise_id": "biceps_curl", "overrides": {"target_deg": 38}})
    assert r.status_code == 422 and "hysteresis" in r.json()["detail"]
    r = client.put("/api/exercise/active", json={"exercise_id": "biceps_curl", "overrides": {"target_deg": 999}})
    assert r.status_code == 422
    assert client.post("/api/exercise/active/reset").status_code == 409

    r = client.put(
        "/api/exercise/active",
        json={"exercise_id": "biceps_curl", "side": "left", "overrides": {"target_deg": 100, "min_hold_ms": 250}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["side"] == "left"
    assert body["effective_rep_counting"]["target_deg"] == 100
    assert body["effective_rep_counting"]["min_hold_ms"] == 250
    assert client.get("/api/exercise/active").json()["exercise"]["id"] == "biceps_curl"
    assert client.post("/api/exercise/active/reset").status_code == 200
    assert client.delete("/api/exercise/active").status_code == 204
    assert client.get("/api/exercise/active").json() is None


def test_end_to_end_curls_are_counted_over_websocket(settings: Settings) -> None:
    """Real pipeline, analyzer and counter; synthetic camera and a scripted
    person curling the right arm."""
    from tests.fakes import CurlingDetector

    app = create_app(settings, partial(FakeCamera, fps=60), CurlingDetector)
    with TestClient(app) as c, c.websocket_connect("/ws/stream") as ws:
        assert c.put("/api/exercise/active", json={"exercise_id": "biceps_curl"}).status_code == 200
        c.post("/api/camera/start")
        reps = 0
        phases: set[str] = set()
        frames = 0
        while reps < 2:
            frames += 1
            assert frames < 2000, "reps were not counted"
            msg = ws.receive()
            if not msg.get("bytes"):
                continue
            m, _ = decode_frame_packet(msg["bytes"])
            assert m.exercise is not None and m.exercise.exercise_id == "biceps_curl"
            assert m.angle_space == "image"
            phases.add(m.exercise.phase)
            reps = m.exercise.reps
        assert {"ready", "moving", "at_target", "returning"} <= phases
        assert m.exercise.last_event is not None and m.exercise.last_event.kind == "rep_completed"
        assert m.exercise.last_event.peak_deg is not None and m.exercise.last_event.peak_deg > 105
        c.post("/api/camera/stop")


def test_selection_id_changes_on_every_selection_and_reset(client: TestClient) -> None:
    a = client.put("/api/exercise/active", json={"exercise_id": "biceps_curl"}).json()["selection_id"]
    b = client.post("/api/exercise/active/reset").json()["selection_id"]
    c = client.put("/api/exercise/active", json={"exercise_id": "biceps_curl"}).json()["selection_id"]
    assert len({a, b, c}) == 3
    assert client.get("/api/exercise/active").json()["selection_id"] == c


def test_end_to_end_feedback_over_websocket(settings: Settings) -> None:
    """Counted curls produce a positive feedback message in the stream, and the
    form rule is evaluated (synthetic upper arm stays still → ok)."""
    from tests.fakes import CurlingDetector

    app = create_app(settings, partial(FakeCamera, fps=60), CurlingDetector)
    with TestClient(app) as c, c.websocket_connect("/ws/stream") as ws:
        c.put("/api/exercise/active", json={"exercise_id": "biceps_curl"})
        c.post("/api/camera/start")
        seen_keys: set[str] = set()
        rule_states: set[str] = set()
        for _ in range(3000):
            msg = ws.receive()
            if not msg.get("bytes"):
                continue
            m, _ = decode_frame_packet(msg["bytes"])
            assert m.exercise is not None
            fb = m.exercise.feedback
            rule_states.update(r.state for r in fb.rules)
            if fb.message:
                seen_keys.add(fb.message.key)
            if "event:rep_completed" in seen_keys and "ok" in rule_states:
                break
        assert "event:rep_completed" in seen_keys
        assert "ok" in rule_states and "violated" not in rule_states
        c.post("/api/camera/stop")


def test_session_endpoints_and_conflicts(client: TestClient) -> None:
    assert client.get("/api/session").json() is None
    assert client.post("/api/session/pause").status_code == 409
    assert client.post("/api/session", json={"exercise_id": "nope"}).status_code == 404
    r = client.post("/api/session", json={"exercise_id": "sit_to_stand", "side": "left"})
    assert r.status_code == 422 and "both sides" in r.json()["detail"]
    r = client.post("/api/session", json={"exercise_id": "biceps_curl", "overrides": {"target_deg": 38}})
    assert r.status_code == 422

    r = client.post("/api/session", json={"exercise_id": "biceps_curl", "sets": 2, "reps_per_set": 3, "rest_s": 5, "practice": False})
    assert r.status_code == 200 and r.json()["state"] == "active"
    assert client.post("/api/session", json={"exercise_id": "biceps_curl"}).status_code == 409
    # Manual exercise selection must not hijack the session's counter.
    assert client.put("/api/exercise/active", json={"exercise_id": "sit_to_stand"}).status_code == 409
    assert client.delete("/api/exercise/active").status_code == 409
    assert client.get("/api/exercise/active").json()["selection_id"] == r.json()["selection_id"]

    assert client.post("/api/session/pause").json()["state"] == "paused"
    assert client.post("/api/session/advance").status_code == 409
    assert client.post("/api/session/resume").json()["state"] == "active"
    assert client.post("/api/session/advance").json()["state"] == "resting"
    assert client.delete("/api/session").status_code == 409
    ended = client.post("/api/session/end").json()
    assert ended["state"] == "ended" and ended["summary"] is not None
    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/session").json() is None


def test_full_session_over_websocket(settings: Settings) -> None:
    """Real pipeline: two sets of two curls with no rest, ending in a summary."""
    from tests.fakes import CurlingDetector

    app = create_app(settings, partial(FakeCamera, fps=60), CurlingDetector)
    with TestClient(app) as c, c.websocket_connect("/ws/stream") as ws:
        c.post("/api/camera/start")
        r = c.post("/api/session", json={"exercise_id": "biceps_curl", "sets": 2, "reps_per_set": 2, "rest_s": 0, "practice": False})
        assert r.status_code == 200
        states: list[str] = []
        final = None
        for _ in range(5000):
            msg = ws.receive()
            if not msg.get("text"):
                continue
            data = json.loads(msg["text"])
            if data.get("type") == "session" and data["session"]:
                states.append(data["session"]["state"])
                if data["session"]["state"] == "completed":
                    final = data["session"]
                    break
        assert final is not None, f"session did not complete; states seen: {states[-5:]}"
        assert final["summary"]["total_reps"] == 4
        assert final["summary"]["sets_completed"] == 2
        assert final["summary"]["peak_deg"]["max_deg"] > 110
        # Counting stops once the session completes.
        assert c.get("/api/exercise/active").json() is None
        c.post("/api/camera/stop")
