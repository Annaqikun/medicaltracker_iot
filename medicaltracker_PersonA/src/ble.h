#pragma once

#include <Arduino.h>

// Initialize BLE and start advertising
void initBLE();

// Update advertising data with latest info
void updateAdvertising();

// Provide latest temperature value to BLE advertising payload
void setAdvertisedTemperature(float gotTemperature);

// Provide latest battery % to BLE advertising payload
void setAdvertisedBatteryPercent(uint8_t percent);

// movement-related (used for status flags + adaptive interval)
void setAdvertisedMoving(bool moving);
void setAdvertisedStationary(bool stationary);