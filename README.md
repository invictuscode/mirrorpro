# PT Smart Mirror (prototype)

Camera-based movement tracking for physical-therapy exercises, designed to run
locally on a laptop today and on a Raspberry Pi behind a two-way mirror later.

> **Research prototype — not clinically validated.** Not a medical device and
> not a substitute for a licensed physical therapist. All body positions are
> experimental computer-vision estimates. No regulatory compliance is claimed.

**Status: Phase 6 plus anti-cheat and guidance.** Joints that must stay
steady (e.g. straight elbows in jumping jack arms) can block repetitions, so
an exercise cannot be completed with the wrong joint or by hiding a joint;
demonstrations suggest these automatically. Each session starts with a guided
practice repetition, with arrows and target lines on the camera, and every
exercise has detailed setup, step and key-point guidance.

**Phase 6 — custom exercises from a therapist's demonstration**
(record or upload → suggested parameters → review → approve), on top of the
smart-mirror interface with exercise sessions (sets,
rest, pause/resume, timer, summary), on top of live pose tracking, estimated
joint angles, repetition counting and rule-based feedback. Eight demo
exercises are included; before starting, the mirror offers to keep the
defaults or adjust the angles, hold time, sets, reps and rest. During a
session the counter fills the screen, and a Camera button splits the screen
to show the camera with all body points. Patient plans and SQLite storage
(Phase 7) are not implemented yet. See
[docs/CUSTOM_EXERCISES.md](docs/CUSTOM_EXERCISES.md).

Feedback comes from explicit configurable rules, never from a generative
model. Unreliable tracking is reported as uncertainty, never as a movement
error. See [docs/FEEDBACK.md](docs/FEEDBACK.md).

The presets are **demonstration configurations**: their thresholds are
illustrative values for software testing, not clinical targets, and they have
not been reviewed by a clinician. See [docs/EXERCISES.md](docs/EXERCISES.md).

Joint angles are experimental estimates with real limitations — read
[docs/JOINT_ANGLES.md](docs/JOINT_ANGLES.md) before interpreting them.

## Privacy defaults

* Video is processed on this computer. Nothing is uploaded; there is no
  analytics or telemetry.
* No frames are written to disk. Frames exist in memory only while processed.
* The backend binds to `127.0.0.1` only. The JPEG preview goes only to the
  local browser page and can be turned off (`PTM_PREVIEW_ENABLED=false`).

## Requirements (verified on this machine)

| | Version |
|---|---|
| macOS | 27.0, Apple Silicon (arm64) |
| Python | 3.13 (python.org build) |
| Node.js / npm | 24.10 / 11.6 (Vite 8 needs Node ≥ 20.19) |

Pinned packages: `backend/requirements*.txt`, `frontend/package.json`.
Notable choices:

* **mediapipe 1.1.1** — uses the official Tasks `PoseLandmarker` API.
* **opencv-contrib-python 4.14** — mediapipe depends on this package. Do
  **not** also install `opencv-python`; both provide `cv2` and conflict.
  Pinned to the 4.x line rather than the brand-new 5.0 major.
* **React 19.3, Vite 8.3, TypeScript 7.0** — the versions the official
  `create-vite` React-TS template currently pairs.

