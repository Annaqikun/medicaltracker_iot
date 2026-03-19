import math
import itertools
import numpy as np


class KalmanFilter:
    """
    Scalar (1D) Kalman filter for smoothing a single noisy signal (e.g. RSSI).
    Q = process noise (how much the true value drifts between updates).
    R = measurement noise (how noisy each reading is).
    """

    def __init__(self, Q=0.01, R=1.0):
        self._x = None   # state estimate
        self._p = 1.0    # estimate uncertainty
        self.Q  = Q
        self.R  = R

    def update(self, measurement):
        """Feed one raw reading; returns the smoothed value."""
        if self._x is None:
            self._x = measurement
            return self._x

        self._p += self.Q
        K        = self._p / (self._p + self.R)
        self._x  = self._x + K * (measurement - self._x)
        self._p  = (1 - K) * self._p
        return self._x


_kalman_filters = {}   # {mac: KalmanFilter}


def get_smoothed_distance(mac, rssi, A=-80, n=3.0):
    """
    Smooth a raw RSSI reading for the given MAC via a per-tag Kalman filter,
    then convert to distance. Creates the filter on first call for that MAC.
    """
    if mac not in _kalman_filters:
        _kalman_filters[mac] = KalmanFilter()
    smoothed_rssi = _kalman_filters[mac].update(rssi)
    return rssi_to_distance(smoothed_rssi, A=A, n=n)


def rssi_to_distance(rssi, A=-80, n=3.0):
    """
    Log-distance path loss model.
    A = RSSI at 1 metre — calibrate using hakim_test/findA, read Avg off the M5 screen.
    n = path loss exponent — 2 for open space, 3–4 for indoors.
    """
    return 10 ** ((A - rssi) / (10 * n))


def trilaterate(receivers):
    """
    Linear least-squares trilateration. Takes (x, y, distance) tuples, min 3.
    Linearises the circle equations pairwise, solves with lstsq (handles >3 receivers too).
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
        result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        return float(result[0]), float(result[1])
    except np.linalg.LinAlgError:
        return None


def _heron_area(a, b, c):
    """Area of a triangle given its 3 side lengths. Returns 0 if the points are collinear (degenerate triangle lel)."""
    s = (a + b + c) / 2
    return math.sqrt(max(s * (s - a) * (s - b) * (s - c), 0.0))


def _heron_localize_3(r1, r2, r3):
    """Barycentric localization from exactly 3 receivers. Returns (x, y, triangle_area) or None."""
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


def heron_localize(receivers):
    """
    Barycentric localization using Heron's formula. Takes (x, y, distance) tuples, min 3.
    With 4+ receivers, tries all combinations of 3 and returns a weighted average,
    where each triangle's estimate is weighted by its geometric area (larger = better geometry).
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


def is_valid_triangle(d1, d2, d3):
    """
    Geometric pre-check before running trilateration.
    Fails fast on triangle inequality, then confirms with Heron's area² > 0.
    """
    if not (d1 + d2 > d3 and d1 + d3 > d2 and d2 + d3 > d1):
        return False
    s = (d1 + d2 + d3) / 2
    return s * (s - d1) * (s - d2) * (s - d3) > 0


def weighted_centroid(receivers):
    """
    Last-resort position estimate using inverse-distance weighting (w = 1/d²).
    Works with any number of receivers. Takes (x, y, distance) tuples.
    """
    wx, wy, total_w = 0.0, 0.0, 0.0
    for x, y, d in receivers:
        w = 1.0 / (max(d, 0.01) ** 2)
        wx      += w * x
        wy      += w * y
        total_w += w
    if total_w == 0:
        return None
    return wx / total_w, wy / total_w


def localize(receivers):
    """
    Localization pipeline with heron_localize() as primary. Takes (x, y, distance) tuples.

    With 3+ receivers:
      1. heron_localize()                            confidence=high
      2. If that fails → is_valid_triangle check → trilaterate() confidence=medium
      3. Both fail     → weighted_centroid()         confidence=medium

    With <3 receivers:
      → weighted_centroid() confidence=low

    Returns {"x": float, "y": float, "method": str, "confidence": str} or None.
    """
    if len(receivers) >= 3:
        pos = heron_localize(receivers)
        if pos:
            return {"x": pos[0], "y": pos[1], "method": "heron", "confidence": "high"}

        distances = [d for _, _, d in receivers]
        geometry_valid = any(
            is_valid_triangle(d1, d2, d3)
            for d1, d2, d3 in itertools.combinations(distances, 3)
        )
        if geometry_valid:
            pos = trilaterate(receivers)
            if pos:
                return {"x": pos[0], "y": pos[1], "method": "trilateration", "confidence": "medium"}

    pos = weighted_centroid(receivers)
    if pos is None:
        return None
    confidence = "medium" if len(receivers) >= 3 else "low"
    return {"x": pos[0], "y": pos[1], "method": "weighted_centroid", "confidence": confidence}
