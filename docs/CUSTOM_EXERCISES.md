# Custom exercises from a demonstration (Phase 6)

A therapist demonstrates a movement; the system suggests parameters; the
therapist reviews, edits and approves. **Nothing reaches patients until a
named therapist approves it.**

Therapist workspace: `http://127.0.0.1:5173/#/therapist` (also linked from the
developer console).

> **No sign-in yet.** The workspace is acceptable only while the backend
> listens on `127.0.0.1` (the default). Authentication and authorisation are
> required before any networked deployment.

## Workflow

1. **Describe:** name, description, instructions (one step per line), camera
   view and placement guidance. Choose the view in which the movement crosses
   the camera, not one where it moves toward it.
2. **Demonstrate**, either way:
   * **Record with the camera:** a 3-second countdown, then the tracking
     pipeline records the per-frame *joint angles* (maximum 60 s). No frames
     are retained.
   * **Upload a video** (MP4/H.264 recommended, up to 2 min / 300 MB): it is
     processed on this computer with the same model and angle analyzer, then
     **deleted immediately**, whether processing succeeded or not.
3. **Review the analysis:** a chart of the driving angle with detected
   repetitions and the suggested thresholds, ranked joint candidates, detected
   repetitions (furthest angle, duration, time near the end position),
   optional form reminders, and warnings.
4. **Edit the parameters:** every value is editable. The chart's threshold
   lines follow the edits.
5. **Save as draft**, optionally consenting to store the demonstration's angle
   data. The default is not to.
6. **Approve:** reviewer name + attestation. Approval publishes the exercise
   to the mirror with `clinical_review.status = "approved"` and
   `reviewed_by = <name>`.

## How suggestions are derived (`backend/app/authoring/analysis.py`)

| Step | Method |
|---|---|
| Driving joint | For each joint family and side: tracked fraction and robust range (5th–95th percentile). Joints tracked in < 50% of frames or moving < 15° are ignored. If both sides move (smaller range ≥ 60% of the larger) → "both sides"; otherwise the more-moving side. Ranked by range × tracked fraction. |
| Gaps | Tracking gaps ≤ 500 ms are interpolated; longer gaps split repetitions. |
| Start position | The extreme nearest to where the recording begins **and** ends (0.6 s windows at each end). If the ends disagree or sit mid-range → `ambiguous_direction` warning; the therapist sets *low end / high end*. |
| Repetitions | Normalised hysteresis (enter ≥ 70%, leave ≤ 30% of the range) on a smoothed signal, so noise cannot add reps. Hold = time within 10% of the rep's peak. |
| Start threshold | rest level + 25% of the movement span |
| Target threshold | typical (median) peak − 15% of the span. Deliberately short of the demonstration, which is usually fuller than a patient needs. |
| Hysteresis | 8% of the span, clamped to 4–10° |
| Hold | 80% of the median demonstrated hold, if that hold is ≥ 0.6 s; otherwise none |
| Rep timing | minimum = ½ of the shortest rep (≥ 0.4 s); maximum = 3 × the longest rep (5–60 s) |
| Steady joints | Every other joint that stayed within a < 25° range during the reps (and was tracked ≥ 60% of the time; real 2D estimates of a held-straight limb jitter by 10–20° during fast movement) must stay steady for the patient too, so the movement cannot be imitated with another joint. Each becomes a rule that is **on and blocks repetitions by default**, allowing the demonstrated 5th–95th percentile ± 15°. The wording depends on the joint and how it was held (e.g. an elbow held near 0° gives "Keep your elbows straight."). The therapist can untick any rule, or make it a reminder only. Only joints in the same body region as the driving joint are suggested (upper body: shoulders and elbows; lower body: hips and knees), so an arm exercise never requires the legs to be in view. A joint that moved during the demonstration is not suggested; the system will not require what the demonstrator did not do. |

Every suggestion is validated as a real exercise configuration. If none is
possible (e.g. the movement was too small), no thresholds are suggested, and
the analysis says why instead of inventing values.

### Warnings

`single_demonstration` (always), `ambiguous_joint`, `ambiguous_direction`,
`low_tracking` (< 80% tracked), `few_reps` (< 2), `inconsistent_peaks`
(spread > 20°), `inconsistent_timing` (> 2× variation), `small_movement`
(< 25°), `not_starting_at_rest`, `no_movement`, `no_valid_thresholds`.

Therapists can also **add a joint that must stay steady by hand** in the
parameter editor ("Add a joint that must stay steady"). It starts as held
straight (≤ 45°), checked through the whole movement, blocking, with the
out-of-plane check on. Use this when the demonstration did not keep the joint
still enough for it to be suggested.

## Versioning, approval and patients

* Drafts carry `clinical_review.status = "draft"`. The exercise library
  refuses drafts, so a draft can never be started on the mirror.
* Approval requires a reviewer name **and** an attestation; the backend
  re-validates the full definition (the same schema and wording guardrail as
  presets).
* Editing an approved exercise creates the next version as a draft. Patients
  keep the last approved version until the new one is approved.
* The UI disables *Approve* while there are unsaved edits, because approval
  applies to the saved version.
* **Archive** removes an exercise from the mirror. Exercises that have been
  offered to patients cannot be deleted, only archived.

## Data stored

Location: `data/custom_exercises/` (git-ignored; set with `PTM_DATA_DIR`).

| File | When | Contents |
|---|---|---|
| `custom_<slug>_<id>.json` | always | The edited fields, status, version, the approved definition, and demonstration *metadata* (source, duration, frame count, whether angle data was stored) |
| `custom_<…>.<demo_id>.angles.json` | **only with consent** | Per-frame joint angles from the demonstration |

Never stored: video, images, landmarks, or anything identifying the
demonstrator. Unconsented demonstrations live only in memory (the 8 most
recent), and are lost on restart.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/demonstrations/live` | Recording status |
| POST | `/api/demonstrations/live/start` · `/stop` · `/cancel` | 409 if the camera is off, a session is running, or already recording; 422 if too short or no person |
| POST | `/api/demonstrations/upload?angle_space=image` | Raw video body; 413 if > 300 MB; 422 if unreadable, too long, or no person |
| POST | `/api/demonstrations/{demo_id}/analyze` | `{joint?, side_mode?, side?, start_position?: "low"|"high"}` → analysis |
| GET / POST | `/api/custom-exercises` | List / create a draft `{fields, demo_id?, store_angle_data}` |
| GET / PUT | `/api/custom-exercises/{id}` | Read / edit (editing an approved one creates a new draft version) |
| POST | `/api/custom-exercises/{id}/approve` | `{reviewer, attestation}` |
| POST | `/api/custom-exercises/{id}/archive` | |
| DELETE | `/api/custom-exercises/{id}` | Drafts / archived only |

## Designed for later

* **Multiple demonstrations:** `demonstrations` is a list; combining several
  demonstrations into one suggestion is a natural extension.
* **Alternative views / patient abilities:** definitions are versioned and
  independent of any video. Per-patient overrides arrive with plans (Phase 7).
* **Assigning to a patient's plan:** Phase 7.

## Known limitations

* One driving angle, using the four joint families tracked today.
* Suggestions are heuristics on a single demonstration; they are not
  validated against clinical measurement.
* Uploaded-video support depends on OpenCV's codecs on this machine; some
  phone formats (e.g. HEVC `.mov`) may not open.
* Analysis uses the smoothed angles the pipeline produces (live) or a fresh
  analyzer (uploads), so the two paths can differ slightly for the same
  movement.
