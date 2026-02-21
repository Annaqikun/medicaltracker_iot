import asyncio
import json
import time
from datetime import datetime
from bleak import BleakScanner
import paho.mqtt.client as mqtt
from m5stick_parser import M5StickCNameParser
import psutil


# MQTT Settings
MQTT_BROKER = "192.168.1.9"  # Change to router IP for production
MQTT_PORT = 1883           # 8883 for TLS in production
MQTT_QOS = 1
MQTT_USERNAME = "rpi4_zone_a"
MQTT_PASSWORD = "1234"


RECEIVER_ID = "rpi4_zone_a"


KNOWN_MEDICINE_TAGS = [
    "4C:75:25:CB:7E:0A",
]


PUBLISH_ONLY_KNOWN_TAGS = False
DEVICE_NAME_PATTERN = "MediTag"



parser = M5StickCNameParser()

class MQTTPublisher:


    def __init__(self, broker: str, port: int, receiver_id: str,
                 username: str = None, password: str = None):
        self.broker = broker
        self.port = port
        self.receiver_id = receiver_id
        self.client = mqtt.Client(client_id=f"{receiver_id}_{int(time.time())}")

        # Set credentials if provided
        if username and password:
            self.client.username_pw_set(username, password)

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.client.on_disconnect = self._on_disconnect

        self.connected = False
        self.publish_count = 0
    
    def publish_rssi(self, mac:str,rssi:int):
        topic = f"hospital/medicine/rssi_only/{mac}"

        payload = {
            'timestamp':datetime.utcnow().isoformat() + 'Z',
            'receiver_id': self.receiver_id,
            'mac': mac,
            'rssi': rssi
        }

        self.client.publish(topic,json.dumps(payload),qos=MQTT_QOS)

    def _on_connect(self, client, userdata, flags, rc):

        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
            self.connected = True
        else:
            print(f"Connection failed with code {rc}")
            self.connected = False

    def _on_publish(self, client, userdata, mid):

        self.publish_count += 1

    def _on_disconnect(self, client, userdata, rc):

        print(f"Disconnected from MQTT broker (code {rc})")
        self.connected = False

    def connect(self):
        """Connect to MQTT broker"""
        try:
            print(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            # Wait for connection
            timeout = 5
            while not self.connected and timeout > 0:
                time.sleep(0.1)
                timeout -= 0.1

            if not self.connected:
                raise Exception("Connection timeout")

        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            raise

    def publish_scan(self, mac: str, rssi: int, parsed_data: dict):
        topic = f"hospital/medicine/scan/{self.receiver_id}"

        # Build JSON payload matching task requirements
        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': self.receiver_id,
            'mac': mac,
            'rssi': rssi,
            'temperature': parsed_data['temperature'],
            'battery': parsed_data['battery'],
            'medicine': parsed_data['medicine'],
            'sequence_number': parsed_data['sequence_number'],
        }


        # Publish with QoS 1 
        result = self.client.publish(
            topic,
            json.dumps(payload),
            qos=MQTT_QOS
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"Published: {parsed_data['medicine']} ({mac}) | RSSI: {rssi} dBm | Temp: {parsed_data['temperature']}°C | Battery: {parsed_data['battery']}% | Seq: {parsed_data['sequence_number']}")
            return True
        else:
            print(f"Publish failed for {mac}: {result.rc}")
            return False

    def publish_heartbeat(self):

        topic = f"hospital/system/rpi_status/{self.receiver_id}"

        # Get system info of the router (currently  raps pi)


        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': self.receiver_id,
            'uptime': int(time.time() - psutil.boot_time()),
            'scan_count': self.publish_count,
            'status': 'online'
        }

        self.client.publish(topic, json.dumps(payload), qos=1)

    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()


async def scan_and_publish():
    """Main scanning and publishing loop"""
    print("=" * 70)
    print("M5StickC BLE to MQTT Publisher")
    print("=" * 70)
    print(f"MQTT Broker:    {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Receiver ID:    {RECEIVER_ID}")
    if KNOWN_MEDICINE_TAGS and PUBLISH_ONLY_KNOWN_TAGS:
        print(f"Publishing only known tags: {len(KNOWN_MEDICINE_TAGS)}")
        for tag in KNOWN_MEDICINE_TAGS:
            print(f"  - {tag}")
    else:
        print(f"Publishing all M5StickC devices")
    print("=" * 70)
    print()


    publisher = MQTTPublisher(
        MQTT_BROKER,
        MQTT_PORT,
        RECEIVER_ID,
        MQTT_USERNAME,
        MQTT_PASSWORD
    )

    try:
        publisher.connect()
    except Exception as e:
        print(f"\nCannot start: MQTT broker not available")
        print(f"\nMake sure Mosquitto is running:")
        return

    print("Scanning for M5StickC devices... (Press Ctrl+C to stop)\n")

    def callback(device, advertisement_data):
        mac  = device.address.upper()
        device_name = device.name if device.name else "Unknown"
        rssi = advertisement_data.rssi
        COMPANY_ID = 0xFFFF

        is_known_tag = mac in [tag.upper() for tag in KNOWN_MEDICINE_TAGS]

        if PUBLISH_ONLY_KNOWN_TAGS and not is_known_tag:
            return

        if device_name == "MED_TAG":
            mfg_bytes = advertisement_data.manufacturer_data.get(COMPANY_ID)
            if mfg_bytes:
                parsed_data = parser.parse_manufacturer(mfg_bytes, mac)

                if parsed_data:
                    publisher.publish_scan(mac,rssi,parsed_data)
                    publisher.publish_rssi(mac,rssi)

    scanner = BleakScanner(callback, scanning_mode="active")

    await scanner.start()

    last_heartbeat = time.time()

    try:
        while True:
            await asyncio.sleep(1)

            # Send heartbeat every 60 seconds
            if time.time() - last_heartbeat >= 60:
                publisher.publish_heartbeat()
                last_heartbeat = time.time()

    except KeyboardInterrupt:
        print("\n\nStopping scanner...")
    finally:
        await scanner.stop()
        publisher.disconnect()
        print(f"\nTotal messages published: {publisher.publish_count}")
        print("Disconnected from MQTT broker")


def main():

    try:
        asyncio.run(scan_and_publish())
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()