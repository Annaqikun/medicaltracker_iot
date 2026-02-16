#include "ble.h"
#include "mac.h"
#include "med.h"

#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <math.h>

static BLEAdvertising* adv = nullptr;

static float advertisedTemperature = 25.00f;

void setAdvertisedTemperature(float gotTemperature) {
  advertisedTemperature = gotTemperature;
}

/*
Manufacturer Data Layout:
Byte 0-1  : Company ID (0xFFFF, little-endian)
Byte 2-7  : Device MAC address (6 bytes, raw)
Byte 8-19 : Medicine name (12 bytes, ASCII, space padded, truncated if >12)
Byte 20-21 : Temperature (2 bytes, signed int16, 0.01°C, big-endian hi,lo)
*/
static std::string buildMfgData(const String& med, float temp) {
  std::string s;
  s.reserve(22);

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

  return s;
}

void updateAdvertising() {
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(getMedicineName(), advertisedTemperature));

  adv->stop();
  adv->setAdvertisementData(ad);
  adv->setScanResponseData(sd);
  adv->start();
}

void initBLE() {
  BLEDevice::init("MED_TAG");
  adv = BLEDevice::getAdvertising();

  // Advertising interval = 1600 * 0.625ms = 1000ms (1 second)
  adv->setMinInterval(1600);
  adv->setMaxInterval(1600);

  updateAdvertising();
}