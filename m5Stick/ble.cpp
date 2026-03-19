#include "ble.h"
#include "mac.h"
#include "med.h"
#include "ble_ack.h"

#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <math.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <M5Unified.h>

extern bool findMeActive;
extern void drawM5Screen();

static BLEAdvertising* adv = nullptr;
static BLEServer* ackServer = nullptr;
static BLEService* ackService = nullptr;
static BLECharacteristic* ackCharacteristic = nullptr;
static BLECharacteristic* commandCharacteristic = nullptr;

static const char* ACK_SERVICE_UUID = "12345678-1234-1234-1234-1234567890ab";
static const char* ACK_CHARACTERISTIC_UUID = "abcdefab-1234-1234-1234-abcdefabcdef";
const char* COMMAND_CHARACTERISTIC_UUID = "abcdefab-1234-1234-1234-abcdefabcdf0";

static uint16_t advSeq = 0;

static float advertisedTemperature = 25.00f;
static uint8_t advertisedBatteryPercent = 0;

static bool advertisedMoving = false;
static bool advertisedStationary = true;
static bool advertisedLowBattery = false;

/*
Manufacturer Data Layout:
Byte 0-1   : Company ID (0xFFFF, little-endian)
Byte 2-7   : Device MAC address (6 bytes, raw)
Byte 8-19  : Medicine name (12 bytes, ASCII, space padded, truncated if >12)
Byte 20-21 : Temperature (2 bytes, signed int16, 0.01°C, big-endian hi,lo)
Byte 22    : Battery (1 byte)
Byte 23    : Movement flags (1 byte, bit 0 = moving, bit 1 = low battery)
Byte 24-25 : Sequence number (2 bytes, big-endian)
*/
static std::string buildMfgData(const String& med, float temp, uint8_t battPct, bool moving, bool lowBattery) {
  std::string s;
  s.reserve(26);

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
  if (moving) flags |= 0x01;   // bit0 = moving
  if (lowBattery) flags |= 0x02; // bit1 = low battery
  s.push_back((char)flags);

  uint16_t seq = advSeq++;
  s.push_back((char)((seq >> 8) & 0xFF));
  s.push_back((char)(seq & 0xFF));

  return s;
}

class AckCharacteristicCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    std::string value = characteristic->getValue();

    Serial.println("[BLE ACK] GATT write received");

    if (value.empty()) {
      Serial.println("[BLE ACK] Empty payload ignored");
      return;
    }

    Serial.print("[BLE ACK] Raw bytes: ");
    for (size_t i = 0; i < value.size(); i++) {
      Serial.printf("%02X ", (uint8_t)value[i]);
    }
    Serial.println();

    Serial.printf("[BLE ACK] Payload as text: %s\n", value.c_str());

    if (value == "ack") {
      recordBleAck();
    } else {
      Serial.println("[BLE ACK] Invalid payload ignored");
    }
  }
};

void triggerFindMe() {
  findMeActive = true;
  drawM5Screen();

  M5.Speaker.setVolume(255);

  // {frequency, duration, gap after}
  const int melody[][3] = {
    {1319, 400, 8},   // E
    {1319, 400, 8},   // E
    {1760, 350, 20},  // A
    {1976, 350, 8},   // B
    {2093, 750, 10},  // C

    {2093, 700, 8},   // C
    {2093, 1400, 10}, // C

    {1976, 350, 8},   // B
    {1760, 350, 8},   // A
    {1397, 1050, 10}, // F

    {1397, 700, 8}    // F
  };
  const int noteCount = sizeof(melody) / sizeof(melody[0]);

  // Play it twice
  for (int round = 0; round < 2; round++) {
    for (int i = 0; i < noteCount; i++) {
      M5.Speaker.tone(melody[i][0], melody[i][1]);
      delay(melody[i][1] + melody[i][2]);
    }
    delay(300);
  }
  M5.Speaker.stop();

  findMeActive = false;
  drawM5Screen();
}

class CommandCharacteristicCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    std::string value = characteristic->getValue();

    Serial.println("[BLE CMD] GATT write received");

    if (value.empty()) {
      Serial.println("[BLE CMD] Empty payload ignored");
      return;
    }

    Serial.printf("[BLE CMD] Payload: %s\n", value.c_str());

    if (value == "find") {
      Serial.println("[BLE CMD] Find command received — triggering Find Me");
      triggerFindMe();
    } else {
      Serial.printf("[BLE CMD] Unknown command ignored: %s\n", value.c_str());
    }
  }
};

static void applyAdaptiveInterval() {
  // BLE interval units are 0.625ms
  // Faster = better GATT ACK reliability but more battery drain
  // 320 = 200ms — good balance for ACK + tracking
  uint16_t interval;
  if (advertisedStationary) {
    interval = 320;   // 200ms - reliable for GATT ACK connections
  } else {
    interval = 160;   // 100ms - fast tracking when moving
  }

  adv->setMinInterval(interval);
  adv->setMaxInterval(interval);
}

class AckServerCallbacks: public BLEServerCallbacks{
  void onDisconnect(BLEServer* server) override{
    Serial.println("[BLE ACK] Client disconnected, restarting advertising");
    BLEDevice::getAdvertising()->start();
  }
};


static void setupAckGattServer() {
  ackServer = BLEDevice::createServer();
  ackServer ->setCallbacks(new AckServerCallbacks());

  ackService = ackServer->createService(ACK_SERVICE_UUID);

  ackCharacteristic = ackService->createCharacteristic(
      ACK_CHARACTERISTIC_UUID,
      BLECharacteristic::PROPERTY_WRITE
  );

  ackCharacteristic->setCallbacks(new AckCharacteristicCallbacks());
  ackCharacteristic->setValue("waiting");

  commandCharacteristic = ackService->createCharacteristic(
      COMMAND_CHARACTERISTIC_UUID,
      BLECharacteristic::PROPERTY_WRITE
  );

  commandCharacteristic->setCallbacks(new CommandCharacteristicCallbacks());
  commandCharacteristic->setValue("idle");

  ackService->start();

  Serial.println("[BLE ACK] GATT service started");
  Serial.printf("[BLE ACK] Service UUID: %s\n", ACK_SERVICE_UUID);
  Serial.printf("[BLE ACK] Characteristic UUID: %s\n", ACK_CHARACTERISTIC_UUID);
  Serial.printf("[BLE CMD] Command Characteristic UUID: %s\n", COMMAND_CHARACTERISTIC_UUID);
}

void updateAdvertising() {
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(getMedicineName(), 
                                      advertisedTemperature, 
                                      advertisedBatteryPercent, 
                                      advertisedMoving,
                                      advertisedLowBattery));

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

  setupAckGattServer();

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

void setAdvertisedLowBattery(bool lowBattery) {
  advertisedLowBattery = lowBattery;
}