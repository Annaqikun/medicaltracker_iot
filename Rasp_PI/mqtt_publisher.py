import asyncio
import json
import time
import logging
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from bleak import BleakScanner, BleakClient
import paho.mqtt.client as mqtt
from m5stick_parser import M5StickCNameParser
import psutil
import ssl
import os


# MQTT Settings
MQTT_BROKER = "192.168.0.5"
MQTT_PORT = 1883
MQTT_QOS = 1
MQTT_USERNAME = "rpi"
MQTT_PASSWORD = "1234"

RECEIVER_ID = "rpi_a"

KNOWN_MEDICINE_TAGS = [
    "4C:75:25:CB:86:62",
]

PUBLISH_ONLY_KNOWN_TAGS = True
COMPANY_ID = 0xFFFF
SCAN_WINDOW_SECONDS = 5

# --- Logging setup ---
logger = logging.getLogger("ble_scanner")
logger.setLevel(logging.INFO)

_file_handler = RotatingFileHandler("ble_scanner.log", maxBytes=1_000_000, backupCount=3)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

# --- RSSI Smoothing ---
_rssi_history: dict[str, deque] = {}

def smooth_rssi(mac: str, rssi: int) -> int:
    if mac not in _rssi_history:
        _rssi_history[mac] = deque(maxlen=5)
    _rssi_history[mac].append(rssi)
    return round(sum(_rssi_history[mac]) / len(_rssi_history[mac]))


parser = M5StickCNameParser()
ACK_SERVICE_UUID        = "12345678-1234-1234-1234-1234567890ab"
ACK_CHARACTERISTIC_UUID = "abcdefab-1234-1234-1234-abcdefabcdef"

# --- ACK state ---
_seen_devices: dict[str, tuple] = {}    # {mac: (BLEDevice, last_seen_time)}
_pending_checks: set[str] = set()       # routine ack requests from backend
_emergency_checks: set[str] = set()     # emergency — blind GATT search


class MQTTPublisher:

    def __init__(self, broker: str, port: int, receiver_id: str,
                 username: str = None, password: str = None):
        self.broker = broker
        self.port = port
        self.receiver_id = receiver_id
        self.client = mqtt.Client(client_id=f"{receiver_id}_{int(time.time())}")
        if username and password:
            self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

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
            client.subscribe(f"hospital/medicine/ack_check/#", qos=1)
            logger.info(f"Subscribed to ack check requests")
        else:
            logger.error(f"Connection failed with code {rc}")
            self.connected = False

    def _on_publish(self, client, userdata, mid):
        self.publish_count += 1

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnect (code {rc}), reconnecting...")
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_message(self, client, userdata, message):
        if message.topic.startswith("hospital/medicine/ack_check/"):
            mac = message.topic.split("/")[-1].upper()
            try:
                payload = json.loads(message.payload.decode("utf-8"))
                emergency = payload.get("emergency", False)
            except Exception:
                emergency = False

            if emergency:
                _emergency_checks.add(mac)
                _pending_checks.discard(mac)
                logger.info(f"[ACK] EMERGENCY search requested for {mac}")
            else:
                if mac not in _emergency_checks:
                    _pending_checks.add(mac)
                logger.info(f"[ACK] Routine check requested for {mac}")

    def publish_ack_result(self, mac: str, status: str):
        topic = f"hospital/medicine/ack_result/{self.receiver_id}"
        payload = {
            'mac': mac,
            'status': status,
            'receiver_id': self.receiver_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        self.client.publish(topic, json.dumps(payload), qos=1)
        logger.info(f"[ACK] Result: {mac} -> {status}")

    def connect(self):
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            if self.port == 8883:
                self.client.tls_set(ca_certs=os.path.expanduser("~/iot_project/certs/ca.crt"))
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            timeout = 15
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
            'moving': parsed_data.get('moving', False),
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


# --- GATT ACK (called ONLY when scanner is fully stopped) ---

async def send_ble_ack(mac: str, publisher):
    """GATT ack using MAC string. Scanner MUST be fully stopped before calling."""
    try:
        logger.info(f"[ACK] Connecting to {mac}...")
        async with BleakClient(mac, timeout=10.0) as client:
            logger.info(f"[ACK] Connected to {mac}, writing ack char...")
            await client.write_gatt_char(ACK_CHARACTERISTIC_UUID, b"ack")
            logger.info(f"[ACK] Write complete — SUCCESS for {mac}")
            publisher.publish_ack_result(mac, "success")
    except Exception as e:
        logger.info(f"[ACK] FAILED for {mac}: {type(e).__name__}: {repr(e)}")
        publisher.publish_ack_result(mac, "failed")
    finally:
        _pending_checks.discard(mac)
        _emergency_checks.discard(mac)


# --- Main loop: alternating scan and ack phases ---

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
    last_heartbeat = time.time()

    try:
        while True:
            # ========== SCAN PHASE ==========
            # BleakScanner as context manager — auto-starts, auto-stops cleanly
            scan_results = {}

            def callback(device, advertisement_data):
                mac = device.address.upper()
                device_name = device.name if device.name else "Unknown"

                is_known_tag = mac in [tag.upper() for tag in KNOWN_MEDICINE_TAGS]
                if PUBLISH_ONLY_KNOWN_TAGS and not is_known_tag:
                    return

                if device_name == "MED_TAG":
                    scan_results[mac] = (device, advertisement_data)

            async with BleakScanner(callback, scanning_mode="active"):
                await asyncio.sleep(SCAN_WINDOW_SECONDS)
            # Scanner is now FULLY STOPPED and cleaned up
            await asyncio.sleep(3)  # give BlueZ time to fully release adapter

            # Process all collected advertisements
            for mac, (device, adv_data) in scan_results.items():
                _seen_devices[mac] = (device, time.time())
                raw_rssi = adv_data.rssi
                mfg_bytes = adv_data.manufacturer_data.get(COMPANY_ID)
                if mfg_bytes:
                    parsed_data = parser.parse_manufacturer(mfg_bytes, mac)
                    if parsed_data:
                        smoothed = smooth_rssi(mac, raw_rssi)
                        if publisher.publish_scan(mac, smoothed, parsed_data):
                            publisher.publish_rssi(mac, smoothed)

            # Heartbeat
            if time.time() - last_heartbeat >= 60:
                publisher.publish_heartbeat()
                last_heartbeat = time.time()

            # ========== ACK PHASE ==========
            # Scanner is fully stopped — GATT connect is safe here
            logger.info(f"[ACK] Pending: {_pending_checks} | Emergency: {_emergency_checks} | Seen: {list(_seen_devices.keys())}")

            # Routine acks — only if we saw the device this scan cycle
            for mac in list(_pending_checks):
                if mac in scan_results:
                    logger.info(f"[ACK] Routine ack for {mac}")
                    await send_ble_ack(mac, publisher)

            # Emergency acks — try even if not seen (blind search)
            for mac in list(_emergency_checks):
                logger.info(f"[ACK] Emergency ack for {mac}")
                await send_ble_ack(mac, publisher)

    except KeyboardInterrupt:
        logger.info("Stopping scanner...")
    finally:
        publisher.disconnect()
        logger.info(f"Total messages published: {publisher.publish_count}")


def main():
    try:
        asyncio.run(scan_and_publish())
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()
