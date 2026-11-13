# Backend ↔ frontend protocol (v8)

Source of truth: `backend/app/schemas/messages.py` (Python) and
`frontend/src/types/protocol.ts` (TypeScript). Keep them in sync and bump
`PROTOCOL_VERSION` on breaking changes.

The backend binds to `127.0.0.1:8000`. In development the Vite server proxies
`/api` and `/ws` to it, so the browser talks to a single origin.

## REST

| Method | Path                 | Response          | Notes |
|--------|----------------------|-------------------|-------|
| GET    | `/api/health`        | `{"ok": true}`    | Liveness. |
| GET    | `/api/status`        | `StatusMessage`   | Current pipeline state. |
| POST   | `/api/camera/start`  | `StatusMessage`   | Opens camera + model, starts workers. **503** with a `StatusMessage` whose `error` explains why if it fails. Idempotent. |
| POST   | `/api/camera/stop`   | `StatusMessage`   | Stops workers and releases the camera. Idempotent. |
| GET    | `/api/pose/topology` | `{landmark_names: string[33], connections: [int, int][]}` | Static skeleton definition. |
| GET    | `/api/exercises` | `ExerciseSummary[]` | `{id, version, name, description, camera_view, side_mode, default_side, is_demo}` |
| GET    | `/api/exercises/{id}` | `ExerciseDefinition` | Full definition (see EXERCISES.md). 404 if unknown. |
| GET    | `/api/exercise/active` | `ActiveExercise \| null` | `{selection_id, exercise, side, overrides, effective_rep_counting}` |
| PUT    | `/api/exercise/active` | `ActiveExercise` | Body `{exercise_id, side?, overrides?: {start_deg?, target_deg?, min_hold_ms?}}`. Count starts at 0. 404 unknown id; 422 with a readable `detail` for a bad side or overrides. |
| POST   | `/api/exercise/active/reset` | `ActiveExercise` | Same settings, count back to 0 (new `selection_id`). 409 if none active. |
| DELETE | `/api/exercise/active` | 204 | Stop tracking the exercise. |
| GET    | `/api/session` | `SessionView \| null` | Exercise session; see MIRROR_UI.md for the full session API (start, pause, resume, advance, end, dismiss). |
| —      | `/api/demonstrations/…`, `/api/custom-exercises/…` | | Therapist authoring; see CUSTOM_EXERCISES.md. |
| GET    | `/api/angles/definitions` | `AngleDefinition[]` | `{id, label, joint, side, landmarks: [proximal, vertex, distal], convention: "flexion" \| "included", description}`. See JOINT_ANGLES.md. |

Interactive docs: http://127.0.0.1:8000/docs (FastAPI-generated).

## WebSocket `/ws/stream`

Server → client only; anything the client sends is ignored. On connect the
server immediately sends the current status, then pushes updates.

### Text messages: `StatusMessage`

```json
{
  "type": "status",
  "protocol_version": 7,
  "state": "stopped | starting | running | stopping | error",
  "error": null | { "code": "<ErrorCode>", "message": "human-readable, actionable" },
  "camera": "OpenCV camera #0 (auto)" | null,
  "model": "pose_landmarker_full.task",
  "profile": "dev",
  "preview_enabled": true,
  "angle_space": "world | image"
}
```

`ErrorCode`: `model_missing`, `detector_init_failed`, `camera_open_failed`,
`camera_read_failed`, `inference_failed`.

### Text messages: `SessionMessage`

```json
{ "type": "session", "session": null | SessionView }
```

Sent on connect and on every session change. `SessionView` is defined in
`backend/app/schemas/session.py` (state, plan, current set and reps, finished
sets, `active_ms`, `rest_ms`, `elapsed_ms`, `rest_remaining_ms`, `summary`).
Timers are as of the message; clients extrapolate between messages.

### Binary messages: frame packet

```
offset 0  uint32 big-endian  N = length of JSON
offset 4  N bytes            UTF-8 JSON FrameMessage
offset 4+N  remaining bytes  JPEG preview (absent when has_preview = false)
```

One packet per processed frame, so landmarks and image are always in sync and
the JPEG is not base64-inflated.

