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

void drawSerial() {
  Serial.printf("MAC: %s\n", getMacString().c_str());
  Serial.printf("MED: %s\n", getMedicineName().c_str());
  Serial.printf("Temp(C): %.2f\n", getTemperature());
  Serial.printf("Bat(V): %.3f  Bat(%%): %u\n", getBatteryVoltage(), getBatteryPercent());
  Serial.printf("Move: %s  |a|=%.2fg\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY", getAccelMagnitude());
  Serial.printf("Seq: %u\n", getLastSentSeq());
  Serial.printf("WiFi session: %s\n", isWifiSessionActive() ? "ACTIVE" : "INACTIVE");
  Serial.printf("WiFi link: %s\n", isWifiConnected() ? "CONNECTED" : "DISCONNECTED");
  Serial.printf("MQTT: %s\n", isMqttConnected() ? "CONNECTED" : "DISCONNECTED");
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
  setAdvertisedMoving(isCurrentlyMoving());
  setAdvertisedStationary(isCurrentlyStationary());

  initBLE();

  initWifiModule(TAG_ID);

  initBleAckTracker();

  drawM5Screen();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();

  bool bleDirty = false;
  bool displayDirty = false;

  wifiTask();

  if (M5.BtnA.wasPressed()) {
    Serial.println("[MAIN] Manual BLE ack test");
    recordBleAck();
  }

  if (M5.BtnB.wasPressed()) {
    Serial.println("=== START WIFI SESSION ===");
    startWifiSession(WifiSessionReason::Manual);
    displayDirty = true;
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

  if (!isWifiSessionActive() && shouldTriggerLostBleFailover()) {
    Serial.println("[MAIN] Lost BLE detected -> start Wi-Fi failover");
    startWifiSession(WifiSessionReason::LostBle);
  }

  if (bleDirty) updateAdvertising();
  if (displayDirty) drawM5Screen();
  
  delay(10);
}