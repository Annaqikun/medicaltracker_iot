"""BLE ACK orchestration for the Medical Tracker IoT backend.

This module provides the AckOrchestrator class which periodically requests
BLE acknowledgement checks for every registered tag and processes the
results.  When a tag fails to respond after several attempts it is flagged
as potentially lost via a database alert.
"""

import json
import logging
import threading
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from config import settings
from database import Database

# TODO: replace with tag_registry.get_whitelist() after merging HMAC branch
HARDCODED_TAGS = [
    "4C:75:25:CB:86:62",
]

logger = logging.getLogger(__name__)


class AckOrchestrator:
    """Orchestrates periodic BLE ACK checks for all registered tags.

    The orchestrator runs a daemon thread that wakes every
    ``ACK_CHECK_INTERVAL_SECONDS`` and, for each whitelisted MAC address,
    publishes a check request on the MQTT topic
    ``hospital/medicine/ack_check/{mac}``.  Results arrive on
    ``hospital/medicine/ack_result/{receiver_id}`` and are processed by
    :meth:`on_ack_result`.
    """

    def __init__(self, database: Database) -> None:
        """Initialise the ACK orchestrator.

        Args:
            database: Database instance used for writing alerts.
        """
        self.db = database

        # {mac: {"last_success_ts": datetime|None, "attempts": int, "last_request_ts": datetime|None}}
        self._ack_state: Dict[str, Dict[str, Any]] = {}
        self._ack_state_lock = threading.Lock()

        self._mqtt_client: Optional[mqtt.Client] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, mqtt_client: mqtt.Client) -> None:
        """Start the background orchestration loop.

        Args:
            mqtt_client: Connected MQTT client used for publishing check
                requests.
        """
        self._mqtt_client = mqtt_client
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("AckOrchestrator started")

    def stop(self) -> None:
        """Stop the background orchestration loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("AckOrchestrator stopped")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Daemon loop that periodically checks all tags."""
        while self._running:
            try:
                self._check_all_tags()
            except Exception as e:
                logger.error(f"Error in ACK orchestration loop: {e}")
            time.sleep(settings.ack_check_interval_seconds)

    def _check_all_tags(self) -> None:
        """Run one pass of the orchestration logic for every registered MAC."""
        macs = HARDCODED_TAGS  # TODO: use tag_registry.get_whitelist()
        now = datetime.utcnow()

        with self._ack_state_lock:
            for mac in macs:
                # Ensure state entry exists
                if mac not in self._ack_state:
                    self._ack_state[mac] = {
                        "last_success_ts": None,
                        "attempts": 0,
                        "last_request_ts": None,
                    }

                state = self._ack_state[mac]

                # --- Timeout detection (count once per request) ---
                if state["last_request_ts"] is not None:
                    elapsed = (now - state["last_request_ts"]).total_seconds()
                    if elapsed > settings.ack_result_timeout_seconds:
                        no_success_since_request = (
                            state["last_success_ts"] is None
                            or state["last_success_ts"] < state["last_request_ts"]
                        )
                        if no_success_since_request:
                            state["attempts"] += 1
                            logger.warning(
                                f"[ACK] Timeout for tag {mac}, attempt {state['attempts']}"
                            )
                        # Clear so we don't re-count this same request
                        state["last_request_ts"] = None

                # --- Max attempts exceeded → alert ---
                if state["attempts"] >= settings.ack_max_attempts:
                    logger.warning(
                        f"[ACK] Tag {mac} potentially lost after "
                        f"{state['attempts']} failed attempts"
                    )
                    self.db.write_alert(
                        mac=mac,
                        alert_type="tag_potentially_lost",
                        message=(
                            f"Tag {mac} did not respond to "
                            f"{state['attempts']} ACK requests"
                        ),
                        severity="critical",
                    )
                    state["attempts"] = 0
                    continue  # don't immediately re-request after alert

                # --- Decide whether to send a new check request ---
                # Don't request if one is already pending (not yet timed out)
                if state["last_request_ts"] is not None:
                    continue  # request in flight, wait for timeout or result

                should_request = (
                    state["last_success_ts"] is None
                    or (now - state["last_success_ts"]).total_seconds()
                    >= settings.ack_period_seconds
                )

                if should_request:
                    self._publish_check(mac)
                    state["last_request_ts"] = now

    def _publish_check(self, mac: str) -> None:
        """Publish an ACK check request for *mac*.

        Args:
            mac: MAC address of the tag to check.
        """
        if self._mqtt_client is None:
            logger.warning("[ACK] Cannot publish check — MQTT client not set")
            return

        topic = f"hospital/medicine/ack_check/{mac}"
        try:
            self._mqtt_client.publish(topic, payload="{}", qos=1)
            logger.info(f"[ACK] Published check request on {topic}")
        except Exception as e:
            logger.error(f"[ACK] Failed to publish check for {mac}: {e}")

    # ------------------------------------------------------------------
    # MQTT callback
    # ------------------------------------------------------------------

    def on_ack_result(self, client: Any, userdata: Any, message: Any) -> None:
        """Handle an incoming ACK result message.

        Expected topic format::

            hospital/medicine/ack_result/{receiver_id}

        Expected JSON payload::

            {"mac": "XX:XX:XX:XX:XX:XX", "status": "success"}

        Args:
            client: MQTT client (unused).
            userdata: User data (unused).
            message: MQTT message with ``topic`` and ``payload`` attributes.
        """
        try:
            topic_parts = message.topic.split("/")
            if len(topic_parts) < 4:
                logger.warning(f"[ACK] Unexpected topic format: {message.topic}")
                return

            receiver_id = topic_parts[3]

            payload = json.loads(message.payload.decode("utf-8"))
            mac = payload.get("mac")
            status = payload.get("status")

            if not mac:
                logger.warning(f"[ACK] Missing 'mac' in ack_result payload: {payload}")
                return

            if status == "success":
                now = datetime.utcnow()
                with self._ack_state_lock:
                    if mac not in self._ack_state:
                        self._ack_state[mac] = {
                            "last_success_ts": None,
                            "attempts": 0,
                            "last_request_ts": None,
                        }
                    self._ack_state[mac]["last_success_ts"] = now
                    self._ack_state[mac]["attempts"] = 0

                logger.info(f"[ACK] Tag {mac} confirmed alive by {receiver_id}")
            else:
                logger.debug(
                    f"[ACK] Non-success status for {mac} from {receiver_id}: {status}"
                )

        except json.JSONDecodeError as e:
            logger.error(f"[ACK] Failed to decode ack_result payload: {e}")
        except Exception as e:
            logger.error(f"[ACK] Error processing ack_result: {e}")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_ack_stats(self) -> Dict[str, Any]:
        """Return a snapshot of the internal ACK state for all tags.

        Returns:
            Dict mapping each MAC to its current state (deep copy).
        """
        with self._ack_state_lock:
            return deepcopy(self._ack_state)
