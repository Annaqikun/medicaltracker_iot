#pragma once

#include <Arduino.h>

// Initialize motion detection (uses built-in MPU6886 IMU on M5StickC Plus)
void initMovement();

// Call frequently in loop; internally rate-limited to every 100ms
// Returns true only when moving/stationary state CHANGES (for UI/BLE updates)
bool movementTask();

// True if movement detected within grace period (10s)
bool isCurrentlyMoving();

// True if no movement for grace period (10s)
bool isCurrentlyStationary();

// Latest acceleration magnitude in g (for debugging/display)
float getAccelMagnitude();