```json
{
  "type": "frame",
  "frame_id": 1234,
  "timestamp_ms": 98765432,
  "width": 1280, "height": 720,
  "person_detected": true,
  "landmarks": [[x, y, z, visibility, presence], ... 33 entries] | null,
  "has_preview": true,
  "angle_space": "image",
  "angles": [
    { "id": "left_elbow_flexion", "status": "ok", "value_deg": 87.3, "raw_deg": 88.1, "confidence": 0.93 },
    { "id": "right_elbow_flexion", "status": "low_visibility", "value_deg": null, "raw_deg": null, "confidence": 0.21 }
  ],
  "exercise": null | {
    "exercise_id": "biceps_curl",
    "selection_id": 7,
    "side": "right",
    "sides_used": ["right"],
    "phase": "waiting_for_start | ready | moving | at_target | returning",
    "reps": 3,
    "signal_deg": 97.4,
    "progress": 0.83,
    "hold_ms": 0,
    "last_event": null | {
      "seq": 5, "kind": "rep_completed | target_not_reached | hold_too_short | too_fast | timed_out | tracking_lost",
      "timestamp_ms": 98760000, "peak_deg": 117.0, "duration_ms": 2380, "hold_ms": 610
    },
    "feedback": {
      "message": null | {
        "seq": 12, "key": "rule:upper_arm_still", "text": "Keep your upper arm still by your side.",
        "category": "tracking | correction | cue | positive", "issued_ms": 98761000
      },
      "rules": [ { "id": "upper_arm_still", "state": "inactive | ok | violated | uncertain", "value_deg": 52.0 } ],
      "tracking_ok": true
    }
  },
  "metrics": {
    "capture_fps": 30.0, "inference_fps": 29.6, "inference_ms": 14.2,
    "latency_ms": 21.0, "dropped_frames": 12
  }
}
```

* `x`, `y`: normalized to the **unmirrored** source image (0–1; can be slightly
  outside when a joint is estimated off-frame). Landmark names are anatomical
  (`left_elbow` = the subject's left). Mirroring is a display concern handled by
  the frontend.
* `z`: relative depth, hip-midpoint origin, roughly the same scale as `x`. A
  rough model estimate — not a measured depth.
* `visibility` / `presence`: model scores in 0–1. Not calibrated probabilities.
* `timestamp_ms`: monotonic clock, not wall time.
* Landmarks are rounded to 4 decimals (~1.5 KB JSON per frame).
* `angles`: one entry per definition, every frame. `status` is `ok`,
  `no_person`, `low_visibility`, `out_of_frame`, `degenerate` or `unavailable`;
  `value_deg` (smoothed) and `raw_deg` are `null` unless `ok`. `confidence` is
  the minimum visibility of the three landmarks (null with no person).

### Version history

* **v8**: `StartSession.rule_overrides` (rule id → `min_deg` / `max_deg` /
  `blocks_rep`; unknown ids are rejected with 422); `SessionView.form_rules`
  holds the effective rules for the session.
* **v7**: rule statuses carry `reason` (`angle` | `out_of_plane`); form rules
  have `out_of_plane_limit`.
* **v6**: rep event kinds `form_broken` (with `detail` = rule id) and
  `form_unverified`; rule statuses carry `sustained` and `blocks_rep`; form
  rules have `blocks_rep`; exercise definitions have `guidance`; sessions have
  a `practice` state and a `practice` status (`StartSession.practice`,
  default true).
* **v5**: `session` text messages; session endpoints; `ExerciseSummary.dosage`.
  Text messages must be dispatched on `type` (`status` or `session`).
* **v4**: `ExerciseState.feedback` (current message, per-rule states, tracking
  gate). `ExerciseDefinition.feedback` (see FEEDBACK.md). Message keys are a
  `MessageKey` value, `event:<key>` for rep outcomes, or `rule:<id>`.
* **v3**: `FrameMessage.exercise`, `FrameMessage.angle_space` (the space used
  for that frame: the active exercise's, else the default), exercise REST
  endpoints. `StatusMessage.angle_space` is now the *default* space, and the
  default changed from `world` to `image`. `selection_id` lets clients notice
  a selection made by another client and refetch `/api/exercise/active`.
* **v2**: `FrameMessage.angles`, `StatusMessage.angle_space`,
  `GET /api/angles/definitions`. The frontend refuses to run against a backend
  with a different `protocol_version` and says so.

### Delivery semantics

Latest-wins at every stage: the pipeline processes the newest camera frame,
and each WebSocket client is sent only the newest packet it has not yet seen.
A slow client skips frames rather than accumulating lag.
