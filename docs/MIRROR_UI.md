# Smart-mirror interface and sessions (Phase 5)

## Two screens

| URL | For | Contents |
|---|---|---|
| `http://127.0.0.1:5173/` (`#/`) | The patient, on the mirror display | Exercise picker → settings → session → summary |
| `http://127.0.0.1:5173/#/dev` | Development on the MacBook | Diagnostics: FPS, landmark visibility, all angles, rule states, manual exercise selection |

Both use the same backend stream; the mirror shows only what a patient needs.

## Design decisions

* **Pure black background.** Behind a two-way mirror, black pixels read as
  the mirror surface and only bright content shows through. The layout is
  mostly black with high-contrast text.
* **Readable at a distance.** Type is sized in `vmin`. The rep count is about
  17% of the shorter screen side, and feedback about 4%.
* **Portrait and landscape.** Mirrors are usually portrait. The layout stacks
  in portrait (camera view, then count, angle and feedback) and goes
  side-by-side in landscape.
* **Counter first, camera on request.** A session opens with the counter
  filling the screen. The **Camera** button (`C`) splits the screen: the
  camera with all body points on one side, the counter on the other (stacked
  in portrait). Pressing it again hides the camera. Both choices are
  remembered per device.
* **Camera style** (`D` or the top-right button): *Video* (camera image +
  points, for a laptop or TV) or *Points only* (on black, for a two-way
  mirror where the reflection replaces the video).
* **One message at a time.** The feedback engine (Phase 4) decides what to
  say. While tracking is unreliable, the phase line says "Waiting for clear
  tracking" instead of a movement instruction, so the two never contradict
  each other.
* **Only relevant angles.** The canvas labels only the exercise's
  `display_angles` on the working side. The side panel shows the angle
  driving the count, marked "Estimated by camera".
* **Fail visibly.** A rendering error shows a readable "Something went wrong"
  screen with a Reload button, never a blank (black, i.e. "off-looking")
  screen. A frontend/backend version mismatch shows "Update needed".

## Practice repetition and movement guides

Each session starts with **one practice repetition** (it can be turned off on
the settings screen, or skipped with *Skip practice* / `N`). It never counts
and is not in the summary. During practice:

* The camera view is always shown, with **movement guides** for the joint that
  drives the count, on each side in use:
  * a bright green **target** line: where the moving segment should reach,
    at the target angle and on the side the person is moving;
  * a dashed **start** line: where to return to;
  * a blue **arc arrow** at the joint: which way to move now (toward the
    target, or back toward the start), turning into a **hold** ring while a
    hold is required;
  * **rings on the joints that must stay steady**: teal when within range,
    red when outside, dashed grey when not visible.
* A step list (Start → Move → Hold → Return) highlights the current step,
  using the exercise's own cue text, followed by the key points and tempo.

After one full practice attempt (counted or not; the outcome is shown), set 1 starts with a fresh
counter. Outside practice, the guides can be shown with **Guides** / `G` (the
choice is remembered per device). The joint rings are shown whenever the
camera is.

The guides are drawn in the same aspect-corrected 2D image space the angles
are measured in, from the live landmarks
(`frontend/src/services/guideGeometry.ts`, unit-tested).

## Keep in mind panel

