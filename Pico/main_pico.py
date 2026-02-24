import bluetooth
import time
import network
import json
from umqtt.simple import MQTTClient
from micropython import const


PICO_ID = 2  # Change to 2 for second Pico
TAG_MAC = "4C:75:25:CB:7E:0A"

# WiFi Configuration
WIFI_SSID = "SINGTEL-7988"      
WIFI_PASSWORD = "gPwRxmhaWrD3"   

MQTT_BROKER = "192.168.1.9"
MQTT_PORT = 1883
MQTT_CLIENT_ID = f"pico_{PICO_ID}"



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
    
print(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")

try:
    mqtt_client = MQTTClient(
        MQTT_CLIENT_ID,
        MQTT_BROKER,
        port=MQTT_PORT,
        keepalive=60,
        user = "pico_2",
        password = "1234"
    )
    mqtt_client.connect()
    print("Connected to MQTT broker")
except Exception as e:
    print(f"MQTT connection failed: {e}")
    raise


# Setup BLE
ble = bluetooth.BLE()
ble.active(True)
# last_device_name = None
# last_parsed_data = None
scan_count = 0

def parse_device_name(name, mac):
    """Parse M5StickC device name: MT{temp}_{battery}_{seq}"""
    try:
        import re
        match = re.match(r'MT(\d+)_(\d+)_(\d+)', name)
        if not match:
            return None
        
        temp_raw = int(match.group(1))
        battery = int(match.group(2))
        seq = int(match.group(3))
        
        return {
            'mac': mac,
            'temperature': round(temp_raw / 100.0, 2),
            'battery': battery,
            'status_flags_raw': 0,
            'status': {
                'moving': False,
                'temperature_alert': False,
                'wifi_active': False
            },
            'sequence_number': seq,
            'device_name': name
        }
    except:
        return None



def publish_scan(mac, rssi, parsed_data):

    global scan_count

    topic = f"hospital/medicine/scan/pico_{PICO_ID}"
    
    payload = {
        'receiver_id': f"pico_{PICO_ID}",
        'timestamp': f"{time.time()}", 
        'mac': mac,
        'rssi': rssi,
        'temperature': parsed_data['temperature'],
        'battery': parsed_data['battery'],
        'sequence_number': parsed_data['sequence_number'],
        'medicine': parsed_data['medicine'],
    }
    
    try:
        mqtt_client.publish(
            topic.encode(),
            json.dumps(payload).encode(),
            qos=1
        )
        scan_count += 1
        print(f"Scan {scan_count}: {parsed_data['medicine']} ({mac}) | RSSI: {rssi} dBm | Temp: {parsed_data['temperature']}°C | Bat: {parsed_data['battery']}%")
        return True
    except Exception as e:
        print(f"Publish failed: {e}")
        return False

def parse_mfg_data(adv_data):
    data = bytes(adv_data)
    i = 0
    while i < len(data):
        length = data[i]
        if length == 0:
            break
        ad_type = data[i + 1]
        if ad_type == 0xFF:
            payload = data[i + 2: i + 1 +length]
            if len(payload) >= 23:
                medicine = payload[2 + 6 : 2+6+12].decode('ascii',errors = 'ignore').strip()
                temp_hi = payload[20]
                temp_lo = payload[21]
                temp_raw = (temp_hi << 8) | temp_lo
                if temp_raw > 32767:
                    temp_raw -= 65536
                temperature = round(temp_raw/100.0,2)
                battery = payload[22]
                moving = bool(payload[23] & 0x01) if len(payload) >=24 else False
                sequence_number = ((payload[24] << 8) | payload[25]) if len(payload) >= 26 else 0
                return{
                    'medicine': medicine,
                    'temperature': temperature,
                    'battery': battery,
                    'moving': moving,
                    'sequence_number': sequence_number
                }
        i += 1 + length
    return None




def publish_rssi(mac, rssi):
    topic = f"hospital/medicine/rssi_only/{mac}"

    payload = {
        'timestamp': f"{time.time()}",
        'receiver_id': f"pico_{PICO_ID}",
        'mac': mac,
        'rssi': rssi
    }

    try:
        mqtt_client.publish(
            topic.encode(),
            json.dumps(payload).encode(),
            qos=1
        )
    except Exception as e:
        print(f"RSSI publish failed: {e}")


def publish_heartbeat():
    topic = f"hospital/system/pico_status/pico_{PICO_ID}"
    
    payload = {
        'timestamp': f"{time.time()}",
        'device_id': f"pico_{PICO_ID}",
        'scan_count': scan_count,
        'status': 'online'
    }
    
    try:
        mqtt_client.publish(
            topic.encode(),
            json.dumps(payload).encode(),
            qos=1
        )
    except Exception as e:
        print(f"Heartbeat failed: {e}")


def parse_adv_name(adv_data):
    """Extract device name from advertisement data"""
    try:
        data = bytes(adv_data)
        i = 0
        while i < len(data):
            length = data[i]
            if length == 0:
                break

            ad_type = data[i + 1]

            # Type 0x09 = Complete Local Name
            # Type 0x08 = Shortened Local Name
            if ad_type == 0x09 or ad_type == 0x08:
                name_bytes = data[i + 2:i + 1 + length]
                return name_bytes.decode('utf-8')

            i += 1 + length
    except:
        pass
    return None

def irq(event, data):
    """BLE interrupt handler"""
    
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        mac = ':'.join(['{:02X}'.format(b) for b in bytes(addr)])
        
        # Check if this is our target M5StickC
        if mac.upper() == TAG_MAC:
            # Parse device name from advertisement
            parsed = parse_mfg_data(adv_data)
            if parsed:
                publish_scan(mac,rssi, parsed)
                publish_rssi(mac, rssi)
            
    
    elif event == _IRQ_SCAN_DONE:
        ble.gap_scan(0, 60000, 30000, True)

print(f"Scanning for {TAG_MAC} and publishing scans to MQTT...")
print("Press Ctrl+C to stop")

ble.irq(irq)
ble.gap_scan(0, 60000, 30000, True)

last_heartbeat = time.time()

try:
    while True:
        # Publish heartbeat every 60 seconds
        if time.time() - last_heartbeat >= 60:
            publish_heartbeat()
            last_heartbeat = time.time()
        
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping...")
    ble.gap_scan(None)
    mqtt_client.disconnect()
    print(f"Total scans published: {scan_count}")
    print("Disconnected")


