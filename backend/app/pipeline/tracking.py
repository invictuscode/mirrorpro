"""Camera → pose-model → packet pipeline.

Two worker threads, decoupled by a single-slot "latest frame" buffer:

* **capture** reads the camera as fast as it delivers frames and overwrites the
  slot, so the driver queue never backs up and latency stays bounded.
* **inference** takes the newest frame, runs the pose model, encodes the
  optional preview JPEG and hands a packet to ``on_frame``.

If inference is slower than the camera, intermediate frames are skipped (and
counted) instead of queueing. Delivery to clients is handled elsewhere
(:mod:`app.api.stream_hub`) with the same latest-wins policy, so a slow browser
can never stall capture or inference.

Raw frames live only in memory for the duration of one iteration; nothing is
written to disk.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import cv2
import numpy as np

from app.biomechanics import AngleAnalyzer, AngleResult, AngleSpace
from app.camera import CameraError, FrameSource, OpenCVCamera
from app.config import Settings
from app.exercises.tracker import ExerciseFrame, ExerciseTracker
from app.feedback.engine import FeedbackState
from app.pipeline.metrics import Ema, RateMeter
from app.pose.detector import MediaPipePoseDetector, ModelNotFoundError, PoseDetector
from app.schemas.messages import (
    AngleMeasurement,
    ErrorCode,
    ErrorInfo,
    ExerciseStateMessage,
    FeedbackMessageModel,
    FeedbackStateMessage,
    FrameMessage,
    FrameMetrics,
    PipelineState,
    RepEventMessage,
    RuleStatusMessage,
    StatusMessage,
    encode_frame_packet,
)

log = logging.getLogger(__name__)

SourceFactory = Callable[[Settings], FrameSource]
AngleListener = Callable[[int, Sequence[AngleResult], AngleSpace], None]
DetectorFactory = Callable[[Settings], PoseDetector]
_JOIN_TIMEOUT_S = 3.0


@dataclass(slots=True)
class _Frame:
    frame_id: int
    captured_ms: int
    image: np.ndarray


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _round(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def _angle_message(a: AngleResult) -> AngleMeasurement:
    return AngleMeasurement(
        id=a.id,
        status=a.status.value,
        value_deg=_round(a.value_deg, 1),
        raw_deg=_round(a.raw_deg, 1),
        confidence=_round(a.confidence, 2),
    )


def _exercise_message(f: ExerciseFrame) -> ExerciseStateMessage:
    c = f.counter
    e = c.last_event
    return ExerciseStateMessage(
        exercise_id=f.exercise_id,
        selection_id=f.selection_id,
        side=f.side.value if f.side else None,
        sides_used=[side.value for side in f.sides_used],
        phase=c.phase.value,
        reps=c.reps,
        signal_deg=_round(c.signal_deg, 1),
        progress=_round(c.progress, 3),
        hold_ms=c.hold_ms,
        last_event=RepEventMessage(
            seq=e.seq,
            kind=e.kind.value,
            timestamp_ms=e.timestamp_ms,
            peak_deg=e.peak_deg,
            duration_ms=e.duration_ms,
            hold_ms=e.hold_ms,
            detail=e.detail,
        )
        if e
        else None,
        feedback=_feedback_message(f.feedback),
    )


def _feedback_message(fb: FeedbackState) -> FeedbackStateMessage:
    m = fb.message
    return FeedbackStateMessage(
        message=FeedbackMessageModel(
            seq=m.seq, key=m.key, text=m.text, category=m.category.value, issued_ms=m.issued_ms
        )
        if m
        else None,
        rules=[
            RuleStatusMessage(
                id=r.id,
                state=r.state.value,
                value_deg=_round(r.value_deg, 1),
                sustained=r.sustained,
                blocks_rep=r.blocks_rep,
                reason=r.reason.value if r.reason else None,
            )
            for r in fb.rules
        ],
        tracking_ok=fb.tracking_ok,
    )


def resize_to_width(image: np.ndarray, width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= width:
        return image
    return cv2.resize(image, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)


class TrackingPipeline:
    def __init__(
        self,
        settings: Settings,
        on_status: Callable[[StatusMessage], None],
        on_frame: Callable[[bytes], None],
        source_factory: SourceFactory = OpenCVCamera,
        detector_factory: DetectorFactory = MediaPipePoseDetector,
    ) -> None:
        self._settings = settings
        self._on_status = on_status
        self._on_frame = on_frame
        self._source_factory = source_factory
        self._detector_factory = detector_factory

        # Guards lifecycle transitions and the fields below it.
        self._lock = threading.RLock()
        self._state = PipelineState.STOPPED
        self._error: ErrorInfo | None = None
        self._source: FrameSource | None = None
        self._detector: PoseDetector | None = None
        self._threads: list[threading.Thread] = []
        self._stop_evt = threading.Event()
        # Incremented per start(); lets a late failure from an old run be ignored.
        self._run_id = 0

        # Latest-frame slot shared by the two workers.
        self._cond = threading.Condition()
        self._latest: _Frame | None = None
        self._latest_consumed = True

        self._capture_rate = RateMeter()
        self._inference_rate = RateMeter()
        self._inference_ms = Ema()
        self._dropped = 0

        # Replaced wholesale (atomic reference swap) by the API thread; only the
        # inference thread calls its update().
        self._exercise: ExerciseTracker | None = None
        # Called (inference thread) with each exercise frame, e.g. by sessions.
        self._exercise_listener: Callable[[ExerciseFrame], None] | None = None
        # Called (inference thread) with every frame's angles, e.g. by the
        # demonstration recorder.
        self._angle_listener: AngleListener | None = None

    # ---------------------------------------------------------------- exercise
    @property
    def exercise(self) -> ExerciseTracker | None:
        return self._exercise

    def set_exercise(self, tracker: ExerciseTracker | None) -> None:
        """Select (or clear with None) the exercise to track. Takes effect on the
        next processed frame. Pass a new tracker to reset the count."""
        self._exercise = tracker

    def set_exercise_listener(self, listener: Callable[[ExerciseFrame], None] | None) -> None:
        self._exercise_listener = listener

    def set_angle_listener(self, listener: AngleListener | None) -> None:
        self._angle_listener = listener

    # ------------------------------------------------------------------ status
    @property
    def state(self) -> PipelineState:
        return self._state

    def status(self) -> StatusMessage:
        with self._lock:
            return StatusMessage(
                state=self._state,
                error=self._error,
                camera=self._source.description if self._source else None,
                model=self._settings.model_path.name,
                profile=self._settings.profile,
                preview_enabled=self._settings.preview_enabled,
                angle_space=self._settings.angle_space.value,
            )

    def _set_state(self, state: PipelineState, error: ErrorInfo | None = None) -> None:
        with self._lock:
            self._state = state
            self._error = error
            status = self.status()
        if error:
            log.error("Pipeline %s: [%s] %s", state.value, error.code.value, error.message)
        else:
            log.info("Pipeline %s", state.value)
        self._on_status(status)

    # --------------------------------------------------------------- lifecycle
    def start(self) -> StatusMessage:
        """Open camera and model and start workers. Blocks while the camera opens
        (can take ~1 s on macOS), so call it from a worker thread, not an event
        loop. Failures are reported through the returned status, not raised."""
        with self._lock:
            if self._state in (PipelineState.RUNNING, PipelineState.STARTING):
                return self.status()
            self._set_state(PipelineState.STARTING)

            try:
                detector = self._detector_factory(self._settings)
            except ModelNotFoundError as exc:
                self._set_state(PipelineState.ERROR, ErrorInfo(code=ErrorCode.MODEL_MISSING, message=str(exc)))
                return self.status()
            except Exception as exc:
                log.exception("Pose detector initialisation failed")
                self._set_state(
                    PipelineState.ERROR,
                    ErrorInfo(code=ErrorCode.DETECTOR_INIT_FAILED, message=f"Could not load pose model: {exc}"),
                )
                return self.status()

            source = self._source_factory(self._settings)
            try:
                source.open()
            except Exception as exc:
                detector.close()
                source.close()
                if not isinstance(exc, CameraError):
                    log.exception("Unexpected error opening camera")
                self._set_state(PipelineState.ERROR, ErrorInfo(code=ErrorCode.CAMERA_OPEN_FAILED, message=str(exc)))
                return self.status()

            self._source, self._detector = source, detector
            self._run_id += 1
            self._stop_evt = threading.Event()
            self._reset_counters()
            run_id = self._run_id
            self._threads = [
                threading.Thread(target=self._capture_loop, args=(run_id,), name="ptm-capture", daemon=True),
                threading.Thread(target=self._inference_loop, args=(run_id,), name="ptm-inference", daemon=True),
            ]
            for t in self._threads:
                t.start()
            self._set_state(PipelineState.RUNNING)
            return self.status()

    def stop(self) -> StatusMessage:
        """Stop workers and release the camera. Idempotent."""
        with self._lock:
            if self._state in (PipelineState.STOPPED, PipelineState.STOPPING):
                return self.status()
            if self._threads or self._source:
                self._set_state(PipelineState.STOPPING)
            self._teardown()
            self._set_state(PipelineState.STOPPED)
            return self.status()

    def _teardown(self) -> None:
        with self._lock:
            self._stop_evt.set()
            with self._cond:
                self._cond.notify_all()
            current = threading.current_thread()
            for t in self._threads:
                if t is not current:
                    t.join(timeout=_JOIN_TIMEOUT_S)
                    if t.is_alive():
                        log.warning("Worker %s did not exit within %.0fs", t.name, _JOIN_TIMEOUT_S)
            self._threads = []
            if self._source is not None:
                self._source.close()
                self._source = None
            if self._detector is not None:
                self._detector.close()
                self._detector = None
            with self._cond:
                self._latest = None

    def _fail(self, run_id: int, code: ErrorCode, message: str) -> None:
        """Called from a worker. Tears down on a separate thread because a worker
        cannot join itself, then reports the error."""
        self._stop_evt.set()

        def teardown() -> None:
            with self._lock:
                if run_id != self._run_id or self._state is not PipelineState.RUNNING:
                    return  # already stopped/restarted by someone else
                self._teardown()
                self._set_state(PipelineState.ERROR, ErrorInfo(code=code, message=message))

        threading.Thread(target=teardown, name="ptm-teardown", daemon=True).start()

    def _reset_counters(self) -> None:
        self._capture_rate = RateMeter()
        self._inference_rate = RateMeter()
        self._inference_ms = Ema()
        self._dropped = 0
        with self._cond:
            self._latest = None
            self._latest_consumed = True

    # ----------------------------------------------------------------- workers
    def _capture_loop(self, run_id: int) -> None:
        source = self._source
        assert source is not None
        stop = self._stop_evt
        frame_id = 0
        failures = 0
        try:
            while not stop.is_set():
                image = source.read()
                if image is None:
                    failures += 1
                    if failures >= self._settings.max_consecutive_read_failures:
                        self._fail(
                            run_id,
                            ErrorCode.CAMERA_READ_FAILED,
                            f"Camera stopped delivering frames ({failures} consecutive failed reads). "
                            "It may have been disconnected or taken by another app.",
                        )
                        return
                    stop.wait(0.02)
                    continue
                failures = 0
                with self._cond:
                    if not self._latest_consumed:
                        self._dropped += 1
                    self._latest = _Frame(frame_id, _monotonic_ms(), image)
                    self._latest_consumed = False
                    self._cond.notify()
                frame_id += 1
                self._capture_rate.tick()
        except Exception as exc:
            log.exception("Capture loop crashed")
            self._fail(run_id, ErrorCode.CAMERA_READ_FAILED, f"Camera read error: {exc}")

    def _inference_loop(self, run_id: int) -> None:
        detector = self._detector
        assert detector is not None
        s = self._settings
        stop = self._stop_evt
        min_interval = 1.0 / s.max_inference_fps if s.max_inference_fps > 0 else 0.0
        next_due = 0.0
        last_ts = -1
        # Fresh per run so filter history never spans a stop/start. One analyzer
        # per coordinate space, created when first needed (an exercise may
        # require a different space from the default).
        analyzers: dict[AngleSpace, AngleAnalyzer] = {}

        def analyzer_for(space: AngleSpace) -> AngleAnalyzer:
            if space not in analyzers:
                analyzers[space] = AngleAnalyzer(replace(s.angle_config(), space=space))
            return analyzers[space]

        try:
            while not stop.is_set():
                # Rate limit *before* taking a frame so we always use the newest one.
                if min_interval and (delay := next_due - time.monotonic()) > 0:
                    if stop.wait(delay):
                        break
                with self._cond:
                    self._cond.wait_for(lambda: stop.is_set() or not self._latest_consumed, timeout=0.5)
                    if stop.is_set():
                        break
                    if self._latest_consumed or self._latest is None:
                        continue
                    frame = self._latest
                    self._latest_consumed = True
                next_due = time.monotonic() + min_interval

                t0 = time.perf_counter()
                rgb = cv2.cvtColor(resize_to_width(frame.image, s.inference_width), cv2.COLOR_BGR2RGB)
                # MediaPipe VIDEO mode requires strictly increasing timestamps.
                ts = max(frame.captured_ms, last_ts + 1)
                last_ts = ts
                estimate = detector.detect(rgb, ts)
                self._inference_ms.update((time.perf_counter() - t0) * 1000)
                self._inference_rate.tick()

                h, w = frame.image.shape[:2]
                tracker = self._exercise  # read once: the API may swap it concurrently
                space = tracker.definition.camera.angle_space if tracker else s.angle_space
                angles = analyzer_for(space).update(estimate.landmarks, estimate.world_landmarks, ts, (w, h))
                exercise = tracker.update(angles, ts, estimate.landmarks, (w, h)) if tracker else None
                if self._angle_listener is not None:
                    try:
                        self._angle_listener(ts, angles, space)
                    except Exception:
                        log.exception("Angle listener failed")
                if exercise is not None and self._exercise_listener is not None:
                    try:
                        self._exercise_listener(exercise)
                    except Exception:
                        # Session bookkeeping must never stop tracking; log loudly.
                        log.exception("Exercise listener failed")

                jpeg = self._encode_preview(frame.image) if s.preview_enabled else None
                lm = estimate.landmarks
                message = FrameMessage(
                    frame_id=frame.frame_id,
                    timestamp_ms=frame.captured_ms,
                    width=w,
                    height=h,
                    person_detected=estimate.person_detected,
                    landmarks=np.round(lm, 4).tolist() if lm is not None else None,
                    has_preview=jpeg is not None,
                    angle_space=space.value,
                    angles=[_angle_message(a) for a in angles],
                    exercise=_exercise_message(exercise) if exercise else None,
                    metrics=FrameMetrics(
                        capture_fps=round(self._capture_rate.rate(), 1),
                        inference_fps=round(self._inference_rate.rate(), 1),
                        inference_ms=round(self._inference_ms.value or 0.0, 1),
                        latency_ms=float(_monotonic_ms() - frame.captured_ms),
                        dropped_frames=self._dropped,
                    ),
                )
                self._on_frame(encode_frame_packet(message, jpeg))
        except Exception as exc:
            log.exception("Inference loop crashed")
            self._fail(run_id, ErrorCode.INFERENCE_FAILED, f"Pose inference error: {exc}")

    def _encode_preview(self, image: np.ndarray) -> bytes:
        s = self._settings
        small = resize_to_width(image, s.preview_width)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, s.preview_jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return buf.tobytes()
