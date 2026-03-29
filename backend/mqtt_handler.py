"""MQTT message handler for the Medical Tracker IoT backend.

This module provides the MedicineTracker class for processing MQTT messages
from BLE receivers, managing RSSI buffers, and triggering position calculations.
All state is held in-memory from live MQTT data — no database required.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import tag_registry
import hmac_verify
from config import settings
from trilaterate import (
    get_smoothed_distance,
    localize,
    calculate_position_error,
    calculate_confidence,
    reset_kalman_filter,
)

logger = logging.getLogger(__name__)

MAX_ALERTS = 50  # keep last N alerts in memory


class MedicineTracker:
    """MQTT message handler for medicine tracking.

    All live state (scan data, positions, alerts) is held in-memory.
    """

    def __init__(self, db=None) -> None:
        self.db = db  # optional InfluxDB for historical logging
        self.settings = settings

        # Buffer: {mac: {receiver_id: {distance, ts, medicine, temp, battery, moving}}}
        self._buffer: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self._buffer_lock = threading.RLock()

        # Latest scan status per mac (what /api/medicines serves)
        self._latest_status: Dict[str, Dict[str, Any]] = {}
        self._status_lock = threading.Lock()

        # Latest position per mac (what /api/positions serves)
        self._latest_positions: Dict[str, Dict[str, Any]] = {}
        self._positions_lock = threading.Lock()

        # In-memory alert list (what /api/alerts serves)
        self._alerts: List[Dict[str, Any]] = []
        self._alerts_lock = threading.Lock()

        # Deduplication: {mac: last_sequence_number}
        self._last_seq: Dict[str, int] = {}
        self._seq_lock = threading.Lock()

        # Position calculation throttling
        self._last_position_calc: Dict[str, datetime] = {}
        self._calc_lock = threading.Lock()

        # Auth failure counters
        self._auth_counters = {
            "unknown_mac": 0,
            "missing_hmac": 0,
            "invalid_hmac": 0,
        }
        self._auth_counter_lock = threading.Lock()

        # Receiver positions for trilateration
        self._receiver_positions = self.settings.receiver_coordinates

        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("MedicineTracker started")

    def stop(self) -> None:
        self._cleanup_running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
        logger.info("MedicineTracker stopped")

    # ------------------------------------------------------------------
    # Public getters (for API endpoints)
    # ------------------------------------------------------------------

    def get_latest_statuses(self) -> List[Dict[str, Any]]:
        with self._status_lock:
            return list(self._latest_status.values())

    def get_latest_positions(self) -> List[Dict[str, Any]]:
        with self._positions_lock:
            return list(self._latest_positions.values())

    def get_alerts(self) -> List[Dict[str, Any]]:
        with self._alerts_lock:
            return list(self._alerts)

    def get_buffer_stats(self) -> Dict[str, Any]:
        with self._buffer_lock:
            return {
                "mac_count": len(self._buffer),
                "total_entries": sum(len(r) for r in self._buffer.values()),
                "receivers_per_mac": {
                    mac: len(receivers) for mac, receivers in self._buffer.items()
                },
            }

    def get_auth_stats(self) -> Dict[str, int]:
        with self._auth_counter_lock:
            return dict(self._auth_counters)

    def _db_log(self, method_name: str, *args, **kwargs) -> None:
        """Fire-and-forget write to InfluxDB for historical data."""
        if self.db is None:
            return
        try:
            getattr(self.db, method_name)(*args, **kwargs)
        except Exception as e:
            logger.debug(f"DB log failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_loop(self) -> None:
        while self._cleanup_running:
            try:
                self._cleanup_old_data()
                time.sleep(5.0)
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    def _cleanup_old_data(self) -> None:
        cutoff_time = datetime.utcnow() - timedelta(
            seconds=self.settings.buffer_timeout_seconds
        )
        removed_count = 0

        with self._buffer_lock:
            stale_macs = []
            for mac in list(self._buffer.keys()):
                for receiver_id in list(self._buffer[mac].keys()):
                    entry_ts = self._buffer[mac][receiver_id].get("ts")
                    if entry_ts and entry_ts < cutoff_time:
                        del self._buffer[mac][receiver_id]
                        removed_count += 1
                if not self._buffer[mac]:
                    del self._buffer[mac]
                    stale_macs.append(mac)

        if stale_macs:
            with self._seq_lock:
                for mac in stale_macs:
                    self._last_seq.pop(mac, None)
            for mac in stale_macs:
                reset_kalman_filter(mac)
            # Clear stale statuses and positions
            with self._status_lock:
                for mac in stale_macs:
                    self._latest_status.pop(mac, None)
            with self._positions_lock:
                for mac in stale_macs:
                    self._latest_positions.pop(mac, None)

        if removed_count > 0:
            logger.debug(f"Cleaned up {removed_count} stale buffer entries")

    # ------------------------------------------------------------------
    # MQTT callback
    # ------------------------------------------------------------------

    def on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            topic_parts = message.topic.split("/")
            if len(topic_parts) < 4:
                return

            payload = json.loads(message.payload.decode("utf-8"))
            is_rssi_only = (topic_parts[2] == "rssi_only")

            if is_rssi_only:
                mac = (payload.get("mac") or topic_parts[3]).upper()
                rssi = payload.get("rssi")
                receiver_id = payload.get("receiver_id")
                if not mac or rssi is None or not receiver_id:
                    return

                tag = tag_registry.get_tag(mac)
                if tag is None:
                    return

                medicine = tag["medicine_name"]
                distance = get_smoothed_distance(
                    mac, rssi,
                    self.settings.rssi_reference,
                    self.settings.path_loss_exponent,
                    receiver_id=receiver_id,
                )
                self._update_buffer(mac=mac, receiver_id=receiver_id,
                                    distance=distance, medicine=medicine)
                self._try_calculate_position(mac, medicine)
                return

            # Full scan topic: hospital/medicine/scan/{receiver_id}
            receiver_id = topic_parts[3]
            logger.info(f"RAW PAYLOAD: {payload}")

            mac = payload.get("mac")
            rssi = payload.get("rssi")
            seq = payload.get("sequence_number") or payload.get("seq")
            if not mac or rssi is None:
                return

            mac = mac.upper()

            # Tag registry lookup
            tag = tag_registry.get_tag(mac)
            if tag is None:
                with self._auth_counter_lock:
                    self._auth_counters["unknown_mac"] += 1
                logger.warning(f"MAC {mac} not in tag registry (receiver={receiver_id})")
                return

            # HMAC verification
            if "hmac" not in payload:
                with self._auth_counter_lock:
                    self._auth_counters["missing_hmac"] += 1
                logger.warning(f"No HMAC for {mac} (receiver={receiver_id})")
                return

            if not hmac_verify.verify_from_mqtt_payload(payload, tag["hmac_key"]):
                with self._auth_counter_lock:
                    self._auth_counters["invalid_hmac"] += 1
                logger.warning(f"Invalid HMAC for {mac} from {receiver_id}")
                return

            medicine = tag["medicine_name"]

            # Deduplication
            if not self._check_sequence(mac, seq):
                return

            temperature = payload.get("temperature")
            battery = payload.get("battery")
            moving = payload.get("moving", False)

            distance = get_smoothed_distance(
                mac, rssi,
                self.settings.rssi_reference,
                self.settings.path_loss_exponent,
                receiver_id=receiver_id,
            )

            # Update in-memory latest status
            with self._status_lock:
                self._latest_status[mac] = {
                    "mac": mac,
                    "medicine": medicine,
                    "receiver_id": receiver_id,
                    "distance": round(distance, 2),
                    "temperature": temperature,
                    "battery": battery,
                    "moving": moving,
                    "sequence_number": seq,
                    "time": datetime.utcnow().isoformat() + "Z",
                }

            # Log to InfluxDB for history
            self._db_log(
                "write_scan", mac=mac, receiver_id=receiver_id,
                distance=distance, medicine=medicine, temperature=temperature,
                battery=battery, moving=moving, sequence_number=seq,
            )

            # Update buffer for trilateration
            self._update_buffer(
                mac=mac, receiver_id=receiver_id, distance=distance,
                medicine=medicine, temperature=temperature,
                battery=battery, moving=moving,
            )

            self._try_calculate_position(mac, medicine)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON payload: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_sequence(self, mac: str, seq: Optional[int]) -> bool:
        if seq is None:
            return True
        with self._seq_lock:
            last_seq = self._last_seq.get(mac)
            if last_seq is None:
                self._last_seq[mac] = seq
                return True
            diff = (seq - last_seq) % 65536
            if 1 <= diff <= 1000:
                self._last_seq[mac] = seq
                return True
            return False

    def _update_buffer(
        self, mac: str, receiver_id: str, distance: float,
        medicine: str, temperature: Optional[float] = None,
        battery: Optional[int] = None, moving: bool = False,
    ) -> None:
        with self._buffer_lock:
            self._buffer[mac][receiver_id] = {
                "distance": distance,
                "ts": datetime.utcnow(),
                "medicine": medicine,
                "temperature": temperature,
                "battery": battery,
                "moving": moving,
            }

    def _add_alert(
        self, mac: str, alert_type: str, message: str,
        severity: str = "warning", medicine: str = "",
    ) -> None:
        with self._alerts_lock:
            self._alerts.insert(0, {
                "mac": mac,
                "alert_type": alert_type,
                "message": message,
                "severity": severity,
                "medicine": medicine,
                "resolved": False,
                "time": datetime.utcnow().isoformat() + "Z",
            })
            if len(self._alerts) > MAX_ALERTS:
                self._alerts = self._alerts[:MAX_ALERTS]
        # Log to InfluxDB for history
        self._db_log(
            "write_alert", mac=mac, alert_type=alert_type,
            message=message, severity=severity, medicine=medicine,
        )

    def resolve_alerts(self, mac: str, alert_type: str = None, message: str = None) -> None:
        """Mark matching alerts as resolved."""
        with self._alerts_lock:
            for alert in self._alerts:
                if alert["mac"] != mac or alert.get("resolved"):
                    continue
                if alert_type and alert["alert_type"] != alert_type:
                    continue
                alert["resolved"] = True
                alert["resolved_at"] = datetime.utcnow().isoformat() + "Z"
            if message:
                self._alerts.insert(0, {
                    "mac": mac,
                    "alert_type": "resolved",
                    "message": message,
                    "severity": "info",
                    "medicine": "",
                    "resolved": True,
                    "time": datetime.utcnow().isoformat() + "Z",
                })
        # Log resolution to InfluxDB
        if message:
            self._db_log(
                "write_alert", mac=mac, alert_type="resolved",
                message=message, severity="info",
            )

    def _try_calculate_position(self, mac: str, medicine: str) -> None:
        now = datetime.utcnow()
        with self._calc_lock:
            last_calc = self._last_position_calc.get(mac)
            if last_calc:
                elapsed = (now - last_calc).total_seconds()
                if elapsed < self.settings.position_calculation_interval:
                    return

        with self._buffer_lock:
            if mac not in self._buffer:
                return
            receiver_data = self._buffer[mac].copy()

        if not receiver_data:
            return

        receiver_tuples = []
        distances: Dict[str, float] = {}
        for receiver_id, data in receiver_data.items():
            if receiver_id in self._receiver_positions:
                rx, ry = self._receiver_positions[receiver_id]
                receiver_tuples.append((rx, ry, data["distance"]))
                distances[receiver_id] = data["distance"]

        if not receiver_tuples:
            return

        # Debug: log all receiver inputs
        for receiver_id, dist in distances.items():
            rx, ry = self._receiver_positions[receiver_id]
            logger.info(
                f"[POS INPUT] {mac} | {receiver_id} @ ({rx}, {ry}) | dist={dist:.2f}m"
            )

        result = localize(receiver_tuples)
        if not result:
            logger.warning(f"[POS FAIL] {mac} | localize returned None with {len(receiver_tuples)} receivers")
            return

        x, y = result["x"], result["y"]
        method = result["method"]

        rmse = calculate_position_error(
            (x, y), self._receiver_positions, distances
        )
        confidence = calculate_confidence(method, len(receiver_tuples), rmse)

        with self._calc_lock:
            self._last_position_calc[mac] = now

        # Store position in memory
        with self._positions_lock:
            self._latest_positions[mac] = {
                "mac": mac,
                "x": round(x, 2),
                "y": round(y, 2),
                "accuracy": round(rmse, 2),
                "confidence": round(confidence),
                "method": method,
                "medicine": medicine,
                "receiver_count": len(receiver_tuples),
                "time": now.isoformat() + "Z",
            }

        # Log position to InfluxDB for history
        self._db_log(
            "write_position", mac=mac, x=x, y=y,
            accuracy=rmse, confidence=confidence, method=method,
            medicine=medicine, receiver_count=len(receiver_tuples),
        )

        logger.info(
            f"[POS RESULT] {mac} | ({x:.2f}, {y:.2f}) | method={method} "
            f"confidence={confidence:.0f} | rmse={rmse:.2f}m | receivers={len(receiver_tuples)}"
        )

        # Out-of-bounds alert
        bounds = {"x_min": -5.0, "x_max": 15.0, "y_min": -5.0, "y_max": 15.0}
        if (x < bounds["x_min"] or x > bounds["x_max"] or
                y < bounds["y_min"] or y > bounds["y_max"]):
            self._add_alert(
                mac=mac,
                alert_type="out_of_bounds",
                message=f"Position ({x:.1f}, {y:.1f}) outside safe area",
                severity="critical",
                medicine=medicine,
            )
