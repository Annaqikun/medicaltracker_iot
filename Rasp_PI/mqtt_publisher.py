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
MQTT_BROKER = "192.168.137.1"
MQTT_PORT = 8883
MQTT_QOS = 1
MQTT_USERNAME = "rpi"
MQTT_PASSWORD = "1234"

RECEIVER_ID = "rpi_a"

KNOWN_MEDICINE_TAGS = []

PUBLISH_ONLY_KNOWN_TAGS = True
WHITELIST_TOPIC = "hospital/system/whitelist"
COMPANY_ID = 0xFFFF
SCAN_WINDOW_SECONDS = 3

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
COMMAND_CHARACTERISTIC_UUID = "abcdefab-1234-1234-1234-abcdefabcdf0"

# --- ACK state ---
_seen_devices: dict[str, tuple] = {}    # {mac: (BLEDevice, last_seen_time)}
_pending_checks: set[str] = set()       # routine ack requests from backend
_emergency_checks: set[str] = set()     # emergency — blind GATT search

# --- Command state ---
_pending_commands: dict[str, str] = {}  # {mac: command_string}


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
            client.subscribe(f"hospital/medicine/command_ble/#", qos=1)
            client.subscribe(WHITELIST_TOPIC, qos=1)
            logger.info(f"Subscribed to ack check requests, BLE command requests, and {WHITELIST_TOPIC}")
        else:
            logger.error(f"Connection failed with code {rc}")
            self.connected = False

    def _on_message(self, client, userdata, message):
        global KNOWN_MEDICINE_TAGS
        logger.info(f"Received message on topic: {message.topic}")

        if message.topic == WHITELIST_TOPIC:
            try:
                raw = message.payload.decode("utf-8")
                logger.info(f"Whitelist payload: {raw}")
                whitelist = json.loads(raw)
                if isinstance(whitelist, list):
                    KNOWN_MEDICINE_TAGS = [mac.upper() for mac in whitelist]
                    logger.info(f"Whitelist updated ({len(KNOWN_MEDICINE_TAGS)} MACs): {KNOWN_MEDICINE_TAGS}")
                else:
                    logger.warning(f"Invalid whitelist format: {whitelist}")
            except Exception as e:
                logger.error(f"Failed to parse whitelist: {e}")

        elif message.topic.startswith("hospital/medicine/ack_check/"):
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

        elif message.topic.startswith("hospital/medicine/command_ble/"):
            mac = message.topic.split("/")[-1].upper()
            _pending_commands[mac] = "find"
            logger.info(f"[CMD] BLE find requested for {mac}")

    def _on_publish(self, client, userdata, mid):
        self.publish_count += 1

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnect (code {rc}), reconnecting...")
        else:
            logger.info("Disconnected from MQTT broker")

    def publish_ble_command_result(self, mac: str, command: str, status: str):
        topic = f"hospital/medicine/command_ble_result/{self.receiver_id}"
        payload = {
            'mac': mac,
            'command': command,
            'status': status,
            'receiver_id': self.receiver_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        self.client.publish(topic, json.dumps(payload), qos=1)
        logger.info(f"[CMD] Result: {mac} {command} -> {status}")

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
            'sequence_number': parsed_data['sequence_number'],
            'moving': parsed_data.get('moving', False),
            'hmac': parsed_data['hmac'],
        }
        result = self.client.publish(topic, json.dumps(payload), qos=MQTT_QOS)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(
                f"SCAN | MAC: {mac} | "
                f"RSSI: {rssi} dBm | Temp: {parsed_data['temperature']}C | "
                f"Bat: {parsed_data['battery']}% | Seq: {parsed_data['sequence_number']} | "
                f"HMAC: {parsed_data['hmac']}"
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


# --- GATT Command (called ONLY when scanner is fully stopped) ---

async def send_ble_command(mac: str, command: str, publisher):
    """Send a BLE command (e.g. 'find') to a tag via GATT write. Scanner MUST be stopped."""
    try:
        logger.info(f"[CMD] Connecting to {mac} to send '{command}'...")
        async with BleakClient(mac, timeout=10.0) as client:
            await client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, command.encode())
            logger.info(f"[CMD] SUCCESS — sent '{command}' to {mac}")
            publisher.publish_ble_command_result(mac, command, "success")
    except Exception as e:
        logger.info(f"[CMD] FAILED for {mac}: {type(e).__name__}: {repr(e)}")
        publisher.publish_ble_command_result(mac, command, "failed")
    finally:
        _pending_commands.pop(mac, None)


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
                device_name = (
                    advertisement_data.local_name
                    or device.name
                    or "Unknown"
                )

                is_known_tag = mac in [tag.upper() for tag in KNOWN_MEDICINE_TAGS]
                if PUBLISH_ONLY_KNOWN_TAGS and not is_known_tag:
                    return

                existing = scan_results.get(mac)

                if device_name == "MED_TAG":
                    if existing is None:
                        scan_results[mac] = {
                            "device": device,
                            "adv_data": advertisement_data,
                            "matched_name": True,
                        }
                    else:
                        existing["device"] = device
                        existing["matched_name"] = True

                        # Prefer the frame that actually carries manufacturer data.
                        if advertisement_data.manufacturer_data.get(COMPANY_ID):
                            existing["adv_data"] = advertisement_data
                        elif not existing["adv_data"].manufacturer_data.get(COMPANY_ID):
                            existing["adv_data"] = advertisement_data
                    return

                # Some adapters report manufacturer data on scan response frames
                # without the local name. If we've already matched the tag name for
                # this MAC, keep the richer frame so RSSI/manufacturer data updates.
                if (
                    existing is not None
                    and existing.get("matched_name")
                    and advertisement_data.manufacturer_data.get(COMPANY_ID)
                ):
                    existing["device"] = device
                    existing["adv_data"] = advertisement_data

            async with BleakScanner(callback, scanning_mode="active"):
                await asyncio.sleep(SCAN_WINDOW_SECONDS)
            # Scanner is now FULLY STOPPED and cleaned up
            await asyncio.sleep(1)  # give BlueZ time to fully release adapter

            # Process all collected advertisements
            for mac, result in scan_results.items():
                device = result["device"]
                adv_data = result["adv_data"]
                _seen_devices[mac] = (device, time.time())
                raw_rssi = adv_data.rssi
                logger.info(
                    f"[SCANDBG] MAC={mac} name={adv_data.local_name or device.name or 'Unknown'} "
                    f"rssi={raw_rssi} mfg_keys={list(adv_data.manufacturer_data.keys())}"
                )
                mfg_bytes = adv_data.manufacturer_data.get(COMPANY_ID)
                if mfg_bytes:
                    logger.info(f"[SCANDBG] MAC={mac} mfg_len={len(mfg_bytes)}")
                    parsed_data = parser.parse_manufacturer(mfg_bytes, mac)
                    if parsed_data:
                        if publisher.publish_scan(mac, raw_rssi, parsed_data):
                            publisher.publish_rssi(mac, raw_rssi)
                    else:
                        logger.warning(
                            f"[SCANDBG] Parser returned None for {mac} with "
                            f"mfg_len={len(mfg_bytes)} bytes={mfg_bytes.hex()}"
                        )
                else:
                    logger.warning(
                        f"[SCANDBG] No manufacturer data for {mac}; "
                        f"available_keys={list(adv_data.manufacturer_data.keys())}"
                    )

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

            # ========== COMMAND PHASE ==========
            # Send BLE commands only if MAC was seen in this scan cycle
            for mac, command in list(_pending_commands.items()):
                if mac in scan_results:
                    logger.info(f"[CMD] Sending BLE command '{command}' to {mac}")
                    await send_ble_command(mac, command, publisher)
                else:
                    logger.info(f"[CMD] {mac} not seen this scan cycle — skipping '{command}'")

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
