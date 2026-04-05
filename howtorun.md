# Medical Tracker IoT — How to Run

## Architecture

```
M5StickC Plus2 (BLE Tag)
  ↓ BLE (18-byte HMAC-signed payload)
  ↓ Bleak strips 2-byte Company ID — parser sees 16 bytes
Raspberry Pi (BLE Scanner + MQTT Publisher)
  ↓ MQTT (port 1883 plaintext / 8883 TLS)
Mosquitto Broker
  ↓ MQTT
Backend (FastAPI + InfluxDB + ACK Orchestrator)
  ↓ REST API (port 8000)
Dashboard / Frontend
```

### BLE Payload Layout (18 bytes total)

```
Firmware bytes:           RPi parser bytes (after Bleak strips Company ID):
Byte 0-1:  Company ID    (stripped by Bleak)
Byte 2-7:  MAC (6)       mfg_bytes[0:6]
Byte 8-9:  Temp (int16)  mfg_bytes[6:8]
Byte 10:   Battery       mfg_bytes[8]
Byte 11:   Flags         mfg_bytes[9]   (bit0=moving, bit1=low battery)
Byte 12-13: Seq (uint16) mfg_bytes[10:12]
Byte 14-17: HMAC (4)     mfg_bytes[12:16]
```

> **Note:** The `main_coordinator/` directory contains a legacy experimental MQTT deduplicator. It is superseded by the backend and is NOT needed. Ignore it.

---

## Step 1: MQTT Broker

### Install Mosquitto
```bash
# macOS
brew install mosquitto

# Linux
sudo apt install mosquitto mosquitto-clients
```

### Create users
```bash
mosquitto_passwd -c /etc/mosquitto/passwordfile rpi
# Enter password when prompted (e.g. 1234)
mosquitto_passwd -b /etc/mosquitto/passwordfile coordinator 1234
mosquitto_passwd -b /etc/mosquitto/passwordfile m5tag 1234
mosquitto_passwd -b /etc/mosquitto/passwordfile dashboard 1234
```

### Deploy ACL

> **WARNING:** Use the root `acl` file ONLY — not `acl.txt` or `mqtt setup/acl` (those are outdated and missing critical permissions like whitelist read for RPi).

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

# TLS (production) — uncomment and set cert paths
# listener 8883 0.0.0.0
# cafile /etc/mosquitto/ca.crt
# certfile /etc/mosquitto/server.crt
# keyfile /etc/mosquitto/server.key
```

### Start (Linux/Mac)
```bash
sudo systemctl start mosquitto
# Or run manually with logs:
mosquitto -c /etc/mosquitto/mosquitto.conf -v
```

### Start (Windows — PowerShell as Administrator)
```powershell
$env:OPENSSL_CONF="C:\Users\delvi\OneDrive\Desktop\SIT_Stuff\year2\IOT\project\certs\openssl_tls12.cnf"
mosquitto -c "C:\Program Files\mosquitto\mosquitto.conf" -v
```

> **Note:** `OPENSSL_CONF` must be set in the same terminal session before starting — without it TLS on port 8883 will fail. The `-v` flag shows verbose logs.
>
> Alternatively as a Windows service (requires PC restart after first setup for the env var to take effect):
> ```powershell
> net start mosquitto
> ```

### Verify
```bash
mosquitto_sub -h localhost -p 1883 -u dashboard -P 1234 -t "hospital/#" -v
```

---

## Step 2: InfluxDB

### Install & Setup
```bash
# Download from https://portal.influxdata.com/downloads/
# Start InfluxDB, open http://localhost:8086
# Create org: "iot"
# Create bucket: "medicine_tracking"
# Generate an All Access API token
```

### Configure backend `.env`

Create/edit `backend/.env`:
```
# MQTT
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=coordinator
MQTT_PASSWORD=1234
# MQTT_CA_CERT=/path/to/ca.crt    # Uncomment for TLS (port 8883)

