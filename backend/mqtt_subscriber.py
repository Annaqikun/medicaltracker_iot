"""Standalone MQTT subscriber that writes incoming messages to InfluxDB.

Subscribe to `hospital/#` (or override via environment) and attempt to
map messages into the existing `medicine_status` measurement so the
frontend (the FastAPI backend) can read them.

Usage:
    python backend/mqtt_subscriber.py

Configure connection via `backend/.env` (same settings used by the
backend app).
"""

import json
import logging
import ssl
import time
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from influxdb_client import Point

from config import settings
from database import Database
from trilaterate import rssi_to_distance


LOG = logging.getLogger("mqtt_subscriber")


def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
    if rc == 0:
        LOG.info("Connected to MQTT broker")
        topic = getattr(settings, "MQTT_TOPIC", "hospital/#") or "hospital/#"
        client.subscribe(topic)
        LOG.info(f"Subscribed to topic: {topic}")
    else:
        LOG.error(f"Failed to connect to MQTT broker: {rc}")


def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    db: Database = userdata.get("db")
    topic = message.topic
    payload_bytes = message.payload

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        # Not JSON — store as raw string so it's still visible in DB
        payload_str = payload_bytes.decode("utf-8", errors="replace")
        try:
            p = Point("raw_mqtt").tag("topic", topic).field("payload", payload_str).time(datetime.utcnow())
            db.write_api.write(bucket=db.bucket, org=db.org, record=p)
            LOG.info(f"Wrote raw MQTT payload to Influx: topic={topic}")
        except Exception as e:
            LOG.error(f"Failed to write raw payload: {e}")
        return

    # If message contains expected fields for medicine tracking, map to medicine_status
    mac = payload.get("mac") or payload.get("address")
    rssi = payload.get("rssi")

    # Prefer receiver id from payload; otherwise parse common topic formats.
    topic_parts = topic.split("/")
    receiver_id = payload.get("receiver_id")
    if not receiver_id:
        # Expected: hospital/medicine/scan/<receiver_id>
        if len(topic_parts) >= 4 and topic_parts[1] == "medicine" and topic_parts[2] == "scan":
            receiver_id = topic_parts[3]
        # Fallback: hospital/<receiver_id>/...
        elif len(topic_parts) >= 2:
            receiver_id = topic_parts[1]
        else:
            receiver_id = "unknown"

    if mac and rssi is not None:
        try:
            rssi_val = int(rssi)
        except Exception:
            try:
                rssi_val = int(float(rssi))
            except Exception:
                LOG.warning(f"Invalid RSSI value: {rssi}")
                return

        # Convert RSSI->distance using same algorithm as the backend
        distance = rssi_to_distance(
            rssi_val,
            settings.rssi_reference,
            settings.path_loss_exponent,
        )

        medicine = payload.get("medicine", payload.get("type", "unknown"))
        temperature = payload.get("temperature")
        battery = payload.get("battery")
        moving = payload.get("moving", False)
        seq = payload.get("sequence_number") or payload.get("seq")

        success = db.write_scan(
            mac=str(mac),
            receiver_id=str(receiver_id),
            distance=distance,
            medicine=str(medicine),
            temperature=temperature,
            battery=battery,
            moving=bool(moving),
            sequence_number=seq,
            timestamp=datetime.utcnow(),
        )

        if success:
            LOG.info(f"Wrote scan for {mac} from {receiver_id} rssi={rssi_val} d={distance:.2f}m")
        else:
            LOG.error(f"Failed to write scan for {mac}")
        return

    # If JSON but doesn't match expected schema, store it as raw JSON
    try:
        p = Point("raw_mqtt").tag("topic", topic).field("payload_json", json.dumps(payload)).time(datetime.utcnow())
        db.write_api.write(bucket=db.bucket, org=db.org, record=p)
        LOG.info(f"Wrote raw JSON payload to Influx: topic={topic}")
    except Exception as e:
        LOG.error(f"Failed to write raw JSON payload: {e}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Create DB connection
    db = Database(
        url=settings.INFLUXDB_URL,
        token=settings.INFLUXDB_TOKEN,
        org=settings.INFLUXDB_ORG,
        bucket=settings.INFLUXDB_BUCKET,
    )

    client = mqtt.Client(client_id="medical_tracker_subscriber")

    # Set credentials if present
    if settings.mqtt.username:
        client.username_pw_set(settings.mqtt.username, settings.mqtt.password)

    # TLS if CA provided
    if settings.MQTT_CA_CERT:
        client.tls_set(ca_certs=settings.MQTT_CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    else:
        LOG.info("No CA cert configured — connecting without TLS")

    # Attach DB into userdata for callbacks
    client.user_data_set({"db": db})
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect and run loop
    try:
        LOG.info(f"Connecting to MQTT {settings.MQTT_HOST}:{settings.MQTT_PORT}")
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
        client.loop_start()

        # Keep running until user stops
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        LOG.info("Interrupted, shutting down")
    except Exception as e:
        LOG.error(f"MQTT subscriber error: {e}")
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        db.close()


if __name__ == "__main__":
    main()
