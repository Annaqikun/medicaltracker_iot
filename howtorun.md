# Hospital Medicine Tracking System - Setup Guide

## Architecture Overview

```
M5StickC (BLE Beacon) --> Pico W / RPi4 (BLE Scanner) --> Mosquitto (MQTT Broker) --> Main Computer (Deduplicator)
```

| Device | Role | Protocol |
|--------|------|----------|
| M5StickC Plus2 | BLE beacon broadcasting sensor data | BLE advertisement |
| Pico W / RPi4 | BLE scanner, MQTT publisher | BLE + MQTT |
| Main Computer | MQTT broker (Mosquitto) + Deduplicator | MQTT |

## MQTT Topic Structure

| Topic | Purpose | Publisher |
|-------|---------|-----------|
| `hospital/medicine/scan/{receiver_id}` | Full scan data (temp, battery, RSSI, seq) | Pico / RPi |
| `hospital/medicine/rssi_only/{mac}` | RSSI-only lightweight data | Pico / RPi |
| `hospital/medicine/rssi/{receiver_id}/{mac}` | Deduplicated data | Main computer |
| `hospital/system/pico_status/pico_{id}` | Pico heartbeat | Pico |
| `hospital/system/rpi_status/{receiver_id}` | RPi heartbeat | RPi |
| `hospital/system/coordinator_status` | Coordinator heartbeat | Main computer |

---

## Step 1: Generate TLS Certificates

From the project folder:

```powershell
cd "<project_folder>"

# Generate CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes -subj "/CN=MosquittoCA"

# Generate server key + CSR
openssl req -newkey rsa:4096 -keyout server.key -out server.csr -nodes -subj "/CN=<BROKER_IP>"

# Sign server cert with CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365
```

## Step 2: Create MQTT Users

From the Mosquitto install directory (run as Administrator):

```powershell
cd "C:\Program Files\mosquitto"

# First user (-c creates the file, prompts for password)
mosquitto_passwd -c passwordfile rpi4_zone_a

# Additional users (-b appends, password inline)
mosquitto_passwd -b passwordfile pico_1 <PASSWORD>
mosquitto_passwd -b passwordfile pico_2 <PASSWORD>
mosquitto_passwd -b passwordfile coordinator <PASSWORD>
mosquitto_passwd -b passwordfile dashboard <PASSWORD>
```

## Step 3: Create ACL File

Create an `acl` file in the project folder:

```
# RPi4
user rpi4_zone_a
topic write hospital/medicine/scan/rpi4_zone_a
topic write hospital/medicine/rssi_only/#
topic write hospital/system/rpi_status/rpi4_zone_a

# Pico 1
user pico_1
topic write hospital/medicine/scan/pico_1
topic write hospital/medicine/rssi_only/#
topic write hospital/system/pico_status/pico_1

# Pico 2
user pico_2
topic write hospital/medicine/scan/pico_2
topic write hospital/medicine/rssi_only/#
topic write hospital/system/pico_status/pico_2

# Coordinator (main_computer)
user coordinator
topic read hospital/medicine/scan/#
topic write hospital/medicine/rssi/#
topic write hospital/system/coordinator_status

# Dashboard - read only
user dashboard
topic read hospital/#
```

## Step 4: Configure Mosquitto

Replace the top of `C:\Program Files\mosquitto\mosquitto.conf`:

```
# Non-TLS listener (port 1883)
listener 1883 0.0.0.0
allow_anonymous false
password_file C:/Program Files/mosquitto/passwordfile
acl_file <project_folder>/acl

# TLS listener (port 8883)
listener 8883 0.0.0.0
allow_anonymous false
password_file C:/Program Files/mosquitto/passwordfile
acl_file <project_folder>/acl
cafile <project_folder>/ca.crt
certfile <project_folder>/server.crt
keyfile <project_folder>/server.key
```

## Step 5: Add Credentials to Code

### mqtt_publisher.py (RPi)
```python
MQTT_USERNAME = "rpi4_zone_a"
MQTT_PASSWORD = "<PASSWORD>"
```

### main_computer.py (Coordinator)
Add after creating the MQTT client:
```python
self.client = mqtt.Client(client_id="coordinator")
self.client.username_pw_set("coordinator", "<PASSWORD>")
```

### main_pico.py (Pico)
```python
mqtt_client = MQTTClient(
    MQTT_CLIENT_ID, MQTT_BROKER,
    port=MQTT_PORT, keepalive=60,
    user="pico_1", password="<PASSWORD>"  # or pico_2 for second Pico
)
```

---

## Running the System

Start in this order:

### 1. Start Mosquitto Broker (Admin terminal)
```powershell
# Kill any existing instance
net stop mosquitto

# Start with config
cd "C:\Program Files\mosquitto"
mosquitto -c mosquitto.conf -v
```

### 2. Start Main Computer (Deduplicator)
```powershell
cd <project_folder>
python main_computer.py
```

### 3. Start RPi Publisher
```powershell
cd <project_folder>
myenv/Scripts/activate
python mqtt_publisher.py
```

### 4. Start Pico W
Upload `main_pico.py` to the Pico as `main.py` and power on:
```powershell
mpremote cp main_pico.py :main.py
mpremote reset
```

### 5. Power on M5StickC
Already flashed with `m5_stick_code.cpp` via Arduino IDE. Just plug in.

---

## Verifying the System

### Subscribe to topics
```powershell
# All hospital data
mosquitto_sub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "hospital/#" -v

# Scan data only
mosquitto_sub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "hospital/medicine/scan/#" -v

# RSSI only
mosquitto_sub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "hospital/medicine/rssi_only/#" -v

# Heartbeats
mosquitto_sub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "hospital/system/#" -v
```

### Test ACL (should be denied)
```powershell
mosquitto_pub -h localhost -p 1883 -u dashboard -P <PASSWORD> -t "hospital/medicine/scan/test" -m "should fail"
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Port 1883 already in use | `taskkill /IM mosquitto.exe /F` (run as Admin) |
| "not authorised" error | Check username matches password file and ACL |
| Pico WiFi not connecting | Check SSID/password, move closer to router, reset Pico |
| No data from Pico in deduplicator | RPi may be reporting same sequence first (dedup working correctly) |
| M5StickC draining battery fast | Reduce display brightness, increase broadcast interval |
