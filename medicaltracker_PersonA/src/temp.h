#pragma once

#include <Arduino.h>

// init DHT22 + do an initial read
void initTemp();

// call frequently; it will only read every READ_PERIOD_MS internally
bool tempTask();

// latest temperature (°C)
float getTemperature();
