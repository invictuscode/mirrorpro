# Architecture

## Overview

```
                        Python backend (FastAPI, 127.0.0.1:8000)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │  capture thread          inference thread                 asyncio loop     │
 │  OpenCVCamera.read() ──► [latest-frame slot] ──► resize ─► StreamHub ──► WS │
 │  (camera FPS)            (single slot,          MediaPipe   (latest-wins   │
 │                           overwritten)          Pose        per client)    │
 │                                                 JPEG preview               │
 └───────────────────────────────────────────────────────────────────────────┘
                                   │ /ws/stream (binary packets + JSON status)
                                   ▼
                     React frontend (Vite, 127.0.0.1:5173)
   PoseStreamClient ─► createImageBitmap (≤1 in flight) ─► frameRef ─► rAF canvas draw
                                                         └─► 4 Hz snapshot ─► text panels
```

### Why this shape

* **Two threads with a single-slot buffer.** Capture never waits on inference
  and inference always takes the newest frame, so latency stays bounded when
  the model is slower than the camera (the Raspberry Pi case). Skipped frames
  are counted (`dropped_frames`), not queued.
* **Python owns the camera.** Inference runs where MediaPipe's native runtime
  is, and the same process will run on a Pi. The browser never touches the
  camera.
* **One binary packet per frame** (landmarks JSON + optional JPEG) keeps image
  and skeleton in sync without base64 overhead.
* **Preview video is optional.** Behind a two-way mirror the reflection *is*
  the video; set `PTM_PREVIEW_ENABLED=false` and only ~1.5 KB of landmarks per
  frame is sent. That also removes the JPEG encode cost on a Pi.
* **React does not re-render per frame.** Frames go into a ref and are drawn in
  a `requestAnimationFrame` loop; diagnostic panels update from a 4 Hz snapshot.
* **Interfaces at the seams.** `FrameSource` (camera) and `PoseDetector`
  (model) are protocols, injected via `create_app(...)`. Tests use fakes; a
  Picamera2 source or a different model can be added without touching the
  pipeline or API.

## Backend layout

| Path | Responsibility |
|------|----------------|
| `app/config.py` | `PTM_*` env settings, hardware profiles (`dev`, `pi`), validation |
| `app/camera/source.py` | `FrameSource` protocol, `OpenCVCamera`, platform-specific error hints |
| `app/pose/detector.py` | `PoseDetector` protocol, `MediaPipePoseDetector` (Tasks API, VIDEO mode) |
| `app/pose/topology.py` | Landmark names + skeleton edges (tested against installed MediaPipe) |
| `app/biomechanics/geometry.py` | `angle_at(a, b, c)`: 2D/3D angle with degenerate/invalid input → `None` |
| `app/biomechanics/filters.py` | One Euro, EMA, pass-through filters (timestamp-aware) |
| `app/biomechanics/joints.py` | Joint-angle definitions and conventions |
| `app/biomechanics/analyzer.py` | Per-frame gating (visibility, frame bounds), space selection, smoothing, gap reset |
| `app/pipeline/tracking.py` | Threaded capture/inference pipeline, lifecycle, error reporting |
| `app/pipeline/metrics.py` | FPS meter, EMA |
| `app/exercises/schema.py` | Exercise definition model + validation, therapist overrides |
| `app/exercises/library.py` | Loads/validates preset JSON files (fails loudly) |
| `app/exercises/rep_counter.py` | Repetition state machine (pure; hysteresis, confirmation, gaps, timing) |
| `app/exercises/tracker.py` | Picks the driving angle(s) for an exercise and runs the counter |
| `app/exercises/phases.py` | Rep phases and event kinds shared by counter and feedback |
| `app/feedback/config.py` | Feedback config, form rules, default messages, wording guardrail |
| `app/feedback/engine.py` | Rule evaluation, uncertainty gating, message arbitration (pure) |
| `app/sessions/manager.py` | Sets, rest, pause/resume, timing, summary (thread-safe, injectable clock) |
| `app/api/sessions.py` | Session endpoints |
| `app/schemas/session.py` | Session contract |
| `app/authoring/series.py` | Per-frame angle series from a demonstration (derived data only) |
| `app/authoring/analysis.py` | Joint ranking, rep detection, suggested parameters, warnings (pure) |
| `app/authoring/recorder.py` | Live recording via the pipeline's angle listener; bounded demo cache |
| `app/authoring/video.py` | Uploaded video → angle series (same model/analyzer) |
| `app/authoring/store.py` | Custom-exercise persistence (JSON files behind a protocol; SQLite in Phase 7) |
| `app/authoring/service.py` | Draft → approve → library workflow, versioning, consent-gated storage |
| `app/api/authoring.py` | Authoring endpoints (upload streamed to a temp file, always deleted) |
| `app/api/exercises.py` | Exercise library + active-selection endpoints |
| `app/schemas/messages.py` | Wire contract (pydantic) + frame packet encoding |
| `app/api/stream_hub.py` | Thread → asyncio fan-out, latest-wins per subscriber |
| `app/api/routes.py` | REST + WebSocket endpoints |
| `app/main.py` | App factory, lifespan (camera released on shutdown) |

