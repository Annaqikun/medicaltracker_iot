"""
Simple position logger.

Connects to MQTT, runs both localization engines in the background.
Type 'x y' to snapshot the current estimate + log it to CSV.
No background printing — input is never interrupted.

Usage:
  python logger.py --receivers rpi_a:0,0 rpi_b:2,0 rpi_c:2,2 --csv results.csv
"""

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt

import engine as eng
import engine_trilateration as eng_tri


MIN_RECEIVERS = 3
READING_MAX_AGE = 10.0

latest_readings = defaultdict(dict)
readings_lock = threading.Lock()

latest_estimate = {"heron": None, "tri": None, "fresh": None, "mac": None}
estimate_lock = threading.Lock()

CSV_FIELDS = [
    "timestamp", "mac", "actual_x", "actual_y",
    "heron_x", "heron_y", "heron_method", "heron_confidence", "heron_err",
    "tri_x",   "tri_y",   "tri_method",   "tri_confidence",   "tri_err",
]


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe("hospital/medicine/rssi_only/#")
    else:
        print(f"[MQTT] Failed (rc={rc})")
        sys.exit(1)


def on_message(client, userdata, msg):
    receiver_positions = userdata["receiver_positions"]
    try:
        parts = msg.topic.split("/")
        if len(parts) < 4:
            return
        mac = parts[3]
        payload = json.loads(msg.payload.decode())
        receiver_id = payload.get("receiver_id")
        rssi = payload.get("rssi")
        if receiver_id is None or rssi is None or receiver_id not in receiver_positions:
            return
        with readings_lock:
            latest_readings[mac][receiver_id] = {"rssi": rssi, "timestamp": time.time()}
    except Exception:
        pass


def compute_loop(receiver_positions, A, n, stop_event):
    while not stop_event.is_set():
        time.sleep(1)
        with readings_lock:
            if not latest_readings:
                continue
            mac = next(iter(latest_readings))
            snapshot = dict(latest_readings[mac])

        now = time.time()
        fresh = []
        for receiver_id, data in snapshot.items():
            if now - data["timestamp"] > READING_MAX_AGE:
                continue
            if receiver_id not in receiver_positions:
                continue
            x, y = receiver_positions[receiver_id]
            d = eng.get_smoothed_distance(f"{mac}_{receiver_id}", data["rssi"], A=A, n=n)
            fresh.append((x, y, d, receiver_id, data["rssi"]))

        if len(fresh) < MIN_RECEIVERS:
            continue

        receivers_xyz = [(x, y, d) for x, y, d, _, _ in fresh]
        heron_result = eng.localize(receivers_xyz)
        tri_result   = eng_tri.localize_trilateration(receivers_xyz)

        with estimate_lock:
            latest_estimate["mac"]   = mac
            latest_estimate["heron"] = heron_result
            latest_estimate["tri"]   = tri_result
            latest_estimate["fresh"] = fresh


def error_m(result, ax, ay):
    if result is None:
        return None
    return math.dist((result["x"], result["y"]), (ax, ay))


def write_row(path, row):
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def parse_receivers(raw_list):
    out = {}
    for item in raw_list:
        name, coords = item.split(":")
        x, y = coords.split(",")
        out[name.strip()] = (float(x), float(y))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker",    default="192.168.137.1")
    parser.add_argument("--port",      type=int, default=1883)
    parser.add_argument("--user",      default="coordinator")
    parser.add_argument("--password",  default="1234")
    parser.add_argument("--ca",        default=None)
    parser.add_argument("--receivers", nargs="+", default=["rpi_a:0,0", "rpi_b:2,0", "rpi_c:2,2"], metavar="ID:X,Y")
    parser.add_argument("--A",         type=float, default=-60.0)
    parser.add_argument("--n",         type=float, default=3.0)
    parser.add_argument("--csv",       default="results.csv", metavar="FILE")
    args = parser.parse_args()

    receiver_positions = parse_receivers(args.receivers)
    print(f"Receivers : {receiver_positions}")
    print(f"Broker    : {args.broker}:{args.port}")
    print(f"CSV       : {args.csv}")
    print(f"\nConnecting...")

    client = mqtt.Client(userdata={"receiver_positions": receiver_positions})
    client.username_pw_set(args.user, args.password)
    if args.ca:
        client.tls_set(ca_certs=args.ca)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    stop_event = threading.Event()
    threading.Thread(target=compute_loop, args=(receiver_positions, args.A, args.n, stop_event), daemon=True).start()

    print("Ready. Type actual position as 'x y' and press Enter to log. Ctrl+C to quit.\n")

    try:
        while True:
            raw = input("actual pos > ").strip()
            if not raw:
                continue
            try:
                ax, ay = map(float, raw.split())
            except ValueError:
                print("  Format: x y  (e.g. 1 1)")
                continue

            with estimate_lock:
                mac          = latest_estimate["mac"]
                heron_result = latest_estimate["heron"]
                tri_result   = latest_estimate["tri"]
                fresh        = latest_estimate["fresh"]

            if not fresh:
                print("  No estimate yet — waiting for readings from 3+ receivers.")
                continue

            row = {
                "timestamp":        datetime.now().isoformat(),
                "mac":              mac,
                "actual_x":         ax,
                "actual_y":         ay,
                "heron_x":          heron_result["x"]          if heron_result else None,
                "heron_y":          heron_result["y"]          if heron_result else None,
                "heron_method":     heron_result["method"]     if heron_result else None,
                "heron_confidence": heron_result["confidence"] if heron_result else None,
                "heron_err":        error_m(heron_result, ax, ay),
                "tri_x":            tri_result["x"]            if tri_result   else None,
                "tri_y":            tri_result["y"]            if tri_result   else None,
                "tri_method":       tri_result["method"]       if tri_result   else None,
                "tri_confidence":   tri_result["confidence"]   if tri_result   else None,
                "tri_err":          error_m(tri_result, ax, ay),
            }

            write_row(args.csv, row)

            heron_pos = f"({heron_result['x']:.2f}, {heron_result['y']:.2f})" if heron_result else "FAILED"
            tri_pos   = f"({tri_result['x']:.2f},   {tri_result['y']:.2f})" if tri_result   else "FAILED"
            print(f"  Heron : {heron_pos}  err={row['heron_err']:.2f}m" if row["heron_err"] is not None else f"  Heron : {heron_pos}")
            print(f"  Tri   : {tri_pos}  err={row['tri_err']:.2f}m"   if row["tri_err"]   is not None else f"  Tri   : {tri_pos}")
            print(f"  Logged to {args.csv}\n")

    except KeyboardInterrupt:
        pass

    stop_event.set()
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
