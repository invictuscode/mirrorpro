"""Turn a demonstration's angle series into *candidate* exercise parameters.

Everything here is a suggestion for a therapist to review. One demonstration
contains measurement noise, camera-angle effects and the demonstrator's own
movement style, so the output deliberately includes warnings and ranked
alternatives rather than a single "correct" answer.

Pure functions over numpy arrays; no camera, model or storage access.
"""

from __future__ import annotations

import math
import statistics
import warnings

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import ValidationError

from app.authoring.series import AngleSeries
from app.biomechanics.joints import JOINT_ANGLES
from app.exercises.phases import RepPhase
from app.exercises.schema import RepCountingConfig, Side, SideMode
from app.feedback.config import FormRule, RuleSide
from app.schemas.authoring import (
    AnalysisResult,
    AnalysisWarning,
    ChartSeries,
    DetectedRep,
    JointCandidate,
    SuggestedRule,
)

JOINTS: tuple[str, ...] = tuple(dict.fromkeys(d.joint for d in JOINT_ANGLES))

MIN_VALID_FRACTION = 0.5  # below this a joint is not considered at all
MIN_RANGE_DEG = 15.0  # smaller ranges are treated as "did not move"
BILATERAL_RATIO = 0.6  # both sides move if the smaller range is ≥ 60% of the larger
MAX_GAP_MS = 500  # shorter tracking gaps are interpolated; longer ones split reps
ENTER_PEAK, LEAVE_PEAK = 0.7, 0.3  # normalised hysteresis for rep detection
HOLD_BAND = 0.1  # "near the peak" = within 10% of the range
REST_WINDOW_MS = 600  # start/end windows used to identify the start position
CHART_POINTS = 400


# --------------------------------------------------------------- utilities
def _robust_range(x: np.ndarray) -> tuple[float, float, float]:
    """(valid fraction, p5, p95) of an angle array with NaNs."""
    valid = x[~np.isnan(x)]
    if valid.size == 0:
        return 0.0, math.nan, math.nan
    return valid.size / x.size, float(np.percentile(valid, 5)), float(np.percentile(valid, 95))


def _round5(v: float) -> float:
    return float(min(180.0, max(0.0, 5 * round(v / 5))))


