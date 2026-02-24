import asyncio
import json
import time
import logging
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from bleak import BleakScanner
import paho.mqtt.client as mqtt
from m5stick_parser import M5StickCNameParser
import psutil


# MQTT Settings
MQTT_BROKER = "10.132.40.168"
MQTT_PORT = 1883
MQTT_QOS = 1
MQTT_USERNAME = "rpi_a"
MQTT_PASSWORD = "1234"

RECEIVER_ID = "rpi_a"

KNOWN_MEDICINE_TAGS = [
    "4C:75:25:CB:7E:0A",
]

PUBLISH_ONLY_KNOWN_TAGS = False
COMPANY_ID = 0xFFFF

# --- Logging setup ---
# Writes to ble_scanner.log, max 1MB per file, keeps 3 old files
logger = logging.getLogger("ble_scanner")
logger.setLevel(logging.INFO)

_file_handler = RotatingFileHandler("ble_scanner.log", maxBytes=1_000_000, backupCount=3)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

# --- RSSI Smoothing ---
# Keeps last 5 RSSI readings per MAC and returns the average
_rssi_history: dict[str, deque] = {}

def smooth_rssi(mac: str, rssi: int) -> int:
    if mac not in _rssi_history:
        _rssi_history[mac] = deque(maxlen=5)
    _rssi_history[mac].append(rssi)
    return round(sum(_rssi_history[mac]) / len(_rssi_history[mac]))


parser = M5StickCNameParser()


class MQTTPublisher:

    def __init__(self, broker: str, port: int, receiver_id: str,
                 username: str = None, password: str = None):
        self.broker = broker
        self.port = port
        self.receiver_id = receiver_id
        self.client = mqtt.Client(client_id=f"{receiver_id}_{int(time.time())}")

        if username and password:
            self.client.username_pw_set(username, password)

        # Connection resilience: auto-reconnect after 1s, up to 30s backoff
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.client.on_disconnect = self._on_disconnect

        self.connected = False
        self.publish_count = 0

    def publish_rssi(self, mac: str, rssi: int):
        topic = f"hospital/medicine/rssi_only/{mac}"

        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': self.receiver_id,
            'mac': mac,
            'rssi': rssi
        }

        self.client.publish(topic, json.dumps(payload), qos=MQTT_QOS)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.broker}:{self.port}")
            self.connected = True
        else:
            logger.error(f"Connection failed with code {rc}")
            self.connected = False

    def _on_publish(self, client, userdata, mid):
        self.publish_count += 1

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            # Unexpected disconnect — paho will auto-reconnect via reconnect_delay_set
            logger.warning(f"Unexpected disconnect (code {rc}), reconnecting...")
        else:
            logger.info("Disconnected from MQTT broker")

    def connect(self):
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            timeout = 5
            while not self.connected and timeout > 0:
                time.sleep(0.1)
                timeout -= 0.1

            if not self.connected:
                raise Exception("Connection timeout")

        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def publish_scan(self, mac: str, rssi: int, parsed_data: dict):
        topic = f"hospital/medicine/scan/{self.receiver_id}"

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

        result = self.client.publish(topic, json.dumps(payload), qos=MQTT_QOS)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(
                f"SCAN | {parsed_data['medicine']} | MAC: {mac} | "
                f"RSSI: {rssi} dBm | Temp: {parsed_data['temperature']}C | "
                f"Bat: {parsed_data['battery']}% | Seq: {parsed_data['sequence_number']}"
            )
            return True
        else:
            logger.error(f"Publish failed for {mac}: {result.rc}")
            return False

    def publish_heartbeat(self):
        topic = f"hospital/system/rpi_status/{self.receiver_id}"

        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': self.receiver_id,
            'uptime': int(time.time() - psutil.boot_time()),
            'scan_count': self.publish_count,
            'status': 'online'
        }

        self.client.publish(topic, json.dumps(payload), qos=1)
        logger.info(f"Heartbeat | uptime: {payload['uptime']}s | scans: {self.publish_count}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()


async def scan_and_publish():
    logger.info("=" * 60)
    logger.info("BLE Medicine Tag Scanner starting")
    logger.info(f"Broker: {MQTT_BROKER}:{MQTT_PORT}  Receiver: {RECEIVER_ID}")
    logger.info("=" * 60)

    publisher = MQTTPublisher(
        MQTT_BROKER, MQTT_PORT, RECEIVER_ID,
        MQTT_USERNAME, MQTT_PASSWORD
    )

    try:
        publisher.connect()
    except Exception as e:
        logger.error("Cannot start: MQTT broker not available")
        return

    logger.info("Scanning for MED_TAG devices...")

    def callback(device, advertisement_data):
        mac = device.address.upper()
        device_name = device.name if device.name else "Unknown"
        raw_rssi = advertisement_data.rssi

        is_known_tag = mac in [tag.upper() for tag in KNOWN_MEDICINE_TAGS]
        if PUBLISH_ONLY_KNOWN_TAGS and not is_known_tag:
            return

        if device_name == "MED_TAG":
            mfg_bytes = advertisement_data.manufacturer_data.get(COMPANY_ID)
            if mfg_bytes:
                parsed_data = parser.parse_manufacturer(mfg_bytes, mac)
                if parsed_data:
                    # Smooth RSSI before publishing
                    smoothed = smooth_rssi(mac, raw_rssi)
                    publisher.publish_scan(mac, smoothed, parsed_data)
                    publisher.publish_rssi(mac, smoothed)

    scanner = BleakScanner(callback, scanning_mode="active")
    await scanner.start()

    last_heartbeat = time.time()

    try:
        while True:
            await asyncio.sleep(1)
            if time.time() - last_heartbeat >= 60:
                publisher.publish_heartbeat()
                last_heartbeat = time.time()

    except KeyboardInterrupt:
        logger.info("Stopping scanner...")
    finally:
        await scanner.stop()
        publisher.disconnect()
        logger.info(f"Total messages published: {publisher.publish_count}")


def main():
    try:
        asyncio.run(scan_and_publish())
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()
