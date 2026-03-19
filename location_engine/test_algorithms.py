"""
Live localization test — runs on coordinator PC.

Subscribes to hospital/medicine/rssi_only/#, collects RSSI from all receivers
for the same M5StickC, then runs both engines side by side on every sample.

Modes:
  python test_algorithms.py                         live, no recording
  python test_algorithms.py --record session.json   live + save readings to file
  python test_algorithms.py --replay session.json   replay a saved session
"""

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt

import engine as eng
import engine_trilateration as eng_tri


# State

latest_readings = defaultdict(dict)
readings_lock = threading.Lock()
READING_MAX_AGE = 10.0
MIN_RECEIVERS = 3


# MQTT

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected")
        client.subscribe("hospital/medicine/rssi_only/#")
    else:
        print(f"[MQTT] Failed (rc={rc})")
        sys.exit(1)


def on_message(client, userdata, msg):
    receiver_positions = userdata["receiver_positions"]
    record_log = userdata.get("record_log")
    try:
        parts = msg.topic.split("/")
        if len(parts) < 4:
            return
        mac = parts[3]

        payload = json.loads(msg.payload.decode())
        receiver_id = payload.get("receiver_id")
        rssi = payload.get("rssi")

        if receiver_id is None or rssi is None:
            return
        if receiver_id not in receiver_positions:
            return

        ts = time.time()
        with readings_lock:
            latest_readings[mac][receiver_id] = {"rssi": rssi, "timestamp": ts}

        if record_log is not None:
            record_log.append({"mac": mac, "receiver_id": receiver_id,
                                "rssi": rssi, "timestamp": ts})
    except Exception as e:
        print(f"[MQTT] Parse error: {e}")


# Localization helpers

def build_receivers(readings_snapshot, receiver_positions, mac, A, n):
    """Convert a {receiver_id: {rssi, timestamp}} snapshot into (x, y, d, rid, rssi) tuples."""
    result = []
    for receiver_id, data in readings_snapshot.items():
        if receiver_id not in receiver_positions:
            continue
        x, y = receiver_positions[receiver_id]
        d = eng.get_smoothed_distance(f"{mac}_{receiver_id}", data["rssi"], A=A, n=n)
        result.append((x, y, d, receiver_id, data["rssi"]))
    return result


def run_both(receivers_xyz):
    return eng.localize(receivers_xyz), eng_tri.localize_trilateration(receivers_xyz)


def error_m(result, actual):
    if result is None or actual is None:
        return None
    return math.dist((result["x"], result["y"]), actual)


# Display

def fmt_result(result, actual=None):
    if result is None:
        return "FAILED"
    parts = f"({result['x']:.2f}, {result['y']:.2f})  method={result['method']:<16s}  confidence={result['confidence']}"
    if actual:
        parts += f"  error={error_m(result, actual):.2f}m"
    return parts


def print_sample(mac, fresh, heron_result, tri_result, actual=None):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] MAC: {mac}")
    for x, y, d, rid, rssi in fresh:
        print(f"  {rid:12s}  pos=({x},{y})  rssi={rssi:.1f} dBm  dist={d:.2f}m")
    print(f"  Heron-primary : {fmt_result(heron_result, actual)}")
    print(f"  Tri-primary   : {fmt_result(tri_result,   actual)}")


CSV_FIELDS = [
    "timestamp", "mac", "actual_x", "actual_y",
    "heron_x", "heron_y", "heron_method", "heron_confidence", "heron_err",
    "tri_x",   "tri_y",   "tri_method",   "tri_confidence",   "tri_err",
]


def write_csv(path, session_results):
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(session_results)
    print(f"\nResults appended to {path} ({len(session_results)} rows)")