def _interpolate_short_gaps(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Fill NaN runs shorter than MAX_GAP_MS linearly; leave long gaps as NaN."""
    y = x.copy()
    nan = np.isnan(y)
    if nan.all() or not nan.any():
        return y
    i = 0
    n = y.size
    while i < n:
        if not nan[i]:
            i += 1
            continue
        j = i
        while j < n and nan[j]:
            j += 1
        if 0 < i and j < n and t[j] - t[i - 1] <= MAX_GAP_MS:
            y[i:j] = np.interp(t[i:j], [t[i - 1], t[j]], [y[i - 1], y[j]])
        i = j
    return y


def _smooth(x: np.ndarray, window: int = 5) -> np.ndarray:
    """Centred moving average that ignores NaNs (NaN where no data)."""
    if x.size < window:
        return x.copy()
    valid = (~np.isnan(x)).astype(float)
    filled = np.where(np.isnan(x), 0.0, x)
    k = np.ones(window)
    num = np.convolve(filled, k, mode="same")
    den = np.convolve(valid, k, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den == 0] = np.nan
    return out


# ---------------------------------------------------------- joint ranking
def rank_joints(series: AngleSeries) -> list[JointCandidate]:
    candidates: list[JointCandidate] = []
    for joint in JOINTS:
        sides = {}
        for side in Side:
            vf, p5, p95 = _robust_range(series.values[f"{side.value}_{joint}"])
            sides[side] = (vf, (p95 - p5) if vf >= MIN_VALID_FRACTION else 0.0)
        (lvf, lr), (rvf, rr) = sides[Side.LEFT], sides[Side.RIGHT]
        big = max(lr, rr)
        if big < MIN_RANGE_DEG:
            continue
        if min(lr, rr) >= BILATERAL_RATIO * big:
            candidates.append(_candidate(joint, SideMode.MEAN_OF_VISIBLE, None, (lr + rr) / 2, max(lvf, rvf)))
        else:
            side = Side.LEFT if lr * lvf >= rr * rvf else Side.RIGHT
            vf, rng = sides[side]
            candidates.append(_candidate(joint, SideMode.SINGLE, side, rng, vf))
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _candidate(joint: str, mode: SideMode, side: Side | None, rng: float, vf: float, scored: bool = True) -> JointCandidate:
    return JointCandidate(
        joint=joint,
        side_mode=mode,
        side=side,
        range_deg=round(rng, 1),
        valid_fraction=round(vf, 3),
        score=round(rng * vf, 1) if scored else 0.0,
    )


def driving_signal(series: AngleSeries, joint: str, side_mode: SideMode, side: Side | None) -> np.ndarray:
    if side_mode is SideMode.SINGLE:
        assert side is not None
        return series.values[f"{side.value}_{joint}"]
    left, right = series.values[f"left_{joint}"], series.values[f"right_{joint}"]
    with warnings.catch_warnings():
        # Frames where neither side is tracked are expected and become NaN.
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.vstack([left, right]), axis=0)


# ------------------------------------------------------------ rep detection
@dataclass(frozen=True)
class RepDetection:
    increasing: bool | None
    lo: float
    hi: float
    reps: list[DetectedRep]
    direction_ambiguous: bool = False


def _window_level(t: np.ndarray, y: np.ndarray, start: bool) -> float | None:
    w = y[t <= t[0] + REST_WINDOW_MS] if start else y[t >= t[-1] - REST_WINDOW_MS]
    return None if w.size == 0 or np.isnan(w).all() else float(np.nanmedian(w))


def detect_reps(t: np.ndarray, x: np.ndarray, increasing: bool | None = None) -> RepDetection:
    """Find repetitions: start position → near the other extreme → back.

    Unless ``increasing`` is given, the start position is the extreme nearest
    to where the demonstration begins and ends. If the two ends disagree, or
    both sit mid-range (e.g. recording began mid-movement), the direction is
    flagged as ambiguous for the therapist to settle. Normalised hysteresis
    thresholds stop noise near a boundary creating extra reps.
    """
    y_raw = _smooth(_interpolate_short_gaps(t, x))
    vf, lo, hi = _robust_range(y_raw)
    if vf == 0 or hi - lo < MIN_RANGE_DEG:
        return RepDetection(None, lo, hi, [])
    ambiguous = False
    if increasing is None:
        ends = (_window_level(t, y_raw, start=True), _window_level(t, y_raw, start=False))
        levels = [(v - lo) / (hi - lo) for v in ends if v is not None] or [0.0]
        mean_level = sum(levels) / len(levels)
        increasing = mean_level <= 0.5
        disagree = len(levels) == 2 and (levels[0] - 0.5) * (levels[1] - 0.5) < 0
        ambiguous = disagree or all(0.3 < v < 0.7 for v in levels)
    y = (y_raw - lo) / (hi - lo) if increasing else (hi - y_raw) / (hi - lo)

    reps: list[DetectedRep] = []
    in_rep = False
    rep_start = 0
    left_rest_at = int(t[0])
    peak_i = 0
    for i in range(y.size):
        v = y[i]
        if np.isnan(v):
            in_rep = False  # long gap: abandon any rep in progress
            continue
        if not in_rep:
            if v <= LEAVE_PEAK:
                left_rest_at = int(t[i])
            elif v >= ENTER_PEAK:
                in_rep, rep_start, peak_i = True, left_rest_at, i
        else:
            if v > y[peak_i]:
                peak_i = i
            if v <= LEAVE_PEAK:
                seg = slice(np.searchsorted(t, rep_start), i + 1)
                near = (y[seg] >= y[peak_i] - HOLD_BAND) & ~np.isnan(y[seg])
                dt = np.diff(t[seg], prepend=t[seg][0])
                reps.append(
                    DetectedRep(
                        start_ms=int(rep_start - t[0]),
                        end_ms=int(t[i] - t[0]),
                        peak_deg=round(float(y_raw[peak_i]), 1),
                        hold_ms=int(dt[near].sum()),
                    )
                )
                in_rep = False
                left_rest_at = int(t[i])
    return RepDetection(increasing, lo, hi, reps, ambiguous)


# -------------------------------------------------------------- suggestions
def _suggest_rep_counting(
    increasing: bool, rest: float, peak: float, reps: list[DetectedRep]
) -> tuple[RepCountingConfig | None, list[AnalysisWarning]]:
    warnings: list[AnalysisWarning] = []
    span = abs(peak - rest)
    sign = 1 if increasing else -1
    start = _round5(rest + sign * 0.25 * span)
    target = _round5(peak - sign * 0.15 * span)
    hysteresis = float(min(10, max(4, round(0.08 * span))))
    holds = [r.hold_ms for r in reps]
    median_hold = statistics.median(holds) if holds else 0
    min_hold = int(250 * round(0.8 * median_hold / 250)) if median_hold >= 600 else 0
    durations = [r.end_ms - r.start_ms for r in reps]
    min_rep = int(max(400, 100 * round(0.5 * min(durations) / 100))) if durations else 600
    max_rep = int(min(60_000, max(5000, 1000 * math.ceil(3 * max(durations) / 1000)))) if durations else 20_000
    try:
        cfg = RepCountingConfig(
            start_deg=start, target_deg=target, hysteresis_deg=hysteresis, min_hold_ms=min_hold,
            min_rep_ms=min_rep, max_rep_ms=max_rep,
        )  # fmt: skip
    except ValidationError:
        warnings.append(
            AnalysisWarning(
                code="no_valid_thresholds",
                message="The movement was too small to place separate start and target thresholds. "
                "Set them manually or record a clearer demonstration.",
            )
        )
        return None, warnings
    return cfg, warnings


# A joint "stayed steady" if its robust range was below this. Real 2D angle
# estimates of a straight limb jitter by 10–20° during fast movement, so a
# tighter limit misses joints a therapist clearly held still.
STEADY_MAX_RANGE_DEG = 25.0
STEADY_MIN_TRACKED = 0.6
STEADY_MARGIN_DEG = 15.0  # allowed deviation beyond what the demonstration showed

# (threshold, wording when held near 0°, wording otherwise); {s} = plural suffix
_STEADY_WORDING: dict[str, tuple[float, str, str]] = {
    "elbow_flexion": (25, "Keep your elbow{s} straight.", "Keep your elbow bend steady."),
    "knee_flexion": (20, "Keep your knee{s} straight.", "Keep your knee bend steady."),
    "shoulder_elevation": (30, "Keep your upper arm{s} by your side.", "Keep your upper arm{s} steady."),
    "hip_flexion": (20, "Keep your body upright.", "Keep your hip position steady."),
}


# Steady joints are only suggested within the moving joint's body region: an
# arm exercise checks arm joints, a leg exercise checks hip and knee. (Legs
# are often out of frame during arm exercises, and are irrelevant to them.)
_REGION: dict[str, str] = {
    "elbow_flexion": "upper",
    "shoulder_elevation": "upper",
    "hip_flexion": "lower",
    "knee_flexion": "lower",
}


def _steady_message(joint: str, typical: float, both_sides: bool) -> str:
    near_zero_below, straight, other = _STEADY_WORDING[joint]
    text = straight if typical < near_zero_below else other
    return text.format(s="s" if both_sides else "")


def _suggest_rules(series: AngleSeries, chosen: JointCandidate, reps: list[DetectedRep]) -> list[SuggestedRule]:
    """Joints that stayed steady during the demonstrated reps must stay steady
    for the patient too: otherwise the movement could be faked with another
    joint (e.g. bending the elbows during an arm raise). Suggested rules are
    therefore on and blocking by default; the therapist can switch any off.

    Each rule is a band around what the demonstration showed (5th–95th
    percentile ± a margin), on the same side(s) as the driving joint."""
    if not reps:
        return []
    t = series.timestamps_ms - series.timestamps_ms[0]
    in_reps = np.zeros(t.size, dtype=bool)
    for r in reps:
        in_reps |= (t >= r.start_ms) & (t <= r.end_ms)
    single = chosen.side_mode is SideMode.SINGLE and chosen.side is not None
    sides = [chosen.side] if single and chosen.side else list(Side)
    out: list[SuggestedRule] = []
    for joint in JOINTS:
        if joint == chosen.joint or _REGION[joint] != _REGION[chosen.joint]:
            continue
        vals = np.concatenate([series.values[f"{s.value}_{joint}"][in_reps] for s in sides])
        vf, p5, p95 = _robust_range(vals)
        if vf < STEADY_MIN_TRACKED or p95 - p5 >= STEADY_MAX_RANGE_DEG:
            continue  # moved, or not tracked well enough to judge
        typical = float(np.nanmedian(vals))
        low = p5 - STEADY_MARGIN_DEG
        high = p95 + STEADY_MARGIN_DEG
        out.append(
            SuggestedRule(
                include=True,
                rule=FormRule(
                    id=f"steady_{joint}",
                    joint=joint,
                    side=RuleSide.SIGNAL,
                    phases=[RepPhase.MOVING, RepPhase.AT_TARGET, RepPhase.RETURNING],
                    min_deg=_round5(low) if low >= 5 else None,
                    max_deg=_round5(high) if high <= 175 else None,
                    sustain_ms=400,
                    message=_steady_message(joint, typical, both_sides=not single),
                    blocks_rep=True,
                ),
                observed_range_deg=(round(p5, 1), round(p95, 1)),
            )
        )
    return out


def _chart(series: AngleSeries, x: np.ndarray) -> ChartSeries:
    step = max(1, math.ceil(x.size / CHART_POINTS))
    t = (series.timestamps_ms - series.timestamps_ms[0])[::step]
    return ChartSeries(t_ms=[int(v) for v in t], deg=[None if np.isnan(v) else round(float(v), 1) for v in x[::step]])


def analyze(
    demo_id: str,
    series: AngleSeries,
    joint: str | None = None,
    side_mode: SideMode | None = None,
    side: Side | None = None,
    start_position: Literal["low", "high"] | None = None,
) -> AnalysisResult:
    warnings: list[AnalysisWarning] = [
        AnalysisWarning(
            code="single_demonstration",
            message="These values come from one demonstration. Review and adjust them for the intended patients before approving.",
        )
    ]
    candidates = rank_joints(series)
    if joint is not None:
        if joint not in JOINTS:
            raise ValueError(f"unknown joint {joint!r}")
        match = next((c for c in candidates if c.joint == joint), None)
        sm = side_mode or (match.side_mode if match else SideMode.SINGLE)
        sd = side if sm is SideMode.SINGLE else None
        if sm is SideMode.SINGLE and sd is None:
            sd = match.side if match and match.side else Side.RIGHT
        vf, p5, p95 = _robust_range(driving_signal(series, joint, sm, sd))
        chosen = _candidate(joint, sm, sd, (p95 - p5) if vf else 0.0, vf, scored=False)
    elif candidates:
        chosen = candidates[0]
        if len(candidates) > 1 and candidates[1].score >= 0.8 * chosen.score:
            warnings.append(
                AnalysisWarning(
                    code="ambiguous_joint",
                    message=f"{candidates[1].joint.replace('_', ' ')} moved almost as much as "
                    f"{chosen.joint.replace('_', ' ')}. Check that the right joint drives the count.",
                )
            )
    else:
        warnings.append(
            AnalysisWarning(
                code="no_movement",
                message="No joint moved clearly enough while being tracked. Check the camera position and record again.",
            )
        )
        return _empty(demo_id, [], None, warnings, None)

    x = driving_signal(series, chosen.joint, chosen.side_mode, chosen.side)
    if chosen.valid_fraction < 0.8:
        warnings.append(
            AnalysisWarning(
                code="low_tracking",
                message=f"The driving angle was reliably tracked in only {chosen.valid_fraction:.0%} of frames. "
                "Suggestions may be unreliable.",
            )
        )
    forced = None if start_position is None else start_position == "low"
    det = detect_reps(series.timestamps_ms, x, forced)
    increasing, lo, hi, reps = det.increasing, det.lo, det.hi, det.reps
    if det.direction_ambiguous:
        warnings.append(
            AnalysisWarning(
                code="ambiguous_direction",
                message="Could not tell whether the start position is at the low or high end of the movement "
                "(the recording may have begun mid-movement). Check the chart and set the start position.",
            )
        )
    if increasing is None:
        warnings.append(
            AnalysisWarning(code="no_movement", message="The selected joint did not move enough to detect repetitions.")
        )
        return _empty(demo_id, candidates, chosen, warnings, _chart(series, x))

    if len(reps) < 2:
        warnings.append(
            AnalysisWarning(
                code="few_reps",
                message=f"Only {len(reps)} repetition{'s' if len(reps) != 1 else ''} detected. "
                "Demonstrate 3–5 repetitions for more reliable suggestions.",
            )
        )
    # Rest level from frames near the start extreme; typical peak from reps.
    y = (x - lo) / (hi - lo) if increasing else (hi - x) / (hi - lo)
    rest_frames = x[(y <= 0.15) & ~np.isnan(x)]
    rest = float(np.median(rest_frames)) if rest_frames.size else (lo if increasing else hi)
    peaks = [r.peak_deg for r in reps]
    peak = float(statistics.median(peaks)) if peaks else (hi if increasing else lo)
    if peaks and len(peaks) >= 2 and max(peaks) - min(peaks) > 20:
        warnings.append(
            AnalysisWarning(
                code="inconsistent_peaks", message=f"Repetition peaks varied from {min(peaks):.0f}° to {max(peaks):.0f}°."
            )
        )
    durations = [r.end_ms - r.start_ms for r in reps]
    if len(durations) >= 2 and max(durations) > 2 * min(durations):
        warnings.append(
            AnalysisWarning(code="inconsistent_timing", message="Repetition durations varied by more than a factor of two.")
        )
    if abs(peak - rest) < 25:
        warnings.append(
            AnalysisWarning(
                code="small_movement",
                message=f"The movement range was small ({abs(peak - rest):.0f}°); estimates are relatively noisy.",
            )
        )
    first_valid = x[~np.isnan(x)][:5]
    if first_valid.size and (abs(float(np.median(first_valid)) - rest) > 0.3 * abs(peak - rest)):
        warnings.append(
            AnalysisWarning(
                code="not_starting_at_rest",
                message="The demonstration did not begin in the start position; the start may be misidentified.",
            )
        )

    rc, rc_warnings = _suggest_rep_counting(increasing, rest, peak, reps)
    warnings.extend(rc_warnings)
    return AnalysisResult(
        demo_id=demo_id,
        joint_candidates=candidates,
        chosen=chosen,
        increasing=increasing,
        rest_deg=round(rest, 1),
        typical_peak_deg=round(peak, 1),
        reps=reps,
        suggested_rep_counting=rc,
        suggested_rules=_suggest_rules(series, chosen, reps),
        warnings=warnings,
        chart=_chart(series, x),
    )


def _empty(
    demo_id: str,
    candidates: list[JointCandidate],
    chosen: JointCandidate | None,
    warnings_: list[AnalysisWarning],
    chart: ChartSeries | None,
) -> AnalysisResult:
    return AnalysisResult(
        demo_id=demo_id,
        joint_candidates=candidates,
        chosen=chosen,
        increasing=None,
        rest_deg=None,
        typical_peak_deg=None,
        reps=[],
        suggested_rep_counting=None,
        suggested_rules=[],
        warnings=warnings_,
        chart=chart,
    )
