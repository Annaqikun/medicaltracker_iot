#pragma once

#include <Arduino.h>

// Initialize motion detection + initial state (uses the built-in MPU6886 on M5StickC Plus)
void initMovement();

// Call frequently; internally rate-limited.
// Returns true when moving/stationary state changes.
bool movementTask();

// True if we detected "movement" recently (|a| > threshold).
bool isMoving();

// True if we detected no movement for the stationary timeout.
bool isStationary();

// Latest acceleration magnitude in g (for debugging/UI)
float getAccelMagnitude();
