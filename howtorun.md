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
| `hospital/medicine/emergency/{tag_id}` | M5Stick emergency (lost BLE, temp alert) | M5Stick |
| `hospital/medicine/command/{tag_id}` | Commands to M5Stick (e.g. "find") | Coordinator |
| `hospital/medicine/ack/{tag_id}` | M5Stick acknowledgements | M5Stick |
| `hospital/system/pico_status/pico_{id}` | Pico heartbeat | Pico |
| `hospital/system/rpi_status/{receiver_id}` | RPi heartbeat | RPi |
| `hospital/system/coordinator_status` | Coordinator heartbeat | Main computer |

## MQTT Users & ACL

| User | Purpose | Permissions |
|------|---------|-------------|
| `rpi` | Raspberry Pi publisher | Write scans, RSSI, heartbeats |
| `m5tag` | Shared M5Stick account (all tags) | Write emergency/ack, read commands |
| `coordinator` | Main computer deduplicator | Read scans/emergencies, write RSSI/commands/status |
| `dashboard` | Web dashboard (read-only) | Read all `hospital/#` topics |

---

## Step 1: Run the Automated TLS Setup Script

The setup script generates TLS certificates, creates MQTT users (including `m5tag`), configures ACL, and updates `mosquitto.conf` automatically.

### Windows (PowerShell as Administrator)
```powershell
powershell -ExecutionPolicy Bypass -File setup_mosquitto_tls.ps1
```

### Mac/Linux
```bash
chmod +x setup_mosquitto_tls.sh && ./setup_mosquitto_tls.sh
```

The script will prompt for:
- **Broker IP** (default: `192.168.137.1` — your hotspot IP)
- **RPi MQTT username/password** (default: `rpi` / `1234`)
- **M5Stick shared password** (default: `password000`)
- **Extra users** (enter `coordinator,dashboard` and set passwords for each)

The script creates:
| File | Purpose |
|------|---------|
| `password.txt` | MQTT user credentials (hashed) — includes `rpi`, `m5tag`, and any extra users |
| `acl` | Topic access control per user |
| `certs/ca.crt` | CA certificate (copy to RPi + M5Stick) |
| `certs/server.crt` | Server certificate (ECDSA) |
| `certs/server.key` | Server private key |
| `certs/openssl_tls12.cnf` | Forces TLS 1.2 (required for ESP32) |

> **Important:** The script stops Mosquitto, deletes old certs, and regenerates everything fresh. If you re-run the script, you must copy the new `ca.crt` to all devices again.

## Step 2: Add Credentials to Code

### mqtt_publisher.py (RPi)
```python
MQTT_USERNAME = "rpi"
MQTT_PASSWORD = "1234"
```

### main_computer.py (Coordinator)
```python
self.client.username_pw_set("coordinator", "<PASSWORD>")
self.client.tls_set(ca_certs=os.path.join(..., "certs", "ca.crt"))
```

### wifi_manager.cpp (M5Stick)
```cpp
static const char* MQTT_USER = "m5tag";
static const char* MQTT_PASSWORD = "password000";
```
All M5Sticks share the `m5tag` account. The tag ID (e.g. `m5tag01`) is set in `main.cpp` and used as the MQTT client ID, not the username.

> **Note:** Update `WIFI_SSID`, `WIFI_PASSWORD`, and `MQTT_IP` in `wifi_manager.cpp` to match your hotspot.

### Copy ca.crt to devices

**RPi:**
```bash
mkdir -p ~/iot_project/certs
scp certs/ca.crt <user>@<rpi_ip>:~/iot_project/certs/ca.crt
```

**M5Stick:**
Copy `certs/ca.crt` to `m5Stick/certs/ca.crt` in the project, then rebuild and flash via PlatformIO.

---

## Running the System

Start in this order:

### 1. Start Mosquitto Broker

**Option A: Run as Windows service** (if `OPENSSL_CONF` was set by the script):
```powershell
net start mosquitto
```

**Option B: Run manually with verbose logs** (recommended for debugging):
```powershell
$env:OPENSSL_CONF="<project_folder>\certs\openssl_tls12.cnf"
mosquitto -c "C:\Program Files\Mosquitto\mosquitto.conf" -v
```

> **Important:** `OPENSSL_CONF` must be set to enforce TLS 1.2. Without it, the broker uses TLS 1.3 which ESP32 cannot connect to. The setup script sets this as a system environment variable, but you may need to restart your PC for the service to pick it up.

### 2. Start Main Computer (Coordinator)
```powershell
cd <project_folder>\main_coordinator
python main_computer.py
```

### 3. Start RPi Publisher
```bash
# Via systemd service (recommended)
sudo systemctl start mqtt_publisher

# Or manually
cd ~/iot_project
source venv/bin/activate
python mqtt_publisher.py
```

