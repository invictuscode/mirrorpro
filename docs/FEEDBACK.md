# Real-time feedback (Phase 4)

Code: `backend/app/feedback/` — `config.py` (per-exercise configuration and the
wording guardrail), `engine.py` (rules and arbitration). Each
`ExerciseTracker` owns one `FeedbackEngine`; its output travels in every frame
as `exercise.feedback` (protocol v4).

Feedback is produced by **explicit, configurable rules and fixed message
text**. No generative model judges movement or writes messages.

## What the system will and will not say

* It reports what the camera *estimated* against targets someone configured.
  It never says a movement is safe, never diagnoses, and never suggests
  changing a clinician's plan.
* All patient-facing text (feedback messages, form-rule messages and
  instructions) passes a guardrail that rejects words implying safety,
  diagnostic or treatment claims (`safe*`, `unsafe`, `diagnos*`, `injur*`,
  `prescri*`, `cure*`, `heal*`, `treat*`). The guardrail is a backstop for
  obvious mistakes, **not** a substitute for clinical review of the wording.
* Live messages are limited to 120 characters so they stay readable from a
  distance.

## Message categories

| Category | Priority | Raised when | Example (default text) |
|---|---|---|---|
| `tracking` | 3 | The angle driving the rep count has been unreliable for `tracking_grace_ms` | "Your movement could not be tracked clearly. Adjust your position." / "Step into view of the camera." |
| `correction` | 2 | A form rule has been violated for its `sustain_ms`; or a rep was not counted (target not reached, hold too short, too fast, a blocking rule broken) | "Keep your upper arm still by your side." |
| `cue` | 1 | At the target with a required hold; or not back at the start for `start_prompt_after_ms` | "Hold this position briefly." / "Return to the starting position." |
| `positive` | 1 | A rep was counted | "Repetition completed." |

## Uncertainty is not a deviation

* While the driving angle is unreliable, **no** corrections or cues are
  issued, starting with the first unreliable frame. After
  `tracking_grace_ms`, the tracking message is shown instead. Short blips the
  rep counter tolerates never produce a tracking message.
* Each form rule checks its own joint. If that joint is not reliably tracked,
  the rule's state is `uncertain` and it makes no judgement, even if it was
  violated a moment earlier.
* The tracking category has a neutral grey style in the UI so that
  uncertainty is not shown as an error or a correction.

## Arbitration: avoiding contradictory or rapid-fire messages

At most one message is shown at a time. Each frame, candidates are ranked by
priority (ties are broken by configuration order) and the first *allowed* one
is issued:

| Guard | Default | Effect |
|---|---|---|
| `cooldown_ms` | 2500 | Minimum gap between any two corrections/cues, so different instructions cannot follow each other rapidly |
| `repeat_cooldown_ms` | 8000 | Minimum gap before the same correction/cue repeats |
| `min_display_ms` | 1500 | A message cannot be replaced by one of equal or lower priority sooner than this |
| `display_ms` | 3000 | How long a message stays up |
| Event consumption | — | Each rep outcome is considered once, on the frame it occurs; one that loses arbitration is dropped, never shown late |
| Condition cues | — | "Hold" and "Return to start" disappear as soon as their condition ends |

Tracking messages bypass the cooldowns (they always take over immediately)
and disappear as soon as tracking recovers.

## Form rules

```jsonc
"feedback": {
  "messages": { "target_not_reached": "Bend your elbow a little further." },
  "form_rules": [{
    "id": "upper_arm_still",
    "joint": "shoulder_elevation",
    "side": "signal",              // signal | left | right | both
    "phases": ["moving", "at_target", "returning"],
    "max_deg": 40,                 // and/or min_deg
    "sustain_ms": 500,
    "message": "Keep your upper arm still by your side."
  }],
  "cooldown_ms": 2500, "repeat_cooldown_ms": 8000,
  "display_ms": 3000, "min_display_ms": 1500,
  "tracking_grace_ms": 700, "start_prompt_after_ms": 4000
}
```

`side: "signal"` checks the side(s) currently driving the rep count. For a
single-side exercise, that is the selected side even while it is momentarily
untracked: the rule reports `uncertain` rather than switching to the other
arm. `both` checks every reliably tracked side and uses the worst value.

The demo rules are:

