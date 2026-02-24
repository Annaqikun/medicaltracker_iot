#include <M5StickCPlus2.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>
#include <esp_bt_device.h>

static uint16_t sequenceNumber = 0;
static String medicineName = "PANADOL";
static BLEAdvertising* pAdvertising = nullptr;

/*
Manufacturer Data Layout (matches Person A's ble.cpp format):
  Byte 0-1   : Company ID (0xFFFF, little-endian)
  Byte 2-7   : Device MAC address (6 bytes)
  Byte 8-19  : Medicine name (12 bytes, ASCII, space padded)
  Byte 20-21 : Temperature (signed int16, big-endian, 0.01 C)
  Byte 22    : Battery (0-100%)
  Byte 23    : Movement flags (bit 0 = moving, always 0 - no IMU motion detection)
  Byte 24-25 : Sequence number (uint16, big-endian)
*/
static std::string buildMfgData(float temp, uint8_t battPct) {
  std::string s;
  s.reserve(26);

  // Company ID
  s.push_back((char)0xFF);
  s.push_back((char)0xFF);

  // MAC address (6 bytes)
  const uint8_t* mac = esp_bt_dev_get_address();
  for (int i = 0; i < 6; i++) s.push_back((char)mac[i]);

  // Medicine name (12 bytes, space padded)
  String med = medicineName;
  if (med.length() > 12) med = med.substring(0, 12);
  while ((int)med.length() < 12) med += ' ';
  s.append(med.c_str(), 12);

  // Temperature as signed int16 big-endian (0.01 C)
  int16_t t100 = (int16_t)(temp * 100.0f);
  s.push_back((char)((t100 >> 8) & 0xFF));
  s.push_back((char)(t100 & 0xFF));

  // Battery %
  if (battPct > 100) battPct = 100;
  s.push_back((char)battPct);

  // Movement flags (bit 0 = moving, always 0 since no motion detection)
  s.push_back((char)0x00);

  // Sequence number (uint16 big-endian)
  s.push_back((char)((sequenceNumber >> 8) & 0xFF));
  s.push_back((char)(sequenceNumber & 0xFF));

  return s;
}

static void updateAdvertising(float temp, uint8_t battPct) {
  // Advertising packet: flags + name "MED_TAG"
  BLEAdvertisementData ad;
  ad.setFlags(0x06);
  ad.setName("MED_TAG");

  // Scan response: manufacturer data with sensor values
  BLEAdvertisementData sd;
  sd.setManufacturerData(buildMfgData(temp, battPct));

  pAdvertising->stop();
  pAdvertising->setAdvertisementData(ad);
  pAdvertising->setScanResponseData(sd);
  pAdvertising->start();
}

static void drawDisplay(float temp, uint8_t battPct) {
  StickCP2.Display.fillScreen(BLACK);
  StickCP2.Display.setCursor(0, 0);
  StickCP2.Display.println(medicineName);
  StickCP2.Display.print("T:");
  StickCP2.Display.print(temp, 2);
  StickCP2.Display.println("C");
  StickCP2.Display.print("B:");
  StickCP2.Display.print(battPct);
  StickCP2.Display.println("%");
  StickCP2.Display.print("Seq:");
  StickCP2.Display.println(sequenceNumber);
}

void setup() {
  auto cfg = M5.config();
  StickCP2.begin(cfg);
  StickCP2.Display.setBrightness(30);
  StickCP2.Display.setRotation(1);
  StickCP2.Display.fillScreen(BLACK);
  StickCP2.Display.setTextSize(2);
  StickCP2.Display.setCursor(0, 0);
  StickCP2.Display.println("Medicine Tag");
  StickCP2.Display.println("Starting...");

  Serial.begin(115200);
  Serial.println("Starting BLE Medicine Tag");

  // Init BLE once — no more deinit/reinit every loop
  BLEDevice::init("MED_TAG");
  pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->setMinInterval(1600);  // 1000ms interval
  pAdvertising->setMaxInterval(1600);
}

void loop() {
  StickCP2.update();

  float tempFloat = 0;
  StickCP2.Imu.getTemp(&tempFloat);
  uint8_t batteryLevel = StickCP2.Power.getBatteryLevel();

  // Button A — toggle medicine name
  if (StickCP2.BtnA.wasPressed()) {
    medicineName = (medicineName == "PANADOL") ? "AMOXICILLIN" : "PANADOL";
    Serial.printf("Medicine changed: %s\n", medicineName.c_str());
  }

  updateAdvertising(tempFloat, batteryLevel);
  sequenceNumber++;

  drawDisplay(tempFloat, batteryLevel);

  Serial.printf("Broadcasting - Med: %s | Temp: %.2fC | Bat: %d%% | Seq: %d\n",
                medicineName.c_str(), tempFloat, batteryLevel, sequenceNumber);

  delay(10000);
}
