from __future__ import annotations

import threading
from functools import partial

from app.config import Settings
from app.pipeline.tracking import TrackingPipeline
from app.pose.detector import ModelNotFoundError
from app.schemas.messages import ErrorCode, PipelineState, StatusMessage, decode_frame_packet
from tests.conftest import wait_until
from tests.fakes import FakeCamera, FakeDetector


class Recorder:
    def __init__(self) -> None:
        self.statuses: list[StatusMessage] = []
        self.packets: list[bytes] = []
        self._lock = threading.Lock()

    def status(self, s: StatusMessage) -> None:
        with self._lock:
            self.statuses.append(s)

    def frame(self, p: bytes) -> None:
        with self._lock:
            self.packets.append(p)

    @property
    def states(self) -> list[PipelineState]:
        return [s.state for s in self.statuses]


def make(settings: Settings, camera=FakeCamera, detector=FakeDetector) -> tuple[TrackingPipeline, Recorder]:
    rec = Recorder()
    return TrackingPipeline(settings, rec.status, rec.frame, camera, detector), rec


def test_start_streams_packets_then_stop_releases_camera(settings: Settings) -> None:
    detectors: list[FakeDetector] = []

    def detector_factory(s: Settings) -> FakeDetector:
        detectors.append(FakeDetector(s))
        return detectors[-1]

    pipeline, rec = make(settings, detector=detector_factory)
    assert pipeline.start().state is PipelineState.RUNNING
    wait_until(lambda: len(rec.packets) >= 6)
    assert pipeline.stop().state is PipelineState.STOPPED

    camera = FakeCamera.instances[0]
    assert not camera.is_open and camera.close_calls == 1
    assert detectors[0].closed
    assert rec.states == [PipelineState.STARTING, PipelineState.RUNNING, PipelineState.STOPPING, PipelineState.STOPPED]

    messages = [decode_frame_packet(p) for p in rec.packets]
    detected = [m for m, _ in messages if m.person_detected]
    missing = [m for m, _ in messages if not m.person_detected]
    assert detected and missing, "fake detector alternates person / no person"
    assert all(m.landmarks is not None and len(m.landmarks) == 33 for m in detected)
    assert all(m.landmarks is None for m in missing)
    assert all(jpeg.startswith(b"\xff\xd8") for _, jpeg in messages)  # real JPEG preview
    ids = [m.frame_id for m, _ in messages]
    assert ids == sorted(ids)
    # MediaPipe VIDEO mode needs strictly increasing timestamps.
    ts = detectors[0].timestamps
    assert all(b > a for a, b in zip(ts, ts[1:]))


def test_frames_are_downscaled_to_inference_width(settings: Settings) -> None:
    s = settings.model_copy(update={"inference_width": 320})
    detectors: list[FakeDetector] = []
    pipeline, rec = make(s, detector=lambda st: detectors.append(FakeDetector(st)) or detectors[-1])
    pipeline.start()
    wait_until(lambda: len(rec.packets) >= 2)
    pipeline.stop()
    assert detectors[0].shapes[0] == (240, 320, 3)  # 640x480 → 320x240, RGB


def test_preview_disabled_sends_landmarks_only(settings: Settings) -> None:
    pipeline, rec = make(settings.model_copy(update={"preview_enabled": False}))
    pipeline.start()
    wait_until(lambda: len(rec.packets) >= 2)
    pipeline.stop()
    msg, jpeg = decode_frame_packet(rec.packets[0])
    assert not msg.has_preview and jpeg == b""


def test_restart_after_stop(settings: Settings) -> None:
    pipeline, rec = make(settings)
    pipeline.start()
    wait_until(lambda: len(rec.packets) >= 2)
    pipeline.stop()
    n = len(rec.packets)
    assert pipeline.start().state is PipelineState.RUNNING
    wait_until(lambda: len(rec.packets) >= n + 2)
    pipeline.stop()
    assert len(FakeCamera.instances) == 2
    assert all(c.close_calls == 1 for c in FakeCamera.instances)


