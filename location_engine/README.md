# Location Engine

BLE-RSSI-based indoor localization for the medical tracker system.

---

## 1. Engine Files

There are two engine files. They share **all the same helper functions** — the only difference is the priority order inside `localize()`.

| File | Primary | Fallback 1 | Fallback 2 |
|------|---------|------------|------------|
| `engine.py` | Heron's barycentric | Trilateration | Weighted centroid |
| `engine_trilateration.py` | Trilateration | Heron's barycentric | Weighted centroid |

Use `test_algorithms.py` to run both on the same real data and compare.

---

### Shared Functions

#### `rssi_to_distance(rssi, A, n)`
Converts a raw RSSI reading to an estimated distance using the log-distance path loss model:

```
distance = 10 ^ ((A - rssi) / (10 * n))
```

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `A` | `-80` | RSSI at exactly 1 metre from the tag. **Calibrate this** using `hakim_test/findA` — run it, stand 1m from the Pi and read the average off the M5 screen. |
| `n` | `3.0` | Path loss exponent. `2.0` = open space, `3.0–4.0` = indoors with walls. |

---

#### `KalmanFilter(Q, R)`
Scalar (1D) Kalman filter for smoothing a noisy signal over time (used on RSSI values).

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `Q` | `0.01` | Process noise — how much the true RSSI is expected to drift between readings. Raise if the tag moves frequently. |
| `R` | `1.0` | Measurement noise — how noisy each raw RSSI reading is. Raise if your environment has high interference. |

**Usage:** call `.update(measurement)` with each new raw reading; it returns the smoothed value.

---

#### `get_smoothed_distance(mac, rssi, A, n)`
Convenience function: runs RSSI through a per-tag `KalmanFilter`, then converts to distance.
Filters are stored in a module-level dict `_kalman_filters` keyed by `mac` (or `mac_receiverid` when multiple receivers are tracking the same tag). Created automatically on first call.

---

#### `is_valid_triangle(d1, d2, d3)`
Geometric pre-check run before trilateration. Given three measured distances, checks:
1. Triangle inequality — none of the three distances exceeds the sum of the other two.
2. Heron's area² > 0 — the distances can form a non-degenerate triangle.

Returns `True` if trilateration is geometrically worth attempting.

---

#### `trilaterate(receivers)`
Linear least-squares trilateration. Takes a list of `(x, y, distance)` tuples (minimum 3).
Linearises the circle equations pairwise and solves with `numpy.linalg.lstsq`, so it handles
4+ receivers naturally by minimising residuals across all of them.
Returns `(x, y)` or `None` on failure.

---

#### `heron_localize(receivers)`
Barycentric localization using Heron's formula. Takes `(x, y, distance)` tuples (minimum 3).
For each combination of 3 receivers it computes a weighted position estimate, where the weight
is the geometric area of the triangle formed by those receivers — larger triangle = better geometry = more weight.
With 4+ receivers all triangle combinations are averaged.
Returns `(x, y)` or `None` on failure.

---

#### `weighted_centroid(receivers)`
Last-resort fallback. Works with any number of receivers (including fewer than 3).
Each receiver is weighted by `1 / distance²` — closer receivers pull the estimate more strongly.
Returns `(x, y)` or `None`.

---

### `localize(receivers)` / `localize_trilateration(receivers)`

The main entry point. Takes `(x, y, distance)` tuples and returns:

```python
{"x": float, "y": float, "method": str, "confidence": str}
# or None if all methods fail
```

| `method` | `confidence` | When |
|----------|-------------|------|
| `"heron"` or `"trilateration"` | `"high"` | Primary method succeeded |
| `"trilateration"` or `"heron"` | `"medium"` | Primary failed, fallback succeeded |
| `"weighted_centroid"` | `"medium"` | 3+ receivers but both geo methods failed |
| `"weighted_centroid"` | `"low"` | Fewer than 3 receivers |

**Pipeline — `engine.py`:**
```
3+ receivers → heron_localize()          → confidence=high
             → is_valid_triangle check
               → trilaterate()           → confidence=medium
             → weighted_centroid()       → confidence=medium
< 3 receivers → weighted_centroid()      → confidence=low
```

**Pipeline — `engine_trilateration.py`:**
```
3+ receivers → is_valid_triangle check
               → trilaterate()           → confidence=high
             → heron_localize()          → confidence=medium
             → weighted_centroid()       → confidence=medium
< 3 receivers → weighted_centroid()      → confidence=low
```

---

## 2. Test File — `test_algorithms.py`

Runs both engines side by side on real RSSI data and compares their accuracy.

### Modes

