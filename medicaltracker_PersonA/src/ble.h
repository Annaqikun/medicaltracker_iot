#pragma once

#include <Arduino.h>
#include <string>

extern String medicineName;

void initBLE();
void updateAdvertising();
String getMacString();