### 4. Start Pico W
Upload `main_pico.py` to the Pico as `main.py` and power on:
```powershell
mpremote cp main_pico.py :main.py
mpremote reset
```

### 5. Power on M5StickC
Already flashed via PlatformIO. Just plug in or press the reset button.

### 6. Start the FastAPI backend and open the dashboard
From the `backend` folder:

```powershell
cd <project_folder>\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open the dashboard in a browser:

```text
http://127.0.0.1:8000/dashboard
```

The dashboard reads from these backend routes:

- `GET /api/medicines`
- `GET /api/alerts`
- `GET /api/status`

### 7. Seed sample InfluxDB data for frontend testing
If InfluxDB is running but empty, you can populate sample medicine and alert data without touching the backend logic:

```powershell
cd <project_folder>\database
python seed_influxdb.py
```

The script reads InfluxDB settings from `backend/.env` when available and writes sample records into the configured bucket.

---

## Verifying the System

### Subscribe to topics
```powershell
# All hospital data (port 1883, no TLS)
mosquitto_sub -h localhost -p 1883 -u coordinator -P <PASSWORD> -t "hospital/#" -v

# Emergency messages from M5Stick
mosquitto_sub -h localhost -p 1883 -u coordinator -P <PASSWORD> -t "hospital/medicine/emergency/#" -v

# Heartbeats
mosquitto_sub -h localhost -p 1883 -u dashboard -P <PASSWORD> -t "hospital/system/#" -v
```

### Test TLS connection
```powershell
openssl s_client -connect <BROKER_IP>:8883 -tls1_2 -CAfile certs/ca.crt
```
Should show `Protocol: TLSv1.2` and `Verify return code: 0 (ok)`.

### Test ACL (should be denied)
```powershell
# Dashboard cannot publish
mosquitto_pub -h localhost -p 1883 -u dashboard -P <PASSWORD> -t "hospital/medicine/scan/test" -m "should fail"
```

---

## Automating the RPi with a systemd Service

Instead of manually running `mqtt_publisher.py`, you can install it as a systemd service so it starts automatically on boot and restarts on failure.

Two files are provided in `Rasp_PI/`:
- `mqtt_publisher.service` — systemd unit file
- `install_service.sh` — one-shot setup script

### 1. Transfer files to the RPi

From your Windows machine (project root):

```powershell
scp Rasp_PI/mqtt_publisher.py Rasp_PI/m5stick_parser.py Rasp_PI/mqtt_publisher.service Rasp_PI/install_service.sh pi@<RPI_IP>:~/
```

### 2. Run the installer on the RPi

```bash
ssh pi@<RPI_IP>
# Fix Windows line endings (CRLF → LF) — required if files were created on Windows
sed -i 's/\r//' install_service.sh mqtt_publisher.service
chmod +x install_service.sh
sudo ./install_service.sh
```

> **If you see `cannot execute: required file not found`**, the script has Windows line endings. Run the `sed` command above to fix it.

The script will:
1. Copy scripts to `/home/pi/iot_project/`
2. Create a Python venv and install `bleak`, `paho-mqtt`, `psutil`
3. Install and enable the service (auto-starts on every boot)
4. Start it immediately

### 3. Managing the service

```bash
sudo systemctl status mqtt_publisher      # check status
sudo systemctl restart mqtt_publisher     # restart after config changes
sudo systemctl stop mqtt_publisher        # stop
sudo journalctl -u mqtt_publisher -f      # follow live logs
```

> The service waits for `network-online.target` before starting and auto-restarts on failure (`Restart=on-failure`).

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Port 1883 already in use | `net stop mosquitto` then `taskkill /IM mosquitto.exe /F` (Admin) |
| "not authorised" error | Check username matches password file and ACL |
| Pico WiFi not connecting | Check SSID/password, move closer to router, reset Pico |
| No data from Pico in deduplicator | RPi may be reporting same sequence first (dedup working correctly) |
| M5StickC draining battery fast | Reduce display brightness, increase broadcast interval |
| `cannot execute: required file not found` on Pi | Windows line endings — run `sed -i 's/\r//' install_service.sh mqtt_publisher.service` then retry |

---

## TLS Setup & Debugging Guide

This section covers the full TLS setup process and common issues encountered.

### How TLS Works in This Project

```
M5Stick ---(TLS 1.2)---> Mosquitto:8883 <---(TLS 1.2)--- RPi / Coordinator
                              |
                         (plain MQTT)
                              |
                         Mosquitto:1883 <--- Pico W / local clients