| Mode | Command | What it does |
|------|---------|--------------|
| Live | `python test_algorithms.py` | Subscribes to MQTT, estimates position in real time |
| Record | `python test_algorithms.py --record session.json` | Same as live, also saves every RSSI reading to a JSON file |
| Replay | `python test_algorithms.py --replay session.json` | Loads a saved recording and runs both engines on it without any hardware |

**Recommended workflow:** do one physical walkthrough with `--record`, then use `--replay` to compare engines or tune parameters as many times as you want without needing hardware.

---

### CLI Parameters

#### Environment-specific — change these to match your setup

| Argument | Default | What to change |
|----------|---------|----------------|
| `--broker` | `192.168.137.1` | IP address of your MQTT broker |
| `--port` | `1883` | MQTT port (use `8883` if TLS) |
| `--user` | `coordinator` | MQTT username |
| `--password` | `1234` | MQTT password |
| `--ca` | `None` | Path to CA cert if using TLS, e.g. `/etc/mosquitto/ca.crt` |
| `--receivers` | `rpi_a:0,0 rpi_b:4,0 rpi_c:4,4` | Physical positions of each Raspberry Pi receiver in metres. See below. |
| `--A` | `-60.0` | RSSI at 1 metre — **calibrate this first** using `hakim_test/findA` |
| `--n` | `3.0` | Path loss exponent for your environment |

#### Other parameters

| Argument | Default | Meaning |
|----------|---------|---------|
| `--interval` | `2.0` | Seconds between position estimates |
| `--record` | — | Filename to save RSSI readings to |
| `--replay` | — | Filename to load and replay |

---

### Specifying Receiver Positions

Pass each receiver as `id:x,y` in metres. Works for any number of receivers:

```bash
# 3 receivers
python test_algorithms.py --receivers rpi_a:0,0 rpi_b:4,0 rpi_c:2,4

# 4 receivers
python test_algorithms.py --receivers rpi_a:0,0 rpi_b:5,0 rpi_c:5,5 rpi_d:0,5

# 5 receivers
python test_algorithms.py --receivers rpi_a:0,0 rpi_b:5,0 rpi_c:5,5 rpi_d:0,5 rpi_e:2.5,2.5
```

The IDs must match the `receiver_id` field published by each Raspberry Pi over MQTT.
More receivers generally improves accuracy since `trilaterate()` and `heron_localize()` both
use all available readings (not just 3).

---

### Output

Each sample prints the receivers seen, then both engine estimates:

```
[14:23:01] MAC: AA:BB:CC:DD:EE:FF
  rpi_a         pos=(0,0)   rssi=-65.0 dBm  dist=2.14m
  rpi_b         pos=(4,0)   rssi=-71.0 dBm  dist=3.89m
  rpi_c         pos=(2,4)   rssi=-68.0 dBm  dist=3.02m
  Heron-primary : (2.14, 3.07)  method=heron             confidence=high
  Tri-primary   : (2.31, 3.22)  method=trilateration     confidence=high
```

When you type an actual position (`x y`), error is added:

```
  Heron-primary : (2.14, 3.07)  method=heron             confidence=high    error=0.21m
  Tri-primary   : (2.31, 3.22)  method=trilateration     confidence=high    error=0.38m
```

At the end of the session (Ctrl+C), a summary is printed:

```
Session summary (8 logged positions)
  Heron-primary   mean=0.34m  max=0.91m
    heron: 6 samples
    weighted_centroid: 2 samples
  Tri-primary     mean=0.41m  max=1.12m
    trilateration: 7 samples
    heron: 1 samples
  Winner: Heron-primary
```

The method breakdown shows how often each engine fell back to a secondary method —
frequent fallbacks suggest the geometry or RSSI quality is poor.

---

### Example Commands

```bash
# Quick live test with default settings
python test_algorithms.py

# Live test with your actual environment values
python test_algorithms.py \
  --broker 172.20.10.4 \
  --receivers rpi_a:0,0 rpi_b:6,0 rpi_c:6,5 rpi_d:0,5 \
  --A -63 --n 3.2

# Record a walkthrough
python test_algorithms.py \
  --broker 172.20.10.4 \
  --receivers rpi_a:0,0 rpi_b:6,0 rpi_c:6,5 rpi_d:0,5 \
  --A -63 --n 3.2 \
  --record ward_b_session.json

# Replay it while tuning A and n
python test_algorithms.py \
  --replay ward_b_session.json \
  --receivers rpi_a:0,0 rpi_b:6,0 rpi_c:6,5 rpi_d:0,5 \
  --A -65 --n 2.9
```
