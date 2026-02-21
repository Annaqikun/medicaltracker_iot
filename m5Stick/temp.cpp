#include "temp.h"

#include <DHT.h>
#include <math.h>

// ===== DHT22 wiring =====
// DAT -> G26
// VCC -> 3V3
// GND -> GND
#define DHTPIN 26
#define DHTTYPE DHT22

static DHT dht(DHTPIN, DHTTYPE);

// Read every 30 seconds
static const uint32_t READ_PERIOD_MS = 30000;
static uint32_t lastReadMs = 0;

static float latestTemperature = 25.00f; // default at boot

void initTemp() {
  dht.begin();

  // initial read
  float t = dht.readTemperature();
  if (!isnan(t)) latestTemperature = t;

  lastReadMs = millis();
}

bool tempTask() {
  uint32_t now = millis();
  if (now - lastReadMs < READ_PERIOD_MS) return false;
  lastReadMs = now;

  float t = dht.readTemperature();
  if (isnan(t)) return false;

  // print readings to Serial Monitor
  int16_t t100 = (int16_t)lroundf(t * 100.0f);
  Serial.printf("[%lu] Temp(C): %.2f  Packed: %d (0x%02X%02X)\n",
                now, t, t100,
                (uint8_t)((t100 >> 8) & 0xFF),
                (uint8_t)(t100 & 0xFF));

  // Only trigger BLE update if changed
  if (fabs(t - latestTemperature) > 0.01f) {
    latestTemperature = t;
    return true;
  }
  return false;
}

float getTemperature() {
  return latestTemperature;
}