`biomechanics/` imports nothing from camera, model, API or config; the
pipeline builds an `AngleAnalyzerConfig` from settings and calls
`AngleAnalyzer.update()` once per frame in the inference thread.

The active exercise is an `ExerciseTracker` held by the pipeline. The API
thread replaces it wholesale (an atomic reference swap); only the inference
thread calls its `update()`, so the counter needs no locking.

Sessions sit above the pipeline. The `SessionManager` installs a tracker
per set via `pipeline.set_exercise`, and receives every exercise frame via
`pipeline.set_exercise_listener` (exceptions there are logged and never stop
tracking). The stream hub carries text channels (`status`, `session`) plus
binary frames, each latest-wins.

The `database/` module (Phase 7) is intentionally **not** created yet.

## Frontend layout

| Path | Responsibility |
|------|----------------|
| `src/types/protocol.ts` | TypeScript mirror of the wire contract |
| `src/services/packet.ts` | Binary packet / status parsing with validation |
| `src/services/streamClient.ts` | WebSocket with reconnect + backpressure-aware JPEG decode |
| `src/services/trackingStatus.ts` | Prioritised "what should the user know" logic (pure, tested) |
| `src/services/api.ts` | REST calls |
| `src/services/angles.ts` | Pair angle definitions with measurements, formatting (pure, tested) |
| `src/services/exercise.ts` | Phase labels and rep-event descriptions (pure, tested) |
| `src/hooks/useExercises.ts` | Library, active selection, resync via `selection_id` |
| `src/components/ExercisePanel.tsx` | Choose exercise/side, adjust thresholds, live count and events |
| `src/components/RepOverlay.tsx` | Large rep counter over the camera view |
| `src/components/FeedbackBanner.tsx` | The current feedback message, large, `aria-live` |
| `src/components/FeedbackPanel.tsx` | Dev view: rule states, tracking gate, message log |
| `src/services/feedback.ts` | Rule descriptions and message log (pure, tested) |
| `src/components/AnglesPanel.tsx` | Left/right angle table with reasons for missing values |
| `src/hooks/usePoseStream.ts` | React binding: frame ref, status, throttled snapshot |
| `src/components/PoseCanvas.tsx` | Canvas renderer (video + skeleton coloured by visibility) |
| `src/App.tsx` | Hash routing (`#/` mirror, `#/dev` console) inside an error boundary |
| `src/pages/MirrorPage.tsx` | Patient-facing screen: picks home / session / summary, shortcuts, display mode |
| `src/components/mirror/*` | Home, session, summary screens and the camera stage |
| `src/hooks/useSessionControls.ts` | Session commands (starts the camera first) |
| `src/services/time.ts` | Duration formatting and timer extrapolation (tested) |
| `src/pages/TherapistPage.tsx` | Therapist workspace: list, wizard, edit, approve |
| `src/components/therapist/*` | Basics, demonstration (record/upload), review, parameter editor, chart |
| `src/services/authoring.ts`, `authoringApi.ts` | Draft-building helpers (tested), authoring API client |
| `src/pages/DevPage.tsx` | Developer console layout |

## Error handling

