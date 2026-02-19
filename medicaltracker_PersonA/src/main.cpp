#include "ble.h"
#include "mac.h"
#include "med.h"
#include "temp.h"
#include "battery.h"
#include "movement.h"

#include <Arduino.h>
#include <M5Unified.h>

void drawM5Screen() {
  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(1);

  M5.Display.println("BLE ADV OK");
  M5.Display.printf("MAC:\n%s\n", getMacString().c_str());
  M5.Display.printf("MED:%s\n", getMedicineName().c_str());
  M5.Display.printf("T:%.2fC\n", getTemperature());
  M5.Display.printf("B:%u%%\n", getBatteryPercent());
  M5.Display.printf("Move:%s\n", isMoving() ? "MOVING" : (isStationary() ? "STATIONARY" : "IDLE"));
}

void drawSerial() {
  Serial.printf("MAC: %s\n", getMacString().c_str());
  Serial.printf("MED: %s\n", getMedicineName().c_str());
  Serial.printf("Temp(C): %.2f\n", getTemperature());
  Serial.printf("Bat(V): %.3f  Bat(%%): %u\n", getBatteryVoltage(), getBatteryPercent());
  Serial.printf("Move: %s  |a|=%.2fg\n", isMoving() ? "MOVING" : (isStationary() ? "STATIONARY" : "IDLE"), getAccelMagnitude());
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.begin(115200);
  delay(3000);

  initTemp();
  initBattery();
  initMovement();

  setAdvertisedTemperature(getTemperature());
  setAdvertisedBatteryPercent(getBatteryPercent());
  setAdvertisedMoving(isMoving());
  setAdvertisedStationary(isStationary());

  initBLE();

  drawM5Screen();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

  bool bleDirty = false;
  bool displayDirty = false;

  if (M5.BtnA.wasPressed()) {
    toggleMedicine();
    bleDirty = true;
    displayDirty = true;
    Serial.printf("[%lu] MED changed: %s\n", millis(), getMedicineName().c_str());
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== STATUS ===");
    drawSerial();
  }

  if (tempTask()) {
    setAdvertisedTemperature(getTemperature());
    bleDirty = true;
    displayDirty = true;
  }

  if (batteryTask()) {
    setAdvertisedBatteryPercent(getBatteryPercent());
    bleDirty = true;
    displayDirty = true;
  }

  if (movementTask()) {
    setAdvertisedMoving(isMoving());
    setAdvertisedStationary(isStationary());
    bleDirty = true;
    displayDirty = true;
  }

  if (bleDirty) updateAdvertising();
  if (displayDirty) drawM5Screen();
  
  delay(10);
}