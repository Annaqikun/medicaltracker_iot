#include "movement.h"

#include <M5Unified.h>
#include <math.h>

// Tunables
static const uint32_t MOVE_READ_PERIOD_MS = 100;      // Check IMU every 100ms
static const float    MOVE_THRESHOLD      = 1.20f;    // |a| > 1.20G = movement detected (was 1.05)
static const uint32_t STATIONARY_TIMEOUT  = 10000;    // 10s grace period before "stationary"

// State
static uint32_t lastReadMs = 0;
static uint32_t lastMoveMs = 0;

static bool isMoving = true;          // Start as MOVING until proven otherwise
static float latestMagnitude = 1.0f;  // Latest |a| in g

static float readAccelMagnitude() {
  float ax, ay, az;
  M5.Imu.getAccelData(&ax, &ay, &az);
  return sqrtf(ax * ax + ay * ay + az * az);
}

void initMovement() {
  M5.Imu.begin();
  
  latestMagnitude = readAccelMagnitude();
  
  uint32_t now = millis();
  lastReadMs = now;
  lastMoveMs = now;  // Assume we "moved" at boot so we start in MOVING state
  
  isMoving = true;
}

bool movementTask() {
  uint32_t now = millis();
  if (now - lastReadMs < MOVE_READ_PERIOD_MS) return false;
  lastReadMs = now;
  
  latestMagnitude = readAccelMagnitude();
  
  // If we detect motion, update the timestamp
  if (latestMagnitude > MOVE_THRESHOLD) {
    lastMoveMs = now;
  }
  
  // Simple 2-state logic:
  // If moved within last 10s → MOVING, else → STATIONARY
  bool wasMoving = isMoving;
  uint32_t timeSinceMove = now - lastMoveMs;
  isMoving = (timeSinceMove < STATIONARY_TIMEOUT);
  
  // Return true only when state changes (so UI/BLE can update efficiently)
  return (isMoving != wasMoving);
}

bool isCurrentlyMoving() {
  return isMoving;
}

bool isCurrentlyStationary() {
  return !isMoving;
}

float getAccelMagnitude() {
  return latestMagnitude;
}