def print_summary(session_results):
    if not session_results:
        return

    print(f"\nSession summary ({len(session_results)} logged positions)")
    for label, key in [("Heron-primary", "heron"), ("Tri-primary", "tri")]:
        errs    = [r[f"{key}_err"]    for r in session_results if r[f"{key}_err"]    is not None]
        methods = [r[f"{key}_method"] for r in session_results if r[f"{key}_method"] is not None]
        if errs:
            print(f"  {label:14s}  mean={sum(errs)/len(errs):.2f}m  max={max(errs):.2f}m")
        for method, count in Counter(methods).most_common():
            print(f"    {method}: {count} samples")

    heron_errs = [r["heron_err"] for r in session_results if r["heron_err"] is not None]
    tri_errs   = [r["tri_err"]   for r in session_results if r["tri_err"]   is not None]
    if heron_errs and tri_errs:
        winner = "Heron-primary" if sum(heron_errs) / len(heron_errs) <= sum(tri_errs) / len(tri_errs) else "Tri-primary"
        print(f"  Winner: {winner}")


# Live mode

def run_live(args, receiver_positions, record_log=None):
    client = mqtt.Client(userdata={"receiver_positions": receiver_positions,
                                   "record_log": record_log})
    client.username_pw_set(args.user, args.password)
    if args.ca:
        client.tls_set(ca_certs=args.ca)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    print("\nWaiting for M5StickC readings (10s)...")
    time.sleep(10)

    with readings_lock:
        known_macs = list(latest_readings.keys())

    if not known_macs:
        print("No M5StickC detected. Is the pipeline running?")
        client.loop_stop()
        sys.exit(1)

    if len(known_macs) == 1:
        mac = known_macs[0]
    else:
        for i, m in enumerate(known_macs):
            print(f"  [{i}] {m}")
        mac = known_macs[int(input("Select index: "))]
    print(f"MAC: {mac}")

    session_results = []
    latest = {"heron": None, "tri": None, "fresh": None}
    latest_lock = threading.Lock()
    stop_event = threading.Event()

    def sample_loop():
        while not stop_event.is_set():
            time.sleep(args.interval)
            with readings_lock:
                snapshot = dict(latest_readings[mac])
            fresh = build_receivers(snapshot, receiver_positions, mac, args.A, args.n)
            if len(fresh) < MIN_RECEIVERS:
                continue
            receivers_xyz = [(x, y, d) for x, y, d, _, _ in fresh]
            heron_result, tri_result = run_both(receivers_xyz)
            with latest_lock:
                latest["heron"] = heron_result
                latest["tri"]   = tri_result
                latest["fresh"] = fresh
            print_sample(mac, fresh, heron_result, tri_result)

    threading.Thread(target=sample_loop, daemon=True).start()
    print(f"\nSampling every {args.interval}s. Type 'x y' to log actual position. Ctrl+C to finish.\n")

    try:
        while True:
            raw = input().strip()
            if not raw:
                continue
            try:
                ax, ay = map(float, raw.split())
            except ValueError:
                print("  Enter position as: x y")
                continue
            with latest_lock:
                heron_result = latest["heron"]
                tri_result   = latest["tri"]
                fresh        = latest["fresh"]
            if not fresh:
                print("  No data yet.")
                continue
            actual = (ax, ay)
            print_sample(mac, fresh, heron_result, tri_result, actual)
            session_results.append({
                "timestamp":        datetime.now().isoformat(),
                "mac":              mac,
                "actual_x":         ax,
                "actual_y":         ay,
                "heron_x":          heron_result["x"]          if heron_result else None,
                "heron_y":          heron_result["y"]          if heron_result else None,
                "heron_method":     heron_result["method"]     if heron_result else None,
                "heron_confidence": heron_result["confidence"] if heron_result else None,
                "heron_err":        error_m(heron_result, actual),
                "tri_x":            tri_result["x"]            if tri_result   else None,
                "tri_y":            tri_result["y"]            if tri_result   else None,
                "tri_method":       tri_result["method"]       if tri_result   else None,
                "tri_confidence":   tri_result["confidence"]   if tri_result   else None,
                "tri_err":          error_m(tri_result,   actual),
            })
    except KeyboardInterrupt:
        stop_event.set()

    client.loop_stop()
    client.disconnect()
    print_summary(session_results)

    if record_log is not None and args.record:
        with open(args.record, "w") as f:
            json.dump(record_log, f, indent=2)
        print(f"\nRecording saved to {args.record} ({len(record_log)} readings)")

    if args.csv and session_results:
        write_csv(args.csv, session_results)