```

- **Port 8883**: TLS encrypted (used by M5Stick, RPi, Coordinator)
- **Port 1883**: Plain MQTT (used by Pico W and local testing)
- ESP32 (M5Stick) uses mbedTLS which only supports **TLS 1.2** — the broker must be forced to use TLS 1.2 via `OPENSSL_CONF`
- The M5Stick uses `setInsecure()` instead of `setCACert()` due to an ESP32 mbedTLS compatibility issue with self-signed CA certs. The connection is still TLS **encrypted** — it just skips server certificate verification.

### Regenerating Certificates

If you need to regenerate certs (e.g. changed broker IP):

1. Re-run the setup script (it deletes old certs automatically)
2. Copy the new `ca.crt` to RPi: `scp certs\ca.crt <user>@<rpi_ip>:~/iot_project/certs/ca.crt`
3. Copy to M5Stick: `copy certs\ca.crt m5Stick\certs\ca.crt`
4. Rebuild and reflash M5Stick firmware via PlatformIO
5. Restart the broker

### M5Stick error: `-9984 X509 Certificate verification failed`

**Cause:** The broker is using TLS 1.3 but ESP32 mbedTLS only supports TLS 1.2. This happens when `OPENSSL_CONF` is not set.

**Fix:** Start the broker with `OPENSSL_CONF` set:
```powershell
$env:OPENSSL_CONF="<project_folder>\certs\openssl_tls12.cnf"
mosquitto -c "C:\Program Files\Mosquitto\mosquitto.conf" -v
```

**Verify TLS version:**
```powershell
openssl s_client -connect <BROKER_IP>:8883 -tls1_2 -CAfile certs/ca.crt 2>&1 | Select-String "Protocol"
```
Must show `TLSv1.2`. If it shows `TLSv1.3`, `OPENSSL_CONF` is not set.

### M5Stick error: `-1 start_ssl_client`

**Cause:** The broker is not running, not listening on port 8883, or `OPENSSL_CONF` is not set.

**Fix:**
1. Check broker is listening: `netstat -ano | findstr ":8883"`
2. If empty, start the broker with `OPENSSL_CONF` as shown above
3. If listening but still failing, restart the broker

### M5Stick error: `MQTT Connect failed, rc=5`

**Cause:** MQTT authentication failed. The username/password is wrong or the user is not in `password.txt`.

**Fix:** Add or re-add the M5Stick user:
```powershell
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b password.txt m5tag password000
```
Then restart the broker.

### RPi error: `Connection timed out` on port 8883

**Cause:** Missing `tls_set()` in `mqtt_publisher.py` or wrong ca.crt path.

**Fix:** Ensure `mqtt_publisher.py` has:
```python
self.client.tls_set(ca_certs=os.path.expanduser("~/iot_project/certs/ca.crt"))
```
And verify `ca.crt` exists on the RPi at that path.

### Broker error: `Only one usage of each socket address`

**Cause:** Another Mosquitto instance is already running on that port.

**Fix:**
```powershell
# Stop the Windows service
net stop mosquitto
# Kill any remaining processes
taskkill /IM mosquitto.exe /F
# Then start again
$env:OPENSSL_CONF="<project_folder>\certs\openssl_tls12.cnf"
mosquitto -c "C:\Program Files\Mosquitto\mosquitto.conf" -v
```

### Broker error: `Unable to load server key file` / `key values mismatch`

**Cause:** The server.key and server.crt don't match (partial cert regeneration).

**Fix:** Re-run the setup script to regenerate all certs fresh. Then copy the new `ca.crt` to all devices.

### Broker error: `Unable to load server certificate` / `No such file or directory`

**Cause:** `server.crt` was not generated. This can happen if:
- The Mosquitto service was holding cert files open when the script tried to delete them
- The openssl commands failed silently

**Fix:** Re-run the setup script as Administrator. The script now stops Mosquitto first before regenerating certs.

### Setting OPENSSL_CONF as a system environment variable

To avoid setting `$env:OPENSSL_CONF` every time, the setup script sets it permanently. To set it manually (Admin PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("OPENSSL_CONF", "<project_folder>\certs\openssl_tls12.cnf", "Machine")
```
Then restart the Mosquitto service:
```powershell
net stop mosquitto
net start mosquitto
```
> **Note:** You may need a full PC restart for the service to pick up the new environment variable.

### Quick checklist if M5Stick can't connect

1. Is the broker running? → `netstat -ano | findstr ":8883"`
2. Is `OPENSSL_CONF` set? → `echo $env:OPENSSL_CONF` (must point to `openssl_tls12.cnf`)
3. Is the TLS version correct? → `openssl s_client -connect <BROKER_IP>:8883 -tls1_2 -CAfile certs/ca.crt` (must show `TLSv1.2`)
4. Is the m5tag user in password.txt? → Add with `mosquitto_passwd.exe -b password.txt m5tag password000`
5. Did you rebuild and reflash the M5Stick after changing ca.crt?
