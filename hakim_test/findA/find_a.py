# Run on Pi 4 alongside m5stack_scanner.ino on the M5 — stand 1m apart, read Avg RSSI off the M5 screen, use as A in engine.py.
import subprocess
import time

DEVICE_NAME = "MedTracker_Pi4"

def start_advertising():
    # Reset bluetooth adapter
    subprocess.run(["sudo", "hciconfig", "hci0", "up"], check=True)

    # Set advertising data: flags + complete local name
    # 0x02 0x01 0x06 = flags (General Discoverable + BR/EDR Not Supported)
    # Then length + 0x09 + name bytes
    name_hex = DEVICE_NAME.encode().hex()
    name_len = len(DEVICE_NAME) + 1  # +1 for the type byte
    adv_data = f"02 01 06 {name_len:02x} 09 {' '.join(name_hex[i:i+2] for i in range(0, len(name_hex), 2))}"

    # Set advertising data
    subprocess.run(
        ["sudo", "hcitool", "-i", "hci0", "cmd", "0x08", "0x0008"] + adv_data.split(),
        check=True
    )

    # Start advertising (non-connectable undirected)
    subprocess.run(
        ["sudo", "hcitool", "-i", "hci0", "cmd", "0x08", "0x000a", "01"],
        check=True
    )

    print(f"Broadcasting as '{DEVICE_NAME}'")
    print("Place M5Stack at known distances and record RSSI")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            print(".", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        subprocess.run(["sudo", "hcitool", "-i", "hci0", "cmd", "0x08", "0x000a", "00"])
        print("Advertising stopped.")

if __name__ == "__main__":
    start_advertising()
