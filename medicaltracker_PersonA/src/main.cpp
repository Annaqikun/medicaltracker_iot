#include "ble.h"
#include "mac.h"
#include "med.h"
#include "temp.h"

#include <Arduino.h>
#include <M5Unified.h>


void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.begin(115200);
  delay(3000);

  initTemp();
  setAdvertisedTemperature(getTemperature());

  initBLE();

  String macStr = getMacString();

  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(1);
  M5.Display.println("BLE ADV OK");
  M5.Display.printf("MAC:\n%s\n", macStr.c_str());
  M5.Display.printf("MED:%s\n", getMedicineName().c_str());
  M5.Display.printf("T:%.2fC\n", getTemperature());

  Serial.println("Advertising started");
  Serial.print("MAC: "); Serial.println(macStr);
  Serial.print("MED: "); Serial.println(getMedicineName());
  Serial.print("Temp(C): "); Serial.println(getTemperature(), 2);
}

void loop() {
  M5.update();

  if (tempTask()) {
    float t = getTemperature();
    setAdvertisedTemperature(t);
    updateAdvertising();

    M5.Display.clearDisplay();
    M5.Display.setCursor(0, 0);
    M5.Display.println("BLE ADV OK");
    M5.Display.printf("MAC:\n%s\n", getMacString().c_str());
    M5.Display.printf("MED:%s\n", getMedicineName().c_str());
    M5.Display.printf("T:%.2fC\n", t);
  }

  if (M5.BtnA.wasPressed()) {
    toggleMedicine();
    updateAdvertising();
    Serial.printf("[%lu] MED changed: %s\n", millis(), getMedicineName().c_str());
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== STATUS ===");
    Serial.print("MAC: "); Serial.println(getMacString());
    Serial.print("MED: "); Serial.println(getMedicineName());
    Serial.print("Temp: "); Serial.println(getTemperature(), 2);
  }

  delay(10);
}