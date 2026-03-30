"""Localization engine for calculating medicine positions from RSSI values.

Provides Kalman-filtered RSSI smoothing, Heron-primary localization pipeline
(heron -> trilaterate -> weighted_centroid), and numeric confidence scoring.

Localization pipeline (Heron-primary):
    3+ receivers -> heron_localize()          confidence=high
                 -> trilaterate() (lstsq)     confidence=medium
                 -> weighted_centroid()        confidence=medium
    <3 receivers -> weighted_centroid()        confidence=low
"""

import itertools
import logging
import math
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kalman filter for RSSI smoothing
# ---------------------------------------------------------------------------

class KalmanFilter:
    """Scalar (1D) Kalman filter for smoothing a single noisy signal (e.g. RSSI).

    Args:
        Q: Process noise — how much the true value drifts between updates.
        R: Measurement noise — how noisy each reading is.
    """

    def __init__(self, Q: float = 0.01, R: float = 1.0) -> None:
        self._x: Optional[float] = None  # state estimate
        self._p: float = 1.0             # estimate uncertainty
        self.Q = Q
        self.R = R

    def update(self, measurement: float) -> float:
        """Feed one raw reading; returns the smoothed value."""
        if self._x is None:
            self._x = measurement
            return self._x

        self._p += self.Q
        K = self._p / (self._p + self.R)
        self._x = self._x + K * (measurement - self._x)
        self._p = (1 - K) * self._p
        return self._x


# Thread-safe per-tag Kalman filter state
_kalman_filters: Dict[str, KalmanFilter] = {}
_kalman_lock = threading.Lock()


def reset_kalman_filter(mac: str) -> None:
    """Remove all Kalman filters for a tag so they re-initialise on next reading."""
    with _kalman_lock:
        stale = [k for k in _kalman_filters if k.startswith(f"{mac}:")]
        for k in stale:
            del _kalman_filters[k]


def get_smoothed_distance(
    mac: str,
    rssi: int,
    rssi_reference: int = -59,
    path_loss_exponent: float = 2.5,
    receiver_id: str = "",
) -> Optional[float]:
    """Kalman-smooth a raw RSSI reading then convert to distance.

    Creates a per-(mac, receiver_id) KalmanFilter on first call. Thread-safe.
    Rejects positive RSSI values (invalid telemetry) before they can
    contaminate the Kalman state.

    Args:
        mac: Tag identifier.
        rssi: Raw RSSI value in dBm.
        rssi_reference: RSSI at 1 metre distance.
        path_loss_exponent: Environment path loss exponent.
        receiver_id: Receiver identifier (each receiver gets its own filter).

    Returns:
        Smoothed distance estimate in metres, or None if the raw RSSI
        is invalid (positive values are rejected).
    """
    if rssi > 0:
        logger.warning(
            f"Rejecting invalid positive RSSI {rssi} dBm for {mac}:{receiver_id}"
        )
        return None
    key = f"{mac}:{receiver_id}"
    with _kalman_lock:
        if key not in _kalman_filters:
            _kalman_filters[key] = KalmanFilter()
        smoothed_rssi = _kalman_filters[key].update(rssi)
    return rssi_to_distance(smoothed_rssi, rssi_reference, path_loss_exponent)


# ---------------------------------------------------------------------------
# RSSI -> distance conversion
# ---------------------------------------------------------------------------

def rssi_to_distance(
    rssi: float,
    rssi_reference: int = -59,
    path_loss_exponent: float = 2.5
) -> float:
    """Convert RSSI value to estimated distance using log-distance path loss model.

    d = 10^((RSSI_ref - RSSI) / (10 * n))

    Args:
        rssi: Measured RSSI value in dBm (negative value).
        rssi_reference: RSSI value at 1 metre distance (default: -59 dBm).
        path_loss_exponent: Path loss exponent based on environment
            (2.0 for free space, 2.5-3.0 for indoor, 3.0-4.0 for obstacles).

    Returns:
        float: Estimated distance in metres.

    Raises:
        ValueError: If path_loss_exponent is zero or negative.
    """
    if path_loss_exponent <= 0:
        raise ValueError("Path loss exponent must be positive")

    if rssi < -90:
        logger.warning(f"Very weak RSSI: {rssi:.1f} dBm, distance may be unreliable")

    # Calculate distance using path loss model
    distance = math.pow(10.0, (rssi_reference - rssi) / (10.0 * path_loss_exponent))

    # Single cap — applies uniformly to weak signals and model outliers
    max_distance = 50.0
    if distance > max_distance:
        logger.debug(f"Capped distance from {distance:.2f}m to {max_distance}m")
        return max_distance

    logger.debug(f"RSSI {rssi:.1f} dBm -> Distance {distance:.2f}m")
    return distance


