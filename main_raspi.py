import asyncio
import socket
from bleak import BleakScanner


RASPI_ID = 0  # Raspberry Pi sensor ID
TAG_MAC = "4C:75:25:CB:7E:0A"
COMPUTER_IP = "192.168.1.9"  # Change to your computer's IP
UDP_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_to_computer(rssi):
    """Send RSSI reading directly to computer via UDP"""
    try:
        msg = f"REPORT,{RASPI_ID},{rssi}"
        sock.sendto(msg.encode(), (COMPUTER_IP, UDP_PORT))
        print(f"Sent: {msg}")
    except Exception as e:
        print(f"Send error: {e}")

async def main():
    print(f"Raspberry Pi (ID {RASPI_ID}) starting...")
    print(f"Scanning for {TAG_MAC}")
    print(f"Sending to {COMPUTER_IP}:{UDP_PORT}")

    def callback(device, advertisement_data):
        if device.address.upper() == TAG_MAC:
            rssi = advertisement_data.rssi
            print(f"Found tag! RSSI: {rssi}")
            send_to_computer(rssi)

    scanner = BleakScanner(callback, scanning_mode="active")
    await scanner.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())