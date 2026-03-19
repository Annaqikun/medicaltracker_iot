# ============================================================
# Mosquitto TLS + Auth Setup Script (Windows)
# Usage: Run as Administrator
#   powershell -ExecutionPolicy Bypass -File setup_mosquitto_tls.ps1
# ============================================================

$MOSQ_DIR = "C:\Program Files\mosquitto"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

Write-Host ""
Write-Host "============================================================"
Write-Host "  Mosquitto TLS + Auth Setup"
Write-Host "============================================================"
Write-Host ""

# ---- CHECK ADMIN ----
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator."
    Write-Host "  Right-click PowerShell -> Run as Administrator, then re-run."
    exit 1
}

# ---- USER INPUTS ----
$BROKER_IP = Read-Host "Enter MQTT broker IP address (default: 192.168.137.1)"
if ([string]::IsNullOrWhiteSpace($BROKER_IP)) { $BROKER_IP = "192.168.137.1" }

$RPI_USER = Read-Host "Enter RPi MQTT username (default: rpi)"
if ([string]::IsNullOrWhiteSpace($RPI_USER)) { $RPI_USER = "rpi" }

$RPI_PASS = Read-Host "Enter RPi MQTT password (default: 1234)"
if ([string]::IsNullOrWhiteSpace($RPI_PASS)) { $RPI_PASS = "1234" }

$M5TAG_PASS = Read-Host "Enter M5Stick shared password (default: password000)"
if ([string]::IsNullOrWhiteSpace($M5TAG_PASS)) { $M5TAG_PASS = "password000" }

$EXTRA_USERS_INPUT = Read-Host "Enter any extra MQTT usernames separated by commas (e.g. coordinator,dashboard) or press Enter to skip"
$EXTRA_USERS = @()
if (-not [string]::IsNullOrWhiteSpace($EXTRA_USERS_INPUT)) {
    $EXTRA_USERS = $EXTRA_USERS_INPUT -split "," | ForEach-Object { $_.Trim() }
}

Write-Host ""
Write-Host "---- Settings ----"
Write-Host "  Broker IP  : $BROKER_IP"
Write-Host "  RPi user   : $RPI_USER"
Write-Host "  M5Stick user: m5tag"
Write-Host "  Extra users: $($EXTRA_USERS -join ', ')"
Write-Host "------------------"
Write-Host ""

# ============================================================
# STEP 0 — Stop Mosquitto (so cert files are not locked)
# ============================================================
Write-Host "[0/6] Stopping Mosquitto..."
net stop mosquitto 2>$null
Stop-Process -Name mosquitto -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Write-Host "  Mosquitto stopped."

# ============================================================
# STEP 1 — Create password file
# ============================================================
Write-Host "[1/6] Creating password file..."

& "$MOSQ_DIR\mosquitto_passwd.exe" -c -b password.txt $RPI_USER $RPI_PASS
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to create password file"; exit 1 }

& "$MOSQ_DIR\mosquitto_passwd.exe" -b password.txt m5tag $M5TAG_PASS
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to add m5tag user"; exit 1 }
Write-Host "  Added user: m5tag (shared M5Stick account)"

foreach ($user in $EXTRA_USERS) {
    $pass = Read-Host "  Enter password for '$user'"
    & "$MOSQ_DIR\mosquitto_passwd.exe" -b password.txt $user $pass
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to add user $user"; exit 1 }
    Write-Host "  Added user: $user"
}

Write-Host "  password.txt created."

# ============================================================
# STEP 2 — Create ACL file
# ============================================================
Write-Host "[2/6] Creating ACL file..."

$ACL_CONTENT = @"
# RPi - can publish scans, RSSI, and heartbeats
user $RPI_USER
topic write hospital/medicine/scan/#
topic write hospital/medicine/rssi_only/#
topic write hospital/system/rpi_status/#

# M5Stick tags (shared account) - emergency, ack, and command topics
user m5tag
topic write hospital/medicine/emergency/#
topic write hospital/medicine/ack/#
topic read hospital/medicine/command/#

# Coordinator - can read scans and emergencies, publish deduplicated data and status
user coordinator
topic read hospital/medicine/scan/#
topic read hospital/medicine/emergency/#
topic write hospital/medicine/rssi/#
topic write hospital/medicine/command/#
topic write hospital/system/coordinator_status

# Dashboard - read only access to everything
user dashboard
topic read hospital/#
"@

Set-Content -Path "acl" -Value $ACL_CONTENT
Write-Host "  acl created."

# ============================================================
# STEP 3 — Generate TLS certificates
# ============================================================
Write-Host "[3/6] Generating TLS certificates..."

if (Test-Path "certs") { Remove-Item "certs" -Recurse -Force }
New-Item -ItemType Directory -Path "certs" | Out-Null
Set-Location "certs"

# CA config
$CA_CNF = @"
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[req_distinguished_name]
C = SG
ST = Singapore
L = Singapore
O = CSC2106
OU = IoT
CN = CSC2106-CA

[v3_ca]
basicConstraints = critical, CA:true
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
"@
Set-Content -Path "ca_openssl.cnf" -Value $CA_CNF

# Server CSR config (avoids -subj flag issues on Windows)
$SERVER_REQ_CNF = @"
[req]
distinguished_name = req_distinguished_name
prompt = no

[req_distinguished_name]
C = SG
ST = Singapore
L = Singapore
O = CSC2106
OU = IoT
CN = $BROKER_IP
"@
Set-Content -Path "server_req.cnf" -Value $SERVER_REQ_CNF