# ---------------------------------------------------------------------------
# Geometric helpers
# ---------------------------------------------------------------------------

def _heron_area(a: float, b: float, c: float) -> float:
    """Area of a triangle given its 3 side lengths.

    Returns 0 if the points are collinear (degenerate triangle).
    """
    s = (a + b + c) / 2
    return math.sqrt(max(s * (s - a) * (s - b) * (s - c), 0.0))


def is_valid_triangle(d1: float, d2: float, d3: float) -> bool:
    """Geometric pre-check before running trilateration.

    Fails fast on triangle inequality, then confirms with Heron's area > 0.
    """
    if not (d1 + d2 > d3 and d1 + d3 > d2 and d2 + d3 > d1):
        return False
    s = (d1 + d2 + d3) / 2
    return s * (s - d1) * (s - d2) * (s - d3) > 0


# ---------------------------------------------------------------------------
# Localization algorithms
# ---------------------------------------------------------------------------

def _heron_localize_3(
    r1: Tuple[float, float, float],
    r2: Tuple[float, float, float],
    r3: Tuple[float, float, float]
) -> Optional[Tuple[float, float, float]]:
    """Barycentric localization from exactly 3 receivers.

    Returns (x, y, triangle_area) or None.
    """
    (x1, y1, d1), (x2, y2, d2), (x3, y3, d3) = r1, r2, r3

    a = math.dist((x2, y2), (x3, y3))
    b = math.dist((x1, y1), (x3, y3))
    c = math.dist((x1, y1), (x2, y2))

    area1 = _heron_area(a, d2, d3)
    area2 = _heron_area(b, d1, d3)
    area3 = _heron_area(c, d1, d2)

    total = area1 + area2 + area3
    if total == 0:
        return None

    w1, w2, w3 = area1 / total, area2 / total, area3 / total
    x = w1 * x1 + w2 * x2 + w3 * x3
    y = w1 * y1 + w2 * y2 + w3 * y3
    triangle_area = _heron_area(a, b, c)
    return x, y, triangle_area


def heron_localize(
    receivers: List[Tuple[float, float, float]]
) -> Optional[Tuple[float, float]]:
    """Barycentric localization using Heron's formula.

    Takes (x, y, distance) tuples, minimum 3.
    With 4+ receivers, tries all combinations of 3 and returns a weighted
    average where each triangle's estimate is weighted by its geometric area.

    Returns (x, y) or None on failure.
    """
    if len(receivers) < 3:
        return None

    estimates = []
    for combo in itertools.combinations(receivers, 3):
        result = _heron_localize_3(*combo)
        if result:
            estimates.append(result)

    if not estimates:
        return None

    total_weight = sum(e[2] for e in estimates)
    if total_weight == 0:
        return None

    x = sum(e[0] * e[2] for e in estimates) / total_weight
    y = sum(e[1] * e[2] for e in estimates) / total_weight
    return x, y


def trilaterate(
    receivers: List[Tuple[float, float, float]]
) -> Optional[Tuple[float, float]]:
    """Linear least-squares trilateration.

    Takes (x, y, distance) tuples, minimum 3.
    Linearises the circle equations pairwise, solves with lstsq.

    Returns (x, y) or None on failure.
    """
    if len(receivers) < 3:
        return None

    x1, y1, d1 = receivers[0]
    A_rows = []
    b_rows = []

    for (xi, yi, di) in receivers[1:]:
        A_rows.append([2 * (xi - x1), 2 * (yi - y1)])
        b_rows.append(d1**2 - di**2 + xi**2 - x1**2 + yi**2 - y1**2)

    A = np.array(A_rows, dtype=float)
    b = np.array(b_rows, dtype=float)

    try:
        if np.linalg.matrix_rank(A) < 2:
            return None
        result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        return float(result[0]), float(result[1])
    except np.linalg.LinAlgError:
        return None


