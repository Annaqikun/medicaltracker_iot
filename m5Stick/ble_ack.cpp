#include "ble_ack.h"

<<<<<<< HEAD
static const unsigned long BLE_ACK_TIMEOUT_MS = 15000;  // NOTE: Testing value. Change to 5 minutes before demo.
=======
static const unsigned long BLE_ACK_TIMEOUT_MS = 30000;  // NOTE: Testing value. Change to 5 minutes before demo.
>>>>>>> origin/PersonA

static unsigned long trackerStartMs = 0;
static unsigned long lastBleAckMs = 0;

// INTERNAL STATE
static bool bleAckReceived = false;
static bool lostBleState = false;
static bool lostBleFailoverTriggered = false;  // Flag to prevent repeated triggers

void initBleAckTracker() {
    trackerStartMs = millis();
    lastBleAckMs = trackerStartMs;
    bleAckReceived = false;
    lostBleState = false;
    lostBleFailoverTriggered = false;

    Serial.println("[BLE ACK] Tracker initialized");
}

void recordBleAck() {
    lastBleAckMs = millis();
    bleAckReceived = true;
    lostBleState = false;
    lostBleFailoverTriggered = false;

    Serial.printf("[BLE ACK] Ack received at %lu ms\n", lastBleAckMs);
}

bool shouldTriggerLostBleFailover() {
    if (lostBleFailoverTriggered) {
        return false;
    }

<<<<<<< HEAD
    if (millis() - lastBleAckMs >= BLE_ACK_TIMEOUT_MS) {
        lostBleState = true;
        lostBleFailoverTriggered = true;

        Serial.println("[BLE ACK] Ack timeout -> LOST BLE");
        return true;
    }
=======
    if (!bleAckReceived) {
        return false;
    }

    if (millis() - lastBleAckMs >= BLE_ACK_TIMEOUT_MS) {
        lostBleState = true;
        lostBleFailoverTriggered = true;
        Serial.println("[BLE ACK] Ack timeout -> LOST BLE");
        return true;
    }

>>>>>>> origin/PersonA
    return false;
}

unsigned long getMsSinceLastBleAckOrBoot() {
    return millis() - lastBleAckMs;
}

bool hasReceivedBleAck() {
    return bleAckReceived;
}

bool isBleCurrentlyLost() {
    return lostBleState;
}