# InfluxDB
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=<paste-your-token-here>
INFLUXDB_ORG=iot
INFLUXDB_BUCKET=medicine_tracking
```

> **IMPORTANT:** The code defaults to `MQTT_PORT=8883` (TLS) if not set in `.env`. Always set it explicitly.
>
> **IMPORTANT:** The `.env.example` in the repo uses `INFLUXDB_ORG=medical` and `INFLUXDB_BUCKET=tracker` — these are WRONG for this project. Use `iot` and `medicine_tracking`.
>
> **SECURITY:** If a real token is committed in `.env`, regenerate it before deploying.

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

### What starts automatically:
- Tag registry loads from `tag_registry.db`
- MQTT connects and subscribes to: scan, emergency, ack_result, command_ble_result topics
- ACK orchestrator loop runs every **10 seconds**, sends health checks every **2 minutes** per tag
- Whitelist sync publishes to retained MQTT topic every 30s
- REST API on port 8000

### Verify
```bash
curl http://localhost:8000/
```

---

## Step 4: M5StickC Plus2 Firmware

### Prerequisites
```bash
pip install platformio
```

### Create CA cert file (required for build)
The build embeds a CA cert even if TLS is disabled. Create the file or the build fails:
```bash
mkdir -p m5Stick/certs
# Copy your CA cert, OR create a dummy for dev:
echo "dummy" > m5Stick/certs/ca.crt
```

### Configure WiFi/MQTT
Edit `m5Stick/wifi_manager.cpp`:
```cpp
static const char* WIFI_SSID = "YourWiFi";
static const char* WIFI_PASSWORD = "YourPassword";
static IPAddress MQTT_IP(192, 168, 0, 5);  // Your broker IP
static const uint16_t MQTT_PORT = 1883;
static const char* MQTT_PASSWORD = "1234";  // Must match mosquitto_passwd for user "m5tag"
```

> **Note:** The MQTT username is hardcoded as `"m5tag"` in the firmware (line ~164). It cannot be changed without editing the source. The password in `wifi_manager.cpp` must match the Mosquitto password for user `m5tag`.

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
1. `checkSerialProvisioning()` — checks if `PROV_PING` is sent over serial
2. `hmacInit()` — loads HMAC key from NVS
   - **No key:** animated cat screen, waits **indefinitely** for serial provisioning (no timeout)
   - **Key found:** starts BLE advertising + GATT server
3. Initializes sensors, WiFi module, BLE ack tracker
4. M5 uses its BLE MAC address as MQTT identity for all topics

### BLE advertising intervals:
- **Stationary:** 200ms (interval=320, units of 0.625ms)
- **Moving:** 100ms (interval=160)

### Buttons:
- **BtnA:** Manual BLE ack test
- **BtnB single press:** Trigger lost BLE WiFi session (waits 500ms for second press)
- **BtnB double press:** Trigger temp alert WiFi session (both presses within 500ms)

### Display modes:
- **Default:** MAC, temp, battery, movement, WiFi/MQTT status
- **FIND ME:** Yellow text, cat face (during find command)
- **LOST BLE:** Red text, WiFi fallback info
- **TEMP HIGH:** Red text, large temperature reading
- **Provisioning cat:** Animated cat waiting for serial provisioning

---

## Step 5: Provision Tags

### Option A: Serial provisioning (recommended)

M5 must be showing the **cat screen** (no key in NVS — either first flash or after NVS erase).

```bash
# Find USB port:
#   Windows: check Device Manager → Ports (COMx)
ls /dev/cu.usb*          # macOS
ls /dev/ttyUSB*          # Linux

# Provision (Windows)
python provision.py flash --port COM3 --medicine "PANADOL" --tag-id "m5tag"

# Provision (Linux/Mac)
python provision.py flash --port /dev/cu.usbserial-XXXX --medicine "PANADOL" --tag-id "m5tag"
```

This: reads MAC from M5 → generates 32-byte HMAC key → flashes to NVS → registers in SQLite → M5 reboots.

### Option B: API provisioning
```bash
# Check USB
curl http://localhost:8000/api/provision/usb

# Flash (Windows)
curl -X POST "http://localhost:8000/api/provision/flash?port=COM3&medicine_name=PANADOL"

# Flash (Linux/Mac)
curl -X POST "http://localhost:8000/api/provision/flash?port=/dev/cu.usbserial-XXXX&medicine_name=PANADOL"
```

### Option C: Manual registration (no USB — registers medicine in DB only, key must already be in M5 NVS)
```bash
python provision.py register --mac 4C:75:25:CB:7E:0A --medicine "PANADOL"
```

### Check / manage registered tags
```bash
python provision.py list
python provision.py get-key --mac 4C:75:25:CB:7E:0A
python provision.py remove --mac 4C:75:25:CB:7E:0A
```

### Manage tags
```bash
python provision.py list
python provision.py get-key --mac 4C:75:25:CB:86:62
python provision.py remove --mac 4C:75:25:CB:86:62
```

Or via API:
```bash
curl http://localhost:8000/api/tags
curl -X DELETE http://localhost:8000/api/tags/4C:75:25:CB:86:62
```

---

## Step 6: Raspberry Pi (BLE Scanner)

### Copy ALL required files to RPi
```bash
scp Rasp_PI/mqtt_publisher.py \
    Rasp_PI/m5stick_parser.py \
    Rasp_PI/requirements.txt \
    Rasp_PI/install_service.sh \
    Rasp_PI/mqtt_publisher.service \
    pi@<RPI_IP>:~/iot_project/
