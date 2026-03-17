# ============================================================
# Mosquitto TLS + Auth Setup Script
# Usage: powershell -ExecutionPolicy Bypass -File setup_mosquitto_tls.ps1
# ============================================================

$MOSQ_DIR = "C:\Program Files\mosquitto"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

Write-Host ""
Write-Host "============================================================"
Write-Host "  Mosquitto TLS + Auth Setup"
Write-Host "============================================================"
Write-Host ""

# ---- USER INPUTS ----
$BROKER_IP = Read-Host "Enter MQTT broker IP address (default: 192.168.137.1)"
if ([string]::IsNullOrWhiteSpace($BROKER_IP)) { $BROKER_IP = "192.168.137.1" }

$RPI_USER = Read-Host "Enter RPi MQTT username (default: rpi)"
if ([string]::IsNullOrWhiteSpace($RPI_USER)) { $RPI_USER = "rpi" }

$RPI_PASS = Read-Host "Enter RPi MQTT password (default: 1234)"
if ([string]::IsNullOrWhiteSpace($RPI_PASS)) { $RPI_PASS = "1234" }

$EXTRA_USERS_INPUT = Read-Host "Enter any extra MQTT usernames separated by commas (e.g. coordinator,dashboard) or press Enter to skip"
$EXTRA_USERS = @()
if (-not [string]::IsNullOrWhiteSpace($EXTRA_USERS_INPUT)) {
    $EXTRA_USERS = $EXTRA_USERS_INPUT -split "," | ForEach-Object { $_.Trim() }
}

Write-Host ""
Write-Host "---- Settings ----"
Write-Host "  Broker IP : $BROKER_IP"
Write-Host "  RPi user  : $RPI_USER"
Write-Host "  Extra users: $($EXTRA_USERS -join ', ')"
Write-Host "------------------"
Write-Host ""

# ============================================================
# STEP 1 — Create password file
# ============================================================
Write-Host "[1/5] Creating password file..."

# Create fresh password file with RPi user
& "$MOSQ_DIR\mosquitto_passwd.exe" -c -b password.txt $RPI_USER $RPI_PASS
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to create password file"; exit 1 }

# Add M5Stick shared account
& "$MOSQ_DIR\mosquitto_passwd.exe" -b password.txt m5tag password000
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to add m5tag user"; exit 1 }
Write-Host "  Added user: m5tag (shared M5Stick account)"

# Add extra users
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
Write-Host "[2/5] Creating ACL file..."

$ACL_CONTENT = @"
# RPi - can publish scans, RSSI, and heartbeats
user $RPI_USER
topic write hospital/medicine/scan/#
topic write hospital/medicine/rssi_only/#
topic write hospital/system/rpi_status/#

# M5Stick tags - emergency, ack, and command topics
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
Write-Host "[3/5] Generating TLS certificates..."

if (Test-Path "certs") { Remove-Item "certs\*" -Force -ErrorAction SilentlyContinue }
if (-not (Test-Path "certs")) { New-Item -ItemType Directory -Path "certs" | Out-Null }
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
openssl genrsa -out ca.key 2048
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate CA key"; exit 1 }
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -config ca_openssl.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate CA certificate"; exit 1 }

# Generate server key + cert
Write-Host "  Generating server key and certificate..."
openssl genrsa -out server.key 2048
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate server key"; exit 1 }
# Use server config file instead of -subj (Windows OpenSSL has issues with -subj)
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
openssl req -new -key server.key -out server.csr -config server_req.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to generate server CSR"; exit 1 }
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256 -extfile server_ext.cnf
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to sign server certificate"; exit 1 }

Write-Host "  Certificates generated in certs\"
Set-Location ".."

# ============================================================
# STEP 4 — Update mosquitto.conf (requires admin)
# ============================================================
Write-Host "[4/6] Updating mosquitto.conf..."

$MOSQ_CONF = "$MOSQ_DIR\mosquitto.conf"
$CONF_CONTENT = @"
# Config file for mosquitto

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
    Write-Host "  Right-click PowerShell -> Run as Administrator, then re-run this script."
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

try {
    net stop mosquitto 2>$null
    net start mosquitto
    Write-Host "  Mosquitto service restarted."
} catch {
    Write-Host "  WARNING: Could not restart Mosquitto service. Restart it manually."
}

# ============================================================
# STEP 6 — Print ca.crt for copying to RPi
# ============================================================
Write-Host "[6/6] Done! Copy this ca.crt to each RPi at ~/iot_project/certs/ca.crt:"
Write-Host ""
Write-Host "-------- ca.crt (copy everything below) --------"
Get-Content "certs\ca.crt"
Write-Host "-------- end of ca.crt --------"
Write-Host ""

# ============================================================
# DONE
# ============================================================
Write-Host "============================================================"
Write-Host "  Setup complete! Mosquitto service is running."
Write-Host ""
Write-Host "  Test subscribe:"
Write-Host "  & '$MOSQ_DIR\mosquitto_sub.exe' -h 127.0.0.1 -p 1883 -u $RPI_USER -P $RPI_PASS -t 'hospital/#' -d"
Write-Host "============================================================"
