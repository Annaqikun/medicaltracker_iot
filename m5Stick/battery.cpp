#include "battery.h"

#include <M5Unified.h>
#include <math.h>

// read every 10 seconds
static const uint32_t BAT_READ_PERIOD_MS = 10000;

static const float BAT_V_MIN = 3.0f;
static const float BAT_V_MAX = 4.2f;

// state
static uint32_t lastReadMs = 0;
static float    latestBatteryVoltage = 0.0f;
static uint8_t  latestBatteryPercent = 0;

// cap the voltage range
static float voltageLimits(float x, float lo, float hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

// linearly map voltage to percent conversion
static uint8_t voltageToPercent(float v) {
  float adjustedVoltage = voltageLimits(v, BAT_V_MIN, BAT_V_MAX);
  float calcPercent = (adjustedVoltage - BAT_V_MIN) * 100.0f / (BAT_V_MAX - BAT_V_MIN);
  int p = (int)lroundf(calcPercent);
  if (p < 0) p = 0;
  if (p > 100) p = 100;
  return (uint8_t)p;
}

static float readBatteryVoltageNow() {
  float v = M5.Power.getBatteryVoltage();

  // Different M5Unified builds return either mV or V depending on backend
  // If it's "too big", assume it's millivolts and normalize to volts
  if (v > 10.0f) v = v / 1000.0f;
  return v;
}

void initBattery() {
  // Initial read
  latestBatteryVoltage = readBatteryVoltageNow();
  latestBatteryPercent = voltageToPercent(latestBatteryVoltage);
  lastReadMs = millis();
}

bool batteryTask() {
  uint32_t now = millis();
  if (now - lastReadMs < BAT_READ_PERIOD_MS) return false;
  lastReadMs = now;

  float v = readBatteryVoltageNow();
  uint8_t p = voltageToPercent(v);

  // Log to Serial for debugging
  Serial.printf("[%lu] Bat(V): %.3f  Bat(%%): %u\n", now, v, p);

  // Update state; trigger if % changed
  if (p != latestBatteryPercent) {
    latestBatteryVoltage = v;
    latestBatteryPercent = p;
    return true;
  }

  // Still keep voltage updated even if % didn’t change
  latestBatteryVoltage = v;
  return false;
}

float getBatteryVoltage() {
  return latestBatteryVoltage;
}

uint8_t getBatteryPercent() {
  return latestBatteryPercent;
}