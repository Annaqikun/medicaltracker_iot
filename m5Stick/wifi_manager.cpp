#include "wifi_manager.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <M5Unified.h>
#include "temp.h"
#include "battery.h"
#include "timeSync.h"
<<<<<<< HEAD

extern const uint8_t certs_ca_crt_start[] asm("_binary_certs_ca_crt_start");  
extern const uint8_t certs_ca_crt_end[]   asm("_binary_certs_ca_crt_end");  // not used as of now

static const char* WIFI_SSID = "azrylaptop";
static const char* WIFI_PASSWORD = "azryhome1234";

static IPAddress MQTT_IP(192, 168, 137, 1);  // change this to your MQTT broker's IP address
=======
#include "ble.h"

extern const uint8_t certs_ca_crt_start[] asm("_binary_certs_ca_crt_start");

static const char* WIFI_SSID = "WY16";
static const char* WIFI_PASSWORD = "Tyrande69";

static IPAddress MQTT_IP(172, 20, 10, 4);  // change this to your MQTT broker's IP address
>>>>>>> origin/PersonA
static const uint16_t MQTT_PORT = 8883;
static const char* MQTT_PASSWORD = "password000";  // change this for each M5Stick

static const unsigned long WIFI_SESSION_DURATION_MS = 30000;
static const unsigned long WIFI_RETRY_INTERVAL_MS = 3000;
static const unsigned long MQTT_RETRY_INTERVAL_MS = 3000;

static String currentTagId;
<<<<<<< HEAD

=======
>>>>>>> origin/PersonA
static WifiSessionReason currentSessionReason = WifiSessionReason::None;

// INTERNAL STATE
static WiFiClientSecure wifiClientSecure;
static PubSubClient mqttClient(wifiClientSecure);

static bool wifiSessionActive = false;
static unsigned long wifiSessionStartMs = 0;
static unsigned long lastWifiRetryMs = 0;
static unsigned long lastMqttRetryMs = 0;

<<<<<<< HEAD
=======
static bool pendingFindBuzz = false;
static bool pendingFindAck = false;

>>>>>>> origin/PersonA
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
<<<<<<< HEAD
=======
    message.reserve(length);
>>>>>>> origin/PersonA

    // convert payload to readable message
    for (unsigned int i = 0; i < length; i++) {
        message += (char)payload[i];
    }

    Serial.println("========== MQTT MESSAGE RECEIVED ==========");
    Serial.printf("Topic: %s\n", topicStr.c_str());
    Serial.printf("Payload: %s\n", message.c_str());

<<<<<<< HEAD
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
=======
    if (topicStr != getCommandTopic()) {
        return;
    }

    if (message == "find") {
        Serial.println("[MQTT] FIND command received");
        pendingFindBuzz = true;
        pendingFindAck = true;
    } else {
        Serial.println("[MQTT] Unknown command received");
>>>>>>> origin/PersonA
    }
}