```

> **IMPORTANT:** All files must be in the **same directory** before running the installer.

### Install
```bash
ssh pi@<RPI_IP>
cd ~/iot_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure
Edit `mqtt_publisher.py`:
```python
MQTT_BROKER = "<broker-ip>"    # Your MQTT broker IP
MQTT_PORT = 1883               # 8883 for TLS
MQTT_USERNAME = "rpi"
MQTT_PASSWORD = "1234"
RECEIVER_ID = "rpi_a"          # Unique per RPi (rpi_a, rpi_b, etc.)
```

### Run manually
```bash
python3 mqtt_publisher.py
```

### Or install as service (auto-start on boot)
```bash
cd ~/iot_project
chmod +x install_service.sh
sudo ./install_service.sh
```

> **Note:** Run `install_service.sh` from the directory containing the Python files. It copies them to `/home/pi/iot_project/` and generates the systemd service file dynamically.

### Service commands
```bash
sudo systemctl status mqtt_publisher
sudo systemctl restart mqtt_publisher
sudo journalctl -u mqtt_publisher -f
```

### How the RPi scanner works:
1. Scans BLE for 5 seconds (context manager — clean start/stop)
2. Publishes scan data to MQTT
3. Checks for pending ACK/command requests from backend
4. Stops scanner, executes GATT writes (ACK or find), resumes
5. Repeat

---

## Step 7: Verify Everything

### Check scanning
```bash
mosquitto_sub -h localhost -p 1883 -u dashboard -P 1234 \
  -t "hospital/medicine/scan/#" -v
```

### Check HMAC auth
```bash
curl http://localhost:8000/api/auth_stats
# Should show: {"unknown_mac": 0, "missing_hmac": 0, "invalid_hmac": 0}
```

### Check ACK health
```bash
curl http://localhost:8000/api/ack_status
```

### Check system status
```bash
curl http://localhost:8000/api/status
```

### Find My Tag (BLE — tag in normal mode)
```bash
curl -X POST http://localhost:8000/api/find/4C:75:25:CB:86:62
```

### Find My Tag (WiFi — tag in lost BLE mode)
Press BtnB on M5 first to enter WiFi mode, then:
```bash
mosquitto_pub -h localhost -p 1883 -u coordinator -P 1234 \
  -t "hospital/medicine/command/4C:75:25:CB:86:62" -m "find"
```

### Trigger emergency search
```bash
curl -X POST http://localhost:8000/api/emergency/4C:75:25:CB:86:62
```

### Check whitelist sync
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
| POST | `/api/tags?mac=XX&medicine_name=YY` | Register tag (generates key) |
| DELETE | `/api/tags/{mac}` | Remove tag |
| GET | `/api/provision/usb` | Scan USB serial ports |
| POST | `/api/provision/flash?port=XX&medicine_name=YY` | Full serial provisioning |
| POST | `/api/find/{mac}` | Find tag (BLE + WiFi) |
| POST | `/api/emergency/{mac}` | Trigger emergency search |
| GET | `/api/medicines` | Current medicine status |
| GET | `/api/data?minutes=60` | Raw scan data |
| GET | `/api/medicine/{mac}/history?hours=24` | Position history |
| GET | `/api/alerts?severity=critical` | System alerts |
| GET | `/api/status` | System stats + MQTT connection |
| GET | `/api/ack_status` | ACK orchestrator state per tag |
| GET | `/api/auth_stats` | HMAC failure counters |

---

## MQTT Topics

| Topic | Direction | Publisher | Subscriber |
|-------|-----------|-----------|------------|
| `hospital/medicine/scan/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/rssi_only/{mac}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/emergency/{mac}` | M5 → Backend | M5 (WiFi) | Backend |
| `hospital/medicine/command/{mac}` | Backend → M5 | Backend | M5 (WiFi) |
| `hospital/medicine/ack_check/{mac}` | Backend → RPi | Backend | RPi |
| `hospital/medicine/ack_result/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/medicine/command_ble/{mac}` | Backend → RPi | Backend | RPi |
| `hospital/medicine/command_ble_result/{receiver_id}` | RPi → Backend | RPi | Backend |
| `hospital/system/whitelist` | Backend → RPi | Backend | RPi (retained) |
| `hospital/system/rpi_status/{receiver_id}` | RPi → Dashboard | RPi | Dashboard |

