"""SQLite-based tag registry for the Medical Tracker IoT backend.

This module manages a registry of known BLE medicine tags (M5StickC),
mapping their MAC addresses to HMAC keys (for payload authentication)
and medicine names (since medicine name is no longer transmitted in the
BLE payload).
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)

# Resolve database path relative to this file's directory
_DB_PATH: str = str(Path(__file__).parent / settings.TAG_DB_PATH)


def _get_connection() -> sqlite3.Connection:
    """Open a connection to the tag registry database.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the tags table if it does not already exist."""
    conn = _get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                mac           TEXT PRIMARY KEY,
                hmac_key      BLOB NOT NULL,
                medicine_name TEXT NOT NULL,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        logger.info("Tag registry database initialised (%s)", _DB_PATH)
    finally:
        conn.close()


def get_tag(mac: str) -> Optional[Dict[str, Any]]:
    """Look up a tag by MAC address.

    Args:
        mac: MAC address string (e.g. "4C:75:25:CB:7E:0A").

    Returns:
        Dict with keys ``hmac_key`` (bytes), ``medicine_name`` (str),
        and ``registered_at`` (str), or None if the MAC is not registered.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT hmac_key, medicine_name, registered_at FROM tags WHERE mac = ?",
            (mac,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hmac_key": bytes(row["hmac_key"]),
            "medicine_name": row["medicine_name"],
            "registered_at": row["registered_at"],
        }
    finally:
        conn.close()


def get_all_tags() -> List[Dict[str, Any]]:
    """Return a list of all registered tags.

    Returns:
        List of dicts, each containing ``mac``, ``hmac_key``,
        ``medicine_name``, and ``registered_at``.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT mac, hmac_key, medicine_name, registered_at FROM tags"
        ).fetchall()
        return [
            {
                "mac": row["mac"],
                "hmac_key": bytes(row["hmac_key"]),
                "medicine_name": row["medicine_name"],
                "registered_at": row["registered_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_whitelist() -> List[str]:
    """Return a list of all registered MAC addresses.

    Returns:
        List of MAC address strings.
    """
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT mac FROM tags").fetchall()
        return [row["mac"] for row in rows]
    finally:
        conn.close()


def register_tag(mac: str, hmac_key: bytes, medicine_name: str) -> None:
    """Insert or update a tag in the registry.

    Args:
        mac: MAC address string.
        hmac_key: 32-byte HMAC-SHA256 key.
        medicine_name: Human-readable medicine name.
    """
    if len(hmac_key) != 32:
        raise ValueError(f"hmac_key must be 32 bytes, got {len(hmac_key)}")

    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO tags (mac, hmac_key, medicine_name)
            VALUES (?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                hmac_key      = excluded.hmac_key,
                medicine_name = excluded.medicine_name,
                registered_at = CURRENT_TIMESTAMP
            """,
            (mac, hmac_key, medicine_name),
        )
        conn.commit()
        logger.info("Registered tag %s -> %s", mac, medicine_name)
    finally:
        conn.close()


def remove_tag(mac: str) -> None:
    """Delete a tag from the registry.

    Args:
        mac: MAC address string.
    """
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM tags WHERE mac = ?", (mac,))
        conn.commit()
        logger.info("Removed tag %s", mac)
    finally:
        conn.close()
