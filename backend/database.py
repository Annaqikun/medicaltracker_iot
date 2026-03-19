"""InfluxDB wrapper for the Medical Tracker IoT backend.

This module provides a Database class for storing and querying medicine
scan data, calculated positions, and alerts in InfluxDB.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.domain.write_precision import WritePrecision

logger = logging.getLogger(__name__)


class Database:
    """InfluxDB wrapper for medical tracker data storage and retrieval."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str
    ) -> None:
        """Initialize the InfluxDB client.

        Args:
            url: InfluxDB server URL (e.g., "http://localhost:8086").
            token: Authentication token for InfluxDB.
            org: Organization name in InfluxDB.
            bucket: Bucket name for storing data.

        Raises:
            ConnectionError: If unable to connect to InfluxDB.
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket

        try:
            self.client = InfluxDBClient(
                url=url,
                token=token,
                org=org
            )
            # Test connection
            health = self.client.health()
            if health.status == "fail":
                raise ConnectionError(f"InfluxDB health check failed: {health.message}")

            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.query_api = self.client.query_api()

            # Test write to verify bucket exists and is writable
            from influxdb_client import Point
            from datetime import datetime
            test_point = Point("test").tag("source", "startup").field("value", 1).time(datetime.utcnow())
            try:
                self.write_api.write(bucket=bucket, org=org, record=test_point)
                logger.info(f"Connected to InfluxDB at {url}, bucket={bucket} is writable")
            except Exception as e:
                logger.warning(f"InfluxDB connection OK but bucket={bucket} test write failed: {e}")
                logger.warning("Data may not be stored properly!")
        except Exception as e:
            logger.error(f"Failed to connect to InfluxDB: {e}")
            raise ConnectionError(f"Failed to connect to InfluxDB: {e}") from e

    def _rssi_to_distance(self, rssi: int, rssi_ref: int = -59, n: float = 2.5) -> float:
        """Convert RSSI to approximate distance in meters."""
        return 10 ** ((rssi_ref - rssi) / (10 * n))

    def write_scan(
        self,
        mac: str,
        receiver_id: str,
        distance: float,
        medicine: str,
        temperature: Optional[float] = None,
        battery: Optional[int] = None,
        moving: bool = False,
        sequence_number: Optional[int] = None,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Store raw medicine scan data from a receiver.

        Args:
            mac: MAC address of the medicine beacon.
            receiver_id: ID of the receiver that detected the beacon.
            distance: Calculated distance in meters.
            medicine: Name/type of medicine.
            temperature: Optional temperature reading in Celsius.
            battery: Optional battery level percentage (0-100).
            moving: Whether the medicine is currently moving.
            sequence_number: Optional sequence number from beacon.
            timestamp: Optional timestamp (defaults to now).

        Returns:
            bool: True if write was successful, False otherwise.
        """
        try:
            point = (
                Point("medicine_status")
                .tag("mac", mac)
                .tag("receiver_id", receiver_id)
                .tag("medicine", medicine)
                .field("distance", distance)
                .field("moving", moving)
            )

            if temperature is not None:
                point = point.field("temperature", temperature)
            if battery is not None:
                point = point.field("battery", battery)
            if sequence_number is not None:
                point = point.field("sequence_number", sequence_number)

            if timestamp:
                point = point.time(timestamp, WritePrecision.NS)

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            self.write_api.flush()  # Force immediate write
            logger.info(f"✓ DB WRITE SUCCESS: {mac} distance={distance:.2f}m temp={temperature} batt={battery} to bucket={self.bucket} org={self.org}")
            return True
        except Exception as e:
            logger.error(f"✗ DB WRITE FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False

    def write_position(
        self,
        mac: str,
        x: float,
        y: float,
        accuracy: float,
        medicine: str,
        receiver_count: int,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Store calculated position for a medicine.

        Args:
            mac: MAC address of the medicine beacon.
            x: X coordinate in meters.
            y: Y coordinate in meters.
            accuracy: Position accuracy/error estimate in meters.
            medicine: Name/type of medicine.
            receiver_count: Number of receivers used for calculation.
            timestamp: Optional timestamp (defaults to now).

        Returns:
            bool: True if write was successful, False otherwise.
        """
        try:
            point = (
                Point("medicine_position")
                .tag("mac", mac)
                .tag("medicine", medicine)
                .field("x", x)
                .field("y", y)
                .field("accuracy", accuracy)
                .field("receiver_count", receiver_count)
            )

            if timestamp:
                point = point.time(timestamp, WritePrecision.NS)

            self.write_api.write(bucket=self.bucket, record=point)
            logger.info(f"Wrote position for {mac}: ({x:.2f}, {y:.2f})")
            return True
        except Exception as e:
            logger.error(f"Failed to write position: {e}")
            return False

    def write_alert(
        self,
        mac: str,
        alert_type: str,
        message: str,
        severity: str = "warning",
        medicine: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Store an alert for a medicine.

        Args:
            mac: MAC address of the medicine beacon.
            alert_type: Type of alert (e.g., "movement", "temperature", "battery").
            message: Human-readable alert message.
            severity: Alert severity ("info", "warning", "critical").
            medicine: Optional name/type of medicine.
            metadata: Optional additional data as key-value pairs.
            timestamp: Optional timestamp (defaults to now).

        Returns:
            bool: True if write was successful, False otherwise.
        """
        try:
            point = (
                Point("alerts")
                .tag("mac", mac)
                .tag("alert_type", alert_type)
                .tag("severity", severity)
                .field("message", message)
            )

            if medicine:
                point = point.tag("medicine", medicine)
            if metadata:
                for key, value in metadata.items():
                    # Convert metadata to string fields to handle various types
                    point = point.field(f"meta_{key}", str(value))

            if timestamp:
                point = point.time(timestamp, WritePrecision.NS)

            self.write_api.write(bucket=self.bucket, record=point)
            logger.warning(f"Wrote alert for {mac}: {alert_type} - {message}")
            return True
        except Exception as e:
            logger.error(f"Failed to write alert: {e}")
            return False

    def query_all_data(
        self,
        minutes: int = 60
    ) -> List[Dict[str, Any]]:
        """Get all raw data from InfluxDB.

        Args:
            minutes: How many minutes of data to retrieve.

        Returns:
            List of all records from medicine_status.
        """
        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -{minutes}m)
            |> filter(fn: (r) => r._measurement == "medicine_status")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append({
                        "time": record.get_time(),
                        "mac": record.values.get("mac"),
                        "medicine": record.values.get("medicine"),
                        "receiver_id": record.values.get("receiver_id"),
                        "distance": record.values.get("distance"),
                        "temperature": record.values.get("temperature"),
                        "battery": record.values.get("battery"),
                        "moving": record.values.get("moving"),
                        "sequence_number": record.values.get("sequence_number")
                    })

            logger.info(f"Retrieved {len(results)} records from last {minutes} minutes")
            return results
        except Exception as e:
            logger.error(f"Failed to query all data: {e}")
            return []

    def query_latest_status(
        self,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get the latest raw scan data for all medicines.

        Args:
            limit: Maximum number of results to return.

        Returns:
            List of status records with keys:
                mac, medicine, receiver_id, rssi, temperature, battery, moving, sequence_number, time.
        """
        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -1h)
            |> filter(fn: (r) => r._measurement == "medicine_status")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> group(columns: ["mac"])
            |> last()
            |> limit(n: {limit})
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append({
                        "mac": record.values.get("mac"),
                        "medicine": record.values.get("medicine"),
                        "receiver_id": record.values.get("receiver_id"),
                        "distance": record.values.get("distance"),
                        "temperature": record.values.get("temperature"),
                        "battery": record.values.get("battery"),
                        "moving": record.values.get("moving"),
                        "sequence_number": record.values.get("sequence_number"),
                        "time": record.get_time()
                    })

            logger.info(f"Retrieved {len(results)} latest medicine statuses")
            return results
        except Exception as e:
            logger.error(f"Failed to query latest status: {e}")
            return []

    def query_latest_positions(
        self,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get the latest calculated positions for all medicines.

        Args:
            limit: Maximum number of results to return.

        Returns:
            List[Dict[str, Any]]: List of position records with keys:
                mac, medicine, x, y, z, accuracy, receiver_count, time.
        """
        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -1h)
            |> filter(fn: (r) => r._measurement == "medicine_position")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> group(columns: ["mac"])
            |> last()
            |> limit(n: {limit})
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append({
                        "mac": record.values.get("mac"),
                        "medicine": record.values.get("medicine"),
                        "x": record.values.get("x"),
                        "y": record.values.get("y"),
                        "accuracy": record.values.get("accuracy"),
                        "receiver_count": record.values.get("receiver_count"),
                        "time": record.get_time()
                    })

            logger.debug(f"Retrieved {len(results)} latest positions")
            return results
        except Exception as e:
            logger.error(f"Failed to query latest positions: {e}")
            return []

    def query_medicine_history(
        self,
        mac: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get position and status history for a specific medicine.

        Args:
            mac: MAC address of the medicine beacon.
            hours: Number of hours of history to retrieve.

        Returns:
            List[Dict[str, Any]]: List of historical records.
        """
        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -{hours}h)
            |> filter(fn: (r) => r._measurement == "medicine_position" or r._measurement == "medicine_status")
            |> filter(fn: (r) => r.mac == "{mac}")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    data = {
                        "measurement": record.values.get("_measurement"),
                        "time": record.get_time(),
                        "mac": mac
                    }
                    # Add all available fields
                    for key, value in record.values.items():
                        if not key.startswith("_") and key not in ["mac", "result", "table"]:
                            data[key] = value
                    results.append(data)

            # Sort by time
            results.sort(key=lambda x: x["time"])
            logger.debug(f"Retrieved {len(results)} history records for {mac}")
            return results
        except Exception as e:
            logger.error(f"Failed to query medicine history: {e}")
            return []

    def query_alerts(
        self,
        hours: int = 24,
        severity: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query alerts from the database.

        Args:
            hours: Number of hours of alerts to retrieve.
            severity: Optional filter by severity level.
            limit: Maximum number of results.

        Returns:
            List[Dict[str, Any]]: List of alert records.
        """
        severity_filter = f'|> filter(fn: (r) => r.severity == "{severity}")' if severity else ""

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -{hours}h)
            |> filter(fn: (r) => r._measurement == "alerts")
            {severity_filter}
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: {limit})
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append({
                        "mac": record.values.get("mac"),
                        "alert_type": record.values.get("alert_type"),
                        "severity": record.values.get("severity"),
                        "message": record.values.get("message"),
                        "medicine": record.values.get("medicine"),
                        "time": record.get_time()
                    })

            logger.debug(f"Retrieved {len(results)} alerts")
            return results
        except Exception as e:
            logger.error(f"Failed to query alerts: {e}")
            return []

    def close(self) -> None:
        """Close the InfluxDB client connection."""
        try:
            self.client.close()
            logger.info("InfluxDB connection closed")
        except Exception as e:
            logger.error(f"Error closing InfluxDB connection: {e}")

    def __enter__(self) -> "Database":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
