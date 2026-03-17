"""HMAC-SHA256 verification for BLE beacon payloads.

Beacons sign their payloads with HMAC-SHA256 (truncated to the first
4 bytes).  This module reconstructs the signed data from the parsed
MQTT JSON and verifies the signature against the key stored in the
beacon registry.
"""

import hmac
import hashlib
import logging
import struct
from typing import Any, Dict

logger = logging.getLogger(__name__)


def verify_hmac(
    mac_bytes: bytes,
    temp_bytes: bytes,
    battery_byte: bytes,
    movement_byte: bytes,
    seq_bytes: bytes,
    received_hmac_hex: str,
    hmac_key: bytes,
) -> bool:
    """Verify a truncated HMAC-SHA256 signature.

    The signed payload is the concatenation (12 bytes total):
        mac (6) + temperature (2) + battery (1) + movement (1) + seq (2)

    The HMAC is computed with SHA-256 and only the first 4 bytes are
    compared against ``received_hmac_hex``.

    Args:
        mac_bytes: 6-byte raw MAC address.
        temp_bytes: 2-byte big-endian signed temperature (value * 100).
        battery_byte: 1-byte battery level.
        movement_byte: 1-byte movement flag (0 or 1).
        seq_bytes: 2-byte big-endian sequence number.
        received_hmac_hex: Hex string of the 4-byte truncated HMAC
            received from the beacon (8 hex chars).
        hmac_key: 32-byte secret key for HMAC-SHA256.

    Returns:
        True if the computed HMAC matches the received one.
    """
    payload = mac_bytes + temp_bytes + battery_byte + movement_byte + seq_bytes

    computed = hmac.new(hmac_key, payload, hashlib.sha256).digest()
    computed_truncated = computed[:4].hex()

    match = hmac.compare_digest(computed_truncated, received_hmac_hex.lower())
    if not match:
        logger.debug(
            "HMAC mismatch: computed=%s received=%s",
            computed_truncated,
            received_hmac_hex,
        )
    return match


def verify_from_mqtt_payload(
    payload: Dict[str, Any],
    hmac_key: bytes,
) -> bool:
    """Verify the HMAC in a parsed MQTT JSON payload.

    Reconstructs the raw byte representation of each field from the
    human-readable MQTT JSON and delegates to :func:`verify_hmac`.

    Expected payload keys:
        * ``mac`` – e.g. ``"4C:75:25:CB:7E:0A"``
        * ``temperature`` – float (Celsius)
        * ``battery`` – int (0-255)
        * ``moving`` – bool
        * ``sequence_number`` or ``seq`` – int (0-65535)
        * ``hmac`` – hex string (8 chars)

    Args:
        payload: Parsed MQTT JSON dict.
        hmac_key: 32-byte HMAC secret key.

    Returns:
        True if the HMAC is valid.
    """
    try:
        # --- MAC: "4C:75:25:CB:7E:0A" -> 6 bytes ---
        mac_str: str = payload["mac"]
        mac_bytes = bytes(int(b, 16) for b in mac_str.split(":"))

        # --- Temperature: float -> int16 big-endian (value * 100) ---
        temp_float = float(payload.get("temperature", 0.0))
        temp_int = int(round(temp_float * 100))
        temp_bytes = struct.pack(">h", temp_int)  # signed 16-bit BE

        # --- Battery: 1 byte ---
        battery = int(payload.get("battery", 0))
        battery_byte = struct.pack("B", battery & 0xFF)

        # --- Movement: 1 byte (1 if moving, else 0) ---
        moving = payload.get("moving", False)
        movement_byte = struct.pack("B", 1 if moving else 0)

        # --- Sequence number: 2 bytes big-endian ---
        seq = int(payload.get("sequence_number") or payload.get("seq", 0))
        seq_bytes = struct.pack(">H", seq & 0xFFFF)

        # --- Received HMAC hex ---
        received_hmac_hex: str = payload["hmac"]

        return verify_hmac(
            mac_bytes=mac_bytes,
            temp_bytes=temp_bytes,
            battery_byte=battery_byte,
            movement_byte=movement_byte,
            seq_bytes=seq_bytes,
            received_hmac_hex=received_hmac_hex,
            hmac_key=hmac_key,
        )
    except (KeyError, ValueError, struct.error) as exc:
        logger.warning("Failed to reconstruct payload for HMAC verification: %s", exc)
        return False
