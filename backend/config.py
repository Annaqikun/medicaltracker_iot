"""Configuration settings for the Medical Tracker IoT backend.

This module provides python-dotenv based configuration management for MQTT,
InfluxDB, and receiver coordinates used in trilateration.
"""

import os
from pathlib import Path
from typing import Dict, Tuple, Optional

from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    """Main application settings using python-dotenv."""

    # MQTT Settings
    MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_CA_CERT = os.getenv("MQTT_CA_CERT")  # None if not set
    MQTT_TOPIC = os.getenv("MQTT_TOPIC", "hospital/medicine/scan/#")

    # InfluxDB Settings
    INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
    INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
    INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "medical")
    INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "medicine_tracking")

    # Receiver coordinates for trilateration (receiver_id -> (x, y, z))
    # Coordinates are in meters relative to a reference point
    RECEIVER_COORDINATES: Dict[str, Tuple[float, float, float]] = {
        "receiver_1": (0.0, 0.0, 2.0),
        "receiver_2": (10.0, 0.0, 2.0),
        "receiver_3": (5.0, 8.66, 2.0),
        "receiver_4": (5.0, 2.89, 2.0),
    }

    # RSSI to distance conversion parameters
    RSSI_REFERENCE = int(os.getenv("RSSI_REFERENCE", "-59"))
    PATH_LOSS_EXPONENT = float(os.getenv("PATH_LOSS_EXPONENT", "2.5"))

    # Buffer management settings
    BUFFER_TIMEOUT_SECONDS = float(os.getenv("BUFFER_TIMEOUT_SECONDS", "10.0"))
    POSITION_CALCULATION_INTERVAL = float(os.getenv("POSITION_CALCULATION_INTERVAL", "2.0"))

    # ACK orchestration
    ACK_PERIOD_SECONDS = float(os.getenv("ACK_PERIOD_SECONDS", "120.0"))
    ACK_CHECK_INTERVAL_SECONDS = float(os.getenv("ACK_CHECK_INTERVAL_SECONDS", "10.0"))
    ACK_MAX_ATTEMPTS = int(os.getenv("ACK_MAX_ATTEMPTS", "100"))
    ACK_RESULT_TIMEOUT_SECONDS = float(os.getenv("ACK_RESULT_TIMEOUT_SECONDS", "30.0"))

    # For backward compatibility - nested access
    @property
    def mqtt(self):
        """Return MQTT settings as a simple object for backward compatibility."""
        class MQTT:
            host = self.MQTT_HOST
            port = self.MQTT_PORT
            username = self.MQTT_USERNAME
            password = self.MQTT_PASSWORD
            ca_cert = self.MQTT_CA_CERT
            topic = self.MQTT_TOPIC
        return MQTT()

    @property
    def influxdb(self):
        """Return InfluxDB settings as a simple object for backward compatibility."""
        class InfluxDB:
            url = self.INFLUXDB_URL
            token = self.INFLUXDB_TOKEN
            org = self.INFLUXDB_ORG
            bucket = self.INFLUXDB_BUCKET
        return InfluxDB()

    # Backward compatibility property names
    @property
    def receiver_coordinates(self):
        """Return receiver coordinates for trilateration."""
        return self.RECEIVER_COORDINATES

    @property
    def rssi_reference(self):
        """Return RSSI reference value."""
        return self.RSSI_REFERENCE

    @property
    def path_loss_exponent(self):
        """Return path loss exponent."""
        return self.PATH_LOSS_EXPONENT

    @property
    def buffer_timeout_seconds(self):
        """Return buffer timeout in seconds."""
        return self.BUFFER_TIMEOUT_SECONDS

    @property
    def position_calculation_interval(self):
        """Return position calculation interval."""
        return self.POSITION_CALCULATION_INTERVAL

    @property
    def ack_period_seconds(self):
        """Return ACK period in seconds."""
        return self.ACK_PERIOD_SECONDS

    @property
    def ack_check_interval_seconds(self):
        """Return ACK check interval in seconds."""
        return self.ACK_CHECK_INTERVAL_SECONDS

    @property
    def ack_max_attempts(self):
        """Return maximum ACK attempts before alert."""
        return self.ACK_MAX_ATTEMPTS

    @property
    def ack_result_timeout_seconds(self):
        """Return ACK result timeout in seconds."""
        return self.ACK_RESULT_TIMEOUT_SECONDS


# Singleton instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings singleton.

    Returns:
        Settings: Application configuration instance.
    """
    return settings
