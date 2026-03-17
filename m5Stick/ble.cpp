#include "ble.h"
#include "mac.h"
#include "hmac.h"

#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <math.h>

static BLEAdvertising* adv = nullptr;

static uint16_t advSeq = 0;

static float advertisedTemperature = 25.00f;
static uint8_t advertisedBatteryPercent = 0;

static bool advertisedMoving = false;
static bool advertisedStationary = true;

/*
Manufacturer Data Layout (18 bytes total):
Byte 0-1   : Company ID (0xFFFF, little-endian)
Byte 2-7   : Device MAC address (6 bytes, raw)
Byte 8-9   : Temperature (2 bytes, signed int16, 0.01°C, big-endian hi,lo)
Byte 10    : Battery (1 byte)
Byte 11    : Movement flags (1 byte, bit 0 only, where 1 = moving and 0 = not moving)
Byte 12-13 : Sequence number (2 bytes, big-endian)
Byte 14-17 : Truncated HMAC-SHA256 (4 bytes, computed over bytes 2-13)
*/
static std::string buildMfgData(float temp, uint8_t battPct, bool moving) {
  std::string s;
  s.reserve(18);

  // Bytes 0-1: Company ID
  s.push_back((char)0xFF);
  s.push_back((char)0xFF);

  // Bytes 2-7: MAC address
  uint8_t mac[6];
  getMacBytes(mac);
  for (int i = 0; i < 6; i++) s.push_back((char)mac[i]);

  // Bytes 8-9: Temperature (big-endian signed int16, units of 0.01°C)
  int16_t t100 = (int16_t)lroundf(temp * 100.0f);
  uint8_t hi = (uint8_t)((t100 >> 8) & 0xFF);
  uint8_t lo = (uint8_t)(t100 & 0xFF);
  s.push_back((char)hi);
  s.push_back((char)lo);

  // Byte 10: Battery percent
  if (battPct > 100) battPct = 100;
  s.push_back((char)battPct);

  // Byte 11: Movement flags (bit 0 = moving)
  uint8_t flags = 0;
  if (moving) flags |= 0x01;
  s.push_back((char)flags);

  // Bytes 12-13: Sequence number (big-endian)
  uint16_t seq = advSeq++;
  s.push_back((char)((seq >> 8) & 0xFF));
  s.push_back((char)(seq & 0xFF));

  // Bytes 14-17: Truncated HMAC-SHA256 (over bytes 2-13)
  uint8_t hmacOut[4];
  computeHmac((const uint8_t*)s.data() + 2, 12, hmacOut);
  for (int i = 0; i < 4; i++) s.push_back((char)hmacOut[i]);

  return s;
}

static void applyAdaptiveInterval() {
  // BLE interval units are 0.625ms
  // Tune these based on your needs:
  // - Faster = better tracking but drains battery
  // - Slower = saves battery but less responsive

  uint16_t interval;
  if (advertisedStationary) {
    interval = 8000;  // 5000ms (5 seconds) - save battery when still
  } else {
    // MOVING - choose your speed:
    interval = 1600;  // 1000ms (1 second) - balanced
    // interval = 800;   // 500ms (0.5 seconds) - real-time but drains fast
    // interval = 3200;  // 2000ms (2 seconds) - battery saver
  }

  adv->setMinInterval(interval);
  adv->setMaxInterval(interval);
}


void updateAdvertising() {
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(advertisedTemperature,
                                      advertisedBatteryPercent,
                                      advertisedMoving));

  adv->stop();

  // adaptive interval before restart
  applyAdaptiveInterval();

  adv->setAdvertisementData(ad);
  adv->setScanResponseData(sd);
  adv->start();

  Serial.printf("[%lu] ADV updated, Seq=%u\n", millis(), getLastSentSeq());
}

void initBLE() {
  BLEDevice::init("MED_TAG");
  adv = BLEDevice::getAdvertising();

  // Set initial interval based on current motion state
  applyAdaptiveInterval();

  updateAdvertising();
}

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

uint16_t getLastSentSeq() {
  if (advSeq == 0) return 0;
  return advSeq - 1;
}
