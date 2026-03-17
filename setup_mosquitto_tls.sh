#!/bin/bash
# ============================================================
# Mosquitto TLS + Auth Setup Script (Mac/Linux)
# Usage: chmod +x setup_mosquitto_tls.sh && ./setup_mosquitto_tls.sh
# ============================================================

set -e

# Detect mosquitto install path
if command -v mosquitto_passwd &>/dev/null; then
    MOSQ_DIR=$(dirname $(command -v mosquitto))
else
    echo "ERROR: mosquitto not found. Install it first:"
    echo "  Mac:   brew install mosquitto"
    echo "  Linux: sudo apt install mosquitto mosquitto-clients"
    exit 1
fi

echo ""
echo "============================================================"
echo "  Mosquitto TLS + Auth Setup"
echo "  Mosquitto found at: $MOSQ_DIR"
echo "============================================================"
echo ""

# ---- USER INPUTS ----
read -p "Enter MQTT broker IP address (default: 192.168.137.1): " BROKER_IP
BROKER_IP=${BROKER_IP:-192.168.137.1}

read -p "Enter RPi MQTT username (default: rpi): " RPI_USER
RPI_USER=${RPI_USER:-rpi}

read -s -p "Enter RPi MQTT password (default: 1234): " RPI_PASS
echo ""
RPI_PASS=${RPI_PASS:-1234}

read -p "Enter extra MQTT usernames separated by commas (e.g. coordinator,dashboard) or press Enter to skip: " EXTRA_USERS_INPUT

echo ""
echo "---- Settings ----"
echo "  Broker IP  : $BROKER_IP"
echo "  RPi user   : $RPI_USER"
echo "  Extra users: $EXTRA_USERS_INPUT"
echo "------------------"
echo ""

# All files go into ~/iot_project
SCRIPT_DIR="$HOME/iot_project"
mkdir -p "$SCRIPT_DIR"
cd "$SCRIPT_DIR"

# ============================================================
# STEP 1 — Create password file
# ============================================================
echo "[1/5] Creating password file..."

mosquitto_passwd -c -b password.txt "$RPI_USER" "$RPI_PASS"

# Add M5Stick shared account
mosquitto_passwd -b password.txt m5tag password000
echo "  Added user: m5tag (shared M5Stick account)"

if [ -n "$EXTRA_USERS_INPUT" ]; then
    IFS=',' read -ra EXTRA_USERS <<< "$EXTRA_USERS_INPUT"
    for user in "${EXTRA_USERS[@]}"; do
        user=$(echo "$user" | xargs)  # trim whitespace
        read -s -p "  Enter password for '$user': " upass
        echo ""
        mosquitto_passwd -b password.txt "$user" "$upass"
        echo "  Added user: $user"
    done
fi

echo "  password.txt created."

# ============================================================
# STEP 2 — Create ACL file
# ============================================================
echo "[2/5] Creating ACL file..."

cat > acl <<EOF
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
EOF

echo "  acl created."

# ============================================================
# STEP 3 — Generate TLS certificates
# ============================================================
echo "[3/5] Generating TLS certificates..."

rm -rf certs
mkdir -p certs
cd certs

# CA config
cat > ca_openssl.cnf <<EOF
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
EOF

# Server extension config
cat > server_ext.cnf <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = $BROKER_IP
EOF

# TLS 1.2 config
cat > openssl_tls12.cnf <<EOF
openssl_conf = openssl_init

[openssl_init]
ssl_conf = ssl_configuration

[ssl_configuration]
system_default = tls_system_default

[tls_system_default]
MinProtocol = TLSv1.2
MaxProtocol = TLSv1.2
EOF

# Generate CA key + cert
echo "  Generating CA key and certificate..."
openssl genrsa -out ca.key 2048 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -config ca_openssl.cnf 2>/dev/null

# Generate server key + cert
echo "  Generating server key and certificate..."
openssl genrsa -out server.key 2048 2>/dev/null
openssl req -new -key server.key -out server.csr \
    -subj "/C=SG/ST=Singapore/L=Singapore/O=CSC2106/OU=IoT/CN=$BROKER_IP" 2>/dev/null
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 3650 -sha256 -extfile server_ext.cnf 2>/dev/null

