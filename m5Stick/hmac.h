#pragma once

#include <Arduino.h>
#include <stdint.h>

// Check for provisioning commands on Serial.
// Call early in setup(), before hmacInit().
// If the provisioning host sends "PROV_PING", this responds with the MAC
// and waits to receive a 32-byte key, writes it to NVS, then reboots.
void checkSerialProvisioning();

// Read HMAC key from NVS at boot. Halts if no key found.
void hmacInit();

// Compute HMAC-SHA256 over data[0..len-1] and write the first 4 bytes to out4bytes.
void computeHmac(const uint8_t* data, size_t len, uint8_t* out4bytes);
