#pragma once

#include <Arduino.h>

enum class WifiSessionReason {
    None,
    Manual,
    LostBle,
    TempAlert,
    PeriodicSync
};

// Initialize Wi-Fi / MQTT module state
void initWifiModule(const char* tagId);

// Call frequently in loop
void wifiTask();

// Start a 30-second Wi-Fi session manually
void startWifiSession(WifiSessionReason reason);

// Stop Wi-Fi session manually and return to BLE-only mode
void stopWifiSession();

// MQTT publish helper for emergency/status messages
bool publishEmergencyStatus(const String& message);

// Connection state helpers
bool isWifiSessionActive();
bool isWifiConnected();
bool isMqttConnected();