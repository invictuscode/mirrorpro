"""Synthetic poses in MediaPipe landmark layout for tests."""

from __future__ import annotations

import math

import numpy as np

from app.pose.topology import LANDMARK_NAMES

I = {n: i for i, n in enumerate(LANDMARK_NAMES)}


def standing_pose(visibility: float = 0.95) -> np.ndarray:
    """Upright figure in normalized image coords: arms hanging, legs straight."""
    lm = np.zeros((33, 5), np.float32)
    lm[:, 0:2] = 0.5
    lm[:, 3:5] = visibility
    for side, x in (("left", 0.6), ("right", 0.4)):  # subject faces the camera
        lm[I[f"{side}_shoulder"], :2] = (x, 0.30)
        lm[I[f"{side}_elbow"], :2] = (x, 0.45)
        lm[I[f"{side}_wrist"], :2] = (x, 0.60)
        lm[I[f"{side}_hip"], :2] = (x - 0.05 if side == "left" else x + 0.05, 0.60)
        lm[I[f"{side}_knee"], :2] = (lm[I[f"{side}_hip"], 0], 0.75)
        lm[I[f"{side}_ankle"], :2] = (lm[I[f"{side}_hip"], 0], 0.90)
    return lm


def with_elbow_flexion(lm: np.ndarray, side: str, flexion_deg: float, forearm: float = 0.15) -> np.ndarray:
    """Return a copy of ``lm`` with the forearm rotated in the image plane so
    the elbow flexion is ``flexion_deg`` (upper arm hangs vertically)."""
    out = lm.copy()
    e = out[I[f"{side}_elbow"], :2]
    t = math.radians(flexion_deg)
    out[I[f"{side}_wrist"], :2] = (e[0] + forearm * math.sin(t), e[1] + forearm * math.cos(t))
    return out
