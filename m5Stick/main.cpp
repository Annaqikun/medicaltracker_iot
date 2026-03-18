#include <Arduino.h>
#include <M5Unified.h>
#include "ble.h"
#include "mac.h"
#include "med.h"
#include "temp.h"
#include "battery.h"
#include "movement.h"
#include "wifi_manager.h"
#include "ble_ack.h"

static const char* TAG_ID = "m5tag01";  // change this for each device

void drawSerial() {
  Serial.printf("MAC: %s\n", getMacString().c_str());
  Serial.printf("MED: %s\n", getMedicineName().c_str());
  Serial.printf("Temp(C): %.2f\n", getTemperature());
  Serial.printf("Bat(V): %.3f  Bat(%%): %u\n", getBatteryVoltage(), getBatteryPercent());
  Serial.printf("Move: %s  |a|=%.2fg\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY", getAccelMagnitude());
}

void setup() {
  auto cfg = M5.config();
  cfg.internal_spk = true;
  M5.begin(cfg);

  M5.Speaker.begin();
  M5.Speaker.setVolume(128);
  M5.Speaker.setAllChannelVolume(255);
  M5.Speaker.setChannelVolume(0, 255);

  Serial.begin(115200);
  delay(3000);

  initTemp();
  initBattery();
  initMovement();

  setAdvertisedTemperature(getTemperature());
  setAdvertisedBatteryPercent(getBatteryPercent());
  setAdvertisedMoving(isCurrentlyMoving());
  setAdvertisedStationary(isCurrentlyStationary());

  initBLE();
  initWifiModule(TAG_ID);
  initBleAckTracker();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

  bool bleDirty = false;

  wifiTask();

  if (M5.BtnA.wasPressed()) {
    Serial.println("[MAIN] Manual BLE ack test");
    recordBleAck();
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== START WIFI SESSION ===");
    startWifiSession(WifiSessionReason::Manual);
  }

  if (tempTask()) {
    setAdvertisedTemperature(getTemperature());
    bleDirty = true;
  }

  if (batteryTask()) {
    setAdvertisedBatteryPercent(getBatteryPercent());
    bleDirty = true;
  }

  if (movementTask()) {
    setAdvertisedMoving(isCurrentlyMoving());
    setAdvertisedStationary(isCurrentlyStationary());
    bleDirty = true;
  }

  if (!isWifiSessionActive() && shouldTriggerLostBleFailover()) {
    Serial.println("[MAIN] Lost BLE detected -> start Wi-Fi failover");
    startWifiSession(WifiSessionReason::LostBle);
  }

  if (bleDirty && !isWifiSessionActive()) {
    updateAdvertising();
  }
  
  delay(10);
}
