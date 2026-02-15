import socket
import numpy as np
from scipy.optimize import least_squares
import time
from datetime import datetime, timedelta


UDP_IP = "0.0.0.0" 
UDP_PORT = 5005
TX_POWER = -59 
LOOP_DELAY = 0.5
TIMEOUT_SECONDS = 3  

SENSORS = {
    0: {'name': 'Raspberry Pi', 'x': 2.0, 'y': 3.0},
    1: {'name': 'Pico 1',       'x': 0.0, 'y': 0.0},
    2: {'name': 'Pico 2',       'x': 4.0, 'y': 0.0}
}

def rssi_to_dist(rssi):
    if rssi == 0: return 0.0
    return 10**((TX_POWER - rssi) / (10 * 2))

def trilaterate(sensor_positions, distances):
    def residuals(point, positions, dists):
        return [np.linalg.norm(point - p) - d for p, d in zip(positions, dists)]
    initial_guess = np.mean(sensor_positions, axis=0)
    result = least_squares(residuals, initial_guess, args=(sensor_positions, distances))
    return result.x

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(False)

current_dists = {}
last_update = {}  # Track when each device last reported
center_point = np.mean([[s['x'], s['y']] for s in SENSORS.values()], axis=0)

print(f"Monitoring Distances on Port {UDP_PORT}...")
print("Waiting for device reports (min 1 device, max 3 devices)...\n")

while True:
    try:

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                line = data.decode().strip()
                if line.startswith("REPORT"):
                    _, s_id, rssi = line.split(',')
                    s_id, rssi = int(s_id), int(rssi)
                    current_dists[s_id] = rssi_to_dist(rssi)
                    last_update[s_id] = datetime.now()
            except BlockingIOError:
                break


        now = datetime.now()
        stale_devices = [s_id for s_id, last_time in last_update.items() 
                        if (now - last_time).total_seconds() > TIMEOUT_SECONDS]
        for s_id in stale_devices:
            del current_dists[s_id]
            del last_update[s_id]


        if current_dists:
            print("\n--- SENSOR READINGS ---")
            active_count = len(current_dists)
            print(f"Active Devices: {active_count}/3")
            
            for s_id, dist in sorted(current_dists.items()):
                print(f"{SENSORS[s_id]['name']}: {dist:.2f} m")
            

            if active_count == 3:
                active_ids = list(current_dists.keys())
                pos_list = np.array([[SENSORS[i]['x'], SENSORS[i]['y']] for i in active_ids])
                dist_list = np.array([current_dists[i] for i in active_ids])
                
                target_xy = trilaterate(pos_list, dist_list)
                final_dist = np.linalg.norm(target_xy - center_point)
                print(f"TRILATERATION: Position ({target_xy[0]:.2f}, {target_xy[1]:.2f})")
                print(f"FINAL DISTANCE: {final_dist:.2f} m")
            

            elif active_count == 2:
                active_ids = list(current_dists.keys())
                pos_list = np.array([[SENSORS[i]['x'], SENSORS[i]['y']] for i in active_ids])
                dist_list = np.array([current_dists[i] for i in active_ids])
                
                target_xy = trilaterate(pos_list, dist_list)
                final_dist = np.linalg.norm(target_xy - center_point)
                print(f"BILATERATION: Estimated position ({target_xy[0]:.2f}, {target_xy[1]:.2f})")
                print(f"FINAL DISTANCE: {final_dist:.2f} m (from center)")
            

            else:
                only_id = list(current_dists.keys())[0]
                print(f"SINGLE DEVICE: Direct distance measurement")
                print(f"FINAL DISTANCE: {current_dists[only_id]:.2f} m (from {SENSORS[only_id]['name']})")

        time.sleep(LOOP_DELAY)

    except KeyboardInterrupt:
        print("\nShutting down...")
        break
    except Exception as e:
        print(f"Error: {e}")
        continue

sock.close()