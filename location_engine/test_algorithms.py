"""
Live localization test — runs on coordinator PC.

Subscribes to hospital/medicine/rssi_only/#, collects RSSI from all receivers
for the same M5StickC, then runs both trilateration and Heron's formula and
prints estimated vs actual position.

Just run: python location_engine/test_algorithms.py
"""

import argparse
import json
import math
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt

from engine import rssi_to_distance, trilaterate, heron_localize


# State

latest_readings = defaultdict(dict)
readings_lock = threading.Lock()
READING_MAX_AGE = 10.0
MIN_RECEIVERS = 3


# MQTT

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected")
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

        if receiver_id is None or rssi is None:
            return
        if receiver_id not in receiver_positions:
            return

        with readings_lock:
            latest_readings[mac][receiver_id] = {
                "rssi": rssi,
                "timestamp": time.time(),
            }
    except Exception as e:
        print(f"[MQTT] Parse error: {e}")


# Localization

def get_fresh_receivers(mac, receiver_positions, A, n):
    now = time.time()
    result = []
    with readings_lock:
        for receiver_id, data in latest_readings[mac].items():
            if now - data["timestamp"] > READING_MAX_AGE:
                continue
            if receiver_id not in receiver_positions:
                continue
            x, y = receiver_positions[receiver_id]
            d = rssi_to_distance(data["rssi"], A=A, n=n)
            result.append((x, y, d, receiver_id, data["rssi"]))
    return result


def error_m(estimated, actual):
    if estimated is None or actual is None:
        return None
    return math.dist(estimated, actual)


# Display

def print_status(mac, fresh):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] MAC: {mac}")
    for x, y, d, rid, rssi in fresh:
        print(f"  {rid:12s}  pos=({x},{y})  rssi={rssi:.1f} dBm  dist={d:.2f} m")


def print_estimates(tri, heron, actual=None):
    if tri:
        err = f"  error={error_m(tri, actual):.3f} m" if actual else ""
        print(f"  Trilateration : ({tri[0]:.2f}, {tri[1]:.2f}){err}")
    else:
        print("  Trilateration : FAILED")
    if heron:
        err = f"  error={error_m(heron, actual):.3f} m" if actual else ""
        print(f"  Heron         : ({heron[0]:.2f}, {heron[1]:.2f}){err}")
    else:
        print("  Heron         : FAILED")


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
    parser.add_argument("--broker",    default="172.20.10.4")           # change if broker IP changes
    parser.add_argument("--port",      type=int, default=8883)          # same here change if needed
    parser.add_argument("--user",      default="coordinator")
    parser.add_argument("--password",  default="1234")
    parser.add_argument("--ca",        default="/etc/mosquitto/ca.crt")
    parser.add_argument("--receivers", nargs="+",                        # update x,y if you move the Pis
                        default=["rpi_a:0,0", "rpi_b:5,0", "rpi_c:2.5,4"],
                        metavar="ID:X,Y")
    parser.add_argument("--A",         type=float, default=-80.0)        # calibrate using hakim_test/findA
    parser.add_argument("--n",         type=float, default=3.0)          # 2=open space, 3-4=indoors
    args = parser.parse_args()

    receiver_positions = parse_receivers(args.receivers)

    print(f"Broker    : {args.broker}:{args.port}")
    print(f"Receivers : {receiver_positions}")
    print(f"A={args.A} dBm  n={args.n}")

    client = mqtt.Client(userdata={"receiver_positions": receiver_positions})
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
        sys.exit(1)

    if len(known_macs) == 1:
        mac = known_macs[0]
        print(f"MAC: {mac}")
    else:
        print("Detected MACs:")
        for i, m in enumerate(known_macs):
            print(f"  [{i}] {m}")
        mac = known_macs[int(input("Select index: "))]

    session_results = []

    print("\nPlace M5 at a known spot, press Enter, type actual x y.")
    print("Ctrl+C to finish.\n")

    try:
        while True:
            input("[Enter when M5 is in position] ")

            fresh = get_fresh_receivers(mac, receiver_positions, args.A, args.n)
            if len(fresh) < MIN_RECEIVERS:
                print(f"  Only {len(fresh)} receiver(s) with data, need {MIN_RECEIVERS}. Try again.")
                continue

            receivers_xyz = [(x, y, d) for x, y, d, _, _ in fresh]
            tri   = trilaterate(receivers_xyz)
            heron = heron_localize(receivers_xyz)

            print_status(mac, fresh)

            actual = None
            raw = input("  Actual position (x y) or blank to skip: ").strip()
            if raw:
                ax, ay = map(float, raw.split())
                actual = (ax, ay)

            print_estimates(tri, heron, actual)

            if actual:
                session_results.append((error_m(tri, actual), error_m(heron, actual)))

    except KeyboardInterrupt:
        pass

    if session_results:
        tri_errs   = [r[0] for r in session_results if r[0] is not None]
        heron_errs = [r[1] for r in session_results if r[1] is not None]
        print("\nSession summary")
        if tri_errs:
            print(f"  Trilateration  mean={sum(tri_errs)/len(tri_errs):.3f} m  max={max(tri_errs):.3f} m")
        if heron_errs:
            print(f"  Heron          mean={sum(heron_errs)/len(heron_errs):.3f} m  max={max(heron_errs):.3f} m")
        if tri_errs and heron_errs:
            winner = "Trilateration" if sum(tri_errs)/len(tri_errs) < sum(heron_errs)/len(heron_errs) else "Heron"
            print(f"  Winner: {winner}")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
