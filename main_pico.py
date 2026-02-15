import bluetooth
import time
import network
import socket
from micropython import const


PICO_ID = 1  # Change to 2 for second Pico
TAG_MAC = "4C:75:25:CB:7E:0A"

# WiFi Configuration
WIFI_SSID = "SINGTEL-7988"      
WIFI_PASSWORD = "gPwRxmhaWrD3"   


COMPUTER_IP = "192.168.1.9"  # Change to your computer's IP
UDP_PORT = 5005


_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)


print(f"Pico {PICO_ID} starting...")
print(f"Connecting to WiFi: {WIFI_SSID}")

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)


max_wait = 10
while max_wait > 0:
    if wlan.status() < 0 or wlan.status() >= 3:
        break
    max_wait -= 1
    print('Waiting for WiFi connection...')
    time.sleep(1)
if wlan.status() != 3:
    print('WiFi connection failed!')
    print(f'Status: {wlan.status()}')
    raise RuntimeError('Network connection failed')
else:
    print('WiFi connected!')
    status = wlan.ifconfig()
    print(f'Pico IP: {status[0]}')
    print(f'Sending to: {COMPUTER_IP}:{UDP_PORT}')

# Setup BLE
ble = bluetooth.BLE()
ble.active(True)

# Setup UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_to_computer(rssi):
    """Send RSSI reading directly to computer via UDP"""
    try:
        msg = f"REPORT,{PICO_ID},{rssi}"
        sock.sendto(msg.encode(), (COMPUTER_IP, UDP_PORT))
        print(f"Sent: {msg}")
    except Exception as e:
        print(f"Send error: {e}")

def irq(event, data):
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        mac = ':'.join(['{:02X}'.format(b) for b in bytes(addr)])
        if mac.upper() == TAG_MAC:
            print(f"Found tag! RSSI: {rssi}")
            send_to_computer(rssi)
    elif event == _IRQ_SCAN_DONE:
        ble.gap_scan(0, 30000, 30000, True)

print(f"Scanning for {TAG_MAC}")
ble.irq(irq)
ble.gap_scan(0, 30000, 30000, True)

while True:
    time.sleep(1)