# Replay mode

def run_replay(args, receiver_positions):
    with open(args.replay) as f:
        log = json.load(f)
    print(f"Loaded {len(log)} readings from {args.replay}\n")

    log.sort(key=lambda r: r["timestamp"])
    t_start  = log[0]["timestamp"]
    interval = args.interval

    state          = defaultdict(dict)   # mac -> receiver_id -> {rssi, timestamp}
    session_results = []
    bucket_end     = t_start + interval
    bucket         = []

    def process_bucket():
        for r in bucket:
            state[r["mac"]][r["receiver_id"]] = {"rssi": r["rssi"], "timestamp": r["timestamp"]}

        for mac, readings in state.items():
            fresh = build_receivers(readings, receiver_positions, mac, args.A, args.n)
            if len(fresh) < MIN_RECEIVERS:
                continue

            receivers_xyz = [(x, y, d) for x, y, d, _, _ in fresh]
            heron_result, tri_result = run_both(receivers_xyz)
            print_sample(mac, fresh, heron_result, tri_result)

            raw = input("  Actual position (x y) or Enter to skip: ").strip()
            if not raw:
                continue
            try:
                ax, ay = map(float, raw.split())
            except ValueError:
                print("  Skipped.")
                continue
            actual = (ax, ay)
            print_sample(mac, fresh, heron_result, tri_result, actual)
            session_results.append({
                "heron_err":    error_m(heron_result, actual),
                "tri_err":      error_m(tri_result,   actual),
                "heron_method": heron_result["method"] if heron_result else None,
                "tri_method":   tri_result["method"]   if tri_result   else None,
            })

    for reading in log:
        if reading["timestamp"] > bucket_end:
            process_bucket()
            bucket.clear()
            bucket_end += interval
        bucket.append(reading)

    if bucket:
        process_bucket()

    print_summary(session_results)


# Main

def parse_receivers(raw_list):
    out = {}
    for item in raw_list:
        name, coords = item.split(":")
        x, y = coords.split(",")
        out[name.strip()] = (float(x), float(y))
    return out


def main():
    parser = argparse.ArgumentParser(description="Live localization test")
    parser.add_argument("--broker",    default="192.168.137.1")
    parser.add_argument("--port",      type=int, default=1883)
    parser.add_argument("--user",      default="coordinator")
    parser.add_argument("--password",  default="1234")
    parser.add_argument("--ca",        default=None)
    parser.add_argument("--receivers", nargs="+",
                        default=["rpi_a:0,0", "rpi_b:4,0", "rpi_c:4,4"],
                        metavar="ID:X,Y")
    parser.add_argument("--A",         type=float, default=-60.0)
    parser.add_argument("--n",         type=float, default=3.0)
    parser.add_argument("--interval",  type=float, default=2.0, metavar="SECONDS")
    parser.add_argument("--record",    metavar="FILE", help="Save RSSI readings to JSON")
    parser.add_argument("--replay",    metavar="FILE", help="Replay a recorded session")
    parser.add_argument("--csv",       metavar="FILE", help="Append logged positions to CSV")
    args = parser.parse_args()

    receiver_positions = parse_receivers(args.receivers)
    print(f"Receivers : {receiver_positions}")
    print(f"A={args.A} dBm  n={args.n}")

    if args.replay:
        run_replay(args, receiver_positions)
    elif args.record:
        run_live(args, receiver_positions, record_log=[])
    else:
        run_live(args, receiver_positions)


if __name__ == "__main__":
    main()