def test_start_and_stop_are_idempotent(settings: Settings) -> None:
    pipeline, _ = make(settings)
    assert pipeline.stop().state is PipelineState.STOPPED
    pipeline.start()
    assert pipeline.start().state is PipelineState.RUNNING
    assert len(FakeCamera.instances) == 1
    pipeline.stop()
    assert pipeline.stop().state is PipelineState.STOPPED


def test_camera_open_failure_reports_error_and_closes_detector(settings: Settings) -> None:
    detectors: list[FakeDetector] = []
    pipeline, rec = make(
        settings,
        camera=partial(FakeCamera, fail_open=True),
        detector=lambda s: detectors.append(FakeDetector(s)) or detectors[-1],
    )
    status = pipeline.start()
    assert status.state is PipelineState.ERROR
    assert status.error is not None and status.error.code is ErrorCode.CAMERA_OPEN_FAILED
    assert detectors[0].closed
    assert not rec.packets


def test_missing_model_reports_model_missing(settings: Settings) -> None:
    def no_model(_: Settings) -> FakeDetector:
        raise ModelNotFoundError("no model here")

    pipeline, _ = make(settings, detector=no_model)
    status = pipeline.start()
    assert status.error is not None and status.error.code is ErrorCode.MODEL_MISSING
    assert not FakeCamera.instances, "camera must not be opened without a model"


def test_camera_disconnect_mid_stream_becomes_error_and_releases(settings: Settings) -> None:
    s = settings.model_copy(update={"max_consecutive_read_failures": 5})
    pipeline, rec = make(s, camera=partial(FakeCamera, fail_after=10))
    pipeline.start()
    wait_until(lambda: pipeline.state is PipelineState.ERROR)
    status = pipeline.status()
    assert status.error is not None and status.error.code is ErrorCode.CAMERA_READ_FAILED
    wait_until(lambda: FakeCamera.instances[0].close_calls == 1)
    # Can recover by starting again (here: with a camera that keeps failing).
    assert pipeline.stop().state is PipelineState.STOPPED


def test_inference_exception_becomes_error(settings: Settings) -> None:
    pipeline, _ = make(settings, detector=partial(FakeDetector, raise_on_call=3))
    pipeline.start()
    wait_until(lambda: pipeline.state is PipelineState.ERROR)
    status = pipeline.status()
    assert status.error is not None and status.error.code is ErrorCode.INFERENCE_FAILED
    assert "fake inference failure" in status.error.message
    wait_until(lambda: FakeCamera.instances[0].close_calls == 1)


def test_rate_limit_caps_inference(settings: Settings) -> None:
    import time

    detectors: list[FakeDetector] = []
    s = settings.model_copy(update={"max_inference_fps": 10.0})
    pipeline, _ = make(s, detector=lambda st: detectors.append(FakeDetector(st)) or detectors[-1])
    pipeline.start()
    time.sleep(1.0)
    pipeline.stop()
    # Camera runs at ~100 fps; inference must stay near 10/s.
    assert 5 <= detectors[0].calls <= 12


def test_frames_carry_joint_angles(settings: Settings) -> None:
    pipeline, rec = make(settings)
    pipeline.start()
    wait_until(lambda: len(rec.packets) >= 6)
    pipeline.stop()
    messages = [decode_frame_packet(p)[0] for p in rec.packets]
    for m in messages:
        assert len(m.angles) == 8
        by_id = {a.id: a for a in m.angles}
        if m.person_detected:
            # Fake landmarks are collinear in index order: arm and leg straight.
            assert by_id["left_elbow_flexion"].status == "ok"
            assert by_id["left_elbow_flexion"].value_deg == 0.0
        else:
            assert all(a.status == "no_person" and a.value_deg is None for a in m.angles)
