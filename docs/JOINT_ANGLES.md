# Joint-angle estimates (Phase 2)

> These are **experimental computer-vision estimates**, not goniometer or
> motion-capture measurements. They have not been validated against a
> clinical reference and must not be used for diagnosis or to change a
> treatment plan.

Code: `backend/app/biomechanics/` (no camera, model or UI dependencies).

## Definitions

Each angle is the angle at a *vertex* landmark between a *proximal* and a
*distal* landmark, computed as `atan2(|BA × BC|, BA · BC)`. Sides are
anatomical (the subject's left), regardless of mirrored display.

| id | Landmarks (proximal–vertex–distal) | Reported value | ~0° when |
|---|---|---|---|
| `left/right_elbow_flexion` | shoulder–elbow–wrist | 180° − included | arm straight |
| `left/right_shoulder_elevation` | hip–shoulder–elbow | included | arm at side (~180° overhead) |
| `left/right_hip_flexion` | shoulder–hip–knee | 180° − included | standing upright |
| `left/right_knee_flexion` | hip–knee–ankle | 180° − included | leg straight |

Caveats specific to each:

* **Shoulder elevation** is the arm-to-trunk angle. It does not separate
  flexion (forward) from abduction (sideways), and the trunk line uses the
  shoulder landmark, which itself moves when the shoulder shrugs.
* **Hip flexion** uses the shoulder as the proximal point, so trunk lean is
  included. It is a "trunk–thigh angle", not an isolated hip-joint angle.
* Omitted on purpose: wrist, ankle, neck and trunk rotation. MediaPipe's hand,
  foot and head points are too coarse for a meaningful single-camera estimate.

`GET /api/angles/definitions` returns these definitions for the UI.

## Coordinate space (`PTM_ANGLE_SPACE`)

| | `world` | `image` (default) |
|---|---|---|
| Source | MediaPipe *world landmarks*: 3D, hip-centred, approx. metres | 2D image landmarks scaled to pixels (aspect-corrected) |
| Strength | Captures bending toward/away from the camera | No reliance on model-guessed depth |
| Weakness | Depth (z) is **inferred by the model from a single image**, not measured | Movement out of the image plane is foreshortened: a curl seen head-on can read near 0° |

Neither is ground truth. Choose per exercise once camera placement is defined
(Phase 3), and compare both against a goniometer before relying on either.

## Reliability gating

An angle is reported only if all three landmarks:

1. have visibility ≥ `PTM_ANGLE_MIN_VISIBILITY` (default 0.5),
2. lie inside the image (2% margin), and
3. form segments longer than a minimum (3 cm world / 1% of image diagonal).

Otherwise `value_deg` is `null` and `status` says why (`low_visibility`,
`out_of_frame`, `degenerate`, `no_person`, `unavailable`). The UI shows the
reason instead of a number. A previous value is **never** carried forward.

Visibility is a model score, not a calibrated probability, so passing the
gate means "the model is fairly confident", not "the value is accurate".

## Smoothing

`PTM_ANGLE_FILTER` = `one_euro` (default), `ema`, or `none`.

* **One Euro** (Casiez et al., 2012) adapts its cutoff to speed: strong
  smoothing at rest, less lag during movement. Tune with
  `PTM_ANGLE_FILTER_MIN_CUTOFF_HZ` (lower = smoother at rest, default 1.0) and
  `PTM_ANGLE_FILTER_BETA` (higher = less lag when moving, default 0.02 per °/s).
* **EMA**: `PTM_ANGLE_FILTER_EMA_ALPHA` (default 0.3).
* If an angle is invalid for longer than `PTM_ANGLE_MAX_GAP_MS` (default
  500 ms), its filter restarts so old values are not blended into new ones.

Both `value_deg` (smoothed) and `raw_deg` (this frame) are sent; the panel
tooltip shows the raw value. All filter defaults are reasonable starting points,
not tuned values.

## Limitations of single-camera angle estimation

* **Projection / foreshortening.** A 2D camera cannot see motion toward or
  away from it. 3D world landmarks reduce this only by *guessing* depth.
* **Model error.** Landmarks are joint-centre estimates from appearance. Loose
  clothing, occlusion (e.g. arm in front of the body), unusual body shapes,
  assistive devices and poor lighting all shift them.
* **Landmarks ≠ anatomy.** MediaPipe's "hip" and "shoulder" points are not
  anatomical joint centres or bony landmarks a clinician would palpate.
* **Camera placement matters.** Height, distance and angle relative to the
  movement plane change readings. Each exercise will need a defined setup.
* **Temporal effects.** Smoothing adds lag; fast movements can be
  under-estimated at their peak.
* **No validation yet.** Accuracy versus a goniometer is unknown. A sensible
  next step is a small comparison study (a few joints, a few positions,
  repeated) before any targets are set from these numbers.
