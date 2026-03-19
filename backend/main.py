"""FastAPI application for the Medical Tracker IoT backend.

This module provides the main FastAPI application with MQTT integration,
REST API endpoints for querying medicine data, and CORS middleware.
"""

import logging
import ssl
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ack_orchestrator import AckOrchestrator
from config import settings
from database import Database
from mqtt_handler import MedicineTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global instances
db: Optional[Database] = None
medicine_tracker: Optional[MedicineTracker] = None
ack_orchestrator: Optional[AckOrchestrator] = None
mqtt_client: Optional[mqtt.Client] = None
mqtt_thread: Optional[threading.Thread] = None


def setup_mqtt_client(tracker: MedicineTracker) -> mqtt.Client:
    """Configure and create MQTT client.

    Args:
        tracker: MedicineTracker instance for message handling.

    Returns:
        mqtt.Client: Configured MQTT client.
    """
    logger.info(f"MQTT settings: host={settings.MQTT_HOST}, port={settings.MQTT_PORT}, ca_cert={settings.MQTT_CA_CERT}")
    logger.info(f"Loaded MQTT_CA_CERT: {settings.MQTT_CA_CERT}")
    client = mqtt.Client(
        client_id="medical_tracker_backend"
    )

    # Set authentication if provided
    if settings.mqtt.username:
        client.username_pw_set(settings.mqtt.username, settings.mqtt.password)

    # Set TLS if CA cert provided
    if settings.MQTT_CA_CERT:
        logger.info(f"Setting up TLS with CA cert: {settings.MQTT_CA_CERT}")
        client.tls_set(ca_certs=settings.MQTT_CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    else:
        logger.info("No CA cert provided, using plaintext MQTT")

    # Set up callbacks
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(settings.mqtt.topic)
            logger.info(f"Subscribed to topic: {settings.mqtt.topic}")
            client.subscribe("hospital/medicine/ack_result/#")
            logger.info("Subscribed to topic: hospital/medicine/ack_result/#")
        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")

    def on_disconnect(client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker: {rc}")

    def on_subscribe(client, userdata, mid, granted_qos):
        logger.info(f"Subscribed with mid={mid}")

    def on_message(client, userdata, message):
        if message.topic.startswith("hospital/medicine/ack_result/"):
            if ack_orchestrator:
                ack_orchestrator.on_ack_result(client, userdata, message)
        else:
            tracker.on_message(client, userdata, message)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    return client


def mqtt_loop(client: mqtt.Client) -> None:
    """Run MQTT client loop in background thread.

    Args:
        client: MQTT client instance.
    """
    while True:
        try:
            logger.info(
                f"Connecting to MQTT broker at {settings.MQTT_HOST}:{settings.MQTT_PORT}"
            )
            client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT error: {e}")
            time.sleep(5)  # Wait before reconnecting


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Handles startup and shutdown events for the FastAPI application,
    including MQTT client initialization and cleanup.

    Args:
        app: FastAPI application instance.
    """
    global db, medicine_tracker, ack_orchestrator, mqtt_client, mqtt_thread

    # Startup
    logger.info("Starting Medical Tracker backend...")

    try:
        # Initialize database
        db = Database(
            url=settings.INFLUXDB_URL,
            token=settings.INFLUXDB_TOKEN,
            org=settings.INFLUXDB_ORG,
            bucket=settings.INFLUXDB_BUCKET
        )
        logger.info("Database connection established")

        # Initialize medicine tracker
        medicine_tracker = MedicineTracker(db)
        medicine_tracker.start()
        logger.info("Medicine tracker started")

        # Initialize ACK orchestrator
        ack_orchestrator = AckOrchestrator(db)
        logger.info("ACK orchestrator initialised")

        # Initialize MQTT client
        mqtt_client = setup_mqtt_client(medicine_tracker)

        # Start MQTT thread
        mqtt_thread = threading.Thread(target=mqtt_loop, args=(mqtt_client,), daemon=True)
        mqtt_thread.start()
        logger.info("MQTT client thread started")

        # Start ACK orchestrator (needs mqtt_client to be ready)
        ack_orchestrator.start(mqtt_client)
        logger.info("ACK orchestrator started")

        yield

    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise

    finally:
        # Shutdown
        logger.info("Shutting down Medical Tracker backend...")

        if ack_orchestrator:
            ack_orchestrator.stop()
            logger.info("ACK orchestrator stopped")

        if medicine_tracker:
            medicine_tracker.stop()
            logger.info("Medicine tracker stopped")

        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            logger.info("MQTT client disconnected")

        if db:
            db.close()
            logger.info("Database connection closed")


# Create FastAPI application
app = FastAPI(
    title="Medical Tracker IoT Backend",
    description="Backend API for tracking medical supplies via BLE beacons",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint returning API information.

    Returns:
        Dict with API status and version information.
    """
    return {
        "name": "Medical Tracker IoT Backend",
        "version": "1.0.0",
        "status": "running",
        "endpoints": [
            "/",
            "/api/medicines",
            "/api/medicine/{mac}/history",
            "/api/alerts",
            "/api/ack_status"
        ]
    }


@app.get("/api/medicines")
async def get_medicines() -> List[Dict[str, Any]]:
    """Get current status of all tracked medicines (raw scan data).

    Returns:
        List of medicine status records.

    Raises:
        HTTPException: If database is not available.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        # Query raw scan data instead of calculated positions
        # (positions require 2+ receivers for trilateration)
        statuses = db.query_latest_status()
        return statuses
    except Exception as e:
        logger.error(f"Error querying medicines: {e}")
        raise HTTPException(status_code=500, detail="Failed to query medicines")


@app.get("/api/data")
async def get_all_data(minutes: int = 60) -> List[Dict[str, Any]]:
    """Get all raw data from InfluxDB.

    Args:
        minutes: How many minutes of data to retrieve (default: 60)

    Returns:
        List of all records from medicine_status.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        records = db.query_all_data(minutes)
        return records
    except Exception as e:
        logger.error(f"Error querying data: {e}")
        raise HTTPException(status_code=500, detail="Failed to query data")


@app.get("/api/medicine/{mac}/history")
async def get_medicine_history(
    mac: str,
    hours: int = 24
) -> List[Dict[str, Any]]:
    """Get position and status history for a specific medicine.

    Args:
        mac: MAC address of the medicine beacon.
        hours: Number of hours of history to retrieve (default: 24).

    Returns:
        List of historical records for the medicine.

    Raises:
        HTTPException: If database is not available or query fails.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    if hours < 1 or hours > 168:  # Max 1 week
        raise HTTPException(status_code=400, detail="Hours must be between 1 and 168")

    try:
        history = db.query_medicine_history(mac, hours)
        return history
    except Exception as e:
        logger.error(f"Error querying medicine history for {mac}: {e}")
        raise HTTPException(status_code=500, detail="Failed to query medicine history")


@app.get("/api/alerts")
async def get_alerts(
    hours: int = 24,
    severity: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get alerts from the system.

    Args:
        hours: Number of hours of alerts to retrieve (default: 24).
        severity: Optional filter by severity ("info", "warning", "critical").

    Returns:
        List of alert records.

    Raises:
        HTTPException: If database is not available or query fails.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="Hours must be between 1 and 168")

    if severity and severity not in ["info", "warning", "critical"]:
        raise HTTPException(
            status_code=400,
            detail="Severity must be one of: info, warning, critical"
        )

    try:
        alerts = db.query_alerts(hours=hours, severity=severity)
        return alerts
    except Exception as e:
        logger.error(f"Error querying alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to query alerts")


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    """Get system status and buffer statistics.

    Returns:
        Dict with system status information.

    Raises:
        HTTPException: If tracker is not available.
    """
    if medicine_tracker is None:
        raise HTTPException(status_code=503, detail="Tracker not available")

    try:
        buffer_stats = medicine_tracker.get_buffer_stats()
        return {
            "status": "running",
            "buffer": buffer_stats,
            "mqtt_connected": mqtt_client.is_connected() if mqtt_client else False
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get status")


@app.get("/api/ack_status")
async def get_ack_status() -> Dict[str, Any]:
    """Get ACK orchestration status for all tracked tags.

    Returns:
        Dict mapping each MAC address to its ACK state.
    """
    if ack_orchestrator:
        return ack_orchestrator.get_ack_stats()
    return {}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