// CONNECTION HELPERS
static void connectWifiIfNeeded() {
<<<<<<< HEAD
    if (!wifiSessionActive) return;
    if (WiFi.status() == WL_CONNECTED) return;

    unsigned long now = millis();
    if (now - lastWifiRetryMs < WIFI_RETRY_INTERVAL_MS) return;
=======
    if (!wifiSessionActive || WiFi.status() == WL_CONNECTED) {
        return;
    }

    unsigned long now = millis();
    if (now - lastWifiRetryMs < WIFI_RETRY_INTERVAL_MS) {
        return;
    }
>>>>>>> origin/PersonA
    lastWifiRetryMs = now;

    Serial.println("[WiFi] Connecting...");
    Serial.printf("[WiFi] SSID: %s\n", WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

static void connectMqttIfNeeded() {
<<<<<<< HEAD
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
=======
    if (!wifiSessionActive || WiFi.status() != WL_CONNECTED || mqttClient.connected()) {
        return;
    }

    unsigned long now = millis();
    if (now - lastMqttRetryMs < MQTT_RETRY_INTERVAL_MS) {
        return;
    }
    lastMqttRetryMs = now;

    Serial.println("[MQTT] Connecting...");
    Serial.printf("[MQTT] Broker: %s:%u\n", MQTT_IP.toString().c_str(), MQTT_PORT);

    if (!syncTimeWithNtp()) {
>>>>>>> origin/PersonA
        Serial.println("[TIME] Cannot start TLS MQTT without valid time");
        return;
    }

<<<<<<< HEAD
    wifiClientSecure.setInsecure();  // TLS encrypted, skip cert verify (ESP32 mbedTLS compat)

    if (mqttClient.connect(clientId.c_str(), currentTagId.c_str(), MQTT_PASSWORD)) {
        Serial.println("[MQTT] Connected");

        bool ok = mqttClient.subscribe(getCommandTopic().c_str());
        Serial.printf("[MQTT] Subscribe to %s => %s\n", getCommandTopic().c_str(), ok ? "OK" : "FAILED");
        
        const char* statusText;
        if (currentSessionReason == WifiSessionReason::LostBle) {
            statusText = "lost_ble";
        } else {
            statusText = "wifi_mqtt_connected";
        }

        String mqttPayload =  makeStatusPayload(statusText);
        bool yup = mqttClient.publish(getEmergencyTopic().c_str(), mqttPayload.c_str());

        Serial.printf("[MQTT] Published status payload => %s\n", yup ? "OK" : "FAILED");
        Serial.printf("[MQTT] Payload: %s\n", mqttPayload.c_str());
    } else {
        Serial.printf("[MQTT] Connect failed, rc=%d\n", mqttClient.state());
    }
=======
    char clientId[32];
    snprintf(clientId, sizeof(clientId), "M5StickCPlus-%s", currentTagId.c_str());

    if (!mqttClient.connect(clientId, currentTagId.c_str(), MQTT_PASSWORD)) {
        Serial.printf("[MQTT] Connect failed, rc=%d\n", mqttClient.state());
        return;
    }

    Serial.println("[MQTT] Connected");

    bool subscribed = mqttClient.subscribe(getCommandTopic().c_str());
    Serial.printf("[MQTT] Subscribe to %s => %s\n",
                  getCommandTopic().c_str(),
                  subscribed ? "OK" : "FAILED");

    const char* statusText =
        (currentSessionReason == WifiSessionReason::LostBle)
            ? "lost_ble"
            : "wifi_mqtt_connected";

    String mqttPayload = makeStatusPayload(statusText);
    bool published = mqttClient.publish(getEmergencyTopic().c_str(), mqttPayload.c_str());
    
    Serial.printf("[MQTT] Published status payload => %s\n", published ? "OK" : "FAILED");
}

static void handlePendingFindCommand() {
    if (!pendingFindBuzz) {
        return;
    }

    // SEND ACK FIRST
    if (pendingFindAck) {
        String ackPayload = makePayload(currentTagId.c_str(), "status", "find_received");

        bool ok = mqttClient.publish(getAckTopic().c_str(), ackPayload.c_str());
        Serial.printf("[MQTT] Published ACK => %s\n", ok ? "OK" : "FAILED");

        pendingFindAck = false;
    }

    // THEN DO BUZZER
    Serial.println("[BUZZER] Starting 5-second alert");
    Serial.println("[BUZZER] Press BtnA to stop early");

    unsigned long buzzStart = millis();
    while (millis() - buzzStart < 5000) {
        M5.update();

        if (M5.BtnA.wasPressed()) {
            Serial.println("[BUZZER] Stopped early by BtnA");
            break;
        }
        M5.Speaker.tone(2000, 100);
        delay(100);
    }
    M5.Speaker.stop();
    Serial.println("[BUZZER] Alert finished");

    pendingFindBuzz = false;
>>>>>>> origin/PersonA
}

// PUBLIC API
void initWifiModule(const char* tagId) {
    currentTagId = tagId;

    wifiClientSecure.setCACert((const char*)certs_ca_crt_start);

    mqttClient.setServer(MQTT_IP, MQTT_PORT);
<<<<<<< HEAD
    mqttClient.setBufferSize(512);
    mqttClient.setCallback(mqttCallback);
=======
    mqttClient.setCallback(mqttCallback);
    mqttClient.setBufferSize(128);
>>>>>>> origin/PersonA

    WiFi.mode(WIFI_OFF);

    Serial.println("[WiFiModule] Initialized");
    Serial.printf("[WiFiModule] Tag ID: %s\n", currentTagId.c_str());
<<<<<<< HEAD
    Serial.printf("[WiFiModule] Emergency topic: %s\n", getEmergencyTopic().c_str());
    Serial.printf("[WiFiModule] Command topic: %s\n", getCommandTopic().c_str());
    Serial.printf("[WiFiModule] Ack topic: %s\n", getAckTopic().c_str());
=======
>>>>>>> origin/PersonA
}

void wifiTask() {
    if (!wifiSessionActive) {
        return;
    }

<<<<<<< HEAD
    if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
        connectMqttIfNeeded();
    }

=======
>>>>>>> origin/PersonA
    if (WiFi.status() != WL_CONNECTED) {
        connectWifiIfNeeded();
    }

<<<<<<< HEAD
    if (mqttClient.connected()) {
        mqttClient.loop();
=======
    if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
        connectMqttIfNeeded();
    }

    if (mqttClient.connected()) {
        mqttClient.loop();
        handlePendingFindCommand();
>>>>>>> origin/PersonA
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

<<<<<<< HEAD
=======
    stopBLE();

>>>>>>> origin/PersonA
    currentSessionReason = reason;
    wifiSessionActive = true;
    wifiSessionStartMs = millis();
    lastWifiRetryMs = 0;
    lastMqttRetryMs = 0;
<<<<<<< HEAD
=======
    pendingFindBuzz = false;
    pendingFindAck = false;
>>>>>>> origin/PersonA

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
<<<<<<< HEAD
    wifiSessionActive = false;
    currentSessionReason = WifiSessionReason::None;

    Serial.println("[WiFiModule] Returned to BLE-only mode");
=======

    wifiSessionActive = false;
    currentSessionReason = WifiSessionReason::None;
    pendingFindBuzz = false;
    pendingFindAck = false;

    Serial.println("[WiFiModule] Rebooting to restore clean BLE state...");
    delay(500);
    ESP.restart();
>>>>>>> origin/PersonA
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