> **Note:** `hospital/medicine/ack/{mac}` is published by M5 as a WiFi-path ack for find commands. The backend does NOT subscribe to this topic — it only processes `ack_result` from RPi.

---

## File Reference

| File | Purpose |
|------|---------|
| `backend/.env` | Backend config — MQTT + InfluxDB credentials |
| `backend/config.py` | All env vars with defaults — **source of truth for settings** |
| `backend/tag_registry.py` | SQLite tag database module |
| `backend/tag_registry.db` | Generated SQLite database (not committed) |
| `backend/hmac_verify.py` | HMAC-SHA256 verification logic |
| `backend/ack_orchestrator.py` | ACK health check orchestration |
| `backend/mqtt_handler.py` | MQTT message processing + HMAC auth |
| `backend/database.py` | InfluxDB read/write operations |
| `backend/trilaterate.py` | RSSI → distance + weighted centroid |
| `provision.py` | Tag provisioning CLI |
| `acl` | MQTT ACL — **canonical version, deploy this one** |
| `acl.txt` | OUTDATED copy — do not use |
| `mqtt setup/acl` | OUTDATED copy — do not use |
| `Rasp_PI/mqtt_publisher.py` | RPi BLE scanner + MQTT publisher |
| `Rasp_PI/m5stick_parser.py` | BLE payload parser (16-byte after Bleak strips Company ID) |
| `Rasp_PI/install_service.sh` | RPi systemd service installer |
| `m5Stick/ble.cpp` | BLE advertising + GATT server (ACK + command characteristics) |
| `m5Stick/hmac.cpp` | HMAC-SHA256 signing + NVS key + serial provisioning |
| `m5Stick/wifi_manager.cpp` | WiFi/MQTT session management |
| `m5Stick/main.cpp` | Boot flow + display modes + button handlers |
| `m5Stick/platformio.ini` | PlatformIO build config |
| `main_coordinator/` | LEGACY — experimental deduplicator, not needed |

---

## All Environment Variables

See `backend/config.py` for defaults. Set in `backend/.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MQTT_HOST` | `localhost` | MQTT broker address |
| `MQTT_PORT` | `8883` | MQTT port (set 1883 for plaintext dev) |
| `MQTT_USERNAME` | `` | MQTT auth username |
| `MQTT_PASSWORD` | `` | MQTT auth password |
| `MQTT_CA_CERT` | `None` | Path to CA cert for TLS (omit for plaintext) |
| `MQTT_TOPIC` | `hospital/medicine/scan/#` | Scan subscription topic |
| `INFLUXDB_URL` | `http://localhost:8086` | InfluxDB address |
| `INFLUXDB_TOKEN` | `` | InfluxDB API token |
| `INFLUXDB_ORG` | `medical` | InfluxDB org (**use `iot` for this project**) |
| `INFLUXDB_BUCKET` | `medicine_tracking` | InfluxDB bucket |
| `TAG_DB_PATH` | `tag_registry.db` | SQLite tag registry path |
| `RSSI_REFERENCE` | `-59` | RSSI at 1 meter (dBm) |
| `PATH_LOSS_EXPONENT` | `2.5` | Radio path loss exponent |
| `BUFFER_TIMEOUT_SECONDS` | `10.0` | Stale buffer entry timeout |
| `POSITION_CALCULATION_INTERVAL` | `2.0` | Min seconds between trilateration |
| `ACK_PERIOD_SECONDS` | `120.0` | How often to check each tag |
| `ACK_CHECK_INTERVAL_SECONDS` | `10.0` | Orchestrator loop interval |
| `ACK_MAX_ATTEMPTS` | `3` | Failures before tag_potentially_lost alert |
| `ACK_RESULT_TIMEOUT_SECONDS` | `30.0` | Timeout waiting for RPi ack result |

---

## Tag Registry Schema

SQLite database at `backend/tag_registry.db`:

