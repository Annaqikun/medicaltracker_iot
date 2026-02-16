#pragma once

#include <Arduino.h>

// Initialize BLE and start advertising
void initBLE();

// Update advertising data with latest info
void updateAdvertising();

// Provide latest temperature value to BLE advertising payload
void setAdvertisedTemperature(float gotTemperature);