Every failure becomes a `StatusMessage` with `state: "error"` and an
`ErrorInfo{code, message}`; the UI shows it over the camera view. Worker-thread
failures (camera unplugged, inference exception) tear down on a separate thread
(a worker can't join itself), release the camera, and report. A run-ID guards
against a late failure from an old run clobbering a newer one. Unexpected
exceptions are logged with tracebacks (`log.exception`), never swallowed.

## Development on Apple Silicon vs deployment on Raspberry Pi

| | MacBook (Apple Silicon) | Raspberry Pi (future) |
|---|---|---|
| Camera API | AVFoundation via OpenCV | V4L2 via OpenCV for USB webcams. The Pi Camera Module on current Raspberry Pi OS uses libcamera; it may need a `Picamera2`-based `FrameSource` (not implemented). |
| Permissions | macOS TCC prompt per launching app | User in `video` group |
| Inference | MediaPipe CPU (XNNPACK); `full` model | MediaPipe CPU on ARM64; start with `lite` (`PTM_PROFILE=pi`) |
| Wheels | `mediapipe-1.1.1-py3-none-macosx_11_0_arm64` | `mediapipe-1.1.1-py3-none-manylinux_2_28_aarch64` exists on PyPI (checked 2026‑10‑27): requires **64-bit** Raspberry Pi OS with glibc ≥ 2.28 (Bookworm or later). Install not yet tested on a Pi. |
| Display | Browser on the same machine | Chromium kiosk on the Pi, or a separate display device |

Notes:

* `PTM_PROFILE=pi` sets conservative starting values (lite model, 640×480,
  15 inference FPS cap, smaller preview). These are **untested guesses**, not
  measured results. Expected performance differs substantially between Pi 4
  and Pi 5; measure with the Performance panel before setting targets.
* No discrete GPU is used or required. MediaPipe's Python Tasks API runs on CPU
  here; GPU delegates are not used. An accelerator (e.g. a Hailo or Coral
  board) would require a different model/runtime and is **not** planned until
  CPU performance on a real Pi has been measured and shown insufficient.
* Disabling the preview (`PTM_PREVIEW_ENABLED=false`) saves JPEG encoding and
  bandwidth — likely worthwhile on a Pi behind a mirror.

## Configuration reference

All optional. Set as environment variables before `scripts/run_backend.sh`.

| Variable | Default (dev) | Meaning |
|---|---|---|
| `PTM_PROFILE` | `dev` | `dev` or `pi` default set |
| `PTM_HOST` / `PTM_PORT` | `127.0.0.1` / `8000` | Bind address. Keep loopback unless you add auth. |
| `PTM_CAMERA_INDEX` | `0` | Camera device index |
| `PTM_CAMERA_BACKEND` | `auto` | `auto`, `avfoundation`, `v4l2` |
| `PTM_CAPTURE_WIDTH` / `_HEIGHT` / `_FPS` | `1280` / `720` / `30` | Requested capture mode (driver may pick nearest) |
| `PTM_MAX_CONSECUTIVE_READ_FAILURES` | `60` | Failed reads before "camera lost" |
| `PTM_MODEL_PATH` | `models/pose_landmarker_full.task` | Relative paths resolve from project root |
| `PTM_MIN_POSE_DETECTION_CONFIDENCE` etc. | `0.5` | MediaPipe thresholds |
| `PTM_INFERENCE_WIDTH` | `640` | Downscale before inference |
| `PTM_MAX_INFERENCE_FPS` | `30` | `0` = unlimited |
| `PTM_PREVIEW_ENABLED` | `true` | Send JPEG preview to the UI |
| `PTM_PREVIEW_WIDTH` / `_JPEG_QUALITY` | `640` / `70` | Preview size/quality |
| `PTM_ANGLE_SPACE` | `image` | `image` (2D) or `world` (3D model estimate). Image is the default: in testing on the MacBook it read better for movements kept side-on to the camera. |
| `PTM_ANGLE_MIN_VISIBILITY` | `0.5` | Min landmark visibility to report an angle |
| `PTM_ANGLE_FILTER` | `one_euro` | `one_euro`, `ema`, `none` |
| `PTM_ANGLE_FILTER_MIN_CUTOFF_HZ` / `_BETA` | `1.0` / `0.02` | One Euro parameters |
| `PTM_ANGLE_FILTER_EMA_ALPHA` | `0.3` | EMA weight |
| `PTM_ANGLE_MAX_GAP_MS` | `500` | Invalid-gap length after which smoothing restarts |
| `PTM_EXERCISE_DIR` | built-in presets | Directory of exercise definition JSON files |
| `PTM_DATA_DIR` | `data/` | Local data: custom exercises, consented angle data |
