#include "wifi_manager.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <M5Unified.h>
#include "temp.h"
#include "battery.h"
#include "timeSync.h"

extern const uint8_t certs_ca_crt_start[] asm("_binary_certs_ca_crt_start");  
extern const uint8_t certs_ca_crt_end[]   asm("_binary_certs_ca_crt_end");  // not used as of now

static const char* WIFI_SSID = "azrylaptop";
static const char* WIFI_PASSWORD = "azryhome1234";

static IPAddress MQTT_IP(192, 168, 137, 1);  // change this to your MQTT broker's IP address
static const uint16_t MQTT_PORT = 8883;
static const char* MQTT_PASSWORD = "password000";  // change this for each M5Stick

static const unsigned long WIFI_SESSION_DURATION_MS = 30000;
static const unsigned long WIFI_RETRY_INTERVAL_MS = 3000;
static const unsigned long MQTT_RETRY_INTERVAL_MS = 3000;

static String currentTagId;

static WifiSessionReason currentSessionReason = WifiSessionReason::None;

// INTERNAL STATE
static WiFiClientSecure wifiClientSecure;
static PubSubClient mqttClient(wifiClientSecure);

static bool wifiSessionActive = false;
static unsigned long wifiSessionStartMs = 0;
static unsigned long lastWifiRetryMs = 0;
static unsigned long lastMqttRetryMs = 0;

// HELPER: enum -> readable text
static const char* reasonToString(WifiSessionReason reason) {
    switch (reason) {
        case WifiSessionReason::Manual:
            return "manual";
        case WifiSessionReason::LostBle:
            return "lost_ble";
        case WifiSessionReason::TempAlert:
            return "temp_alert";
        case WifiSessionReason::PeriodicSync:
            return "periodic_sync";
        default:
            return "unknown";
    }
}

// PAYLOAD HELPERS
static String makePayload(const char* id, const char* key, const char* value) {
    return "{\"id\":\"" + String(id) + "\",\"" + String(key) + "\":\"" + String(value) + "\"}";
}

static String makeStatusPayload(const char* statusText) {
    String payload = "{";
    payload += "\"id\":\"" + currentTagId + "\",";
    payload += "\"status\":\"" + String(statusText) + "\",";
    payload += "\"temp_c\":" + String(getTemperature(), 2) + ",";
    payload += "\"battery_percent\":" + String(getBatteryPercent());
    payload += "}";

    return payload;
}

// TOPIC HELPERS
static String getEmergencyTopic() {
    return "hospital/medicine/emergency/" + currentTagId;
}

static String getCommandTopic() {
    return "hospital/medicine/command/" + currentTagId;
}

static String getAckTopic() {
    return "hospital/medicine/ack/" + currentTagId;
}

// MQTT CALLBACK
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String topicStr = String(topic);
    String message;

    // convert payload to readable message
    for (unsigned int i = 0; i < length; i++) {
        message += (char)payload[i];
    }

    Serial.println("========== MQTT MESSAGE RECEIVED ==========");
    Serial.printf("Topic: %s\n", topicStr.c_str());
    Serial.printf("Payload: %s\n", message.c_str());

    if (topicStr == getCommandTopic()) {
        if (message == "find") {
            Serial.println("[MQTT] FIND command received");

            // Buzzer response
            M5.Speaker.tone(2000, 500);
            delay(200);
            M5.Speaker.tone(2000, 500);

            // Send acknowledgement
            String ackPayload = makePayload(currentTagId.c_str(), "status", "find_received");
            mqttClient.publish(getAckTopic().c_str(), ackPayload.c_str());

            Serial.println("[MQTT] Sent ACK for find command");
        } else {
            Serial.println("[MQTT] Unknown command received");
        }
    }
}

