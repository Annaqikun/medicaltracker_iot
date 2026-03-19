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

bool bleDirty = false;
static bool tempAlertActive = false;

static const unsigned long PERIODIC_WIFI_SYNC_MS = 1800000; // 30 minutes
static unsigned long lastPeriodicSyncMs = 0;

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
  setAdvertisedLowBattery(getBatteryPercent() < 20);

  tempAlertActive = (getTemperature() > 25.0f);

  lastPeriodicSyncMs = millis();

  initBLE();
  initWifiModule(TAG_ID);
  initBleAckTracker();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

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

    bool isHighTemp = (getTemperature() > 25.0f);

    if (isHighTemp && !tempAlertActive && !isWifiSessionActive()) {
      Serial.println("[MAIN] High temperature detected -> starting Wi-Fi alert session");
      startWifiSession(WifiSessionReason::TempAlert);
    }

    tempAlertActive = isHighTemp;
  }

  if (batteryTask()) {
    setAdvertisedBatteryPercent(getBatteryPercent());
    setAdvertisedLowBattery(getBatteryPercent() < 20);
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

  if (!isWifiSessionActive() && (millis() - lastPeriodicSyncMs >= PERIODIC_WIFI_SYNC_MS)) {
      Serial.println("[MAIN] 30-minute periodic Wi-Fi sync triggered");
      startWifiSession(WifiSessionReason::PeriodicSync);
      lastPeriodicSyncMs = millis();
  }

  if (bleDirty && !isWifiSessionActive()) {
    updateAdvertising();
    bleDirty = false;
  }
  
  delay(10);
}
