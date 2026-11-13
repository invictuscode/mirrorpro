"""Joint-angle definitions on MediaPipe Pose landmarks.

Each definition is an angle at landmark ``vertex`` between ``proximal`` and
``distal``. ``convention`` converts the included angle (0–180°) into the value
shown to users. These are *estimates from a camera*, not goniometer readings;
see docs/JOINT_ANGLES.md.

Only angles whose three landmarks are well defined by the model are included.
Ankle, wrist and neck angles are deliberately omitted: MediaPipe's foot, hand
and head points are too coarse or noisy for a meaningful single-camera angle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.pose.topology import LANDMARK_NAMES

_IDX = {name: i for i, name in enumerate(LANDMARK_NAMES)}


class Convention(StrEnum):
    INCLUDED = "included"  # value = included angle ABC
    FLEXION = "flexion"  # value = 180° − included (0° = segments in line)


@dataclass(frozen=True, slots=True)
class JointAngleDefinition:
    id: str
    label: str
    joint: str
    side: str
    proximal: int
    vertex: int
    distal: int
    convention: Convention
    description: str

    @property
    def landmarks(self) -> tuple[int, int, int]:
        return (self.proximal, self.vertex, self.distal)

    def to_value(self, included_deg: float) -> float:
        return included_deg if self.convention is Convention.INCLUDED else 180.0 - included_deg


def _pair(
    joint: str, label: str, proximal: str, vertex: str, distal: str, convention: Convention, description: str
) -> list[JointAngleDefinition]:
    return [
        JointAngleDefinition(
            id=f"{side}_{joint}",
            label=f"{side.capitalize()} {label}",
            joint=joint,
            side=side,
            proximal=_IDX[f"{side}_{proximal}"],
            vertex=_IDX[f"{side}_{vertex}"],
            distal=_IDX[f"{side}_{distal}"],
            convention=convention,
            description=description,
        )
        for side in ("left", "right")
    ]


# Sides are anatomical (the subject's left), independent of display mirroring.
JOINT_ANGLES: tuple[JointAngleDefinition, ...] = (
    *_pair(
        "elbow_flexion", "elbow flexion", "shoulder", "elbow", "wrist", Convention.FLEXION,
        "180° minus the shoulder–elbow–wrist angle. ~0° with the arm straight.",
    ),
    *_pair(
        "shoulder_elevation", "shoulder elevation", "hip", "shoulder", "elbow", Convention.INCLUDED,
        "Angle between trunk (shoulder→hip) and upper arm (shoulder→elbow). ~0° arm at side, "
        "~180° overhead. Does not separate flexion from abduction.",
    ),
    *_pair(
        "hip_flexion", "hip flexion", "shoulder", "hip", "knee", Convention.FLEXION,
        "180° minus the shoulder–hip–knee angle. ~0° standing upright. Includes trunk lean, "
        "so it is not a pure hip-joint measurement.",
    ),
    *_pair(
        "knee_flexion", "knee flexion", "hip", "knee", "ankle", Convention.FLEXION,
        "180° minus the hip–knee–ankle angle. ~0° with the leg straight.",
    ),
)  # fmt: skip

JOINT_ANGLES_BY_ID = {d.id: d for d in JOINT_ANGLES}
