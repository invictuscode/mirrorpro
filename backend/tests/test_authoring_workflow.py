"""Recorder, video processing, draft store and the approval workflow."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.authoring import video as video_mod
from app.authoring.analysis import analyze
from app.authoring.recorder import DemonstrationCache, LiveRecorder, RecordingError
from app.authoring.series import AngleSeries
from app.authoring.service import AuthoringError, CustomExerciseService, NotFound, build_definition
from app.authoring.store import JsonFileStore
from app.authoring.video import VideoError, process_video
from app.biomechanics import AngleResult, AngleSpace, AngleStatus
from app.config import Settings
from app.exercises.library import ExerciseLibrary, ExerciseLibraryError
from app.exercises.schema import RepCountingConfig, ReviewStatus, SideMode
from app.feedback.config import MessageKey
from app.pose.detector import PoseEstimate
from app.schemas.authoring import ApproveRequest, CreateDraft, DraftFields
from tests.fakes import CurlingDetector


def ok(id_: str, v: float) -> AngleResult:
    return AngleResult(id_, AngleStatus.OK, v, v, 0.9)


def nobody(id_: str) -> AngleResult:
    return AngleResult(id_, AngleStatus.NO_PERSON, None, None, None)


# --- live recorder -------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


def test_recorder_captures_frames_and_caches_demo() -> None:
    clock, cache = Clock(), DemonstrationCache()
    rec = LiveRecorder(cache, max_ms=10_000, clock=clock)
    rec.start()
    for i in range(60):
        clock.now = i * 33
        rec.on_frame(i * 33, [ok("right_elbow_flexion", 10 + i)], AngleSpace.IMAGE)
    status = rec.status()
    assert status.recording and status.frames == 60
    info = rec.stop()
    assert info.source == "live" and info.frames == 60 and info.person_fraction == 1.0
    cached = cache.get(info.demo_id)
    assert cached is not None and cached[1].values["right_elbow_flexion"][5] == 15
    assert not rec.recording


def test_recorder_rejects_empty_or_personless_recordings() -> None:
    clock, rec = Clock(), LiveRecorder(DemonstrationCache(), clock=Clock())
    rec.start()
    with pytest.raises(RecordingError, match="camera running"):
        rec.stop()
    rec = LiveRecorder(DemonstrationCache(), clock=clock)
    rec.start()
    for i in range(40):
        rec.on_frame(i * 33, [nobody("right_elbow_flexion")], AngleSpace.IMAGE)
    with pytest.raises(RecordingError, match="person"):
        rec.stop()
    with pytest.raises(RecordingError):
        rec.stop()  # not recording any more


def test_recorder_caps_length_and_ignores_frames_when_idle() -> None:
    clock = Clock()
    rec = LiveRecorder(DemonstrationCache(), max_ms=1000, clock=clock)
    rec.on_frame(0, [ok("right_elbow_flexion", 1)], AngleSpace.IMAGE)  # not recording: ignored
    rec.start()
    for i in range(100):
        clock.now = i * 33
        rec.on_frame(i * 33, [ok("right_elbow_flexion", 1)], AngleSpace.IMAGE)
    assert rec.status().frames <= 32 and rec.status().elapsed_ms == 1000
    with pytest.raises(RecordingError, match="already"):
        rec.start()


def test_cache_is_bounded() -> None:
    cache = DemonstrationCache(capacity=2)
    s = AngleSeries.from_frames([(0, [])], AngleSpace.IMAGE)
    a, b, c = (cache.add("live", s, 1.0) for _ in range(3))
    assert cache.get(a.demo_id) is None and cache.get(c.demo_id) is not None


# --- video ---------------------------------------------------------------------
def write_video(path: Path, seconds: float = 4.0, fps: int = 30) -> Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    assert w.isOpened()
    for i in range(int(seconds * fps)):
        frame = np.full((240, 320, 3), (i * 3) % 255, np.uint8)
        w.write(frame)
    w.release()
    return path


def test_video_is_processed_into_an_angle_series(tmp_path: Path, settings: Settings) -> None:
    path = write_video(tmp_path / "demo.mp4")
    series, frac = process_video(path, settings, CurlingDetector, AngleSpace.IMAGE)
    assert frac == 1.0 and series.n_frames >= 100
    assert series.duration_ms == pytest.approx(4000, abs=100)
    r = analyze("v", series)
    assert r.chosen is not None and r.chosen.joint == "elbow_flexion" and len(r.reps) >= 2


def test_video_errors_are_explained(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"definitely not a video")
    with pytest.raises(VideoError, match="could not be opened"):
        process_video(junk, settings, CurlingDetector, AngleSpace.IMAGE)

    class NoOne:
        def __init__(self, s: Settings) -> None: ...
        def detect(self, rgb: np.ndarray, ts: int) -> PoseEstimate:
            return PoseEstimate(None, None)
        def close(self) -> None: ...

    path = write_video(tmp_path / "empty.mp4", seconds=2)
    with pytest.raises(VideoError, match="person was detected in only 0%"):
        process_video(path, settings, NoOne, AngleSpace.IMAGE)

    monkeypatch.setattr(video_mod, "MAX_DURATION_S", 1)
    with pytest.raises(VideoError, match="limit is 1 s|longer than 1 s"):
        process_video(path, settings, CurlingDetector, AngleSpace.IMAGE)


# --- drafts and approval -------------------------------------------------------------
def fields(**kw: object) -> DraftFields:
    base: dict[str, object] = dict(
        name="Towel slide",
        description="Slide the hand forward along a table.",
        instructions=["Sit at a table side-on to the screen.", "Slide your hand forward, then back."],
        camera_view="side",
        camera_guidance="Sit side-on so shoulder, elbow and wrist stay in view.",
        signal_joint="elbow_flexion",
        side_mode="single",
        default_side="right",
        rep_counting=RepCountingConfig(start_deg=80, target_deg=20, hysteresis_deg=6),
        target_not_reached_message="Slide a little further.",
    )
    return DraftFields.model_validate(base | kw)


@pytest.fixture
def svc(tmp_path: Path) -> tuple[CustomExerciseService, ExerciseLibrary, DemonstrationCache, Path]:
    lib = ExerciseLibrary.from_directory()
    cache = DemonstrationCache()
    d = tmp_path / "custom"
    return CustomExerciseService(JsonFileStore(d), lib, cache), lib, cache, d


def demo(cache: DemonstrationCache) -> str:
    frames = [(i * 33, [ok("right_elbow_flexion", 50 + 30 * np.sin(i / 10))]) for i in range(100)]
    return cache.add("live", AngleSeries.from_frames(frames, AngleSpace.IMAGE), 1.0).demo_id


def test_draft_is_not_offered_until_approved(svc) -> None:  # type: ignore[no-untyped-def]
    s, lib, cache, _ = svc
    rec = s.create(CreateDraft(fields=fields(), demo_id=demo(cache)))
    assert rec.status == "draft" and rec.version == 1 and rec.id.startswith("custom_towel_slide_")
    assert lib.get(rec.id) is None, "drafts never reach patients"
    with pytest.raises(AuthoringError, match="confirming"):
        s.approve(rec.id, ApproveRequest(reviewer="Dr Lee", attestation=False))
    assert lib.get(rec.id) is None

    approved = s.approve(rec.id, ApproveRequest(reviewer="Dr Lee", attestation=True))
    d = lib.get(rec.id)
    assert approved.status == "approved" and approved.live_version == 1
    assert d is not None and d.clinical_review.status is ReviewStatus.APPROVED
    assert d.clinical_review.reviewed_by == "Dr Lee" and not d.is_demo
    assert d.feedback.text(MessageKey.TARGET_NOT_REACHED) == "Slide a little further."
    assert set(d.relevant_landmarks) == {"left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist"}


def test_angle_data_is_stored_only_with_consent(svc) -> None:  # type: ignore[no-untyped-def]
    s, _, cache, d = svc
    no = s.create(CreateDraft(fields=fields(), demo_id=demo(cache), store_angle_data=False))
    yes = s.create(CreateDraft(fields=fields(name="Other"), demo_id=demo(cache), store_angle_data=True))
    assert not list(d.glob(f"{no.id}.*.angles.json"))
    stored = list(d.glob(f"{yes.id}.*.angles.json"))
    assert len(stored) == 1 and json.loads(stored[0].read_text())["values"]["right_elbow_flexion"][0] is not None
    assert no.demonstrations[0].angle_data_stored is False and yes.demonstrations[0].angle_data_stored is True
    # Only JSON is ever written: no video or image files.
    assert {p.suffix for p in d.iterdir()} == {".json"}


def test_editing_an_approved_exercise_needs_reapproval(svc) -> None:  # type: ignore[no-untyped-def]
    s, lib, _, _ = svc
    rec = s.create(CreateDraft(fields=fields()))
    s.approve(rec.id, ApproveRequest(reviewer="Dr Lee", attestation=True))
    edited = s.update(rec.id, fields(rep_counting=RepCountingConfig(start_deg=80, target_deg=30, hysteresis_deg=6)))
    assert edited.status == "draft" and edited.version == 2 and edited.live_version == 1
    live = lib.get(rec.id)
    assert live is not None and live.version == 1 and live.rep_counting.target_deg == 20, "patients keep v1"
    s.approve(rec.id, ApproveRequest(reviewer="Dr Kim", attestation=True))
    live = lib.get(rec.id)
    assert live is not None and live.version == 2 and live.rep_counting.target_deg == 30
    assert live.clinical_review.reviewed_by == "Dr Kim"


def test_archive_and_delete_rules(svc) -> None:  # type: ignore[no-untyped-def]
    s, lib, _, _ = svc
    draft = s.create(CreateDraft(fields=fields()))
    s.delete(draft.id)
    with pytest.raises(NotFound):
        s.get(draft.id)
    rec = s.create(CreateDraft(fields=fields()))
    s.approve(rec.id, ApproveRequest(reviewer="Dr Lee", attestation=True))
    with pytest.raises(AuthoringError, match="archive"):
        s.delete(rec.id)
    s.archive(rec.id)
    assert lib.get(rec.id) is None
    with pytest.raises(AuthoringError):
        s.update(rec.id, fields())
    s.delete(rec.id)


def test_approved_exercises_survive_restart(svc, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, _, d = svc
    rec = s.create(CreateDraft(fields=fields()))
    s.approve(rec.id, ApproveRequest(reviewer="Dr Lee", attestation=True))
    s.create(CreateDraft(fields=fields(name="Still a draft")))
    lib2 = ExerciseLibrary.from_directory()
    s2 = CustomExerciseService(JsonFileStore(d), lib2, DemonstrationCache())
    assert s2.load_approved_into_library() == 1
    assert lib2.get(rec.id) is not None and len(s2.list()) == 2


def test_drafts_get_the_same_validation_and_wording_guardrail(svc) -> None:  # type: ignore[no-untyped-def]
    s, _, cache, _ = svc
    with pytest.raises(ValueError, match="safe"):
        s.create(CreateDraft(fields=fields(instructions=["This is completely safe."])))
    with pytest.raises(ValueError, match="safe"):
        s.create(CreateDraft(fields=fields(target_not_reached_message="Go further, it is safe.")))
    with pytest.raises(NotFound, match="no longer available"):
        s.create(CreateDraft(fields=fields(), demo_id="demo_missing"))
    with pytest.raises(ValueError):
        fields(rep_counting={"start_deg": 30, "target_deg": 35})  # too close


def test_library_refuses_drafts() -> None:
    d = build_definition("custom_x_0000", 1, fields(), ReviewStatus.DRAFT)
    with pytest.raises(ExerciseLibraryError, match="draft"):
        ExerciseLibrary([d])
    lib = ExerciseLibrary.from_directory()
    with pytest.raises(ExerciseLibraryError):
        lib.upsert(d)


def test_bilateral_drafts_drop_default_side() -> None:
    d = build_definition("custom_x_0000", 1, fields(side_mode="mean_of_visible"), ReviewStatus.DRAFT)
    assert d.signal.side_mode is SideMode.MEAN_OF_VISIBLE and d.signal.default_side is None
