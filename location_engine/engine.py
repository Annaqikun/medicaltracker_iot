import math
import numpy as np


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


def heron_localize(receivers):
    """
    Barycentric localization using Heron's formula. Takes (x, y, distance) tuples, first 3 used.
    Each receiver is weighted by the area of the sub-triangle it's opposite to — closer receivers pull harder.
    Returns (x, y) or None on failure.
    """
    if len(receivers) < 3:
        return None

    (x1, y1, d1), (x2, y2, d2), (x3, y3, d3) = receivers[:3]

    # Side lengths between the known receiver positions
    a = math.dist((x2, y2), (x3, y3))  # opposite R1
    b = math.dist((x1, y1), (x3, y3))  # opposite R2
    c = math.dist((x1, y1), (x2, y2))  # opposite R3

    # Area of the sub-triangle facing each receiver, used as its weight
    area1 = _heron_area(a, d2, d3)  # triangle P-R2-R3 → weight for R1
    area2 = _heron_area(b, d1, d3)  # triangle P-R1-R3 → weight for R2
    area3 = _heron_area(c, d1, d2)  # triangle P-R1-R2 → weight for R3

    total = area1 + area2 + area3
    if total == 0:
        return None

    w1, w2, w3 = area1 / total, area2 / total, area3 / total
    return w1 * x1 + w2 * x2 + w3 * x3, w1 * y1 + w2 * y2 + w3 * y3
