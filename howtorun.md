# Medical Tracker IoT — How to Run

## Architecture

```
M5StickC Plus2 (BLE Tag)
  ↓ BLE (18-byte HMAC-signed payload)
Raspberry Pi (BLE Scanner + MQTT Publisher)
  ↓ MQTT
Mosquitto Broker
  ↓ MQTT
Backend (FastAPI + InfluxDB + ACK Orchestrator)
  ↓ REST API
Dashboard / Frontend
```

---

## Step 1: MQTT Broker

### Install Mosquitto
```bash
# macOS
brew install mosquitto

# Linux
sudo apt install mosquitto mosquitto-clients

# Windows: download from https://mosquitto.org/download/
```

### Create users
```bash
mosquitto_passwd -c /etc/mosquitto/passwordfile rpi
mosquitto_passwd -b /etc/mosquitto/passwordfile coordinator 1234
mosquitto_passwd -b /etc/mosquitto/passwordfile m5tag 1234
mosquitto_passwd -b /etc/mosquitto/passwordfile dashboard 1234
```

### Deploy ACL
```bash
sudo cp acl /etc/mosquitto/acl
```

### Mosquitto config (`/etc/mosquitto/mosquitto.conf`)
```
allow_anonymous false
password_file /etc/mosquitto/passwordfile
acl_file /etc/mosquitto/acl

# Plaintext (dev)
listener 1883 0.0.0.0
protocol mqtt

# TLS (production)
# listener 8883 0.0.0.0
# cafile /etc/mosquitto/ca.crt
# certfile /etc/mosquitto/server.crt
# keyfile /etc/mosquitto/server.key
```

### Start
```bash
# Linux
sudo systemctl start mosquitto

# macOS
mosquitto -c /usr/local/etc/mosquitto/mosquitto.conf -v

# Verify
mosquitto_sub -h localhost -p 1883 -u dashboard -P 1234 -t "hospital/#" -v
```

---

## Step 2: InfluxDB

### Install
```bash
# Download from https://portal.influxdata.com/downloads/
# Start InfluxDB, open http://localhost:8086
# Create org: "iot", bucket: "medicine_tracking"
# Generate an API token
```

### Configure backend
Edit `backend/.env`:
```
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=coordinator
MQTT_PASSWORD=1234

INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=<your-token>
INFLUXDB_ORG=iot
INFLUXDB_BUCKET=medicine_tracking
```

---

## Step 3: Backend Server

### Install dependencies
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Start
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Verify
```bash
curl http://localhost:8000/
```

### What starts automatically:
- Tag registry loads from `tag_registry.db`
- MQTT connects and subscribes to scan/emergency/ack/command topics
- ACK orchestrator starts (health checks every 2 min per tag)
- Whitelist sync publishes every 30s
- REST API on port 8000

---

## Step 4: M5StickC Plus2 Firmware

### Prerequisites
```bash
pip install platformio
```

### Configure WiFi/MQTT
Edit `m5Stick/wifi_manager.cpp`:
```cpp
static const char* WIFI_SSID = "YourWiFi";
static const char* WIFI_PASSWORD = "YourPassword";
static IPAddress MQTT_IP(192, 168, 0, 5);  // Broker IP
static const uint16_t MQTT_PORT = 1883;
static const char* MQTT_PASSWORD = "1234";
```

### Build and flash
```bash
cd m5Stick
pio run -t upload
```

### Monitor serial
```bash
pio device monitor -b 115200
```

### Boot flow:
1. Checks for serial provisioning (3s window)
2. Loads HMAC key from NVS
   - No key: animated cat screen, waits for provisioning
   - Key found: starts BLE + GATT server
3. Broadcasts HMAC-signed payload every 200ms (moving) or 1s (stationary)

### Buttons:
- **BtnA**: Manual BLE ack test
- **BtnB single press**: Trigger lost BLE WiFi session
- **BtnB double press**: Trigger temp alert WiFi session

---

## Step 5: Provision Tags

### Option A: Serial (recommended)
M5 must be showing cat screen (no key in NVS).

```bash
# Check USB port
ls /dev/cu.usb*          # macOS
ls /dev/ttyUSB*          # Linux

# Provision
python provision.py flash \
  --port /dev/cu.usbserial-XXXX \
  --medicine "PANADOL" \
  --tag-id "m5tag"
```

### Option B: API
```bash
curl http://localhost:8000/api/provision/usb
curl -X POST "http://localhost:8000/api/provision/flash?port=/dev/cu.usbserial-XXXX&medicine_name=PANADOL"
```

### Option C: Manual (no USB)
```bash
python provision.py register --mac 4C:75:25:CB:86:62 --medicine "PANADOL"
```

### Manage tags
```bash
python provision.py list
python provision.py get-key --mac 4C:75:25:CB:86:62
python provision.py remove --mac 4C:75:25:CB:86:62
```

---