During a session, the panel lists each form rule with a live status (✓ OK,
! check this, ? not visible, · checked during the movement) and the camera's
current reading ("Now 12° (allowed ≤ 45°)", or "Bent toward or away from the
camera"). It marks rules that block repetitions as "Required for the
repetition to count", and lists the exercise's key points.

## Controls

| Action | Button | Key |
|---|---|---|
| Pause / resume | Pause / Resume | `Space` |
| Finish the set now / skip rest | Finish set / Skip rest | `N` |
| End the session | End session (press twice within 4 s) | `E` `E` |
| Show / hide camera (split screen) | Camera / Hide camera | `C` |
| Show / hide movement guides | Guides / Hide guides | `G` |
| Skip the practice repetition | Skip practice | `N` |
| Video or points only | (top right) | `D` |
| Fullscreen | Fullscreen | `F` |

## Settings before starting

Pressing **Start** on an exercise opens a settings screen with its defaults:

| Setting | Meaning (shown in plain words) |
|---|---|
| Side | Which side to track (one-sided exercises only) |
| Starting angle | e.g. "Start position: elbow flexion at or below 35°" |
| Target angle | e.g. "A repetition counts when elbow flexion reaches at least 110°" |
| Hold at target | Seconds to stay at the target for the rep to count |
| Sets, repetitions per set, rest between sets | The session plan |
| Form checks | Each form rule's allowance ("Allowed up to 45°") and whether it is *Required for the repetition to count* or a reminder only |

**Begin with defaults** starts immediately. **Begin with these settings**
is enabled once something has changed and the values are valid. The screen
checks the same rules as the backend (target on the correct side of the
start, more than 2 × hysteresis apart, values in range) and explains any
problem before you begin. Changed thresholds are sent as overrides (form checks as `rule_overrides`), apply to
every set, are shown on the session screen ("Target ≥ 90° · hold 1 s"), and
are reused by *Repeat session*. When an exercise's defaults are demo values,
the screen says so and asks for the therapist's values.

Starting a session starts the camera if needed. If the camera fails, the
session is not started and the error is shown.

## Sessions (backend)

Code: `backend/app/sessions/manager.py`, `backend/app/api/sessions.py`,
`backend/app/schemas/session.py`. In memory; persistence is Phase 7.

```
ACTIVE ──set reaches reps──▶ RESTING ──rest ends / advance──▶ ACTIVE (next set)
  │  └── last set done ──▶ COMPLETED
  ├─ pause ─▶ PAUSED ─ resume ─▶ back to ACTIVE or RESTING
  └─ end (from any in-progress state) ─▶ ENDED
```

* **Plan:** `sets`, `reps_per_set` and `rest_s` default to the exercise's
  dosage (else 1 set × 10 reps) and 30 s rest; they can be set when starting.
* **Each set** gets a fresh `ExerciseTracker`, so its count starts at 0. While
  resting or paused, no tracker is installed, so **nothing is counted**.
  Resuming re-installs the same tracker, so the set's count is kept.
* **Timing:** `active_ms` excludes rest and pauses; `rest_ms` is time resting;
  `elapsed_ms` is wall time since start. A rest that ends while nothing is
  checking still begins the next set at the scheduled moment (a timer also
  pushes the change to clients).
* **Exclusive:** while a session is in progress, manual exercise selection
  (`PUT/DELETE /api/exercise/active`) returns 409, so the dev console cannot
  hijack the session's counter.
* **Summary** (when completed or ended): total reps, sets completed (reaching
  the target) and per-set records, active time, uncounted attempts by reason,
  furthest angle per counted rep (min/max/mean), mean rep time, feedback
  counts by category, and the three most frequent corrections. All of these
  are camera estimates; the summary screen says so.

### API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/session` | Current session or `null` |
| POST | `/api/session` | `{exercise_id, side?, overrides?, sets?, reps_per_set?, rest_s?}`. 404 unknown exercise; 409 one already in progress; 422 invalid. |
| POST | `/api/session/pause` · `/resume` · `/advance` · `/end` | 409 if not allowed now (e.g. `advance` while paused) |
| DELETE | `/api/session` | Dismiss a completed/ended session (409 if in progress) |

The WebSocket pushes `{"type": "session", "session": SessionView | null}` on
every change, including on connect. Between pushes, the UI extrapolates the
running timer and the rest countdown locally.

## Known limitations

* One session at a time and no history yet: Phase 7 stores sessions in
  SQLite.
* Keyboard and mouse only. A hands-free start/stop (e.g. a gesture or a
  remote) would suit a mirror better and is not implemented.
* No audio cues.
* Tested in Chromium (the in-app browser pane) at 1280×800 and 720×1280 with
  a synthetic person. Not yet tested on a real mirror display or a Raspberry
  Pi's browser.
