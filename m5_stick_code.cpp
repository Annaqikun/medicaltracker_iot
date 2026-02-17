#include <M5StickCPlus2.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <BLEAdvertising.h>

uint16_t sequenceNumber = 0;

struct StatusFlags {
  bool moving : 1;
  bool tempAlert : 1;
  bool wifiActive : 1;
  uint8_t reserved : 5;
};

void setup() {
  auto cfg = M5.config();
  StickCP2.begin(cfg);
  StickCP2.Display.setBrightness(30);
  StickCP2.Display.setRotation(1);
  StickCP2.Display.fillScreen(BLACK);
  StickCP2.Display.setTextSize(2);
  StickCP2.Display.setCursor(0, 0);
  StickCP2.Display.println("Medicine Tag");
  StickCP2.Display.println("Broadcasting");
  
  Serial.begin(115200);
  Serial.println("Starting BLE Medicine Tag - Broadcast Mode");
}

void loop() {
  StickCP2.update();
  
  float tempFloat = 0;
  StickCP2.Imu.getTemp(&tempFloat);
  int16_t temperature = (int16_t)(tempFloat * 100);
  
  uint8_t batteryLevel = StickCP2.Power.getBatteryLevel();
  
  StatusFlags flags = {0};
  flags.moving = false;
  flags.tempAlert = false;
  flags.wifiActive = false;
  
  BLEDevice::deinit(false);
  
  char deviceName[32];
  sprintf(deviceName, "MT%d_%d_%d", temperature, batteryLevel, sequenceNumber);
  
  BLEDevice::init(deviceName);

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();

  // Put device name in advertisement packet (not just scan response)
  // so Pico W can read it without needing active scan responses
  BLEAdvertisementData advData;
  advData.setName(deviceName);
  pAdvertising->setAdvertisementData(advData);

  pAdvertising->start();
  
  sequenceNumber++;
  
  StickCP2.Display.fillScreen(BLACK);
  StickCP2.Display.setCursor(0, 0);
  StickCP2.Display.println("MediTag-001");
  StickCP2.Display.print("Temp: ");
  StickCP2.Display.print(temperature / 100.0);
  StickCP2.Display.println("C");
  StickCP2.Display.print("Batt: ");
  StickCP2.Display.print(batteryLevel);
  StickCP2.Display.println("%");
  StickCP2.Display.print("Seq: ");
  StickCP2.Display.println(sequenceNumber);
  
  Serial.print("Broadcasting - Temp: ");
  Serial.print(temperature / 100.0);
  Serial.print("°C, Battery: ");
  Serial.print(batteryLevel);
  Serial.print("%, Seq: ");
  Serial.println(sequenceNumber);
  Serial.print("Device Name: ");
  Serial.println(deviceName);
  
  delay(10000);
}