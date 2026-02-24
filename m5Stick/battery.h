#pragma once

#include <Arduino.h>
#include <stdint.h>

// init battery reading via M5 power chip + do an initial read
void initBattery();

// call frequently; will only read every BAT_READ_PERIOD_MS internally
// returns true if battery % changed
bool batteryTask();

// latest battery voltage(v)
float getBatteryVoltage();

// latest battery %
uint8_t getBatteryPercent();