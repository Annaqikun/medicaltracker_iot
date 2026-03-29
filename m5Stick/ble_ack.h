#pragma once

#include <Arduino.h>


// Initialise the BLE acknowledgement tracker
// Should be called once during system startup
void initBleAckTracker();


// Record that a BLE acknowledgement was received
// (later this will be triggered by a BLE GATT write from the receiver)
void recordBleAck();


// Check whether BLE has been lost due to timeout
// Returns true only once per timeout event
bool shouldTriggerLostBleFailover();


// Returns time elapsed since the last BLE acknowledgement
unsigned long getMsSinceLastBleAckOrBoot();


// Returns true if BLE is currently considered lost
bool isBleCurrentlyLost();


// Returns true once the first BLE acknowledgement has been received
bool hasReceivedBleAck();