// CONNECTION HELPERS
static void connectWifiIfNeeded() {
    if (!wifiSessionActive) return;
    if (WiFi.status() == WL_CONNECTED) return;

    unsigned long now = millis();
    if (now - lastWifiRetryMs < WIFI_RETRY_INTERVAL_MS) return;
    lastWifiRetryMs = now;

    Serial.println("[WiFi] Connecting...");
    Serial.printf("[WiFi] SSID: %s\n", WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

static void connectMqttIfNeeded() {
    if (!wifiSessionActive) return;
    if (WiFi.status() != WL_CONNECTED) return;
    if (mqttClient.connected()) return;

    unsigned long now = millis();
    if (now - lastMqttRetryMs < MQTT_RETRY_INTERVAL_MS) return;
    lastMqttRetryMs = now;

    String clientId = "M5StickCPlus-" + currentTagId;

    Serial.println("[MQTT] Connecting...");
    Serial.printf("[MQTT] Broker: %s:%u\n", MQTT_IP.toString().c_str(), MQTT_PORT);

    bool timeOk = syncTimeWithNtp();
    if (!timeOk) {
        Serial.println("[TIME] Cannot start TLS MQTT without valid time");
        return;
    }

    wifiClientSecure.setInsecure();  // TLS encrypted, skip cert verify (ESP32 mbedTLS compat)

    if (!mqttClient.connect(clientId.c_str(), currentTagId.c_str(), MQTT_PASSWORD)) {
        Serial.printf("[MQTT] Connect failed, rc=%d\n", mqttClient.state());
        return;
    }

    Serial.println("[MQTT] Connected");

    bool subscribed = mqttClient.subscribe(getCommandTopic().c_str());
    Serial.printf("[MQTT] Subscribe to %s => %s\n",
                  getCommandTopic().c_str(),
                  subscribed ? "OK" : "FAILED");

    const char* statusText = "wifi_mqtt_connected";

    if (currentSessionReason == WifiSessionReason::LostBle) {
        statusText = "lost_ble";
    } else if (currentSessionReason == WifiSessionReason::TempAlert) {
        statusText = "temp_high";
    } else if (currentSessionReason == WifiSessionReason::PeriodicSync) {
        statusText = "periodic_sync";
    }

    String mqttPayload = makeStatusPayload(statusText);
    bool published = mqttClient.publish(getEmergencyTopic().c_str(), mqttPayload.c_str());
    Serial.printf("[MQTT] Published status payload => %s\n", published ? "OK" : "FAILED");
}

// PUBLIC API
void initWifiModule(const char* tagId) {
    currentTagId = tagId;

    wifiClientSecure.setCACert((const char*)certs_ca_crt_start);

    mqttClient.setServer(MQTT_IP, MQTT_PORT);
    mqttClient.setBufferSize(512);
    mqttClient.setCallback(mqttCallback);

    WiFi.mode(WIFI_OFF);

    Serial.println("[WiFiModule] Initialized");
    Serial.printf("[WiFiModule] Tag ID: %s\n", currentTagId.c_str());
    Serial.printf("[WiFiModule] Emergency topic: %s\n", getEmergencyTopic().c_str());
    Serial.printf("[WiFiModule] Command topic: %s\n", getCommandTopic().c_str());
    Serial.printf("[WiFiModule] Ack topic: %s\n", getAckTopic().c_str());
}

void wifiTask() {
    if (!wifiSessionActive) {
        return;
    }

    if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
        connectMqttIfNeeded();
    }

    if (WiFi.status() != WL_CONNECTED) {
        connectWifiIfNeeded();
    }

    if (mqttClient.connected()) {
        mqttClient.loop();
    }

    if (millis() - wifiSessionStartMs >= WIFI_SESSION_DURATION_MS) {
        Serial.println("[WiFiModule] 30-second session ended");
        stopWifiSession();
    }
}

void startWifiSession(WifiSessionReason reason) {
    if (wifiSessionActive) {
        Serial.println("[WiFiModule] Session already active");
        return;
    }

    currentSessionReason = reason;
    wifiSessionActive = true;
    wifiSessionStartMs = millis();
    lastWifiRetryMs = 0;
    lastMqttRetryMs = 0;

    Serial.println("[WiFiModule] Starting Wi-Fi session");
    Serial.printf("[WiFiModule] Using Tag ID: %s\n", currentTagId.c_str());
    Serial.printf("[WiFiModule] Reason: %s\n", reasonToString(currentSessionReason));

    connectWifiIfNeeded();
}

void stopWifiSession() {
    if (mqttClient.connected()) {
        mqttClient.disconnect();
        Serial.println("[MQTT] Disconnected");
    }

    if (WiFi.status() == WL_CONNECTED) {
        WiFi.disconnect(true, true);
        Serial.println("[WiFi] Disconnected");
    }

    WiFi.mode(WIFI_OFF);
    wifiSessionActive = false;
    currentSessionReason = WifiSessionReason::None;

    Serial.println("[WiFiModule] Returned to BLE-only mode");
}

bool publishEmergencyStatus(const String& message) {
    if (!mqttClient.connected()) {
        Serial.println("[MQTT] Publish failed: not connected");
        return false;
    }

    String emergencypayload = makePayload(currentTagId.c_str(), "message", message.c_str());
    bool ok = mqttClient.publish(getEmergencyTopic().c_str(), emergencypayload.c_str());

    Serial.printf("[MQTT] Publish emergency => %s\n", ok ? "OK" : "FAILED");
    return ok;
}

bool isWifiSessionActive() {
    return wifiSessionActive;
}

bool isWifiConnected() {
    return WiFi.status() == WL_CONNECTED;
}

bool isMqttConnected() {
    return mqttClient.connected();
}

WifiSessionReason getCurrentWifiSessionReason() {
    return currentSessionReason;
}