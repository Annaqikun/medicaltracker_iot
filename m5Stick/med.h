#pragma once

#include <Arduino.h>

// Get current medicine name (String, may be >12 chars)
// BLE module will truncate/pad when packing
const String& getMedicineName();

void setMedicineName(const String& name);

// toggle behaviour
void toggleMedicine();