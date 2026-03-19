"""SQLite-based tag registry for the Medical Tracker IoT backend.

This module manages a registry of known BLE medicine tags (M5StickC),
mapping their MAC addresses to HMAC keys, medicine names, and tag IDs
(used for MQTT command routing).
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
    """Open a connection to the tag registry database."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the tags table if it does not already exist.
    Migrates existing tables to add tag_id column if missing."""
    conn = _get_connection()
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
        # Migration: add tag_id column if table already exists without it
        try:
            conn.execute("SELECT tag_id FROM tags LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE tags ADD COLUMN tag_id TEXT NOT NULL DEFAULT 'm5tag'")
            logger.info("Migrated tags table: added tag_id column")
        conn.commit()
        logger.info("Tag registry database initialised (%s)", _DB_PATH)
    finally:
        conn.close()


def get_tag(mac: str) -> Optional[Dict[str, Any]]:
    """Look up a tag by MAC address."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT hmac_key, medicine_name, tag_id, registered_at FROM tags WHERE mac = ?",
            (mac,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hmac_key": bytes(row["hmac_key"]),
            "medicine_name": row["medicine_name"],
            "tag_id": row["tag_id"],
            "registered_at": row["registered_at"],
        }
    finally:
        conn.close()


def get_tag_by_tag_id(tag_id: str) -> Optional[Dict[str, Any]]:
    """Look up a tag by its tag_id (MQTT identifier)."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT mac, hmac_key, medicine_name, tag_id, registered_at FROM tags WHERE tag_id = ?",
            (tag_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "mac": row["mac"],
            "hmac_key": bytes(row["hmac_key"]),
            "medicine_name": row["medicine_name"],
            "tag_id": row["tag_id"],
            "registered_at": row["registered_at"],
        }
    finally:
        conn.close()


def get_all_tags() -> List[Dict[str, Any]]:
    """Return a list of all registered tags."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT mac, hmac_key, medicine_name, tag_id, registered_at FROM tags"
        ).fetchall()
        return [
            {
                "mac": row["mac"],
                "hmac_key": bytes(row["hmac_key"]),
                "medicine_name": row["medicine_name"],
                "tag_id": row["tag_id"],
                "registered_at": row["registered_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_whitelist() -> List[str]:
    """Return a list of all registered MAC addresses."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT mac FROM tags").fetchall()
        return [row["mac"] for row in rows]
    finally:
        conn.close()


def mac_to_tag_id(mac: str) -> Optional[str]:
    """Look up the tag_id for a given MAC address."""
    tag = get_tag(mac)
    return tag["tag_id"] if tag else None


def tag_id_to_mac(tag_id: str) -> Optional[str]:
    """Look up the MAC address for a given tag_id."""
    tag = get_tag_by_tag_id(tag_id)
    return tag["mac"] if tag else None


def register_tag(mac: str, hmac_key: bytes, medicine_name: str, tag_id: str = "m5tag") -> None:
    """Insert or update a tag in the registry."""
    if len(hmac_key) != 32:
        raise ValueError(f"hmac_key must be 32 bytes, got {len(hmac_key)}")

    conn = _get_connection()
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
            (mac, hmac_key, medicine_name, tag_id),
        )
        conn.commit()
        logger.info("Registered tag %s -> %s (tag_id=%s)", mac, medicine_name, tag_id)
    finally:
        conn.close()


def remove_tag(mac: str) -> None:
    """Delete a tag from the registry."""
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM tags WHERE mac = ?", (mac,))
        conn.commit()
        logger.info("Removed tag %s", mac)
    finally:
        conn.close()
