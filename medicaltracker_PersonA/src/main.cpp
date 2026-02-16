#include <Arduino.h>
#include <M5Unified.h>
#include "ble.h"

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.begin(115200);
  delay(3000);

  initBLE();

  String macStr = getMacString();

  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(1);
  M5.Display.println("BLE ADV OK");
  M5.Display.printf("MAC:\n%s\n", macStr.c_str());
  M5.Display.printf("MED:%s\n", medicineName.c_str());

  Serial.println("Advertising started");
  Serial.print("MAC: ");
  Serial.println(macStr);
  Serial.print("MED: ");
  Serial.println(medicineName);
}

void loop() {
  M5.update();

  if (M5.BtnA.wasPressed()) {
    medicineName = (medicineName == "PANADOL") ? "AMOXICILLIN" : "PANADOL";
    updateAdvertising();
    Serial.printf("[%lu] MED changed: %s\n", millis(), medicineName.c_str());
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== STATUS ===");
    Serial.print("MAC: "); Serial.println(getMacString());
    Serial.print("MED: "); Serial.println(medicineName);
  }

  delay(10);
}
