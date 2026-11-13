"""Form-rule evaluation, shared by the rep counter (blocking rules) and the
feedback engine (messages), so both see the same judgement for a frame.

Two ways a rule can be violated:

* **angle**: the joint angle is outside the rule's bounds;
* **out of plane**: a 2D camera cannot see a joint bend toward or away from
  it (an elbow bent 90° toward the camera can read ~10°), but the distal
  segment then *looks shorter*. Bone lengths do not change, so if the on-screen
  ratio distal/proximal drops well below its value in the start position
  (default: under 45%, i.e. roughly a 60°+ bend), the joint has bent out of
  view. Turning the whole limb toward the camera shrinks
  both segments alike and leaves the ratio unchanged, so it is not flagged.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from app.biomechanics import AngleResult, AngleStatus
from app.biomechanics.joints import JOINT_ANGLES
from app.exercises.phases import RepPhase
from app.feedback.config import FormRule, RuleSide


class RuleState(StrEnum):
    INACTIVE = "inactive"  # not checked in the current phase
    OK = "ok"
    VIOLATED = "violated"  # outside bounds (acted on only once sustained)
    UNCERTAIN = "uncertain"  # rule's joint not reliably tracked: no judgement


class ViolationReason(StrEnum):
    ANGLE = "angle"
    OUT_OF_PLANE = "out_of_plane"


@dataclass(frozen=True, slots=True)
class RuleStatus:
    id: str
    state: RuleState
    value_deg: float | None
    sustained: bool = False  # violated continuously for at least the rule's sustain_ms
    blocks_rep: bool = False
    reason: ViolationReason | None = None


@dataclass(frozen=True, slots=True)
class FormCheck:
    """Per-frame summary of *blocking* rules, consumed by the rep counter.

    ``violated`` lists (rule id, sustain_ms) for blocking rules outside their
    bounds *this frame*. The counter adds up violated time over the whole rep,
    so a violation interrupted by tracking flicker still counts."""

    violated: tuple[tuple[str, int], ...]
    unverified: bool  # a blocking rule's joint could not be checked this frame

    @property
    def clean(self) -> bool:
        return not self.violated and not self.unverified


# Angle id → (proximal, vertex, distal) landmark indices.
_SEGMENTS: dict[str, tuple[int, int, int]] = {d.id: d.landmarks for d in JOINT_ANGLES}
# Segment lengths are only trusted from clearly visible landmarks: a
# low-confidence wrist estimate can make a straight forearm look short.
_MIN_VISIBILITY = 0.65
_BASELINE_ALPHA = 0.2
_START_PHASES = frozenset({RepPhase.WAITING_FOR_START, RepPhase.READY})


def segment_ratios(landmarks: np.ndarray | None, image_size: tuple[int, int]) -> dict[str, float]:
    """On-screen distal/proximal segment length ratio per angle id, in
    aspect-corrected pixels. Omitted where a landmark is not clearly visible."""
    if landmarks is None:
        return {}
    w, h = image_size
    out: dict[str, float] = {}
    for angle_id, (a, b, c) in _SEGMENTS.items():
        pts = landmarks[[a, b, c]]
        if np.any(pts[:, 3] < _MIN_VISIBILITY):
            continue
        (ax, ay), (bx, by), (cx, cy) = (p[:2] * (w, h) for p in pts)
        proximal = math.hypot(ax - bx, ay - by)
        distal = math.hypot(cx - bx, cy - by)
        if proximal > 1:
            out[angle_id] = distal / proximal
    return out


class RuleEvaluator:
    def __init__(self, rules: Sequence[FormRule]) -> None:
        self._rules = tuple(rules)
        self._sustain = {r.id: r.sustain_ms for r in self._rules}
        self._violated_since: dict[str, int | None] = {r.id: None for r in self._rules}
        # Start-position segment ratio per angle id (learned, per person/camera).
        self._baseline: dict[str, float] = {}

    def evaluate(
        self,
        phase: RepPhase,
        angles: Sequence[AngleResult],
        sides_used: tuple[str, ...],
        timestamp_ms: int,
        ratios: dict[str, float] | None = None,
    ) -> tuple[RuleStatus, ...]:
        ratios = ratios or {}
        if phase in _START_PHASES:
            for angle_id, r in ratios.items():
                prev = self._baseline.get(angle_id)
                self._baseline[angle_id] = r if prev is None else prev + _BASELINE_ALPHA * (r - prev)
        return tuple(self._one(r, phase, angles, sides_used, timestamp_ms, ratios) for r in self._rules)

    def form_check(self, statuses: Sequence[RuleStatus]) -> FormCheck:
        blocking = [s for s in statuses if s.blocks_rep]
        violated = tuple((s.id, self._sustain[s.id]) for s in blocking if s.state is RuleState.VIOLATED)
        return FormCheck(violated, any(s.state is RuleState.UNCERTAIN for s in blocking))

    def _one(
        self,
        rule: FormRule,
        phase: RepPhase,
        angles: Sequence[AngleResult],
        sides_used: tuple[str, ...],
        ts: int,
        ratios: dict[str, float],
    ) -> RuleStatus:
        def status(
            state: RuleState,
            value: float | None = None,
            sustained: bool = False,
            reason: ViolationReason | None = None,
        ) -> RuleStatus:
            return RuleStatus(rule.id, state, value, sustained, rule.blocks_rep, reason)

        if phase not in rule.phases:
            self._violated_since[rule.id] = None
            return status(RuleState.INACTIVE)
        match rule.side:
            case RuleSide.SIGNAL:
                sides = sides_used
            case RuleSide.BOTH:
                sides = ("left", "right")
            case _:
                sides = (rule.side.value,)
        wanted = [f"{s}_{rule.joint}" for s in sides]
        values = [a.value_deg for a in angles if a.id in wanted and a.status is AngleStatus.OK and a.value_deg is not None]
        # Checked even when the angle itself is unmeasurable: a forearm that has
        # all but vanished on screen (with clearly visible landmarks) is the
        # strongest sign of a bend toward the camera.
        out_of_plane = rule.out_of_plane_limit is not None and any(
            (base := self._baseline.get(angle_id)) is not None
            and (now := ratios.get(angle_id)) is not None
            and now < rule.out_of_plane_limit * base
            for angle_id in wanted
        )
        if not values and not out_of_plane:
            self._violated_since[rule.id] = None
            return status(RuleState.UNCERTAIN)
        worst = max(values, key=lambda v: excess(rule, v)) if values else None
        if worst is not None and excess(rule, worst) > 0:
            reason: ViolationReason | None = ViolationReason.ANGLE
        else:
            reason = ViolationReason.OUT_OF_PLANE if out_of_plane else None
        if reason is not None:
            since = self._violated_since[rule.id]
            if since is None:
                since = self._violated_since[rule.id] = ts
            return status(RuleState.VIOLATED, worst, ts - since >= rule.sustain_ms, reason)
        self._violated_since[rule.id] = None
        return status(RuleState.OK, worst)


def excess(rule: FormRule, v: float) -> float:
    """How far ``v`` lies outside the rule's bounds (0 if inside)."""
    over = v - rule.max_deg if rule.max_deg is not None else 0.0
    under = rule.min_deg - v if rule.min_deg is not None else 0.0
    return max(over, under, 0.0)