## Setup

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cd ..
```

### Pose model asset

MediaPipe needs a `.task` model file. It is not in the repo. Download the
official asset from Google's model bucket into `models/`:

```bash
backend/.venv/bin/python scripts/download_model.py
```

This fetches `pose_landmarker_full.task` (~9 MB) from
`storage.googleapis.com/mediapipe-models/pose_landmarker/…/float16/1/` (pinned
model version 1). Add `lite` or `heavy` as arguments for the other variants;
the `pi` profile uses `lite`. After that, no internet connection is needed.

If the download fails with `CERTIFICATE_VERIFY_FAILED`, you ran it with the
system `python3` from python.org that has no CA bundle installed. Use the venv
Python as shown above (it uses `certifi`) or run *Install Certificates.command*
from `/Applications/Python 3.13/`.

### Frontend

```bash
cd frontend
npm install
```

## Run

Two terminals, **started from an app that has camera permission** (see below):

```bash
scripts/run_backend.sh
```

```bash
scripts/run_frontend.sh
```

* **Mirror (patient) view:** http://127.0.0.1:5173. Choose an exercise
  and press Start; the camera starts automatically. Keys: `Space`
  pause/resume, `N` finish set / skip rest, `E E` end, `F` fullscreen, `D`
  display mode.
* **Therapist workspace:** http://127.0.0.1:5173/#/therapist. Create custom
  exercises from a demonstration (local use only; no sign-in yet).
* **Developer console:** http://127.0.0.1:5173/#/dev. Diagnostics, manual
  exercise selection and *Start camera*.

See [docs/MIRROR_UI.md](docs/MIRROR_UI.md).

Stop the backend with Ctrl+C — the camera is released on shutdown.

### macOS camera permission

macOS grants camera access per *launching application* (Terminal, iTerm, VS
Code, …), not per Python script. The first time the backend opens the camera,
macOS should prompt for the app you ran it from. If it was denied earlier, or
no prompt appears:

1. System Settings → Privacy & Security → Camera → enable your terminal app.
2. Fully quit and reopen that terminal app, then start the backend again.

The UI shows *Camera unavailable* with this hint when access is blocked.

## Tests

```bash
cd backend && .venv/bin/python -m pytest
cd frontend && npm test && npm run typecheck
```

Backend tests cover config validation, packet encoding, FPS metrics, the
threaded pipeline (start/stop/restart, downscaling, rate limiting, camera
disconnect, inference failure, missing model) with fake camera/detector,
REST + WebSocket integration, and the real MediaPipe model on blank frames.
Phase 2 adds tests for angle geometry against known coordinates (2D/3D,
near-straight precision, degenerate and invalid inputs), the One Euro/EMA
filters, every joint definition on synthetic poses, aspect-ratio correction,
reliability gating, and filter reset after tracking gaps.
Phase 3 adds tests for the repetition state machine (clean reps, threshold
jitter, one-frame spikes, short and long tracking gaps, too fast, timeout,
required holds, partial reps, decreasing-direction exercises, noisy signals
with dropouts), preset validation and loud failure on bad files, therapist
overrides, signal selection per side, the exercise API, and an end-to-end
test where a scripted person's curls are counted through the real pipeline
and WebSocket.
Phase 4 adds tests for the feedback engine (sustained vs brief violations,
uncertain joints making no judgement, no judgement during the tracking grace
period, tracking and no-person messages, cooldowns between different and
repeated messages, display and minimum-display times, one-shot rep events,
hold and return-to-start cues, rule sides), the wording guardrail on messages,
rules and instructions, and an end-to-end feedback check over the WebSocket.
Phase 5 adds session tests: sets and rest, a rest timer starting the next
set with no frames, zero rest, pause stopping counting and time, pause during
rest freezing the countdown, resume keeping the count, finishing a set early,
skipping rest, ending mid-set (partial set recorded), stale frames from a
previous set ignored, summary statistics, conflicts, the session API, and a
full two-set session over the real pipeline and WebSocket.
Frontend tests cover packet and text-message parsing, tracking-status logic,
angle, exercise and feedback display helpers, and timer formatting and
extrapolation.

## Project layout

```
backend/      FastAPI + OpenCV + MediaPipe (app/, tests/)
frontend/     React + TypeScript + Vite
models/       downloaded .task model assets (git-ignored)
scripts/      model download, run scripts
docs/         ARCHITECTURE.md (design, Pi notes, config), PROTOCOL.md (API contract),
              JOINT_ANGLES.md (definitions, conventions, limitations),
              EXERCISES.md (schema, presets, rep state machine),
              FEEDBACK.md (rules, arbitration, wording policy),
              MIRROR_UI.md (mirror screens, controls, sessions),
              CUSTOM_EXERCISES.md (demonstration → review → approval)
```

## Known limitations

* Single person only (`num_poses=1`).
* `visibility` / `presence` are model scores, not calibrated probabilities.
  `z` is a rough relative depth, not a measurement.
* Joint angles are unvalidated estimates (projection error, model-guessed
  depth, landmark ≠ anatomical joint centre). See docs/JOINT_ANGLES.md.
* Rep counting depends on camera placement matching each exercise's declared
  view, and on the angle estimate. Demo thresholds are not clinical targets.
* Camera index is configured by env var; there is no device picker in the UI.
* Raspberry Pi: not tested. The `pi` profile values are starting guesses, and
  the Pi Camera Module may need a Picamera2 source (not implemented).

## Roadmap

1. ✅ Live camera, pose landmarks, status, start/stop, FPS
2. ✅ Joint-angle estimates with temporal filtering
3. ✅ Preset exercise library + repetition state machine
4. ✅ Rule-based real-time feedback
5. ✅ Smart-mirror full-screen UI and sessions
6. ✅ Custom exercise recording with therapist review
7. SQLite sessions and progress
# mirrorpro
