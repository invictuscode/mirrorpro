# Exercises and repetition counting (Phase 3)

Code: `backend/app/exercises/` — `schema.py` (definition model), `library.py`
(loader), `rep_counter.py` (state machine), `tracker.py` (runs one exercise
on per-frame angles). Presets: `backend/app/exercises/presets/*.json`.

## Clinical content policy

* Shipped presets are **demonstrations**. `clinical_review.status` is
  `unreviewed_demo`; the UI shows a warning whenever one is selected.
* Their thresholds and dosage are **illustrative values chosen for software
  testing**, not clinical targets. No range of motion is appropriate for
  everyone.
* `safety_notes` are intentionally empty. They must be written or approved by
  a qualified professional. A definition can only be `approved` if
  `reviewed_by` names the reviewer (enforced by validation).
* Rep-event messages in the dev panel ("Not counted: target angle not
  reached") explain the counter's decision. Patient-facing feedback is
  configured per exercise; see FEEDBACK.md.
* Instructions and feedback text pass a wording guardrail that rejects
  safety, diagnostic and treatment claims.

## Presets

| id | View | Counting signal | Start → target (demo) | Why this view |
|---|---|---|---|---|
| `standing_arm_raise` | front | mean of visible shoulder elevations | 30° → 120° | Arms move in the plane facing the camera |
| `biceps_curl` | side | one elbow's flexion (side chosen at start) | 35° → 110° | A curl seen from the front is foreshortened in 2D |
| `sit_to_stand` | side | mean of visible knee flexions | 65° → 20° (decreasing) | Knee bend is in the sagittal plane; far leg may be hidden, so whichever side is visible is used |
| `mini_squat` | side | mean of visible knee flexions | 15° → 50° | Small knee bend from standing |
| `seated_knee_extension` | side | one knee's flexion | 70° → 20° (decreasing), 1 s hold | Knee straightens from sitting; demonstrates a required hold |
| `shoulder_flexion` | side | one shoulder's elevation | 30° → 120° | Forward raise is in the sagittal plane, so side-on (the front-view arm raise covers sideways raises) |
| `standing_march` | side | one hip's flexion | 20° → 60° | Knee lift; hip flexion here includes trunk lean (see JOINT_ANGLES.md). No form rule: without knowing the standing leg, no meaningful single-camera check was defined |
| `wall_pushup` | side | mean of visible elbow flexions | 25° → 80° | Elbow bend side-on; far arm is often hidden |
| `jumping_jack_arms` | front | mean of visible shoulder elevations | 30° → 140° | Arm sweep of a jumping jack without the jump; elbows must stay fairly straight (≤ 45°, blocks); legs are not checked |

**Rules that block repetitions** (a rep that breaks them is not counted; see
FEEDBACK.md): arm raise and jumping jack arms, elbows straight; jumping jack
arms, knees straight; biceps curl, upper arm still; shoulder flexion, elbow
straight; seated knee extension, stay seated. The other rules are reminders.

### Guidance

Every preset has a `guidance` block, shown on the settings screen, during the
practice repetition, and in the session's "Keep in mind" panel:

```jsonc
"guidance": {
  "setup": ["Stand facing the screen ...", "Feet together, ..."],
  "cues": { "start": "...", "move": "... toward the green line ...", "hold": "...", "back": "..." },
  "key_points": ["Move both arms together."],
  "tempo": "About 2 seconds up and 2 seconds down."
}
```

All guidance text passes the same wording guardrail as feedback (no safety,
diagnostic or treatment claims); cues are limited to 120 characters.
Key points do not repeat blocking rules, because the UI lists those
automatically as "Required for the repetition to count".

All use `angle_space: "image"`. When an exercise is active, the whole
pipeline computes angles in that exercise's space, so the angles on screen are
always the ones driving the count.

## Definition schema (abridged)

```jsonc
{
  "id": "biceps_curl",               // [a-z0-9_]
  "version": 1,                      // bump when thresholds/instructions change
  "name": "Biceps curl",
  "description": "...",
  "instructions": ["..."],
  "camera": { "view": "side", "angle_space": "image", "guidance": "..." },
  "relevant_landmarks": ["right_shoulder", "..."],   // validated names
  "display_angles": ["elbow_flexion"],               // validated joint families
  "signal": { "joint": "elbow_flexion", "side_mode": "single", "default_side": "right" },
  "rep_counting": {
    "start_deg": 35, "target_deg": 110,   // direction inferred
    "hysteresis_deg": 8,                   // margin to *leave* a zone
    "confirm_ms": 100,                     // zone change must persist this long
    "min_hold_ms": 0,                      // time required in the target zone
    "min_rep_ms": 800, "max_rep_ms": 15000,
    "max_signal_gap_ms": 750               // longer tracking loss abandons the rep
  },
  "dosage": { "reps_per_set": 10, "sets": 2 },
  "feedback": { "messages": { }, "form_rules": [ ] },   // see FEEDBACK.md
  "safety_notes": [],
  "clinical_review": { "status": "unreviewed_demo", "reviewed_by": null, "note": "..." },
  "reference_demonstration": null        // Phase 6
}
```

Validation rejects: unknown joints or landmarks, `single` side mode without a
default side, start/target closer than 2 × hysteresis, `min_rep_ms ≥
max_rep_ms`, `approved` without a reviewer, and unknown fields. A bad file
stops the backend at startup with the file name, rather than being skipped.

To add an exercise, drop a JSON file in `presets/` (or point
`PTM_EXERCISE_DIR` at your own directory) and restart the backend.

## Repetition state machine

```
WAITING_FOR_START ─in start zone─▶ READY ─leaves start zone─▶ MOVING ─reaches target─▶ AT_TARGET
       ▲                             ▲                          │                         │ leaves target
       │ timeout / tracking lost     └──── back to start ───────┘                         ▼ (after min hold)
       └──────────────────────────── (not counted)              READY ◀── counted ── RETURNING
```

A rep counts only after the full sequence start → target (held, if required)
→ start. Defences against false counts:

| Problem | Defence |
|---|---|
| Jitter on a threshold | Enter a zone at the threshold, leave only past threshold ± hysteresis |
| One-frame spikes | A phase change must be observed continuously for `confirm_ms` |
| Brief landmark loss | Gaps ≤ `max_signal_gap_ms` freeze the machine; pending changes are cancelled |
| Long landmark loss | Rep abandoned (`tracking_lost`); must return to start before the next |
| Starting mid-movement | Counting begins only after the start zone is seen |
| Too quick / too slow | `too_fast` (< `min_rep_ms`) and `timed_out` (> `max_rep_ms`) are not counted |
| Partial movement | `target_not_reached`, with the furthest angle reached |
| Target reached, not held | `hold_too_short` (also the final outcome if the person then returns to start) |

Every attempt ends in a `RepEvent` (`seq`, `kind`, `peak_deg`, `duration_ms`,
`hold_ms`) so the UI, and later the session log, can explain each decision.

## Therapist adjustments

`PUT /api/exercise/active` accepts `overrides` for `start_deg`, `target_deg`
and `min_hold_ms`. The merged config is re-validated; overrides that bring the
thresholds too close or reverse the movement direction are rejected with a
422 and a readable reason. The developer console exposes these fields when
choosing an exercise. Per-patient persistence of overrides is Phase 7.

## Known limitations

* Counting is only as good as the angle estimate (see JOINT_ANGLES.md). Camera
  placement must match the exercise's declared view.
* One driving angle per exercise. Secondary criteria (e.g. "elbow stays
  straight while the shoulder raises") are feedback form rules; they do not
  affect counting.
* Sets, rest periods and session timing are Phase 5; the counter tracks a
  running rep count until reset.
* Thresholds are fixed per selection; there is no adaptation to the patient.
