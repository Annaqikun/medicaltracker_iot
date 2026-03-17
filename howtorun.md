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

---

## Step 1: Run the Automated TLS Setup Script

The setup scripts generate TLS certificates, create MQTT users, configure ACL, and update `mosquitto.conf` automatically.

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
- **Extra users** (enter `coordinator,dashboard` and set passwords for each)

The script creates:
| File | Purpose |
|------|---------|
| `password.txt` | MQTT user credentials (hashed) |
| `acl.txt` | Topic access control per user |
| `certs/ca.crt` | CA certificate (copy to RPi + M5Stick) |
| `certs/server.crt` | Server certificate |
| `certs/server.key` | Server private key |
| `certs/openssl_tls12.cnf` | Forces TLS 1.2 (required for ESP32) |

### Add M5Stick Tag User (after running the script)

All M5Sticks share one `m5tag` account:
```powershell
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b password.txt m5tag password000
```

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
static const char* MQTT_PASSWORD = "password000";  // shared m5tag password
```
The M5Stick uses the tag ID (e.g. `m5tag01`) from `main.cpp` as the MQTT username, but authenticates against the shared `m5tag` password file entry.

> **Note:** Update `WIFI_SSID`, `WIFI_PASSWORD`, and `MQTT_IP` in `wifi_manager.cpp` to match your hotspot.

### Copy ca.crt to devices

**RPi:**
```bash
mkdir -p ~/iot_project/certs
scp certs/ca.crt pi@<RPI_IP>:~/iot_project/certs/ca.crt
```

**M5Stick:**
Copy `certs/ca.crt` to `m5Stick/certs/ca.crt` in the project, then rebuild and flash via PlatformIO.

---

## Running the System

Start in this order:

### 1. Start Mosquitto Broker

**Important:** The broker must be started with `OPENSSL_CONF` set to enforce TLS 1.2 (ESP32 mbedTLS does not support TLS 1.3).

```powershell
# Stop the Windows service first (Admin terminal)
net stop mosquitto

# Start manually with TLS 1.2 enforcement
$env:OPENSSL_CONF="<project_folder>\certs\openssl_tls12.cnf"
mosquitto -c "C:\Program Files\Mosquitto\mosquitto.conf" -v
```

Or as a Windows service (if `OPENSSL_CONF` is set as a system environment variable):
```powershell
net start mosquitto
```

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

## TLS Debugging Guide

### M5Stick error: `-9984 X509 Certificate verification failed`

**Cause:** The broker is using TLS 1.3 but ESP32 mbedTLS only supports TLS 1.2.

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

> **Note:** The M5Stick code uses `wifiClientSecure.setInsecure()` instead of `setCACert()` due to an ESP32 mbedTLS compatibility issue with self-signed CA certs. The connection is still TLS encrypted — it just skips server certificate verification.

### M5Stick error: `-1 start_ssl_client`

**Cause:** The broker is not running, not listening on port 8883, or `OPENSSL_CONF` is not set.

**Fix:**
1. Check broker is listening: `netstat -ano | findstr ":8883"`
2. If empty, start the broker with `OPENSSL_CONF` as shown above
3. If listening but still failing, restart the broker

### M5Stick error: `MQTT Connect failed, rc=5`

**Cause:** MQTT authentication failed. The username is not in `password.txt`.

**Fix:** Add the M5Stick user:
```powershell
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b password.txt m5tag password000
```
Then restart the broker.

> The M5Stick uses the tag ID from `main.cpp` (e.g. `m5tag01`) as the MQTT username. However, the password file entry should be `m5tag` (shared account). If using per-tag accounts, add each one individually.

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

### Setting OPENSSL_CONF as a system environment variable

To avoid setting `$env:OPENSSL_CONF` every time, set it permanently (Admin PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("OPENSSL_CONF", "<project_folder>\certs\openssl_tls12.cnf", "Machine")
```
Then restart the Mosquitto service:
```powershell
net stop mosquitto
net start mosquitto
```
> **Note:** The service may need a full PC restart to pick up the new environment variable.