echo "  Certificates generated in certs/"
cd ..

# ============================================================
# STEP 4 — Update mosquitto.conf
# ============================================================
echo "[4/6] Updating mosquitto.conf..."

# Find mosquitto.conf location
if [ -f /etc/mosquitto/mosquitto.conf ]; then
    MOSQ_CONF="/etc/mosquitto/mosquitto.conf"
elif [ -f /opt/homebrew/etc/mosquitto/mosquitto.conf ]; then
    MOSQ_CONF="/opt/homebrew/etc/mosquitto/mosquitto.conf"
elif [ -f /usr/local/etc/mosquitto/mosquitto.conf ]; then
    MOSQ_CONF="/usr/local/etc/mosquitto/mosquitto.conf"
else
    echo "  WARNING: Could not find mosquitto.conf. Creating config at $SCRIPT_DIR/mosquitto.conf"
    MOSQ_CONF="$SCRIPT_DIR/mosquitto.conf"
fi

sudo tee "$MOSQ_CONF" > /dev/null <<EOF
# Config file for mosquitto

# Non-TLS listener (port 1883) - requires username/password
listener 1883 0.0.0.0
allow_anonymous false
password_file $SCRIPT_DIR/password.txt
acl_file $SCRIPT_DIR/acl

# TLS listener (port 8883) - requires username/password + TLS
listener 8883 0.0.0.0
allow_anonymous false
password_file $SCRIPT_DIR/password.txt
acl_file $SCRIPT_DIR/acl
cafile $SCRIPT_DIR/certs/ca.crt
certfile $SCRIPT_DIR/certs/server.crt
keyfile $SCRIPT_DIR/certs/server.key
tls_version tlsv1.2
EOF

echo "  mosquitto.conf updated at: $MOSQ_CONF"

# ============================================================
# STEP 5 — Set OPENSSL_CONF and restart Mosquitto
# ============================================================
echo "[5/6] Setting OPENSSL_CONF and restarting Mosquitto..."

export OPENSSL_CONF="$SCRIPT_DIR/certs/openssl_tls12.cnf"

# Add to shell profile if not already there
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
if ! grep -q "OPENSSL_CONF.*openssl_tls12" "$SHELL_RC" 2>/dev/null; then
    echo "export OPENSSL_CONF=\"$SCRIPT_DIR/certs/openssl_tls12.cnf\"" >> "$SHELL_RC"
    echo "  Added OPENSSL_CONF to $SHELL_RC"
fi

# Create systemd override for Mosquitto service (Linux)
if command -v systemctl &>/dev/null; then
    sudo mkdir -p /etc/systemd/system/mosquitto.service.d
    sudo tee /etc/systemd/system/mosquitto.service.d/openssl.conf > /dev/null <<EOF
[Service]
Environment="OPENSSL_CONF=$SCRIPT_DIR/certs/openssl_tls12.cnf"
EOF
    sudo systemctl daemon-reload
    sudo systemctl restart mosquitto
    echo "  Mosquitto service restarted with OPENSSL_CONF."
# macOS with brew
elif command -v brew &>/dev/null; then
    brew services restart mosquitto 2>/dev/null || sudo brew services restart mosquitto
    echo "  Mosquitto restarted via brew."
fi

# ============================================================
# STEP 6 — Print ca.crt for copying to RPi
# ============================================================
echo "[6/6] Done! Copy this ca.crt to each RPi at ~/iot_project/certs/ca.crt:"
echo ""
echo "-------- ca.crt (copy everything below) --------"
cat certs/ca.crt
echo "-------- end of ca.crt --------"
echo ""

# ============================================================
# DONE
# ============================================================
echo "============================================================"
echo "  Setup complete! Mosquitto service is running."
echo ""
echo "  Test subscribe:"
echo "  mosquitto_sub -h 127.0.0.1 -p 1883 -u $RPI_USER -P $RPI_PASS -t 'hospital/#' -d"
echo "============================================================"