| Exercise | Rule | Bound |
|---|---|---|
| Standing arm raise | elbows straight (both) | elbow flexion ≤ 35° while moving / at target |
| Biceps curl | upper arm still | shoulder elevation ≤ 40° while moving / at target / returning |
| Sit to stand | stand tall | hip flexion ≤ 30° at target |

Like the thresholds, these bounds are **illustrative**. A therapist must set
real values. Message overrides use the keys in
`app/feedback/config.py:MessageKey`.

## Blocking rules: steady joints that cannot be bypassed

A form rule with `"blocks_rep": true` decides whether a repetition counts, not
only what is said:

* Some movement is normal, so a rule has an **allowance** (its `min_deg` /
  `max_deg`; the presets allow elbows up to 45°) and a brief wobble outside it
  does not fail the rep. The rep ends as `form_broken` and is **not counted**
  only if the rule is broken for at least `sustain_ms` **and** at least 20% of
  the repetition's duration, **in total**. Broken time is added up across the
  rep, so tracking flicker that interrupts the violation cannot hide it. The patient sees "Not counted: <the rule's
  message>".
* If the rule's joint cannot be checked (not reliably tracked) for more than
  50% of the rep, the rep ends as `form_unverified` and is **not counted**.
  Hiding a joint from the camera is therefore not a way around the rule. The
  message is shown in the neutral "tracking" style, because it is uncertainty,
  not a movement error.
* **Bending toward or away from the camera is caught too.** A 2D camera
  cannot see an elbow bend toward it: in testing, a 90° bend toward the
  camera read as about 10°, inside an "elbows straight" rule. When that
  happens the forearm *looks shorter*, so each rule also compares the
  on-screen distal/proximal segment length ratio with its value in the start
  position. Below `out_of_plane_limit` (default 0.45 of that value, i.e. roughly a
  60°+ bend; only clearly visible landmarks, visibility ≥ 0.65, are used), the joint
  is treated as violated, with reason `out_of_plane`. Turning the whole limb
  toward the camera shrinks both segments equally and is not flagged. The
  start-position baseline is learned per person and per camera setup.
* Rules without `blocks_rep` remain reminders: they produce feedback, and the
  rep still counts.

Example: in *Jumping jack arms*, `elbows_straight` blocks (allowance 45°), so
a repetition done by bending the elbows (which would otherwise still satisfy
the shoulder angle) does not count, while naturally soft elbows do. Upper-body
exercises only check upper-body joints: the legs do not need to be in view.
Allowances, and whether a rule blocks, can be changed per session on the
settings screen (`StartSession.rule_overrides`). Rules are evaluated
once per frame (`app/feedback/rules.py`) and shared by the counter and the
feedback engine, so the counter and the messages never disagree.

The "Not counted: …" message concludes the rule's own live correction, so it
may follow that correction immediately, bypassing the cooldown. It is the
same instruction, not a new one.

Which joints must stay steady, and whether each one blocks, is the
therapist's decision. Demonstration analysis suggests steady joints with
blocking on by default, only in the same body region as the moving joint
(see CUSTOM_EXERCISES.md). The practice repetition ends after any full
attempt, counted or not, so a strict rule cannot trap the patient in practice.

## Coaching cues

| Cue | When |
|---|---|
| "Keep going toward the target." | Moving, but no progress for `stall_ms` (1.5 s) at < 75% of the way |
| "Almost there. A little further." | Same, at ≥ 75% of the way |
| "Hold this position briefly." | At the target while a hold is still required |
| "Good. Now return slowly to the start." | At the target with the hold done, for `return_cue_after_ms` (0.7 s) |
| "Return to the starting position." | Not back in the start position for `start_prompt_after_ms` |

All cues are condition cues: they disappear as soon as the situation
changes, and they are subject to the normal cooldowns.

## Developer view

The dev console's *Feedback rules* panel shows each rule's live state
(`inactive`, `ok`, `violated`, `uncertain`) and value, whether judgements are
currently paused for tracking, and a log of recent messages.

## Known limitations

* Rules check one angle against fixed bounds. They cannot yet express
  relationships (e.g. "left and right within 15° of each other") or speed and
  smoothness.
* Message text is edited in the JSON definitions; a therapist editing UI comes
  with the therapist interface (Phase 6).
* No audio or spoken feedback yet. The banner is announced to screen readers
  via `aria-live="polite"`.
* Timing defaults are starting points and have not been user-tested with
  patients.
