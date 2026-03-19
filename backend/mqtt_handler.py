"""MQTT message handler for the Medical Tracker IoT backend.

This module provides the MedicineTracker class for processing MQTT messages
from BLE receivers, managing RSSI buffers, and triggering position calculations.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings
from database import Database
import engine as eng

logger = logging.getLogger(__name__)


class MedicineTracker:
    """MQTT message handler for medicine tracking.

    Manages RSSI buffers, handles incoming MQTT messages, performs
    deduplication, calculates positions via trilateration, and handles
    movement detection.
    """

    def __init__(self, database: Database) -> None:
        """Initialize the medicine tracker.

        Args:
            database: Database instance for storing data.
        """
        self.db = database
        self.settings = settings

        # Buffer structure: {mac: {receiver_id: {rssi, ts, medicine, temp, battery, moving}}}
        self._buffer: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self._buffer_lock = threading.RLock()

        # Deduplication: {mac: last_sequence_number}
        self._last_seq: Dict[str, int] = {}
        self._seq_lock = threading.Lock()

        # Position calculation throttling: {mac: last_calculation_timestamp}
        self._last_position_calc: Dict[str, datetime] = {}
        self._calc_lock = threading.Lock()

        # Latest position cache: {mac: {x, y, medicine, time}}
        self._latest_positions: Dict[str, Dict[str, Any]] = {}
        self._positions_lock = threading.Lock()

        # Receiver positions for trilateration
        self._receiver_positions = self.settings.receiver_coordinates

        # Start cleanup thread
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_running = False

    def start(self) -> None:
        """Start background cleanup thread."""
        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("MedicineTracker cleanup thread started")

    def stop(self) -> None:
        """Stop background cleanup thread."""
        self._cleanup_running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
        logger.info("MedicineTracker cleanup thread stopped")

    def _cleanup_loop(self) -> None:
        """Background loop to clean up stale buffer entries."""
        while self._cleanup_running:
            try:
                self._cleanup_old_data()
                time.sleep(5.0)  # Check every 5 seconds
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    def _cleanup_old_data(self) -> None:
        """Remove buffer entries older than the timeout threshold."""
        cutoff_time = datetime.utcnow() - timedelta(
            seconds=self.settings.buffer_timeout_seconds
        )
        removed_count = 0

        with self._buffer_lock:
            for mac in list(self._buffer.keys()):
                for receiver_id in list(self._buffer[mac].keys()):
                    entry_ts = self._buffer[mac][receiver_id].get("ts")
                    if entry_ts and entry_ts < cutoff_time:
                        del self._buffer[mac][receiver_id]
                        removed_count += 1

                # Remove empty MAC entries
                if not self._buffer[mac]:
                    del self._buffer[mac]

        if removed_count > 0:
            logger.debug(f"Cleaned up {removed_count} stale buffer entries")

    def on_message(
        self,
        client: Any,
        userdata: Any,
        message: Any
    ) -> None:
        """MQTT message callback handler.

        Processes incoming MQTT messages from BLE receivers, performs
        deduplication, stores scan data, and triggers position calculation
        when sufficient data is available.

        Args:
            client: MQTT client instance.
            userdata: User data passed to callback.
            message: MQTT message object with topic and payload attributes.
        """
        try:
            # Parse topic to extract receiver_id
            # Topic format: medical/{receiver_id}/status
            topic_parts = message.topic.split("/")
            if len(topic_parts) < 3:
                logger.warning(f"Unexpected topic format: {message.topic}")
                return

            receiver_id = topic_parts[1]

            # Parse JSON payload
            payload = json.loads(message.payload.decode("utf-8"))
            logger.info(f"RAW PAYLOAD: {payload}")  # Debug: see actual data

            # Extract required fields
            mac = payload.get("mac")
            rssi = payload.get("rssi")
            seq = payload.get("sequence_number") or payload.get("seq")
            medicine = payload.get("medicine", "unknown")

            if not mac or rssi is None:
                logger.warning(f"Missing required fields in message: {payload}")
                return

            # Deduplication check
            if not self._check_sequence(mac, seq):
                logger.debug(f"Duplicate message dropped for {mac}")
                return

            # Extract optional fields
            temperature = payload.get("temperature")
            battery = payload.get("battery")
            moving = payload.get("moving", False)

            # Smooth RSSI via Kalman filter then convert to distance
            distance = eng.get_smoothed_distance(f"{mac}_{receiver_id}", rssi, A=-60.0, n=3.0)

            logger.debug(
                f"Received from {receiver_id}: {mac} @ {rssi}dBm -> {distance:.2f}m, "
                f"medicine={medicine}, moving={moving}"
            )

            # Store raw scan data in database (with calculated distance)
            logger.info(f"WRITING TO DB: distance={distance:.2f}m, temp={temperature}, batt={battery}, moving={moving}, seq={seq}")
            self.db.write_scan(
                mac=mac,
                receiver_id=receiver_id,
                distance=distance,
                medicine=medicine,
                temperature=temperature,
                battery=battery,
                moving=moving,
                sequence_number=seq
            )

            # Update buffer
            self._update_buffer(
                mac=mac,
                receiver_id=receiver_id,
                distance=distance,
                medicine=medicine,
                temperature=temperature,
                battery=battery,
                moving=moving
            )

            # Handle movement detection
            if moving:
                self._handle_movement(mac, medicine, receiver_id)

            # Try to calculate position
            self._try_calculate_position(mac, medicine)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON payload: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def _check_sequence(self, mac: str, seq: Optional[int]) -> bool:
        """Check if message is new based on sequence number.

        Args:
            mac: MAC address of the beacon.
            seq: Sequence number from the message.

        Returns:
            bool: True if message should be processed, False if duplicate.
        """
        if seq is None:
            # No sequence number, allow through
            return True

        with self._seq_lock:
            last_seq = self._last_seq.get(mac)
            if last_seq is not None and seq <= last_seq:
                # Check if it's a wraparound (seq reset to 0)
                # If last was 90+ and new is 0-10, it's a reset, not duplicate
                if last_seq > 90 and seq <= 10:
                    logger.debug(f"Sequence reset detected for {mac}: {last_seq} -> {seq}")
                    self._last_seq[mac] = seq
                    return True
                if last_seq - seq <= 100:  # Not a wraparound (within 100)
                    logger.debug(f"Duplicate sequence detected for {mac}: {seq} <= {last_seq}")
                    return False
            self._last_seq[mac] = seq
            return True

    def _update_buffer(
        self,
        mac: str,
        receiver_id: str,
        distance: float,
        medicine: str,
        temperature: Optional[float] = None,
        battery: Optional[int] = None,
        moving: bool = False
    ) -> None:
        """Update the distance buffer with new data.

        Args:
            mac: MAC address of the beacon.
            receiver_id: ID of the receiver.
            distance: Calculated distance in meters.
            medicine: Medicine name/type.
            temperature: Optional temperature reading.
            battery: Optional battery level.
            moving: Whether the medicine is moving.
        """
        with self._buffer_lock:
            self._buffer[mac][receiver_id] = {
                "distance": distance,
                "ts": datetime.utcnow(),
                "medicine": medicine,
                "temperature": temperature,
                "battery": battery,
                "moving": moving
            }

    def _handle_movement(
        self,
        mac: str,
        medicine: str,
        receiver_id: str
    ) -> None:
        """Handle movement detection alert.

        Args:
            mac: MAC address of the medicine.
            medicine: Medicine name/type.
            receiver_id: ID of receiver that detected movement.
        """
        logger.info(f"Movement detected for {mac} ({medicine}) by {receiver_id}")

        self.db.write_alert(
            mac=mac,
            alert_type="movement",
            message=f"Movement detected by {receiver_id}",
            severity="warning",
            medicine=medicine,
            metadata={"receiver_id": receiver_id}
        )

    def _try_calculate_position(self, mac: str, medicine: str) -> None:
        """Attempt to calculate position when sufficient receivers are available.

        Position calculation is throttled to avoid excessive calculations.
        Requires at least 2 receivers.

        Args:
            mac: MAC address of the medicine.
            medicine: Medicine name/type.
        """
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

        if len(receiver_data) < 3:
            return

        # Build (x, y, distance) tuples for the engine
        receivers = []
        for receiver_id, data in receiver_data.items():
            coords = self._receiver_positions.get(receiver_id)
            if coords is None:
                continue
            receivers.append((coords[0], coords[1], data["distance"]))

        if len(receivers) < 3:
            return

        result = eng.localize(receivers)
        if result is None:
            return

        x, y = result["x"], result["y"]
        success = self.db.write_position(
            mac=mac,
            x=x,
            y=y,
            accuracy=0.0,
            medicine=medicine,
            receiver_count=len(receivers)
        )

        if success:
            with self._calc_lock:
                self._last_position_calc[mac] = now
            with self._positions_lock:
                self._latest_positions[mac] = {
                    "mac": mac,
                    "medicine": medicine,
                    "x": x,
                    "y": y,
                    "receiver_count": len(receivers),
                    "time": now.isoformat(),
                }
            self._check_position_alerts(mac, medicine, x, y)

    def _check_position_alerts(
        self,
        mac: str,
        medicine: str,
        x: float,
        y: float,
    ) -> None:
        """Check if position triggers any alerts.

        Args:
            mac: MAC address of the medicine.
            medicine: Medicine name/type.
            x: X coordinate in meters.
            y: Y coordinate in meters.
        """
        bounds = {
            "x_min": -5.0, "x_max": 15.0,
            "y_min": -5.0, "y_max": 15.0,
        }

        if (x < bounds["x_min"] or x > bounds["x_max"] or
                y < bounds["y_min"] or y > bounds["y_max"]):

            logger.warning(f"Medicine {mac} out of bounds at ({x:.2f}, {y:.2f})")

            self.db.write_alert(
                mac=mac,
                alert_type="out_of_bounds",
                message=f"Medicine position ({x:.1f}, {y:.1f}) outside safe area",
                severity="critical",
                medicine=medicine,
                metadata={"x": x, "y": y}
            )

    def get_latest_positions(self) -> List[Dict[str, Any]]:
        """Return the latest calculated position for each tracked tag."""
        with self._positions_lock:
            return list(self._latest_positions.values())

    def get_buffer_stats(self) -> Dict[str, Any]:
        """Get statistics about the current buffer state.

        Returns:
            Dict with buffer statistics.
        """
        with self._buffer_lock:
            mac_count = len(self._buffer)
            total_entries = sum(len(receivers) for receivers in self._buffer.values())

            return {
                "mac_count": mac_count,
                "total_entries": total_entries,
                "receivers_per_mac": {
                    mac: len(receivers) for mac, receivers in self._buffer.items()
                }
            }
