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
        keepalive=60
    )
    mqtt_client.connect()
    print("Connected to MQTT broker")
except Exception as e:
    print(f"MQTT connection failed: {e}")
    raise


# Setup BLE
ble = bluetooth.BLE()
ble.active(True)
last_device_name = None
last_parsed_data = None
vote_count = 0

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



def publish_vote(mac, rssi, parsed_data):

    global vote_count
    
    topic = f"election/votes/pico_{PICO_ID}"
    
    payload = {
        'receiver_id': f"pico_{PICO_ID}",
        'timestamp': f"{time.time()}", 
        'mac': mac,
        'rssi': rssi,
        'temperature': parsed_data['temperature'],
        'battery': parsed_data['battery'],
        'status_flags': parsed_data['status_flags_raw'],
        'status': parsed_data['status'],
        'sequence_number': parsed_data['sequence_number'],
        'device_name': parsed_data['device_name']
    }
    
    try:
        mqtt_client.publish(
            topic.encode(),
            json.dumps(payload).encode(),
            qos=1
        )
        vote_count += 1
        print(f"Vote {vote_count}: {parsed_data['device_name']} ({mac}) | RSSI: {rssi} dBm | Temp: {parsed_data['temperature']}°C | Bat: {parsed_data['battery']}%")
        return True
    except Exception as e:
        print(f"Publish failed: {e}")
        return False




def publish_heartbeat():
    topic = f"hospital/system/pico_status/pico_{PICO_ID}"
    
    payload = {
        'timestamp': f"{time.time()}",
        'device_id': f"pico_{PICO_ID}",
        'vote_count': vote_count,
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
    global last_device_name, last_parsed_data
    
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        mac = ':'.join(['{:02X}'.format(b) for b in bytes(addr)])
        
        # Check if this is our target M5StickC
        if mac.upper() == TAG_MAC:
            # Parse device name from advertisement
            device_name = parse_adv_name(adv_data)
            
            if device_name and device_name.startswith("MT"):
                # Parse the device name
                parsed_data = parse_device_name(device_name, mac)
                
                if parsed_data:
                    # Only publish if data changed 
                    if device_name != last_device_name:
                        last_device_name = device_name
                        last_parsed_data = parsed_data
                        publish_vote(mac, rssi, parsed_data)
                    # Uncomment below to pubnlighs all data (debugging)
                    # publish_vote(mac, rssi, parsed_data)
            else:
                # Device name not available yet, just report RSSI
                print(f"Found tag! MAC: {mac} | RSSI: {rssi} | adv_type: {adv_type} (waiting for name...)")
    
    elif event == _IRQ_SCAN_DONE:
        ble.gap_scan(0, 60000, 30000, True)

print(f"Scanning for {TAG_MAC} and publishing votes to MQTT...")
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
    print(f"Total votes published: {vote_count}")
    print("Disconnected")


