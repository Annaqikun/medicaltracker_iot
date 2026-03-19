#pragma once

#include <Arduino.h>
#include <stdint.h>

// Raw MAC bytes (6 bytes)
void getMacBytes(uint8_t out[6]);

// MAC string like "4C:75:25:CB:80:A2"
String getMacString();
