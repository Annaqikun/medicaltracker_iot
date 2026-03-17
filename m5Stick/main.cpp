#include "ble.h"
#include "mac.h"
#include "hmac.h"
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
  M5.Display.printf("T:%.2fC\n", getTemperature());
  M5.Display.printf("B:%u%%\n", getBatteryPercent());
  M5.Display.printf("Move:%s\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY");
  M5.Display.setTextSize(2);
  M5.Display.println(" /\\_/\\ ");
  M5.Display.println("( o.o )");
  M5.Display.println(" > ^ < ");
}

void drawSerial() {
  Serial.printf("MAC: %s\n", getMacString().c_str());
  Serial.printf("Temp(C): %.2f\n", getTemperature());
  Serial.printf("Bat(V): %.3f  Bat(%%): %u\n", getBatteryVoltage(), getBatteryPercent());
  Serial.printf("Move: %s  |a|=%.2fg\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY", getAccelMagnitude());
  Serial.printf("Seq: %u\n", getLastSentSeq());
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.begin(115200);
  delay(1000);

  // Check if the provisioning script is talking to us over serial.
  // If it sends "PROV_PING", we enter provisioning mode, receive the
  // key, write it to NVS, and reboot. Otherwise we continue normally.
  checkSerialProvisioning();

  // Load HMAC key from NVS — halts if not found
  hmacInit();

  initTemp();
  initBattery();
  initMovement();

  setAdvertisedTemperature(getTemperature());
  setAdvertisedBatteryPercent(getBatteryPercent());
  setAdvertisedMoving(isCurrentlyMoving());
  setAdvertisedStationary(isCurrentlyStationary());

  initBLE();

  drawM5Screen();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

  bool bleDirty = false;
  bool displayDirty = false;

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
    setAdvertisedMoving(isCurrentlyMoving());
    setAdvertisedStationary(isCurrentlyStationary());
    bleDirty = true;
    displayDirty = true;
  }

  if (bleDirty) updateAdvertising();
  if (displayDirty) drawM5Screen();

  delay(10);
}
