#!/bin/bash

# Medical Tracker TLS Setup Script
# Automates certificate generation for Mosquitto MQTT broker

set -e  # Exit on any error

echo "=========================================="
echo "Medical Tracker TLS Certificate Setup"
echo "=========================================="
echo ""

# Get broker IP from user
read -p "Enter the MQTT broker IP address: " BROKER_IP

if [ -z "$BROKER_IP" ]; then
    echo "Error: IP address is required"
    exit 1
fi

# Validate IP format (basic check)
if ! echo "$BROKER_IP" | grep -E '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$' > /dev/null; then
    echo "Warning: IP doesn't look like a standard IPv4 address"
    read -p "Continue anyway? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        exit 1
    fi
fi

echo ""
echo "Will generate certificates for IP: $BROKER_IP"
echo ""

# Check for required directories
CERT_DIR="$(pwd)/certs"
MOSQUITTO_DIR="/etc/mosquitto"

# Create local certs directory
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

echo "Step 1/7: Generating CA private key..."
openssl genrsa -out ca.key 2048 2>/dev/null

echo "Step 2/7: Generating CA certificate..."
openssl req -new -x509 -days 1826 -key ca.key -subj "/CN=MedicalTrackerCA" -out ca.crt

echo "Step 3/7: Generating server private key..."
openssl genrsa -out server.key 2048 2>/dev/null

echo "Step 4/7: Creating server certificate request with IP: $BROKER_IP..."
openssl req -new -key server.key -subj "/CN=$BROKER_IP" -addext "subjectAltName=IP:$BROKER_IP" -out server.csr

echo "Step 5/7: Signing server certificate with CA..."
openssl x509 -req -days 1826 -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -copy_extensions copy -out server.crt

echo "Step 6/7: Verifying certificate..."
echo "Certificate details:"
openssl x509 -in server.crt -text -noout | grep -E "(Subject:|Issuer:|Subject Alternative)" -A1
echo ""

echo "Step 7/7: Setting up Mosquitto configuration..."

# Check if running as root (needed for /etc/mosquitto)
if [ "$EUID" -ne 0 ]; then
    echo "Note: Not running as root. Skipping system file installation."
    echo "To complete setup, run the following as root:"
    echo ""
    echo "  sudo cp $CERT_DIR/ca.crt $MOSQUITTO_DIR/ca.crt"
    echo "  sudo cp $CERT_DIR/server.crt $MOSQUITTO_DIR/server.crt"
    echo "  sudo cp $CERT_DIR/server.key $MOSQUITTO_DIR/server.key"
    echo "  sudo chown mosquitto:mosquitto $MOSQUITTO_DIR/ca.crt $MOSQUITTO_DIR/server.crt $MOSQUITTO_DIR/server.key"
    echo "  sudo chmod 644 $MOSQUITTO_DIR/ca.crt $MOSQUITTO_DIR/server.crt"
    echo "  sudo chmod 640 $MOSQUITTO_DIR/server.key"
    echo ""
else
    # Copy certificates to Mosquitto directory
    cp ca.crt "$MOSQUITTO_DIR/ca.crt"
    cp server.crt "$MOSQUITTO_DIR/server.crt"
    cp server.key "$MOSQUITTO_DIR/server.key"

    # Set ownership and permissions
    chown mosquitto:mosquitto "$MOSQUITTO_DIR/ca.crt" "$MOSQUITTO_DIR/server.crt" "$MOSQUITTO_DIR/server.key"
    chmod 644 "$MOSQUITTO_DIR/ca.crt" "$MOSQUITTO_DIR/server.crt"
    chmod 600 "$MOSQUITTO_DIR/server.key"

    echo "Certificates installed to $MOSQUITTO_DIR"
fi

# Create Mosquitto config file
cat > "$CERT_DIR/tls.conf" << EOF
# TLS Configuration for Medical Tracker MQTT Broker
# Generated for IP: $BROKER_IP

# Authentication
allow_anonymous false
password_file /etc/mosquitto/passwordfile
acl_file /etc/mosquitto/acl

# TLS Listener
listener 8883 0.0.0.0
protocol mqtt
cafile /etc/mosquitto/ca.crt
certfile /etc/mosquitto/server.crt
keyfile /etc/mosquitto/server.key
tls_version tlsv1.2

# Optional: Also enable non-TLS on localhost for debugging
# listener 1883 127.0.0.1
# allow_anonymous false
# password_file /etc/mosquitto/passwordfile
EOF

if [ "$EUID" -eq 0 ]; then
    cp "$CERT_DIR/tls.conf" "$MOSQUITTO_DIR/conf.d/tls.conf"
    echo "Mosquitto config installed to $MOSQUITTO_DIR/conf.d/tls.conf"
else
    echo ""
    echo "To install Mosquitto config, run:"
    echo "  sudo cp $CERT_DIR/tls.conf $MOSQUITTO_DIR/conf.d/tls.conf"
fi

echo ""
echo "=========================================="
echo "Certificate Generation Complete!"
echo "=========================================="
echo ""
echo "Files generated in: $CERT_DIR"
echo ""
echo "Important files:"
echo "  - ca.crt         : Copy to RPi and Pico clients"
echo "  - ca.key         : KEEP SECRET (CA signing key)"
echo "  - server.crt     : Broker certificate (already installed)"
echo "  - server.key     : Broker private key (already installed)"
echo ""
echo "Next steps:"
echo "  1. Copy $CERT_DIR/ca.crt to your RPi at /etc/mosquitto/ca.crt"
echo "  2. Copy $CERT_DIR/ca.crt to your Pico W project"
echo "  3. Update mqtt_publisher.py: MQTT_BROKER = '$BROKER_IP'"
echo "  4. Restart Mosquitto: sudo systemctl restart mosquitto"
echo ""

# Optional: Create a client package
echo "Create client package for RPi? (y/n): "
read create_pkg
if [ "$create_pkg" = "y" ]; then
    CLIENT_PKG="$CERT_DIR/client_package"
    mkdir -p "$CLIENT_PKG"
    cp ca.crt "$CLIENT_PKG/"
    cat > "$CLIENT_PKG/README.txt" << EOF
Client Certificate Package
==========================

This package contains the CA certificate needed to verify the MQTT broker.

Installation on Raspberry Pi:
  sudo mkdir -p /etc/mosquitto
  sudo cp ca.crt /etc/mosquitto/ca.crt

Installation on Pico W:
  Embed ca.crt content in your MicroPython code or upload to device.

Broker IP: $BROKER_IP
Port: 8883
EOF
    echo ""
    echo "Client package created at: $CLIENT_PKG/"
    echo "Copy this entire folder to your RPi and Pico"
fi

echo ""
echo "Done!"
