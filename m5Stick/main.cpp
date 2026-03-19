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

bool findMeActive = false;

void drawM5Screen() {
  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);

  WifiSessionReason reason = getCurrentWifiSessionReason();

  if (findMeActive) {
    // FIND ME mode
    M5.Display.setTextSize(3);
    M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
    M5.Display.println("FIND ME!");
    M5.Display.println();
    M5.Display.setTextSize(2);
    M5.Display.println(" /\\_/\\");
    M5.Display.println("( o.o )");
    M5.Display.println(" > ^ <");
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.println();
    M5.Display.println("  I'm here!");
  } else if (reason == WifiSessionReason::LostBle) {
    // LOST BLE mode
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.println("LOST BLE!");
    M5.Display.println();
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.println("No scanner nearby");
    M5.Display.println("WiFi fallback active");
    M5.Display.println();
    M5.Display.printf("WiFi:%s\n", isWifiConnected() ? "ON" : "OFF");
    M5.Display.printf("MQTT:%s\n", isMqttConnected() ? "ON" : "OFF");
    M5.Display.printf("T:%.2fC  B:%u%%\n", getTemperature(), getBatteryPercent());
  } else if (reason == WifiSessionReason::TempAlert) {
    // TEMP ALERT mode
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.println("TEMP HIGH!");
    M5.Display.println();
    M5.Display.setTextSize(3);
    M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
    M5.Display.printf("%.1fC\n", getTemperature());
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.println();
    M5.Display.println("Alert sent to server");
    M5.Display.printf("WiFi:%s MQTT:%s\n", isWifiConnected() ? "ON" : "OFF", isMqttConnected() ? "ON" : "OFF");
  } else {
    // DEFAULT mode
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.println("BLE ADV OK");
    M5.Display.printf("MAC:\n%s\n", getMacString().c_str());
    M5.Display.printf("MED:%s\n", getMedicineName().c_str());
    M5.Display.printf("T:%.2fC\n", getTemperature());
    M5.Display.printf("B:%u%%\n", getBatteryPercent());
    M5.Display.printf("Move:%s\n", isCurrentlyMoving() ? "MOVING" : "STATIONARY");
    M5.Display.printf("WiFi:%s\n", isWifiConnected() ? "ON" : "OFF");
    M5.Display.printf("MQTT:%s\n", isMqttConnected() ? "ON" : "OFF");
  }
}

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
  setAdvertisedLowBattery(getBatteryPercent() < 20);

  tempAlertActive = (getTemperature() > 25.0f);

  lastPeriodicSyncMs = millis();

  initBLE();

  initWifiModule(TAG_ID);

  initBleAckTracker();

  drawM5Screen();

  Serial.println("Advertising started");
  drawSerial();
}

void loop() {
  M5.update();
  bool displayDirty = false;

  wifiTask();

  if (M5.BtnA.wasPressed()) {
    Serial.println("[MAIN] Manual BLE ack test");
    recordBleAck();
  }

  {
    static unsigned long lastBtnBMs = 0;
    static int btnBPresses = 0;
    static bool btnBPending = false;

    if (M5.BtnB.wasPressed()) {
      btnBPresses++;
      lastBtnBMs = millis();
      btnBPending = true;
    }

    // After 500ms window, decide: single or double press
    if (btnBPending && (millis() - lastBtnBMs > 500)) {
      if (btnBPresses >= 2) {
        Serial.println("=== DOUBLE PRESS: TEMP ALERT ===");
        startWifiSession(WifiSessionReason::TempAlert);
      } else {
        Serial.println("=== SINGLE PRESS: LOST BLE ===");
        startWifiSession(WifiSessionReason::LostBle);
      }
      displayDirty = true;
      btnBPresses = 0;
      btnBPending = false;
    }
  }

  if (tempTask()) {
    setAdvertisedTemperature(getTemperature());
    bleDirty = true;

    bool isHighTemp = (getTemperature() > 25.0f);

    if (isHighTemp && !tempAlertActive && !isWifiSessionActive()) {
      Serial.println("[MAIN] High temperature detected -> starting Wi-Fi alert session");
      startWifiSession(WifiSessionReason::TempAlert);
      displayDirty = true;
    }

    tempAlertActive = isHighTemp;
  }

  if (batteryTask()) {
    setAdvertisedBatteryPercent(getBatteryPercent());
    setAdvertisedLowBattery(getBatteryPercent() < 20);
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
    displayDirty = true;
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
  if (displayDirty) drawM5Screen();

  delay(10);
}