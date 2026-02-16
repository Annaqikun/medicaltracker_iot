#include "ble.h"

#include <M5Unified.h>
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <esp_bt_device.h>

static BLEAdvertising* adv = nullptr;

String medicineName = "PANADOL";

String getMacString() {
  const uint8_t* mac = esp_bt_dev_get_address();
  char buf[18];
  sprintf(buf, "%02X:%02X:%02X:%02X:%02X:%02X",
          mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(buf);
}

/*
Manufacturer Data Layout:

Byte 0-1  : Company ID (0xFFFF, little-endian)
Byte 2-7  : Device MAC address (6 bytes, raw)
Byte 8-19 : Medicine name (12 bytes, ASCII, space padded)

Total length: 20 bytes
*/
std::string buildMfgData(const String& med) {
  std::string s;
  s.reserve(20);

  s.push_back((char)0xFF);
  s.push_back((char)0xFF);

  const uint8_t* mac = esp_bt_dev_get_address();
  for (int i = 0; i < 6; i++) s.push_back((char)mac[i]);

  String m = med;
  if (m.length() > 12) m = m.substring(0, 12);
  while (m.length() < 12) m += ' ';

  s.append(m.c_str(), 12);

  return s;
}

void updateAdvertising() {
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(medicineName));

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