```sql
CREATE TABLE tags (
    mac           TEXT PRIMARY KEY,       -- BLE MAC address
    hmac_key      BLOB NOT NULL,          -- 32-byte HMAC-SHA256 key
    medicine_name TEXT NOT NULL,          -- Human-readable name
    tag_id        TEXT NOT NULL DEFAULT 'm5tag',  -- MQTT identity (metadata)
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Managed via `provision.py` CLI or `POST /api/tags` API.

---

## InfluxDB Measurements

### `medicine_status` (raw scan data, 30-day retention)
- **Tags:** `mac`, `receiver_id`, `medicine`
- **Fields:** `distance` (float), `moving` (bool), `temperature` (float), `battery` (int), `sequence_number` (int)

### `medicine_position` (trilateration results, 90-day retention)
- **Tags:** `mac`, `medicine`
- **Fields:** `x`, `y`, `z` (float), `accuracy` (float), `receiver_count` (int)

### `alerts` (system alerts, 1-year retention)
- **Tags:** `mac`, `alert_type`, `severity`, `medicine`
- **Fields:** `message` (string), metadata fields

---

## BLE GATT Characteristics

Service UUID: `12345678-1234-1234-1234-1234567890ab`

| Characteristic | UUID | Property | Purpose |
|----------------|------|----------|---------|
| ACK | `abcdefab-1234-1234-1234-abcdefabcdef` | Write | RPi writes `"ack"` → M5 calls `recordBleAck()` |
| Command | `abcdefab-1234-1234-1234-abcdefabcdf0` | Write | RPi writes `"find"` → M5 plays melody |

---

## MQTT Payload Examples

### Scan message (RPi → Backend)
Topic: `hospital/medicine/scan/rpi_a`
```json
{
  "timestamp": "2026-03-20T10:30:45Z",
  "receiver_id": "rpi_a",
  "mac": "4C:75:25:CB:86:62",
  "rssi": -65,
  "temperature": 24.5,
  "battery": 85,
  "sequence_number": 42,
  "moving": false,
  "hmac": "a3f81b2c"
}
```

### Emergency message (M5 → Backend, over WiFi)
Topic: `hospital/medicine/emergency/4C:75:25:CB:86:62`
```json
{
  "mac": "4C:75:25:CB:86:62",
  "status": "lost_ble",
  "temp_c": 25.5,
  "battery_percent": 70
}
```

### ACK check request (Backend → RPi)
Topic: `hospital/medicine/ack_check/4C:75:25:CB:86:62`
```json
{"emergency": false}
```

### ACK result (RPi → Backend)
Topic: `hospital/medicine/ack_result/rpi_a`
```json
{
  "mac": "4C:75:25:CB:86:62",
  "status": "success",
  "receiver_id": "rpi_a",
  "timestamp": "2026-03-20T10:31:00Z"
}
```

### BLE command result (RPi → Backend)
Topic: `hospital/medicine/command_ble_result/rpi_a`
```json
{
  "mac": "4C:75:25:CB:86:62",
  "command": "find",
  "status": "success",
  "receiver_id": "rpi_a",
  "timestamp": "2026-03-20T10:31:05Z"
}
```

### Whitelist (Backend → RPi, retained)
Topic: `hospital/system/whitelist`
```json
["4C:75:25:CB:86:62", "AA:BB:CC:DD:EE:FF"]
```

### Command to M5 (Backend → M5, over WiFi)
Topic: `hospital/medicine/command/4C:75:25:CB:86:62`
```
find
```
or
```
resume_ble
```

---

## ACL Permissions

See root `acl` file for the full ACL. Summary:

| User | Can Write | Can Read |
|------|-----------|----------|
| `rpi` | scan, rssi_only, rpi_status, ack_result, command_ble_result | whitelist, ack_check, command_ble |
| `m5tag` | emergency, ack | command |
| `coordinator` | rssi, command, coordinator_status, whitelist, ack_check, command_ble | scan, emergency, ack_result, command_ble_result |
| `dashboard` | (none) | hospital/# (everything) |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| M5 shows cat screen | Not provisioned — run `provision.py flash` |
| M5 build fails with missing `ca.crt` | Create `m5Stick/certs/ca.crt` (even a dummy file works for dev) |
| RPi no scan data | Check MQTT_BROKER IP, whitelist sync, `PUBLISH_ONLY_KNOWN_TAGS` |
| RPi whitelist empty | Check ACL — use root `acl` file, NOT `acl.txt` |
| Backend rejects all messages | Check `api/auth_stats` — HMAC key mismatch means re-provision |
| ACK keeps failing | BlueZ is flaky — check `api/ack_status` for success rate |
| Find not working (BLE) | Tag must be seen in RPi's current 5s scan window |
| Find not working (WiFi) | M5 must be in WiFi mode (BtnB or lost BLE timeout) |
| Whitelist not updating | Check ACL — RPi user needs `read hospital/system/whitelist` |
| MQTT "denied publish" in broker logs | Check ACL matches the root `acl` file, restart Mosquitto |
| InfluxDB 401 Unauthorized | Token expired — regenerate in InfluxDB UI, update `.env` |
| InfluxDB writes fail with 404 | Bucket name wrong — use `medicine_tracking`, not `tracker` |
| Backend connects on wrong port | Set `MQTT_PORT=1883` explicitly in `.env` (code defaults to 8883) |
