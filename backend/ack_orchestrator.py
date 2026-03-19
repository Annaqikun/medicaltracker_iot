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
import tag_registry

# All M5 tags currently use "m5tag" as their MQTT tag_id.
# TODO: add per-device tag_id to tag_registry schema for multi-tag support.
DEFAULT_TAG_ID = "m5tag"


def mac_to_tag_id(mac: str) -> str:
    """Map a MAC address to its MQTT tag_id."""
    # For now all tags share the same tag_id
    return DEFAULT_TAG_ID


def tag_id_to_mac(tag_id: str) -> Optional[str]:
    """Map a tag_id to its MAC address. Returns first match."""
    if tag_id == DEFAULT_TAG_ID:
        whitelist = tag_registry.get_whitelist()
        return whitelist[0] if whitelist else None
    return None

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
        macs = tag_registry.get_whitelist()
        now = datetime.utcnow()

        with self._ack_state_lock:
            for mac in macs:
                # Ensure state entry exists
                if mac not in self._ack_state:
                    self._ack_state[mac] = {
                        "last_success_ts": None,
                        "attempts": 0,
                        "last_request_ts": None,
                        "lost": False,
                        "resume_requested": False,
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

                # --- Max attempts exceeded → mark as lost ---
                if state["attempts"] >= settings.ack_max_attempts and not state.get("lost"):
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
                    state["lost"] = True
                    state["resume_requested"] = True

                # --- Decide whether to send a new check request ---
                is_emergency = state.get("lost", False)

                # Don't request if one is already pending (not yet timed out)
                if state["last_request_ts"] is not None:
                    if not is_emergency:
                        continue  # routine: wait for timeout
                    # Emergency: re-request every check interval (10s) instead of waiting for full timeout
                    elapsed_since_request = (now - state["last_request_ts"]).total_seconds()
                    if elapsed_since_request < settings.ack_check_interval_seconds:
                        continue  # too soon, wait for next loop tick

                should_request = (
                    is_emergency  # always request if lost
                    or state["last_success_ts"] is None
                    or (now - state["last_success_ts"]).total_seconds()
                    >= settings.ack_period_seconds
                )

                if should_request:
                    self._publish_check(mac, emergency=is_emergency)
                    state["last_request_ts"] = now

    def _publish_check(self, mac: str, emergency: bool = False) -> None:
        """Publish an ACK check request for *mac*.

        Args:
            mac: MAC address of the tag to check.
            emergency: If True, RPis should actively search (blind GATT connect).
        """
        if self._mqtt_client is None:
            logger.warning("[ACK] Cannot publish check — MQTT client not set")
            return

        topic = f"hospital/medicine/ack_check/{mac}"
        payload = json.dumps({"emergency": emergency})
        try:
            self._mqtt_client.publish(topic, payload=payload, qos=1)
            mode = "EMERGENCY" if emergency else "routine"
            logger.info(f"[ACK] Published {mode} check request on {topic}")
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
                should_resume = False
                with self._ack_state_lock:
                    if mac not in self._ack_state:
                        self._ack_state[mac] = {
                            "last_success_ts": None,
                            "attempts": 0,
                            "last_request_ts": None,
                            "lost": False,
                            "resume_requested": False,
                        }
                    should_resume = self._ack_state[mac].get("resume_requested", False)
                    self._ack_state[mac]["last_success_ts"] = now
                    self._ack_state[mac]["attempts"] = 0
                    self._ack_state[mac]["last_request_ts"] = None
                    self._ack_state[mac]["lost"] = False
                    self._ack_state[mac]["resume_requested"] = False

                logger.info(f"[ACK] Tag {mac} confirmed alive by {receiver_id}")

                if should_resume and self._mqtt_client:
                    tag_id = mac_to_tag_id(mac)
                    if tag_id:
                        cmd_topic = f"hospital/medicine/command/{tag_id}"
                        self._mqtt_client.publish(cmd_topic, "resume_ble", qos=1)
                        logger.info(f"[ACK] Sent resume_ble to {tag_id} ({mac})")
            elif status == "failed":
                # RPi tried and failed — only count once per check cycle
                with self._ack_state_lock:
                    if mac in self._ack_state and self._ack_state[mac]["last_request_ts"] is not None:
                        self._ack_state[mac]["attempts"] += 1
                        self._ack_state[mac]["last_request_ts"] = None  # clear so we don't double-count
                        logger.warning(
                            f"[ACK] RPi {receiver_id} failed to reach {mac}, "
                            f"attempt {self._ack_state[mac]['attempts']}"
                        )
            else:
                logger.debug(
                    f"[ACK] Unknown status for {mac} from {receiver_id}: {status}"
                )

        except json.JSONDecodeError as e:
            logger.error(f"[ACK] Failed to decode ack_result payload: {e}")
        except Exception as e:
            logger.error(f"[ACK] Error processing ack_result: {e}")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def on_emergency_message(self, client: Any, userdata: Any, message: Any) -> None:
        """Handle M5 emergency messages (e.g. lost_ble status)."""
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            tag_id = payload.get("id")
            status = payload.get("status")

            if status == "lost_ble" and tag_id:
                logger.info(f"[ACK] Emergency message from {tag_id}: {status}")
                self.trigger_emergency_search_for_tag_id(tag_id)
        except Exception as e:
            logger.error(f"[ACK] Failed to process emergency message: {e}")

    def trigger_emergency_search_for_tag_id(self, tag_id: str) -> None:
        """Immediately trigger emergency search for a tag by its tag_id."""
        mac = tag_id_to_mac(tag_id)
        if not mac:
            logger.warning(f"[ACK] Unknown tag_id for emergency trigger: {tag_id}")
            return

        now = datetime.utcnow()

        with self._ack_state_lock:
            state = self._ack_state.setdefault(mac, {
                "last_success_ts": None,
                "attempts": 0,
                "last_request_ts": None,
                "lost": False,
                "resume_requested": False,
            })
            state["lost"] = True
            state["resume_requested"] = True
            state["last_request_ts"] = now  # mark as in-flight so failures are counted

        self._publish_check(mac, emergency=True)
        logger.info(f"[ACK] Forced emergency search for {tag_id} ({mac})")

    def get_ack_stats(self) -> Dict[str, Any]:
        """Return a snapshot of the internal ACK state for all tags.

        Returns:
            Dict mapping each MAC to its current state (deep copy).
        """
        with self._ack_state_lock:
            return deepcopy(self._ack_state)