def weighted_centroid(
    receivers: List[Tuple[float, float, float]]
) -> Optional[Tuple[float, float]]:
    """Position estimate using inverse-distance weighting (w = 1/d^2).

    Works with any number of receivers. Takes (x, y, distance) tuples.
    """
    wx, wy, total_w = 0.0, 0.0, 0.0
    for x, y, d in receivers:
        w = 1.0 / (max(d, 0.01) ** 2)
        wx += w * x
        wy += w * y
        total_w += w
    if total_w == 0:
        return None
    return wx / total_w, wy / total_w


# ---------------------------------------------------------------------------
# Localization pipeline (Heron-primary)
# ---------------------------------------------------------------------------

def localize(
    receivers: List[Tuple[float, float, float]]
) -> Optional[Dict[str, Any]]:
    """Heron-primary localization pipeline.

    Takes (x, y, distance) tuples.

    Pipeline:
        3+ receivers -> heron_localize()        confidence=high
                     -> trilaterate() (lstsq)   confidence=medium (rank check handles bad geometry)
                     -> weighted_centroid()      confidence=medium
        <3 receivers -> weighted_centroid()      confidence=low

    Returns:
        {"x": float, "y": float, "method": str, "confidence": str} or None.
    """
    if len(receivers) >= 3:
        pos = heron_localize(receivers)
        if pos:
            return {"x": pos[0], "y": pos[1], "method": "heron", "confidence": "high"}

        pos = trilaterate(receivers)
        if pos:
            return {"x": pos[0], "y": pos[1], "method": "trilateration", "confidence": "medium"}

    pos = weighted_centroid(receivers)
    if pos is None:
        return None
    confidence = "medium" if len(receivers) >= 3 else "low"
    return {"x": pos[0], "y": pos[1], "method": "weighted_centroid", "confidence": confidence}


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def calculate_confidence(
    method: str,
    receiver_count: int,
    rmse: float
) -> float:
    """Compute numeric confidence score 0-100.

    Weighted scoring:
      - Method (40%): heron=40, trilateration=30, weighted_centroid=15
      - Receiver count (30%): 4+=30, 3=25, 2=15, 1=5
      - RMSE (30%): <0.5m=30, <1m=25, <2m=18, <5m=10, else=0

    Args:
        method: Algorithm used ("heron", "trilateration", "weighted_centroid").
        receiver_count: Number of receivers contributing to the estimate.
        rmse: Root mean square error of the position estimate in metres.

    Returns:
        float: Confidence score 0-100.
    """
    # Method score (40% weight)
    method_scores = {"heron": 40, "trilateration": 30, "weighted_centroid": 15}
    method_score = method_scores.get(method, 0)

    # Receiver count score (30% weight)
    if receiver_count >= 4:
        receiver_score = 30
    elif receiver_count == 3:
        receiver_score = 25
    elif receiver_count == 2:
        receiver_score = 15
    else:
        receiver_score = 5

    # RMSE score (30% weight)
    if rmse < 0.5:
        rmse_score = 30
    elif rmse < 1.0:
        rmse_score = 25
    elif rmse < 2.0:
        rmse_score = 18
    elif rmse < 5.0:
        rmse_score = 10
    else:
        rmse_score = 0

    return float(method_score + receiver_score + rmse_score)


# ---------------------------------------------------------------------------
# Position error (RMSE) — adapted to 2D
# ---------------------------------------------------------------------------

def calculate_position_error(
    calculated_position: Tuple[float, float],
    receivers: Dict[str, Tuple[float, float]],
    distances: Dict[str, float]
) -> float:
    """Calculate the root mean square error of a 2D position estimate.

    Args:
        calculated_position: The calculated (x, y) position.
        receivers: Dictionary of receiver_id -> (x, y) positions.
        distances: Dictionary of receiver_id -> measured distance.

    Returns:
        float: RMSE in metres. Lower values indicate better fit.
    """
    cx, cy = calculated_position
    squared_errors = []

    common_receivers = set(receivers.keys()) & set(distances.keys())

    for receiver_id in common_receivers:
        rx, ry = receivers[receiver_id]
        measured_distance = distances[receiver_id]

        expected_distance = math.sqrt((cx - rx) ** 2 + (cy - ry) ** 2)

        error = measured_distance - expected_distance
        squared_errors.append(error ** 2)

    if not squared_errors:
        return float('inf')

    return math.sqrt(sum(squared_errors) / len(squared_errors))
