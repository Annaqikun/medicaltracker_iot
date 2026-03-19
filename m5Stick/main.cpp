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

<<<<<<< HEAD
static const char* TAG_ID = "m5tag";  // change this for each device

void drawM5Screen() {
  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(1);

  M5.Display.println("BLE ADV OK");
  M5.Display.printf("MAC:\n%s\n", getMacString().c_str());
  M5.Display.printf("MED:%s\n", getMedicineName().c_str());
  M5.Display.printf("T:%.2fC\n", getTemperature());
  M5.Display.printf("B:%u%%\n", getBatteryPercent());
  M5.Display.printf("Move:%s\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY");
  M5.Display.printf("WiFi:%s\n", isWifiConnected() ? "ON" : "OFF");
  M5.Display.printf("MQTT:%s\n", isMqttConnected() ? "ON" : "OFF");
}
=======
static const char* TAG_ID = "m5tag01";  // change this for each device
>>>>>>> origin/PersonA

void drawSerial() {
  Serial.printf("MAC: %s\n", getMacString().c_str());
  Serial.printf("MED: %s\n", getMedicineName().c_str());
  Serial.printf("Temp(C): %.2f\n", getTemperature());
  Serial.printf("Bat(V): %.3f  Bat(%%): %u\n", getBatteryVoltage(), getBatteryPercent());
  Serial.printf("Move: %s  |a|=%.2fg\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY", getAccelMagnitude());
<<<<<<< HEAD
  Serial.printf("Seq: %u\n", getLastSentSeq());
  Serial.printf("WiFi session: %s\n", isWifiSessionActive() ? "ACTIVE" : "INACTIVE");
  Serial.printf("WiFi link: %s\n", isWifiConnected() ? "CONNECTED" : "DISCONNECTED");
  Serial.printf("MQTT: %s\n", isMqttConnected() ? "CONNECTED" : "DISCONNECTED");
=======
>>>>>>> origin/PersonA
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
<<<<<<< HEAD

  initWifiModule(TAG_ID);

  initBleAckTracker();

  drawM5Screen();
=======
  initWifiModule(TAG_ID);
  initBleAckTracker();
>>>>>>> origin/PersonA

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

  bool bleDirty = false;

  wifiTask();

  wifiTask();

  if (M5.BtnA.wasPressed()) {
    Serial.println("[MAIN] Manual BLE ack test");
    recordBleAck();
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== START WIFI SESSION ===");
    startWifiSession(WifiSessionReason::Manual);
<<<<<<< HEAD
    displayDirty = true;
=======
>>>>>>> origin/PersonA
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

<<<<<<< HEAD
  if (bleDirty) updateAdvertising();
  if (displayDirty) drawM5Screen();
=======
  if (bleDirty && !isWifiSessionActive()) {
    updateAdvertising();
  }
>>>>>>> origin/PersonA
  
  delay(10);
}