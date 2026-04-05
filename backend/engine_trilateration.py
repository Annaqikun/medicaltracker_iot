"""Localization engine for calculating medicine positions from RSSI values.

Provides Kalman-filtered RSSI smoothing, trilateration-primary localization
pipeline, and numeric confidence scoring.

Localization pipeline (Trilateration-primary):
    3+ receivers -> is_valid_triangle() gate
                    -> trilaterate() (lstsq)     confidence=high
                 -> heron_localize()             confidence=medium
                 -> weighted_centroid()          confidence=medium
    <3 receivers -> weighted_centroid()          confidence=low
"""

from engine import (
    heron_localize,
    trilaterate,
    weighted_centroid,
    is_valid_triangle,
    get_smoothed_distance,
    calculate_position_error,
    calculate_confidence,
    reset_kalman_filter,
)
from typing import Any, Dict, List, Optional, Tuple


def localize(
    receivers: List[Tuple[float, float, float]]
) -> Optional[Dict[str, Any]]:
    """Trilateration-primary localization pipeline.

    Takes (x, y, distance) tuples.

    Pipeline:
        3+ receivers -> is_valid_triangle() gate
                        -> trilaterate() (lstsq)    confidence=high
                     -> heron_localize()            confidence=medium
                     -> weighted_centroid()          confidence=medium
        <3 receivers -> weighted_centroid()          confidence=low

    Returns:
        {"x": float, "y": float, "method": str, "confidence": str} or None.
    """
    if len(receivers) >= 3:
        distances = [r[2] for r in receivers]
        if is_valid_triangle(distances[0], distances[1], distances[2]):
            pos = trilaterate(receivers)
            if pos:
                return {"x": pos[0], "y": pos[1], "method": "trilateration", "confidence": "high"}

        pos = heron_localize(receivers)
        if pos:
            return {"x": pos[0], "y": pos[1], "method": "heron", "confidence": "medium"}

    pos = weighted_centroid(receivers)
    if pos is None:
        return None
    confidence = "medium" if len(receivers) >= 3 else "low"
    return {"x": pos[0], "y": pos[1], "method": "weighted_centroid", "confidence": confidence}