## Step 6: Raspberry Pi (BLE Scanner)

### Copy files to RPi
```bash
scp Rasp_PI/mqtt_publisher.py Rasp_PI/m5stick_parser.py pi@<RPI_IP>:~/iot_project/
```

### Install
```bash
ssh pi@<RPI_IP>
cd ~/iot_project
python3 -m venv venv
source venv/bin/activate
pip install bleak paho-mqtt psutil
```

### Configure
Edit `mqtt_publisher.py`:
```python
MQTT_BROKER = "<broker-ip>"
MQTT_PORT = 1883
MQTT_USERNAME = "rpi"
MQTT_PASSWORD = "1234"
RECEIVER_ID = "rpi_a"          # Unique per RPi
```

### Run manually
```bash
python3 mqtt_publisher.py
```

### Or install as service
```bash
scp Rasp_PI/install_service.sh Rasp_PI/mqtt_publisher.service pi@<RPI_IP>:~/
ssh pi@<RPI_IP>
chmod +x install_service.sh
sudo ./install_service.sh
```

### Service commands
```bash
sudo systemctl status mqtt_publisher
sudo systemctl restart mqtt_publisher
sudo journalctl -u mqtt_publisher -f
```

---

## Step 7: Verify

### Check scanning works
```bash
mosquitto_sub -h localhost -p 1883 -u dashboard -P 1234 -t "hospital/medicine/scan/#" -v
```

### Check HMAC auth
```bash
curl http://localhost:8000/api/auth_stats
# {"unknown_mac": 0, "missing_hmac": 0, "invalid_hmac": 0}
```

### Check ACK health
```bash
curl http://localhost:8000/api/ack_status
```

### Find My Tag (BLE)
```bash
curl -X POST http://localhost:8000/api/find/4C:75:25:CB:86:62
```

### Find My Tag (WiFi — M5 must be in WiFi mode)
```bash
mosquitto_pub -h localhost -p 1883 -u coordinator -P 1234 \
  -t "hospital/medicine/command/4C:75:25:CB:86:62" -m "find"
```

### Emergency search
```bash
curl -X POST http://localhost:8000/api/emergency/4C:75:25:CB:86:62
```

### Check whitelist
```bash
mosquitto_sub -h localhost -p 1883 -u dashboard -P 1234 \
  -t "hospital/system/whitelist" -v
```

---

## REST API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/` | API info |
| GET | `/api/tags` | List registered tags |
| POST | `/api/tags?mac=XX&medicine_name=YY` | Register tag |
| DELETE | `/api/tags/{mac}` | Remove tag |
| GET | `/api/provision/usb` | Scan USB ports |
| POST | `/api/provision/flash?port=XX&medicine_name=YY` | Serial provision |
| POST | `/api/find/{mac}` | Find tag (BLE + WiFi) |
| POST | `/api/emergency/{mac}` | Emergency search |
| GET | `/api/medicines` | Current medicine status |
| GET | `/api/data?minutes=60` | Raw scan data |
| GET | `/api/medicine/{mac}/history?hours=24` | Position history |
| GET | `/api/alerts?severity=critical` | System alerts |
| GET | `/api/status` | System stats |
| GET | `/api/ack_status` | ACK orchestrator state |
| GET | `/api/auth_stats` | HMAC failure counters |

---

## MQTT Topics

| Topic | Direction | Publisher | Subscriber |
|-------|-----------|-----------|------------|
| `hospital/medicine/scan/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/rssi_only/{mac}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/emergency/{mac}` | M5 → Backend | M5 | Backend |
| `hospital/medicine/command/{mac}` | Backend → M5 | Backend | M5 |
| `hospital/medicine/ack/{mac}` | M5 → Backend | M5 | Backend |
| `hospital/medicine/ack_check/{mac}` | Backend → RPi | Backend | RPi |
| `hospital/medicine/ack_result/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/command_ble/{mac}` | Backend → RPi | Backend | RPi |
| `hospital/medicine/command_ble_result/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/system/whitelist` | Backend → RPi | Backend | RPi (retained) |
| `hospital/system/rpi_status/{receiver_id}` | RPi → Dashboard | RPi | Dashboard |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| M5 shows cat screen | Not provisioned — run `provision.py flash` |
| RPi no scan data | Check `MQTT_BROKER` IP and whitelist sync |
| Backend rejects messages | Check `api/auth_stats` — re-provision if HMAC mismatch |
| ACK keeps failing | BlueZ flaky — check `api/ack_status`, increase timeout |
| Find not working (BLE) | Tag must be seen in RPi's current scan window |
| Find not working (WiFi) | Tag must be in WiFi mode (BtnB or lost BLE) |
| Whitelist not updating | Check ACL — RPi needs `read hospital/system/whitelist` |
| MQTT denied publish | Check ACL, restart Mosquitto after changes |
| InfluxDB 401 | Regenerate token in InfluxDB UI, update `.env` |
