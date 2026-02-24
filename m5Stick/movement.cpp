#include "movement.h"

#include <M5Unified.h>
#include <math.h>

// Tunables
static const uint32_t MOVE_READ_PERIOD_MS = 100;   // how often to read accel
static const float    MOVE_THRESHOLD      = 1.05f;  // |a| > 1.05G => moving
static const uint32_t STATIONARY_MS       = 30000; // 30s no movement => stationary
static const uint32_t MOVING_HOLD_MS      = 2000;  // keep MOVING for 2s after last spike

// State
static uint32_t lastReadMs = 0;
static uint32_t lastMoveMs = 0;

static bool moving = false;
static bool stationary = true;

static float latestMagnitude = 1.0f;  // latest |a| in g

static float readAccelMagnitude() {
  float ax, ay, az;
  M5.Imu.getAccelData(&ax, &ay, &az);
  return sqrtf(ax * ax + ay * ay + az * az);
}

void initMovement() {
  // Ensure IMU is ready on M5StickC Plus (MPU6886)
  M5.Imu.begin();

  latestMagnitude = readAccelMagnitude();

  uint32_t now = millis();
  lastReadMs = now;
  lastMoveMs = now;

  // start IDLE at boot
  moving = false;        
  stationary = false;
}

bool movementTask() {
  uint32_t now = millis();
  if (now - lastReadMs < MOVE_READ_PERIOD_MS) return false;
  lastReadMs = now;

  latestMagnitude = readAccelMagnitude();

  bool prevMoving = moving;
  bool prevStationary = stationary;

  // Update lastMoveMs if we detected movement this cycle
  if (latestMagnitude > MOVE_THRESHOLD) {
    lastMoveMs = now;
  }

  uint32_t sinceMove = now - lastMoveMs;

  // Derive states from elapsed time since last movement
  moving = (sinceMove < MOVING_HOLD_MS);
  stationary = (sinceMove >= STATIONARY_MS);

  // Return true only when state changes (so UI/BLE can update efficiently)
  return (moving != prevMoving) || (stationary != prevStationary);
}

bool isMoving() {
  return moving;
}

bool isStationary() {
  return stationary;
}

float getAccelMagnitude() {
  return latestMagnitude;
}