# Server extension config
$SERVER_EXT = @"
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = $BROKER_IP
"@
Set-Content -Path "server_ext.cnf" -Value $SERVER_EXT

# TLS 1.2 config
$TLS12_CNF = @"
openssl_conf = openssl_init

[openssl_init]
ssl_conf = ssl_configuration

[ssl_configuration]
system_default = tls_system_default

[tls_system_default]
MinProtocol = TLSv1.2
MaxProtocol = TLSv1.2
"@
Set-Content -Path "openssl_tls12.cnf" -Value $TLS12_CNF

# Generate CA key + cert
Write-Host "  Generating CA key and certificate..."
openssl genrsa -out ca.key 2048 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate CA key"; exit 1 }
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -config ca_openssl.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate CA certificate"; exit 1 }

# Generate server key + cert (ECDSA for better ESP32 compatibility)
Write-Host "  Generating server key and certificate..."
openssl ecparam -name prime256v1 -genkey -noout -out server.key
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate server key"; exit 1 }
openssl req -new -key server.key -out server.csr -config server_req.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate server CSR"; exit 1 }
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256 -extfile server_ext.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to sign server certificate"; exit 1 }

# Verify
if (-not (Test-Path "server.crt")) {
    Write-Host "ERROR: server.crt was not generated!"
    exit 1
}
Write-Host "  Certificates generated in certs\"

Set-Location ".."

# ============================================================
# STEP 4 — Update mosquitto.conf
# ============================================================
Write-Host "[4/6] Updating mosquitto.conf..."

$MOSQ_CONF = "$MOSQ_DIR\mosquitto.conf"
$CONF_CONTENT = @"
# Mosquitto config - generated by setup_mosquitto_tls.ps1

# Non-TLS listener (port 1883) - requires username/password
listener 1883 0.0.0.0
allow_anonymous false
password_file $($SCRIPT_DIR -replace '\\','/')/password.txt
acl_file $($SCRIPT_DIR -replace '\\','/')/acl

# TLS listener (port 8883) - requires username/password + TLS
listener 8883 0.0.0.0
allow_anonymous false
password_file $($SCRIPT_DIR -replace '\\','/')/password.txt
acl_file $($SCRIPT_DIR -replace '\\','/')/acl
cafile $($SCRIPT_DIR -replace '\\','/')/certs/ca.crt
certfile $($SCRIPT_DIR -replace '\\','/')/certs/server.crt
keyfile $($SCRIPT_DIR -replace '\\','/')/certs/server.key
tls_version tlsv1.2
"@

try {
    Set-Content -Path $MOSQ_CONF -Value $CONF_CONTENT -ErrorAction Stop
    Write-Host "  mosquitto.conf updated."
} catch {
    Write-Host "  ERROR: Cannot write to mosquitto.conf. Run this script as Administrator."
    exit 1
}

# ============================================================
# STEP 5 — Set OPENSSL_CONF and restart Mosquitto service
# ============================================================
Write-Host "[5/6] Setting OPENSSL_CONF and restarting Mosquitto service..."

$OPENSSL_CONF_PATH = "$SCRIPT_DIR\certs\openssl_tls12.cnf"
[Environment]::SetEnvironmentVariable("OPENSSL_CONF", $OPENSSL_CONF_PATH, "Machine")
$env:OPENSSL_CONF = $OPENSSL_CONF_PATH
Write-Host "  OPENSSL_CONF set to: $OPENSSL_CONF_PATH"

net start mosquitto 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Mosquitto service started."
} else {
    Write-Host "  WARNING: Could not start Mosquitto service."
    Write-Host "  Start manually:"
    Write-Host "    `$env:OPENSSL_CONF=`"$OPENSSL_CONF_PATH`""
    Write-Host "    mosquitto -c `"$MOSQ_CONF`" -v"
}

# ============================================================
# STEP 6 — Print summary and ca.crt
# ============================================================
Write-Host ""
Write-Host "[6/6] Done!"
Write-Host ""
Write-Host "-------- ca.crt (copy to RPi and M5Stick) --------"
Get-Content "certs\ca.crt"
Write-Host "-------- end of ca.crt --------"
Write-Host ""
Write-Host "============================================================"
Write-Host "  Setup complete!"
Write-Host ""
Write-Host "  MQTT Users:"
Write-Host "    rpi      : $RPI_PASS"
Write-Host "    m5tag    : $M5TAG_PASS"
foreach ($user in $EXTRA_USERS) {
    Write-Host "    $user"
}
Write-Host ""
Write-Host "  Copy ca.crt to RPi:"
Write-Host "    scp certs\ca.crt <user>@<rpi_ip>:~/iot_project/certs/ca.crt"
Write-Host ""
Write-Host "  Copy ca.crt to M5Stick:"
Write-Host "    copy certs\ca.crt m5Stick\certs\ca.crt"
Write-Host "    Then rebuild and flash via PlatformIO."
Write-Host ""
Write-Host "  Start broker manually with verbose logs:"
Write-Host "    `$env:OPENSSL_CONF=`"$OPENSSL_CONF_PATH`""
Write-Host "    mosquitto -c `"C:\Program Files\Mosquitto\mosquitto.conf`" -v"
Write-Host ""
Write-Host "  Or as a service (OPENSSL_CONF already set):"
Write-Host "    net start mosquitto"
Write-Host ""
Write-Host "  Test subscribe:"
Write-Host "  & '$MOSQ_DIR\mosquitto_sub.exe' -h 127.0.0.1 -p 1883 -u $RPI_USER -P $RPI_PASS -t 'hospital/#' -d"
Write-Host "============================================================"
