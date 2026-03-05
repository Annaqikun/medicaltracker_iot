"""Trilateration module for calculating medicine positions from RSSI values.

This module provides functions to convert RSSI to distance and calculate
positions using weighted centroid trilateration.
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def rssi_to_distance(
    rssi: int,
    rssi_reference: int = -59,
    path_loss_exponent: float = 2.5
) -> float:
    """Convert RSSI value to estimated distance using path loss model.

    Uses the log-distance path loss model:
    d = 10^((RSSI_ref - RSSI) / (10 * n))

    where:
    - d is the distance in meters
    - RSSI_ref is the reference RSSI at 1 meter
    - RSSI is the measured RSSI
    - n is the path loss exponent

    Args:
        rssi: Measured RSSI value in dBm (negative value)
        rssi_reference: RSSI value at 1 meter distance (default: -59 dBm)
        path_loss_exponent: Path loss exponent based on environment
            (2.0 for free space, 2.5-3.0 for indoor, 3.0-4.0 for obstacles)

    Returns:
        float: Estimated distance in meters. Returns a large value if RSSI
            is too weak to be reliable.

    Raises:
        ValueError: If path_loss_exponent is zero or negative.
    """
    if path_loss_exponent <= 0:
        raise ValueError("Path loss exponent must be positive")

    # Handle edge cases for very weak signals
    if rssi < -90:
        logger.warning(f"Very weak RSSI: {rssi} dBm, distance may be unreliable")
        return 50.0  # Cap at 50 meters for very weak signals

    if rssi > 0:
        logger.warning(f"Unexpected positive RSSI: {rssi} dBm, treating as 0")
        rssi = 0

    # Calculate distance using path loss model
    distance = math.pow(10.0, (rssi_reference - rssi) / (10.0 * path_loss_exponent))

    # Sanity check: cap maximum distance
    max_distance = 100.0
    if distance > max_distance:
        logger.debug(f"Capped distance from {distance:.2f}m to {max_distance}m")
        return max_distance

    logger.debug(f"RSSI {rssi} dBm -> Distance {distance:.2f}m")
    return distance


def trilaterate_weighted(
    receivers: Dict[str, Tuple[float, float, float]],
    distances: Dict[str, float],
    min_receivers: int = 2
) -> Optional[Tuple[float, float, float]]:
    """Calculate position using weighted centroid trilateration.

    Uses a weighted average of receiver positions where weights are
    inversely proportional to the estimated distance. Closer receivers
    have higher influence on the calculated position.

    Args:
        receivers: Dictionary mapping receiver_id to (x, y, z) coordinates in meters.
        distances: Dictionary mapping receiver_id to estimated distance in meters.
        min_receivers: Minimum number of receivers required for calculation (default: 2).

    Returns:
        Optional[Tuple[float, float, float]]: Calculated (x, y, z) position in meters,
            or None if insufficient receivers or calculation fails.

    Raises:
        ValueError: If receivers and distances have no common keys.
    """
    # Find common receivers between positions and distances
    common_receivers = set(receivers.keys()) & set(distances.keys())

    if len(common_receivers) < min_receivers:
        logger.debug(
            f"Insufficient receivers for trilateration: {len(common_receivers)} "
            f"(need {min_receivers})"
        )
        return None

    # Filter to common receivers
    valid_receivers = []
    valid_distances = []

    for receiver_id in common_receivers:
        if distances[receiver_id] > 0:
            valid_receivers.append(receivers[receiver_id])
            valid_distances.append(distances[receiver_id])

    if len(valid_receivers) < min_receivers:
        logger.debug("Not enough valid distances for trilateration")
        return None

    # Calculate weights (inverse of distance, with small epsilon to avoid division by zero)
    epsilon = 0.1  # Minimum distance to avoid infinite weights
    weights = []

    for distance in valid_distances:
        # Weight is inverse of distance squared for better accuracy
        weight = 1.0 / max(distance ** 2, epsilon ** 2)
        weights.append(weight)

    # Normalize weights
    total_weight = sum(weights)
    if total_weight == 0:
        logger.warning("Total weight is zero in trilateration")
        return None

    normalized_weights = [w / total_weight for w in weights]

    # Calculate weighted centroid
    x_sum = 0.0
    y_sum = 0.0
    z_sum = 0.0

    for i, (rx, ry, rz) in enumerate(valid_receivers):
        weight = normalized_weights[i]
        x_sum += rx * weight
        y_sum += ry * weight
        z_sum += rz * weight

    calculated_position = (x_sum, y_sum, z_sum)

    logger.info(
        f"Trilateration calculated position: ({x_sum:.2f}, {y_sum:.2f}, {z_sum:.2f}) "
        f"using {len(valid_receivers)} receivers"
    )

    return calculated_position


def calculate_position_error(
    calculated_position: Tuple[float, float, float],
    receivers: Dict[str, Tuple[float, float, float]],
    distances: Dict[str, float]
) -> float:
    """Calculate the root mean square error of the position estimate.

    Args:
        calculated_position: The calculated (x, y, z) position.
        receivers: Dictionary of receiver positions.
        distances: Dictionary of measured distances.

    Returns:
        float: RMSE in meters. Lower values indicate better fit.
    """
    cx, cy, cz = calculated_position
    squared_errors = []

    common_receivers = set(receivers.keys()) & set(distances.keys())

    for receiver_id in common_receivers:
        rx, ry, rz = receivers[receiver_id]
        measured_distance = distances[receiver_id]

        # Calculate expected distance to calculated position
        expected_distance = math.sqrt(
            (cx - rx) ** 2 + (cy - ry) ** 2 + (cz - rz) ** 2
        )

        # Calculate squared error
        error = measured_distance - expected_distance
        squared_errors.append(error ** 2)

    if not squared_errors:
        return float('inf')

    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))
    return rmse


def get_receiver_positions() -> Dict[str, Tuple[float, float, float]]:
    """Get default receiver positions for the medical tracker system.

    Returns:
        Dict[str, Tuple[float, float, float]]: Dictionary mapping receiver IDs
            to their (x, y, z) coordinates in meters.
    """
    return {
        "receiver_1": (0.0, 0.0, 2.0),
        "receiver_2": (10.0, 0.0, 2.0),
        "receiver_3": (5.0, 8.66, 2.0),
        "receiver_4": (5.0, 2.89, 2.0),
    }
