#!/usr/bin/env python3
"""Provisioning tool for HMAC tag registration.

Manages the tag registry used by the Medical Tracker IoT system.
Each M5StickC BLE tag needs a unique HMAC-SHA256 key for payload
signing. This script handles key generation, serial flashing to the
M5 NVS, and registration in the backend database.

Usage:
    python provision.py flash --port /dev/ttyUSB0 --medicine "PANADOL"
    python provision.py register --mac 4C:75:25:CB:7E:0A --medicine "PANADOL"
    python provision.py list
    python provision.py remove --mac 4C:75:25:CB:7E:0A
    python provision.py get-key --mac 4C:75:25:CB:7E:0A

Requirements:
    pip install pyserial
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Default database path relative to this script
DEFAULT_DB_PATH = str(Path(__file__).parent / "backend" / "tag_registry.db")


# MAC address pattern: six groups of two hex digits separated by colons
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open a connection to the tag registry database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create the tags table if it does not already exist."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                mac           TEXT PRIMARY KEY,
                hmac_key      BLOB NOT NULL,
                medicine_name TEXT NOT NULL,
                tag_id        TEXT NOT NULL DEFAULT 'm5tag',
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def validate_mac(mac: str) -> str:
    """Validate and normalize a MAC address to uppercase."""
    mac = mac.upper()
    if not MAC_PATTERN.match(mac):
        print(f"Error: Invalid MAC address format: {mac}")
        print("Expected format: XX:XX:XX:XX:XX:XX (hex digits)")
        sys.exit(1)
    return mac


def format_key_hex(key: bytes) -> str:
    """Format a key as a hex string."""
    return key.hex()


def format_key_c_array(key: bytes) -> str:
    """Format a key as a C byte array literal."""
    elements = ", ".join(f"0x{b:02x}" for b in key)
    return "{" + elements + "}"


def save_to_db(db_path: str, mac: str, hmac_key: bytes, medicine: str, tag_id: str = "m5tag") -> None:
    """Save a tag to the SQLite database."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO tags (mac, hmac_key, medicine_name, tag_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                hmac_key      = excluded.hmac_key,
                medicine_name = excluded.medicine_name,
                tag_id        = excluded.tag_id,
                registered_at = CURRENT_TIMESTAMP
            """,
            (mac, hmac_key, medicine, tag_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_flash(args: argparse.Namespace) -> None:
    """Flash HMAC key to M5 over serial and register in database.

    1. Opens serial port to M5
    2. Sends PROV_PING
    3. M5 responds with PROV_MAC:<mac>
    4. Generates random 32-byte key
    5. Sends PROV_KEY:<hex> to M5
    6. M5 writes to NVS and responds PROV_OK
    7. Registers MAC + key + medicine in SQLite
    """
    try:
        import serial
    except ImportError:
        print("Error: pyserial is required for serial provisioning.")
        print("Install it with: pip install pyserial")
        sys.exit(1)

    db_path = args.db
    port = args.port
    medicine = args.medicine.strip()
    baud = args.baud

    if not medicine:
        print("Error: Medicine name cannot be empty.")
        sys.exit(1)

    init_db(db_path)

    print(f"Opening {port} at {baud} baud...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"Error: Cannot open serial port: {e}")
        sys.exit(1)

    time.sleep(0.5)  # let M5 boot

    # Step 1: Send provisioning ping
    print("Sending PROV_PING...")
    ser.write(b"PROV_PING\n")
    ser.flush()

    # Step 2: Wait for MAC response
    print("Waiting for M5 to respond with MAC...")
    mac = None
    deadline = time.time() + 10  # 10s timeout
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  M5: {line}")
        if line.startswith("PROV_MAC:"):
            mac = line[len("PROV_MAC:"):].strip()
            break

    if not mac:
        print("Error: M5 did not respond with MAC address.")
        print("Make sure the M5 is plugged in and the firmware supports provisioning.")
        ser.close()
        sys.exit(1)

    mac = validate_mac(mac)
    print(f"Got MAC: {mac}")

    # Step 3: Generate key
    hmac_key = os.urandom(32)
    hex_key = format_key_hex(hmac_key)
    print(f"Generated HMAC key: {hex_key[:16]}...")

    # Step 4: Send key to M5
    print("Sending key to M5...")
    ser.write(f"PROV_KEY:{hex_key}\n".encode())
    ser.flush()

    # Step 5: Wait for confirmation
    confirmed = False
    deadline = time.time() + 10
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  M5: {line}")
        if line == "PROV_OK":
            confirmed = True
            break
        if line.startswith("PROV_ERR:"):
            print(f"Error from M5: {line}")
            ser.close()
            sys.exit(1)

    ser.close()

    if not confirmed:
        print("Error: M5 did not confirm key was saved.")
        sys.exit(1)

    # Step 6: Register in database and publish whitelist
    save_to_db(db_path, mac, hmac_key, medicine, getattr(args, 'tag_id', 'm5tag'))


    print()
    print("=== Provisioning Complete ===")
    print(f"MAC:       {mac}")
    print(f"Medicine:  {medicine}")
    print(f"HMAC Key:  {hex_key[:16]}...")
    print(f"Database:  {db_path}")
    print()
    print("M5 will reboot and start broadcasting with HMAC signing.")
    print()


def cmd_register(args: argparse.Namespace) -> None:
    """Register a tag manually (without serial connection)."""
    db_path = args.db
    mac = validate_mac(args.mac)
    medicine = args.medicine.strip()

    if not medicine:
        print("Error: Medicine name cannot be empty.")
        sys.exit(1)

    init_db(db_path)

    hmac_key = os.urandom(32)
    save_to_db(db_path, mac, hmac_key, medicine, getattr(args, 'tag_id', 'm5tag'))


    hex_str = format_key_hex(hmac_key)
    c_array = format_key_c_array(hmac_key)

    print()
    print("=== Tag Registered ===")
    print(f"MAC:       {mac}")
    print(f"Medicine:  {medicine}")
    print(f"HMAC Key (hex): {hex_str}")
    print(f"HMAC Key (C array): {c_array}")
    print()
    print("To flash this key to the M5, use the 'flash' command instead,")
    print("or manually write to NVS:")
    print('  Namespace: "ble_sec"')
    print('  Key name:  "hmac_key"')
    print()


def cmd_list(args: argparse.Namespace) -> None:
    """List all registered tags."""
    db_path = args.db
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT mac, hmac_key, medicine_name, registered_at FROM tags "
            "ORDER BY registered_at DESC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No tags registered.")
        return

    mac_w = max(len("MAC"), max(len(r["mac"]) for r in rows))
    med_w = max(len("Medicine"), max(len(r["medicine_name"]) for r in rows))
    key_w = len("Key (partial)")
    date_w = len("Registered At")

    header = (
        f"{'MAC':<{mac_w}}  "
        f"{'Medicine':<{med_w}}  "
        f"{'Key (partial)':<{key_w}}  "
        f"{'Registered At':<{date_w}}"
    )
    separator = "-" * len(header)

    print()
    print(header)
    print(separator)

    for row in rows:
        key_preview = bytes(row["hmac_key"]).hex()[:8] + "..."
        registered = row["registered_at"] or "N/A"
        print(
            f"{row['mac']:<{mac_w}}  "
            f"{row['medicine_name']:<{med_w}}  "
            f"{key_preview:<{key_w}}  "
            f"{registered:<{date_w}}"
        )

    print()
    print(f"Total: {len(rows)} tag(s)")
    print()


def cmd_remove(args: argparse.Namespace) -> None:
    """Remove a tag from the registry."""
    db_path = args.db
    mac = validate_mac(args.mac)

    init_db(db_path)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT medicine_name FROM tags WHERE mac = ?", (mac,)
        ).fetchone()

        if row is None:
            print(f"Error: No tag registered with MAC {mac}")
            sys.exit(1)

        medicine = row["medicine_name"]

        conn.execute("DELETE FROM tags WHERE mac = ?", (mac,))
        conn.commit()
    finally:
        conn.close()



    print()
    print(f"Tag removed: {mac} ({medicine})")
    print()


def cmd_get_key(args: argparse.Namespace) -> None:
    """Retrieve and display the HMAC key for a registered tag."""
    db_path = args.db
    mac = validate_mac(args.mac)

    init_db(db_path)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT hmac_key, medicine_name, registered_at FROM tags WHERE mac = ?",
            (mac,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"Error: No tag registered with MAC {mac}")
        sys.exit(1)

    hmac_key = bytes(row["hmac_key"])
    hex_str = format_key_hex(hmac_key)
    c_array = format_key_c_array(hmac_key)

    print()
    print(f"=== Key for {mac} ===")
    print(f"Medicine:  {row['medicine_name']}")
    print(f"Registered: {row['registered_at']}")
    print()
    print(f"HMAC Key (hex): {hex_str}")
    print()
    print(f"HMAC Key (C array):")
    print(f"  {c_array}")
    print()


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provisioning tool for Medical Tracker HMAC tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python provision.py flash --port /dev/ttyUSB0 --medicine "PANADOL"\n'
            '  python provision.py register --mac 4C:75:25:CB:7E:0A --medicine "PANADOL"\n'
            "  python provision.py list\n"
            "  python provision.py remove --mac 4C:75:25:CB:7E:0A\n"
            "  python provision.py get-key --mac 4C:75:25:CB:7E:0A\n"
        ),
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite tag registry database (default: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- flash (serial provisioning) ---
    p_flash = subparsers.add_parser(
        "flash", help="Plug in M5, auto-read MAC, generate key, flash to NVS, register"
    )
    p_flash.add_argument(
        "--port", required=True, help="Serial port (e.g. /dev/ttyUSB0, /dev/cu.usbserial-*)"
    )
    p_flash.add_argument(
        "--medicine", required=True, help="Medicine name (e.g. PANADOL)"
    )
    p_flash.add_argument(
        "--baud", type=int, default=115200, help="Baud rate (default: 115200)"
    )
    p_flash.add_argument(
        "--tag-id", default="m5tag", help="MQTT tag ID for commands (default: m5tag)"
    )

    # --- register (manual, no serial) ---
    p_register = subparsers.add_parser(
        "register", help="Register a tag manually (without serial connection)"
    )
    p_register.add_argument(
        "--mac", required=True, help="BLE MAC address (e.g. 4C:75:25:CB:7E:0A)"
    )
    p_register.add_argument(
        "--medicine", required=True, help="Medicine name (e.g. PANADOL)"
    )
    p_register.add_argument(
        "--tag-id", default="m5tag", help="MQTT tag ID for commands (default: m5tag)"
    )

    # --- list ---
    subparsers.add_parser("list", help="List all registered tags")

    # --- remove ---
    p_remove = subparsers.add_parser("remove", help="Remove a tag from the registry")
    p_remove.add_argument(
        "--mac", required=True, help="BLE MAC address to remove"
    )

    # --- get-key ---
    p_getkey = subparsers.add_parser(
        "get-key", help="Retrieve the HMAC key for a tag (for manual flashing)"
    )
    p_getkey.add_argument(
        "--mac", required=True, help="BLE MAC address to look up"
    )

    args = parser.parse_args()

    commands = {
        "flash": cmd_flash,
        "register": cmd_register,
        "list": cmd_list,
        "remove": cmd_remove,
        "get-key": cmd_get_key,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
