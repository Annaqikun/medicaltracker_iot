

import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
from collections import defaultdict
import threading


MQTT_BROKER = "localhost"  
MQTT_PORT = 1883
MQTT_QOS = 1

# Election timing
VOTE_COLLECTION_PERIOD = 2 
ELECTION_INTERVAL = 5       



class ElectionCoordinator:

    
    def __init__(self, broker, port):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id="coordinator")
        
        # Vote storage: {mac_address: {device_id: vote_data}}
        self.votes = defaultdict(dict)
        self.vote_lock = threading.Lock()
        
        # Statistics
        self.election_count = 0
        self.publish_count = 0
        self.last_winner = None
        
        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
    
    def _on_connect(self, client, userdata, flags, rc):
        """Called when connected to MQTT broker"""
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
            # Subscribe to all election votes
            self.client.subscribe("election/votes/#", qos=MQTT_QOS)
            print("Subscribed to: election/votes/#")
            print("Waiting for votes...\n")
        else:
            print(f"Connection failed with code {rc}")
    
    def _on_message(self, client, userdata, msg):

        try:
            # Parse vote
            vote_data = json.loads(msg.payload.decode())
            device_id = vote_data.get('receiver_id')
            mac = vote_data.get('mac')
            rssi = vote_data.get('rssi')
            
            if not all([device_id, mac, rssi]):
                print(f"Invalid vote from {msg.topic}")
                return
            
            # Store vote
            with self.vote_lock:
                self.votes[mac][device_id] = vote_data
            
            # Print vote received
            temp = vote_data.get('temperature', 'N/A')
            battery = vote_data.get('battery', 'N/A')
            print(f"Vote: {device_id:15} | MAC: {mac} | RSSI: {rssi:4} dBm | Temp: {temp}°C | Bat: {battery}%")
            
        except Exception as e:
            print(f"Error processing vote: {e}")
    
    def run_election(self):
        with self.vote_lock:
            # Copy votes and clear for next election
            current_votes = dict(self.votes)
            self.votes.clear()
        
        if not current_votes:
            print("No votes received this round\n")
            return
        
        self.election_count += 1
        print(f"\n{'='*70}")
        print(f"ELECTION #{self.election_count}")
        print(f"{'='*70}")
        
        # Process each M5StickC (MAC address)
        for mac, device_votes in current_votes.items():
            print(f"\nM5StickC: {mac}")
            print(f"Votes received: {len(device_votes)}")
            
            # Find device with strongest RSSI (most negative = closest)
            winner_id = None
            winner_data = None
            strongest_rssi = -999  # Start with very weak signal
            
            for device_id, vote_data in device_votes.items():
                rssi = vote_data['rssi']
                print(f"  {device_id:15} | RSSI: {rssi:4} dBm")
                
                if rssi > strongest_rssi:
                    strongest_rssi = rssi
                    winner_id = device_id
                    winner_data = vote_data
            
            if winner_data:
                print(f"\nWINNER: {winner_id} (RSSI: {strongest_rssi} dBm)")
                self.last_winner = winner_id
                
                # Publish winner's medicine data
                self.publish_medicine_data(winner_data)
            else:
                print("No valid votes for this M5StickC")
        
        print(f"{'='*70}\n")
    
    def publish_medicine_data(self, vote_data):
        mac = vote_data['mac']
        receiver_id = vote_data['receiver_id']
        
        # Topic format matches original system
        topic = f"hospital/medicine/rssi/{receiver_id}/{mac}"
        
        # Build payload (same format as original system)
        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'receiver_id': receiver_id,
            'mac': mac,
            'rssi': vote_data['rssi'],
            'temperature': vote_data['temperature'],
            'battery': vote_data['battery'],
            'status_flags': vote_data['status_flags'],
            'status': vote_data['status'],
            'sequence_number': vote_data['sequence_number'],
            'device_name': vote_data['device_name']
        }
        
        try:
            result = self.client.publish(
                topic,
                json.dumps(payload),
                qos=MQTT_QOS
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.publish_count += 1
                print(f"Published: {vote_data['device_name']} | Temp: {vote_data['temperature']}°C | Battery: {vote_data['battery']}%")
            else:
                print(f"Publish failed: {result.rc}")
        
        except Exception as e:
            print(f"Error publishing: {e}")
    
    def publish_coordinator_status(self):
        topic = "hospital/system/coordinator_status"
        
        payload = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'election_count': self.election_count,
            'publish_count': self.publish_count,
            'last_winner': self.last_winner,
            'status': 'online'
        }
        
        try:
            self.client.publish(topic, json.dumps(payload), qos=1)
        except Exception as e:
            print(f"Status publish failed: {e}")
    
    def start(self):
        print("="*70)
        print("MQTT Election Coordinator")
        print("="*70)
        print(f"MQTT Broker:         {self.broker}:{self.port}")
        print(f"Vote Collection:     {VOTE_COLLECTION_PERIOD} seconds")
        print(f"Election Interval:   {ELECTION_INTERVAL} seconds")
        print("="*70)
        print()
        

        try:
            self.client.connect(self.broker, self.port, keepalive=60)
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            return
        

        self.client.loop_start()
        
        # Wait for connection
        time.sleep(2)
        
        # Main election loop
        try:
            last_status = time.time()
            
            while True:

                time.sleep(VOTE_COLLECTION_PERIOD)
                
                # Run election
                self.run_election()
                

                if time.time() - last_status >= 60:
                    self.publish_coordinator_status()
                    last_status = time.time()
                

                remaining = ELECTION_INTERVAL - VOTE_COLLECTION_PERIOD
                if remaining > 0:
                    time.sleep(remaining)
        
        except KeyboardInterrupt:
            print("\nStopping coordinator...")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            print(f"\nTotal elections: {self.election_count}")
            print(f"Total publishes: {self.publish_count}")
            print("Coordinator stopped")



def main():
    """Entry point"""
    coordinator = ElectionCoordinator(MQTT_BROKER, MQTT_PORT)
    coordinator.start()


if __name__ == "__main__":
    main()