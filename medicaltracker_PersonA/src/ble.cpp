#include "ble.h"
#include "mac.h"
#include "med.h"

#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <math.h>

static BLEAdvertising* adv = nullptr;

static float advertisedTemperature = 25.00f;
static uint8_t advertisedBatteryPercent = 0;

static bool advertisedMoving = false;
static bool advertisedStationary = true;

void setAdvertisedTemperature(float temperature) {
  advertisedTemperature = temperature;
}

void setAdvertisedBatteryPercent(uint8_t percent) {
  if (percent > 100) percent = 100;
  advertisedBatteryPercent = percent;
}

void setAdvertisedMoving(bool moving) {
  advertisedMoving = moving;
}

void setAdvertisedStationary(bool stationary) {
  advertisedStationary = stationary;
}

/*
Manufacturer Data Layout:
Byte 0-1   : Company ID (0xFFFF, little-endian)
Byte 2-7   : Device MAC address (6 bytes, raw)
Byte 8-19  : Medicine name (12 bytes, ASCII, space padded, truncated if >12)
Byte 20-21 : Temperature (2 bytes, signed int16, 0.01°C, big-endian hi,lo)
Byte 22    : Battery (1 byte)
Byte 23    : Movement flags (1 byte, bit 0 only, where 1 = moving and 0 = not moving)
*/
static std::string buildMfgData(const String& med, float temp, uint8_t battPct, bool moving) {
  std::string s;
  s.reserve(24);

  s.push_back((char)0xFF);
  s.push_back((char)0xFF);

  uint8_t mac[6];
  getMacBytes(mac);
  for (int i = 0; i < 6; i++) s.push_back((char)mac[i]);

  String m = med;
  if (m.length() > 12) m = m.substring(0, 12);
  while (m.length() < 12) m += ' ';
  s.append(m.c_str(), 12);

  int16_t t100 = (int16_t)lroundf(temp * 100.0f);
  uint8_t hi = (uint8_t)((t100 >> 8) & 0xFF);
  uint8_t lo = (uint8_t)(t100 & 0xFF);
  s.push_back((char)hi);
  s.push_back((char)lo);

  if (battPct > 100) battPct = 100;
  s.push_back((char)battPct);

  uint8_t flags = 0;
  if (moving) flags |= 0x01; // bit0 = moving
  s.push_back((char)flags);

  return s;
}

static void applyAdaptiveInterval() {
  // BLE interval units are 0.625ms
  // 500ms  -> 800 units
  // 5000ms -> 8000 units
  uint16_t interval = advertisedStationary ? 8000 : 800;

  adv->setMinInterval(interval);
  adv->setMaxInterval(interval);
}

void updateAdvertising() {
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(getMedicineName(), 
                                      advertisedTemperature, 
                                      advertisedBatteryPercent,
                                      advertisedMoving));

  adv->stop();

  // adaptive interval before restart
  applyAdaptiveInterval();

  adv->setAdvertisementData(ad);
  adv->setScanResponseData(sd);
  adv->start();
}

void initBLE() {
  BLEDevice::init("MED_TAG");
  adv = BLEDevice::getAdvertising();

  // Set initial interval based on current motion state
  applyAdaptiveInterval();

  updateAdvertising();
}