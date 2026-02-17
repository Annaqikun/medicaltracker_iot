import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
import threading


MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_QOS = 1


class MessageDeduplicator:

    def __init__(self, broker, port):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id="coordinator")
        self.client.username_pw_set("coordinator","1234")

        # Track last seen sequence number per MAC address
        self.last_seq = {}
        self.seq_lock = threading.Lock()

        # Statistics
        self.received_count = 0
        self.published_count = 0
        self.duplicate_count = 0

        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
            self.client.subscribe("hospital/medicine/scan/#", qos=MQTT_QOS)
            print("Subscribed to: hospital/medicine/scan/#")
            print("Waiting for messages...\n")
        else:
            print(f"Connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            mac = data.get('mac')
            seq = data.get('sequence_number')

            if mac is None or seq is None:
                print(f"Invalid message from {msg.topic} (missing mac or sequence_number)")
                return

            self.received_count += 1

            with self.seq_lock:
                last = self.last_seq.get(mac)

                # Duplicate check: skip if we already saw this sequence for this MAC
                if last is not None and seq <= last:
                    self.duplicate_count += 1
                    return

                # New sequence number — update tracker
                self.last_seq[mac] = seq

            # Log and publish
            temp = data.get('temperature', 'N/A')
            battery = data.get('battery', 'N/A')
            receiver = data.get('receiver_id', '?')
            print(f"New  | MAC: {mac} | Seq: {seq} | From: {receiver} | RSSI: {data.get('rssi', '?')} dBm | Temp: {temp}°C | Bat: {battery}%")

            self.publish_medicine_data(data)

        except Exception as e:
            print(f"Error processing message: {e}")

    def publish_medicine_data(self, data):
        mac = data['mac']
        receiver_id = data['receiver_id']

        topic = f"hospital/medicine/rssi/{receiver_id}/{mac}"

        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': receiver_id,
            'mac': mac,
            'rssi': data['rssi'],
            'temperature': data['temperature'],
            'battery': data['battery'],
            'status_flags': data['status_flags'],
            'status': data['status'],
            'sequence_number': data['sequence_number'],
            'device_name': data['device_name']
        }

        try:
            result = self.client.publish(
                topic,
                json.dumps(payload),
                qos=MQTT_QOS
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.published_count += 1
            else:
                print(f"Publish failed: {result.rc}")

        except Exception as e:
            print(f"Error publishing: {e}")

    def publish_status(self):
        topic = "hospital/system/coordinator_status"

        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'received_count': self.received_count,
            'published_count': self.published_count,
            'duplicate_count': self.duplicate_count,
            'tracked_macs': list(self.last_seq.keys()),
            'status': 'online'
        }

        try:
            self.client.publish(topic, json.dumps(payload), qos=1)
        except Exception as e:
            print(f"Status publish failed: {e}")

    def start(self):
        print("=" * 70)
        print("MQTT Deduplicator (Sequence Number)")
        print("=" * 70)
        print(f"MQTT Broker:  {self.broker}:{self.port}")
        print(f"Dedup by:     MAC address + sequence number")
        print("=" * 70)
        print()

        try:
            self.client.connect(self.broker, self.port, keepalive=60)
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            return

        self.client.loop_start()
        time.sleep(2)

        try:
            last_status = time.time()

            while True:
                time.sleep(1)

                if time.time() - last_status >= 60:
                    self.publish_status()
                    last_status = time.time()

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            print(f"\nTotal received:   {self.received_count}")
            print(f"Total published:  {self.published_count}")
            print(f"Duplicates skip:  {self.duplicate_count}")
            print("Stopped")


def main():
    coordinator = MessageDeduplicator(MQTT_BROKER, MQTT_PORT)
    coordinator.start()


if __name__ == "__main__":
    main()
